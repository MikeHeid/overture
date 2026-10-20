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
  itself and any nested declared area left out). When the commit is not in
  this branch's history (a squash merge leaves the branch's commits behind),
  the note's own last commit is the base instead;
- undeclared: a CLAUDE.md below the root in a folder not on the list (the
  sprawl gate); files git ignores are never looked at;
- malformed: no header, a header naming another folder, a commit that cannot
  be found, or more than MAX_LINES lines;
- with `memory`, the auto-memory index MEMORY.md in that folder: links to
  files that are not there, and *.md files no line links.

`update` rewrites one note's header to HEAD after someone re-read the area,
and changes nothing else in the file.

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

from . import gitseam as G

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
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


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


def areas(root: Path) -> list[str]:
    """The declared area roots, from the repository's `.overture.json` "areas"; refused by name when unusable."""
    try:
        doc = json.loads(_read(Path(root) / CONFIG, MAX_CONFIG).decode("utf-8"))
    except FileNotFoundError:
        doc = {}
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as e:
        raise NotesError(f"{CONFIG}: cannot be read: {e}") from None
    got = doc.get("areas") if isinstance(doc, dict) else None
    if got is None:
        raise NotesError(f"{root} declares no areas ({CONFIG} \"areas\": a list of folders that may hold a note)")
    if not (isinstance(got, list) and 0 < len(got) <= MAX_AREAS and all(
            isinstance(a, str) and AREA.match(a) and ".." not in a.split("/") and "." not in a.split("/")
            for a in got)) or len(set(got)) != len(got):
        raise NotesError(f"{CONFIG}: areas must be 1 to {MAX_AREAS} distinct relative folders inside the "
                         f"repository (no '.', '..' or leading '/'), e.g. [\"docs\", \"src/server\"]")
    return list(got)


def _pathspec(area: str, declared: list[str]) -> list[str]:
    """The area's files: its folder, less its own note and any nested declared area (which has its own)."""
    return [area, f":(exclude){area}/{NOTE}", *(f":(exclude){d}" for d in declared if d.startswith(area + "/"))]


def _base(root: Path, sha: str, note_rel: str, tick) -> tuple[str | None, str]:
    """(commit to measure from, where it came from): the checked commit when this branch holds it, else the
    note's own last commit; (None, why) when there is neither."""
    rc, full = _git(root, ["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"], tick)
    if rc == 0 and _git(root, ["merge-base", "--is-ancestor", full.strip(), "HEAD"], tick)[0] == 0:
        return full.strip(), "checked"
    rc, last = _git(root, ["log", "-1", "--format=%H", "--", note_rel], tick)
    if rc == 0 and last.strip():
        return last.strip(), "note-commit"
    return None, (f"checked commit {sha} is not in this branch's history, and the note was never committed, so "
                  f"nothing says what it was checked against")


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
    if m["area"] != area:
        return None, f"its header names {m['area']}, but it sits in {area}"
    return m["sha"], None


def check(root: Path | str, *, memory: Path | str | None = None, tick: Callable[[], None] | None = None) -> dict:
    """Every note under `root` (the top of a git checkout) judged; see the module docstring. Never writes."""
    top = _top(root, tick)
    declared = areas(top)
    rc, head = _git(top, ["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], tick)
    if rc != 0:
        raise NotesError(f"{top} has no commit yet")
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
                             *_pathspec(area, declared)], tick)
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
                     or (res["memory"] and (res["memory"]["missing"] or res["memory"]["unlinked"])))
    return res


def memory_index(folder: Path | str) -> dict:
    """The auto-memory index MEMORY.md in `folder`: links to missing files, and *.md files no line links."""
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
    missing, linked = [], set()
    for target in LINK.findall(text):
        path = target.split("#", 1)[0]
        if not path or "://" in path or path.startswith("mailto:"):
            continue
        p = d / path
        if p.is_file():
            linked.add(os.path.realpath(p))
        elif path not in missing:
            missing.append(path)
    unlinked = sorted(p.name for p in d.glob("*.md")
                      if p.name != "MEMORY.md" and os.path.realpath(p) not in linked)
    return {"index": str(index), "missing": missing, "unlinked": unlinked}


def counts(res: dict) -> dict:
    """What the steward's heartbeat carries: numbers only, never a path or a note's text."""
    return {"current": len(res["current"]), "stale": len(res["stale"]), "undeclared": len(res["undeclared"]),
            "malformed": len(res["malformed"])}


def lines(res: dict) -> list[str]:
    """The check in words, one finding a line; the last line is the count."""
    out = [f"always loaded: {r} (read in every session here; not an area note)" for r in res["always_loaded"]]
    for s in res["stale"]:
        more = f" and {s['changed_count'] - len(s['changed'])} more" if s["changed_count"] > len(s["changed"]) else ""
        out.append(f"stale: {s['note']} (checked {s['checked']}): {s['changed_count']} file(s) changed since: "
                   f"{', '.join(s['changed'])}{more}; re-read them, then `notes check --update {s['area']}`")
    out += [f"undeclared: {r}: its folder is not in {CONFIG} \"areas\"" for r in res["undeclared"]]
    out += [f"malformed: {m['note']}: {m['why']}" for m in res["malformed"]]
    mem = res.get("memory")
    if mem:
        out += [f"memory: {mem['index']} links to {t}, which is not there" for t in mem["missing"]]
        out += [f"memory: {u} is linked from no line of {mem['index']}" for u in mem["unlinked"]]
    n, total = len(res["current"]), len(res["current"]) + len(res["stale"]) + len(res["malformed"])
    out.append(f"{n} area notes current" if res["ok"] else f"{n} of {total} area notes current")
    return out


def update(root: Path | str, area: str, *, tick: Callable[[], None] | None = None) -> dict:
    """Stamp `area`'s note as checked at HEAD, after someone re-read the area. Only its first line changes."""
    top = _top(root, tick)
    declared = areas(top)
    if area not in declared:
        raise NotesError(f"{area} is not a declared area ({', '.join(declared)})")
    rel = f"{area}/{NOTE}"
    p = top / rel
    try:
        data = _read(p, MAX_NOTE)
    except FileNotFoundError:
        raise NotesError(f"{rel} does not exist; write the note first") from None
    except OSError as e:
        raise NotesError(f"{rel}: {e}") from None
    sha, why = _parse(top, rel, area)
    if sha is None:
        raise NotesError(f"{rel}: {why}; only a well-formed note is stamped")
    rc, dirty = _git(top, ["status", "--porcelain", "-z", "--", *_pathspec(area, declared)], tick)
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
