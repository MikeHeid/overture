"""What decides whether a locked answer still holds, and why it does not (0.5.0).

A question carries `valid_if` conditions. Until 0.5.0 nothing re-anchored them,
so a whole-file `file_sha256` of a big living file went stale after almost any
unrelated change, and the owner had no way to clear it. Three things change:

- **An `excerpt` condition** holds while its cited text is found anywhere in
  the file. Moving the text keeps it; changing or deleting it does not.
  Whitespace and line endings are normalised before matching, so re-wrapping a
  paragraph is not a change.
- **Anchors on the lock.** The conditions that decide a locked answer are, in
  order: the latest `anchor` record written for that lock (by `reanchor`), the
  lock's own `anchors`, and otherwise the question's `valid_if`. A lock with
  neither evaluates exactly as it did in 0.4.0.
- **Re-locking re-anchors.** A lock on a question that was locked before gets
  fresh anchors from the tree as it is now (`fresh_anchors`), computed by the
  server, never taken from the page.

`explain` says, in plain words, why each failing condition fails, and
`plan_reanchor` works out which stale locks can be re-anchored with evidence
from git history, and which cannot.

1.54 (owner K1-K3) adds a `symbol` condition: one definition, by its dotted
name and its body's hash (`symbols.py`). It holds while that body is unchanged
at that name, whatever else in the file changes (K2). When the name is not
there, the body is looked for (K3): in the same file, and in the files a caller
names as changed (the CI check passes the pull request's changed and renamed
files). Found once, the condition holds and says where its code went
(`moved`); found twice, it is unchecked; found nowhere, it fails, even when a
changed file could not be searched (that file is named beside the break, 1.54
review H2). A cited file whose definitions cannot be read (an unknown language,
a syntax error, not UTF-8) is unchecked, never guessed: `Tree.check`, which
the CI check and the lookup read, says None for it and True for a moved one.
`Tree.holds`, which the console reads as "fresh", holds a symbol only at its
own name: a followed one shows stale there until the owner confirms its
re-anchor (a proposal, `refactor.py`), and an unchecked one shows stale too.
"""

from __future__ import annotations

import difflib
import hashlib
import re
import shlex
import unicodedata
from pathlib import Path
from typing import Callable, Mapping, NamedTuple

from . import gitseam as G
from . import refactor as RX
from . import rootfs as RF
from . import schema as S
from . import symbols as SY

HISTORY_COMMITS = 300   # how far back `git log` looks for the version a lock was taken on
GIT_TIMEOUT = 20        # seconds for one git call
DIFF_LINES = 40         # a "why stale" diff is cut to this many lines...
DIFF_CHARS = 4000       # ...and this many characters
SIMILAR = 0.5           # below this, a region is "not similar" and no diff is shown
MAX_READ = 2 << 20      # bytes: a larger file is never read (0.7.0); it answers like an unreadable one
UNREADABLE = {"outside": "resolves outside the project", "missing": "is not in the project",
              "secret": "is a secrets file, which is never read", "too_large": f"is over {MAX_READ >> 20} MiB, "
              "so it is not read",
              "refused": "is not a plain file under the project root (a symlink, or a path that leaves it)"}
SOURCE_RANGE = re.compile(r"^(?P<path>[^:]+):(?P<a>[0-9]+)(?:-(?P<b>[0-9]+))?\Z")
MAX_CANDIDATES = 200    # changed files searched for a moved symbol's body (K3), at most


def normalise(text: str) -> str:
    """Collapse every run of whitespace (line endings included) to one space, and trim."""
    return " ".join(text.split())


class SymbolState(NamedTuple):
    """Where a `symbol` condition's code is now.

    `state` is 'holds' (that name, that body), 'moved' (that body, under
    `path`::`symbol.qualname`), 'changed' (that name, another body), 'gone'
    (the body is nowhere searched), 'unreadable' (the file is a secret, too big
    or outside: `status`) or 'unchecked' (`reason`).
    """
    state: str
    path: str
    symbol: SY.Symbol | None
    reason: str
    status: str


class _File:
    __slots__ = ("status", "text", "sha", "utf8")

    def __init__(self, status: str, data: bytes | None) -> None:
        self.status = status
        self.utf8 = True
        try:
            self.text = None if data is None else data.decode("utf-8")
        except UnicodeDecodeError:   # an excerpt reads it replaced, as before; a symbol never does (1.54 review H1)
            self.text, self.utf8 = data.decode("utf-8", errors="replace"), False
        self.sha = None if data is None else hashlib.sha256(data).hexdigest()


