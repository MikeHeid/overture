"""Two-key locks (1.43.0, OPEN-DECISIONS.md W6): in some areas a lock needs a second person.

The owner names two-key areas in the People tab (`roles.json` "two_key"). A
lock on a question inside one is not written to the store when it is taken:
it waits here, as the first key, until a second login that may lock there
(an administrator, or a member of that area) locks the same answer. Only then
is the lock written, by that second request.

    STATE/pending-locks.json   {"pending": {QID: {"answer": RECORD_ID, "email": EMAIL,
                                                  "at": UTC, "relock"?: REASON, "nonce"?: NONCE}}}

(`nonce`, on a re-lock's key: the confirmed answer is written as NONCE-a, so the first key's
own request sent again finds it landed. `confirming`: the second key's login, saved before
that answer is written, the only proof that two keys agreed: an answer's nonce is the
writer's to choose, so a re-lock whose lock failed is finished only on this mark.)
    STATE/lock-keys.jsonl      {"email": EMAIL, "id": LOCK_ID}: the first key of each
                               lock a second key confirmed (operators.jsonl names the second)

**Why outside the store.** Everything that acts on a lock reads the store:
the agents' view, the process request's "fold newly locked answers", the
ruling export, stale checks. A first key there would be acted on as a
ruling. Kept here, an unconfirmed lock is invisible to all of them, and to
an older kit, which never reads this file (a downgrade loses waiting first
keys, never confirms one).

`relock` marks a first key for a re-lock (the stale banner's "Still holds"):
confirmed, it writes the superseding answer and its lock, as `relock` does.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import operators as OP
from . import schema as S

FILE = "pending-locks.json"
KEYS_FILE = "lock-keys.jsonl"
MAX_REASON = 2000


class TwoKeyError(Exception):
    """A pending-locks file the kit refuses to read; named."""


def _entry_problem(qid: object, e: object) -> str | None:
    if not isinstance(qid, str) or not S.QID.match(qid):
        return f"{qid!r} is not a question id"
    if not isinstance(e, dict) or not {"answer", "email", "at"} <= set(e) <= {"answer", "email", "at", "relock",
                                                                              "nonce", "confirming"}:
        return 'an entry is {"answer", "email", "at", "relock"?, "nonce"?, "confirming"?}'
    if "confirming" in e and OP.email_problem(e["confirming"]):
        return OP.email_problem(e["confirming"])
    if "nonce" in e and (not isinstance(e["nonce"], str) or not S.NONCE.match(e["nonce"])):
        return f"nonce {e['nonce']!r} is not a nonce"
    if not isinstance(e["answer"], str) or not S.RECORD_ID.match(e["answer"]):
        return f"answer {e['answer']!r} is not a record id"
    if not isinstance(e["at"], str):
        return "at is a UTC time"
    if "relock" in e and (not isinstance(e["relock"], str) or not 0 < len(e["relock"]) <= MAX_REASON):
        return f"relock is a reason of 1 to {MAX_REASON} characters"
    return OP.email_problem(e["email"])


def load(state: Path) -> dict[str, dict]:
    """QID -> its waiting first key; {} when there is no file."""
    p = Path(state) / FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as e:
        raise TwoKeyError(f"{p}: not readable ({e})") from None
    except (ValueError, RecursionError) as e:
        raise TwoKeyError(f"{p}: not JSON ({type(e).__name__})") from None
    got = doc.get("pending") if isinstance(doc, dict) and set(doc) == {"pending"} else None
    if not isinstance(got, dict):
        raise TwoKeyError(f'{p}: the file is exactly {{"pending": {{QID: ENTRY}}}}')
    for qid, e in got.items():
        why = _entry_problem(qid, e)
        if why:
            raise TwoKeyError(f"{p}: {qid!r}: {why}")
    # One login is one key whatever its case: a hand-written "Alice@x" must not let alice@x confirm herself.
    return {qid: {**e, "email": e["email"].lower()} for qid, e in got.items()}


def save(state: Path, pending: dict[str, dict]) -> None:
    """Replace the file with `pending` (removed when empty): a fresh temp file no symlink names, one rename."""
    p = Path(state) / FILE
    if not pending:
        p.unlink(missing_ok=True)
        return
    data = (json.dumps({"pending": pending}, indent=2, sort_keys=True) + "\n").encode()
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


def first_keys(state: Path) -> OP.Operators:
    """Lock id -> the email of its first key: the operators sidecar's shape, in its own file."""
    return OP.Operators(state, file=KEYS_FILE)
