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

1.54 (owner K1-K3): a `symbol` condition decides a ruling like any other on
its path. `would_break` warns when the edit changes that definition's body or
removes it, and says nothing for an edit elsewhere in the file (K2); `follows`
names a definition the edit renames with its body unchanged (K3), which the
ruling follows, so the agent can propose the new name for the owner to
confirm. A ruling on a definition the kit cannot read is unchecked, never
stale.

Safe to import from a hook: the standard library and the kit's own pure
modules (`anchors`, `schema`, `symbols`) only; the store, the server and the export
reader are imported where they are used, never at import time. Nothing here
runs git or any project code.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import time
import unicodedata
from pathlib import Path
from typing import Callable, Iterable

from . import anchors as A
from . import schema as S
from . import symbols as SY

TIMEOUT = 1.5            # seconds the WHOLE socket exchange may take before the committed rulings answer (L7, C7)
MAX_PATHS = 50           # paths one lookup may name
MAX_PATH = 512           # characters of one path
MAX_RESPONSE = 4 << 20   # bytes of a server answer read, at most
QUESTION_CHARS = 160     # a ruling's question, shortened to this in an entry
ANSWER_CHARS = 160       # and its answer
HOLDS, CITES = "holds", "cites"
LABELS = {HOLDS: "holds on this file (this edit can break it)",   # U3: the words say what each label means;
          CITES: "cites this file (its condition is elsewhere; context)"}   # --json keeps the bare "holds"/"cites"
SERVER_SOCKET = "server.sock"   # the one server's agent socket beside server.json (multiserver.SOCKET)
FALLBACK_NOTE = "(from the committed rulings; the console server is not answering)"
SAY_RULINGS = 5          # rulings the hook names for one file (L6)...
SAY_LINE = 300           # ...each line at most this long...
SAY_TOTAL = 2000         # ...and the whole note at most this long, the warnings first (C4)
MAX_RULING_FILES = 500   # committed ruling files the fallback reads, at most (S2: a hostile checkout's 10^5 files)...
MAX_RULING_BYTES = 16 << 20   # ...and bytes in all; past either it says "(first N ruling files)"...
MAX_RULING_ENTRIES = 1000     # ...and *.json entries examined in all, the bad ones too (1.52 S2: 10^5 symlinks)...
MAX_LISTED = 10_000           # ...of at most this many folder entries listed; the rest are counted, never read


class PathRefused(ValueError):
    """A path a lookup will not take, named: absolute, leaving the project, or a secrets file."""


class Unreachable(Exception):
    """The console server did not answer the lookup: no socket, timed out, an older kit, or (C1) a 401, 403 or 5xx."""


class Refused(Exception):
    """The console server answered the lookup with a 400 naming its error: it refused THIS request (its words)."""


# -- paths ------------------------------------------------------------------------------

def _parts(path: str) -> list[str]:
    return [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]


_JOINERS = ("‌", "‍")   # ZWNJ, ZWJ: in Persian and Indic names and emoji sequences; neither breaks a line


def _unsafe(ch: str) -> bool:
    """A character that never reaches the agent's context as itself: any Unicode "other" (control, format such as
    a bidi override, surrogate, private use, unassigned) or a line or paragraph separator; the two joiners pass."""
    cat = unicodedata.category(ch)
    return ch not in _JOINERS and (cat[0] == "C" or cat in ("Zl", "Zp"))