class Tree:
    """The project as it is now.

    A snapshot Tree (the default) reads each file once for its lifetime, so one
    request that checks many conditions on one big file reads and hashes it
    once; build one per request. A live Tree (`snapshot=False`) re-reads the
    file on every check, as the 0.4.0 evaluator did, and keeps only the
    normalised text, keyed by the file's hash.
    """

    def __init__(self, root: Path, item_status: Mapping[str, str | None], *, snapshot: bool = True) -> None:
        self.root = Path(root).resolve()
        self.item_status = item_status
        self.snapshot = snapshot
        self._files: dict[str, _File] = {}
        self._norms: dict[str, str] = {}
        self._syms: dict[tuple[str, str], list[SY.Symbol] | str] = {}

    def _file(self, rel: str) -> _File:
        if RF.confined():
            return self._confined_file(rel)
        p = (self.root / rel).resolve()
        if self.root not in p.parents:
            return _File("outside", None)
        # 0.7.0: a secrets file is never read, whatever cites it, and neither is a
        # file past MAX_READ: both answer like a file that cannot be read.
        if S.secret_path(str(p.relative_to(self.root))) or S.secret_path(rel):
            return _File("secret", None)
        if not p.is_file():
            return _File("missing", None)
        f = self._files.get(rel) if self.snapshot else None
        if f is None:
            try:
                if p.stat().st_size > MAX_READ:
                    return _File("too_large", None)
                f = _File("ok", p.read_bytes())
            except OSError:
                return _File("missing", None)
            if self.snapshot:
                self._files[rel] = f
        return f

    def _confined_file(self, rel: str) -> _File:
        """The one console server's read (K3, §3.6): beneath the held root, no symlink at any depth."""
        if S.secret_path(rel):
            return _File("secret", None)
        f = self._files.get(rel) if self.snapshot else None
        if f is None:
            try:
                f = _File("ok", RF.read(self.root, rel, MAX_READ))
            except RF.Refused:
                return _File("refused", None)
            except FileNotFoundError:
                return _File("missing", None)
            except ValueError:
                return _File("too_large", None)
            except OSError:
                return _File("missing", None)
            if self.snapshot:
                self._files[rel] = f
        return f

    def text(self, rel: str) -> tuple[str, str | None]:
        """(status, text): status is 'ok', or a key of UNREADABLE ('missing', 'outside', 'secret', 'too_large')."""
        f = self._file(rel)
        return f.status, f.text

    def sha(self, rel: str) -> str | None:
        return self._file(rel).sha

    def norm(self, rel: str) -> str | None:
        f = self._file(rel)
        if f.status != "ok":
            return None
        if f.sha not in self._norms:
            self._norms[f.sha] = normalise(f.text)
        return self._norms[f.sha]

    def holds(self, c: dict) -> bool:
        """Whether `c` holds exactly as written; a moved or unchecked symbol does not (see `check`)."""
        if c["kind"] == "item_status":
            return self.item_status.get(c["item"]) == c["status"]
        if c["kind"] == "file_sha256":
            return self.sha(c["path"]) == c["sha256"]
        if c["kind"] == "symbol":   # at its name with its body; a followed one (moved) waits on a re-anchor
            return self.symbol_state(c).state == "holds"
        n = self.norm(c["path"])
        return n is not None and normalise(c["text"]) in n

    def check(self, c: dict, candidates: tuple[str, ...] | list[str] = ()) -> bool | None:
        """`holds` as the CI check and the lookup read it: a symbol followed to its body holds (K3), and one this
        cannot resolve is None (K1: unchecked, never a guess)."""
        if c["kind"] != "symbol":
            return self.holds(c)
        st = self.symbol_state(c, candidates).state
        return True if st in ("holds", "moved") else None if st == "unchecked" else False

    def symbols(self, rel: str) -> tuple[str, list[SY.Symbol] | None, str]:
        """(status, the definitions in `rel` or None, why not): status as `text`; read once per file content."""
        f = self._file(rel)
        if f.status != "ok":
            return f.status, None, ""
        key = (rel, f.sha)
        if key not in self._syms and not f.utf8:
            # 1.54 review H1: replaced text hides a change ("café" and "cafè" in Latin-1 both read "caf\ufffd").
            self._syms[key] = f"{rel} is not UTF-8 text, so its definitions are not read"
        if key not in self._syms:
            try:
                self._syms[key] = SY.find(rel, f.text)
            except SY.Unresolvable as e:
                self._syms[key] = str(e)
        got = self._syms[key]
        return ("ok", None, got) if isinstance(got, str) else ("ok", got, "")

    def symbol_state(self, c: dict, candidates: tuple[str, ...] | list[str] = ()) -> SymbolState:
        """Where `c`'s symbol is now: at its name, moved (its body found once, here or in `candidates`), or not."""
        path, q, sha = c["path"], c["symbol"], c["sha256"]
        status, syms, why = self.symbols(path)
        if status == "ok" and syms is None:
            return SymbolState("unchecked", path, None, why, status)
        if status == "ok":
            same = [s for s in syms if s.qualname == q]
            if len(same) > 1:
                return SymbolState("unchecked", path, None, f"{q} is defined {len(same)} times in {path}", status)
            if same:
                return SymbolState("holds" if same[0].body_sha256 == sha else "changed", path, same[0], "", status)
        elif status not in ("missing",):
            return SymbolState("unreadable", path, None, UNREADABLE[status], status)
        lang = SY.language(path)
        hits, blind = [], []
        for rel in dict.fromkeys([path, *list(candidates)[:MAX_CANDIDATES]]):
            if SY.language(rel) != lang:
                continue
            st, ss, w = self.symbols(rel)
            if st == "ok" and ss is None:
                blind.append(w)
            elif ss:
                hits += [(rel, s) for s in ss if s.body_sha256 == sha]
        if len(hits) > 1:
            where = ", ".join(f"{r}::{s.qualname}" for r, s in hits[:3])
            return SymbolState("unchecked", path, None, f"its body is in {len(hits)} places now ({where}), so "
                                                         f"which one the ruling meant cannot be told", status)
        if hits:
            # A body that calls itself by its old name still counts as moved: the name is blanked only where it
            # is defined, so `f` -> `g` calling `f` hashes alike. The owner confirms the new place (K3).
            return SymbolState("moved", hits[0][0], hits[0][1], "", status)
        # 1.54 review H2: a changed file the kit cannot read never turns "gone" into "unchecked", or any PR
        # could keep a broken ruling green by adding one; it is named beside the break instead.
        return SymbolState("gone", path, None, f"not searched: {blind[0]}" if blind else "", status)


