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
- **Pruning (W3).** Only a worktree whose PR is merged or closed, with no
  uncommitted changes, and every commit on some remote ref. Anything else is
  kept and the reason said. No `--force`, ever, and no remote branch is
  deleted. One with no PR for 14 days is listed as stale and kept.
- **Overlap (W4).** Two agents on one item are warned about, never blocked.

Every process starts through `gitseam` (`git_full`, `proc`, `gh`), so in the
server, where the seam is closed, nothing here can run.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
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
SETUP_SECONDS = 600.0
MAX_STALE_REPORT = 12    # what fits the heartbeat file (doorbell.MAX_WATCH)
TS = "%Y-%m-%dT%H:%M:%SZ"

PrLookup = Callable[[str], "dict | None | str"]   # branch -> {"number", "state"} | None (no PR) | why unknown


class WorktreeError(ValueError):
    """Refused, by name; nothing was made or removed."""


# -- small helpers -----------------------------------------------------------------------------------

def _git(args: list[str], cwd: Path | str, timeout: float = GIT_SECONDS) -> tuple[int, str, str]:
    """git ARGS through the seam. The one place this module starts git (tests watch it for `--force`)."""
    r = G.git_full(args, cwd, timeout=timeout)
    if isinstance(r, G.Unavailable):
        raise WorktreeError(G.UNAVAILABLE)
    return r


def _out(args: list[str], cwd: Path | str) -> str | None:
    rc, out, _err = _git(args, cwd)
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


def project_slug(name: str) -> str:
    """The console's project name as one safe path part: `[A-Za-z0-9._-]`, at most 64, never empty or dotted."""
    s = PROJECT.sub("-", name or "").strip(".-")[:64].strip(".-")
    return s or "project"


def base_dir(home: Path | None = None) -> Path:
    """`~/.overture/worktrees`, refused when the home resolves under /mnt/ (W1)."""
    h = Path(home) if home is not None else Path.home()
    real = os.path.realpath(h)
    if real == "/mnt" or real.startswith("/mnt/"):
        raise WorktreeError(f"refused: your home resolves to {real}, under /mnt/ (a Windows drive under WSL, where "
                            f"git is slow); agent worktrees live in the Linux home. Run from a Linux HOME")
    return Path(real) / ".overture" / "worktrees"


def _project_dir(home: Path | None, project: str, create: bool) -> Path:
    d = base_dir(home) / project_slug(project)
    real = os.path.realpath(d)   # checked before anything is made, so a link onto /mnt/ is never followed
    if real == "/mnt" or real.startswith("/mnt/"):
        raise WorktreeError(f"refused: {d} resolves to {real}, under /mnt/ (a symlink to a Windows drive?); agent "
                            f"worktrees live in the Linux home")
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
    live, gone = [], []
    for e in entries:
        real = os.path.realpath(e["path"])
        (live if real in known and os.path.realpath(main) != real else gone).append(e)
    for e in gone:
        notes.append(f"gone: {e['branch']} is no longer a worktree of this repository; dropped from the registry")
    top = os.path.realpath(project_dir)
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


def _registered_project(main: Path) -> bool:
    """Whether the user switched the console on for this checkout (their own registry, never the repo's)."""
    from . import registry as R
    try:
        return R.enclosing(main) is not None
    except R.RegistryError:
        return False


def _run_setup(path: Path, main: Path, timeout: float) -> dict | None:
    """The project's `worktree_setup`, from the NEW worktree's own .overture.json; never fatal."""
    from . import projectcfg as PC
    try:
        argv = PC.load(path).worktree_setup
    except PC.ConfigError as e:
        return {"ran": False, "ok": False, "note": f"worktree_setup not run: {e}"}
    if not argv:
        return None
    if not _registered_project(main):
        return {"ran": False, "ok": False, "argv": list(argv),
                "note": "worktree_setup not run: this project is not in your registry (agent.py register)"}
    r = G.proc(list(argv), path, timeout=timeout)
    if isinstance(r, G.Unavailable):
        return {"ran": False, "ok": False, "argv": list(argv), "note": f"worktree_setup not run: {G.UNAVAILABLE}"}
    rc, _out_, err = r
    if rc == 0:
        return {"ran": True, "ok": True, "argv": list(argv), "exit": 0, "note": "worktree_setup ran"}
    return {"ran": True, "ok": False, "argv": list(argv), "exit": rc,
            "note": f"worktree_setup failed (exit {rc}): {_first_line(err) or 'no output'}; the worktree is kept, "
                    f"set it up by hand"}


