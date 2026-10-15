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
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from . import operators as OP
from . import schema as S

FILE = "roles.json"
ROLES = ("owner", "member", "viewer")
MAX_AREAS = 50


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
             director: bool = False) -> dict[str, dict]:
    """Set (or, with role None, remove) the role of `email`; return the whole map as written.

    Refuses a change that leaves no owner: the console could then be changed by nobody.
    Removing the last login deletes the file, so roles are off again.
    """
    why = OP.email_problem(email)
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
    got = load(state) or {}
    if entry is None:
        got.pop(email, None)
    else:
        got[email] = entry
    p = Path(state) / FILE
    if not got:
        p.unlink(missing_ok=True)
        return {}
    if not any(e["role"] == "owner" for e in got.values()):
        raise RolesError("that leaves no owner, so nobody could run the console; make another login the owner "
                         "first (`agent.py access EMAIL owner`)")
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
    return got
