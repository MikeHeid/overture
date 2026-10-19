"""Agent worktrees (1.50.0, OPEN-DECISIONS.md "Agent worktrees", W1-W4): made, listed and pruned agent-side.

The console server starts no git and runs no project code (CONSOLE-kit/Q23,
Q24), so everything here runs in `agent.py`, in the agent's or the steward's
own process. The server is told only a branch name and a worktree's basename,
and shows them; it never sees a path.

- **Where (W1).** `~/.overture/worktrees/<project>/<branch>`, in the Linux home.
  A home under `/mnt/` (a Windows drive, from WSL) is refused: git there is
  slow. The branch is `overture/<kind>/<item>`, with `-2`, `-3` ... when
  another agent already has that one, cut from `origin/main` after a fetch (or
  the remote's default branch when there is no `main`, said so).
- **The registry.** `<project>/.registry.json` beside the worktrees: path,
  branch, item, kind, agent, created and base for each. Written to a temporary
  file and renamed over, under a lock; read tolerantly (a corrupt file reads as
  empty, and says so). It is never trusted over `git worktree list`: every
  `new`, `list` and `prune` reconciles the two first, dropping entries git no
  longer knows.
- **Pruning (W3).** Never with uncommitted changes, and never while a commit
  is on no remote. A worktree has LANDED when the one `gh pr list` of the
  cycle reports its PR merged AND that PR's head commit is the worktree's
  `HEAD` (a squash merge deletes the remote branch, but the PR's head is kept
  by the remote, so nothing is lost): it is removed and its local branch
  deleted only if it still points at that commit. A merged PR whose head is
  another commit (work after the merge, or a fork's branch of the same name)
  keeps the worktree. A closed, unmerged PR's worktree goes only when every
  commit is on some remote ref. Anything else is kept and the reason said.
  No `--force`, ever, no `branch -D`, and no remote branch is deleted. Only
  paths under `~/.overture/worktrees/<project>/` are ever acted on. One with
  no PR for 14 days is listed as stale and kept.
- **Overlap (W4).** Two agents on one item are warned about, never blocked.
- **Setup is never run.** A project's `worktree_setup` is read from the new
  worktree, checked (an argv list, no shell) and PRINTED as a suggested
  command; the agent runs it itself, through its own permission prompt. The
  branch it is read from is origin's, which a merged PR controls, so running
  it here would hand that PR the owner's account (lead ruling, 1.50 review S1).

Every process starts through `gitseam` (`git_full`, `gh`), so in the server,
where the seam is closed, nothing here can run.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
import tempfile
import time
from pathlib import Path
from typing import Callable

from . import gitseam as G
from . import names as N
from . import schema as S

KINDS = ("ticket", "visual", "ux", "playbook", "round", "fix")
BRANCH = re.compile(r"^overture/[a-z]+/[A-Za-z0-9._-]{1,120}\Z")    # the server's own check, word for word
BASENAME = re.compile(r"^[A-Za-z0-9._-]{1,120}\Z")                  # a worktree's last path part, as served
PROJECT = re.compile(r"[^A-Za-z0-9._-]+")
MAX_ITEM = 112           # room for "-NN" inside the branch's 120
MAX_SUFFIX = 99
STALE_DAYS = 14
DAY = 86400.0
REGISTRY = ".registry.json"
LOCK = ".registry.lock"
MAX_REGISTRY = 1 << 20
MAX_ENTRIES = 500
GIT_SECONDS = 120.0
MAX_STALE_REPORT = 12    # what fits the heartbeat file (doorbell.MAX_WATCH)
TS = "%Y-%m-%dT%H:%M:%SZ"
GH_LIMIT = 200           # the one `gh pr list` of a cycle: the newest PRs of the repository, every state
GH_FIELDS = "number,state,headRefName,headRefOid"
OID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")

# branch -> a PR {"number", "state", "oid"?} or a list of them | None (no PR) | a string (why it is unknown)
PrLookup = Callable[[str], "dict | list | None | str"]


class WorktreeError(ValueError):
    """Refused, by name; nothing was made or removed."""


# -- small helpers -----------------------------------------------------------------------------------

def _git(args: list[str], cwd: Path | str, timeout: float = GIT_SECONDS) -> tuple[int, str, str]:
    """git ARGS through the seam. The one place this module starts git (tests watch it for `--force`)."""
    r = G.git_full(args, cwd, timeout=timeout)
    if isinstance(r, G.Unavailable):
        raise WorktreeError(G.UNAVAILABLE)
    return r


def _left(deadline: float | None) -> float:
    """A git call's timeout: GIT_SECONDS, or what is left of a cycle's budget (at least a second)."""
    if deadline is None:
        return GIT_SECONDS
    return max(1.0, min(GIT_SECONDS, deadline - time.monotonic()))


def _out(args: list[str], cwd: Path | str, deadline: float | None = None) -> str | None:
    rc, out, _err = _git(args, cwd, _left(deadline))
    return out if rc == 0 else None


def _first_line(text: str) -> str:
    for ln in (text or "").splitlines():
        if ln.strip():
            return ln.strip()[:300]
    return ""


def _ts(t: float) -> str:
    return time.strftime(TS, time.gmtime(t))


def _parse_ts(v: object) -> float | None:
    if not isinstance(v, str):
        return None
    try:
        import calendar
        return float(calendar.timegm(time.strptime(v, TS)))
    except ValueError:
        return None


def kind_problem(kind: object) -> str | None:
    if kind not in KINDS:
        return f"kind {kind!r} is not one of {', '.join(KINDS)}"
    return None


def item_problem(item: object) -> str | None:
    """Why `item` cannot name a branch: the server's item id rules, and git's ref rules on top."""
    if not isinstance(item, str) or not S.ITEM_ID.match(item):
        return f"item {item!r} is not an item id (letters, digits, '_.-', starting with a letter or digit)"
    if len(item) > MAX_ITEM:
        return f"item {item!r} is over {MAX_ITEM} characters, too long for a branch name"
    if ".." in item or item.endswith(".lock") or item.endswith("."):
        return f"item {item!r} cannot be a git branch name ('..', a trailing '.' or '.lock')"
    return None


def branch_name(kind: str, item: str, n: int = 1) -> str:
    return f"overture/{kind}/{item}" + ("" if n == 1 else f"-{n}")


def parse_branch(branch: str) -> tuple[str, str] | None:
    """(kind, last part) of an `overture/<kind>/...` branch, for a worktree the registry lacks; None otherwise.

    Best effort only: `overture/ticket/API-2` may be item API-2 or API's second
    branch, so the registry's own `item` is what everything else uses.
    """
    if not isinstance(branch, str) or not BRANCH.match(branch):
        return None
    _o, kind, rest = branch.split("/", 2)
    return kind, rest


def project_slug(name: str, main: Path | str) -> str:
    """The console's project name as one safe path part, plus the first 8 hex of the sha256 of the main
    checkout's real path: two repositories in folders of the same name never share a registry (1.50 review C5)."""
    s = PROJECT.sub("-", name or "").strip(".-")[:64].strip(".-") or "project"
    return s + "-" + hashlib.sha256(os.fsencode(os.path.realpath(main))).hexdigest()[:8]


