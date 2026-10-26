"""The doorbell, from the agent's side: read it, wait on it, and remember how far the agent got (spec §7.3).

The server appends one JSON line to `inbox.jsonl` for every owner write. An
open session runs `agent.py watch`, which blocks until a line that should wake
it arrives, then exits; the exit is what wakes the session. Only the owner's
requests wake it: `process` (answers are in), `fork` (deliberate), `chat` (0.7.0) and
`visual` (0.8.0, draw a visual of an item).

The agent's own cursor, the highest doorbell seq it has processed, is kept in
`steward/agent-cursor.json` beside the doorbell. It only moves forward.

1.60.0 (OPEN-DECISIONS I4): the steward's two writable files, the cursor and
`watch.json`, live in `STATE/steward/`, a folder holding nothing else. A sandbox
can then let the steward write there without re-opening reads of the rest of
STATE (I1: a write-allowed folder is a readable one). Reads prefer it and fall
back to the file beside the doorbell, where kits before 1.60 kept it.

A scan for a resolve (CONSOLE-kit/Q40, Q41) is a refactor record, not a store
record, so its line cannot take a store seq of its own: it carries the store's
seq as it stood and `rx`, the refactor seq. Such a line is pending while its
`rx` is past `rx_through`, the cursor's second number, which `synced
--rx-through` moves; its `seq` is not what decides it.
"""

from __future__ import annotations

import calendar
import json
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from .registry import read_regular

WAKE_INTENTS = ("process", "fork", "chat", "visual", "scan", "ux-save", "ux-link", "pr-merge")   # 1.32: UX View; 1.33: Merge
CURSOR_FILE = "agent-cursor.json"
MAX_DOORBELL = 64 << 20  # one short line per owner write; far past any real console
MAX_CURSOR = 4096
STEWARD_DIR = "steward"  # 1.60.0 (I4): the cursor and watch.json, and nothing else


def steward_dir(state: Path) -> Path:
    """STATE/steward/, made 0700 when absent. Refused (OSError) when it is a link or a file: a planted link
    there would carry the steward's writes somewhere else."""
    d = Path(state) / STEWARD_DIR
    try:
        os.mkdir(d, 0o700)
    except FileExistsError:
        pass
    if not stat.S_ISDIR(os.lstat(d).st_mode):
        raise OSError(f"{d} is not a folder (a link or a file), so the steward writes nothing there")
    return d


def _read_path(state: Path, name: str) -> Path:
    """Where to read `name`: STATE/steward/ when it is a real folder holding it, else beside the doorbell."""
    d = Path(state) / STEWARD_DIR
    try:
        if stat.S_ISDIR(os.lstat(d).st_mode) and os.path.lexists(d / name):
            return d / name
    except OSError:
        pass
    return Path(state) / name


def migrate_steward(state: Path) -> list[str]:
    """Move a cursor or watch.json kept beside the doorbell (before 1.60) into STATE/steward/, unless one is
    there already. Run outside any sandbox, before one is switched on: a sandboxed steward cannot read the
    old place, and a cursor it cannot read is 0. Returns the names moved."""
    moved = []
    for name in (CURSOR_FILE, "watch.json"):
        old = Path(state) / name
        try:
            if not stat.S_ISREG(os.lstat(old).st_mode):
                continue
        except FileNotFoundError:
            continue
        new = steward_dir(state) / name
        if not os.path.lexists(new):
            os.replace(old, new)
            moved.append(name)
    return moved


def read_lines(path: Path) -> list[dict]:
    """Every complete doorbell line. A final line with no newline is still being written, so it waits.

    Only a regular file is read, and never by blocking on it: a FIFO or device at
    the path is refused by name (`RegistryError`) rather than hanging a watch.
    """
    data = read_regular(Path(path), MAX_DOORBELL)
    if data is None:
        return []
    raw = data.decode("utf-8", errors="replace")  # a bad byte spoils only its own line, which is then skipped
    out = []
    for line in raw.split("\n")[:-1]:  # the piece after the last newline is incomplete or empty
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue  # a damaged line is skipped, never guessed at; the store is the record
        if isinstance(rec, dict) and isinstance(rec.get("seq"), int) and not isinstance(rec["seq"], bool):
            out.append(rec)
    return out


def _rx(r: dict) -> int | None:
    v = r.get("rx")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def pending(path: Path, since: int, intents: tuple[str, ...] | None = WAKE_INTENTS,
            rx_since: int = 0) -> list[dict]:
    """Doorbell lines after `since` (a refactor line: after `rx_since`), oldest first; with `intents`, only those."""
    return [r for r in read_lines(path)
            if (r["seq"] > since if _rx(r) is None else _rx(r) > rx_since)
            and (intents is None or r.get("intent") in intents)]


