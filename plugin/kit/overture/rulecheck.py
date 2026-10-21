"""Which locked rulings a change breaks, read from the committed files alone (1.36.0).

`agent.py check` asks the running console server. CI has no server, and a pull
request should not need one: the rulings a project has locked are already
committed, one file per question, by `fold.py export` (`.overture.json`
`fold.locked`, `.overture/locked` by default). This reads those files and the
checkout, and nothing else: no store, no server, no network.

    python3 rulecheck.py [--root DIR] [--locked DIR] [--base REF] [--adapter FILE]
                         [--format text|markdown|json]

With `--base REF` (a pull request's base) the rulings checked are the ones
committed at REF, the rulings in force before the change, so a pull request
cannot clear its own failure by editing or deleting a ruling file. A ruling the
change re-locks (a newer lock in the same file whose conditions hold) or settles
(an `outcome`) is reported as re-ruled, for the reviewer to confirm, and does
not fail. Rulings whose cited files the change touched but which still hold are
listed, and so is every ruling file the change adds, edits or removes.

An `item_status` condition needs the project's register, which only its adapter
can read; it is checked with `--adapter` and otherwise reported as unchecked,
never as holding.

A `symbol` condition (1.54, owner K1-K3) holds while that definition keeps its
body. When the name is gone, its body is looked for in the same file and in the
files the change adds, edits or renames (git's rename detection on): found
once, the ruling holds and is reported as moved, "old path::old.name -> new
path::new.name", with the `propose-anchor` command that re-anchors it for the
owner to confirm; found nowhere, it is broken (a changed file that cannot be
read is named beside it, never a reason to pass); found twice, or when the cited
file's definitions cannot be read, it is unchecked, unless they could be read at
the base: then it is broken, with why (round 3). This only reads: nothing is
proposed or rewritten from CI.

Exit codes: 0 every checked ruling holds; 1 at least one is broken (or, with
`--strict`, could not be checked); 2 it could not run (bad arguments, a ruling
file that is not valid, a REF git does not know).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import anchors as A
from . import fold as F
from . import gitseam as G
from . import lookup as L
from . import symbols as SY

DEFAULT_LOCKED = ".overture/locked"   # what onboard writes into `.overture.json` (`fold.locked`)
MARKER = "<!-- overture-rulecheck -->"   # the Action finds its own comment by this first line
NOTABLE = "<!-- overture-rulecheck: notable -->"   # second line when the Action should post even on a pass
MAX_COMMENT = 60000   # characters; GitHub's limit for a comment is 65536
REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,199}\Z")   # a sha, branch or tag; never an option
MD_SPECIAL = re.compile(r"([\\`*_\[\]|#~])")


class CheckError(Exception):
    """It could not run: exit 2, named."""


# -- reading the rulings ---------------------------------------------------------------

def _git(root: Path, args: list[str]) -> bytes | None:
    out = G.run(args, root, timeout=A.GIT_TIMEOUT)
    return None if isinstance(out, G.Unavailable) else out


def from_dir(d: Path) -> dict[str, bytes]:
    """name -> bytes of every ruling file in the checkout; a symlink is never followed (it could read out)."""
    if not d.is_dir():
        return {}
    out = {}
    for p in sorted(d.glob("*.json")):
        if p.is_symlink() or not p.is_file():
            raise CheckError(f"{p.name}: not a plain file; a ruling file is never a symlink")
        if p.stat().st_size > A.MAX_READ:
            raise CheckError(f"{p.name}: over {A.MAX_READ >> 20} MiB, so it is not read")
        out[p.name] = p.read_bytes()
    return out


def check_base(root: Path, ref: str) -> None:
    """`ref` names a commit git has here, and `root` is the top of its work tree; else CheckError."""
    if not REF.match(ref) or ".." in ref:
        raise CheckError(f"--base {ref!r} is not a commit, branch or tag name")
    if _git(root, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]) is None:
        raise CheckError(f"--base {ref!r}: git does not know this commit here (fetch it first, "
                         f"e.g. actions/checkout with fetch-depth: 0)")
    # Ruling paths, `ls-tree`, `REF:path` and `diff` must all mean the same file, which holds at the top only.
    if _git(root, ["rev-parse", "--show-prefix"]) != b"\n":
        raise CheckError(f"--root {root} is not the top of its git work tree; run from the top with --base")


def from_ref(root: Path, ref: str, rel: str) -> dict[str, bytes]:
    """name -> bytes of every ruling file committed at `ref` (checked by check_base); {} when the folder was not there."""
    # Not recursive: only the folder's own files, as from_dir reads them.
    listing = _git(root, ["ls-tree", "-z", "--long", ref, "--", rel + "/"])
    if listing is None:
        raise CheckError(f"--base {ref!r}: git could not list {rel}")
    out = {}
    for row in filter(None, listing.split(b"\0")):
        meta, _, raw_path = row.partition(b"\t")
        mode, kind, _sha, size = meta.split()
        path = raw_path.decode("utf-8", errors="replace")
        name = path.rsplit("/", 1)[-1]
        if kind != b"blob" or not name.endswith(".json"):
            continue
        if mode == b"120000":
            raise CheckError(f"{name} at {ref}: a symlink; a ruling file is never a symlink")
        if int(size) > A.MAX_READ:
            raise CheckError(f"{name} at {ref}: over {A.MAX_READ >> 20} MiB, so it is not read")
        blob = _git(root, ["cat-file", "blob", f"{ref}:{path}"])
        if blob is None:
            raise CheckError(f"{name} at {ref}: git could not read it")
        out[name] = blob
    return out


def parse(raw: dict[str, bytes], items: dict | None, where: str) -> dict[str, dict]:
    """name -> entry, each held to `fold`'s own rules; any refusal stops the run, every one named."""
    out, refusals = {}, []
    for name, data in sorted(raw.items()):
        try:
            e = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            refusals.append(f"{name}{where}: not JSON ({err})")
            continue
        # Without a register the item cannot be resolved here, so only that one rule is waived.
        known = items if items is not None else {e.get("item") if isinstance(e, dict) else None: {}}
        errs = F.check_entry(name, e, known)
        if errs:
            refusals += [m + where for m in errs]
            continue
        out[name] = e
    if refusals:
        raise CheckError("a ruling file is not valid, so nothing was checked:\n  " + "\n  ".join(refusals))
    return out


