"""Triggers: HTTP calls (webhooks, 0.12.0) and scheduled clock ticks (cron, 0.15.0) that fire a named playbook.

A trigger is defined in `.overture/triggers.json`:

    {
      "triggers": {
        "pr-merged": {
          "playbook": "security-review",
          "token_sha256": "<sha256 of the bearer token, hex, lowercase>"
        }
      }
    }

The server exposes `POST /api/trigger/<name>` on the owner door. The caller
must satisfy BOTH gates:

1. **Cloudflare Access** — configured on the Access application to accept a
   service token (`CF-Access-Client-Id` + `CF-Access-Client-Secret`) in addition
   to interactive logins. The overture never sees the Access headers; the
   tunnel validates them.
2. **Per-trigger bearer token** — the caller sends `Authorization: Bearer <token>`
   (or `X-Console-Trigger-Token: <token>`). The server hashes the received
   token with SHA-256 and compares to the configured `token_sha256`.

The server NEVER stores the plaintext token. Rotate by generating a new token,
putting its sha256 into the file, and giving the plaintext to the sender.

**GitHub webhooks (1.59.0, OPEN-DECISIONS G1-G3)**: GitHub signs with HMAC, not
a bearer token, and cannot send Access headers. A trigger with a `github` block
takes `POST /api/github/<name>`, served only behind Cloudflare Access, where a
Bypass rule on `/api/github/*` lets GitHub through and the signature is the gate:

        "pr-opened": {"playbook": "triage", "github": {"events": ["pull_request"]}}

The secret is the owner's, set in the terminal (`agent.py github-secret NAME`), and
kept in STATE/github-secrets/NAME.json (0600), never in the repository. A `ping`
is answered and fires nothing; an event not listed is answered and fires nothing;
a delivery id already received is refused. The payload is not given to the playbook.

Rate limit: at most one firing per `MIN_INTERVAL_S` seconds per trigger (in-process).
A rejected call responds 429 and names the next-allowed time.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from . import rootfs as RF
from .registry import RegistryError, read_regular

FILE = ".overture/triggers.json"
MAX_FILE = 32 * 1024
MAX_TRIGGERS = 64
MAX_BODY = 256 * 1024
MIN_INTERVAL_S = 10.0
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}\Z")
EVENT = re.compile(r"^[a-z][a-z_]{0,63}\Z")          # GitHub's X-GitHub-Event names: pull_request, push, ...
DELIVERY = re.compile(r"^[0-9A-Za-z-]{1,64}\Z")      # X-GitHub-Delivery, a GUID
MAX_EVENTS = 32
SECRET_DIR = "github-secrets"
_SECRET = re.compile(r"^[\x20-\x7e]{16,256}\Z")      # printable ASCII: what GitHub's Secret field takes
DELIVERIES_KEPT = 4096   # delivery ids remembered per process, for the replay guard


class TriggerError(ValueError):
    pass


@dataclass(frozen=True)
class Trigger:
    name: str
    playbook: str
    token_sha256: str | None    # None → webhook disabled (cron-only trigger)
    cron: tuple | None          # (minutes, hours, days-of-month, months, days-of-week) each a frozenset of ints
    github_events: frozenset | None = None   # 1.59.0: None → no GitHub route; else the events that fire it

    def to_public(self) -> dict:
        """For /view: token hash + cron shape aren't exposed; only name + playbook + what trigger kinds are armed."""
        kinds = []
        if self.token_sha256:
            kinds.append("webhook")
        if self.cron:
            kinds.append("cron")
        if self.github_events:
            kinds.append("github")
        return {"name": self.name, "playbook": self.playbook, "kinds": kinds}


HISTORY_LIMIT = 100   # most-recent firings kept in-process (bounded ring); older ones drop off