def _under(real: str, top: str) -> bool:
    return real == top or real.startswith(top.rstrip(os.sep) + os.sep)


def _refuse_elsewhere(d: Path, home_real: str) -> None:
    """Refused when `d`, links followed, lands under /mnt/ or outside the user's home (1.50 review S4)."""
    real = os.path.realpath(d)   # checked before anything is made, so a link elsewhere is never followed
    if _under(real, "/mnt"):
        raise WorktreeError(f"refused: {d} resolves to {real}, under /mnt/ (a symlink to a Windows drive?); agent "
                            f"worktrees live in the Linux home")
    if not _under(real, home_real):
        raise WorktreeError(f"refused: {d} resolves to {real}, outside your home {home_real} (a symlink?); agent "
                            f"worktrees live in ~/.overture/worktrees itself")


def base_dir(home: Path | None = None) -> Path:
    """`~/.overture/worktrees`, refused when the home resolves under /mnt/ (W1) or the folder leads out of it."""
    h = Path(home) if home is not None else Path.home()
    real = os.path.realpath(h)
    if _under(real, "/mnt"):
        raise WorktreeError(f"refused: your home resolves to {real}, under /mnt/ (a Windows drive under WSL, where "
                            f"git is slow); agent worktrees live in the Linux home. Run from a Linux HOME")
    d = Path(real) / ".overture" / "worktrees"
    _refuse_elsewhere(d, real)
    return d


def _project_dir(home: Path | None, project: str, main: Path, create: bool) -> Path:
    base = base_dir(home)
    d = base / project_slug(project, main)
    _refuse_elsewhere(d, os.path.realpath(base.parent.parent))
    if create:
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def worktree_path(project_dir: Path, branch: str) -> Path:
    return project_dir.joinpath(*branch.split("/"))