# -- judging ---------------------------------------------------------------------------

conditions = L.conditions   # 1.52.0: one reading of what decides an exported lock, shared with the ruling lookup


def judge(e: dict, tree: A.Tree, history: A.History, item_status: dict | None,
          candidates: list[str] | tuple[str, ...] = (), before=None) -> dict:
    """One ruling's verdict; `candidates` are the files a moved symbol's body is looked for in (K3).

    `before(path)` is a file's text at the base (None when it was not there or
    is not UTF-8): a symbol whose cited file read at the base and cannot be
    read now is broken, not unchecked (1.54 review, round 3).
    """
    conds, origin = conditions(e)
    rows = []
    for c in conds:
        if c["kind"] == "item_status" and item_status is None:
            rows.append({"condition": c, "holds": None, "reason": "unchecked",
                         "words": f"Item {c['item']} must be {c['status']}: not checked here, as there is no "
                                  f"register (pass --adapter)."})
        else:
            rows.append(_unread_now(c, A.explain(c, tree, history, e["source"], candidates), tree, before))
    state = "broken" if any(r["holds"] is False for r in rows) else \
        "unchecked" if any(r["holds"] is None for r in rows) else "holds"
    out = {"qid": e["qid"], "question": e["question"], "source": e["source"], "anchored_by": origin,
           "lock_id": e["locked"]["lock_id"], "state": state, "conditions": rows}
    moved = [{"from": A.symbol_ref(r["condition"]["path"], r["condition"]["symbol"]),
              "to": A.symbol_ref(r["moved_to"]["path"], r["moved_to"]["symbol"])} for r in rows if "moved_to" in r]
    if moved:   # K3: it holds where its code went; the owner confirms the new place (`propose-anchor`)
        out["moved"] = moved
    return out


