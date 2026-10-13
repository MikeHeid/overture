"""Lessons — the audit trail turns generative.

When the owner withdraws a ruling ("this no longer applies") or keeps it unchecked
("still stands, but don't check it against the files any more"), the reason they
give is a POLICY SIGNAL for every future session: don't make this mistake again, or:
this rule still matters but the evidence has moved. Lessons captures those signals
as a plain-text file every agent reads on session start, so the project's accumulated
wisdom travels with the code — not just inside the owner's head.

Storage: a JSONL file under STATE/lessons.jsonl, rewritten whole via atfile.write_at
on every record (small files, atomic swap). Each row:

    {
      "ts": "2026-10-15T14:00:00Z",
      "qid": "A/Q7",
      "item": "A",
      "kind": "withdraw" | "untrack",
      "text": "Should we use 5 retries with exponential backoff?",
      "reason": "Load testing at 10x showed retries cascaded failures.",
      "replaced_by": null
    }

Caps: MAX_LESSONS 2000 (count-FIFO) and MAX_FILE 2 MiB (byte-FIFO); on `record()` the
oldest rows drop until BOTH caps hold, so a wall of long reasons cannot wedge the
feature. The reason is left intact up to MAX_REASON (aligned with schema.MAX_TEXT),
so the policy signal travels whole.

Trust: this module writes only under STATE. The server never reads a lesson's text
or reason during a request and never exposes them beyond the owner door and the
`agent.py lessons` CLI (STATE socket is 0600 under 0700). The file never travels
to a peer. Malformed rows the parser cannot read are DROPPED on the next `record()`
rewrite — the stderr line names the count so the owner knows the file was touched.
"""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import atfile as AF
from . import schema as S

FILE = "lessons.jsonl"
MAX_FILE = 2 << 20              # 2 MiB on disk; byte-FIFO prune on record
MAX_LESSONS = 2000              # count-FIFO prune on record (whichever cap bites first)
MAX_TEXT = 2000                 # question text (one-liner); longer gets soft-truncated
MAX_REASON = S.MAX_TEXT         # 20 000 — the owner's own words; aligned with the store so no reason falls in a gap
MAX_QID = 128
MAX_ITEM = 128

KINDS = ("withdraw", "untrack")
TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
QID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,127}/Q\d+\Z")
ITEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,127}\Z")

# O_DIRECTORY and O_NOFOLLOW are POSIX-only; the plugin targets POSIX, but the file is read on win32 for IDE
# tooling, where the module must still import. getattr with 0 fallback keeps the import clean; the actual read
# through atfile.read_at still refuses symlinks on the FILE level (where it matters).
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
STATE_FLAGS = os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | os.O_CLOEXEC


class LessonError(ValueError):
    """A lesson the kit refuses to write; the message says why and holds no project secret."""


@contextmanager
def _state_fd(state: Path) -> Iterator[int]:
    """Hold an open descriptor on STATE for the atfile primitives, close on exit."""
    sfd = os.open(state, STATE_FLAGS)
    try:
        yield sfd
    finally:
        os.close(sfd)


def _trim_oneline(text: str, cap: int) -> str:
    """Soft-truncate the question text to one line, cap chars. Whitespace is collapsed so a
    `\\n## ...` in the title can never spell a heading in the folded Markdown."""
    one = " ".join((text or "").split())
    if len(one) <= cap:
        return one
    return one[: cap - 1] + "…"


def _check(row: object) -> None:
    """Validate a row's shape. Raises LessonError for every malformation (never KeyError
    on a missing key, never TypeError on a non-string field): a stored-row reader expects
    all failures as LessonError, so load() can drop the row without faulting the page."""
    if not isinstance(row, dict):
        raise LessonError("row must be a JSON object")
    kind = row.get("kind")
    if kind not in KINDS:
        raise LessonError(f"kind {kind!r} is not in {KINDS}")
    ts = row.get("ts")
    if not isinstance(ts, str) or not TS_RE.match(ts):
        raise LessonError("ts must be ISO-UTC like 2026-10-15T14:00:00Z")
    qid = row.get("qid")
    if not isinstance(qid, str) or len(qid) > MAX_QID or not QID_RE.match(qid):
        raise LessonError(f"qid {qid!r} is malformed")
    item = row.get("item")
    if not isinstance(item, str) or len(item) > MAX_ITEM or not ITEM_RE.match(item):
        raise LessonError(f"item {item!r} is malformed")
    text = row.get("text")
    if not isinstance(text, str) or not text.strip():
        raise LessonError("text must be a non-empty string")
    reason = row.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise LessonError("reason must be a non-empty string")
    if len(reason) > MAX_REASON:
        raise LessonError(f"reason is {len(reason)} characters; limit is {MAX_REASON}")
    rb = row.get("replaced_by")
    if rb is not None and (not isinstance(rb, str) or not QID_RE.match(rb)):
        raise LessonError(f"replaced_by must be null or a qid; got {rb!r}")


