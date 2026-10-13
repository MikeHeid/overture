"""Lessons — the audit trail turns generative .

When the owner withdraws a ruling ("this no longer applies") or keeps it unchecked
("still stands, but don't check it against the files any more"), the reason they
give is a POLICY SIGNAL for every future session: don't make this mistake again, or:
this rule still matters but the evidence has moved. Lessons captures those signals
as a plain-text file every agent reads on session start, so the project's accumulated
wisdom travels with the code — not just inside the owner's head.

Storage: append-only JSONL under STATE/lessons.jsonl, written via atfile.write_at.
Each row:

    {
      "ts": "2026-10-15T14:00:00Z",
      "qid": "A/Q7",
      "item": "A",
      "kind": "withdraw" | "untrack",
      "text": "Should we use 5 retries with exponential backoff?",
      "reason": "Load testing at 10x showed retries cascaded failures.",
      "replaced_by": null
    }

Caps: MAX_LESSONS 2000 (file is pruned FIFO above that), MAX_FILE 2 MiB. A lesson
over the character caps is refused by name — the owner's reason is the signal, so a
truncated reason loses the point.

Trust: this module writes only under STATE. The server never reads a lesson's text
or reason during a request and never exposes them beyond the owner door and the
`agent.py lessons` CLI (STATE/tokens-gated). The file never travels to a peer.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from . import atfile as AF

FILE = "lessons.jsonl"
MAX_FILE = 2 << 20          # 2 MiB on disk
MAX_LESSONS = 2000
MAX_TEXT = 2000             # question text; one-liner
MAX_REASON = 10_000         # the owner's own words
MAX_QID = 128
MAX_ITEM = 128

KINDS = ("withdraw", "untrack")
TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
QID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,127}/Q\d+\Z")
ITEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,127}\Z")

STATE_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC


class LessonError(ValueError):
    """A lesson the kit refuses to write; the message says why and holds no project secret."""


def _trim(text: str, cap: int) -> str:
    """Soft-truncate: trim to cap chars, add an ellipsis if cut. Used for question text in the
    recorded row — the reason stays intact (or we refuse the record if it's over the cap)."""
    if len(text) <= cap:
        return text
    return text[: cap - 1] + "…"


def _check(row: dict) -> None:
    if row["kind"] not in KINDS:
        raise LessonError(f"kind {row['kind']!r} is not in {KINDS}")
    if not TS_RE.match(row["ts"]):
        raise LessonError("ts must be ISO-UTC like 2026-10-15T14:00:00Z")
    if not QID_RE.match(row["qid"]):
        raise LessonError(f"qid {row['qid']!r} is malformed")
    if not ITEM_RE.match(row["item"]):
        raise LessonError(f"item {row['item']!r} is malformed")
    if not isinstance(row["text"], str) or not row["text"].strip():
        raise LessonError("text must be a non-empty string")
    if not isinstance(row["reason"], str) or not row["reason"].strip():
        raise LessonError("reason must be a non-empty string")
    if len(row["reason"]) > MAX_REASON:
        raise LessonError(f"reason is {len(row['reason'])} characters; limit is {MAX_REASON}")
    rb = row.get("replaced_by")
    if rb is not None and (not isinstance(rb, str) or not QID_RE.match(rb)):
        raise LessonError(f"replaced_by must be null or a qid; got {rb!r}")


def load(state: Path) -> list[dict]:
    """Read STATE/lessons.jsonl. Returns the full list of valid rows, oldest first.

    An absent file returns []. A malformed line is skipped with a stderr note; one bad row
    never faults a page load.
    """
    sfd = os.open(state, STATE_FLAGS)
    try:
        raw = AF.read_at(sfd, FILE, MAX_FILE)
    finally:
        os.close(sfd)
    if raw is None:
        return []
    rows: list[dict] = []
    dropped = 0
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            dropped += 1
            continue
        if not isinstance(obj, dict):
            dropped += 1
            continue
        try:
            _check(obj)
        except LessonError:
            dropped += 1
            continue
        rows.append(obj)
    if dropped:
        sys.stderr.write(f"console lessons: {dropped} malformed row(s) ignored (not deleted)\n")
    return rows


def record(state: Path, qid: str, item: str, kind: str, text: str, reason: str,
           now_iso: str, replaced_by: str | None = None) -> dict:
    """Append a lesson row to STATE/lessons.jsonl. Returns the stored row.

    The caller holds Console._lock (so this never races a parallel refactor on the same qid).
    Reason is required and uncapped above MAX_REASON — a truncated owner reason loses the
    signal, so we refuse rather than silently cut it.
    """
    row = {
        "ts": now_iso,
        "qid": qid,
        "item": item,
        "kind": kind,
        "text": _trim(text or "", MAX_TEXT),
        "reason": reason,
        "replaced_by": replaced_by,
    }
    _check(row)
    existing = load(state)
    existing.append(row)
    # FIFO prune when past MAX_LESSONS so disk doesn't drift unbounded on a long-running project.
    if len(existing) > MAX_LESSONS:
        existing = existing[-MAX_LESSONS:]
    data = ("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in existing)
            + "\n").encode("utf-8")
    if len(data) > MAX_FILE:
        raise LessonError(f"lessons file would be {len(data)} bytes; limit is {MAX_FILE}")
    sfd = os.open(state, STATE_FLAGS)
    try:
        AF.write_at(sfd, FILE, data)
    finally:
        os.close(sfd)
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
        for line in row["reason"].splitlines() or [""]:
            out.append(line)
        out.append("")
        if row.get("replaced_by"):
            out.append(f"**Replaced by:** `{row['replaced_by']}`")
            out.append("")
    return "\n".join(out)
