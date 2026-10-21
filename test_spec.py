#!/usr/bin/env python3
"""The published protocol (docs/spec, Wave 4, owner P1-P4) against the kit that implements it.

    python3 test_spec.py

The spec is the prose (PROTOCOL.md), a JSON Schema and conformance vectors. These tests keep the three and the
kit saying the same thing: every vector gets the kit's verdict, the JSON Schema gets the verdict it claims, and the
schema's limits and shapes are the kit's own constants. Standard library only: the JSON Schema is checked by a
small checker below that refuses any keyword it does not implement, rather than skipping it.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE / "plugin" / "kit"
sys.path.insert(0, str(KIT))

from overture import fold as F  # noqa: E402
from overture import names as NM  # noqa: E402
from overture import schema as S  # noqa: E402
from overture import symbols as SY  # noqa: E402
from overture.store import Store, StoreError, utc_now  # noqa: E402

SPEC = HERE / "docs" / "spec"
SCHEMA = json.loads((SPEC / "overture-protocol-1.schema.json").read_text(encoding="utf-8"))
RECORDS = json.loads((SPEC / "vectors" / "records.json").read_text(encoding="utf-8"))["records"]
SEQUENCES = json.loads((SPEC / "vectors" / "store.json").read_text(encoding="utf-8"))["sequences"]
RULINGS = json.loads((SPEC / "vectors" / "rulings.json").read_text(encoding="utf-8"))["rulings"]
PROSE = (SPEC / "PROTOCOL.md").read_text(encoding="utf-8")
CORE = ("question", "answer", "lock", "anchor")


# -- a JSON Schema 2020-12 checker for exactly the keywords the spec's schema uses ------------------------------

ANNOTATIONS = frozenset({"$schema", "$id", "$defs", "title", "description"})
TYPES = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
         "string": lambda v: isinstance(v, str), "null": lambda v: v is None, "boolean": lambda v: isinstance(v, bool),
         "integer": lambda v: isinstance(v, int) and not isinstance(v, bool)}


class UnknownKeyword(Exception):
    """The schema uses a keyword this checker does not implement; skipping it would pass what it should refuse."""


def _pattern(p: str) -> re.Pattern:
    # ECMA-262's `$` is the end of the string; Python's also matches before one trailing newline.
    if p.endswith("$") and not p.endswith("\\$"):
        p = p[:-1] + r"\Z"
    return re.compile(p)


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise UnknownKeyword(f"$ref {ref!r}: only local references are implemented")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def json_errors(v: object, sch: dict | bool, root: dict = SCHEMA, at: str = "$") -> list[str]:
    """Every way `v` fails `sch`; empty when it passes."""
    if isinstance(sch, bool):   # `false` refuses any value (a field that must be absent); `true` takes any
        return [] if sch else [f"{at}: not allowed here"]
    errs: list[str] = []
    for kw, arg in sch.items():
        if kw in ANNOTATIONS or kw in ("then", "else"):
            continue
        if kw == "$ref":
            errs += json_errors(v, _resolve(arg, root), root, at)
        elif kw == "type":
            names = arg if isinstance(arg, list) else [arg]
            if not any(TYPES[n](v) for n in names):
                errs.append(f"{at}: not {arg}")
        elif kw == "enum":
            if v not in arg or (isinstance(v, bool) and not any(a is v for a in arg)):
                errs.append(f"{at}: not one of {arg}")
        elif kw == "const":
            if v != arg or isinstance(v, bool) != isinstance(arg, bool):
                errs.append(f"{at}: not {arg!r}")
        elif kw == "pattern":
            if isinstance(v, str) and not _pattern(arg).search(v):
                errs.append(f"{at}: does not match {arg}")
        elif kw in ("minLength", "maxLength"):
            if isinstance(v, str) and (len(v) < arg if kw == "minLength" else len(v) > arg):
                errs.append(f"{at}: {kw} {arg}")
        elif kw in ("minItems", "maxItems"):
            if isinstance(v, list) and (len(v) < arg if kw == "minItems" else len(v) > arg):
                errs.append(f"{at}: {kw} {arg}")
        elif kw == "minimum":
            if TYPES["integer"](v) and v < arg:
                errs.append(f"{at}: below {arg}")
        elif kw == "uniqueItems":
            if arg and isinstance(v, list) and len({json.dumps(x, sort_keys=True) for x in v}) != len(v):
                errs.append(f"{at}: items repeat")
        elif kw == "items":
            if isinstance(v, list):
                for i, x in enumerate(v):
                    errs += json_errors(x, arg, root, f"{at}[{i}]")
        elif kw == "required":
            if isinstance(v, dict):
                errs += [f"{at}: missing {k}" for k in arg if k not in v]
        elif kw == "properties":
            if isinstance(v, dict):
                for k, s in arg.items():
                    if k in v:
                        errs += json_errors(v[k], s, root, f"{at}.{k}")
        elif kw == "additionalProperties":
            if arg is not False:
                raise UnknownKeyword("additionalProperties other than false")
            if isinstance(v, dict):
                errs += [f"{at}: unknown field {k}" for k in sorted(set(v) - set(sch.get("properties", {})))]
        elif kw == "dependentRequired":
            if isinstance(v, dict):
                errs += [f"{at}: {k} needs {d}" for k, ds in arg.items() if k in v for d in ds if d not in v]
        elif kw == "allOf":
            for s in arg:
                errs += json_errors(v, s, root, at)
        elif kw == "anyOf":
            if all(json_errors(v, s, root, at) for s in arg):
                errs.append(f"{at}: matches none of anyOf")
        elif kw == "not":
            if not json_errors(v, arg, root, at):
                errs.append(f"{at}: matches what `not` refuses")
        elif kw == "oneOf":
            n = sum(1 for s in arg if not json_errors(v, s, root, at))
            if n != 1:
                errs.append(f"{at}: matches {n} of oneOf, not exactly one")
        elif kw == "if":
            if not json_errors(v, arg, root, at):
                errs += json_errors(v, sch.get("then", {}), root, at)
            else:
                errs += json_errors(v, sch.get("else", {}), root, at)
        else:
            raise UnknownKeyword(kw)
    return errs


def defs(name: str) -> dict:
    return SCHEMA["$defs"][name]


class CheckerTests(unittest.TestCase):
    def test_the_checker_refuses_a_keyword_it_does_not_implement(self):
        # Catches: a checker that skips what it does not know, so a schema using `format` or `patternProperties`
        # would pass vectors it never checked.
        with self.assertRaises(UnknownKeyword):
            json_errors("x", {"format": "email"})
        with self.assertRaises(UnknownKeyword):
            json_errors({}, {"additionalProperties": {"type": "string"}})

    def test_the_checker_reads_dollar_as_the_end_of_the_string(self):
        # Catches: Python's `$`, which also matches before a trailing newline, so "retry_once\n" passed as an option
        # id under the checker while every ECMA-262 validator refuses it.
        self.assertTrue(json_errors("retry_once\n", defs("optionId")))
        self.assertFalse(json_errors("retry_once", defs("optionId")))


# -- the vectors ----------------------------------------------------------------------------------------------

class RecordVectorTests(unittest.TestCase):
    def test_every_record_vector_gets_the_kits_verdict(self):
        # Catches: a vector the kit disagrees with, so the published spec says one thing and Overture does another.
        for v in RECORDS:
            with self.subTest(v["name"]):
                errs = S.validate(v["record"])
                if v["valid"]:
                    self.assertEqual(errs, [])
                else:
                    self.assertTrue(any(v["reference_error"] in e for e in errs), errs)

    def test_the_json_schema_gets_the_verdict_each_vector_claims(self):
        # Catches: a JSON Schema that refuses a valid record (an adopter's tool then rejects real stores), or one
        # that stops catching what a vector says it catches. A vector the schema cannot catch is marked so, and
        # must really pass it: PROTOCOL.md section 9 lists those checks, and the list stays honest.
        for v in RECORDS:
            with self.subTest(v["name"]):
                errs = json_errors(v["record"], SCHEMA)
                if v["valid"]:
                    self.assertEqual(errs, [])
                elif v["schema_catches"]:
                    self.assertNotEqual(errs, [])
                else:
                    self.assertEqual(errs, [], "marked beyond the schema, but the schema catches it")

    def test_the_vectors_cover_every_kind_and_condition(self):
        # Catches: a kind or a condition kind added to the spec with no valid vector, so nothing pins its shape.
        kinds = {v["record"]["type"] for v in RECORDS if v["valid"]}
        self.assertEqual(kinds, set(CORE))
        conds = {c["kind"] for v in RECORDS if v["valid"] for c in v["record"].get("valid_if", [])}
        self.assertEqual(conds, set(S.VALID_IF_KINDS))


class RulingVectorTests(unittest.TestCase):
    def test_every_ruling_file_vector_gets_folds_verdict(self):
        # Catches: a ruling file the spec calls valid that `fold` and the CI check refuse (or the reverse). The item
        # is taken as known, as rulecheck.py does when it runs without the project's register.
        for v in RULINGS:
            with self.subTest(v["name"]):
                errs = F.check_entry(v["file"], v["ruling"], {v["ruling"].get("item"): {}})
                if v["valid"]:
                    self.assertEqual(errs, [])
                else:
                    self.assertTrue(any(v["reference_error"] in e for e in errs), errs)

    def test_the_json_schema_gets_the_verdict_each_ruling_vector_claims(self):
        # Catches: a rulingFile definition that refuses a file `fold.py export` wrote, or stops catching what a
        # vector says it catches; one marked beyond the schema must really pass it (PROTOCOL.md section 13).
        for v in RULINGS:
            with self.subTest(v["name"]):
                errs = json_errors(v["ruling"], defs("rulingFile"))
                if v["valid"]:
                    self.assertEqual(errs, [])
                elif v["schema_catches"]:
                    self.assertNotEqual(errs, [])
                else:
                    self.assertEqual(errs, [], "marked beyond the schema, but the schema catches it")

    def test_the_valid_vectors_use_every_field_the_schema_defines(self):
        # Catches: a field in the rulingFile definition that no export ever writes (so nothing pins its shape), or
        # one an export writes that the definition lacks.
        valid = [v["ruling"] for v in RULINGS if v["valid"]]
        self.assertEqual({k for r in valid for k in r}, set(defs("rulingFile")["properties"]))
        answers = [a for r in valid for a in [r["locked"], *r["history"]]]
        self.assertEqual({k for a in answers for k in a}, set(defs("lockedAnswer")["properties"]))
        self.assertEqual({k for r in valid for a in r.get("earlier", []) for k in a},
                         set(defs("earlierAnswer")["properties"]))

    def test_the_committed_vectors_are_what_the_generator_builds(self):
        # Catches: a vector edited by hand (so its verdict was never checked against the kit), or a kit change
        # that moves an id or an export while the committed vectors keep the old one.
        import spec_vectors
        for name, text in spec_vectors.build().items():
            with self.subTest(name):
                self.assertEqual((SPEC / "vectors" / name).read_text(encoding="utf-8"), text)

    def test_an_export_is_written_in_the_byte_form_the_spec_names(self):
        # Catches: an export's byte form changing (indent, key order, escaping), so a re-export of an unchanged
        # ruling shows as a change in every repository that commits them.
        e = next(v for v in RULINGS if v["valid"])
        with tempfile.TemporaryDirectory() as d:
            F.write_export({e["file"]: e["ruling"]}, Path(d))
            text = (Path(d) / e["file"]).read_text(encoding="utf-8")
        self.assertEqual(text, json.dumps(e["ruling"], indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        self.assertEqual(e["file"], e["ruling"]["qid"].replace("/", "__") + ".json")


class StoreVectorTests(unittest.TestCase):
    @staticmethod
    def spec_id(rec: dict) -> str:
        """The id as PROTOCOL.md section 3 defines it, written out here rather than calling the kit."""
        body = {k: v for k, v in rec.items() if k not in ("id", "seq", "ts", "schemaVersion")}
        canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:24]

    def test_every_sequence_replays_with_the_same_ids_and_refusals(self):
        # Catches: a store rule the spec states and the kit does not keep (or the reverse), and an id derivation
        # that drifts from the one PROTOCOL.md defines, which would break every other implementation's ids.
        for seq in SEQUENCES:
            with self.subTest(seq["name"]), tempfile.TemporaryDirectory() as d:
                st = Store(Path(d) / "store.jsonl")
                for step in seq["steps"]:
                    if step["accepted"]:
                        got = st.append(step["record"])
                        self.assertEqual((got["id"], got["seq"]), (step["id"], step["seq"]))
                        self.assertEqual(self.spec_id(step["record"]), step["id"])
                    else:
                        with self.assertRaises(StoreError) as cm:
                            st.append(step["record"])
                        self.assertIn(step["reference_error"], str(cm.exception))

    def test_a_replayed_store_reloads_line_for_line(self):
        # Catches: a store written by the rules that the kit's own loader then refuses (seq or id per line), so a
        # conforming writer's file would not open.
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "store.jsonl"
            st = Store(path)
            for step in SEQUENCES[0]["steps"]:
                st.append(step["record"])
            again = Store(path)
            self.assertEqual([r["id"] for r in again.records()], [s["id"] for s in SEQUENCES[0]["steps"]])


# -- the schema says what the kit says ------------------------------------------------------------------------

def py_pattern(rx: re.Pattern) -> str:
    """A kit shape as the JSON Schema writes it: no group names, `$` for `\\Z`."""
    p = re.sub(r"\(\?P<\w+>", "(", rx.pattern)
    assert p.endswith("\\Z"), p
    return p[:-2] + "$"


class DriftTests(unittest.TestCase):
    def test_each_kinds_fields_are_the_kits(self):
        # Catches: a field added to a kind in schema.py (or the schema) and not the other: a writer that follows the
        # spec is then refused by name ("unknown field"), or the spec allows what the kit refuses.
        for kind in CORE:
            with self.subTest(kind):
                d = defs(kind)
                self.assertEqual(set(d["properties"]), set(S.REQUIRED[kind]) | S.OPTIONAL[kind] | S.STORE_FIELDS)
                self.assertEqual(set(d["required"]), set(S.REQUIRED[kind]) | {"type", "schemaVersion"})
                self.assertEqual({d["properties"]["by"]["const"]}, set(S.WRITERS[kind]))
        self.assertEqual(set(SCHEMA["properties"]["type"]["enum"]), set(CORE))
        self.assertEqual(defs("schemaVersion")["const"], S.SCHEMA_VERSION)

    def test_the_shapes_are_the_kits(self):
        # Catches: a pattern edited on one side only, e.g. a nonce widened in schema.py while the published schema
        # still refuses it.
        pairs = {"nonce": S.NONCE, "recordId": S.RECORD_ID, "itemId": S.ITEM_ID, "qid": S.QID,
                 "optionId": S.OPTION_ID, "sha256": S.SHA256, "qualname": S.QUALNAME, "source": S.SOURCE,
                 "otherRole": S.OTHER_ROLE}
        for name, rx in pairs.items():
            with self.subTest(name):
                self.assertEqual(defs(name)["pattern"], py_pattern(rx))
        self.assertRegex(utc_now(), _pattern(defs("ts")["pattern"]))

    def test_the_limits_and_lists_are_the_kits(self):
        # Catches: a limit raised in the kit and not in the published schema (or the reverse).
        q, conds = defs("question")["properties"], {k: defs(f"condition_{k}") for k in S.VALID_IF_KINDS}
        ev = defs("evidenceRow")["properties"]
        checks = {
            "options": (q["options"]["maxItems"], S.MAX_OPTIONS),
            "picks": (defs("answer")["properties"]["picks"]["maxItems"], S.MAX_OPTIONS),
            "valid_if": (q["valid_if"]["maxItems"], S.MAX_VALID_IF),
            "lock anchors": (defs("lock")["properties"]["anchors"]["maxItems"], S.MAX_VALID_IF),
            "anchor anchors": (defs("anchor")["properties"]["anchors"]["maxItems"], S.MAX_VALID_IF),
            "evidence": (q["evidence"]["maxItems"], S.MAX_EVIDENCE),
            "text": (defs("text")["maxLength"], S.MAX_TEXT),
            "own_text": (defs("textMayBeEmpty")["maxLength"], S.MAX_TEXT),
            "one line": (defs("oneLine")["maxLength"], S.MAX_LINE),
            "one line, may be empty": (defs("oneLineMayBeEmpty")["maxLength"], S.MAX_LINE),
            "source": (defs("source")["maxLength"], S.MAX_LINE),
            "excerpt min": (conds["excerpt"]["properties"]["text"]["minLength"], S.MIN_EXCERPT),
            "excerpt max": (conds["excerpt"]["properties"]["text"]["maxLength"], S.MAX_EXCERPT),
            "symbol path": (conds["symbol"]["properties"]["path"]["maxLength"], S.MAX_LINE),
            "qualname": (defs("qualname")["maxLength"], S.MAX_QUALNAME),
            "cite": (ev["cite"]["maxLength"], S.MAX_LINE),
            "evidence text": (ev["text"]["maxLength"], S.MAX_EXCERPT),
            "evidence result": (ev["result"]["maxLength"], S.MAX_EVIDENCE_RESULT),
        }
        for name, (got, want) in checks.items():
            with self.subTest(name):
                self.assertEqual(got, want)
        self.assertEqual(tuple(q["kind"]["enum"]), S.QUESTION_KINDS)
        self.assertEqual(tuple(q["star_by"]["anyOf"][0]["enum"]), S.STAR_BY)
        self.assertEqual(tuple(defs("condition")["properties"]["kind"]["enum"]), S.VALID_IF_KINDS)
        self.assertEqual(set(ev), S.EVIDENCE_FIELDS)

    def test_the_ruling_file_rules_are_folds(self):
        # Catches: a limit or a name rule changed in fold.py or names.py and not in the published rulingFile.
        self.assertEqual(defs("rulingFile")["properties"]["earlier"]["maxItems"], F.MAX_EARLIER)
        self.assertEqual(defs("shortName")["pattern"], py_pattern(NM.NAME))
        self.assertEqual(defs("shortName")["maxLength"], NM.MAX_NAME)
        self.assertEqual(set(defs("rulingFile")["properties"]["asked_by_agent"]["allOf"][1]["not"]["enum"]),
                         set(NM.RESERVED))
        out = defs("outcome")
        self.assertEqual(set(out["properties"]["kind"]["enum"]), set(F.OUTCOME_KEYS))
        self.assertEqual(set(out["properties"]), {k for need, may in F.OUTCOME_KEYS.values() for k in need | may})

    def test_each_condition_kinds_keys_are_the_kits(self):
        # Catches: a key added to a condition kind on one side only; the kit refuses a condition whose keys are not
        # exactly its own, so the valid vector carrying all four kinds is the kit's word for each key set.
        full = next(v["record"] for v in RECORDS if v["valid"] and len(v["record"]["valid_if"]) == 4)
        for c in full["valid_if"]:
            with self.subTest(c["kind"]):
                d = defs(f"condition_{c['kind']}")
                self.assertEqual(set(c), set(d["required"]))
                self.assertEqual(set(c), set(d["properties"]))

    def test_the_prose_names_what_the_kit_computes(self):
        # Catches: the symbol hash's normalisation changing (its prefix moves with it) while PROTOCOL.md still
        # names the old one, a worked example whose id no longer derives from its record, and a limit changed in
        # the kit that the prose still states.
        self.assertIn(f"`{SY.HASH_PREFIX.strip()}`", PROSE)
        first = SEQUENCES[0]["steps"][0]
        self.assertIn(first["id"], PROSE)
        self.assertEqual(StoreVectorTests.spec_id(first["record"]), first["id"])
        stated = re.findall(r"`([A-Z_]+)` = ([0-9][0-9,]*)", PROSE)
        for name in ("MAX_TEXT", "MAX_LINE", "MAX_OPTIONS", "MAX_VALID_IF", "MAX_EVIDENCE", "MIN_EXCERPT",
                     "MAX_EXCERPT", "MAX_EVIDENCE_LINES", "MAX_EVIDENCE_RESULT", "MAX_QUALNAME"):
            with self.subTest(name):
                values = {int(v.replace(",", "")) for n, v in stated if n == name}
                self.assertEqual(values, {getattr(S, name)}, "every place the prose states it")
        self.assertTrue(all(hasattr(S, n) for n, _ in stated), "the prose names a constant the kit lacks")


if __name__ == "__main__":
    unittest.main()