def conditions_for(store, q: dict) -> tuple[list[dict], str]:
    """The conditions that decide `q`'s current lock, and where they came from.

    'reanchor' (an `anchor` record), 'lock' (the lock's own anchors) or
    'question' (its `valid_if`, as in 0.4.0). An unlocked question is decided by
    its `valid_if`.
    """
    head = store.head(q["qid"])
    lk = store.lock_of(head["id"]) if head is not None else None
    if lk is None:
        return q["valid_if"], "question"
    conds, origin, _ = lock_conditions(store, q, lk)
    return conds, origin


def lock_conditions(store, q: dict, lk: dict) -> tuple[list[dict], str, dict | None]:
    """The conditions that decide one lock, where they came from, and the `anchor` record if one decides.

    The same order everywhere, the view and the export alike: an anchor the
    owner confirmed from a proposal (CONSOLE-kit/Q31, `refactor.py`), the
    lock's latest `anchor` record, then the lock's own `anchors`, then the
    question's `valid_if`. A confirmed anchor lives beside the store, so a kit
    that predates it decides by the rest and reads the answer stale, never fresh.
    """
    c = RX.confirmed(store, lk["id"])
    if c is not None:
        return c[1]["anchors"], "confirmed", c[1]
    a = store.anchor_of(lk["id"])
    if a is not None:
        return a["anchors"], "reanchor", a
    if "anchors" in lk:
        return lk["anchors"], "lock", None
    return q["valid_if"], "question", None


def fresh_anchors(base: list[dict], tree: Tree) -> list[dict]:
    """The anchors a re-lock takes: each condition re-read against the tree as it is now.

    An `excerpt` that holds stays as it is. An `excerpt` whose text is gone
    cannot be re-derived from anything the owner saw, so it falls back to the
    whole file's hash as it is now: strict, but it pins what the owner re-locked
    against. A `file_sha256` is re-hashed. An `item_status` is kept as it is.
    A condition on a file that is gone stays as it is, and keeps the answer stale.
    """
    out = []
    for c in base:
        if c["kind"] == "symbol":
            out.append(_fresh_symbol(c, tree))
            continue
        if c["kind"] == "item_status" or tree.holds(c):
            out.append(c)
            continue
        sha = tree.sha(c["path"])
        out.append(c if sha is None else {"kind": "file_sha256", "path": c["path"], "sha256": sha})
    return out


def _fresh_symbol(c: dict, tree: Tree) -> dict:
    """A re-lock's `symbol` anchor: the symbol where it is now (a same-file rename followed), its body re-hashed.

    The owner re-locked against the code as it is, so a changed body is the
    new body; a symbol that is gone, unreadable or unchecked stays as it was,
    and keeps the answer stale.
    """
    st = tree.symbol_state(c)
    if st.state in ("holds", "moved", "changed"):
        return {"kind": "symbol", "path": st.path, "symbol": st.symbol.qualname, "sha256": st.symbol.body_sha256}
    return c