def clean_path(raw: object) -> str:
    """`raw` as a normalised project-relative path; a trailing "/" stays and means "everything under it".

    Refused by name (PathRefused): not a string, empty, too long, a control
    character, absolute, a `..` part, or a secrets file (`schema.secret_path`).
    """
    if not isinstance(raw, str) or not raw.strip():
        raise PathRefused("a path is a non-empty string")
    if len(raw) > MAX_PATH or any(_unsafe(ch) for ch in raw):
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
    """`text` on one line, at most `n` long; a `"` becomes `'`, so it cannot close the quotes it is shown in (S3).

    1.52 C2: and no control character survives: a line break is a space (as
    `normalise` makes every whitespace run), any other (an ESC, a NUL) a `?`,
    so a hostile file NAME cannot start a line of its own in an agent's context.
    Nor can a bidi override reverse what follows it: every `_unsafe`
    character is a `?`.
    """
    s = A.normalise(text).replace('"', "'") if isinstance(text, str) else ""
    s = s if len(s) <= n else s[:n - 1].rstrip() + "…"
    return "".join("?" if _unsafe(ch) else ch for ch in s)


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
    """`holds(condition)` over `tree`; None for an item status when the register is not known here.

    1.54: a symbol followed to its body in the same file holds (K3), and one
    the kit cannot resolve is None (K1), as `anchors.Tree.check` reads them.
    """
    def holds(c: dict) -> bool | None:
        if c.get("kind") == "item_status" and not statuses_known:
            return None
        return tree.check(c)
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


def would_break(conds: list[dict], path: str, new_text: str, old_text: str | None) -> list[dict]:
    """The conditions on `path` that hold on `old_text` (the file now) and fail on `new_text`, each with why.

    C5: only a condition that holds NOW and fails after is one this edit
    breaks; with `old_text` None (absent, unreadable) nothing is checked. An
    excerpt breaks when its text (whitespace normalised, as the check reads
    it) is no longer in the file. A whole-file hash breaks on any change at
    all: that is what such a condition means, and the words say so.
    """
    if old_text is None:
        return []
    out = []
    new_norm, old_norm = A.normalise(new_text), A.normalise(old_text)
    for c in conds:
        if not covers(path, c.get("path")):
            continue
        if c.get("kind") == "excerpt":
            t = A.normalise(c.get("text") or "")
            if t in old_norm and t not in new_norm:
                out.append({"condition": c, "words": f"it changes or removes the text the ruling rests on "
                                                     f"(\"{_short(c.get('text'), 80)}\")"})
        elif c.get("kind") == "file_sha256":
            if _sha(old_text) == c.get("sha256") and _sha(new_text) != c.get("sha256"):
                out.append({"condition": c, "words": "it changes the file the ruling pins"})
        elif c.get("kind") == "symbol":
            why = _symbol_change(c, path, new_text, old_text)
            if why and why[0] == "break":
                out.append({"condition": c, "words": why[1]})
    return out


def follows(conds: list[dict], path: str, new_text: str, old_text: str | None) -> list[dict]:
    """1.54 (K3): the `symbol` conditions on `path` this edit renames, its body unchanged: {condition, to}.

    The ruling follows such a definition, so it is no warning; the note names
    the new name, so the agent can propose it for the owner to confirm.
    """
    if old_text is None:
        return []
    out = []
    for c in conds:
        if covers(path, c.get("path")) and c.get("kind") == "symbol":
            why = _symbol_change(c, path, new_text, old_text)
            if why and why[0] == "moved":
                out.append({"condition": c, "to": why[1]})
    return out


def symbol_name(q: object) -> str:
    """A definition's name as a note may show it: the schema's dotted shape, else `?` (it enters a context)."""
    return q if isinstance(q, str) and not SY.qualname_problem(q) else "?"


def _symbol_change(c: dict, path: str, new_text: str, old_text: str) -> tuple[str, str] | None:
    """('break', why) or ('moved', new name) for a symbol condition that holds on `old_text`; None for neither.

    C5: only a definition that holds now (that name, that body) can be broken
    by this edit. A definition the kit cannot read after the edit is left
    unsaid: the lookup informs, and never guesses.
    """
    q, sha = c.get("symbol"), c.get("sha256")
    if not isinstance(q, str) or not isinstance(sha, str):
        return None
    before = SY.resolve(path, old_text, q)
    if before.state != "found" or before.symbol.body_sha256 != sha:
        return None
    after = SY.resolve(path, new_text, q)
    name = symbol_name(q)
    if after.state == "found":
        return None if after.symbol.body_sha256 == sha else ("break", f"it changes the body of {name}, which the "
                                                                      f"ruling rests on")
    if after.state == "unchecked":   # 1.54 review, round 3: the CI check fails what it read before and cannot now
        return "break", A.plain(f"after it, {name} cannot be read for definitions ({after.reason}), so the CI "
                                f"check fails the ruling it rests on")
    try:
        hits = SY.by_body(path, new_text, sha)
    except SY.Unresolvable:
        return None
    if len(hits) == 1:
        return "moved", hits[0].qualname
    return "break", f"it removes {name}, or renames it and changes its body"


