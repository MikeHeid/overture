"""Which of the owner's rulings bear on a file, and whether an edit would break one (1.52.0).

Owner, OPEN-DECISIONS "Ruling lookup before an agent edits", R1-R4: before an
agent edits a file it is shown the rulings on that file, from the running
console server, or from the committed rulings (`.overture.json` `fold.locked`)
when the server does not answer; and if the edit would break one, it is warned
by name. It is never blocked: this informs, it does not decide.

Two labels (R4):

- **holds on this file**: a condition that DECIDES the ruling is on the path.
  The deciding conditions are the export's (`fold.export` writes them, in the
  order `anchors.lock_conditions` keeps: a confirmed proposal, the latest
  `anchor` record, the lock's own anchors, the question's `valid_if`).
- **cites this file**: the question's `source` or an evidence row's `cite`
  points at it, but no deciding condition does. Such a ruling is context; no
  edit of this file can break it.

Every delivery (the PreToolUse hook, `agent.py rulings`, the MCP `rulings`
tool, the server's agent-socket POST /rulings) builds one entry shape here,
from export-shaped entries: the server exports its store as it serves it, the
fallback reads the committed files. A ruling that was withdrawn, kept
unchecked or superseded is no ruling and is never listed; a stale one is
listed with `stale: true`, because its evidence moved.

Safe to import from a hook: the standard library and the kit's own pure
modules (`anchors`, `schema`) only; the store, the server and the export
reader are imported where they are used, never at import time. Nothing here
runs git or any project code.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
from pathlib import Path
from typing import Callable, Iterable

from . import anchors as A
from . import schema as S

TIMEOUT = 1.5            # seconds the socket may take before the committed rulings answer instead (L7)
MAX_PATHS = 50           # paths one lookup may name
MAX_PATH = 512           # characters of one path
MAX_RESPONSE = 4 << 20   # bytes of a server answer read, at most
QUESTION_CHARS = 160     # a ruling's question, shortened to this in an entry
ANSWER_CHARS = 160       # and its answer
HOLDS, CITES = "holds", "cites"
LABELS = {HOLDS: "holds on this file", CITES: "cites this file"}
SERVER_SOCKET = "server.sock"   # the one server's agent socket beside server.json (multiserver.SOCKET)
FALLBACK_NOTE = "(from the committed rulings; the console server is not answering)"
SAY_RULINGS = 5          # rulings the hook names for one file (L6)...
SAY_LINE = 300           # ...each line at most this long...
SAY_TOTAL = 2000         # ...and the whole note at most this long


class PathRefused(ValueError):
    """A path a lookup will not take, named: absolute, leaving the project, or a secrets file."""


class Unreachable(Exception):
    """The console server did not answer the lookup (no socket, refused, timed out, or an older kit)."""


class Refused(Exception):
    """The console server answered the lookup, and refused it (its words)."""


# -- paths ------------------------------------------------------------------------------

def _parts(path: str) -> list[str]:
    return [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]


def clean_path(raw: object) -> str:
    """`raw` as a normalised project-relative path; a trailing "/" stays and means "everything under it".

    Refused by name (PathRefused): not a string, empty, too long, a control
    character, absolute, a `..` part, or a secrets file (`schema.secret_path`).
    """
    if not isinstance(raw, str) or not raw.strip():
        raise PathRefused("a path is a non-empty string")
    if len(raw) > MAX_PATH or any(ord(ch) < 32 for ch in raw):
        raise PathRefused(f"path {raw[:60]!r}: over {MAX_PATH} characters, or a control character")
    if raw.startswith(("/", "\\")) or (len(raw) > 1 and raw[1] == ":"):
        raise PathRefused(f"path {raw!r}: absolute; give it relative to the project root")
    parts = _parts(raw)
    if ".." in parts:
        raise PathRefused(f"path {raw!r}: leaves the project (a .. part)")
    if not parts:
        raise PathRefused(f"path {raw!r}: names no file or folder")
    why = S.secret_path("/".join(parts))
    if why:
        raise PathRefused(f"path {raw!r}: {why}, which is never read")
    return "/".join(parts) + ("/" if raw.replace("\\", "/").endswith("/") else "")


def covers(query: str, path: object) -> bool:
    """Whether the cleaned `query` names `path`: the same file, or (a trailing "/") anything under the folder."""
    if not isinstance(path, str):
        return False
    rel = "/".join(_parts(path))
    return rel.startswith(query) if query.endswith("/") else rel == query


# -- one ruling, from its exported entry ------------------------------------------------------

def conditions(e: dict) -> tuple[list[dict], str]:
    """What decides an exported lock: its anchors when it carries them (export wrote the deciding ones), else valid_if."""
    lk = e["locked"]
    return (lk["anchors"], lk["anchored_by"]) if "anchors" in lk else (e["valid_if"], "question")


def _source_path(source: object) -> str | None:
    if not isinstance(source, str) or not source:
        return None
    m = A.SOURCE_RANGE.match(source)
    return m.group("path") if m else source


def cited_paths(e: dict) -> list[str]:
    """The paths a ruling points at without being decided by them: its `source`, its evidence rows' `cite`."""
    out = [_source_path(e.get("source"))]
    for row in e.get("evidence") or []:
        parts = S.cite_parts(row.get("cite")) if isinstance(row, dict) else None
        out.append(parts[0] if parts else None)
    return [p for p in out if p]


