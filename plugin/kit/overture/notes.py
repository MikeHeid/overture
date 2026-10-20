"""Area notes and the memory index, checked (1.53.0; owner M1-M4, OPEN-DECISIONS "Memory in its own place").

An area note is a short `CLAUDE.md` (at most MAX_LINES lines) in one of the
folders a repository declares in `.overture.json`:

    {"areas": ["plugin/hooks", "plugin/kit", "docs"]}

Claude Code loads such a file only when a session reads in that folder, so a
note costs nothing elsewhere; the repository-root CLAUDE.md is the opposite
(loaded in every session there) and is reported as "always loaded", never as
an area note. A note's first line says which commit its facts were checked at:

    <!-- area: plugin/hooks · checked: 1a2b3c4 -->

`check` reads the repository and says, never writing anything:

- stale: the area's committed files changed after that commit (the note
  itself, any nested declared area and any file `.overture.json`
  "notes_ignore" names left out: a release's version bump writes such a file
  and changes no fact). When the commit is not in
  this branch's history (a squash merge leaves the branch's commits behind),
  the last commit that changed the note's header line is the base instead
  (1.53 review C3: a typo fix lower in the note does not move it). Changes
  that landed in the base commit itself count as checked;
- undeclared: a CLAUDE.md below the root in a folder not on the list (the
  sprawl gate); files git ignores are never looked at;
- malformed: no header, a header naming another folder, a commit that cannot
  be found, or more than MAX_LINES lines;
- with `memory`, the auto-memory index MEMORY.md in that folder: links to
  files that are not there, links that leave the folder (never looked up),
  and *.md files no line links.

A shallow clone is refused: its history stops short, so staleness cannot be
judged (1.53 review C2). Every name and reason `lines` prints passes through
`lookup._short`, so a hostile file name cannot reach a terminal as an escape
sequence or a bidi override (1.53 review S1).

`stamp` rewrites one note's header to HEAD after someone re-read the area,
and changes nothing else in the file; `check` never writes (1.53 review C4).

Agent side only. Every git call goes through `gitseam` (CONSOLE-kit/Q23), so
inside the console server, where the seam is closed, it refuses rather than
start git. Standard library only; importing it does nothing.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

from . import gitseam as G
from .lookup import _short, _unsafe

NOTE = "CLAUDE.md"
CONFIG = ".overture.json"
ALWAYS_LOADED = ("CLAUDE.md", ".claude/CLAUDE.md")   # read by Claude Code in every session at the root
MAX_LINES = 10
MAX_NOTE = 16384
MAX_CONFIG = 64 * 1024
MAX_AREAS = 32
MAX_CHANGED = 20         # files named per stale note; the count is always whole
GIT_SECONDS = 30.0
HEADER = re.compile(r"^<!-- area: (?P<area>\S+) · checked: (?P<sha>[0-9a-f]{7,40}) -->\Z")
AREA = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*\Z")
LINK = re.compile(r"\[[^\]]*\]\((?:<([^<>\n]+)>|([^)\s]+))")   # [t](a%20b.md) and [t](<a b.md>), C8
SAY = 300                # characters of one name or reason `lines` prints, at most
HEADER_LINE = "^<!-- area: .* checked: [0-9a-f]"   # git log -G: a commit that added or removed a header line


class NotesError(Exception):
    """A check that cannot be made; the message names why, and nothing was read as clean."""


def _git(root: Path, args: list[str], tick: Callable[[], None] | None) -> tuple[int, str]:
    got = G.git_full(args, root, timeout=GIT_SECONDS, tick=tick)
    if isinstance(got, G.Unavailable):
        raise NotesError("no git here: the console server starts no git (CONSOLE-kit/Q23); run it agent-side")
    rc, out, err = got
    if rc in (124, 126, 127):
        raise NotesError(f"git {args[0]}: {err.strip() or rc}")
    return rc, out


def _top(root: Path | str, tick) -> Path:
    root = Path(root)
    if not root.is_dir():
        raise NotesError(f"--root {root}: not a folder")
    rc, out = _git(root, ["rev-parse", "--show-toplevel"], tick)
    if rc != 0:
        raise NotesError(f"{root} is not a git checkout")
    top = Path(out.strip())
    if os.path.realpath(top) != os.path.realpath(root):
        raise NotesError(f"--root {root}: not the top of its git checkout (that is {top})")
    return top


def top_of(cwd: Path | str, *, tick: Callable[[], None] | None = None) -> Path:
    """The top of the git checkout `cwd` is in (the default --root)."""
    rc, out = _git(Path(cwd), ["rev-parse", "--show-toplevel"], tick)
    if rc != 0:
        raise NotesError(f"{cwd} is not in a git checkout; pass --root")
    return Path(out.strip())


def _read(p: Path, cap: int) -> bytes:
    """A small regular file's bytes; a symlink, a FIFO or a file past `cap` is refused (OSError)."""
    fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > cap:
            raise OSError(f"{p} is not a regular file of at most {cap} bytes")
        return os.read(fd, cap + 1)[:cap]
    finally:
        os.close(fd)


