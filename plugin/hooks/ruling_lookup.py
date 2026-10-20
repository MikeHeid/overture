"""PreToolUse on Edit|Write|MultiEdit|NotebookEdit: the owner's rulings on a file, before an agent edits it (1.52.0).

Owner, OPEN-DECISIONS "Ruling lookup before an agent edits": R1 "Live, with
fallback", R2 "Inform + warn", R3 "Hook + command + MCP", R4 "Both, labelled".
Before an edit the agent reads, in its context, the rulings that hold on the
file and those that only cite it; if the edit would break one, a warning names
it. **It never decides.** The output carries `additionalContext` alone, never
a `permissionDecision`: "allow" would skip the owner's own permission prompt,
and "deny" is not what the owner chose (R2). The edit always goes through the
normal permission flow.

**Which project.** The file's checkout is the nearest folder above it holding
`.git`. The console is the one the user's registry names for EXACTLY that
checkout, or for the main checkout it is a linked worktree of: its `.git` file
says "gitdir: MAIN/.git/worktrees/NAME" and git's back link
(`MAIN/.git/worktrees/NAME/gitdir`) names it again (no git is run). A file in
any other repository (a sibling clone, a repo nested in the registered one, a
folder whose `.git` file merely claims a project) gets nothing, whatever the
session's directory: only the registered checkout's rulings are ever said, and
only its paths are sent to its server (AS1, S1).

**Where the rulings come from.** The console server, over its agent socket
(`POST /rulings`, the one server's `/p/<project>/rulings` with its token), with
one 1.5 s deadline for the whole exchange. When the socket is absent, times
out, answers 401, 403 or 5xx, or runs a kit with no lookup, the rulings
committed in the checkout answer instead (`.overture.json` `fold.locked`), and
the note says so; a bad committed file is skipped and named, at most 500 are
read. Only a 400 naming its error (the server refusing this request) silences it.

**Noise.** A file's rulings are said once per session (STATE_HOME/overture/
rulings-shown.json, keyed by session, path and the set of rulings), and again
when that set changes; a would-break warning is said every time. Nothing is
printed for a file with no rulings.

**It fails OPEN and silent**: input it cannot read, an unreadable registry,
any error at all prints nothing and exits 0.

Unlike the other hooks it imports kit code: `overture.lookup` from the kit
inside THIS plugin's own folder (`../kit`), never the kit the registry names
and never anything from the project. It reads project files only as data.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True  # never leave a __pycache__ in the installed plugin
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "kit"))   # this plugin's own kit, never the registry's or the project's
import session_start as SS  # noqa: E402  (this plugin's own hook module)
try:
    from overture import anchors as A  # noqa: E402
    from overture import lookup as L  # noqa: E402
except Exception:  # noqa: BLE001 - native Windows Python (1.53.1): the kit's reads need POSIX open flags, and
    A = L = None   # no project registers there (its paths are POSIX); `note` then fails open in main, silent

TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
MAX_INPUT = 4 << 20                # a Write's content rides in the input
SHOWN_FILE = "rulings-shown.json"
MAX_SHOWN = 256 << 10
KEEP_SHOWN = 500                   # (session, path) pairs remembered, newest first...
KEEP_SECONDS = 7 * 86400           # ...for at most a week


def _shown_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "overture" / SHOWN_FILE


def _load_shown(p: Path) -> dict:
    try:
        raw = SS._read_regular(p, MAX_SHOWN, nofollow=True)
        doc = json.loads(raw.decode("utf-8")) if raw is not None else {}
    except (OSError, SS.Unsafe, UnicodeDecodeError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def seen_before(sid: str | None, path: str, digest: str) -> bool:
    """Whether this session was shown this file's rulings, as they are now; records it when not. Never raises.

    C6: the read-modify-write is not locked. Two edits racing in one session
    can each miss the other's record, so a list may be shown twice; that is
    the worst case (never a list withheld), and accepted for no lock file.
    """
    if sid is None:
        return False
    p, key, now = _shown_path(), f"{sid}\0{path}", time.time()
    try:
        shown = _load_shown(p)
        old = shown.get(key)
        if isinstance(old, dict) and old.get("h") == digest:
            return True
        shown[key] = {"h": digest, "t": now}
        keep = sorted(((k, v) for k, v in shown.items() if isinstance(v, dict) and isinstance(v.get("t"), (int, float))
                       and now - v["t"] < KEEP_SECONDS), key=lambda kv: -kv[1]["t"])[:KEEP_SHOWN]
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".rulings-shown.")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(dict(keep), fh)
        os.replace(tmp, p)
    except Exception:  # noqa: BLE001 - a state file it cannot write means the note is said again, never lost
        return False
    return False


def _digest(hits: list[dict]) -> str:
    rows = [[h.get("qid"), h.get("label"), h.get("stale"), h.get("locked_at"), h.get("answer")] for h in hits]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def _current(f: Path) -> str | None:
    """The file's text as it is now, or None: absent, not a plain file, past MAX_READ, or not UTF-8."""
    try:
        if f.is_symlink() or not f.is_file() or f.stat().st_size > A.MAX_READ:
            return None
        return f.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _entry_for(root: Path) -> dict | None:
    """The registry entry for exactly this checkout, or for the main checkout it is a verified worktree of; else None."""
    found = SS.projects()
    for start in (Path(os.path.realpath(root)), L.main_checkout(root)):
        e = found.get(str(start)) if start is not None else None
        if e is not None:
            return SS.checked(e)
    return None


def more_command(e: dict, rel: str) -> str:
    """The command that lists every ruling on `rel`, each part shell-quoted (AS2: an agent may run it as it stands)."""
    return shlex.join(["python3", str(Path(e["kit"]) / "agent.py"), "--state", e["state"], "rulings", "--path", rel])


def note(payload: object) -> str | None:
    """The context for this edit, or None. Raises on anything unreadable (main says nothing then)."""
    if not isinstance(payload, dict) or payload.get("tool_name") not in TOOLS:
        return None
    tool, ti = payload["tool_name"], payload.get("tool_input")
    raw = ti.get("notebook_path" if tool == "NotebookEdit" else "file_path") if isinstance(ti, dict) else None
    if not isinstance(raw, str) or not raw.startswith("/"):
        return None
    f = Path(os.path.realpath(raw))
    root = L.project_root(f.parent)
    if root is None:
        return None
    e = _entry_for(root)
    if e is None:
        return None
    rel = L.clean_path(f.relative_to(root).as_posix())
    res = L.lookup(Path(e["state"]), root, [rel])
    hits = res["rulings"].get(rel) or []
    if not hits:
        return None
    breaks = []   # C5: only with the current text read is anything a would-break
    current = None if tool == "NotebookEdit" else _current(f)
    after = None if current is None else L.post_edit(tool, ti, current)
    if after is not None and len(after.encode("utf-8")) <= A.MAX_READ:
        breaks = [(h, L.would_break(h.get("conditions") or [], rel, after, current))
                  for h in hits if h.get("label") == L.HOLDS]
    more = more_command(e, rel)
    info = not seen_before(SS.session_id(payload), rel, _digest(hits))
    return L.say(rel, hits, breaks, res.get("note"), more, info=info)


def main() -> int:
    try:
        raw = sys.stdin.read(MAX_INPUT + 1)
        text = note(json.loads(raw)) if raw.strip() and len(raw) <= MAX_INPUT else None
    except Exception:  # noqa: BLE001 - fail open: a lookup never costs the owner an edit or a session
        return 0
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