class Store:
    """Thread-safe in-process registry + rate limiter + firing history (0.16.0)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._triggers: dict[str, Trigger] = {}
        self._last_fired: dict[str, float] = {}
        import collections
        self._history: collections.deque = collections.deque(maxlen=HISTORY_LIMIT)
        self._deliveries: collections.deque = collections.deque()   # 1.59.0: (name, id), oldest first
        self._delivered: set = set()

    def set_all(self, triggers: dict[str, Trigger]) -> None:
        with self._lock:
            self._triggers = dict(triggers)
            self._last_fired = {k: v for k, v in self._last_fired.items() if k in triggers}

    def get(self, name: str) -> Trigger | None:
        with self._lock:
            return self._triggers.get(name)

    def all(self) -> dict[str, Trigger]:
        with self._lock:
            return dict(self._triggers)

    def claim(self, name: str, now: float) -> float | None:
        """Record a firing at `now` and return None; or return the next-allowed time when rate-limited."""
        with self._lock:
            last = self._last_fired.get(name)
            if last is not None and now - last < MIN_INTERVAL_S:
                return last + MIN_INTERVAL_S
            self._last_fired[name] = now
            return None

    def admit(self, name: str, delivery: str, now: float) -> str | float | None:
        """1.59.0: one signed GitHub delivery. "replay" when its id was received before; the next-allowed
        time when rate-limited (the id is NOT kept, so GitHub's Redeliver works later); else None, and both
        the firing and the id are kept. One lock, so two copies of one delivery cannot both fire."""
        with self._lock:
            key = (name, delivery)
            if key in self._delivered:
                return "replay"
            last = self._last_fired.get(name)
            if last is not None and now - last < MIN_INTERVAL_S:
                return last + MIN_INTERVAL_S
            self._last_fired[name] = now
            self._delivered.add(key)
            self._deliveries.append(key)
            while len(self._deliveries) > DELIVERIES_KEPT:
                self._delivered.discard(self._deliveries.popleft())
            return None

    def log(self, name: str, kind: str, ts: str, records: int, skipped: int, error: str | None = None) -> None:
        """Append one firing record to the in-process history ring, newest-first on reads via `recent`."""
        with self._lock:
            self._history.append({"name": name, "kind": kind, "ts": ts,
                                  "records": records, "skipped": skipped, "error": error})

    def recent(self, limit: int = 20) -> list[dict]:
        """The newest `limit` firings, newest first."""
        with self._lock:
            items = list(self._history)
        items.reverse()
        return items[: max(1, min(HISTORY_LIMIT, limit))]


def load(root: Path) -> dict[str, Trigger]:
    """Read `.overture/triggers.json` and return every well-formed trigger, keyed by name.

    Returns {} when the file is absent. A single malformed trigger raises TriggerError NAMING the first
    problem, so the server refuses to start half-configured. The playbook name is NOT resolved here;
    the webhook refuses at firing time if the playbook file is missing.
    """
    try:
        if RF.confined():
            raw = RF.read(Path(root), FILE, MAX_FILE)
        else:
            raw = read_regular(Path(root) / FILE, MAX_FILE)
    except FileNotFoundError:
        # 1.19.2: a missing .overture/triggers.json is a project with no triggers configured,
        # not a startup fault. Catch BEFORE the broad OSError clause.
        return {}
    except (RegistryError, RF.Refused, ValueError, OSError) as e:
        raise TriggerError(str(e)) from None
    if raw is None:
        return {}
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise TriggerError(f"{FILE} is not JSON: {e}") from None
    if not isinstance(doc, dict):
        raise TriggerError(f"{FILE}: top-level must be an object")
    triggers = doc.get("triggers")
    if triggers is None:
        return {}
    if not isinstance(triggers, dict):
        raise TriggerError(f"{FILE}: triggers must be an object mapping names to definitions")
    if len(triggers) > MAX_TRIGGERS:
        raise TriggerError(f"{FILE}: {len(triggers)} triggers; at most {MAX_TRIGGERS}")
    out: dict[str, Trigger] = {}
    for name, cfg in triggers.items():
        if not isinstance(name, str) or not NAME.match(name):
            raise TriggerError(f"{FILE}: trigger name {name!r} is lowercase letters, digits, '_' or '-' (1-64)")
        out[name] = _validate(name, cfg)
    return out


def _validate(name: str, cfg: object) -> Trigger:
    if not isinstance(cfg, dict):
        raise TriggerError(f"{FILE}: triggers[{name!r}] must be an object")
    playbook = cfg.get("playbook")
    if not isinstance(playbook, str) or not NAME.match(playbook):
        raise TriggerError(f"{FILE}: triggers[{name!r}].playbook must name a playbook (slug-shaped)")
    token_sha = cfg.get("token_sha256")
    if token_sha is not None:
        if not isinstance(token_sha, str) or not _SHA256_HEX.match(token_sha):
            raise TriggerError(f"{FILE}: triggers[{name!r}].token_sha256 is 64 lowercase hex chars "
                               "(sha256 of the bearer token you give the sender)")
    cron_raw = cfg.get("cron")
    cron_fields: tuple | None = None
    if cron_raw is not None:
        if not isinstance(cron_raw, str):
            raise TriggerError(f"{FILE}: triggers[{name!r}].cron must be a 5-field cron string "
                               "like '0 9 * * MON' or '*/15 * * * *'")
        try:
            cron_fields = parse_cron(cron_raw)
        except ValueError as e:
            raise TriggerError(f"{FILE}: triggers[{name!r}].cron: {e}") from None
    events = _github_events(name, cfg.get("github")) if "github" in cfg else None
    if token_sha is None and cron_fields is None and events is None:
        raise TriggerError(f"{FILE}: triggers[{name!r}] must set at least one of token_sha256 (webhook), "
                           "cron (schedule) or github (signed GitHub webhook)")
    return Trigger(name=name, playbook=playbook, token_sha256=token_sha, cron=cron_fields, github_events=events)


def _github_events(name: str, gh: object) -> frozenset:
    """1.59.0: `"github": {"events": ["pull_request", ...]}`, exactly; `ping` is always answered, never listed."""
    shape = f'{FILE}: triggers[{name!r}].github is exactly {{"events": ["pull_request", ...]}}'
    if not isinstance(gh, dict) or set(gh) != {"events"}:
        raise TriggerError(shape)
    events = gh["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
        raise TriggerError(f"{shape}, with 1-{MAX_EVENTS} events")
    for e in events:
        if not isinstance(e, str) or not EVENT.match(e):
            raise TriggerError(f"{FILE}: triggers[{name!r}].github.events: {e!r} is not a GitHub event name "
                               "(lowercase letters and '_', as X-GitHub-Event sends it)")
        if e == "ping":
            raise TriggerError(f"{FILE}: triggers[{name!r}].github.events: 'ping' is answered and never fires; "
                               "leave it out")
    return frozenset(events)


# -- GitHub's signature and the owner's secret (1.59.0) ---------------------------------------------------

def signature_matches(secret: str, body: bytes, header: str | None) -> bool:
    """`X-Hub-Signature-256: sha256=<hex>` over the exact body bytes, compared in constant time."""
    if not isinstance(header, str) or not header.startswith("sha256="):
        return False
    want = hmac.new(secret.encode("ascii"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256="):].encode("ascii", "replace"), want.encode("ascii"))


def _secret_path(state: Path, name: str) -> Path:
    if not isinstance(name, str) or not NAME.match(name):
        raise TriggerError("a trigger name is lowercase letters, digits, '_' or '-' (1-64)")
    return Path(state) / SECRET_DIR / f"{name}.json"


def load_secret(state: Path, name: str) -> str | None:
    """The trigger's GitHub secret, or None when none is set. A file the kit refuses raises TriggerError,
    naming the file but never its contents."""
    p = _secret_path(state, name)
    try:
        raw = read_regular(p, 4096, nofollow=True)
    except (RegistryError, ValueError, OSError) as e:
        raise TriggerError(f"{p}: not readable ({type(e).__name__})") from None
    if raw is None:
        return None
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        doc = None
    secret = doc.get("secret") if isinstance(doc, dict) and set(doc) == {"secret"} else None
    if not isinstance(secret, str) or not _SECRET.match(secret):
        raise TriggerError(f'{p}: the file is exactly {{"secret": "..."}}, 16-256 printable characters')
    return secret


def mint_secret() -> str:
    import secrets
    return secrets.token_urlsafe(32)


def set_secret(state: Path, name: str, secret: str | None) -> None:
    """Write (None: remove) the trigger's GitHub secret: 0600, written whole and renamed into place, and
    logged in the role log by the trigger's name only (RO.logged_change), never by the secret."""
    from . import roles as RO
    from .notify import _write
    p = _secret_path(state, name)
    if secret is not None and not _SECRET.match(secret):
        raise TriggerError("a GitHub secret is 16-256 printable ASCII characters")

    def plan():
        had = p.exists()
        if secret is None and not had:
            return None
        if secret is not None:
            p.parent.mkdir(mode=0o700, exist_ok=True)
        return ({"setting": {"key": "github_secret", "from": name if had else None,
                             "to": name if secret is not None else None}},
                lambda: _write(p, {"secret": secret} if secret is not None else None))
    RO.logged_change(state, None, plan)


# -- cron parser ------------------------------------------------------------------------
# Minute Hour DayOfMonth Month DayOfWeek. `*`, `*/n`, ranges `a-b`, lists `a,b,c`, and `a-b/n`. Named
# months (JAN..DEC) and days-of-week (SUN..SAT) are accepted; shortcuts like `@daily` are not — spell
# the full form so a reader of the config can see exactly when it fires. DoW: 0 or 7 = Sunday.

_MONTH = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,"JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}
_DOW = {"SUN":0,"MON":1,"TUE":2,"WED":3,"THU":4,"FRI":5,"SAT":6}
_FIELDS = (("minute", 0, 59, {}),
           ("hour", 0, 23, {}),
           ("day-of-month", 1, 31, {}),
           ("month", 1, 12, _MONTH),
           ("day-of-week", 0, 6, _DOW))


def parse_cron(spec: str) -> tuple:
    """Parse a 5-field cron string. Returns a tuple of frozensets, one per field."""
    parts = spec.strip().split()
    if len(parts) != 5:
        raise ValueError(f"cron has 5 fields separated by spaces; got {len(parts)}")
    out = []
    for raw, (fname, lo, hi, aliases) in zip(parts, _FIELDS):
        out.append(frozenset(_parse_cron_field(raw, lo, hi, aliases, fname)))
    return tuple(out)


def _parse_cron_field(raw: str, lo: int, hi: int, aliases: dict, fname: str) -> set:
    def lookup(v: str) -> int:
        v = v.strip().upper()
        if v in aliases:
            return aliases[v]
        try:
            return int(v)
        except ValueError:
            raise ValueError(f"{fname} cannot read {v!r}") from None
    out: set = set()
    for piece in raw.split(","):
        step = 1
        if "/" in piece:
            piece, step_s = piece.rsplit("/", 1)
            try:
                step = int(step_s)
            except ValueError:
                raise ValueError(f"{fname} step {step_s!r} is not an integer") from None
            if step < 1:
                raise ValueError(f"{fname} step must be >= 1")
        if piece == "*" or piece == "":
            a, b = lo, hi
        elif "-" in piece:
            a_s, b_s = piece.split("-", 1)
            a, b = lookup(a_s), lookup(b_s)
        else:
            v = lookup(piece)
            a, b = v, v
        # Day-of-week accepts 7 as a Sunday alias (same as 0).
        if fname == "day-of-week":
            if a == 7: a = 0
            if b == 7: b = 0
        if a < lo or b > hi or a > b:
            raise ValueError(f"{fname} {piece!r} is out of range {lo}..{hi}")
        out.update(range(a, b + 1, step))
    return out


def cron_matches(cron: tuple, now) -> bool:
    """True when the local-time `now` matches every cron field. `now` is a datetime.datetime."""
    minutes, hours, dom, months, dow = cron
    return (now.minute in minutes and now.hour in hours and now.day in dom
            and now.month in months and (now.weekday() + 1) % 7 in dow)
#         ^ Python weekday: Mon=0..Sun=6; cron: Sun=0..Sat=6. (Mon=0 -> cron 1); (Sun=6 -> cron 0).


def token_from_header(auth: str | None, extra: str | None) -> str | None:
    """Pull a bearer token from either `Authorization: Bearer <token>` or `X-Console-Trigger-Token: <token>`.

    Returns the token string without the `Bearer ` prefix, or None when neither header carries one.
    """
    for v in (auth, extra):
        if isinstance(v, str) and v:
            s = v.strip()
            if s.lower().startswith("bearer "):
                s = s[7:].strip()
            if s:
                return s
    return None


def token_matches(trigger: Trigger, token: str) -> bool:
    """Constant-time comparison of sha256(token) against the configured sha256."""
    if not isinstance(token, str) or not token:
        return False
    got = hashlib.sha256(token.encode("utf-8", errors="strict")).hexdigest()
    return hmac.compare_digest(got, trigger.token_sha256)


def mint() -> tuple[str, str]:
    """Mint a fresh (token, token_sha256) pair for the operator to copy into triggers.json + the sender."""
    import secrets
    token = "ck_trg_" + secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()