def watch(path: Path, since: int, *, poll: float = 2.0, timeout: float | None = None,
          sleep: Callable[[float], None] = time.sleep,
          clock: Callable[[], float] = time.monotonic,
          heartbeat: Callable[[], None] | None = None, rx_since: int = 0) -> list[dict]:
    """Block until a wake line arrives after `since`, and return every wake line waiting.

    A line already there when the watch starts returns at once, so a signal sent
    while no session was watching is never missed. With `timeout`, an empty list
    means it ran out. `heartbeat`, if given, is called once per poll while the
    watch waits (see `Heartbeat`).
    """
    start = clock()
    while True:
        found = pending(path, since, rx_since=rx_since)
        if found:
            return found
        if timeout is not None and clock() - start >= timeout:
            return []
        if heartbeat is not None:
            heartbeat()
        sleep(poll)


# "Agent listening" (0.6.0). A watch that is waiting on the doorbell says so in
# `watch.json` beside it: `watching`, when it last said so (`at`), and the time
# by which it promises to say so again (`until`). The server reads it and shows
# the owner "listening" only while that promise is kept, so a watch killed
# without a word (SIGKILL, a closed laptop) lapses to "idle" on its own, and a
# watch that exits normally says so at once. It is a hint for the owner, never
# something the doorbell depends on: a failed write is reported and the watch
# goes on.
WATCH_FILE = "watch.json"
BEAT_EVERY = 10.0     # seconds between writes while waiting; a 2 s poll does not write every 2 s
BEAT_GRACE = 20.0     # slack past the promised next beat before "listening" lapses
MAX_WATCH = 4096
MAX_PROMISE = 86400   # an `until` further ahead than this is not believed
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _ts(t: float) -> str:
    return time.strftime(TS_FORMAT, time.gmtime(t))


def _parse_ts(v: object) -> float | None:
    if not isinstance(v, str) or len(v) > 40:
        return None
    try:
        return float(calendar.timegm(time.strptime(v, TS_FORMAT)))
    except ValueError:
        return None