def _short(text: object, n: int) -> str:
    s = A.normalise(text) if isinstance(text, str) else ""
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def answer_words(lk: dict) -> str:
    """The owner's answer in a few words: the picked labels, then the owner's own text."""
    said = [*(lk.get("picked_labels") or []), *([lk["own_text"]] if lk.get("own_text") else [])]
    return _short("; ".join(str(s) for s in said), ANSWER_CHARS) or "(no words)"


def entry(e: dict, label: str, conds: list[dict], stale: bool) -> dict:
    """The one entry shape every delivery uses. A short name for who locked it, never an email."""
    lk = e["locked"]
    out = {"qid": e["qid"], "item": e["item"], "question": _short(e.get("question"), QUESTION_CHARS),
           "answer": answer_words(lk), "locked_at": lk.get("locked_at"), "label": label,
           "conditions": conds, "stale": stale}
    if isinstance(lk.get("locked_by_name"), str):
        out["locked_by_name"] = lk["locked_by_name"]
    return out


def holds_fn(tree: A.Tree, statuses_known: bool) -> Callable[[dict], bool | None]:
    """`holds(condition)` over `tree`; None for an item status when the register is not known here."""
    def holds(c: dict) -> bool | None:
        if c.get("kind") == "item_status" and not statuses_known:
            return None
        return tree.holds(c)
    return holds


def match(entries: Iterable[dict], path: str, holds: Callable[[dict], bool | None] | None = None) -> list[dict]:
    """The rulings on cleaned `path`: those that hold on it first, then those that only cite it.

    A ruling with an `outcome` (withdrawn, kept unchecked, superseded) is left
    out. `holds` decides `stale` (any deciding condition that fails); without
    it nothing is called stale.
    """
    found = []
    for e in entries:
        if "outcome" in e:
            continue
        conds, _origin = conditions(e)
        on = [c for c in conds if covers(path, c.get("path"))]
        if on:
            label = HOLDS
        elif any(covers(path, p) for p in cited_paths(e)):
            label = CITES
        else:
            continue
        stale = holds is not None and any(holds(c) is False for c in conds)
        found.append(entry(e, label, on, stale))
    return sorted(found, key=lambda h: (h["label"] != HOLDS, h["qid"]))


# -- what an edit would break ------------------------------------------------------------

