"""Who may decide what (1.39.0): a role for each Access login, kept in the console.

With several people behind one console's Access policy, every login could
answer, lock and run anything. Now the owner can say who does what:

    STATE/roles.json    {"roles": {EMAIL: {"role": "owner"}
                                 | {"role": "member", "areas": [ITEM_ID, ...], "director"?: true}
                                 | {"role": "viewer", "areas"?: [ITEM_ID, ...], "director"?: true}}}

(1.41.0) `areas` on a viewer and `director` on either only shape the Inbox's
"Mine": see `mine`. Writing is still the role's alone.

- **No file: nothing changes.** Every login that passes Access is the owner,
  as through 1.38, so a solo console needs no setup.
- **owner**: every owner action.
- **member**: answers, locks and plain messages (no intent: no fork, merge or
  playbook) on questions and items inside their areas. An area is an item and
  everything under it, through `parent`.
- **viewer**: reads the console, writes nothing.
- **A login the file does not list is a viewer**, and so is a request with no
  email (an Access service token). Listing is how a login gets to write.

The file is the owner's, set with `agent.py access`, and never committed: like
`operators.jsonl` it names logins by email, which stay in the console (the
owner's ruling of 2026-10-14). A file the kit cannot read stops every write
rather than letting one through: an unreadable list is not an empty one.

(1.42.0, OPEN-DECISIONS.md W5) Every change is a line of an append-only log
beside it, shown in the People tab:

    STATE/roles-log.jsonl    {"at": UTC, "by": EMAIL | null, "email": EMAIL,
                              "from": ENTRY | null, "to": ENTRY | null}

`by` is the console login that made the change, or null for `agent.py access`
in the owner's terminal. The line is written before roles.json is replaced and
cut back if that fails, so no change lands unlogged. One case stays: a process
killed between the line and the rename leaves a line for a change that did not
land (roles.json is what is in force). A line a killed writer left half-written
is cut back by the next writer. The log's lock also keeps the console and the
terminal from writing roles.json over each other.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from . import operators as OP
from . import schema as S
from .store import utc_now

FILE = "roles.json"
LOG_FILE = "roles-log.jsonl"
ROLES = ("owner", "member", "viewer")
MAX_AREAS = 50
LOG_SHOWN = 50   # the People tab shows the newest; the file keeps every line
_AT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")   # store.utc_now's shape


class RolesError(Exception):
    """A roles file the kit refuses to read, or a role it refuses to write; named."""


def _areas_problem(areas: object) -> str | None:
    if not isinstance(areas, list) or not 1 <= len(areas) <= MAX_AREAS:
        return f"\"areas\" is a list of 1 to {MAX_AREAS} item ids"
    for a in areas:
        if not isinstance(a, str) or not S.ITEM_ID.match(a):
            return f"area {a!r} is not an item id"
    if len(set(areas)) != len(areas):
        return "an area is listed twice"
    return None


def _entry_problem(entry: object) -> str | None:
    """1.41.0 (OPEN-DECISIONS.md W3): a member or viewer may carry `"director": true`, and a viewer may
    carry areas. Both only shape what "Mine" shows; neither grants a write. A 1.40 kit refuses such a file
    by name rather than reading past the fields, so a downgrade fails closed."""
    if not isinstance(entry, dict) or entry.get("role") not in ROLES:
        return f"a role is one of {', '.join(ROLES)}"
    role = entry["role"]
    if role == "owner":
        return None if set(entry) == {"role"} else "an owner takes no other field (an owner sees and decides all)"
    extra = set(entry) - {"role", "areas", "director"}
    if extra:
        return f"{role} takes role, areas and director only, not {', '.join(sorted(extra))}"
    if "director" in entry and entry["director"] is not True:
        return "director is true when present (leave it out otherwise)"
    if role == "member" and "areas" not in entry:
        return f"a member has \"areas\": a list of 1 to {MAX_AREAS} item ids"
    if "areas" in entry:
        return _areas_problem(entry["areas"])
    return None


def mine(entry: Mapping) -> list[str] | None:
    """The areas "Mine" shows for this entry, or None for everything (W3): an owner, a director, and a
    viewer with no areas see all by default; a member, or a viewer with areas, sees their areas."""
    if entry.get("role") == "owner" or entry.get("director") or not entry.get("areas"):
        return None
    return list(entry["areas"])


def load(state: Path) -> dict[str, dict] | None:
    """Email -> role entry from STATE/roles.json, or None when there is no file (roles are off)."""
    p = Path(state) / FILE
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        raise RolesError(f"{p}: not readable ({e.strerror or e})") from None
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise RolesError(f"{p}: not JSON ({e})") from None
    got = doc.get("roles") if isinstance(doc, dict) and set(doc) == {"roles"} else None
    if not isinstance(got, dict):
        raise RolesError(f"{p}: the file is exactly {{\"roles\": {{EMAIL: ROLE}}}}")
    out: dict[str, dict] = {}
    for email, entry in got.items():
        why = OP.email_problem(email) or _entry_problem(entry)
        if why:
            raise RolesError(f"{p}: {email!r}: {why}")
        if email.lower() in out:
            raise RolesError(f"{p}: {email!r} is listed twice (logins are compared without case)")
        out[email.lower()] = entry
    if not any(e["role"] == "owner" for e in out.values()):
        # Written by hand, perhaps: the kit's own writer refuses this. Nobody could change it from the console.
        raise RolesError(f"{p}: no login is an owner, so nobody could run the console; name one with "
                         f"`agent.py access EMAIL owner`")
    return out


def role_of(roles: Mapping[str, dict] | None, email: str | None) -> dict:
    """The entry that governs `email`: owner when roles are off, viewer when unlisted or nameless."""
    if roles is None:
        return {"role": "owner"}
    if email is None:
        return {"role": "viewer"}
    return roles.get(email.lower(), {"role": "viewer"})


def within(item: object, areas: list[str], items: Mapping[str, dict]) -> bool:
    """True when `item` is one of `areas` or sits under one, through `parent` in the register."""
    seen: set[str] = set()
    cur = item
    while isinstance(cur, str) and cur not in seen:   # a parent loop ends the walk, it never spins
        if cur in areas:
            return True
        seen.add(cur)
        rec = items.get(cur)
        cur = rec.get("parent") if isinstance(rec, dict) else None
    return False


def set_role(state: Path, email: str, role: str | None, areas: list[str] | None = None,
             director: bool = False, by: str | None = None) -> dict[str, dict]:
    """Set (or, with role None, remove) the role of `email`; return the whole map as written.

    Refuses a change that leaves no owner: the console could then be changed by nobody.
    Removing the last login deletes the file, so roles are off again. `by` is the console login making the
    change, None from the terminal; a change that changes nothing writes nothing, not even a log line.
    """
    why = OP.email_problem(email) or (by is not None and OP.email_problem(by))
    if why:
        raise RolesError(why)
    entry = None
    if role is not None:
        entry = {"role": role}
        if areas or role == "member":
            entry["areas"] = list(areas or [])
        if director:
            entry["director"] = True
        why = _entry_problem(entry)
        if why:
            raise RolesError(why)
    email = email.lower()
    # No mkdir: a mistyped --state fails here ("nothing was written") rather than starting a new state dir.
    log = os.open(Path(state) / LOG_FILE, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                  0o600)
    try:
        # Held from the load to the rename: the console and `agent.py access` each read, change and write the
        # whole map, and without one lock across processes the second writer drops the first one's change.
        fcntl.flock(log, fcntl.LOCK_EX)
        got = load(state) or {}
        before = got.get(email)
        if before == entry:
            return got
        if entry is None:
            got.pop(email)
        else:
            got[email] = entry
        if got and not any(e["role"] == "owner" for e in got.values()):
            raise RolesError("that leaves no owner, so nobody could run the console; make another login the "
                             "owner first (`agent.py access EMAIL owner`)")
        line = (json.dumps({"at": utc_now(), "by": by.lower() if by else None, "email": email, "from": before,
                            "to": entry}, sort_keys=True, separators=(",", ":")) + "\n").encode()
        end = _mend_tail(log)
        try:
            if os.write(log, line) != len(line):
                raise OSError("short write")
            os.fsync(log)
            _write_map(Path(state) / FILE, got)
        except BaseException:
            os.ftruncate(log, end)   # the change did not land, so neither does its line
            raise
        return got
    finally:
        os.close(log)   # closing releases the lock


def _mend_tail(log: int) -> int:
    """Cut a half-written last line (a writer killed mid-append) back to the last whole line; return the end.

    Under the lock, so no live writer is mid-append: one that fails cuts its own line back. Without this the
    next line would be appended onto the fragment, and the merged line would stop the log reading for good.
    """
    size = os.lseek(log, 0, os.SEEK_END)
    if size == 0 or os.pread(log, 1, size - 1) == b"\n":
        return size
    pos = size
    while pos > 0:
        start = max(0, pos - 4096)
        cut = os.pread(log, pos - start, start).rfind(b"\n")
        if cut >= 0:
            pos = start + cut + 1
            break
        pos = start
    sys.stderr.write(f"roles log: dropped {size - pos} bytes of a half-written last line\n")
    os.ftruncate(log, pos)
    return pos


def _write_map(p: Path, got: dict[str, dict]) -> None:
    if not got:
        p.unlink(missing_ok=True)   # the last login removed: roles are off again
        return
    data = (json.dumps({"roles": dict(sorted(got.items()))}, indent=2, sort_keys=True) + "\n").encode()
    # The operator-names writer: a fresh temp file no symlink names, then one rename.
    tmp = p.with_name(f".{FILE}.{os.urandom(8).hex()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _line_problem(rec: object) -> str | None:
    if not isinstance(rec, dict) or set(rec) != {"at", "by", "email", "from", "to"}:
        return 'a line is exactly {"at", "by", "email", "from", "to"}'
    if not isinstance(rec["at"], str) or not _AT.match(rec["at"]):
        return f"at {rec['at']!r} is not a UTC time"
    if rec["by"] is not None and OP.email_problem(rec["by"]):
        return OP.email_problem(rec["by"])
    if rec["from"] is None and rec["to"] is None:
        return "a change has a from or a to"
    return OP.email_problem(rec["email"]) or next(
        (_entry_problem(rec[k]) for k in ("from", "to") if rec[k] is not None and _entry_problem(rec[k])), None)


def history(state: Path, limit: int = LOG_SHOWN) -> tuple[list[dict], int]:
    """The newest `limit` role changes, newest first, and how many the log holds in all.

    A line that is not well formed is refused by line number, never skipped. A last line with no newline is
    left out: a writer holds the lock mid-append, and one that failed cut its line back (`set_role`).
    """
    p = Path(state) / LOG_FILE
    try:
        lines = p.read_text(encoding="utf-8").split("\n")
    except FileNotFoundError:
        return [], 0
    except (OSError, UnicodeDecodeError) as e:
        raise RolesError(f"{p}: not readable ({e})") from None
    lines.pop()   # "" after the last newline, or a line still being written
    out = []
    for n, raw in enumerate(lines, 1):
        try:
            rec = json.loads(raw)
        except ValueError as e:
            raise RolesError(f"{p}:{n}: not JSON ({e})") from None
        why = _line_problem(rec)
        if why:
            raise RolesError(f"{p}:{n}: {why}")
        out.append(rec)
    return out[::-1][:limit], len(out)