def symbol_ref(path: str, qualname: str) -> str:
    """The `path::Class.method` form agents write and reports show."""
    return f"{path}::{qualname}"


def propose_command(qid: str, ref: str, basis: str = "moved, same body") -> str | None:
    """The `agent.py propose-anchor` command re-anchoring `qid` on `ref`, every value shell-quoted; None when unsafe.

    1.54 review (security): in CI the qid and the moved symbol's path and name
    come from the pull request's head, so a file named `a;touch x.py` or a name
    with `$HOME` must reach an operator's copy-paste as data. A value holding a
    control character or a line break is not printed at all (it could forge a
    line of the report); the caller says so, and the JSON keeps the raw fields.
    """
    if any(_control(v) for v in (qid, ref, basis)):
        return None
    return shlex.join(["agent.py", "propose-anchor", qid, "--symbol", ref, "--basis", basis])


def _control(v: object) -> bool:
    return not isinstance(v, str) or any(unicodedata.category(ch)[0] == "C" or unicodedata.category(ch) in ("Zl", "Zp")
                                         for ch in v)


def symbol_condition(tree: Tree, path: str, qualname: str) -> tuple[dict | None, SY.Symbol | None, str]:
    """(the `symbol` condition, the definition) for `path::qualname` as the tree is now, or (None, None, why not).

    What `ask` and a re-anchor proposal take: the one definition of that name,
    its body hash read here. A secrets file, a file that is not there or cannot
    be read for definitions, a name it does not define and a name it defines
    twice are each refused by name, never guessed.
    """
    ref = symbol_ref(path, qualname)
    errs = S._check_condition({"kind": "symbol", "path": path, "symbol": qualname, "sha256": "0" * 64})
    if errs:
        return None, None, f"{ref}: " + "; ".join(e.removeprefix("valid_if ") for e in errs)
    if S.secret_path(path):
        return None, None, f"{ref}: {path} names {S.secret_path(path)}; a condition never reads a secrets file"
    status, syms, why = tree.symbols(path)
    if status != "ok":
        return None, None, f"{ref}: {path} {UNREADABLE[status]}"
    if syms is None:
        return None, None, f"{ref}: {why}; anchor on the lines with an excerpt instead"
    same = [s for s in syms if s.qualname == qualname]
    if len(same) > 1:
        return None, None, f"{ref}: {qualname} is defined {len(same)} times in {path}, so it cannot pin one"
    if not same:
        names = ", ".join(s.qualname for s in syms[:8]) + (", ..." if len(syms) > 8 else "")
        return None, None, f"{ref}: {path} defines no {qualname}" + (f" (it defines {names})" if syms else "")
    s = same[0]
    return {"kind": "symbol", "path": path, "symbol": qualname, "sha256": s.body_sha256}, s, ""


# -- git history ---------------------------------------------------------------

def _safe_path(rel: str) -> bool:
    return (isinstance(rel, str) and rel and not rel.startswith(("/", "-"))
            and ".." not in rel.split("/") and not any(ord(ch) < 32 for ch in rel))


class History:
    """Past versions of files from the project's git history, looked up by sha256.

    One `git log` and one `git cat-file --batch` per path, cached, so a whole
    check costs a few git calls however many answers cite the same file.
    """

    def __init__(self, root: Path, max_commits: int = HISTORY_COMMITS) -> None:
        self.root = Path(root).resolve()
        self.max_commits = max_commits
        self._versions: dict[str, list[tuple[str, bytes]] | None] = {}

    def _git(self, args: list[str], data: bytes | None = None) -> bytes | None:
        # Through gitseam (Q23): read-only, and in the server (seam closed) no git is started at all.
        out = G.run(args, self.root, data=data, timeout=GIT_TIMEOUT)
        return None if isinstance(out, G.Unavailable) else out

    def versions(self, rel: str) -> list[tuple[str, bytes]] | None:
        """(commit, content) for each commit that touched `rel`, newest first; None without git."""
        if rel in self._versions:
            return self._versions[rel]
        out = None
        if _safe_path(rel):
            log = self._git(["log", f"-n{self.max_commits}", "--format=%H", "--", rel])
            if log is not None:
                commits = log.decode().split()
                blobs = self._git(["cat-file", "--batch"],
                                  "".join(f"{c}:./{rel}\n" for c in commits).encode()) if commits else b""
                out = _parse_batch(commits, blobs or b"")
        self._versions[rel] = out
        return out

    source = None   # git read here, in this process: no provenance to name (the steward's is `stewardgit`)

    def find(self, rel: str, sha256: str):
        """(commit, text) of the newest version of `rel` whose sha256 is `sha256`, None, or `G.NO_GIT` (no git here)."""
        if not G.is_open():
            return G.NO_GIT
        for commit, blob in self.versions(rel) or []:
            if hashlib.sha256(blob).hexdigest() == sha256:
                return commit, blob.decode("utf-8", errors="replace")
        return None