def post_edit(tool: str, tool_input: dict, current: str | None) -> str | None:
    """The file's text after the edit, or None when it cannot be worked out (then nothing is checked).

    Write: its content. Edit: `old_string` -> `new_string`, the first time or
    (replace_all) every time. MultiEdit: each edit in order. An `old_string`
    absent from the text (the tool itself will fail), an unread file, and a
    NotebookEdit (cells, not text) all give None.
    """
    if not isinstance(tool_input, dict):
        return None
    if tool == "Write":
        c = tool_input.get("content")
        return c if isinstance(c, str) else None
    if tool == "Edit":
        edits = [tool_input]
    elif tool == "MultiEdit":
        edits = tool_input.get("edits")
        if not isinstance(edits, list):
            return None
    else:
        return None
    if current is None:
        return None
    text = current
    for ed in edits:
        old, new = (ed.get("old_string"), ed.get("new_string")) if isinstance(ed, dict) else (None, None)
        if not isinstance(old, str) or not isinstance(new, str) or not old or old not in text:
            return None
        text = text.replace(old, new) if ed.get("replace_all") is True else text.replace(old, new, 1)
    return text


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def would_break(conds: list[dict], path: str, new_text: str, old_text: str | None = None) -> list[dict]:
    """The conditions on `path` that fail on `new_text`, each with why; with `old_text`, only those that held on it.

    An excerpt breaks when its text (whitespace normalised, as the check reads
    it) is no longer in the file. A whole-file hash breaks on any change at
    all: that is what such a condition means, and the words say so.
    """
    out = []
    new_norm, old_norm = A.normalise(new_text), None if old_text is None else A.normalise(old_text)
    for c in conds:
        if not covers(path, c.get("path")):
            continue
        if c.get("kind") == "excerpt":
            t = A.normalise(c.get("text") or "")
            if t not in new_norm and (old_norm is None or t in old_norm):
                out.append({"condition": c, "words": f"it changes or removes the text the ruling cites "
                                                     f"(\"{_short(c.get('text'), 80)}\")"})
        elif c.get("kind") == "file_sha256":
            if _sha(new_text) != c.get("sha256") and (old_text is None or _sha(old_text) == c.get("sha256")):
                out.append({"condition": c, "words": "the ruling pins this whole file's hash, so any change to "
                                                     "the file breaks it"})
    return out


# -- where the rulings come from ---------------------------------------------------------------

def from_export_dir(d: Path) -> list[dict]:
    """Every committed ruling in `d`, each held to fold's own rules (rulecheck's reader); CheckError if one is not."""
    from . import rulecheck as RC   # here, not at import: it pulls in the fold and the store
    return list(RC.parse(RC.from_dir(Path(d)), None, "").values())


def committed(root: Path, paths: list[str]) -> dict[str, list[dict]]:
    """path -> rulings, from the files `fold.py export` committed in the checkout at `root`."""
    from . import fold as F
    from . import rulecheck as RC
    root = Path(root).resolve()
    d = F.inside(root, RC._locked_default(root, None), "fold.locked")
    entries = from_export_dir(d)
    holds = holds_fn(A.Tree(root, {}), statuses_known=False)
    return {p: match(entries, p, holds) for p in paths}


class _UnixConn(http.client.HTTPConnection):
    def __init__(self, sock_path: Path, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self.sock_path = sock_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self.sock_path))


def fetch(sock: Path, paths: list[str], project: str | None = None, token: str | None = None,
          timeout: float = TIMEOUT) -> dict[str, list[dict]]:
    """path -> rulings from the console server's agent socket; Unreachable when it does not answer in `timeout`.

    A server that answers with a refusal raises Refused with its words.
    """
    route = f"/p/{project}/rulings" if project else "/rulings"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    conn = _UnixConn(Path(sock), timeout)
    try:
        conn.request("POST", route, body=json.dumps({"paths": paths}).encode("utf-8"), headers=headers)
        resp = conn.getresponse()
        raw = resp.read(MAX_RESPONSE + 1)
    except (OSError, http.client.HTTPException) as e:   # absent, refused, timed out, or cut off
        raise Unreachable(f"{type(e).__name__}: {e}") from None
    finally:
        conn.close()
    if resp.status == 404:   # a server on a kit before 1.52.0, which has no lookup
        raise Unreachable("the console server runs a kit with no ruling lookup")
    try:
        out = json.loads(raw) if len(raw) <= MAX_RESPONSE else None
    except ValueError:
        out = None
    if resp.status != 200 or not isinstance(out, dict) or not isinstance(out.get("rulings"), dict):
        why = out.get("error") if isinstance(out, dict) else None
        raise Refused(why or f"the console server answered {resp.status}")
    return out["rulings"]


def door(state: Path) -> tuple[Path, str | None, str | None]:
    """(socket, project, token) for the console at `state`: the one server's when server.json hosts it, else STATE/agent.sock."""
    from . import serverfile as SF
    s = os.path.realpath(state)
    for name, e in SF.load()["projects"].items():
        if isinstance(e, dict) and isinstance(e.get("state"), str) and os.path.realpath(e["state"]) == s:
            return SF.location().parent / SERVER_SOCKET, name, SF.read_token(name)
    return Path(state) / "agent.sock", None, None