# -- where the rulings come from ---------------------------------------------------------------

def from_export_dir(d: Path, notes: list[str] | None = None, shown: str | None = None) -> list[dict]:
    """The committed rulings in `d`, each held to fold's own rules (rulecheck's parse); a file that is not, skipped.

    C2: one bad file (not a plain file, too big, not JSON, not a valid ruling)
    is skipped and named in `notes` as `shown/NAME`, and the rest are still
    read. S2: at most MAX_RULING_FILES files and MAX_RULING_BYTES bytes, in
    name order; past that `notes` says "(first N ruling files)". Three skipped files are named, the rest counted.
    1.52 S2: a bad file counts too: at most MAX_RULING_ENTRIES are examined, of
    at most MAX_LISTED folder entries listed, and `notes` counts the files not
    read. C2: a skipped file's name is quoted and shown through `_short`, so
    no control character in it reaches an agent's context. Unlike the CI
    check (rulecheck.from_dir, which refuses the lot), this is advice before
    an edit, so a partial answer that says it is partial beats none.
    """
    from . import rulecheck as RC   # here, not at import: it pulls in the fold and the store
    d, notes = Path(d), notes if notes is not None else []
    if not d.is_dir():
        return []
    shown = shown or d.name
    out, skipped, total, read, examined, listed, more = [], [], 0, 0, 0, [], False
    with os.scandir(d) as it:
        for n, de in enumerate(it):
            if n >= MAX_LISTED:
                more = True
                break
            if de.name.endswith(".json"):
                listed.append(de.name)
    names = sorted(listed)
    for name in names:
        if read >= MAX_RULING_FILES or examined >= MAX_RULING_ENTRIES:
            break
        examined += 1
        p = d / name
        try:
            if p.is_symlink() or not p.is_file():
                raise RC.CheckError("not a plain file; a ruling file is never a symlink")
            size = p.stat().st_size
            if size > A.MAX_READ:
                raise RC.CheckError(f"over {A.MAX_READ >> 20} MiB")
            if total + size > MAX_RULING_BYTES:
                examined -= 1   # not read: it is one of the files the note counts
                break
            total, read = total + size, read + 1
            out += RC.parse({name: p.read_bytes()}, None, "").values()
        except (OSError, RC.CheckError) as e:
            why = str(e).rsplit("\n  ", 1)[-1]
            skipped.append(f"skipped \"{_short(f'{shown}/{name}', 160)}\": {_short(why.removeprefix(name + ': '), 120)}")
    unread = len(names) - examined
    if read < len(names) - len(skipped):
        notes.append(f"(first {read} ruling files)")
    if unread or more:
        notes.append(f"({unread}{'+' if more else ''} more ruling files not read)")
    if skipped:
        notes.append("; ".join(skipped[:3]) + (f" (and {len(skipped) - 3} more skipped)" if len(skipped) > 3 else ""))
    return out


def committed(root: Path, paths: list[str], notes: list[str] | None = None) -> dict[str, list[dict]]:
    """path -> rulings, from the files `fold.py export` committed in the checkout at `root`; `notes` says what was not read.

    An item_status condition is UNCHECKED here (a checkout has no register),
    so it never makes a ruling stale; the server, which has one, does check it
    (the one difference from the live answer; test_rulecheck holds the two alike otherwise).
    """
    from . import fold as F
    from . import rulecheck as RC
    root = Path(root).resolve()
    rel = RC._locked_default(root, None)
    d = F.inside(root, rel, "fold.locked")
    entries = from_export_dir(d, notes, d.relative_to(root).as_posix())
    holds = holds_fn(A.Tree(root, {}), statuses_known=False)
    return {p: match(entries, p, holds) for p in paths}


