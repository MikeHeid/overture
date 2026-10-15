"""Project settings set in the console (1.44.0): the Settings tab, for administrators and directors.

Some of a console's behaviour is a team's decision, not plumbing: how much chat
is allowed, how many agents may work one item, what each lane is called and
coloured. The owner chose (2026-10-15) to put those in the hands of a project's
administrators and directors, set from the console:

    STATE/settings.json    {"settings": {KEY: VALUE}}   (only what was set; the rest is the default)

- **Beside the repo, never in it.** The console still writes nothing into the
  project tree. A value set here overrides the committed default (`.overture.json`
  for lanes, the kit's own for the limits), and the Settings tab says so.
- **Live.** Read on every use, so a change needs no restart.
- **Logged.** Every change is a line of the role log (roles.logged_change):
  `{"at", "by", "setting": {"key", "from", "to"}}`, shown under Settings.
- **A damaged file falls back to the defaults**, named in the server log: these
  are limits and labels, not who may decide (that is roles.json, which fails closed).

Plumbing stays out: Access, hosts, ports, paths, tokens, the steward and the
adapter are set where they are today, never from a web page.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import operators as OP
from . import projectcfg as PC
from . import roles as RO

FILE = "settings.json"
# key -> (minimum, maximum, the kit's default, what it is). Whole numbers only.
LIMITS = {
    "chat_per_minute": (1, 60, 6, "Chat messages a minute"),
    "chat_per_hour": (1, 1000, 60, "Chat messages an hour"),
    "working_per_item": (1, 50, 8, "Agents working one item at once"),
}
KEYS = frozenset(LIMITS) | {"lanes"}


class SettingsError(Exception):
    """A setting the kit refuses, or a settings file it cannot read; named."""


def problem(key: object, value: object) -> str | None:
    """Why `value` is not a value of `key`, or None. None as a value means "back to the default"."""
    if not isinstance(key, str) or key not in KEYS:   # a list or an object is unhashable: a 400, not a 500
        return f"{key!r} is not a setting here (settings: {', '.join(sorted(KEYS))})"
    if value is None:
        return None
    if key in LIMITS:
        lo, hi, _, what = LIMITS[key]
        if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
            return f"{what}: a whole number from {lo} to {hi}"
        return None
    # lanes: the `.overture.json` shape, labels and colours only (`ux` changes a lane's flow: the repo's).
    if not isinstance(value, dict) or any(not isinstance(o, dict) or set(o) - {"color", "label"}
                                          for o in value.values()):
        return 'lanes is {"lane-x": {"label"?, "color"?}}: a label and a colour per lane'
    try:
        PC._lanes(value)
    except PC.ConfigError as e:
        return str(e).replace(f"{PC.FILE}: ", "")
    return None


def load(state: Path) -> dict:
    """The values set here (not the defaults); {} when none. A file the kit refuses raises SettingsError."""
    p = Path(state) / FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as e:
        raise SettingsError(f"{p}: not readable ({type(e).__name__})") from None
    got = doc.get("settings") if isinstance(doc, dict) and set(doc) == {"settings"} else None
    if not isinstance(got, dict):
        raise SettingsError(f'{p}: the file is exactly {{"settings": {{KEY: VALUE}}}}')
    for k, v in got.items():
        why = problem(k, v) or (v is None and "a value set here is not null (leave it out)")
        if why:
            raise SettingsError(f"{p}: {k}: {why}")
    return got


def effective(state: Path, project_lanes: dict) -> tuple[dict, str | None]:
    """(every setting as it applies now, the file's problem or None). A damaged file means the defaults."""
    try:
        got = load(state)
        bad = None
    except SettingsError as e:
        got, bad = {}, str(e)
    out = {k: got.get(k, LIMITS[k][2]) for k in LIMITS}
    lanes = {lane: dict(o) for lane, o in project_lanes.items()}
    for lane, o in got.get("lanes", {}).items():
        lanes[lane] = {**lanes.get(lane, {}), **o}
    out["lanes"] = lanes
    return out, bad


def put(state: Path, key: str, value: object, by: str | None) -> dict:
    """Set `key` to `value` (None: back to the default), logged; return the values set here."""
    why = problem(key, value)
    if why:
        raise SettingsError(why)
    p = Path(state) / FILE
    out: list[dict] = []

    def plan():
        # A damaged file applies as the defaults (effective) and the tab says so; any change from the console,
        # a Reset included, replaces it, so it can be mended there rather than only by hand. What it held is
        # unreadable, so the log line's `from` is null and the server log names the damage.
        try:
            got, damaged = load(state), False
        except SettingsError as e:
            sys.stderr.write(f"console settings: {e}; replaced by this change\n")
            got, damaged = {}, True
        before = got.get(key)
        new = {k: v for k, v in got.items() if k != key}
        if value is not None:
            new[key] = value
        out.append(new if before != value or damaged else got)
        if before == value and not damaged:
            return None
        return {"setting": {"key": key, "from": before, "to": value}}, lambda: _write(p, new)
    RO.logged_change(state, by, plan)
    return out[0]


def put_name(state: Path, email: str, name: str | None, by: str | None) -> bool:
    """Set (None: clear) the short name committed rulings carry for `email`, logged; whether it changed.

    The console's Settings tab and `agent.py operator-name` both write through here, so the two never
    interleave a read-modify-write and every change, from either, is a line of the role log.
    """
    why = OP.email_problem(email) or (OP.name_problem(name) if name is not None else None)
    if why:
        raise OP.OperatorsError(why)
    email = email.lower()
    changed: list[bool] = []

    def plan():
        before = OP.load_names(state).get(email)
        changed.append(before != name)
        if before == name:
            return None
        return ({"setting": {"key": "operator_name", "email": email, "from": before, "to": name}},
                lambda: OP.set_name(state, email, name))
    RO.logged_change(state, by, plan)
    return changed[0]


def _write(p: Path, got: dict) -> None:
    if not got:
        p.unlink(missing_ok=True)
        return
    data = (json.dumps({"settings": got}, indent=2, sort_keys=True) + "\n").encode()
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