def lookup(state: Path | None, root: Path | None, paths: list[str], timeout: float = TIMEOUT,
           where: tuple[Path, str | None, str | None] | None = None) -> dict:
    """{"source": "server"|"committed", "note": str|None, "rulings": {path: [entry]}}: the server, else the checkout.

    The committed rulings answer only when the server does not (Unreachable);
    a refusal from a server that did answer is raised (Refused).
    """
    why = "no console state"
    if state is not None:
        try:
            sock, project, token = where if where is not None else door(state)
            return {"source": "server", "note": None, "rulings": fetch(sock, paths, project, token, timeout)}
        except Unreachable as e:
            why = str(e)
        except Refused:
            raise
        except Exception as e:  # noqa: BLE001 - an unreadable server.json or token file: the server is out of reach
            why = f"{type(e).__name__}: {e}"
    if root is None:
        raise Unreachable(f"the console server did not answer ({why}) and there is no checkout to read")
    return {"source": "committed", "note": FALLBACK_NOTE, "why": why, "rulings": committed(root, paths)}


# -- the checkout a file is in -----------------------------------------------------------------

def project_root(start: Path) -> Path | None:
    """The nearest folder holding `start` (itself or an ancestor) with a `.git` (a folder, or a worktree's file)."""
    p = Path(os.path.realpath(start))
    for d in (p, *p.parents):
        if os.path.lexists(d / ".git"):
            return d
    return None


def main_checkout(root: Path) -> Path | None:
    """For a linked worktree (`.git` is a file: "gitdir: MAIN/.git/worktrees/NAME"), MAIN; else None. No git is run."""
    f = Path(root) / ".git"
    try:
        if f.is_symlink() or not f.is_file() or f.stat().st_size > 4096:
            return None
        line = f.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    gd = Path(line[len("gitdir:"):].strip())
    if not gd.is_absolute():
        gd = Path(root) / gd
    gd = Path(os.path.realpath(gd))
    if gd.parent.name != "worktrees" or gd.parent.parent.name != ".git":
        return None
    return gd.parent.parent.parent


# -- in words ---------------------------------------------------------------------------------

def line_of(h: dict) -> str:
    """One ruling in one line: label, qid, question, answer, when and who, and whether it is stale."""
    who = f" by {h['locked_by_name']}" if h.get("locked_by_name") else ""
    when = (h.get("locked_at") or "")[:10]
    s = (f"- {LABELS.get(h['label'], h['label'])}: {h['qid']} \"{h['question']}\" -> {h['answer']} "
         f"(locked {when}{who})")
    if h.get("stale"):
        s += " STALE: its evidence changed since it was locked, so do not rely on it"
    return s if len(s) <= SAY_LINE else s[:SAY_LINE - 1] + "…"


def say(path: str, hits: list[dict], breaks: list[tuple[dict, list[dict]]], note: str | None, more: str,
        info: bool = True) -> str | None:
    """The hook's note for one file, or None when it has nothing to say.

    `info` False leaves out the list (already shown this session); a warning
    that the edit would break a ruling is always said.
    """
    out = []
    warn = [(h, b) for h, b in breaks if b]
    if info and hits:
        out.append(f"Owner rulings on {path}{' ' + note if note else ''}. Follow them; to go against one, ask "
                   f"the owner first (console-ask):")
        shown = [line_of(h) for h in hits[:SAY_RULINGS]]
        rest = len(hits) - len(shown)
        while shown and len("\n".join(out + shown)) > SAY_TOTAL - 200:
            shown.pop()
            rest += 1
        out += shown
        if rest:
            out.append(f"- and {rest} more: `{more}`")
    for h, b in warn:
        out.append(f"WARNING: this edit would break the owner's ruling {h['qid']} (\"{_short(h['question'], 80)}\"): "
                   f"{'; '.join(x['words'] for x in b)}. The edit is not blocked. If the change is right, tell the "
                   f"owner and ask for a re-lock; otherwise keep what the ruling rests on.")
    if not out:
        return None
    text = "\n".join(out)
    return text if len(text) <= SAY_TOTAL else text[:SAY_TOTAL - 1] + "…"