def _config(root: Path) -> dict:
    try:
        doc = json.loads(_read(Path(root) / CONFIG, MAX_CONFIG).decode("utf-8"))
    except FileNotFoundError:
        doc = {}
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as e:
        raise NotesError(f"{CONFIG}: cannot be read: {e}") from None
    return doc if isinstance(doc, dict) else {}


def _plain(got: object) -> bool:
    """1 to MAX_AREAS distinct relative paths inside the repository: no '.', '..' or leading '/'."""
    return isinstance(got, list) and 0 < len(got) <= MAX_AREAS and len(set(got)) == len(got) and all(
        isinstance(a, str) and AREA.match(a) and ".." not in a.split("/") and "." not in a.split("/") for a in got)


def areas(root: Path) -> list[str]:
    """The declared area roots, from the repository's `.overture.json` "areas"; refused by name when unusable."""
    got = _config(root).get("areas")
    if got is None:
        raise NotesError(f"{root} declares no areas ({CONFIG} \"areas\": a list of folders that may hold a note)")
    if not _plain(got):
        raise NotesError(f"{CONFIG}: areas must be 1 to {MAX_AREAS} distinct relative folders inside the "
                         f"repository (no '.', '..' or leading '/'), e.g. [\"docs\", \"src/server\"]")
    return list(got)


def ignored(root: Path, declared: list[str]) -> list[str]:
    """`.overture.json` "notes_ignore": files whose change alone makes no note stale (the files a release's
    version bump writes). Checked like "areas"; a declared area, or a folder holding one, is refused, so no
    note's whole area can be ignored away. Absent: none."""
    got = _config(root).get("notes_ignore")
    if got is None:
        return []
    if not _plain(got):
        raise NotesError(f"{CONFIG}: notes_ignore must be 1 to {MAX_AREAS} distinct relative files inside the "
                         f"repository (no '.', '..' or leading '/'), e.g. [\"src/server/version.py\"]")
    for f in got:
        if any(d == f or d.startswith(f + "/") for d in declared):
            raise NotesError(f"{CONFIG}: notes_ignore names {f}, a declared area or a folder holding one; "
                             f"name the files a version bump writes, not a whole area")
    return list(got)


def _pathspec(area: str, declared: list[str], ignore: list[str]) -> list[str]:
    """The area's files: its folder, less its own note, any nested declared area (which has its own) and any
    file "notes_ignore" names."""
    return [area, f":(exclude){area}/{NOTE}", *(f":(exclude){d}" for d in declared if d.startswith(area + "/")),
            *(f":(exclude){f}" for f in ignore if f.startswith(area + "/"))]


def _base(root: Path, sha: str, note_rel: str, tick) -> tuple[str | None, str]:
    """(commit to measure from, where it came from): the checked commit when this branch holds it, else the
    last commit that changed the note's header line (C3: not its last commit, which a typo fix would move);
    (None, why) when there is neither. An ambiguous short sha is not a commit here, so it falls back too."""
    rc, full = _git(root, ["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"], tick)
    if rc == 0 and _git(root, ["merge-base", "--is-ancestor", full.strip(), "HEAD"], tick)[0] == 0:
        return full.strip(), "checked"
    rc, last = _git(root, ["log", "-1", "--format=%H", f"-G{HEADER_LINE}", "--", note_rel], tick)
    if rc == 0 and last.strip():
        return last.strip(), "header-commit"
    return None, (f"checked commit {sha} is not in this branch's history, and the note's header was never "
                  f"committed, so nothing says what it was checked against")