def _parse_batch(commits: list[str], raw: bytes) -> list[tuple[str, bytes]]:
    out, pos = [], 0
    for c in commits:
        nl = raw.find(b"\n", pos)
        if nl < 0:
            break
        head = raw[pos:nl].split()
        pos = nl + 1
        if len(head) == 3 and head[1] == b"blob":
            size = int(head[2])
            out.append((c, raw[pos:pos + size]))
            pos += size + 1  # the content, then its newline
    return out


def cited_range(source: str, path: str) -> tuple[int, int] | None:
    """The 1-based inclusive line range `source` cites in `path`, or None when it cites none there."""
    m = SOURCE_RANGE.match(source or "")
    if not m or m.group("path") != path:
        return None
    a = int(m.group("a"))
    b = int(m.group("b") or a)
    return (a, b) if 1 <= a <= b else None


def _lines(text: str, rng: tuple[int, int]) -> str | None:
    lines = text.replace("\r\n", "\n").split("\n")
    a, b = rng
    if b > len(lines):
        return None
    return "\n".join(lines[a - 1:b])


# -- why stale -------------------------------------------------------------------

def _cap(lines: list[str]) -> str:
    out = "\n".join(lines[:DIFF_LINES])
    if len(lines) > DIFF_LINES:
        out += f"\n… {len(lines) - DIFF_LINES} more line(s) not shown"
    return out[:DIFF_CHARS]


def nearest(cited: str, current: str) -> dict | None:
    """The region of `current` most like `cited`, and a small diff from one to the other.

    Cheap on purpose: the most distinctive (longest) cited line is matched
    against every line of the file, and the region is laid around that match.
    """
    want = [ln for ln in cited.replace("\r\n", "\n").split("\n")]
    keys = sorted((ln.strip() for ln in want if ln.strip()), key=len, reverse=True)
    if not keys:
        return None
    key = keys[0]
    have = current.replace("\r\n", "\n").split("\n")
    best, best_i = 0.0, -1
    sm = difflib.SequenceMatcher(autojunk=False)
    sm.set_seq2(key)
    for i, ln in enumerate(have):
        sm.set_seq1(ln.strip())
        if sm.real_quick_ratio() <= best or sm.quick_ratio() <= best:
            continue
        r = sm.ratio()
        if r > best:
            best, best_i = r, i
    if best < SIMILAR:
        return None
    offset = next(n for n, ln in enumerate(want) if ln.strip() == key)
    start = max(0, best_i - offset)
    region = have[start:start + len(want)]
    raw = list(difflib.unified_diff(want, region, "cited", "now", lineterm="", n=2))[2:]  # no file headers
    diff = [ln for ln in raw if not ln.startswith("@@")]  # nor hunk headers: they mean nothing to a reader
    return {"line": start + 1, "diff": _cap(diff)}


def explain(c: dict, tree: Tree, history: History, source: str, candidates: tuple[str, ...] | list[str] = ()) -> dict:
    """Why condition `c` holds or not, in plain words, with a small diff where it is cheap.

    A `symbol` condition's `holds` is None when it is unchecked; `candidates`
    are the files its body is also looked for in (K3: a change's files).
    """
    if c["kind"] == "symbol":
        return explain_symbol(c, tree, candidates)
    out = {"condition": c, "holds": tree.holds(c)}
    if out["holds"]:
        return {**out, "reason": "holds", "words": "This still holds."}
    if c["kind"] == "item_status":
        now = tree.item_status.get(c["item"])
        words = (f"Item {c['item']} is no longer in the register; the answer assumed it was {c['status']}."
                 if c["item"] not in tree.item_status else
                 f"Item {c['item']} was expected to be {c['status']}; it is now {now}.")
        return {**out, "reason": "status_changed", "expected": c["status"], "actual": now, "words": words}
    status, text = tree.text(c["path"])
    if status == "outside":
        return {**out, "reason": "outside_project", "words": f"{c['path']} resolves outside the project."}
    if status == "missing":
        return {**out, "reason": "file_missing",
                "words": f"{c['path']} is gone: it was moved, renamed or deleted."}
    if status != "ok":  # a secrets file or one too large to read (0.7.0): never read, never diffed
        return {**out, "reason": "file_unreadable", "words": f"{c['path']} {UNREADABLE[status]}."}
    if c["kind"] == "excerpt":
        near = nearest(c["text"], text)
        words = f"The text this answer cites is no longer in {c['path']}: it was changed or deleted."
        if near:
            words += f" The most similar text now starts at line {near['line']}."
            return {**out, "reason": "text_changed", "words": words, **near}
        return {**out, "reason": "text_changed", "words": words + " Nothing similar is left in the file."}
    return {**out, "reason": "file_changed", **_file_changed(c, text, history, source)}


