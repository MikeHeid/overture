"""Who made each owner decision (1.38.0): the Access login behind each owner write.

Every owner write was stored `by: "owner"`, so with several people behind one
console's Access policy, a lock could not say who took it. The console server
already verifies an Access token on every owner request; its `email` claim is
now kept for each record the request writes.

**Where it lives.** Beside the store, never in a store record, for the reason
`names.py` gives: a field the schema does not know stops an older kit from
starting on the store at all. So the store keeps its shape and each email is a
line of a sidecar:

    STATE/operators.jsonl    one line per record: {"email": EMAIL, "id": RECORD_ID}

The file is append-only; a record keeps the first email it was given (a retried
write is the same record). A line that is not well formed is refused on load,
by line number, never skipped. Writes that no person made (cron, triggers,
replays) and writes through the agent's door get no line.

**What leaves the console.** The email stays in the console: its feed shows it
to whoever can open the console already. The committed ruling files that
`fold.py export` writes carry a short name instead, and only one the owner set:

    STATE/operator-names.json    {"names": {EMAIL: NAME}}

set with `agent.py operator-name EMAIL NAME`. With no name for an email, the
export carries nothing, so its file is byte for byte what 1.37 wrote (the owner
chose this on 2026-10-14: no email in a repository that may be public).
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from pathlib import Path

from . import names as N
from . import schema as S

FILE = "operators.jsonl"
NAMES_FILE = "operator-names.json"
MAX_EMAIL = 254


class OperatorsError(Exception):
    """An operators or operator-names file the kit refuses to read, or a value it refuses; named."""


def email_problem(v: object) -> str | None:
    """Why `v` is not an email to keep, or None. The shape `account_email` holds the footer's to."""
    if not isinstance(v, str) or not 3 <= len(v) <= MAX_EMAIL or v.count("@") != 1 or v.startswith("@") \
            or v.endswith("@") or any(c.isspace() or not c.isprintable() for c in v):
        return f"{v!r} is not an email address"
    return None


def name_problem(v: object) -> str | None:
    """Why `v` is not a short operator name, or None: the agent-name shape, as it is printed the same way."""
    if not isinstance(v, str) or len(v) > N.MAX_NAME or not N.NAME.fullmatch(v):
        return (f"operator name {v!r} is refused: use 1 to {N.MAX_NAME} characters of lowercase letters, "
                f"digits and single hyphens, starting with a letter (e.g. michael)")
    return None


class Operators:
    """The operators sidecar of one state directory: record id -> the email of whoever wrote it."""

    def __init__(self, state: Path) -> None:
        self.path = Path(state) / FILE
        self._lock = threading.Lock()
        self._by_id: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        lines = self.path.read_text(encoding="utf-8").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        elif lines:
            raise OperatorsError(f"{self.path}: line {len(lines)} has no newline, so a write was cut short. Move "
                                 f"that line aside by hand; the kit does not guess what it said")
        for n, line in enumerate(lines, 1):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise OperatorsError(f"{self.path}:{n}: not JSON ({e.msg})") from None
            if not isinstance(rec, dict) or set(rec) != {"id", "email"}:
                raise OperatorsError(f"{self.path}:{n}: a line is exactly {{\"email\": EMAIL, \"id\": RECORD_ID}}")
            if not isinstance(rec["id"], str) or not S.RECORD_ID.match(rec["id"]):
                raise OperatorsError(f"{self.path}:{n}: id {rec['id']!r} is not a record id")
            why = email_problem(rec["email"])
            if why:
                raise OperatorsError(f"{self.path}:{n}: {why}")
            self._by_id.setdefault(rec["id"], rec["email"])

    def mapping(self) -> dict[str, str]:
        """A copy of record id -> email."""
        with self._lock:
            return dict(self._by_id)

    def add(self, rid: str, email: str) -> bool:
        """Keep `email` for record `rid`, unless it has one already (a retry keeps the first); True when written."""
        why = email_problem(email)
        if why:
            raise OperatorsError(why)
        if not isinstance(rid, str) or not S.RECORD_ID.match(rid):
            raise OperatorsError(f"{rid!r} is not a record id")
        with self._lock:
            if rid in self._by_id:
                return False
            line = json.dumps({"email": email, "id": rid}, sort_keys=True, separators=(",", ":")) + "\n"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())
                finally:
                    fcntl.flock(fh, fcntl.LOCK_UN)
            self._by_id[rid] = email
            return True


def load_beside(store_path: Path) -> dict[str, str]:
    """Record id -> email from the operators file beside a store file; {} when there is none."""
    return Operators(Path(store_path).parent).mapping()


def load_names(state: Path) -> dict[str, str]:
    """Email -> short name from STATE/operator-names.json; {} when there is none. A bad file is refused, named."""
    p = Path(state) / NAMES_FILE
    if not p.exists():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise OperatorsError(f"{p}: not readable JSON ({e})") from None
    got = doc.get("names") if isinstance(doc, dict) and set(doc) == {"names"} else None
    if not isinstance(got, dict):
        raise OperatorsError(f"{p}: the file is exactly {{\"names\": {{EMAIL: NAME}}}}")
    for email, name in got.items():
        why = email_problem(email) or name_problem(name)
        if why:
            raise OperatorsError(f"{p}: {why}")
    return dict(got)


def set_name(state: Path, email: str, name: str | None) -> dict[str, str]:
    """Set (or, with None, clear) the short name for `email`; return the whole map as written."""
    why = email_problem(email) or (name_problem(name) if name is not None else None)
    if why:
        raise OperatorsError(why)
    got = load_names(state)
    if name is None:
        got.pop(email, None)
    else:
        got[email] = name
    p = Path(state) / NAMES_FILE
    tmp = p.with_name(f".{NAMES_FILE}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"names": dict(sorted(got.items()))}, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)   # whole or not at all: a reader never sees half a file
    return got