def write_watch(state: Path, watching: bool, *, every: float = BEAT_EVERY, now: float | None = None,
                stale: list | None = None, notes: dict | None = None) -> None:
    """Record whether a watch is waiting now; `every` is how soon it promises to write again.

    1.50.0: `stale` is the steward's last list of stale agent worktrees (W3), branch and age only, folded into
    this heartbeat so no new route was needed; an older server reads the file and ignores the key.
    1.53.0: `notes` is the steward's last area-notes check, as counts only (`notes.counts`), the same way.
    """
    t = time.time() if now is None else now
    rec = {"watching": watching, "at": _ts(t), "until": _ts(t + every + BEAT_GRACE) if watching else None}
    if stale is not None:
        rec["stale_worktrees"] = _stale_rows(stale)
    if notes is not None:
        rec["area_notes"] = {k: v for k, v in notes.items() if isinstance(k, str) and isinstance(v, int)
                             and not isinstance(v, bool)}
    p = steward_dir(state) / WATCH_FILE
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".watch.", suffix=".tmp")  # 0600 from creation
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read_watch(path: Path) -> bytes | None:
    """The heartbeat's bytes, or None when absent.

    Trust: the state dir is the server's own, mode 0700, so only this user can
    put anything in it. Even so, the file is opened with O_NOFOLLOW (a symlink
    raises ELOOP) and O_NONBLOCK, and must be a small regular file: a link
    planted to make some other file read as a heartbeat reads as "never".
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_WATCH:
            raise OSError(f"{path} is not a small regular file")
        return os.read(fd, MAX_WATCH + 1)[:MAX_WATCH]
    finally:
        os.close(fd)


def listening(state: Path, *, now: float | None = None) -> dict:
    """What the owner is told: {"state": "listening"|"idle"|"never", "last_seen": ts|None}.

    Anything unreadable, malformed or not a regular file reads as "never", by
    name of state, never as "listening": the safe error is to under-claim.
    """
    t = time.time() if now is None else now
    try:
        data = _read_watch(_read_path(state, WATCH_FILE))
        rec = json.loads(data.decode("utf-8")) if data is not None else None
    except (OSError, ValueError, RecursionError):   # 1.50 clearing round: nested past the parser's depth: never
        rec = None
    if not isinstance(rec, dict):
        return {"state": "never", "last_seen": None}
    at, until = _parse_ts(rec.get("at")), _parse_ts(rec.get("until"))
    if at is None or at > t + 60:  # a stamp from the future is a broken clock or a forged file
        return {"state": "never", "last_seen": None}
    if (rec.get("watching") is True and until is not None
            and at <= until <= at + MAX_PROMISE and t <= until):
        return {"state": "listening", "last_seen": rec["at"]}
    return {"state": "idle", "last_seen": rec["at"]}


STALE_BRANCH = re.compile(r"^overture/[a-z]+/[A-Za-z0-9._-]{1,120}\Z")   # worktrees.BRANCH, the server's check
MAX_STALE = 12
STALE_FOR = 86400.0   # 1.50 review C8: the stale list is shown only while its heartbeat is at most a day old


def _stale_rows(rows: object) -> list[dict]:
    """The stale-worktree rows worth keeping: a branch of the shape, a whole number of days, an agent name."""
    from . import names as N
    out: list[dict] = []
    for r in rows if isinstance(rows, list) else []:
        if not (isinstance(r, dict) and isinstance(r.get("branch"), str) and STALE_BRANCH.match(r["branch"])
                and isinstance(r.get("age_days"), int) and not isinstance(r["age_days"], bool)
                and 0 <= r["age_days"] <= 36500):
            continue
        row = {"branch": r["branch"], "age_days": r["age_days"]}
        a = r.get("agent")
        if isinstance(a, str) and (a == N.UNNAMED or N.problem(a) is None):
            row["agent"] = a
        out.append(row)
        if len(out) >= MAX_STALE:
            break
    return out


def stale_worktrees(state: Path, *, now: float | None = None) -> dict | None:
    """{"at": ts, "worktrees": [...]} from the steward's last heartbeat, or None when it reported none.

    The file is the agent's, so every row is checked again here: a branch of the
    worktree shape and a number of days, never a path; a stamp from the future
    or anything malformed reads as nothing.
    """
    t = time.time() if now is None else now
    try:
        data = _read_watch(_read_path(state, WATCH_FILE))
        rec = json.loads(data.decode("utf-8")) if data is not None else None
    except (OSError, ValueError, RecursionError):   # 1.50 clearing round: nested past the parser's depth: nothing
        return None
    if not isinstance(rec, dict) or "stale_worktrees" not in rec:
        return None
    at = _parse_ts(rec.get("at"))
    if at is None or at > t + 60 or t - at > STALE_FOR:   # C8: a list the steward left a day ago says nothing
        return None
    return {"at": rec["at"], "worktrees": _stale_rows(rec.get("stale_worktrees"))}


class Heartbeat:
    """Write `watch.json` on the first call, then at most once per `every` seconds.

    A write that fails is reported once on stderr and never stops the watch.
    """

    def __init__(self, state: Path, poll: float, *, clock: Callable[[], float] = time.monotonic,
                 warn: Callable[[str], None] | None = None, stale: list | None = None,
                 notes: dict | None = None) -> None:
        self.state = Path(state)
        self.stale = stale      # 1.50.0: the steward's stale worktrees, carried on every beat (None: say nothing)
        self.notes = notes      # 1.53.0: the steward's last area-notes counts, the same way
        self.every = max(BEAT_EVERY, poll)  # a slow poll promises its own, longer, interval
        self.clock = clock
        self.warn = warn or (lambda m: sys.stderr.write(m + "\n"))
        self._last: float | None = None
        self._warned = False

    def _write(self, watching: bool) -> None:
        try:
            extra = {} if self.stale is None else {"stale": self.stale}   # unchanged when there is nothing to say
            if self.notes is not None:
                extra["notes"] = self.notes
            write_watch(self.state, watching, every=self.every, **extra)
        except OSError as e:
            if not self._warned:
                self._warned = True
                self.warn(f"overture: cannot record the watch in {self.state / WATCH_FILE}: {e}; "
                          "the owner will not see 'agent listening'")

    def __call__(self) -> None:
        now = self.clock()
        if self._last is None or now - self._last >= self.every:
            self._last = now
            self._write(True)

    def update(self, stale: list | None) -> None:
        """1.50.0: the steward's prune finished after the first beat: carry its stale list, written now."""
        self.stale = stale
        self._last = self.clock()
        self._write(True)

    def update_notes(self, notes: dict | None) -> None:
        """1.53.0: the steward's notes check finished after the first beat: carry its counts, written now."""
        self.notes = notes
        self._last = self.clock()
        self._write(True)

    def stop(self) -> None:
        """The watch is over (woken, timed out or interrupted): say so now, not after the promise lapses."""
        self._write(False)


def _cursor_value(state: Path, key: str) -> int:
    try:
        data = read_regular(_read_path(state, CURSOR_FILE), MAX_CURSOR)
        v = json.loads(data.decode("utf-8")).get(key, 0) if data is not None else 0
    except (OSError, ValueError, AttributeError, RecursionError):   # 1.50 clearing round: too deep reads as 0
        return 0
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def read_cursor(state: Path) -> int:
    return _cursor_value(state, "through")


def read_rx_cursor(state: Path) -> int:
    """The highest refactor seq (a scan's `rx`) the agent has processed."""
    return _cursor_value(state, "rx_through")


def write_cursor(state: Path, through: int, rx_through: int | None = None) -> int:
    """Record that the agent has processed up to `through` (and `rx_through`); neither moves backwards.

    Returns the store cursor now held. Each number keeps its own high mark, so
    moving one never resets the other.
    """
    now = max(read_cursor(state), through)
    rx = max(read_rx_cursor(state), rx_through or 0)
    p = steward_dir(state) / CURSOR_FILE
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".agent-cursor.", suffix=".tmp")  # 0600, unique, from creation
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"through": now, **({"rx_through": rx} if rx else {})}) + "\n")
    os.replace(tmp, p)
    return now
