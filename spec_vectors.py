#!/usr/bin/env python3
"""Build the protocol's conformance vectors, docs/spec/vectors/*.json (1.55, Wave 4).

    python3 spec_vectors.py           # write them
    python3 spec_vectors.py --check   # exit 1 when the committed files differ from what this builds

Every verdict below is written by hand. The kit only fills in what it computes (record ids, exported ruling
files), and it must agree with every verdict, or this stops before writing anything: a vector the kit disagrees
with is a bug in one of them, never something to regenerate away. test_spec.py runs the check.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "plugin" / "kit"))
from overture import fold as F  # noqa: E402
from overture import schema as S  # noqa: E402
from overture.store import Store, StoreError  # noqa: E402

if not __debug__:
    sys.exit("spec_vectors.py checks each verdict with assert; run it without -O")

VECTORS = ROOT / "docs" / "spec" / "vectors"

H = "0" * 63 + "1"
SYM = "9f" * 32

Q = {"type": "question", "schemaVersion": 1, "qid": "PAY-2/Q1", "item": "PAY-2",
     "text": "Should a failed charge retry, and how often?", "kind": "single",
     "options": [{"id": "retry_once", "label": "Retry once", "description": "One more try after 30 s; cheap"},
                 {"id": "no_retry", "label": "Never retry", "description": "Fail at once; the caller decides"}],
     "star": "retry_once", "valid_if": [{"kind": "excerpt", "path": "docs/payments.md",
                                         "text": "A charge is attempted at most twice."}],
     "source": "docs/payments.md:12-14", "by": "agent", "nonce": "q1-nonce-0001"}
A = {"type": "answer", "schemaVersion": 1, "qid": "PAY-2/Q1", "picks": ["retry_once"], "own_text": "",
     "by": "owner", "nonce": "a1-nonce-0001"}
L = {"type": "lock", "schemaVersion": 1, "qid": "PAY-2/Q1", "answer": "0123456789abcdef01234567",
     "by": "owner", "nonce": "l1-nonce-0001"}
N = {"type": "anchor", "schemaVersion": 1, "qid": "PAY-2/Q1", "lock": "0123456789abcdef01234567",
     "anchors": [{"kind": "symbol", "path": "src/pay.py", "symbol": "Ledger.charge", "sha256": SYM}],
     "basis": "Ledger.charge moved from billing.py with the same body.", "by": "agent", "nonce": "n1-nonce-0001"}


def w(base, **kw):
    r = copy.deepcopy(base)
    for k, v in kw.items():
        if v is DROP:
            r.pop(k, None)
        else:
            r[k] = v
    return r


DROP = object()
ALL_CONDS = [{"kind": "file_sha256", "path": "config/limits.toml", "sha256": H},
             {"kind": "item_status", "item": "PAY-1", "status": "done"},
             {"kind": "excerpt", "path": "docs/payments.md", "text": "A charge is attempted at most twice."},
             {"kind": "symbol", "path": "src/pay.py", "symbol": "Ledger.charge", "sha256": SYM}]
EV = [{"cite": "src/pay.py:40-52", "command": "pytest -q tests/test_pay.py", "result": "3 passed",
       "text": "def charge(self, amount):\n    ..."}]

# (name, record, valid, schema_catches, reference_error)
RECORDS = [
    ("question: single, one excerpt", Q, True),
    ("question: no conditions", w(Q, valid_if=[]), True),
    ("question: free, no options, no star", w(Q, kind="free", options=[], star=None), True),
    ("question: multi, every condition kind, evidence, forked, star_by",
     w(Q, kind="multi", valid_if=ALL_CONDS, evidence=EV, forked_from="0123456789abcdef01234567",
       star_by="architect"), True),
    ("question: star_by a typed other seat", w(Q, star_by="other:Payments lead"), True),
    ("question: as stored, with id, seq and ts", w(Q, id="a" * 24, seq=1, ts="2026-10-21T20:00:00Z"), True),
    ("answer: one pick", A, True),
    ("answer: own words only", w(A, picks=[], own_text="Retry twice, but only on a timeout."), True),
    ("answer: supersedes a locked answer", w(A, picks=["no_retry"], supersedes="0123456789abcdef01234567",
                                             reason="The provider now retries for us.", nonce="a2-nonce-0002"),
     True),
    ("lock: plain", L, True),
    ("lock: with its own anchors", w(L, anchors=ALL_CONDS[2:]), True),
    ("anchor: re-anchors a lock", N, True),

    ("unknown record type", w(Q, type="verdict"), False, True, "unknown record type"),
    ("schemaVersion 2", w(Q, schemaVersion=2), False, True, "schemaVersion 2 is not 1"),
    ("an unknown field", w(Q, agent_name="cursor-1"), False, True, "unknown field(s) agent_name"),
    ("a missing field", w(Q, star=DROP), False, True, "missing star"),
    ("question by the owner", w(Q, by="owner"), False, True, "only ['agent'] may write one"),
    ("nonce too short", w(Q, nonce="short"), False, True, "nonce must be 8-64"),
    ("qid numbered Q0", w(Q, qid="PAY-2/Q0"), False, True, "is not <itemId>/Q<n>"),
    ("qid names another item", w(Q, qid="PAY-3/Q1"), False, False, "names item 'PAY-3'"),
    ("free question with options", w(Q, kind="free", star=None), False, True, "a free question offers no options"),
    ("single question with one option", w(Q, options=Q["options"][:1]), False, True, "at least two options"),
    ("star that is not an option", w(Q, star="maybe"), False, False, "star 'maybe' is not one of the options"),
    ("option ids repeat", w(Q, options=[Q["options"][0], dict(Q["options"][1], id="retry_once")], star=None),
     False, False, "option ids repeat"),
    ("option label on two lines", w(Q, options=[dict(Q["options"][0], label="Retry\nonce"), Q["options"][1]]),
     False, True, "label must be one line"),
    ("option label with U+2028", w(Q, options=[dict(Q["options"][0], label="Retry once"), Q["options"][1]]),
     False, True, "label must be one line"),
    ("text only whitespace", w(Q, text="  \n "), False, True, "text must not be empty"),
    ("excerpt under 8 characters", w(Q, valid_if=[dict(ALL_CONDS[2], text="twice.")]), False, True,
     "it needs at least 8"),
    ("excerpt under 8 once whitespace collapses", w(Q, valid_if=[dict(ALL_CONDS[2], text="a   b   c   d")]),
     False, False, "it needs at least 8"),
    ("condition path absolute", w(Q, valid_if=[dict(ALL_CONDS[0], path="/etc/limits.toml")]), False, True,
     "must be relative"),
    ("condition path climbs out", w(Q, valid_if=[dict(ALL_CONDS[0], path="docs/../../limits.toml")]), False, True,
     "must be relative"),
    ("condition with an extra key", w(Q, valid_if=[dict(ALL_CONDS[1], since="2026-10-01")]), False, True,
     "item_status takes exactly"),
    ("condition of an unknown kind", w(Q, valid_if=[{"kind": "regex", "path": "a.py", "text": "x+"}]), False, True,
     "needs kind in"),
    ("symbol hash not hex", w(Q, valid_if=[dict(ALL_CONDS[3], sha256="abc")]), False, True,
     "sha256 must be 64 lowercase hex"),
    ("symbol name not dotted", w(Q, valid_if=[dict(ALL_CONDS[3], symbol="Ledger..charge")]), False, True,
     "must be a dotted name"),
    ("evidence row without its text", w(Q, evidence=[{"cite": "src/pay.py:40"}]), False, True,
     "text must be the cited lines"),
    ("evidence cite climbs out", w(Q, evidence=[dict(EV[0], cite="../pay.py:40")]), False, True,
     "must be a relative path inside the project"),
    ("evidence cite ends before it starts", w(Q, evidence=[dict(EV[0], cite="src/pay.py:52-40")]), False, False,
     "start before end"),
    ("evidence cite over 200 lines", w(Q, evidence=[dict(EV[0], cite="src/pay.py:1-201")]), False, False,
     "must name 1 to 200 lines"),
    ("star_by with no star", w(Q, star=None, star_by="architect"), False, True, "this question has no"),
    ("forked, starred, no star_by", w(Q, forked_from="0123456789abcdef01234567"), False, True, "add star_by"),
    ("answer with no pick and no words", w(A, picks=[], own_text=" "), False, True,
     "needs at least one pick or its own words"),
    ("answer supersedes without a reason", w(A, supersedes="0123456789abcdef01234567"), False, True,
     "supersedes and reason go together"),
    ("answer picks repeat", w(A, picks=["retry_once", "retry_once"]), False, True, "picks repeat"),
    ("answer by an agent", w(A, by="agent"), False, True, "only ['owner'] may write one"),
    ("lock with empty anchors", w(L, anchors=[]), False, True, "anchors must name at least one condition"),
    ("lock naming no answer", w(L, answer=""), False, True, "answer must be the id of the answer"),
    ("anchor with an empty basis", w(N, basis="   "), False, True, "basis must not be empty"),
    ("anchor naming a lock by a bad id", w(N, lock="L1"), False, True, "lock must be the id of the lock"),
    # Whitespace is the set PROTOCOL.md section 3 names (Python's str.isspace): U+FEFF is not in it, U+001C and
    # U+0085 are, though ECMA-262's \s says the opposite of all three (1.55 review M1).
    ("text only U+FEFF, which is not whitespace", w(Q, text="﻿"), True),
    ("text only U+001C, which is whitespace", w(Q, text="\x1c"), False, True, "text must not be empty"),
    ("text only U+0085, which is whitespace", w(Q, text="\x85"), False, True, "text must not be empty"),
    ("schemaVersion true, not 1", w(Q, schemaVersion=True), False, True, "schemaVersion True is not 1"),
]


def check_records() -> list[dict]:
    out = []
    for case in RECORDS:
        name, rec, valid = case[:3]
        errs = S.validate(rec)
        if valid:
            assert not errs, (name, errs)
            out.append({"name": name, "valid": True, "record": rec})
        else:
            schema_catches, needle = case[3], case[4]
            assert errs and any(needle in e for e in errs), (name, errs)
            out.append({"name": name, "valid": False, "schema_catches": schema_catches,
                        "reference_error": needle, "record": rec})
    return out


# A store sequence: (name, [(record or a function of the earlier ids, accepted, reference_error)])
def ref(i):
    return ("@", i)


def resolve(v, ids):
    if isinstance(v, tuple) and v[0] == "@":
        return ids[v[1]]
    if isinstance(v, dict):
        return {k: resolve(x, ids) for k, x in v.items()}
    if isinstance(v, list):
        return [resolve(x, ids) for x in v]
    return v


def plain(r):
    return {k: v for k, v in r.items() if k != "schemaVersion"} | {"schemaVersion": 1}


A2 = w(A, picks=["no_retry"], nonce="a2-nonce-0002")
SEQS = [
    ("ask, answer, lock, supersede, re-lock, re-anchor", [
        (Q, True), (A, True), (w(L, answer=ref(1)), True),
        (w(A2, supersedes=ref(1), reason="The provider now retries for us."), True),
        (w(L, answer=ref(3), nonce="l2-nonce-0002"), True),
        (w(N, lock=ref(4)), True)]),
    ("a retried write is the same record, written once", [
        (Q, True), (Q, True, None, "retry")]),
    ("a qid is minted once", [
        (Q, True), (w(Q, nonce="q1-nonce-0002", text="Asked again."), False, "already exists")]),
    ("an answer names an existing question", [
        (A, False, "no question PAY-2/Q1")]),
    ("an answer picks only that question's options", [
        (Q, True), (w(A, picks=["sometimes"]), False, "are not options of PAY-2/Q1")]),
    ("a single question takes one pick", [
        (Q, True), (w(A, picks=["retry_once", "no_retry"]), False, "takes one pick")]),
    ("a lock locks the current answer", [
        (Q, True), (A, True), (A2, True), (w(L, answer=ref(1)), False, "is not the current answer")]),
    ("an answer is locked once", [
        (Q, True), (A, True), (w(L, answer=ref(1)), True),
        (w(L, answer=ref(1), nonce="l2-nonce-0002"), False, "is already locked")]),
    ("a locked question takes a new answer only by superseding", [
        (Q, True), (A, True), (w(L, answer=ref(1)), True), (A2, False, "is locked. A new answer supersedes")]),
    ("supersedes names the current answer", [
        (Q, True), (A, True), (w(L, answer=ref(1)), True),
        (w(A2, supersedes="0123456789abcdef01234567", reason="Changed my mind."), False,
         "is not the current answer of")]),
    ("only the current lock is re-anchored", [
        (Q, True), (A, True), (w(L, answer=ref(1)), True),
        (w(A2, supersedes=ref(1), reason="The provider now retries for us."), True),
        (w(N, lock=ref(2)), False, "only the current lock is re-anchored")]),
    ("the writer never assigns id, seq or ts", [
        (w(Q, seq=1), False, "seq is the store's to assign")]),
    # The id's canonical JSON with what escapes and what does not: non-ASCII, a quote, a backslash, a control
    # character and U+2028 (1.55 review M3).
    ("the id of text that JSON escapes, and text it does not", [
        (w(Q, text="Café: \"retry\" \\ once\x01 then stop"), True)]),
    ("an unpaired surrogate is refused, never hashed", [
        (w(Q, text="retry \ud800 once"), False, "unpaired surrogate")]),
]


def check_store() -> list[dict]:
    out = []
    for name, steps in SEQS:
        with tempfile.TemporaryDirectory() as d:
            st = Store(Path(d) / "store.jsonl", clock=lambda: "2026-10-21T20:00:00Z")
            ids, rows = [], []
            for step in steps:
                rec, ok = step[0], step[1]
                rec = resolve(rec, ids)
                before = st.seq()
                try:
                    got = st.append(rec)
                    accepted = True
                except StoreError as e:
                    accepted, err = False, str(e)
                assert accepted == ok, (name, rec, None if accepted else err)
                if ok:
                    assert got["id"] == S.record_id(rec | {"schemaVersion": 1}), name
                    row = {"record": rec, "accepted": True, "id": got["id"], "seq": got["seq"]}
                    if len(step) > 3 and step[3] == "retry":
                        assert st.seq() == before, name
                        row["retry"] = True
                    ids.append(got["id"])
                    rows.append(row)
                else:
                    assert step[2] in err, (name, err)
                    ids.append(None)
                    rows.append({"record": rec, "accepted": False, "reference_error": step[2]})
            out.append({"name": name, "steps": rows})
    return out


FORK ={"type": "message", "schemaVersion": 1, "item": "PAY-2", "text": "Deliberate on retries before we ship.",
        "by": "owner", "nonce": "f1-nonce-0001", "intent": "fork", "mode": "explore"}


def exported(steps, names=None, locked_by=None) -> dict:
    """Append `steps` (records, or functions of the earlier stored records) and return the one exported file."""
    with tempfile.TemporaryDirectory() as d:
        st = Store(Path(d) / "store.jsonl", clock=lambda: "2026-10-21T20:00:00Z")
        got = []
        for s in steps:
            got.append(st.append(s(got) if callable(s) else s))
        out = F.export(st, names={got[0]["id"]: names} if names else None,
                       locked_by={r["id"]: locked_by for r in got if r["type"] == "lock"} if locked_by else None)
        assert len(out) == 1, out
        return out


def lock_of(i, **kw):
    return lambda got: w(L, answer=got[i]["id"], **kw)


RULING_STORES = {
    "one answer, locked": [Q, A, lock_of(1)],
    "superseded, then locked again": [
        Q, A, lock_of(1), lambda g: w(A2, supersedes=g[1]["id"], reason="The provider now retries for us."),
        lock_of(3, nonce="l2-nonce-0002")],
    "superseded, changed once before the new lock, then re-anchored": [
        Q, A, lock_of(1),
        lambda g: w(A2, supersedes=g[1]["id"], reason="The provider now retries for us."),
        lambda g: w(A, picks=[], own_text="Never retry, and log it.", nonce="a3-nonce-0003"),
        lock_of(4, nonce="l2-nonce-0002"),
        lambda g: w(N, lock=g[5]["id"])],
    "locked with its own anchors, asked and locked by named sessions": [
        Q, A, lock_of(1, anchors=[{"kind": "file_sha256", "path": "config/limits.toml", "sha256": H}])],
    "forked from an owner's request": [
        FORK, lambda g: w(Q, forked_from=g[0]["id"], star_by="panel", evidence=EV), A, lock_of(2)],
}


def rulings() -> list[dict]:
    files = {}
    for name, steps in RULING_STORES.items():
        named = name.startswith("locked with its own anchors")
        files[name] = exported(steps, names="agent-6" if named else None, locked_by="alex" if named else None)
    one = files["one answer, locked"]
    fname, base = next(iter(one.items()))
    chain_name, chain = next(iter(files["superseded, changed once before the new lock, then re-anchored"].items()))
    fork_name, fork = next(iter(files["forked from an owner's request"].items()))
    relock_name, relock = next(iter(files["superseded, then locked again"].items()))
    cases = [(n, *next(iter(f.items())), True) for n, f in files.items()]
    cases += [
        ("settled: kept, but no longer checked", fname,
         w(base, outcome={"kind": "untracked", "by": "owner", "at": "2026-10-22T09:00:00Z",
                          "record": "0123456789abcdef01234567"}), True),
        ("replaces an older question", fname, w(base, replaces="PAY-1/Q4"), True),
        ("settled: superseded by a newer question", fname,
         w(base, outcome={"kind": "superseded", "by": "owner", "at": "2026-10-22T09:00:00Z",
                          "record": "0123456789abcdef01234567", "replaced_by": "PAY-2/Q2"}), True),
    ]
    bad = lambda **kw: w(base, **kw)  # noqa: E731
    lk = base["locked"]
    cases += [
        ("file name is not the qid's", "PAY-2__Q2.json", base, False, False, "file name does not match qid"),
        ("schemaVersion 2", fname, bad(schemaVersion=2), False, True, "schemaVersion 2 is not 1"),
        ("asked by the owner", fname, bad(asked_by="owner"), False, True, "only ['agent'] may write one"),
        ("asked_at is not a store time", fname, bad(asked_at="21 Oct 2026"), False, True,
         "is not a store timestamp"),
        ("picked_labels edited", fname, bad(locked=dict(lk, picked_labels=["Never retry"])), False, False,
         "picked_labels does not match"),
        ("picked_star edited", fname, bad(locked=dict(lk, picked_star=False)), False, False,
         "picked_star does not match"),
        ("locked by an agent", fname, bad(locked=dict(lk, locked_by="agent")), False, True,
         "is not locked by the owner"),
        ("a pick that is not an option", fname,
         bad(locked=dict(lk, picks=["sometimes"], picked_labels=[])), False, False, "which are not options"),
        ("anchors without anchored_by", fname, bad(locked=dict(lk, anchors=[ALL_CONDS[0]])), False, True,
         "anchored_by is 'lock'"),
        ("re-anchored without its anchor record", fname,
         bad(locked=dict(lk, anchored_by="reanchor", anchors=[ALL_CONDS[0]])), False, True,
         "anchored_by is 'lock'"),
        ("asked_by_agent is a reserved name", fname, bad(asked_by_agent="owner"), False, True, "is reserved"),
        ("locked_by_name is not a short name", fname, bad(locked=dict(lk, locked_by_name="Alex Doe")), False, True,
         "locked_by_name"),
        ("an earlier answer with an extra field", chain_name,
         w(chain, earlier=[dict(chain["earlier"][0], note="x")]), False, True, "an earlier answer carries exactly"),
        ("order leaves an answer out", chain_name, w(chain, order=chain["order"][1:]), False, False,
         "order must list every answer exactly once"),
        ("a lock followed without superseding it", chain_name,
         w(chain, earlier=[{k: v for k, v in chain["earlier"][0].items() if k not in ("supersedes", "reason")}]),
         False, False, "without superseding it"),
        ("withdrawn without a reason", fname,
         bad(outcome={"kind": "withdrawn", "by": "owner", "at": "2026-10-22T09:00:00Z",
                      "record": "0123456789abcdef01234567"}), False, True, "outcome is withdrawn (with reason)"),
        ("replaces itself", fname, bad(replaces="PAY-2/Q1"), False, False, "is not another question's qid"),
        ("a fork message without forked_from", fname, bad(fork=FORK), False, True, "without forked_from"),
        ("forked_from with no fork message", fname, bad(forked_from="0123456789abcdef01234567", star_by="panel"),
         False, True, "does not carry the fork message"),
        # 1.55 review M2 and L2.
        ("forked and starred, without star_by", fork_name, w(fork, star_by=DROP), False, True, "add star_by"),
        ("picked_star as 0, not false", relock_name, w(relock, locked=dict(relock["locked"], picked_star=0)),
         False, True, "picked_star does not match"),
        ("asked_at in other digits", fname, bad(asked_at="٢٠٢٦-10-21T20:00:00Z"), False, True,
         "is not a store timestamp"),
        ("a locked answer's blank reason", relock_name, w(relock, locked=dict(relock["locked"], reason="  ")),
         False, True, "reason must be non-empty text"),
        # 1.55.1: fold refuses an unknown field as the schema does (PROTOCOL.md section 13, a reader SHOULD).
        ("a ruling file with an unknown field", fname, bad(reviewed_by="alex"), False, True,
         "unknown field(s) reviewed_by"),
        ("a locked answer with an unknown field", relock_name,
         w(relock, history=[dict(relock["history"][0], note="x")]), False, True, "unknown field(s) note"),
    ]
    out = []
    for case in cases:
        name, file, entry, valid = case[:4]
        errs = F.check_entry(file, entry, {entry.get("item"): {}})
        if valid:
            assert not errs, (name, errs)
            out.append({"name": name, "file": file, "valid": True, "ruling": entry})
        else:
            assert errs and any(case[5] in e for e in errs), (name, errs)
            out.append({"name": name, "file": file, "valid": False, "schema_catches": case[4],
                        "reference_error": case[5], "ruling": entry})
    return out


HEAD = ("Overture protocol 1.0 conformance vectors, built by spec_vectors.py from hand-written verdicts, each "
        "checked against the reference kit. See docs/spec/PROTOCOL.md section 10.")


def build() -> dict[str, str]:
    """File name -> the exact text of each vectors file."""
    out = {}
    for fname, key, data in (("records.json", "records", check_records()), ("store.json", "sequences", check_store()),
                             ("rulings.json", "rulings", rulings())):
        # ASCII escapes: a vector may hold an unpaired surrogate, which UTF-8 cannot write.
        out[fname] = json.dumps({"protocol": "1.0", "about": HEAD, key: data}, indent=1, ensure_ascii=True) + "\n"
    return out


def main(argv: list[str]) -> int:
    files = build()
    if argv == ["--check"]:
        stale = [n for n, t in files.items() if not (VECTORS / n).is_file()
                 or (VECTORS / n).read_text(encoding="utf-8") != t]
        for n in stale:
            print(f"docs/spec/vectors/{n} is not what spec_vectors.py builds; run it and review the diff")
        return 1 if stale else 0
    if argv:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    VECTORS.mkdir(parents=True, exist_ok=True)
    for n, t in files.items():
        (VECTORS / n).write_text(t, encoding="utf-8")
        print(f"wrote docs/spec/vectors/{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