def _unread_now(c: dict, row: dict, tree: A.Tree, before) -> dict:
    """`row`, or a break when `c` is a symbol whose cited file read for it at the base and cannot now.

    1.54 review, round 3: "unchecked" is the honest word when there is nothing
    to compare with, but a change that turns a ruling the check could read into
    one it cannot read (a lexer miss such as `if (0) /'/.test("")`, a syntax
    error) would otherwise pass any PR. It fails, and says why, so the author
    fixes the code or asks for a re-anchor. Only when the symbol resolved
    cleanly at the base, from text that decodes as UTF-8 (round 4).
    """
    if c["kind"] != "symbol" or row["holds"] is not None or before is None:
        return row
    status, syms, why = tree.symbols(c["path"])
    if status != "ok":
        return row
    # Round 4: a read failure (a lexer miss, a syntax error) is promoted. A name found twice, or redefined,
    # is a doubt about which definition runs, and an ordinary edit can cause one: unchecked, unless (round 5)
    # none of its definitions has the ruled body, when the doubt cannot save it: the body changed.
    if syms is not None:
        same = [s for s in syms if s.qualname == c["symbol"]]
        if len(same) < 2 or any(s.body_sha256 == c["sha256"] for s in same):
            return row
    old = before(c["path"])
    if old is None or SY.resolve(c["path"], old, c["symbol"]).state != "found":
        return row
    ref = A.symbol_ref(c["path"], c["symbol"])
    if syms is not None:
        return {**row, "holds": False, "reason": "symbol_changed",
                "words": A.plain(f"{ref}: {c['symbol']} is defined {len(same)} times in {c['path']} now (or "
                                 f"redefined), and none of them has the body the ruling rests on: the body changed.")}
    return {**row, "holds": False, "reason": "symbol_unreadable",
            "words": A.plain(f"{ref}: read at the base, but not as this change leaves it: {why}. A change the check "
                             f"cannot read fails it, never passes it: fix the code, or ask the owner to re-anchor.")}


def _at_base(root: Path, base: str):
    """`path` -> its text at `base` (None when absent, too big or not UTF-8), each path read once."""
    seen: dict[str, str | None] = {}

    def read(path: str) -> str | None:
        if path not in seen:
            spec = f"{base}:{path}"
            raw = _git(root, ["cat-file", "blob", spec]) if _git(root, ["cat-file", "-e", spec]) is not None else None
            try:
                seen[path] = None if raw is None or len(raw) > A.MAX_READ else raw.decode("utf-8")
            except UnicodeDecodeError:
                seen[path] = None
        return seen[path]
    return read


def _cited(e: dict) -> set[str]:
    return {c["path"] for c in conditions(e)[0] if "path" in c}


def changed_paths(root: Path, base: str) -> tuple[set[str], list[str]]:
    """(every path the change touched, a rename's old and new name both; the paths it adds, edits or renames to).

    Rename detection is on (1.54, K3): a moved symbol's body is looked for in
    the second set, the files as the change leaves them.
    """
    out = _git(root, ["diff", "--name-status", "-z", "--find-renames", base, "--"])
    if out is None:
        raise CheckError(f"--base {base!r}: git could not diff the checkout against it")
    parts = [p.decode("utf-8", errors="replace") for p in out.split(b"\0")]
    touched, now, i = set(), [], 0
    while i < len(parts) and parts[i]:
        status = parts[i]
        n = 2 if status[:1] in ("R", "C") else 1
        names = parts[i + 1:i + 1 + n]
        i += 1 + n
        touched.update(names)
        if status[:1] != "D" and names:
            now.append(names[-1])
    return touched, sorted(set(now))