def _overlap(live: list[dict], item: str, bucket: str, mine: str) -> list[dict]:
    return [{"branch": e["branch"], "agent": e["agent"], "kind": e["kind"]}
            for e in live if e["item"] == item and e["branch"] != mine and e["agent"] != bucket]


def new(repo: Path | str, project: str, kind: str, item: str, agent: str | None, *, home: Path | None = None,
        now: float | None = None, setup_timeout: float = SETUP_SECONDS) -> dict:
    """Make (or, for the same agent, kind and item, return) this agent's worktree for ITEM. Raises WorktreeError."""
    why = kind_problem(kind) or item_problem(item)
    if why:
        raise WorktreeError(f"refused: {why}")
    bucket = agent or N.UNNAMED
    if bucket != N.UNNAMED and N.problem(bucket):
        raise WorktreeError(f"refused: {N.problem(bucket)}")
    main = main_checkout(repo)
    if main is None:
        raise WorktreeError(f"refused: {repo} is not inside a git repository with a .git folder")
    if _out(["remote", "get-url", "origin"], main) is None:
        raise WorktreeError(f"refused: {main} has no remote named origin to branch from")
    pdir = _project_dir(home, project, create=True)
    t = time.time() if now is None else now
    notes: list[str] = []
    with _locked(pdir):
        live, _loose, rnotes, known = _reconcile(pdir, main)
        notes += rnotes
        for e in live:
            if e["item"] == item and e["kind"] == kind and e["agent"] == bucket:
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
    setup = _run_setup(path, main, setup_timeout)
    if setup is not None:
        notes.append(setup["note"])
    return {**{k: entry[k] for k in ("path", "branch", "kind", "item", "agent", "created", "base")},
            "worktree": path.name, "reused": False, "overlap": overlap, "notes": notes, "setup": setup}


# -- list ------------------------------------------------------------------------------------------------

def gh_prs(main: Path) -> tuple[PrLookup | None, str | None]:
    """A lookup of each branch's PR through `gh`, or (None, why) when gh cannot be used at all."""
    r = G.gh(["--version"], main, timeout=30)
    if isinstance(r, G.Unavailable):
        return None, G.UNAVAILABLE
    if r[0] != 0:
        return None, "gh (the GitHub CLI) is not available, so no PR state is known"

    def lookup(branch: str):
        res = G.gh(["pr", "list", "--head", branch, "--state", "all", "--json", "number,state", "--limit", "20"],
                   main)
        if isinstance(res, G.Unavailable):
            return G.UNAVAILABLE
        rc, out, err = res
        if rc != 0:
            return f"gh pr list failed: {_first_line(err) or f'exit {rc}'}"
        try:
            rows = json.loads(out or "[]")
        except ValueError:
            return "gh pr list printed something that is not JSON"
        prs = [r for r in rows if isinstance(r, dict) and isinstance(r.get("number"), int)
               and isinstance(r.get("state"), str)] if isinstance(rows, list) else []
        if not prs:
            return None
        prs.sort(key=lambda r: (r["state"].upper() == "OPEN", r["number"]), reverse=True)
        return {"number": prs[0]["number"], "state": prs[0]["state"].lower()}
    return lookup, None


def _int(out: str | None) -> int | None:
    try:
        return int((out or "").strip())
    except ValueError:
        return None