def explain_symbol(c: dict, tree: Tree, candidates: tuple[str, ...] | list[str] = ()) -> dict:
    """Why a `symbol` condition holds, moved, changed, is gone or is unchecked, in plain words."""
    st = tree.symbol_state(c, candidates)
    ref = symbol_ref(c["path"], c["symbol"])
    out = {"condition": c}
    if st.state == "holds":
        return {**out, "holds": True, "reason": "holds", "words": "This still holds."}
    if st.state == "moved":
        to = symbol_ref(st.path, st.symbol.qualname)
        return {**out, "holds": True, "reason": "moved", "moved_to": {"path": st.path, "symbol": st.symbol.qualname},
                "line": st.symbol.start_line,
                "words": f"moved: {ref} -> {to}, with the same body, so it still holds. The owner confirms the "
                         f"new place (`agent.py propose-anchor` proposes it)."}
    if st.state == "unchecked":
        return {**out, "holds": None, "reason": "unchecked",
                "words": f"{ref}: not checked here, as {st.reason}; a symbol is never guessed."}
    if st.state == "changed":
        s = st.symbol
        return {**out, "holds": False, "reason": "symbol_changed", "line": s.start_line,
                "words": f"The body of {c['symbol']} in {c['path']} changed since this answer was locked "
                         f"(it is now lines {s.start_line}-{s.end_line})."}
    if st.state == "unreadable":
        return {**out, "holds": False, "reason": "file_unreadable", "words": f"{c['path']} {st.reason}."}
    where = " or in the files this change touched" if candidates else ""
    beside = f" ({st.reason}.)" if st.reason else ""   # a changed file it could not search, named (1.54 review H2)
    if st.status == "missing":
        return {**out, "holds": False, "reason": "file_missing",
                "words": f"{c['path']} is gone, and no symbol{where} has the body of {c['symbol']}: it was "
                         f"deleted, or moved and changed.{beside}"}
    words = (f"{c['symbol']} is no longer in {c['path']}, and no symbol there{where} has its body: it was "
             f"deleted, or renamed and changed.{beside}")
    _, syms, _ = tree.symbols(c["path"])
    near = difflib.get_close_matches(c["symbol"], [s.qualname for s in syms or []], n=1, cutoff=0.6)
    if near:
        s = next(x for x in syms if x.qualname == near[0])
        words += f" The nearest name there now is {s.qualname} (line {s.start_line})."
        return {**out, "holds": False, "reason": "symbol_gone", "line": s.start_line, "words": words}
    return {**out, "holds": False, "reason": "symbol_gone", "words": words}


def _file_changed(c: dict, text: str, history: History, source: str) -> dict:
    words = f"{c['path']} changed since this answer was locked."
    found = history.find(c["path"], c["sha256"])
    if isinstance(found, G.Unavailable):  # in the server (Q23), with nothing the steward pushed for it
        return {"history": G.UNAVAILABLE,
                "words": words + f" Git history is {G.UNAVAILABLE}, so the version it was locked against, "
                                 f"and what changed, cannot be shown."}
    if found is None:
        return {"words": words + " The version it was locked against is not in the recent git history, "
                                 "so what changed cannot be shown."}
    commit, old = found
    out = {"locked_version": commit[:12] if commit else None}
    named = _version_words(commit, history)
    if history.source:   # the past version is the steward's (hash-verified); the commit id is its word alone
        out["history"] = history.source
        words += f" The version it was locked against came {history.source}, checked against the lock's hash."
    rng = cited_range(source, c["path"])
    cited = _lines(old, rng) if rng else None
    if cited is None or not normalise(cited):
        return {**out, "words": words + f" The question cites no line range in this file, so the whole file "
                                        f"counts (it was locked against {named})."}
    if normalise(cited) in normalise(text):
        return {**out, "cited_text": "unchanged",
                "words": words + f" The lines the question cites ({rng[0]}-{rng[1]} when it was locked) are "
                                 f"unchanged; only other parts of the file changed. Re-locking, or "
                                 f"`agent.py reanchor`, clears this."}
    near = nearest(cited, text) or {}
    return {**out, "cited_text": "changed", **near,
            "words": words + f" The lines the question cites ({rng[0]}-{rng[1]} when it was locked) changed."}


def _version_words(commit: str | None, history) -> str:
    """'commit abc123def456', with the steward named when the id is its word; an unnamed version said so."""
    prov = f" ({history.source})" if history.source else ""
    return f"commit {commit[:12]}{prov}" if commit else f"a version whose commit was not named{prov}"