def run(root: Path, locked: str, base: str | None, items: dict | None, strict: bool = False) -> dict:
    """The whole report: what is broken, re-ruled, unchecked, touched and holds, and which ruling files changed."""
    root = Path(root).resolve()
    item_status = None if items is None else {k: v.get("status") for k, v in items.items()}
    head = parse(from_dir(root / locked), items, "")
    old = parse(from_ref(root, base, locked), items, f" (at {base})") if base else head
    tree, history = A.Tree(root, item_status or {}), A.History(root)
    touched_files, candidates = changed_paths(root, base) if base else (set(), [])
    before = _at_base(root, base) if base else None
    rep = {"base": base, "locked": locked, "broken": [], "reruled": [], "unchecked": [], "touched": [], "holds": [],
           "settled": [], "files": {"added": sorted(set(head) - set(old)), "removed": sorted(set(old) - set(head)),
                                    "edited": sorted(n for n in set(head) & set(old) if head[n] != old[n])}}
    # The rulings in force before the change, then any the change adds: a new ruling must hold too.
    for name, e in [*sorted(old.items()), *sorted((n, h) for n, h in head.items() if n not in old)]:
        if "outcome" in e:
            rep["settled"].append({"qid": e["qid"], "outcome": e["outcome"]["kind"]})
            continue
        j = judge(e, tree, history, item_status, candidates, before)
        now = head.get(name)
        if j["state"] == "broken" and base and now is not None and now is not e and (
                "outcome" in now or (now["locked"]["lock_id"] != e["locked"]["lock_id"]
                                     and judge(now, tree, history, item_status, candidates, before)["state"] == "holds")):
            j = {**j, "state": "reruled", "by": "outcome" if "outcome" in now else "lock",
                 "new_lock": now["locked"]["lock_id"]}
        elif j["state"] == "holds" and _cited(e) & touched_files:
            j = {**j, "state": "touched", "files": sorted(_cited(e) & touched_files)}
        rep[j["state"]].append(j)
    # Said in the report, so a wrong folder does not read as "all hold". Not a reason to comment: a
    # project that adds the Action before its first ruling would get one on every pull request, and
    # the folder comes from the base, so a pull request cannot empty it.
    rep["empty"] = not old and not head
    # What a reviewer must see on the pull request itself, not only in the job summary.
    rep["moved"] = [{"qid": j["qid"], **m} for k in ("touched", "holds") for j in rep[k] for m in j.get("moved", [])]
    rep["notable"] = bool(rep["broken"] or rep["reruled"] or rep["unchecked"] or rep["moved"]
                          or any(rep["files"].values()))
    rep["strict"] = strict
    rep["notable"] = rep["notable"] or (strict and rep["empty"])   # a strict failure shows on the pull request
    # Under --strict, "nothing could be checked" fails as well as "this one could not": a re-ruling does
    # not, since the reviewer sees it on the pull request and it is the owner's to make.
    rep["exit"] = 1 if rep["broken"] or (strict and (rep["unchecked"] or rep["empty"])) else 0
    return rep


# -- printing --------------------------------------------------------------------------