def main_checkout(d: Path | str) -> Path | None:
    """The main checkout of the repository holding `d` (itself, or the one a linked worktree belongs to)."""
    out = _out(["rev-parse", "--path-format=absolute", "--git-common-dir"], d)
    if not out or not out.strip():
        return None
    common = Path(out.strip())
    if common.name != ".git":
        return None   # a bare repository, or a separate git dir: not supported
    return Path(os.path.realpath(common.parent))


def git_worktrees(main: Path) -> dict[str, str | None]:
    """Every worktree git knows for this repository: {real path: branch name or None (detached)}."""
    out = _out(["worktree", "list", "--porcelain"], main)
    if out is None:
        raise WorktreeError(f"refused: `git worktree list` failed in {main}")
    found: dict[str, str | None] = {}
    path: str | None = None
    for ln in out.splitlines() + [""]:
        if ln.startswith("worktree "):
            path = os.path.realpath(ln[len("worktree "):])
            found[path] = None
        elif ln.startswith("branch ") and path is not None:
            ref = ln[len("branch "):]
            found[path] = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
        elif not ln:
            path = None
    return found


# -- the registry ------------------------------------------------------------------------------------

def _entry_ok(e: object) -> bool:
    return (isinstance(e, dict) and isinstance(e.get("path"), str) and os.path.isabs(e["path"])
            and isinstance(e.get("branch"), str) and BRANCH.match(e["branch"]) is not None
            and isinstance(e.get("item"), str) and item_problem(e["item"]) is None
            and e.get("kind") in KINDS and isinstance(e.get("agent"), str)
            and (e["agent"] == N.UNNAMED or N.problem(e["agent"]) is None)
            and isinstance(e.get("created"), str) and _parse_ts(e["created"]) is not None)


def read_registry(project_dir: Path) -> tuple[list[dict], str | None]:
    """(entries, problem). Missing: ([], None). Corrupt or unsafe: ([], why): tolerated, never fatal."""
    p = Path(project_dir) / REGISTRY
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return [], None
    except OSError as e:
        return [], f"the registry {p} cannot be read ({e.strerror or e}); it is rebuilt from git"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_REGISTRY:
            return [], f"the registry {p} is not a small regular file; it is rebuilt from git"
        raw = os.read(fd, MAX_REGISTRY + 1)
    finally:
        os.close(fd)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return [], f"the registry {p} is not JSON; it is rebuilt from git"
    rows = doc.get("worktrees") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return [], f"the registry {p} has no worktree list; it is rebuilt from git"
    good = [dict(e) for e in rows[:MAX_ENTRIES] if _entry_ok(e)]
    return good, (None if len(good) == len(rows) else
                  f"the registry {p} had {len(rows) - len(good)} unreadable entr{'y' if len(rows) - len(good) == 1 else 'ies'}, dropped")


