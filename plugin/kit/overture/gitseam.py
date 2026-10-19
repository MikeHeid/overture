"""The one door every git call in the kit goes through (owner ruling CONSOLE-kit/Q23).

Git obeys the repository's own `.git/config`, and an agent can write that file.
Some keys make git run a program (`log.showSignature` with `gpg.program`, a
`core.fsmonitor` hook, a diff or textconv driver, and any key git adds later).
The console server runs outside every agent's jail, so a git it starts could
be made to run code there. No `-c` blocklist can close that: git has no switch
to ignore repository config, and a blocklist is defeated by the next key.

So the SERVER spawns no git at all. `server.serve` calls `close()` first thing,
before it reads the project; from then on `run` starts no process and returns
`NO_GIT`, a typed `Unavailable`, never `None` (`None` keeps its meaning: "git
ran and failed, or this is not a git work tree"). Closing is one-way: there is
no `open()`. Every feature git fed says `UNAVAILABLE` when the seam is closed,
never a silent blank.

Agent-side callers (`agent.py`, run by an agent inside its own jail, and the
module functions called from any process that is not the server) find the seam
open and use git as before.

`gh`, the GitHub CLI, goes through this door too (`gh`, below), for `agent.py
prs-push`: gh runs git to find the repository's remote, so it obeys the same
config, and the server never talks to GitHub anyway. Closed, it starts nothing
and returns `NO_GIT`, exactly as `run` does.

`git_full` (1.50.0) is the same door with the exit code and both streams, for
`worktrees.py`'s `git worktree` calls. It runs git and nothing else: the kit
starts no other program, and a project's `worktree_setup` is printed for the
agent to run through its own permission prompt, never run here. Closed, it
starts nothing and returns `NO_GIT`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Sequence

UNAVAILABLE = "unavailable (no git in the server)"
# 0.8.1: every git call is READ-ONLY. Plain `git status` refreshes the index's stat cache
# and rewrites .git/index when it can take the lock; `--no-optional-locks` (and the same as
# an environment variable, for any git a hook or alias starts) turns that off.
GIT = ("git", "--no-optional-locks")


class Unavailable:
    """What `run` returns once the seam is closed: no process was started. One instance, `NO_GIT`."""

    __slots__ = ()
    reason = UNAVAILABLE

    def __repr__(self) -> str:
        return "NO_GIT"


NO_GIT = Unavailable()
_OPEN = True


def close() -> None:
    """Refuse every later git call in this process. Called once by the server at startup; never undone."""
    global _OPEN
    _OPEN = False


def is_open() -> bool:
    return _OPEN


def env() -> dict[str, str]:
    return {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}


def run(args: Sequence[str], cwd: Path | str, *, timeout: float, data: bytes | None = None,
        text: bool = False) -> bytes | str | None | Unavailable:
    """`git --no-optional-locks ARGS` in `cwd`: stdout on exit 0, None when it failed or could not start.

    With the seam closed (in the server) it starts nothing and returns `NO_GIT`.
    """
    if not _OPEN:
        return NO_GIT
    try:
        r = subprocess.run([*GIT, *args], cwd=cwd, input=data, capture_output=True, text=text,
                           timeout=timeout, check=False, env=env())
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


GH_SECONDS = 120


def gh(args: Sequence[str], cwd: Path | str, *, timeout: float = GH_SECONDS) -> tuple[int, str, str] | Unavailable:
    """`gh ARGS` in `cwd`, never prompting: (exit code, stdout, stderr); 127 when gh is not installed.

    With the seam closed (in the server) it starts nothing and returns `NO_GIT`.
    """
    if not _OPEN:
        return NO_GIT
    quiet = {"GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1", "GH_PAGER": "", "PAGER": ""}
    try:
        r = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False,
                           env={**env(), **quiet})
    except FileNotFoundError:
        return 127, "", "gh (the GitHub CLI) is not installed or not on PATH"
    except subprocess.TimeoutExpired:
        return 124, "", f"gh did not finish within {timeout:g} s"
    except (OSError, subprocess.SubprocessError) as e:
        return 126, "", f"gh could not start: {e}"
    return r.returncode, r.stdout, r.stderr


MAX_OUTPUT = 4 << 20   # 1.50.0: what `git_full` keeps of each stream; more than any listing it reads


def _kept(fh) -> str:
    fh.seek(0)
    return fh.read(MAX_OUTPUT).decode("utf-8", "replace")


def git_full(args: Sequence[str], cwd: Path | str, *, timeout: float) -> tuple[int, str, str] | Unavailable:
    """`git --no-optional-locks ARGS` in `cwd` as (exit code, stdout, stderr); `NO_GIT` once the seam is closed.

    1.50.0, for `worktrees.py`. Git only: there is no door here for any other program (a project's
    `worktree_setup` is printed for the agent to run, never run by the kit). Each stream is spooled to a
    temporary file and at most MAX_OUTPUT bytes of it kept, so a huge listing cannot fill memory. It runs in a
    session of its own, and on `timeout` the whole group is killed. 127 when git cannot be found, 126 when it
    cannot start, 124 on a timeout.
    """
    if not _OPEN:
        return NO_GIT
    if isinstance(args, (str, bytes)) or not all(isinstance(a, str) and "\0" not in a for a in args):
        raise ValueError("git's arguments are a list of strings (never one shell string)")
    import signal
    import tempfile
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            p = subprocess.Popen([*GIT, *args], cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                 env=env(), start_new_session=True)
        except FileNotFoundError:
            return 127, "", "git: not found"
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            return 126, "", f"git could not start: {e}"
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return 124, "", f"git did not finish within {timeout:g} s and was stopped"
        return rc, _kept(out), _kept(err)