def status(e: dict, now: float, prs: PrLookup | None) -> dict:
    """One worktree's state: last commit, ahead/behind, dirty, unpushed, PR and stale. Reads only."""
    path = e["path"]
    row = {k: e.get(k) for k in ("path", "branch", "item", "kind", "agent", "created", "base")}
    row["registered"] = e.get("registered", True)
    last = _out(["log", "-1", "--format=%H%x1f%ct%x1f%s"], path)
    if last and last.count("\x1f") >= 2:
        sha, ct, subj = last.rstrip("\n").split("\x1f", 2)
        row["last_commit"] = {"sha": sha[:12], "at": _ts(float(ct)) if ct.isdigit() else None, "subject": subj[:200]}
    else:
        row["last_commit"] = None
    row["ahead"] = row["behind"] = None
    if e.get("base"):
        lr = _out(["rev-list", "--left-right", "--count", f"{e['base']}...HEAD"], path)
        parts = (lr or "").split()
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            row["behind"], row["ahead"] = int(parts[0]), int(parts[1])
    st = _out(["status", "--porcelain", "--untracked-files=normal"], path)
    row["dirty"] = None if st is None else bool(st.strip())
    row["unpushed"] = _int(_out(["rev-list", "--count", "HEAD", "--not", "--remotes"], path))
    if prs is None:
        row["pr"], row["pr_unknown"] = None, "gh is not available"
    elif not BRANCH.match(e["branch"] or ""):
        row["pr"], row["pr_unknown"] = None, "not on an overture/ branch"
    else:
        got = prs(e["branch"])
        if isinstance(got, str):
            row["pr"], row["pr_unknown"] = None, got
        else:
            row["pr"], row["pr_unknown"] = got, None
    created = _parse_ts(e.get("created"))
    if created is None:
        with contextlib.suppress(OSError):
            created = os.stat(path).st_mtime
    row["age_days"] = int((now - created) // DAY) if created is not None else None
    row["stale"] = bool(row["pr"] is None and row["pr_unknown"] is None and created is not None
                        and now - created >= STALE_DAYS * DAY)
    return row


def list_worktrees(repo: Path | str, project: str, *, home: Path | None = None, now: float | None = None,
                   prs: PrLookup | None | bool = True) -> dict:
    """Every worktree under `~/.overture/worktrees/<project>/`, reconciled with git, with its state.

    `prs`: True looks PRs up through gh (degrading to "unknown" without it); a
    callable is used as the lookup (tests); None means no PR state is known.
    """
    main = main_checkout(repo)
    if main is None:
        raise WorktreeError(f"refused: {repo} is not inside a git repository with a .git folder")
    pdir = _project_dir(home, project, create=False)
    t = time.time() if now is None else now
    notes: list[str] = []
    if prs is True:
        prs, why = gh_prs(main)
        if why:
            notes.append(why)
    if not pdir.is_dir():
        return {"project": project_slug(project), "worktrees": [], "notes": notes, "gh": prs is not None}
    with _locked(pdir):
        live, loose, rnotes, _known = _reconcile(pdir, main)
    notes += rnotes
    rows = [status(e, t, prs) for e in [*live, *loose]]
    return {"project": project_slug(project), "worktrees": rows, "notes": notes, "gh": prs is not None}


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
    """Why this worktree stays, or None when every rule for removing it holds (W3)."""
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
    if r.get("unpushed") is None:
        return "cannot tell whether every commit is on a remote"
    if r["unpushed"]:
        return (f"{r['unpushed']} commit{'s' if r['unpushed'] != 1 else ''} on no remote ref (push them, or remove "
                f"it by hand)")
    return None


def prune(repo: Path | str, project: str, *, dry_run: bool = False, home: Path | None = None,
          now: float | None = None, prs: PrLookup | None | bool = True) -> dict:
    """Remove the worktrees W3 allows; keep and explain the rest. Never `--force`, never a remote branch."""
    listing = list_worktrees(repo, project, home=home, now=now, prs=prs)
    main = main_checkout(repo)
    removed, kept, notes = [], [], list(listing["notes"])
    if not listing["gh"]:
        notes.append("without gh no PR state is known, so every worktree is kept")
    pdir = _project_dir(home, project, create=False)
    for r in listing["worktrees"]:
        why = _keep_reason(r)
        if why is None and not r.get("registered", True):
            why = "not in the registry (made by hand?); remove it with git worktree remove"
        if why:
            kept.append({"branch": r["branch"], "item": r.get("item"), "why": why, "stale": bool(r.get("stale"))})
            continue
        if dry_run:
            removed.append({"branch": r["branch"], "item": r.get("item"), "dry_run": True})
            continue
        rc, _o, err = _git(["worktree", "remove", r["path"]], main)
        if rc != 0:
            kept.append({"branch": r["branch"], "item": r.get("item"),
                         "why": f"git worktree remove refused: {_first_line(err) or f'exit {rc}'}", "stale": False})
            continue
        with _locked(pdir):
            entries, _p = read_registry(pdir)
            write_registry(pdir, [e for e in entries if os.path.realpath(e["path"]) != os.path.realpath(r["path"])])
        gone = {"branch": r["branch"], "item": r.get("item")}
        rc, _o, err = _git(["branch", "-d", r["branch"]], main)   # -d, never -D: git refuses an unmerged branch
        if rc != 0:
            gone["branch_kept"] = _first_line(err) or f"exit {rc}"
        removed.append(gone)
        _tidy(pdir, Path(r["path"]))
    return {"project": listing["project"], "removed": removed, "kept": kept,
            "stale": stale_summary(listing), "notes": notes, "gh": listing["gh"], "dry_run": dry_run}


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