def write_registry(project_dir: Path, entries: list[dict]) -> None:
    """Replace the registry atomically: a temporary file in the same folder, fsync'd, renamed over."""
    d = Path(project_dir)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = json.dumps({"worktrees": entries[:MAX_ENTRIES]}, indent=1, sort_keys=True).encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".registry.", suffix=".tmp")   # 0600 from creation
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, d / REGISTRY)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def _locked(project_dir: Path):
    """One writer at a time across agents: an exclusive lock on `.registry.lock` beside the registry."""
    fd = os.open(Path(project_dir) / LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _reconcile(project_dir: Path, main: Path) -> tuple[list[dict], list[dict], list[str], dict[str, str | None]]:
    """(live registered entries, unregistered worktrees under the project dir, notes, git's list).

    Git wins: a registry entry whose path git no longer lists as a worktree of
    this repository is dropped (and said); a worktree git lists under the
    project dir that the registry lacks is reported with what its branch says.
    """
    entries, problem = read_registry(project_dir)
    notes = [problem] if problem else []
    known = git_worktrees(main)
    top = os.path.realpath(project_dir)
    live, gone, outside = [], [], []
    for e in entries:
        real = os.path.realpath(e["path"])
        if not real.startswith(top + os.sep):   # S5: only what lies under this project's folder is ours
            outside.append(e)
        else:
            (live if real in known and os.path.realpath(main) != real else gone).append(e)
    for e in gone:
        notes.append(f"gone: {e['branch']} is no longer a worktree of this repository; dropped from the registry")
    for e in outside:
        notes.append(f"outside: {e['branch']} was registered at a path outside {top}; dropped from the registry, "
                     f"and nothing there is touched")
    gone += outside
    have = {os.path.realpath(e["path"]) for e in live}
    loose = []
    for path, branch in sorted(known.items()):
        if path.startswith(top + os.sep) and path not in have:
            parsed = parse_branch(branch or "")
            loose.append({"path": path, "branch": branch or "(detached)", "item": parsed[1] if parsed else None,
                          "kind": parsed[0] if parsed else None, "agent": None, "created": None, "base": None,
                          "registered": False})
    if gone or problem:
        write_registry(project_dir, live)
    return live, loose, notes, known


# -- new -----------------------------------------------------------------------------------------------

def _base_ref(main: Path) -> tuple[str, str | None]:
    """(the ref to branch from, a note when it is not origin/main). Refused when origin has neither."""
    if _git(["rev-parse", "--verify", "--quiet", "refs/remotes/origin/main"], main)[0] == 0:
        return "origin/main", None
    head = _out(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], main)
    name = head.strip() if head and head.strip().startswith("origin/") else None
    if name is None:
        rc, out, _err = _git(["ls-remote", "--symref", "origin", "HEAD"], main)
        m = re.search(r"^ref: refs/heads/(\S+)\s+HEAD$", out or "", re.M) if rc == 0 else None
        name = f"origin/{m.group(1)}" if m else None
    if name and _git(["rev-parse", "--verify", "--quiet", f"refs/remotes/{name}"], main)[0] == 0:
        return name, (f"origin has no main branch, so this branched from {name}, the repository's default branch")
    raise WorktreeError("refused: origin has no main branch and no default branch this can find; fetch it, or set "
                        "one with `git remote set-head origin --auto`")


def _setup_suggestion(path: Path) -> dict | None:
    """The project's `worktree_setup`, read from the NEW worktree's .overture.json and checked: NEVER run here.

    Lead ruling (1.50 review S1): the file comes from origin's branch, which any
    merged PR controls, so running it would give that PR the owner's account
    without a single prompt. It is printed instead, for the agent to run itself
    through its own Bash tool, where the user is asked first.
    """
    from . import projectcfg as PC
    try:
        argv = PC.load(path).worktree_setup
    except PC.ConfigError as e:
        return {"ran": False, "argv": None, "command": None, "note": f"worktree_setup ignored: {e}"}
    if not argv:
        return None
    command = "cd " + shlex.quote(str(path)) + " && " + shlex.join(argv)
    return {"ran": False, "argv": list(argv), "command": command,
            "note": "This project suggests a setup step; run it yourself in the worktree (Overture never runs it): "
                    + command}


def _overlap(live: list[dict], item: str, bucket: str, mine: str) -> list[dict]:
    return [{"branch": e["branch"], "agent": e["agent"], "kind": e["kind"]}
            for e in live if e["item"] == item and e["branch"] != mine and e["agent"] != bucket]


NAME_NEEDED = ("refused: `worktree new` needs this session's agent name, so the worktree, its marks and any overlap "
               "warning are this session's own (unnamed sessions would share one worktree). Name it as for `agent.py "
               "working`: `agent.py --as agent-N ...` before the subcommand, OVERTURE_AGENT=agent-N, or "
               "/overture:as agent-N in the session")


def _head(path: str, deadline: float | None = None) -> str | None:
    out = _out(["rev-parse", "--verify", "--quiet", "HEAD"], path, deadline)
    sha = (out or "").strip()
    return sha if OID.match(sha) else None