def check(store, root: Path, item_status: Mapping[str, str | None],
          history: History | None = None) -> dict:
    """Every stale answer, and for each of its conditions whether it holds and why not."""
    tree = Tree(root, item_status)
    history = history or History(root)
    out = {}
    for q in (r for r in store.records() if r["type"] == "question"):
        conds, origin = conditions_for(store, q)
        head = store.head(q["qid"])
        if head is None or store.lock_of(head["id"]) is None or all(tree.holds(c) for c in conds):
            continue
        if RX.outcome(store, q["qid"]) is not None:   # withdrawn, kept unchecked or superseded: not stale
            continue
        out[q["qid"]] = {"anchored_by": origin,
                         "conditions": [explain(c, tree, history, q["source"]) for c in conds]}
    return out


# -- one-time re-anchor --------------------------------------------------------------

def plan_reanchor(store, root: Path, item_status: Mapping[str, str | None],
                  history: History | None = None) -> list[dict]:
    """For every stale lock, which conditions can be re-anchored with evidence, and which cannot.

    Only a failing `file_sha256` is ever replaced, and only when all of this is
    true: the question's `source` names a line range in that same file; git
    history holds the version whose sha256 the condition names (the version the
    answer was locked against); and the lines the question cited in that
    version are still in the file now. The replacement is an `excerpt` of those
    lines. Anything else stays as it is, and is reported with the reason.
    """
    tree = Tree(root, item_status)
    history = history or History(root)
    plan = []
    for q in (r for r in store.records() if r["type"] == "question"):
        head = store.head(q["qid"])
        lk = store.lock_of(head["id"]) if head is not None else None
        if lk is None:
            continue
        conds, origin = conditions_for(store, q)
        if all(tree.holds(c) for c in conds) or RX.outcome(store, q["qid"]) is not None:
            continue
        new, changes, kept = [], [], []
        for c in conds:
            if tree.holds(c):
                new.append(c)
                continue
            repl, why = _reanchor_one(c, tree, history, q["source"])
            new.append(repl or c)
            (changes if repl else kept).append({"from": c, **({"to": repl} if repl else {}), "why": why})
        plan.append({"qid": q["qid"], "lock": lk["id"], "anchored_by": origin, "base": conds, "anchors": new,
                     "changes": changes, "unresolved": kept,
                     "fresh": all(tree.holds(c) for c in new)})
    return plan


def still_supported(entry: dict, tree: Tree) -> str | None:
    """None when every replacement in a planned re-anchor still holds, exactly once, in `tree`; else why not."""
    for ch in entry["changes"]:
        to = ch["to"]
        n = tree.norm(to["path"])
        seen = 0 if n is None else n.count(normalise(to["text"]))
        if seen != 1:
            return (f"{to['path']} changed while this ran: the cited text is now there {seen} time(s); "
                    f"nothing was written, run it again")
    return None


def _reanchor_one(c: dict, tree: Tree, history: History, source: str) -> tuple[dict | None, str]:
    if c["kind"] == "item_status":
        return None, f"item {c['item']} is not {c['status']}; a status change is real, so it stays stale"
    if c["kind"] == "excerpt":
        return None, f"the cited text is no longer in {c['path']}"
    if c["kind"] == "symbol":
        return None, (f"{symbol_ref(c['path'], c['symbol'])} is re-anchored by a proposal the owner confirms "
                      f"(`agent.py propose-anchor <qid> --symbol PATH::NAME`), never from history")
    status = tree.text(c["path"])[0]
    if status != "ok":
        return None, f"{c['path']} {'is gone' if status == 'missing' else UNREADABLE[status]}"
    rng = cited_range(source, c["path"])
    if rng is None:
        return None, f"the question's source ({source}) names no line range in {c['path']}"
    found = history.find(c["path"], c["sha256"])
    if isinstance(found, G.Unavailable):  # in the server (Q23), with nothing the steward pushed for it
        return None, (f"git history is {G.UNAVAILABLE}, so the version of {c['path']} it was locked "
                      f"against cannot be looked up")
    if found is None:
        return None, (f"the version of {c['path']} it was locked against is not in the last "
                      f"{history.max_commits} commits that touched it")
    commit, old = found
    named = _version_words(commit, history)
    cited = _lines(old, rng)
    if cited is None or not normalise(cited):
        return None, f"lines {rng[0]}-{rng[1]} are not in {c['path']} at {named}"
    if len(normalise(cited)) < S.MIN_EXCERPT:
        return None, f"lines {rng[0]}-{rng[1]} are too short to anchor on ({len(normalise(cited))} characters)"
    if len(cited) > S.MAX_EXCERPT:
        return None, (f"lines {rng[0]}-{rng[1]} are {len(cited)} characters, over the "
                      f"{S.MAX_EXCERPT} an excerpt may hold")
    seen = tree.norm(c["path"]).count(normalise(cited))
    if seen == 0:
        return None, f"lines {rng[0]}-{rng[1]} as locked ({named}) changed; the answer is really stale"
    if seen > 1:
        # An excerpt found in several places would hold while the one the question
        # meant was changed or deleted: too weak to justify calling the answer fresh.
        return None, (f"lines {rng[0]}-{rng[1]} as locked appear {seen} times in {c['path']} now, "
                      f"so they cannot pin the one the question meant")
    return ({"kind": "excerpt", "path": c["path"], "text": cited},
            f"lines {rng[0]}-{rng[1]} as locked ({named}) are unchanged in the file now")