def _md(s: str) -> str:
    """Text from a ruling file, inert in a GitHub comment: no markup, no HTML, no @mention, no autolink.

    A zero-width space breaks `@name`, `://` and `www.`, which GitHub would
    otherwise turn into a ping or a link, while the text still reads the same.
    """
    s = MD_SPECIAL.sub(r"\\\1", s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    for raw in ("@", "://", "www."):
        s = re.sub(re.escape(raw), lambda m: m.group(0)[0] + "​" + m.group(0)[1:], s, flags=re.IGNORECASE)
    return " ".join(s.split())


def _fence(diff: str) -> str:
    ticks = "`" * max(3, 1 + max((len(m) for m in re.findall(r"`+", diff)), default=0))
    return f"{ticks}diff\n{diff}\n{ticks}"


def _moved_line(m: dict) -> str:
    """One moved ruling in the text report; its re-anchor command shell-quoted, or withheld and said why (1.54 review)."""
    cmd = A.propose_command(m["qid"], m["to"])
    if cmd is None:
        return (f"moved {_plain(m['qid'])}: {_plain(m['from'])} -> {_plain(m['to'])}; it still holds. No re-anchor "
                f"command is printed: a value holds a character a shell could read as more than itself (see "
                f"--format json for the fields)")
    return f"moved {m['qid']}: {m['from']} -> {m['to']}; it still holds. Re-anchor it for the owner to confirm: {cmd}"


def _plain(s: str) -> str:
    return "".join("?" if A._control(ch) else ch for ch in s)


def _unchecked_words(j: dict) -> str:
    """Why a ruling was not checked: its unchecked conditions' own words (an item status, a symbol)."""
    return " ".join(c["words"] for c in j["conditions"] if c["holds"] is None)


def _count(rep: dict) -> int:
    return sum(len(rep[k]) for k in ("broken", "reruled", "unchecked", "touched", "holds"))


def _verdict(rep: dict) -> str:
    """The one-line result, the same in every format; under --strict an unchecked ruling is a failure."""
    n = _count(rep)
    if rep["broken"]:
        return f"{len(rep['broken'])} of {n} ruling(s) broken by this change."
    if rep["strict"] and rep["empty"]:
        return "No ruling files were found, which --strict fails."
    if rep["strict"] and rep["unchecked"]:
        return f"{len(rep['unchecked'])} of {n} ruling(s) could not be checked, which --strict fails."
    return f"All {n} checked ruling(s) hold."


def markdown(rep: dict) -> str:
    out = [MARKER, NOTABLE if rep["notable"] else "", f"**Overture: {_verdict(rep)}**", ""]
    if rep["empty"]:
        out.append(f"No ruling files were found in {_md(rep['locked'])}. If this project has rulings, the "
                   f"folder is wrong: nothing was checked.\n")
    for j in rep["broken"]:
        out.append(f"### {_md(j['qid'])}: {_md(j['question'])}")
        out.append(f"Cited at {_md(j['source'])}. The owner's ruling no longer holds:")
        for c in j["conditions"]:
            if c["holds"] is False:
                out.append(f"- {_md(c['words'])}")
                if c.get("diff"):
                    out.append(_fence(c["diff"]))
        out.append("Ask the owner to re-lock it, change the code back, or withdraw the ruling.\n")
    if rep["reruled"]:
        out.append("**Re-ruled in this change** (confirm the owner did this):")
        out += [f"- {_md(j['qid'])}: {'settled' if j['by'] == 'outcome' else 're-locked as ' + _md(j['new_lock'])}"
                for j in rep["reruled"]]
        out.append("")
    if rep["unchecked"]:
        out.append("**Not checked here** (an item status needs the register, pass `adapter`; a symbol is never "
                   "guessed):")
        out += [f"- {_md(j['qid'])}: {_md(_unchecked_words(j))}" for j in rep["unchecked"]]
        out.append("")
    if rep["moved"]:
        out.append("**Followed to a new place** (the code a ruling rests on moved with its body unchanged; the "
                   "owner confirms the new place):")
        out += [f"- {_md(m['qid'])}: {_md(m['from'])} → {_md(m['to'])}" for m in rep["moved"]]
        out.append("")
    if rep["touched"]:
        out.append("**Touched, still holds:**")
        out += [f"- {_md(j['qid'])}: {', '.join(_md(f) for f in j['files'])}" for j in rep["touched"]]
        out.append("")
    f = rep["files"]
    if any(f.values()):
        out.append("**Ruling files this change edits:** " + "; ".join(
            f"{k} {', '.join(_md(x) for x in v)}" for k, v in f.items() if v))
    body = "\n".join(ln for i, ln in enumerate(out) if i != 1 or ln).rstrip() + "\n"
    if len(body) > MAX_COMMENT:   # GitHub refuses a longer comment; the job summary and log keep the rest
        body = (body[:MAX_COMMENT].rsplit("\n", 1)[0] + "\n\n… cut here; for the whole report run "
                "`rulecheck.py --base <base>` on the branch.\n")
    return body


def text(rep: dict) -> str:
    """The plain-text report. 1.54 review M3: every value is printed through `_plain`, since a reason can name a
    path from the change, and a path can hold a line break that would forge a report line of its own."""
    P = _plain
    out = []
    for j in rep["broken"]:
        out.append(f"BROKEN {P(j['qid'])} (cited at {P(j['source'])}, anchored by {P(j['anchored_by'])}):")
        for c in j["conditions"]:
            out.append(f"  {'holds' if c['holds'] else 'unchecked' if c['holds'] is None else 'FAILS'}: "
                       f"{P(c['words'])}")
            if c.get("diff") and c["holds"] is False:
                out += ["      " + P(ln) for ln in c["diff"].split("\n")]
    out += [f"re-ruled {P(j['qid'])}: {'settled' if j['by'] == 'outcome' else 'new lock ' + P(j['new_lock'])}; "
            f"confirm the owner did this" for j in rep["reruled"]]
    out += [f"unchecked {P(j['qid'])}: {P(_unchecked_words(j))}" for j in rep["unchecked"]]
    out += [_moved_line(m) for m in rep["moved"]]
    out += [f"touched {P(j['qid'])}: {', '.join(P(f) for f in j['files'])} changed; it still holds"
            for j in rep["touched"]]
    out += [f"ruling files {k}: {', '.join(P(x) for x in v)}" for k, v in rep["files"].items() if v]
    if rep["empty"]:
        out.append(f"no ruling files in {P(rep['locked'])}: if this project has rulings, the folder is wrong")
    out.append(_verdict(rep))
    return "\n".join(out) + "\n"


# -- command line ----------------------------------------------------------------------

def _locked_default(root: Path, base: str | None) -> str:
    """`fold.locked` from `.overture.json`: as committed at `base` when there is one.

    Read from the change itself, a pull request could point it at an empty folder
    and pass with nothing checked (1.36.0 review, HIGH).
    """
    p = root / ".overture.json"
    try:
        if base:
            spec = f"{base}:{p.name}"
            raw = _git(root, ["cat-file", "blob", spec]) if _git(root, ["cat-file", "-e", spec]) is not None else None
            cfg = json.loads(raw) if raw is not None else {}
        else:
            cfg = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError) as e:
        raise CheckError(f"{p}{' at ' + base if base else ''}: not readable JSON ({e})") from None
    fold = cfg.get("fold") if isinstance(cfg, dict) else None
    v = fold.get("locked") if isinstance(fold, dict) else None
    return v if isinstance(v, str) else DEFAULT_LOCKED


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, default=Path("."), help="the project checkout (default: here)")
    ap.add_argument("--locked", help=f"the committed ruling files (default: .overture.json fold.locked, "
                                     f"else {DEFAULT_LOCKED})")
    ap.add_argument("--base", metavar="REF", help="check the rulings committed at REF (a pull request's base)")
    ap.add_argument("--adapter", help="the project's adapter, imported to read item statuses (it is code: opt in)")
    ap.add_argument("--format", choices=("text", "markdown", "json"), default="text")
    ap.add_argument("--strict", action="store_true",
                    help="fail (exit 1) when a ruling could not be checked, such as an item status with no --adapter")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        root = Path(a.root).resolve()
        if a.base:
            check_base(root, a.base)
        locked = (a.locked if a.locked is not None else _locked_default(root, a.base)).rstrip("/")
        F.inside(root, locked, "--locked")   # the same boundary fold holds its paths to
        items = F.load_adapter(F.inside(root, a.adapter, "--adapter")).items() if a.adapter else None
        rep = run(root, locked, a.base, items, a.strict)
    except (CheckError, F.FoldError) as e:
        print(f"rulecheck: {e}", file=sys.stderr)
        return 2
    except (Exception, SystemExit) as e:  # noqa: BLE001 - an adapter that fails or exits, or git gone odd:
        # named, never a pass. SystemExit too: an adapter's sys.exit(0) would otherwise end the run as "holds".
        print(f"rulecheck: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(rep, indent=2, ensure_ascii=False) + "\n" if a.format == "json" else
                     markdown(rep) if a.format == "markdown" else text(rep))
    return rep["exit"]
