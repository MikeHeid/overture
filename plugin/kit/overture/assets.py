"""Assets (1.32, FEED-ASSETS.md): screenshots and recordings an agent posts on an item.

A visual answers an owner's request; an asset is the agent showing its work unasked: a
before and an after of a UI change, a screenshot of a failure, a short recording. The
owner sees them in the Feed and on the item.

Storage, under STATE only (never the project), outside the append-only store so an
older kit is never refused by them and the oldest can be pruned (F1):

    STATE/assets/index.json          {"assets": {id: row}, "pruned": [note, ...]}
    STATE/assets/<sha256>.<ext>      the bytes, once per content however many rows name them

Every file is read and written through a held folder descriptor (atfile), so a symlink
planted in its place is refused. The format is decided from the file's MAGIC BYTES, never
its name: PNG, JPEG, WebP or GIF. SVG is never accepted: it can carry script. Width and
height are read from the header with the standard library and bounded.

Limits (FEED-ASSETS.md):
- a still image is at most 2 MiB, a GIF at most 8 MiB, each side at most 8000 px;
- an agent posts at most RATE_COUNT assets in RATE_WINDOW seconds;
- an item holds at most PER_ITEM assets, the project at most MAX_TOTAL bytes. Past either,
  the oldest assets that are neither starred nor linked to a PR are pruned (F1, architect
  default) and a note says so in the Feed; when nothing can be pruned the post is refused.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import struct
from datetime import datetime, timezone
from pathlib import Path

from . import atfile as AF

DIR = "assets"
INDEX = "index.json"
MAX_STILL = 2 << 20
MAX_GIF = 8 << 20
MAX_SIDE = 8000
MAX_CAPTION = 200
MAX_INDEX = 4 << 20
PER_ITEM = 100
MAX_TOTAL = 300 << 20
RATE_COUNT = 30
RATE_WINDOW = 600
RATE_PROJECT = 120          # every agent together, per RATE_WINDOW: the agent name is self-declared
MAX_ROWS = 3000             # rows in the index, whatever their bytes: tiny files must not fill it for good
VIEW_PER_ITEM = 24          # newest per item sent with every page view; the item's `counts` say how many in all
JPEG_SCAN = 256 << 10       # a JPEG's frame header is near its start; never scan a whole crafted file
MAX_PRUNED_NOTES = 50
KINDS = ("before", "after", "screenshot", "recording")
MIME = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
EXT = {"png": ".png", "jpeg": ".jpg", "webp": ".webp", "gif": ".gif"}
ID_RE = re.compile(r"^a[0-9a-f]{16}\Z")
SHA_RE = re.compile(r"^[0-9a-f]{64}\Z")
TICKET_RE = re.compile(r"^T-[A-Za-z0-9_-]{4,20}\Z")
STATE_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC


class AssetError(ValueError):
    """A refusal the poster sees, by name; carries no project secret."""


# ---- format sniffing (stdlib only) ------------------------------------------------------------

def sniff(data: bytes) -> tuple[str, int, int]:
    """(format, width, height) from the bytes' own header, or AssetError naming why not."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24 and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        w, h = struct.unpack("<HH", data[6:10])
        return "gif", w, h
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8X":
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return "webp", w, h
        if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            w, h = struct.unpack("<HH", data[26:30])
            return "webp", w & 0x3FFF, h & 0x3FFF
        if chunk == b"VP8L" and data[20:21] == b"\x2f":
            b = int.from_bytes(data[21:25], "little")
            return "webp", (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
        raise AssetError("a WebP file whose header could not be read")
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        end = min(len(data), JPEG_SCAN)
        while i + 9 < end:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                i += 1 if marker == 0xFF else 2
                continue
            seg = int.from_bytes(data[i + 2:i + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "jpeg", w, h
            if seg < 2:
                break
            i += 2 + seg
        raise AssetError("a JPEG file with no frame header")
    if data.lstrip()[:5].lower() in (b"<?xml", b"<svg ", b"<svg>") or b"<svg" in data[:512].lower():
        raise AssetError("SVG is not accepted as an asset: it can carry script. Post a PNG of it instead")
    raise AssetError("not a PNG, JPEG, WebP or GIF file (judged by its first bytes, not its name)")


# ---- the index --------------------------------------------------------------------------------

def _open_dir(state: Path, create: bool) -> int | None:
    sfd = os.open(state, STATE_FLAGS)
    try:
        try:
            return os.open(DIR, STATE_FLAGS | os.O_NOFOLLOW, dir_fd=sfd)
        except FileNotFoundError:
            if not create:
                return None
            os.mkdir(DIR, 0o700, dir_fd=sfd)
            return os.open(DIR, STATE_FLAGS | os.O_NOFOLLOW, dir_fd=sfd)
    finally:
        os.close(sfd)


def load(state: Path) -> dict:
    """`{"assets": {id: row}, "pruned": [...]}`; empty when nothing was ever posted."""
    dfd = _open_dir(state, create=False)
    if dfd is None:
        return {"assets": {}, "pruned": []}
    try:
        raw = AF.read_at(dfd, INDEX, MAX_INDEX)
    finally:
        os.close(dfd)
    if raw is None:
        return {"assets": {}, "pruned": []}
    if len(raw) > MAX_INDEX:
        raise AssetError(f"{DIR}/{INDEX} is over {MAX_INDEX} bytes")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise AssetError(f"{DIR}/{INDEX} is not JSON: {e}") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("assets"), dict):
        raise AssetError(f"{DIR}/{INDEX} must be an object with an 'assets' map")
    assets = {k: v for k, v in doc["assets"].items() if ID_RE.match(str(k)) and _row_ok(v)}
    pruned = [n for n in doc.get("pruned", []) if isinstance(n, dict)][-MAX_PRUNED_NOTES:]
    return {"assets": assets, "pruned": pruned}


def _row_ok(r: object) -> bool:
    """A row every reader can use; anything else is skipped on load (and so dropped at the next save)."""
    return (isinstance(r, dict) and isinstance(r.get("item"), str) and r.get("format") in MIME
            and isinstance(r.get("sha256"), str) and bool(SHA_RE.match(r["sha256"]))
            and isinstance(r.get("bytes"), int) and isinstance(r.get("at"), str)
            and isinstance(r.get("caption"), str) and r.get("kind") in KINDS and ID_RE.match(str(r.get("id", ""))))


def _save(dfd: int, doc: dict) -> None:
    data = json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_INDEX:
        raise AssetError(f"the asset index would be {len(data)} bytes; the limit is {MAX_INDEX}")
    AF.write_at(dfd, INDEX, data)


def _file_name(row: dict) -> str:
    return row["sha256"] + EXT[row["format"]]


# ---- writes -----------------------------------------------------------------------------------

def _one_line(v: object, field: str, limit: int) -> str:
    if not isinstance(v, str) or not v.strip():
        raise AssetError(f"{field} must be a non-empty string")
    v = v.strip()
    if "\n" in v or "\r" in v:
        raise AssetError(f"{field} must be one line")
    if len(v) > limit:
        raise AssetError(f"{field} is {len(v)} characters; the limit is {limit}")
    return v


def _parse_time(s: object) -> float:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def check(data: bytes) -> tuple[str, int, int]:
    """Format, size and sides, with no file touched: the server runs it BEFORE taking its lock."""
    if len(data) > MAX_GIF:
        raise AssetError(f"the file is {len(data)} bytes; the most an asset can be is {MAX_GIF}")
    fmt, w, h = sniff(data)
    cap = MAX_GIF if fmt == "gif" else MAX_STILL
    if len(data) > cap:
        raise AssetError(f"the {fmt.upper()} is {len(data)} bytes; the limit for it is {cap}")
    if not (1 <= w <= MAX_SIDE and 1 <= h <= MAX_SIDE):
        raise AssetError(f"the image is {w}×{h}; each side must be 1 to {MAX_SIDE} px")
    return fmt, w, h


def add(state: Path, *, item: str, data: bytes, caption: str, kind: str, agent: str | None, now: str,
        starred: set[str] = frozenset(), qid: str | None = None, pr: int | None = None,
        ticket: str | None = None) -> dict:
    """Store one asset; return `{"asset": row, "pruned": [notes]}`. The caller has checked `item`,
    `qid` and `ticket` exist. Refusals raise AssetError, before anything is written."""
    fmt, w, h = check(data)
    caption = _one_line(caption, "caption", MAX_CAPTION)
    if not isinstance(kind, str) or kind not in KINDS:
        raise AssetError(f"kind {kind!r} is not one of {', '.join(KINDS)}")
    if pr is not None and (isinstance(pr, bool) or not isinstance(pr, int) or pr < 1):
        raise AssetError("pr must be a pull request number")
    if ticket is not None and not TICKET_RE.match(str(ticket)):
        raise AssetError(f"ticket {ticket!r} is not a ticket id")
    sha = hashlib.sha256(data).hexdigest()
    t_now = _parse_time(now)

    dfd = _open_dir(state, create=True)
    try:
        doc = load(state)
        rows = doc["assets"]
        # The same bytes posted again on the same item are one asset.
        for row in rows.values():
            if row.get("item") == item and row.get("sha256") == sha:
                return {"asset": row, "pruned": [], "duplicate": True}
        recent = [r for r in rows.values() if t_now - _parse_time(r.get("at")) < RATE_WINDOW]
        mine = [r for r in recent if r.get("agent") == agent]     # an unnamed agent shares one bucket
        who = f"agent {agent}" if agent else "unnamed agents"
        if len(mine) >= RATE_COUNT:
            raise AssetError(f"{who} posted {len(mine)} assets in the last "
                             f"{RATE_WINDOW // 60} minutes; the limit is {RATE_COUNT}")
        if len(recent) >= RATE_PROJECT:
            raise AssetError(f"{len(recent)} assets were posted in the last {RATE_WINDOW // 60} minutes; "
                             f"the project's limit is {RATE_PROJECT}")
        row = {"id": "a" + secrets.token_hex(8), "item": item, "format": fmt, "mime": MIME[fmt],
               "width": w, "height": h, "bytes": len(data), "sha256": sha, "caption": caption,
               "kind": kind, "by": "agent", "agent": agent, "at": now}
        if qid:
            row["qid"] = qid
        if pr is not None:
            row["pr"] = pr
        if ticket:
            row["ticket"] = ticket
        notes = _make_room(rows, row, starred, now)
        new_file = not any(r.get("sha256") == sha for r in rows.values())
        if new_file:
            AF.write_at(dfd, _file_name(row), data)
        rows[row["id"]] = row
        doc["pruned"] = (doc["pruned"] + notes)[-MAX_PRUNED_NOTES:]
        try:
            _save(dfd, doc)
        except BaseException:
            if new_file:   # never leave a file no row names
                try:
                    os.unlink(_file_name(row), dir_fd=dfd)
                except FileNotFoundError:
                    pass
            raise
        _sweep(dfd, rows)
        return {"asset": row, "pruned": notes}
    finally:
        os.close(dfd)


PAIR_WINDOW = 30 * 60   # a "before" this close ahead of an "after" on the same item is shown, and kept, with it


def _protected_ids(rows: dict, starred: set[str]) -> set[str]:
    """Assets F1 never prunes: linked to a PR, starred, or the "before" of a kept "after" (the console stars
    a before/after pair by its "after")."""
    keep = {r["id"] for r in rows.values() if "pr" in r or ("asset:" + r["id"]) in starred}
    for a in [r for r in rows.values() if r["id"] in keep and r.get("kind") == "after"]:
        t = _parse_time(a.get("at"))
        # The one "before" the console shows beside it: the newest within the window.
        befores = [b for b in rows.values() if b.get("kind") == "before" and b.get("item") == a.get("item")
                   and 0 <= t - _parse_time(b.get("at")) <= PAIR_WINDOW]
        if befores:
            keep.add(max(befores, key=lambda b: b.get("at", ""))["id"])
    return keep


def _make_room(rows: dict, new: dict, starred: set[str], now: str) -> list[dict]:
    """F1: prune the oldest unprotected assets until the item and the project fit. Mutates `rows`."""
    notes: list[dict] = []

    def unique_bytes(rs) -> int:
        return sum({r["sha256"]: r["bytes"] for r in rs}.values())

    def prune_one(pool: list[dict], why: str) -> None:
        keep = _protected_ids(rows, starred)
        candidates = sorted((r for r in pool if r["id"] not in keep), key=lambda r: r.get("at", ""))
        if not candidates:
            raise AssetError(f"{why}, and every asset there is starred or linked to a PR. "
                             "Unstar some, or have the owner delete some")
        victim = candidates[0]
        del rows[victim["id"]]
        notes.append({"id": victim["id"], "item": victim["item"], "caption": victim["caption"],
                      "at": now, "why": why})

    while sum(1 for r in rows.values() if r["item"] == new["item"]) >= PER_ITEM:
        prune_one([r for r in rows.values() if r["item"] == new["item"]],
                  f"item {new['item']} holds {PER_ITEM} assets")
    while len(rows) + 1 > MAX_ROWS:
        prune_one(list(rows.values()), f"the project holds {MAX_ROWS} assets")
    while unique_bytes(list(rows.values()) + [new]) > MAX_TOTAL:
        prune_one(list(rows.values()), f"assets fill the project's {MAX_TOTAL >> 20} MiB")
    return notes


def _sweep(dfd: int, rows: dict) -> None:
    """Remove stored files no row names any more."""
    keep = {_file_name(r) for r in rows.values()}
    for name in os.listdir(dfd):
        if name == INDEX or name in keep:
            continue
        stem, _, ext = name.partition(".")
        if SHA_RE.match(stem) and ("." + ext) in EXT.values():
            try:
                os.unlink(name, dir_fd=dfd)
            except FileNotFoundError:
                pass


def delete(state: Path, asset_id: str) -> dict:
    """The owner removes one asset. Its file goes when no other row names the same bytes."""
    if not isinstance(asset_id, str) or not ID_RE.match(asset_id):
        raise AssetError("id must be an asset id")
    dfd = _open_dir(state, create=False)
    if dfd is None:
        raise AssetError(f"no asset {asset_id}")
    try:
        doc = load(state)
        row = doc["assets"].pop(asset_id, None)
        if row is None:
            raise AssetError(f"no asset {asset_id}")
        _save(dfd, doc)
        _sweep(dfd, doc["assets"])
        return row
    finally:
        os.close(dfd)


# ---- reads ------------------------------------------------------------------------------------

def read(state: Path, asset_id: str) -> tuple[bytes, str]:
    """(bytes, mime) of one asset, re-checked against its recorded hash and format."""
    if not isinstance(asset_id, str) or not ID_RE.match(asset_id):
        raise AssetError("id must be an asset id")
    row = load(state)["assets"].get(asset_id)
    if row is None:
        raise AssetError(f"no asset {asset_id}")
    dfd = _open_dir(state, create=False)
    if dfd is None:
        raise AssetError(f"no asset {asset_id}")
    try:
        data = AF.read_at(dfd, _file_name(row), MAX_GIF)
    finally:
        os.close(dfd)
    if data is None or hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise AssetError(f"asset {asset_id}'s file is missing or was changed on disk; it is not shown")
    fmt, _, _ = sniff(data)
    if fmt != row["format"]:
        raise AssetError(f"asset {asset_id}'s file is not the {row['format']} it was stored as")
    return data, MIME[fmt]


VIEW_FIELDS = ("id", "item", "format", "width", "height", "bytes", "caption", "kind", "agent", "at",
               "qid", "pr", "ticket")


def as_view(doc: dict) -> dict:
    """What the owner's page needs: rows by item (newest first), the newest overall, and the prune notes."""
    rows = sorted((r for r in doc.get("assets", {}).values()
                   if isinstance(r.get("item"), str) and r.get("format") in MIME and SHA_RE.match(str(r.get("sha256")))),
                  key=lambda r: r.get("at", ""), reverse=True)
    slim = [{k: r[k] for k in VIEW_FIELDS if k in r} for r in rows]
    by_item: dict[str, list[dict]] = {}
    counts: dict[str, int] = {}
    for r in slim:
        counts[r["item"]] = counts.get(r["item"], 0) + 1
        if counts[r["item"]] <= VIEW_PER_ITEM:
            by_item.setdefault(r["item"], []).append(r)
    total = sum({r["sha256"]: r["bytes"] for r in rows}.values())
    return {"by_item": by_item, "counts": counts, "recent": slim[:60], "count": len(slim), "bytes": total,
            "limit_bytes": MAX_TOTAL, "pruned": list(reversed(doc.get("pruned", [])))}


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