# -- structured evidence (0.7.0) -------------------------------------------------------

EVIDENCE_NOW_CHARS = 8000   # the current lines a review form is sent for one row, at most


def _split(text: str) -> list[str]:
    return text.replace("\r\n", "\n").split("\n")


def fill_evidence(rows: list[dict], tree: Tree) -> tuple[list[dict], list[str]]:
    """Read each row's cited lines from the tree, as the question is asked.

    Returns the rows with `text` filled in, and every reason a row cannot be
    read. A row that cites a missing file, lines past its end, or only blank
    lines is refused by name: evidence that cites nothing is not evidence.
    """
    out, errs = [], []
    for n, row in enumerate(rows, 1):
        path, a, b = S.cite_parts(row["cite"])  # the schema has already checked the shape
        status, text = tree.text(path)
        if status != "ok":
            errs.append(f"evidence row {n}: {path} {UNREADABLE[status]}")
            continue
        lines = _split(text)
        if b > len(lines):
            errs.append(f"evidence row {n}: {row['cite']} runs past the end of {path} ({len(lines)} lines)")
            continue
        cited = "\n".join(lines[a - 1:b])
        if not normalise(cited):
            errs.append(f"evidence row {n}: {row['cite']} cites only blank lines")
            continue
        if len(cited) > S.MAX_EXCERPT:
            errs.append(f"evidence row {n}: {row['cite']} is {len(cited)} characters, over the {S.MAX_EXCERPT} "
                        f"a row may hold; cite fewer lines")
            continue
        out.append({**row, "text": cited})
    return out, errs


def evidence_now(rows: list[dict], tree: Tree) -> list[dict]:
    """Each evidence row with the cited lines as they are now, and whether they changed since the question was asked.

    `state` is `unchanged` (the cited lines read as they did), `moved` (the
    same text is still in the file, elsewhere: `line` says where), `changed`
    (the text is not in the file any more; `diff` shows the nearest region
    when there is one) or `missing` (the file is gone). The comparison is the
    `excerpt` check's: whitespace and line endings do not count.
    """
    out = []
    for row in rows:
        parts = S.cite_parts(row.get("cite"))
        e = {k: row[k] for k in ("cite", "command", "result") if k in row}
        asked = row.get("text") or ""
        e["asked"] = asked
        if parts is None:
            out.append({**e, "state": "missing", "words": "This citation cannot be read."})
            continue
        path, a, b = parts
        status, text = tree.text(path)
        if status != "ok":
            out.append({**e, "state": "missing", "words": f"{path} is gone: it was moved, renamed or deleted."
                        if status == "missing" else f"{path} {UNREADABLE[status]}."})
            continue
        lines = _split(text)
        now = "\n".join(lines[a - 1:b]) if a <= len(lines) else ""
        if normalise(now) == normalise(asked):
            out.append({**e, "state": "unchanged", "line": a, "now": now[:EVIDENCE_NOW_CHARS],
                        "words": "Unchanged since the question was asked."})
            continue
        near = nearest(asked, text)
        if normalise(asked) in normalise(text):
            at = near["line"] if near else a
            moved = "\n".join(lines[at - 1:at - 1 + (b - a + 1)])
            out.append({**e, "state": "moved", "line": at, "now": moved[:EVIDENCE_NOW_CHARS],
                        "words": f"Unchanged since the question was asked; it now starts at line {at}."})
            continue
        row_out = {**e, "state": "changed", "line": a, "now": now[:EVIDENCE_NOW_CHARS],
                   "words": "Changed since the question was asked."}
        if near:
            row_out["diff"] = near["diff"]
            row_out["words"] += f" The most similar text now starts at line {near['line']}."
        out.append(row_out)
    return out


def evaluator(root: Path, item_status: Mapping[str, str | None], *,
              snapshot: bool = False) -> Callable[[dict], bool]:
    """A `holds(condition)` function; live by default, or over one reading of the tree (see `Tree`)."""
    return Tree(root, item_status, snapshot=snapshot).holds