def _parse(root: Path, rel: str, area: str) -> tuple[str | None, str | None]:
    """(checked sha, None) for a well-formed note, else (None, why)."""
    try:
        text = _read(root / rel, MAX_NOTE).decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return None, f"cannot be read: {e}"
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        return None, f"{len(lines)} lines; a note holds at most {MAX_LINES}"
    m = HEADER.match(lines[0]) if lines else None
    if not m:
        return None, f"its first line is not `<!-- area: {area} · checked: <commit> -->`"
    if any(_unsafe(ch) for ch in m["area"]):   # S1: an ESC or a bidi override is refused by name, never echoed
        return None, "its header's area holds a control or format character"
    if m["area"] != area:
        return None, f"its header names {_short(m['area'], SAY)}, but it sits in {area}"
    return m["sha"], None


def check(root: Path | str, *, memory: Path | str | None = None, tick: Callable[[], None] | None = None) -> dict:
    """Every note under `root` (the top of a git checkout) judged; see the module docstring. Never writes."""
    top = _top(root, tick)
    declared = areas(top)
    ignore = ignored(top, declared)
    rc, head = _git(top, ["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], tick)
    if rc != 0:
        raise NotesError(f"{top} has no commit yet")
    rc, shallow = _git(top, ["rev-parse", "--is-shallow-repository"], tick)
    if rc != 0 or shallow.strip() != "false":   # C2: a cut history would make every checked commit look absent
        raise NotesError("shallow clone: staleness can't be judged; fetch full history (git fetch --unshallow)")
    rc, listed = _git(top, ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
                            NOTE, f":(glob)**/{NOTE}"], tick)
    if rc != 0:
        raise NotesError("git ls-files failed")
    found = sorted({r for r in listed.split("\0") if r and (top / r).exists()})
    res = {"root": str(top), "head": head.strip(), "areas": declared, "current": [], "stale": [],
           "undeclared": [], "malformed": [], "always_loaded": [], "memory": None}
    for rel in found:
        if rel in ALWAYS_LOADED:
            res["always_loaded"].append(rel)
            continue
        area = rel[:-len("/" + NOTE)]
        if area not in declared:
            res["undeclared"].append(rel)
            continue
        sha, why = _parse(top, rel, area)
        base, came = _base(top, sha, rel, tick) if sha else (None, why)
        if base is None:
            res["malformed"].append({"note": rel, "why": came})
            continue
        rc, out = _git(top, ["diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", base, "HEAD", "--",
                             *_pathspec(area, declared, ignore)], tick)
        if rc != 0:
            res["malformed"].append({"note": rel, "why": f"git diff from {sha} failed"})
            continue
        changed = sorted(f for f in out.split("\0") if f)
        if changed:
            res["stale"].append({"area": area, "note": rel, "checked": sha, "base": came,
                                 "changed_count": len(changed), "changed": changed[:MAX_CHANGED]})
        else:
            res["current"].append(area)
    if memory is not None:
        res["memory"] = memory_index(memory)
    res["ok"] = not (res["stale"] or res["undeclared"] or res["malformed"]
                     or (res["memory"] and (res["memory"]["missing"] or res["memory"]["outside"]
                                            or res["memory"]["unlinked"])))
    return res


def memory_index(folder: Path | str) -> dict:
    """The auto-memory index MEMORY.md in `folder`: links to missing files, links that leave the folder (S3: an
    absolute or `..` target, or one resolving out through a symlink, is named and never looked up), and *.md
    files no line links. A link's `%20` and `<a b.md>` spellings are read as the file they name (C8)."""
    d = Path(folder)
    if not d.is_dir():
        raise NotesError(f"--memory {d}: not a folder")
    index = d / "MEMORY.md"
    try:
        text = _read(index, 1 << 20).decode("utf-8")
    except FileNotFoundError:
        raise NotesError(f"{index} does not exist: no memory index to check") from None
    except (OSError, UnicodeDecodeError) as e:
        raise NotesError(f"{index}: cannot be read: {e}") from None
    missing, outside, linked = [], [], set()
    real_d = os.path.realpath(d)
    for angled, bare in LINK.findall(text):
        path = (angled or bare).split("#", 1)[0]
        if not path or "://" in path or path.startswith("mailto:"):
            continue
        path = unquote(path)
        if "\0" not in path and (os.path.isabs(path) or ".." in Path(path).parts   # a %00 names no file: missing
                                 or os.path.commonpath([real_d, os.path.realpath(d / path)]) != real_d):
            if path not in outside:
                outside.append(path)
            continue
        p = d / path
        if "\0" not in path and p.is_file():
            linked.add(os.path.realpath(p))
        elif path not in missing:
            missing.append(path)
    unlinked = sorted(p.name for p in d.glob("*.md")
                      if p.name != "MEMORY.md" and os.path.realpath(p) not in linked)
    return {"index": str(index), "missing": missing, "outside": outside, "unlinked": unlinked}


def counts(res: dict) -> dict:
    """What the steward's heartbeat carries: numbers only, never a path or a note's text."""
    return {"current": len(res["current"]), "stale": len(res["stale"]), "undeclared": len(res["undeclared"]),
            "malformed": len(res["malformed"])}


def lines(res: dict) -> list[str]:
    """The check in words, one finding a line; the last line is the count. Every name and reason passes through
    `_short` (S1): a file name holding an ESC or a bidi override is shown with `?` in its place."""
    def q(x: object) -> str:
        return _short(x, SAY)
    out = [f"always loaded: {q(r)} (read in every session here; not an area note)" for r in res["always_loaded"]]
    for s in res["stale"]:
        more = f" and {s['changed_count'] - len(s['changed'])} more" if s["changed_count"] > len(s["changed"]) else ""
        out.append(f"stale: {q(s['note'])} (checked {q(s['checked'])}): {s['changed_count']} file(s) changed since: "
                   f"{', '.join(q(c) for c in s['changed'])}{more}; re-read them, then `notes stamp {q(s['area'])}`")
    out += [f"undeclared: {q(r)}: its folder is not in {CONFIG} \"areas\"" for r in res["undeclared"]]
    out += [f"malformed: {q(m['note'])}: {q(m['why'])}" for m in res["malformed"]]
    mem = res.get("memory")
    if mem:
        out += [f"memory: {q(mem['index'])} links to {q(t)}, which is not there" for t in mem["missing"]]
        out += [f"memory: {q(mem['index'])} links to {q(t)}, outside the memory folder; never looked up"
                for t in mem["outside"]]
        out += [f"memory: {q(u)} is linked from no line of {q(mem['index'])}" for u in mem["unlinked"]]
    n, total = len(res["current"]), len(res["current"]) + len(res["stale"]) + len(res["malformed"])
    out.append(f"{n} area notes current" if res["ok"] else f"{n} of {total} area notes current")
    return out


def stamp(root: Path | str, area: str, *, tick: Callable[[], None] | None = None) -> dict:
    """Stamp `area`'s note as checked at HEAD, after someone re-read the area. Only its first line changes.

    `notes stamp AREA` (1.53 review C4: its own verb, so `check` never writes). S2: refused when the area's
    folder resolves outside the repository (a committed symlink) or the note is a symlink, so the write can
    never land outside the checkout.
    """
    top = _top(root, tick)
    declared = areas(top)
    ignore = ignored(top, declared)
    if area not in declared:
        raise NotesError(f"{_short(area, SAY)} is not a declared area ({', '.join(declared)})")
    rel = f"{area}/{NOTE}"
    p = top / rel
    real_top = os.path.realpath(top)
    if os.path.commonpath([real_top, os.path.realpath(p.parent)]) != real_top:
        raise NotesError(f"{area} resolves outside the repository (a symlinked folder); nothing is stamped there")
    if p.is_symlink():
        raise NotesError(f"{rel} is a symlink; only a regular file is stamped")
    try:
        data = _read(p, MAX_NOTE)
    except FileNotFoundError:
        raise NotesError(f"{rel} does not exist; write the note first") from None
    except OSError as e:
        raise NotesError(f"{rel}: {e}") from None
    sha, why = _parse(top, rel, area)
    if sha is None:
        raise NotesError(f"{rel}: {why}; only a well-formed note is stamped")
    rc, dirty = _git(top, ["status", "--porcelain", "-z", "--", *_pathspec(area, declared, ignore)], tick)
    if rc != 0 or dirty:
        raise NotesError(f"{area} has uncommitted changes; the stamp names a commit, so commit them first")
    rc, head = _git(top, ["rev-parse", "--short", "HEAD"], tick)
    if rc != 0:
        raise NotesError(f"{top} has no commit yet")
    _first, nl, rest = data.partition(b"\n")
    new = f"<!-- area: {area} · checked: {head.strip()} -->".encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".CLAUDE.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(new + nl + rest)
        os.chmod(tmp, os.stat(p).st_mode & 0o777)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return {"area": area, "note": rel, "was": sha, "checked": head.strip()}
