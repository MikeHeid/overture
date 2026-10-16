"""Sign-in links (1.46.0, OPEN-DECISIONS.md "Without Cloudflare", L1 L2 L5 L6): a console with no Access.

With `--auth link` nothing in front of the console proves who is at the
browser, so the console does it itself. The network (Tailscale, a LAN,
loopback) only decides who can reach the port; a local process that reaches
it still cannot forge a sign-in.

- **An invite** is made in the owner's terminal: `agent.py invite EMAIL`
  (refused in a Claude Code session). Its token is `ovi_` and 256 random bits,
  printed once as a link and never stored: only its SHA-256 is kept. It works
  once and lapses 24 hours after it was made (L2).
- **Opening the link** (`GET /signin?t=…`) never spends it: a chat app's link
  preview or a mail scanner GETs every link it sees. The page asks "Sign this
  browser in as EMAIL?" and its button POSTs the token back, from the
  console's own origin (`POST /signin`). That POST spends the invite under this
  file's lock, so two presses of one link sign in exactly one browser.
- **A device** is that browser from then on: an HttpOnly cookie
  `overture-device=<12 hex id>.<secret>`, with only the secret's SHA-256 kept
  here. It stays signed in until revoked (People, or `agent.py devices
  --revoke ID`); a revocation takes effect on the very next request, because
  the file is read again whenever its stamp changes.

The file is the machine's, beside the user's registry, not a project's: a
browser's cookie belongs to a host, not a port, so one cookie is presented to
every console of this user on this machine (L6). It does NOT open every one
(architect default amending L6, security review of 1.46): a device is admitted
to a console only when

  (a) that project's roles are ON and list the device's email, or
  (b) the device was invited FROM that project (its `projects` holds the key).

So a sign-in link opens the project it was made from, plus every project whose
roles list that email; with roles off, only the projects it was invited from.
An invite records the project it was made from; redeeming one in a browser that
already holds a device of the SAME email adds that project to the device (same
cookie) instead of making a second one. `admitted` is the one predicate: the
gate (server.device_verifier), People's listing and its Revoke all ask it, so
they cannot disagree. Each project's roles still decide what that login may do.

A project's key is `project_key(STATE)`: the real path of its state directory,
which is what the registry already keys a console by (registry.py: several
checkouts on one state are ONE console) and the one thing all three doors hold
(server.py's Config.state, server.json's entry "state", agent.py's --state).
A project name is not (single-project servers take any --project text, and two
machines' names can collide), nor is a root (several roots share one console).

    ${XDG_CONFIG_HOME:-~/.config}/overture/devices.json      (0600, dir 0700)
    {"invites": [{"id": 8 hex, "email", "sha256", "expires": UTC, "project": KEY}],
     "devices": [{"id": 12 hex, "email", "sha256", "created": UTC, "label": "Firefox on Linux",
                  "projects": [KEY, ...]}]}

Every field is checked on every read, dates parsed and not only matched (a
"2099-13-45T99:99:99Z" would otherwise reach a comparison and raise there,
blocking every sign-in and revoke). A file that fails any check signs
NOBODY in (fail closed) rather than being read past; the server names why in
its log, once per change of the file. Every invite, sign-in and revoke is a
line of the acting project's role log (roles.py), taken under this file's lock
first and the log's second, always in that order.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import operators as OP
from . import registry as R
from . import roles as RO

FILE = "devices.json"
MAX_FILE = 1 << 20
MAX_INVITES = 200          # waiting invites; the expired ones are pruned on every write
MAX_DEVICES = 500
INVITE_HOURS = 24          # L2: a link works once, within a day
COOKIE = "overture-device"
MAX_AGE = 34560000         # 400 days, the longest a browser keeps a cookie; GET / slides it (server.py)
TOKEN = re.compile(r"^ovi_[A-Za-z0-9_-]{43}\Z")                 # "ovi_" + secrets.token_urlsafe(32)
COOKIE_VALUE = re.compile(r"^([0-9a-f]{12})\.([A-Za-z0-9_-]{43})\Z")
DEVICE_ID = re.compile(r"^[0-9a-f]{12}\Z")
INVITE_ID = re.compile(r"^[0-9a-f]{8}\Z")
SHA = re.compile(r"^[0-9a-f]{64}\Z")
LABEL = re.compile(r"^[A-Za-z ]{1,64}\Z")
_AT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_FMT = "%Y-%m-%dT%H:%M:%SZ"
# A project key (project_key): an absolute real path. Capped at PATH_MAX; no control character (a key is printed
# by `agent.py devices` and compared byte for byte). A device may hold at most MAX_PROJECTS of them.
PROJECT_MAX = 4096
MAX_PROJECTS = 100
_PROJECT = re.compile(r"^/[^\x00-\x1f\x7f]*\Z")
ACTIONS = ("invite", "signin", "revoke")
# The console's own origin in link mode (server.py --origin, server.json's "origin"): https on a bare DNS name
# (Tailscale's `tailscale serve` proxies HTTPS to 127.0.0.1) or plain http on loopback, an optional port, and
# nothing else: it is compared byte for byte with a browser's Origin header and put into a link.
_HOST = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
_PORT = r"(?::(?:[1-9][0-9]{0,3}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5]))?"
ORIGIN = re.compile(rf"^(?:https://(?=.{{1,253}}(?::|\Z)){_HOST}|http://(?:127\.0\.0\.1|localhost)){_PORT}\Z")


class DevicesError(Exception):
    """A devices file the kit refuses to read, or a change it refuses to make; named. Never carries a token."""


def location() -> Path:
    """Beside the user's registry: the machine's sign-ins, for every console of this user here (L6)."""
    return R.location().parent / FILE


def clean_origin(origin: str) -> str:
    """`origin` with one trailing "/" dropped: `https://h.example/` and `https://h.example` are one origin."""
    return origin[:-1] if isinstance(origin, str) and origin.endswith("/") else origin


def origin_problem(origin: object) -> str | None:
    """Why `origin` is not a console origin for link mode, or None (after `clean_origin`)."""
    if not isinstance(origin, str) or not ORIGIN.match(clean_origin(origin)):
        return (f"origin {origin!r} is refused: use https://NAME[:PORT] (a bare DNS name, e.g. "
                f"https://box.tailnet.ts.net) or http://127.0.0.1[:PORT] / http://localhost[:PORT], lowercase, "
                f"with no path, query, fragment or user name")
    return None


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _stamp(at: datetime) -> str:
    return at.strftime(_FMT)


def _when(text: str) -> datetime:
    return datetime.strptime(text, _FMT).replace(tzinfo=timezone.utc)


def _sha(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("ascii"), b.encode("ascii"))


def label(user_agent: object) -> str:
    """"Firefox on Linux": what People shows for a device. Short and from a fixed list of words, never the raw
    User-Agent, which a browser fills with version numbers and anything an extension adds."""
    ua = user_agent if isinstance(user_agent, str) else ""
    # Order matters: Edge says "Chrome" and "Safari" too, Chrome says "Safari", and an iPhone says "Mac OS X".
    browser = ("Edge" if ("Edg/" in ua or "Edge/" in ua or "EdgiOS" in ua) else
               "Firefox" if ("Firefox/" in ua or "FxiOS" in ua) else
               "Chrome" if ("Chrome/" in ua or "CriOS" in ua or "Chromium/" in ua) else
               "Safari" if "Safari/" in ua else "a browser")
    system = ("Windows" if "Windows" in ua else
              "Android" if "Android" in ua else
              "iOS" if ("iPhone" in ua or "iPad" in ua or "iPod" in ua) else
              "macOS" if ("Macintosh" in ua or "Mac OS X" in ua) else
              "Linux" if ("Linux" in ua or "X11" in ua) else "another system")
    return f"{browser} on {system}"


# -- reading: every field checked, a damaged file signs nobody in -------------------------------------------

def project_key(state: Path | str) -> str:
    """The key a project goes by here: the real path of its STATE (see the module's docstring for why)."""
    return os.path.realpath(state)


def _project_problem(v: object) -> str | None:
    if not isinstance(v, str) or not 1 <= len(v) <= PROJECT_MAX or not _PROJECT.match(v):
        return f"a project is an absolute path of at most {PROJECT_MAX} characters, with no control character"
    return None


def _time_problem(name: str, v: object) -> str | None:
    # Parsed, not only matched (security review of 1.46): a month 13 passes the regex and then raised ValueError
    # in the middle of a comparison, dropping the connection and blocking every revoke until hand-fixed.
    if isinstance(v, str) and _AT.match(v):
        try:
            _when(v)
            return None
        except ValueError:
            pass
    return f"{name} {v!r} is not a UTC time"


def _invite_problem(v: object) -> str | None:
    if not isinstance(v, dict) or set(v) != {"id", "email", "sha256", "expires", "project"}:
        return 'an invite is exactly {"id", "email", "sha256", "expires", "project"}'
    if not isinstance(v["id"], str) or not INVITE_ID.match(v["id"]):
        return f"invite id {v['id']!r} is not 8 hex digits"
    if not isinstance(v["sha256"], str) or not SHA.match(v["sha256"]):
        return "an invite's sha256 is not 64 lowercase hex digits"
    return (_time_problem("expires", v["expires"]) or _project_problem(v["project"])
            or OP.email_problem(v["email"]))


def _device_problem(v: object) -> str | None:
    if not isinstance(v, dict) or set(v) != {"id", "email", "sha256", "created", "label", "projects"}:
        return 'a device is exactly {"id", "email", "sha256", "created", "label", "projects"}'
    if not isinstance(v["id"], str) or not DEVICE_ID.match(v["id"]):
        return f"device id {v['id']!r} is not 12 hex digits"
    if not isinstance(v["sha256"], str) or not SHA.match(v["sha256"]):
        return "a device's sha256 is not 64 lowercase hex digits"
    if not isinstance(v["label"], str) or not LABEL.match(v["label"]):
        return "a device's label is 1 to 64 letters and spaces"
    ps = v["projects"]
    if not isinstance(ps, list) or not 1 <= len(ps) <= MAX_PROJECTS:
        return f"a device's projects are a list of 1 to {MAX_PROJECTS}"
    for p in ps:
        if _project_problem(p):
            return _project_problem(p)
    if len(set(ps)) != len(ps):
        return "a device names one project twice"
    return _time_problem("created", v["created"]) or OP.email_problem(v["email"])


def admitted(device: dict, project: str, roles: dict | None) -> bool:
    """THE ONE RULE for whether `device` ({"email", "projects", ...}) is let in to the console of `project` (a
    project_key) whose roles are `roles` (roles.load: None when off): (a) roles on and its email listed, or (b)
    invited from this project. The gate, People's listing and its Revoke all ask this, so they cannot disagree."""
    return project in device["projects"] or (roles is not None and device["email"] in roles)


def _parse(p: Path) -> dict:
    try:
        raw = R.read_regular(p, MAX_FILE, nofollow=True)
    except R.RegistryError as e:   # a FIFO, a device file, or over the cap
        raise DevicesError(str(e)) from None
    except OSError as e:           # a symlink (O_NOFOLLOW), or not readable
        raise DevicesError(f"{p}: not readable ({e.strerror or e})") from None
    if raw is None:
        return {"invites": [], "devices": []}
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise DevicesError(f"{p}: not JSON ({e})") from None
    except RecursionError:
        raise DevicesError(f"{p}: nested too deep to be a devices file") from None
    if not isinstance(doc, dict) or set(doc) != {"invites", "devices"} \
            or not isinstance(doc["invites"], list) or not isinstance(doc["devices"], list):
        raise DevicesError(f'{p}: the file is exactly {{"invites": [...], "devices": [...]}}')
    if len(doc["invites"]) > MAX_INVITES or len(doc["devices"]) > MAX_DEVICES:
        raise DevicesError(f"{p}: more than {MAX_INVITES} invites or {MAX_DEVICES} devices")
    for kind, rows, why in (("invite", doc["invites"], _invite_problem), ("device", doc["devices"], _device_problem)):
        for n, row in enumerate(rows, 1):
            problem = why(row)
            if problem:
                raise DevicesError(f"{p}: {kind} {n}: {problem}")
        if len({r["id"] for r in rows}) != len(rows) or len({r["sha256"] for r in rows}) != len(rows):
            raise DevicesError(f"{p}: two {kind}s share an id or a hash")
    return {"invites": [dict(r) for r in doc["invites"]],
            "devices": [{**r, "projects": list(r["projects"])} for r in doc["devices"]]}


# The parsed file (or why it was refused), kept while its (inode, size, mtime, ctime) stamp is unchanged: every
# owner request asks `who`, and a write replaces the file by rename, so a revoke is seen by the next request.
_parsed: dict[str, tuple[tuple | None, dict | DevicesError]] = {}


def _file_stamp(p: Path) -> tuple | None:
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise DevicesError(f"{p}: not readable ({e.strerror or e})") from None
    return (st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_mode)


def load(path: Path | None = None, log=None) -> dict:
    """The file as {"invites", "devices"}, read again only when it changed. Raises DevicesError when refused.

    `log(message)` is called once per change of a refused file (the server's log), never per request.
    """
    p = Path(path or location())
    stamp = _file_stamp(p)
    hit = _parsed.get(str(p))
    if hit is not None and stamp is not None and hit[0] == stamp:
        got = hit[1]
    else:
        try:
            got = _parse(p)
        except DevicesError as e:
            got = e
            if log is not None:
                log(str(e))
        # The stamp was taken before the read: a write in between changes it, so the next call reads again.
        _parsed[str(p)] = (stamp, got)
    if isinstance(got, DevicesError):
        raise got
    return got


def _write(p: Path, doc: dict) -> None:
    """roles._write_map's way: a fresh temp file no symlink names (O_EXCL, O_NOFOLLOW, 0600), fsync, one rename."""
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode()
    if len(data) > MAX_FILE:   # a file over the read cap would sign nobody in: refuse the change instead
        raise DevicesError(f"the devices file would be over {MAX_FILE} bytes; revoke some browsers under People")
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


@contextlib.contextmanager
def locked(path: Path | None = None):
    """The file's lock (`devices.json.lock` beside it, flock), held from a read to its rename. Always taken
    BEFORE the role log's lock: the console and `agent.py` both take the two, and one order means no deadlock."""
    p = Path(path or location())
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(p.with_name(p.name + ".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield p
    finally:
        os.close(fd)   # closing releases the lock


def _logged(p: Path, state: Path, by: str | None, action: str, email: str, ident: str, doc: dict) -> None:
    """Write `doc` to the file through the role log of `state` (roles.logged_change): the line first, cut back
    if the write fails, so no sign-in, invite or revoke lands unlogged. Called under `locked`."""
    RO.logged_change(state, by, lambda: ({"device": {"action": action, "email": email, "id": ident}},
                                         lambda: _write(p, doc)))


def _live(invites: list[dict], now: datetime) -> list[dict]:
    return [i for i in invites if _when(i["expires"]) > now]


def invite(path: Path | None, email: str, state: Path, now: datetime | None = None) -> tuple[str, str]:
    """A new invite for `email`: (the token, to print ONCE as a link; the invite's id). Only its hash is kept.
    Logged in `state`'s role log with by None: invites are made in the owner's terminal. The invite records
    `state`'s project (project_key): the console it opens, whatever that project's roles say (rule b)."""
    why = OP.email_problem(email)
    project = project_key(state)
    why = why or _project_problem(project)
    if why:
        raise DevicesError(why)
    email, at = email.lower(), _now(now)
    token = "ovi_" + secrets.token_urlsafe(32)
    with locked(path) as p:
        doc = _parse(p)
        invites = _live(doc["invites"], at)
        if len(invites) >= MAX_INVITES:
            raise DevicesError(f"{MAX_INVITES} invites are already waiting; they lapse after {INVITE_HOURS} hours")
        ids = {i["id"] for i in invites}
        ident = next(x for x in iter(lambda: secrets.token_hex(4), None) if x not in ids)
        invites.append({"id": ident, "email": email, "sha256": _sha(token),
                        "expires": _stamp(at + timedelta(hours=INVITE_HOURS)), "project": project})
        _logged(p, state, None, "invite", email, ident, {"invites": invites, "devices": doc["devices"]})
    return token, ident


def _find_invite(doc: dict, token: object, at: datetime, project: str) -> dict | None:
    """The live invite this token names AND that was made from `project` (the answering console's key), or None.
    An invite made elsewhere is exactly an unknown one here (F10): its page names no email on another project's
    port, and it is never spent there, so it still works where it was made."""
    if not isinstance(token, str) or not TOKEN.match(token):
        return None
    want = _sha(token)
    hit = None
    for i in doc["invites"]:   # every row compared, in constant time, whichever matches
        if _same(i["sha256"], want) and _when(i["expires"]) > at:
            hit = i
    return hit if hit is not None and hit["project"] == project else None


def peek(path: Path | None, token: object, state: Path, now: datetime | None = None, log=None) -> str | None:
    """The email a live invite made from `state`'s project would sign in, or None (unknown, used, lapsed,
    malformed, or made from another project). Spends nothing. `state` is the answering console's, and required,
    so no caller can forget it."""
    hit = _find_invite(load(path, log), token, _now(now), project_key(state))
    return hit["email"] if hit else None


def _proven(devices: list[dict], cookie_value: object) -> dict | None:
    """The device row this cookie value proves (id found, secret's hash equal in constant time), or None."""
    m = COOKIE_VALUE.match(cookie_value) if isinstance(cookie_value, str) else None
    if m is None:
        return None
    ident, want = m.group(1), _sha(m.group(2))
    for d in devices:
        if d["id"] == ident:
            return d if _same(d["sha256"], want) else None
    return None


def redeem(path: Path | None, token: object, device_label: str, state: Path,
           now: datetime | None = None, current: object = None) -> tuple[str, str, str] | None:
    """Spend a live invite: (device id, cookie value, email), or None when the invite is unknown, used or lapsed.
    Under the file's lock from read to rename: of two presses, exactly one wins. Logged in `state`'s role log, by
    the device's own email.

    `current` is the device cookie the request already carries (credential(), or None). When it proves a device
    of the invite's SAME email, the invite's project is added to that device and its cookie is kept: one browser,
    one device, however many projects invited it. Otherwise a new device is made, holding the invite's project.
    A cookie of ANOTHER email is never extended (it would grant that login a project it was not invited to)."""
    at = _now(now)
    lab = device_label if isinstance(device_label, str) and LABEL.match(device_label) else "a browser on another system"
    with locked(path) as p:
        doc = _parse(p)
        hit = _find_invite(doc, token, at, project_key(state))   # `state`: the answering console's (F10)
        if hit is None:
            return None   # nothing written, nothing logged
        invites =[i for i in _live(doc["invites"], at) if i["id"] != hit["id"]]
        mine = _proven(doc["devices"], current)
        if mine is not None and mine["email"] == hit["email"]:
            projects = mine["projects"] + ([] if hit["project"] in mine["projects"] else [hit["project"]])
            if len(projects) > MAX_PROJECTS:
                raise DevicesError(f"this browser is signed in to {MAX_PROJECTS} projects already")
            devices = [{**d, "projects": projects} if d["id"] == mine["id"] else d for d in doc["devices"]]
            _logged(p, state, hit["email"], "signin", hit["email"], mine["id"],
                    {"invites": invites, "devices": devices})
            return mine["id"], current, hit["email"]
        if len(doc["devices"]) >= MAX_DEVICES:
            raise DevicesError(f"{MAX_DEVICES} browsers are signed in already; revoke some under People first")
        ids = {d["id"] for d in doc["devices"]}
        ident = next(x for x in iter(lambda: secrets.token_hex(6), None) if x not in ids)
        secret = secrets.token_urlsafe(32)
        devices = doc["devices"] + [{"id": ident, "email": hit["email"], "sha256": _sha(secret),
                                     "created": _stamp(at), "label": lab, "projects": [hit["project"]]}]
        _logged(p, state, hit["email"], "signin", hit["email"], ident, {"invites": invites, "devices": devices})
    return ident, f"{ident}.{secret}", hit["email"]


def device(path: Path | None, cookie_value: object, log=None) -> dict | None:
    """The device this cookie value proves, as {id, email, projects}, or None. Re-read when the file changes (a
    revoke). Whether it may enter a given console is `admitted`'s to say, not this."""
    d = _proven(load(path, log)["devices"], cookie_value)
    return {"id": d["id"], "email": d["email"], "projects": list(d["projects"])} if d else None


def who(path: Path | None, cookie_value: object, log=None) -> str | None:
    """The email of the device this cookie value proves, or None, on ANY console: callers that gate a console use
    `device` and `admitted` instead."""
    d = device(path, cookie_value, log)
    return d["email"] if d else None


def listing(path: Path | None = None, log=None) -> list[dict]:
    """Every device, oldest first: {id, email, created, label, projects}; never a hash. People shows only the
    ones `admitted` here, and not their projects (paths stay off the page)."""
    return [{k: (list(d[k]) if k == "projects" else d[k]) for k in ("id", "email", "created", "label", "projects")}
            for d in load(path, log)["devices"]]


def revoke(path: Path | None, device_id: object, state: Path, by: str | None = None,
           here: tuple[str, dict | None] | None = None, now: datetime | None = None) -> str | None:
    """Sign a device out: return its email, or None when there is no such device (or, with `here` = (project_key,
    that project's roles or None), none `admitted` there: a console revokes only the devices it lets in, which
    are the ones it lists). Logged in `state`'s role log; `by` is the revoking owner's email, None from the
    terminal, which may revoke any device on the machine."""
    if not isinstance(device_id, str) or not DEVICE_ID.match(device_id):
        return None
    if by is not None and OP.email_problem(by):
        raise DevicesError(OP.email_problem(by))
    with locked(path) as p:
        doc = _parse(p)
        hit = next((d for d in doc["devices"] if d["id"] == device_id), None)
        if hit is None or (here is not None and not admitted(hit, *here)):
            return None
        devices = [d for d in doc["devices"] if d["id"] != device_id]
        _logged(p, state, by, "revoke", hit["email"], device_id,
                {"invites": _live(doc["invites"], _now(now)), "devices": devices})
    return hit["email"]


def cookie_header(value: str, origin: str) -> str:
    """The Set-Cookie value for a device. SameSite=Lax, not Strict: Strict drops the cookie when the console is
    opened from a link elsewhere (a notification in the team's channel). Secure exactly when the origin is https."""
    return (f"{COOKIE}={value}; HttpOnly; SameSite=Lax; Path=/; Max-Age={MAX_AGE}"
            + ("; Secure" if origin.startswith("https://") else ""))


def credential(headers) -> str | None:
    """The one `overture-device` cookie value a request carries, shape-checked; None for none, two, or a bad one."""
    found = []
    for line in headers.get_all("Cookie") or []:
        for part in str(line).split(";"):
            name, eq, value = part.strip().partition("=")
            if eq and name == COOKIE:
                found.append(value)
    return found[0] if len(found) == 1 and COOKIE_VALUE.match(found[0]) else None