class _DeadlineSocket(socket.socket):
    """A Unix socket with ONE wall-clock deadline for every operation together (C7), not a timeout per operation:
    a console dripping a byte at a time would otherwise hold the hook for as long as it likes."""
    deadline = 0.0

    def _left(self) -> None:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("the console server took over the lookup's deadline")
        self.settimeout(left)

    def connect(self, address) -> None:  # type: ignore[override]
        self._left()
        super().connect(address)

    def sendall(self, data, *a) -> None:  # type: ignore[override]
        self._left()
        super().sendall(data, *a)

    def recv_into(self, buf, *a) -> int:  # type: ignore[override]   (what http.client's reads come through)
        self._left()
        return super().recv_into(buf, *a)

    def recv(self, n, *a) -> bytes:  # type: ignore[override]
        self._left()
        return super().recv(n, *a)


class _UnixConn(http.client.HTTPConnection):
    def __init__(self, sock_path: Path, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self.sock_path = sock_path

    def connect(self) -> None:
        s = _DeadlineSocket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.deadline = time.monotonic() + self.timeout
        self.sock = s
        s.connect(str(self.sock_path))


def fetch(sock: Path, paths: list[str], project: str | None = None, token: str | None = None,
          timeout: float = TIMEOUT) -> dict[str, list[dict]]:
    """path -> rulings from the console server's agent socket; Unreachable when it does not answer in `timeout`.

    `timeout` is one deadline for the whole exchange (C7). C1: only a 400
    naming its `error` is the server refusing this request (Refused, its
    words); a 401 or 403 (a token gone stale), a 5xx (a crash), a 404 (a kit
    with no lookup) or any other answer is the server not answering, so the
    committed rulings answer instead (Unreachable).
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
    if resp.status == 200 and isinstance(out, dict) and isinstance(out.get("rulings"), dict):
        return out["rulings"]
    why = out.get("error") if isinstance(out, dict) else None
    if resp.status == 400 and isinstance(why, str) and why:
        raise Refused(why)
    raise Unreachable(f"the console server answered {resp.status}")


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
    a refusal from a server that did answer is raised (Refused). The note
    says the answer is the committed one, and any ruling file not read.
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
    notes: list[str] = []
    found = committed(root, paths, notes)
    return {"source": "committed", "note": " ".join([FALLBACK_NOTE, *notes]), "why": why, "rulings": found}


# -- the checkout a file is in -----------------------------------------------------------------

def project_root(start: Path) -> Path | None:
    """The nearest folder holding `start` (itself or an ancestor) with a `.git` (a folder, or a worktree's file)."""
    p = Path(os.path.realpath(start))
    for d in (p, *p.parents):
        if os.path.lexists(d / ".git"):
            return d
    return None


def _gitdir_line(f: Path, key: str) -> Path | None:
    """The path a small plain git link file names ("gitdir: P", or just "P" for key ""), relative to its folder; else None."""
    try:
        if f.is_symlink() or not f.is_file() or f.stat().st_size > 4096:
            return None
        line = f.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if key:
        if not line.startswith(key):
            return None
        line = line[len(key):].strip()
    if not line:
        return None
    p = Path(line)
    return Path(os.path.realpath(p if p.is_absolute() else f.parent / p))


def main_checkout(root: Path) -> Path | None:
    """For a linked worktree of MAIN, MAIN; else None. No git is run.

    The worktree's `.git` file says "gitdir: MAIN/.git/worktrees/NAME", and
    (S1) git's own back link must agree: `MAIN/.git/worktrees/NAME/gitdir`
    names this `.git` file. Without that, any folder could write a `.git` file
    naming a registered project and borrow its console and rulings.
    """
    root = Path(os.path.realpath(root))
    gd = _gitdir_line(root / ".git", "gitdir:")
    if gd is None or gd.parent.name != "worktrees" or gd.parent.parent.name != ".git":
        return None
    if _gitdir_line(gd / "gitdir", "") != root / ".git":
        return None
    return gd.parent.parent.parent


# -- in words ---------------------------------------------------------------------------------

def line_of(h: dict) -> str:
    """One ruling in one line: label, qid, question, answer, when and who, and whether it is stale."""
    who = f" by {h['locked_by_name']}" if h.get("locked_by_name") else ""
    when = (h.get("locked_at") or "")[:10]
    syms = [symbol_name(c.get("symbol")) for c in h.get("conditions") or [] if isinstance(c, dict)
            and c.get("kind") == "symbol"]
    on = f" [on {', '.join(syms[:3])}{', ...' if len(syms) > 3 else ''}]" if syms else ""   # 1.54: which definitions
    s = (f"- {LABELS.get(h['label'], h['label'])}{on}: {h['qid']} \"{h['question']}\" -> {h['answer']} "
         f"(locked {when}{who})")
    if h.get("stale"):
        s += " STALE: its evidence changed since it was locked, so do not rely on it"
    return s if len(s) <= SAY_LINE else s[:SAY_LINE - 1] + "…"


def say(path: str, hits: list[dict], breaks: list[tuple[dict, list[dict]]], note: str | None, more: str,
        info: bool = True, moves: list[tuple[dict, list[dict]]] = ()) -> str | None:
    """The hook's note for one file, or None when it has nothing to say.

    `info` False leaves out the list (already shown this session); a warning
    that the edit would break a ruling is always said. C4: the warnings come
    first and always fit, each whole (three lines, U2); the list gets what is
    left of SAY_TOTAL. `more` is the command that shows everything. `moves`
    (1.54, K3) are the definitions the edit renames with their bodies kept:
    each is said after the warnings, with the proposal that re-anchors it.
    """
    warned, out, notes = [], [], []
    for h, ms in moves:
        for m in ms:
            # A name the note can only show as `?` (non-ASCII, say) is never proposed as `?` (1.54 review, LOW).
            cmd = (A.propose_command(str(h.get("qid")), f"{path}::{m['to']}", "renamed, same body")
                   if symbol_name(m["to"]) == m["to"] else None)
            notes.append("\n".join([
                _cut(f"NOTE: this edit renames {symbol_name(m['condition'].get('symbol'))} to "
                     f"{symbol_name(m['to'])}, which ruling {_short(h.get('qid'), 80)} rests on; its body is "
                     f"unchanged, so the ruling follows it. After the edit, propose the new name for the owner to "
                     f"confirm:"), f"  `{cmd}`" if cmd else "  (`agent.py propose-anchor`; a name here is not printable)"]))
    warn = [(h, b) for h, b in breaks if b]
    for i, (h, b) in enumerate(warn):
        w = "\n".join([f"WARNING: this edit would break ruling {h['qid']} (\"{_short(h['question'], 80)}\").",
                       _cut(f"  Why: {'; '.join(x['words'] for x in b)}."),
                       "  What to do: keep what the ruling rests on, or ask the owner to re-lock it (`agent.py ask`). "
                       "The edit is not blocked."])
        tail = f"- and {len(warn) - i - 1} more would break: `{more}`" if i < len(warn) - 1 else ""
        if len("\n".join(warned + [w, tail])) > SAY_TOTAL and warned:
            warned.append(f"- and {len(warn) - i} more would break: `{more}`")
            break
        warned.append(w)
    for n in notes:   # after the warnings, while they fit: a rename is news, not a break
        if len("\n".join(warned + [n])) <= SAY_TOTAL:
            warned.append(n)
    left = SAY_TOTAL - len("\n".join(warned)) - (1 if warned else 0)
    if info and hits:
        out.append(f"Owner rulings on {path}{' ' + note if note else ''}. Follow them; to go against one, ask the "
                   f"owner first with a new question (`agent.py ask`; the console-ask skill shows how):")
        shown = [line_of(h) for h in hits[:SAY_RULINGS]]
        rest = len(hits) - len(shown)
        tail = lambda n: [f"- and {n} more: `{more}`"] if n else []  # noqa: E731
        while shown and len("\n".join(out + shown + tail(rest))) > left:
            shown.pop()
            rest += 1
        out = out + shown + tail(rest) if len("\n".join(out + shown + tail(rest))) <= left else []
    text = "\n".join(warned + out)
    return text or None


def _cut(s: str) -> str:
    return s if len(s) <= SAY_LINE else s[:SAY_LINE - 1] + "…"
