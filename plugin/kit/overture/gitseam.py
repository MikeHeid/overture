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

`proc` (1.50.0) is the same door for any other program the agent side starts:
`worktrees.py` runs `git worktree` through `git_full` and a project's
`worktree_setup` argv through `proc`, never through a shell. Closed, both start
nothing and return `NO_GIT`.
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


def proc(argv: Sequence[str], cwd: Path | str, *, timeout: float,
         env_over: dict[str, str] | None = None) -> tuple[int, str, str] | Unavailable:
    """Run ARGV (a list, never a shell) in `cwd`: (exit code, stdout, stderr), as text.

    1.50.0: the door for the agent side's other processes, so the server's rule
    stays one module wide: with the seam closed (in the server) it starts nothing
    and returns `NO_GIT`. It runs in a session of its own, and on `timeout` the
    whole group is killed, so a setup command's children cannot outlive it.
    127 when the program cannot be found, 126 when it cannot start, 124 on a timeout.
    """
    if not _OPEN:
        return NO_GIT
    if isinstance(argv, (str, bytes)) or not argv or not all(isinstance(a, str) and a and "\0" not in a
                                                            for a in argv):
        raise ValueError("argv is a non-empty list of non-empty strings (never one shell string)")
    import signal
    try:
        p = subprocess.Popen(list(argv), cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env={**env(), **(env_over or {})},
                             start_new_session=True)
    except FileNotFoundError:
        return 127, "", f"{argv[0]}: not found"
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return 126, "", f"{argv[0]} could not start: {e}"
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return 124, "", f"{argv[0]} did not finish within {timeout:g} s and was stopped"
    return p.returncode, out or "", err or ""


def git_full(args: Sequence[str], cwd: Path | str, *, timeout: float) -> tuple[int, str, str] | Unavailable:
    """`git --no-optional-locks ARGS` in `cwd` as (exit code, stdout, stderr); `NO_GIT` once the seam is closed."""
    return proc([*GIT, *args], cwd, timeout=timeout)