def new(repo: Path | str, project: str, kind: str, item: str, agent: str | None, *, home: Path | None = None,
        now: float | None = None, prs: PrLookup | None | bool = True) -> dict:
    """Make (or, for the same agent, kind and item, return) this agent's worktree for ITEM. Raises WorktreeError.

    `prs` is asked only when this agent already has a worktree for the item: one whose PR merged or closed is
    never handed back (1.50 review C3); a fresh `-N` one is made and the old one left for `prune`.
    """
    why = kind_problem(kind) or item_problem(item)
    if why:
        raise WorktreeError(f"refused: {why}")
    if not agent or agent == N.UNNAMED:
        raise WorktreeError(NAME_NEEDED)
    if N.problem(agent):
        raise WorktreeError(f"refused: {N.problem(agent)}")
    bucket = agent
    main = main_checkout(repo)
    if main is None:
        raise WorktreeError(f"refused: {repo} is not inside a git repository with a .git folder")
    if _out(["remote", "get-url", "origin"], main) is None:
        raise WorktreeError(f"refused: {main} has no remote named origin to branch from")
    pdir = _project_dir(home, project, main, create=True)
    t = time.time() if now is None else now
    notes: list[str] = []
    with _locked(pdir):
        live, _loose, rnotes, known = _reconcile(pdir, main)
        notes += rnotes
        mine = [e for e in live if e["item"] == item and e["kind"] == kind and e["agent"] == bucket]
        if mine and prs is True:
            prs, gh_why = gh_prs(main)
            if gh_why:
                notes.append(f"{gh_why}; your worktree is handed back without knowing whether its PR landed")
        for e in mine:
            pr = _pick_pr(prs(e["branch"]) if callable(prs) else None, _head(e["path"]))
            if pr and pr["state"] in ("merged", "closed"):
                notes.append(f"your earlier worktree for {kind} {item}, on {e['branch']}, has PR #{pr['number']} "
                             f"{pr['state']}: it is never reused, and waits for `agent.py worktree prune`; this is "
                             f"a fresh one")
                continue
            return {"path": e["path"], "branch": e["branch"], "worktree": Path(e["path"]).name, "kind": kind,
                    "item": item, "agent": bucket, "created": e["created"], "base": e.get("base"),
                    "reused": True, "overlap": _overlap(live, item, bucket, e["branch"]), "notes": notes,
                    "setup": None}
        rc, _o, err = _git(["fetch", "--quiet", "origin"], main)
        if rc != 0:
            notes.append(f"git fetch origin failed ({_first_line(err) or f'exit {rc}'}); branched from what was "
                         f"last fetched")
        base, note = _base_ref(main)
        if note:
            notes.append(note)
        held = {e["branch"] for e in live} | {b for b in known.values() if b}
        branch = path = None
        for n in range(1, MAX_SUFFIX + 1):
            cand = branch_name(kind, item, n)
            p = worktree_path(pdir, cand)
            if cand in held or os.path.realpath(p) in known:
                continue
            if _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{cand}"], main)[0] == 0:
                continue   # a branch left from an earlier worktree: never reused, never deleted here
            if os.path.lexists(p):
                raise WorktreeError(f"refused: {p} exists and is not a registered worktree of this repository; "
                                    f"look at it, and move it aside if it is stale")
            branch, path = cand, p
            break
        if branch is None:
            raise WorktreeError(f"refused: {MAX_SUFFIX} branches for {kind} {item} already exist")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        rc, _o, err = _git(["worktree", "add", "--no-track", "-b", branch, str(path), base], main, timeout=600)
        if rc != 0:
            raise WorktreeError(f"refused: git worktree add failed: {_first_line(err) or f'exit {rc}'}")
        entry = {"path": str(path), "branch": branch, "item": item, "kind": kind, "agent": bucket,
                 "created": _ts(t), "base": base}
        write_registry(pdir, [*live, entry])
        overlap = _overlap(live, item, bucket, branch)
    setup = _setup_suggestion(path)
    if setup is not None:
        notes.append(setup["note"])
    return {**{k: entry[k] for k in ("path", "branch", "kind", "item", "agent", "created", "base")},
            "worktree": path.name, "reused": False, "overlap": overlap, "notes": notes, "setup": setup}


# -- list ------------------------------------------------------------------------------------------------

def gh_prs(main: Path) -> tuple[PrLookup | None, str | None]:
    """ONE `gh pr list` for the whole repository, keyed by head branch, or (None, why) when gh cannot say.

    1.50 review C2: one call per cycle, never one per worktree. Every state, the newest GH_LIMIT PRs, with
    each PR's head commit (`headRefOid`), which is what tells a landed worktree from a fork's PR that only
    shares its branch name (C1).
    """
    r = G.gh(["pr", "list", "--state", "all", "--limit", str(GH_LIMIT), "--json", GH_FIELDS], main)
    if isinstance(r, G.Unavailable):
        return None, G.UNAVAILABLE
    rc, out, err = r
    if rc == 127:
        return None, "gh (the GitHub CLI) is not available, so no PR state is known"
    if rc != 0:
        return None, f"gh pr list failed ({_first_line(err) or f'exit {rc}'}), so no PR state is known"
    try:
        rows = json.loads(out or "[]")
    except ValueError:
        return None, "gh pr list printed something that is not JSON, so no PR state is known"
    if not isinstance(rows, list):
        return None, "gh pr list printed no list, so no PR state is known"
    by: dict[str, list[dict]] = {}
    for row in rows:
        if not (isinstance(row, dict) and isinstance(row.get("number"), int) and isinstance(row.get("state"), str)
                and isinstance(row.get("headRefName"), str)):
            continue
        oid = row.get("headRefOid")
        by.setdefault(row["headRefName"], []).append(
            {"number": row["number"], "state": row["state"].lower(),
             "oid": oid if isinstance(oid, str) and OID.match(oid) else None})
    return (lambda branch: by.get(branch)), None