def load(state: Path) -> list[dict]:
    """Read STATE/lessons.jsonl. Returns the full list of valid rows, oldest first.

    An absent file returns []. A malformed line is skipped with a stderr note; one bad row
    never faults a page load. Splits on "\\n" only, so a control character inside a reason
    cannot forge or split a row (`splitlines` would split on U+2028, U+0085 and others).
    """
    with _state_fd(state) as sfd:
        raw = AF.read_at(sfd, FILE, MAX_FILE)
    if raw is None:
        return []
    rows: list[dict] = []
    dropped = 0
    for line in raw.decode("utf-8", "replace").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            _check(obj)
        except (json.JSONDecodeError, LessonError):
            dropped += 1
            continue
        rows.append(obj)
    if dropped:
        # The next record() rewrites the file from these valid rows, so malformed lines ARE
        # dropped from disk at that point. Owner sees the stderr line and knows.
        sys.stderr.write(f"console lessons: {dropped} malformed row(s) skipped "
                         f"(will be dropped on next record)\n")
    return rows


def _encode_lines(rows: list[dict]) -> list[bytes]:
    return [json.dumps(r, ensure_ascii=False, sort_keys=True).encode("utf-8") for r in rows]


def _join(lines: list[bytes]) -> bytes:
    return b"\n".join(lines) + b"\n" if lines else b""


def _fit(rows: list[dict]) -> tuple[list[dict], bytes]:
    """Return the newest rows that fit under both caps, plus the already-encoded body for them.
    Byte cap bites first on long reasons; count cap bites first on short ones. Each row is
    encoded exactly once per record (linear in len(rows)); the prune walks a running byte sum
    rather than re-encoding on every pop."""
    rows = rows[-MAX_LESSONS:]
    if not rows:
        return [], b""
    lines = _encode_lines(rows)
    sizes = [len(line) + 1 for line in lines]        # +1 for the row's trailing newline
    total = sum(sizes)
    i = 0
    while i < len(rows) and total > MAX_FILE:
        total -= sizes[i]
        i += 1
    return rows[i:], _join(lines[i:])


def record(state: Path, qid: str, item: str, kind: str, text: str, reason: str,
           now_iso: str, replaced_by: str | None = None) -> dict:
    """Append a lesson row to STATE/lessons.jsonl. Returns the stored row.

    The caller holds Console._lock, so this never races a parallel refactor on the same qid.
    Reason is kept whole up to MAX_REASON (aligned with schema.MAX_TEXT, 20 000) — a truncated
    owner reason loses the signal, so a longer one is refused by name. The file is pruned
    FIFO by BOTH count and bytes until it fits, so no amount of long reasons can wedge the
    feature.
    """
    row = {
        "ts": now_iso,
        "qid": qid,
        "item": item,
        "kind": kind,
        "text": _trim_oneline(text, MAX_TEXT),
        "reason": reason,
        "replaced_by": replaced_by,
    }
    _check(row)
    _, data = _fit([*load(state), row])
    if len(data) > MAX_FILE:
        # Can only happen if a single row is itself larger than MAX_FILE, which _check already refuses
        # at MAX_REASON (20 000 chars, ~20 KB) — so this is a tripwire for a future field growing.
        raise LessonError(f"lessons file would be {len(data)} bytes; limit is {MAX_FILE}")
    with _state_fd(state) as sfd:
        AF.write_at(sfd, FILE, data)
    return row


def as_view(rows: list[dict]) -> dict:
    """Shape for view.lessons: just the summary. The full list is read via `agent.py lessons`;
    we don't travel every lesson's reason through every /api/view."""
    if not rows:
        return {"count": 0, "newest_ts": None}
    return {"count": len(rows), "newest_ts": rows[-1]["ts"]}


def to_markdown(rows: list[dict]) -> str:
    """Render the full list as a Markdown document — what `agent.py lessons [--fold PATH]`
    writes to disk or stdout. Newest first (reading order), one H2 per lesson.

    The question `text` is a one-liner (collapsed on record so a newline cannot inject a
    heading); the owner's `reason` is wrapped as a 4-space-indented code block so no
    Markdown spelling inside it (headings, lists, HTML) activates. Future agents read the
    reason as prose, but the format itself refuses to pretend any part of it is structure.
    """
    out: list[str] = ["# Lessons",
                      "",
                      "Rulings the owner withdrew or stopped checking, in reverse chronological",
                      "order. Each lesson records the owner's reasoning so future sessions do",
                      "not re-litigate the same ground.",
                      ""]
    if not rows:
        out.append("_No lessons recorded yet._")
        out.append("")
        return "\n".join(out)
    kind_label = {"withdraw": "withdrawn", "untrack": "kept unchecked"}
    for row in reversed(rows):
        date = row["ts"][:10]
        klabel = kind_label.get(row["kind"], row["kind"])
        out.append(f"## {date} — {row['qid']} ({klabel})")
        out.append("")
        out.append(f"**Ruling:** {row['text']}")
        out.append("")
        out.append(f"**Why {klabel}:**")
        out.append("")
        for line in row["reason"].split("\n") or [""]:
            out.append("    " + line)
        out.append("")
        if row.get("replaced_by"):
            out.append(f"**Replaced by:** `{row['replaced_by']}`")
            out.append("")
    return "\n".join(out)