def _pick_pr(got: object, head: str | None) -> dict | None:
    """The PR that speaks for this worktree: the one whose head commit is its HEAD, else an open one, else the
    newest. A lookup may give one PR (a dict) or several (a list); None or nothing usable: no PR."""
    rows = got if isinstance(got, list) else [got] if isinstance(got, dict) else []
    norm = [{"number": r["number"], "state": r["state"].lower(),
             "oid": r.get("oid") if isinstance(r.get("oid"), str) else None}
            for r in rows if isinstance(r, dict) and isinstance(r.get("number"), int)
            and isinstance(r.get("state"), str)]
    if not norm:
        return None
    return max(norm, key=lambda r: (head is not None and r["oid"] == head, r["state"] == "open", r["number"]))


def _int(out: str | None) -> int | None:
    try:
        return int((out or "").strip())
    except ValueError:
        return None


def status(e: dict, now: float, prs: PrLookup | None, deadline: float | None = None) -> dict:
    """One worktree's state: last commit, ahead/behind, dirty, unpushed, PR and stale. Reads only."""
    path = e["path"]
    row = {k: e.get(k) for k in ("path", "branch", "item", "kind", "agent", "created", "base")}
    row["registered"] = e.get("registered", True)
    last = _out(["log", "-1", "--format=%H%x1f%ct%x1f%s"], path, deadline)
    if last and last.count("\x1f") >= 2:
        sha, ct, subj = last.rstrip("\n").split("\x1f", 2)
        row["last_commit"] = {"sha": sha[:12], "at": _ts(float(ct)) if ct.isdigit() else None, "subject": subj[:200]}
        row["head"] = sha if OID.match(sha) else None
    else:
        row["last_commit"] = row["head"] = None
    row["ahead"] = row["behind"] = None
    if e.get("base"):
        lr = _out(["rev-list", "--left-right", "--count", f"{e['base']}...HEAD"], path, deadline)
        parts = (lr or "").split()
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            row["behind"], row["ahead"] = int(parts[0]), int(parts[1])
    st = _out(["status", "--porcelain", "--untracked-files=normal"], path, deadline)
    row["dirty"] = None if st is None else bool(st.strip())
    row["unpushed"] = _int(_out(["rev-list", "--count", "HEAD", "--not", "--remotes"], path, deadline))
    if prs is None:
        row["pr"], row["pr_unknown"] = None, "gh is not available"
    elif not BRANCH.match(e["branch"] or ""):
        row["pr"], row["pr_unknown"] = None, "not on an overture/ branch"
    else:
        got = prs(e["branch"])
        if isinstance(got, str):
            row["pr"], row["pr_unknown"] = None, got
        else:
            row["pr"], row["pr_unknown"] = _pick_pr(got, row["head"]), None
    row["landed"] = bool(row["pr"] and row["pr"]["state"] == "merged" and row["head"]
                         and row["pr"]["oid"] == row["head"])
    created = _parse_ts(e.get("created"))
    if created is None:
        with contextlib.suppress(OSError):
            created = os.stat(path).st_mtime
    row["age_days"] = int((now - created) // DAY) if created is not None else None
    row["stale"] = bool(row["pr"] is None and row["pr_unknown"] is None and created is not None
                        and now - created >= STALE_DAYS * DAY)
    return row


def list_worktrees(repo: Path | str, project: str, *, home: Path | None = None, now: float | None = None,
                   prs: PrLookup | None | bool = True, deadline: float | None = None,
                   start_after: str | None = None) -> dict:
    """Every worktree under `~/.overture/worktrees/<project>/`, reconciled with git, with its state.

    `prs`: True looks PRs up through gh, in one call (degrading to "unknown" without it); a callable is used
    as the lookup (tests, and the steward's watch, which made its one call already); None means no PR state is
    known. `deadline` (time.monotonic) stops it early, at least one worktree in, and `unfinished` then names
    the last branch looked at; `start_after` takes up from there (worktrees are looked at in branch order).
    """
    main = main_checkout(repo)
    if main is None:
        raise WorktreeError(f"refused: {repo} is not inside a git repository with a .git folder")
    pdir = _project_dir(home, project, main, create=False)
    t = time.time() if now is None else now
    notes: list[str] = []
    slug = project_slug(project, main)
    if prs is True:
        prs, why = gh_prs(main)
        if why:
            notes.append(why)
    if not pdir.is_dir():
        return {"project": slug, "worktrees": [], "notes": notes, "gh": prs is not None, "unfinished": None}
    with _locked(pdir):
        live, loose, rnotes, _known = _reconcile(pdir, main)
    notes += rnotes
    todo = sorted([*live, *loose], key=lambda e: e["branch"] or "")
    if start_after:
        todo = [e for e in todo if (e["branch"] or "") > start_after]
    rows: list[dict] = []
    unfinished = None
    for e in todo:
        if deadline is not None and rows and time.monotonic() >= deadline:
            unfinished = rows[-1]["branch"]
            break
        rows.append(status(e, t, prs, deadline))
    return {"project": slug, "worktrees": rows, "notes": notes, "gh": prs is not None, "unfinished": unfinished}


def stale_summary(listing: dict) -> list[dict]:
    """What the console is told about stale worktrees: branch, age and agent only, never a path."""
    out = []
    for r in listing.get("worktrees", []):
        if r.get("stale") and isinstance(r.get("branch"), str) and BRANCH.match(r["branch"]):
            row = {"branch": r["branch"], "age_days": int(r["age_days"] or 0)}
            if isinstance(r.get("agent"), str) and (r["agent"] == N.UNNAMED or N.problem(r["agent"]) is None):
                row["agent"] = r["agent"]
            out.append(row)
    return out[:MAX_STALE_REPORT]


# -- prune -----------------------------------------------------------------------------------------------

def _keep_reason(r: dict) -> str | None:
    """Why this worktree stays, or None when every rule for removing it holds (W3; 1.50 review C1)."""
    if r.get("pr_unknown"):
        return f"PR state unknown ({r['pr_unknown']})"
    pr = r.get("pr")
    if pr is None:
        return (f"no PR, {r['age_days']} days old: stale, listed in the console and kept" if r.get("stale")
                else "no PR yet")
    if pr["state"] not in ("merged", "closed"):
        return f"PR #{pr['number']} is {pr['state']}"
    if r.get("dirty") is None:
        return "its status cannot be read"
    if r["dirty"]:
        return "it has uncommitted changes"
    if pr["state"] == "merged":
        # Landed: the PR merged AND its head commit is this worktree's HEAD, so every commit here is on the
        # remote (the PR keeps its head even after a squash merge deletes the branch). Anything else is kept.
        if r.get("landed"):
            return None
        if not r.get("head"):
            return f"PR #{pr['number']} merged, but this worktree's HEAD cannot be read"
        if not pr.get("oid"):
            return (f"PR #{pr['number']} merged, but gh did not say at which commit, so whether this worktree "
                    f"landed is unknown")
        return (f"PR #{pr['number']} merged at {pr['oid'][:12]}, but this worktree is at {r['head'][:12]}: "
                f"commits after the merge, or another repository's branch of the same name (remove it by hand "
                f"when you are sure)")
    # Closed, never merged: only when every commit is on some remote ref (W3: unpushed commits always block).
    if r.get("unpushed") is None:
        return "cannot tell whether every commit is on a remote"
    if r["unpushed"]:
        return (f"{r['unpushed']} commit{'s' if r['unpushed'] != 1 else ''} on no remote ref (push them, or remove "
                f"it by hand)")
    return None


def prune(repo: Path | str, project: str, *, dry_run: bool = False, home: Path | None = None,
          now: float | None = None, prs: PrLookup | None | bool = True, budget: float | None = None,
          start_after: str | None = None) -> dict:
    """Remove the worktrees W3 allows; keep and explain the rest. Never `--force`, never a remote branch.

    `budget` (seconds) caps the looking; what is left is named in `unfinished`, for `start_after` next time.
    """
    deadline = None if budget is None else time.monotonic() + budget
    listing = list_worktrees(repo, project, home=home, now=now, prs=prs, deadline=deadline,
                             start_after=start_after)
    main = main_checkout(repo)
    removed, kept, notes = [], [], list(listing["notes"])
    if not listing["gh"]:
        notes.append("without gh no PR state is known, so every worktree is kept")
    pdir = _project_dir(home, project, main, create=False)
    top = os.path.realpath(pdir)
    for r in listing["worktrees"]:
        why = _keep_reason(r)
        if why is None and not r.get("registered", True):
            why = "not in the registry (made by hand?); remove it with git worktree remove"
        if why is None and not os.path.realpath(r["path"]).startswith(top + os.sep):
            why = f"its path is outside {top}; prune acts only there"   # S5: never reached through the registry
        if why:
            kept.append({"branch": r["branch"], "item": r.get("item"), "why": why, "stale": bool(r.get("stale"))})
            continue
        if dry_run:
            removed.append({"branch": r["branch"], "item": r.get("item"), "dry_run": True})
            continue
        why = _remove(pdir, main, r)
        if why:
            kept.append({"branch": r["branch"], "item": r.get("item"), "why": why, "stale": False})
            continue
        gone = {"branch": r["branch"], "item": r.get("item"), "landed": bool(r.get("landed"))}
        if r.get("landed"):
            # Only if the branch still points at the commit that landed: never `branch -D`, never a guess.
            rc, _o, err = _git(["update-ref", "-d", f"refs/heads/{r['branch']}", r["head"]], main)
        else:
            rc, _o, err = _git(["branch", "-d", r["branch"]], main)   # -d: git refuses an unmerged branch
        if rc != 0:
            gone["branch_kept"] = _first_line(err) or f"exit {rc}"
        removed.append(gone)
        _tidy(pdir, Path(r["path"]))
    if listing["unfinished"]:
        notes.append(f"stopped after {budget:g} s, at {listing['unfinished']}; the rest is looked at next time")
    return {"project": listing["project"], "removed": removed, "kept": kept,
            "stale": stale_summary(listing), "notes": notes, "gh": listing["gh"], "dry_run": dry_run,
            "unfinished": listing["unfinished"]}


def _remove(pdir: Path, main: Path, r: dict) -> str | None:
    """`git worktree remove` (never --force), under the registry lock, after looking again: None when removed.

    1.50 review L2: an agent may have written into it since it was judged, so it is judged clean and at the
    same commit once more, right before the remove, and the reason is said when that no longer holds.
    """
    with _locked(pdir):
        st = _out(["status", "--porcelain", "--untracked-files=normal"], r["path"])
        if st is None:
            return "its status cannot be read now; kept"
        if st.strip():
            return "it has uncommitted changes now (written while prune ran); kept"
        if _head(r["path"]) != r.get("head"):
            return "its HEAD moved while prune ran (a new commit?); kept, and looked at again next time"
        rc, _o, err = _git(["worktree", "remove", r["path"]], main)
        if rc != 0:
            return f"git worktree remove refused: {_first_line(err) or f'exit {rc}'}"
        entries, _p = read_registry(pdir)
        write_registry(pdir, [e for e in entries if os.path.realpath(e["path"]) != os.path.realpath(r["path"])])
    return None


def _tidy(pdir: Path, path: Path) -> None:
    """Remove the now-empty folders between a removed worktree and the project dir (never anything else)."""
    top = os.path.realpath(pdir)
    p = path.parent
    while os.path.realpath(p).startswith(top + os.sep):
        try:
            p.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            return    # not empty (another worktree's folder), or not ours to remove
        p = p.parent


# -- where am I ----------------------------------------------------------------------------------------

def registered_here(cwd: Path | str, home: Path | None = None) -> dict | None:
    """The registry entry of the agent worktree holding `cwd`, with its CURRENT branch, or None.

    For `agent.py working`: only a worktree in a registry under
    `~/.overture/worktrees/` counts, and the branch sent is the one checked out
    now, and only when it has the shape the server accepts.
    """
    try:
        root = base_dir(home)
    except WorktreeError:
        return None
    top = _out(["rev-parse", "--show-toplevel"], cwd)
    if not top or not top.strip():
        return None
    real = os.path.realpath(top.strip())
    if not real.startswith(os.path.realpath(root) + os.sep) or not root.is_dir():
        return None
    for reg in sorted(root.glob(f"*/{REGISTRY}")):
        entries, _p = read_registry(reg.parent)
        for e in entries:
            if os.path.realpath(e["path"]) == real:
                head = _out(["rev-parse", "--abbrev-ref", "HEAD"], real)
                branch = head.strip() if head else ""
                if not BRANCH.match(branch):
                    return None
                name = Path(real).name
                return {**e, "branch": branch, "worktree": name if BASENAME.match(name) else None}
    return None
