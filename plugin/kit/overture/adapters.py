"""Adapters for other agent vendors (Wave 4, owner V1-V4): the Claude plugin's guardrails, in their hooks.

Any MCP client already asks and reads rulings through `mcp_server.py` (1.35).
What only Claude Code had is the plugin's hooks: the note a session starts
with, and the owner's rulings said around an edit. This module gives Codex CLI,
Cursor and Copilot CLI the same, through each vendor's own hooks (V1).

**One core, a thin layer per vendor (V4).** `read` turns a vendor's hook input
into an `Event` (a session start, or the files an edit touches); the core turns
that into a note; `render` writes the note in the vendor's output shape. The
Claude plugin's hooks (`plugin/hooks/`) are not built on this yet: they stay as
shipped.

**When each vendor can speak.** Each vendor's documented hooks decide it
(OPEN-DECISIONS "Wave 4: adapters"):

- Codex CLI says a note before an edit (`PreToolUse` on `apply_patch`, with
  `additionalContext`), so it gets what the Claude hook says: the rulings on
  each file the patch touches, and a warning when the patch would break one.
- Cursor and Copilot CLI can say nothing before a tool without deciding it
  (Cursor's `agent_message` is read only on a deny; Copilot's `preToolUse`
  only allows or denies, and fails closed). So they speak after the edit
  (`postToolUse`): the rulings on the file, and a warning when the edit broke
  one. Where the input carries the edit's old and new text, the file before the
  edit is worked out by undoing it, so a ruling that was already stale is not
  blamed on this edit; where it does not, a held ruling that is stale on the
  file as it is now is named as such.

**It informs and never decides (V2, as 1.52 R2).** No output carries a
permission decision.

**Trust comes from the user, never the repository (V3, §7.7).** A note is said
only in a project the user registered (`agent.py register`): a session start
in a registered project or one inside it, an edit only of a file whose own
checkout is registered (or is a verified worktree of one, `lookup.main_checkout`),
as `hooks/ruling_lookup.py` decides it. A file in any other repository gets
nothing, and only the registered checkout's paths are sent to its server.

**It fails open.** `adapter_hook.py` catches everything and exits 0: a broken
adapter never costs the owner a session or an edit.

Standard library only; it imports the kit's hook-safe modules (`lookup`,
`registry`) and nothing from a project.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

from . import lookup as L
from . import registry as R

VENDORS = ("codex", "cursor", "copilot")
EVENTS = ("session-start", "edit")
MAX_INPUT = 4 << 20                  # a whole file's new content can ride in the input
MAX_EDITS = 20                       # files one tool call may touch that are looked up, at most
SHOWN_FILE = "adapter-rulings-shown.json"
MAX_SHOWN = 256 << 10
KEEP_SHOWN = 500
KEEP_SECONDS = 7 * 86400
HOW_TO_ASK = "the overture MCP `ask` tool, or `agent.py ask`"

# Where an edit's file and text sit in a tool's input. Copilot CLI documents its edit tools
# (`edit`, `create`) but not their arguments, and Cursor names few of its tools, so the keys
# the vendors are known to use are tried in order; a call whose shape is not recognised says nothing.
PATH_KEYS = ("file_path", "path", "filePath", "target_file", "targetFile", "filename")
OLD_KEYS = ("old_string", "old_str", "oldString", "old_text")
NEW_KEYS = ("new_string", "new_str", "newString", "new_text")
CONTENT_KEYS = ("content", "contents", "file_text", "fileText", "text")


class Edit(NamedTuple):
    """One file a tool call touches, with the text the input shows (each None when it shows none)."""
    path: Path
    old: str | None = None       # a fragment the edit replaced...
    new: str | None = None       # ...and what replaced it
    content: str | None = None   # the whole new file (a create or a write)
    deleted: bool = False


class Event(NamedTuple):
    kind: str                    # "session-start" or "edit"
    cwd: Path | None
    session: str | None
    edits: tuple[Edit, ...] = ()
    hunks: tuple[tuple[Path, tuple[tuple[str, str], ...]], ...] = ()   # Codex: per file, (old, new) blocks in order


# -- reading a vendor's input ------------------------------------------------------------------------------

def _str(v: object) -> str | None:
    return v if isinstance(v, str) else None


def _abs(raw: object, cwd: Path | None) -> Path | None:
    s = _str(raw)
    if not s or "\0" in s:
        return None
    p = Path(s)
    if not p.is_absolute():
        if cwd is None:
            return None
        p = cwd / p
    return Path(os.path.realpath(p))


def _first(d: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str):
            return v
    return None


def _args(v: object) -> dict:
    """A tool's arguments as a dict: Copilot types them `unknown`, so a JSON string is read too."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return {}
    return v if isinstance(v, dict) else {}


def edit_from_args(args: dict, cwd: Path | None) -> Edit | None:
    """The file a generic edit tool's arguments name, with its old/new text or whole content; None for a non-edit."""
    path = _abs(_first(args, PATH_KEYS), cwd)
    if path is None:
        return None
    old, new = _first(args, OLD_KEYS), _first(args, NEW_KEYS)
    if old is not None and new is not None:
        return Edit(path, old=old, new=new)
    content = _first(args, CONTENT_KEYS)
    if content is not None:
        return Edit(path, content=content)
    return None   # a read, a list, a search: no text written, so no edit


def parse_patch(text: str, cwd: Path | None) -> tuple[list[Edit], list[tuple[Path, list[tuple[str, str]]]]]:
    """Codex's `apply_patch` envelope: the files it touches, and each update's hunks as (old, new) blocks.

        *** Begin Patch
        *** Update File: a.py       hunks follow: "@@ ..." then lines " ctx", "-old", "+new"
        *** Move to: b.py           (optional, right after an Update)
        *** Add File: c.py          every line "+..."
        *** Delete File: d.py
        *** End Patch

    A file's text after the patch is worked out from these by `after_patch`.
    """
    edits: list[Edit] = []
    hunks: list[tuple[Path, list[tuple[str, str]]]] = []
    cur: Path | None = None
    mode: str | None = None
    added: list[str] = []
    old: list[str] = []
    new: list[str] = []
    blocks: list[tuple[str, str]] = []

    def close_hunk() -> None:
        if old or new:
            blocks.append(("\n".join(old), "\n".join(new)))
        old.clear()
        new.clear()

    def close_file() -> None:
        nonlocal cur, mode
        if cur is not None and mode == "add":
            edits.append(Edit(cur, content="\n".join(added) + ("\n" if added else "")))
        elif cur is not None and mode == "update":
            close_hunk()
            edits.append(Edit(cur))
            hunks.append((cur, list(blocks)))
        cur, mode = None, None
        added.clear()
        old.clear()
        new.clear()
        blocks.clear()

    for line in text.split("\n"):
        if line.startswith("*** Update File: "):
            close_file()
            cur, mode = _abs(line[len("*** Update File: "):].strip(), cwd), "update"
        elif line.startswith("*** Add File: "):
            close_file()
            cur, mode = _abs(line[len("*** Add File: "):].strip(), cwd), "add"
        elif line.startswith("*** Delete File: "):
            close_file()
            p = _abs(line[len("*** Delete File: "):].strip(), cwd)
            if p is not None:
                edits.append(Edit(p, deleted=True))
        elif line.startswith("*** Move to: "):
            pass   # the text moves with the file; the rulings said are the source's
        elif line.startswith("*** "):
            close_file()   # Begin/End Patch, End of File
        elif mode == "add" and line.startswith("+"):
            added.append(line[1:])
        elif mode == "update":
            if line.startswith("@@"):
                close_hunk()
            elif line.startswith("-"):
                old.append(line[1:])
            elif line.startswith("+"):
                new.append(line[1:])
            elif line.startswith(" "):
                old.append(line[1:])
                new.append(line[1:])
    close_file()
    return edits, hunks


def after_patch(current: str, blocks: list[tuple[str, str]]) -> str | None:
    """`current` with each hunk applied in order, each at its first place after the last; None if one is missing."""
    text, at = current, 0
    for old, new in blocks:
        i = text.find(old, at) if old else -1
        if i < 0:
            return None
        text = text[:i] + new + text[i + len(old):]
        at = i + len(new)
    return text


def read(vendor: str, event: str, payload: object) -> Event | None:
    """The vendor's hook input as an Event, or None when it is not one this adapter acts on."""
    if not isinstance(payload, dict) or vendor not in VENDORS or event not in EVENTS:
        return None
    cwd = _abs(payload.get("cwd"), None)
    if cwd is None and vendor == "cursor":
        roots = payload.get("workspace_roots")
        cwd = _abs(roots[0], None) if isinstance(roots, list) and roots else None
    sid = _str(payload.get("sessionId" if vendor == "copilot" else "session_id")) or _str(
        payload.get("conversation_id"))
    if event == "session-start":
        return Event("session-start", cwd, sid)
    if vendor == "codex":
        if payload.get("tool_name") != "apply_patch":
            return None
        ti = payload.get("tool_input")
        cmd = _str(ti.get("command")) if isinstance(ti, dict) else _str(ti)
        if cmd is None:
            return None
        edits, hunks = parse_patch(cmd, cwd)
        return Event("edit", cwd, sid, tuple(edits[:MAX_EDITS]),
                     tuple((p, tuple(b)) for p, b in hunks[:MAX_EDITS]))
    args = _args(payload.get("toolArgs") if vendor == "copilot" else payload.get("tool_input"))
    one = edit_from_args(args, cwd)
    return Event("edit", cwd, sid, (one,) if one is not None else ())


# -- the notes --------------------------------------------------------------------------------------------

def _entry_for_checkout(root: Path) -> dict | None:
    """The registry entry for exactly this checkout, or for the main checkout it is a verified worktree of."""
    found = R.load()
    for start in (Path(os.path.realpath(root)), L.main_checkout(root)):
        e = found.get(str(start)) if start is not None else None
        if e is not None:
            return None if R.entry_problems(e) else e
    return None


def session_note(cwd: Path | None) -> str | None:
    """What a session in a registered project starts with; None anywhere else."""
    if cwd is None:
        return None
    hit = R.enclosing(cwd)
    if hit is None:
        return None
    root, e = hit
    agent = shlex.join(["python3", str(Path(e["kit"]) / "agent.py"), "--state", e["state"]])
    lines = [
        f"Owner console: this project ({root}) is registered with an Overture console. The owner decides here, "
        "and their rulings bind this session.",
        "- Post every question the owner must decide to the console with the overture MCP `ask` tool (or "
        f"`{agent} ask FILE`); a question written only in a reply or a document never reaches the owner's inbox. "
        "Run `lesson_match` on a draft first, and read `answers` so you do not ask what is already decided.",
        "- `todo` lists what is waiting on you; `rulings` with {\"paths\": [...]} lists the owner's rulings on "
        "files before you change them.",
        "- Rulings on a file you edit are also said to you around the edit. Follow them; to go against one, ask "
        "the owner first with a new question.",
        "- Never run `watch`, `synced` or the fold: they belong to the console's steward.",
    ]
    if e.get(R.STEWARD):
        lines.append(f"- This console's steward is {e[R.STEWARD]}; this session is not it.")
    return "\n".join(lines)


def _shown_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "overture" / SHOWN_FILE


def seen_before(sid: str | None, key: str, digest: str) -> bool:
    """Whether this session was shown this file's rulings as they are now; records it when not. Never raises.

    As `hooks/ruling_lookup.seen_before`: unlocked, so two racing edits may each
    say the list; that is the worst case (never a list withheld).
    """
    if sid is None:
        return False
    p, now = _shown_path(), time.time()
    k = hashlib.sha256(f"{sid}\0{key}".encode("utf-8", "replace")).hexdigest()
    try:
        raw = R.read_regular(p, MAX_SHOWN, nofollow=True)
        shown = json.loads(raw.decode("utf-8")) if raw is not None else {}
        shown = shown if isinstance(shown, dict) else {}
        old = shown.get(k)
        if isinstance(old, dict) and old.get("h") == digest:
            return True
        shown[k] = {"h": digest, "t": now}
        keep = sorted(((x, v) for x, v in shown.items() if isinstance(v, dict) and isinstance(v.get("t"), (int, float))
                       and now - v["t"] < KEEP_SECONDS), key=lambda kv: -kv[1]["t"])[:KEEP_SHOWN]
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".adapter-shown.")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(dict(keep), fh)
        os.replace(tmp, p)
    except Exception:  # noqa: BLE001 - a state file it cannot use means the list is said again, never lost
        return False
    return False


def _digest(hits: list[dict]) -> str:
    rows = [[h.get("qid"), h.get("label"), h.get("stale"), h.get("locked_at"), h.get("answer")] for h in hits]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def _text(f: Path) -> str | None:
    """The file's text as it is now, or None: absent, not a plain file, too large, or not UTF-8."""
    try:
        if f.is_symlink() or not f.is_file() or f.stat().st_size > L.A.MAX_READ:
            return None
        return f.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _undo(current: str | None, ed: Edit) -> str | None:
    """The file's text before an edit that already happened, when the input shows enough to undo it; else None."""
    if current is None or ed.old is None or ed.new is None or not ed.new or current.count(ed.new) != 1:
        return None   # a fragment that is absent or not unique cannot be put back with certainty
    return current.replace(ed.new, ed.old, 1)


def _before_and_after(ed: Edit, hunks: dict, before_edit: bool) -> tuple[str | None, str | None]:
    """(the file's text before the edit, after it); either None when it cannot be worked out."""
    now = _text(ed.path)
    if before_edit:
        if ed.deleted:
            return now, ""
        if ed.path in hunks:
            return now, after_patch(now, list(hunks[ed.path])) if now is not None else None
        return now, ed.content if now is not None else None   # an Add over a file that exists
    return _undo(now, ed), "" if ed.deleted else now


def edit_note(ev: Event, before_edit: bool) -> str | None:
    """The note for the files an edit touches, joined; None when none of them has a ruling to say."""
    hunks = dict(ev.hunks)
    notes = []
    for ed in ev.edits:
        root = L.project_root(ed.path.parent)
        e = _entry_for_checkout(root) if root is not None else None
        if e is None:
            continue
        try:
            rel = L.clean_path(ed.path.relative_to(root).as_posix())
        except ValueError:
            continue
        res = L.lookup(Path(e["state"]), root, [rel])
        hits = res["rulings"].get(rel) or []
        if not hits:
            continue
        held = [h for h in hits if h.get("label") == L.HOLDS]
        old, new = _before_and_after(ed, hunks, before_edit)
        breaks, moves = [], []
        if new is not None and old is not None and len(new.encode("utf-8")) <= L.A.MAX_READ:
            breaks = [(h, L.would_break(h.get("conditions") or [], rel, new, old)) for h in held]
            moves = [(h, L.follows(h.get("conditions") or [], rel, new, old)) for h in held]
        elif not before_edit:
            # Nothing to undo the edit with: name each held ruling that is stale on the file as it is now,
            # without claiming this edit did it.
            breaks = [(h, [{"words": "it is stale on the file as it is now (this edit or an earlier one changed "
                                     "what it rests on)"}]) for h in held if h.get("stale")]
        more = shlex.join(["python3", str(Path(e["kit"]) / "agent.py"), "--state", e["state"], "rulings",
                           "--path", rel])
        info = not seen_before(ev.session, f"{root}\0{rel}", _digest(hits))
        text = L.say(rel, hits, breaks, res.get("note"), more, info=info, moves=moves, done=not before_edit,
                     how_to_ask=HOW_TO_ASK)
        if text:
            notes.append(text)
    return "\n\n".join(notes) or None


def note(vendor: str, event: str, payload: object) -> str | None:
    """The note this vendor's hook says for `payload`, or None. May raise; `adapter_hook.py` fails open."""
    ev = read(vendor, event, payload)
    if ev is None:
        return None
    if ev.kind == "session-start":
        return session_note(ev.cwd)
    return edit_note(ev, before_edit=vendor == "codex")


# -- writing a vendor's output ----------------------------------------------------------------------------

def render(vendor: str, event: str, text: str | None) -> str:
    """The hook's stdout: the vendor's own shape around `text`; never a permission decision.

    Codex reads empty output as nothing to add; Cursor and Copilot read `{}` the same way.
    """
    if vendor == "codex":
        if not text:
            return ""
        name = "SessionStart" if event == "session-start" else "PreToolUse"
        return json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}})
    if not text:
        return "{}"
    return json.dumps({"additional_context" if vendor == "cursor" else "additionalContext": text})


# -- installing (V3: the user's own config, never the repository's) ----------------------------------------

MARK = "adapter_hook.py"     # how an installed hook is known as ours, to replace or remove it
MCP_NAME = "overture"
AGENTS_BEGIN = "<!-- overture:begin (written by `agent.py adapter agents-md`; edit outside these lines) -->"
AGENTS_END = "<!-- overture:end -->"


class InstallError(Exception):
    pass


def hook_command(kit: Path, vendor: str, event: str) -> str:
    return shlex.join(["python3", str(kit / "adapter_hook.py"), vendor, event])


def hook_specs(kit: Path, vendor: str) -> dict:
    """The vendor's hook entries, in its own config shape (V2): the session-start note and the edit note."""
    start, edit = hook_command(kit, vendor, "session-start"), hook_command(kit, vendor, "edit")
    if vendor == "codex":
        return {"SessionStart": [{"matcher": "startup|resume|clear|compact",
                                  "hooks": [{"type": "command", "command": start, "timeout": 10}]}],
                "PreToolUse": [{"matcher": "apply_patch",
                                "hooks": [{"type": "command", "command": edit, "timeout": 5}]}]}
    if vendor == "cursor":
        return {"sessionStart": [{"command": start, "timeout": 10}],
                "postToolUse": [{"command": edit, "timeout": 5}]}
    return {"sessionStart": [{"type": "command", "bash": start, "timeoutSec": 10}],
            "postToolUse": [{"type": "command", "bash": edit, "matcher": "edit|create", "timeoutSec": 5}]}


def paths(vendor: str, home: Path | None = None) -> dict[str, Path]:
    """Where this vendor keeps its user-level hooks and MCP config (V3)."""
    h = home or Path(os.path.expanduser("~"))
    return {"codex": {"hooks": h / ".codex" / "hooks.json", "mcp": h / ".codex" / "config.toml"},
            "cursor": {"hooks": h / ".cursor" / "hooks.json", "mcp": h / ".cursor" / "mcp.json"},
            "copilot": {"hooks": h / ".copilot" / "hooks" / "overture.json",
                        "mcp": h / ".copilot" / "mcp-config.json"}}[vendor]


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise InstallError(f"{p} is not JSON this command can merge into ({e}); fix or move it, then run again")
    if not isinstance(doc, dict):
        raise InstallError(f"{p} is not a JSON object; fix or move it, then run again")
    return doc


def _write_text(p: Path, text: str) -> None:
    """Replace `p` whole and at once, keeping its mode; a new file is the user's alone (0600)."""
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if p.exists():
            os.chmod(tmp, p.stat().st_mode & 0o777)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _ours(entry: object) -> bool:
    return MARK in json.dumps(entry)


def merge_hooks(doc: dict, specs: dict | None, vendor: str, where: Path) -> dict:
    """`doc` with every hook of ours removed, then `specs` added (None: removed only); everyone else's kept."""
    out = dict(doc)
    if vendor != "codex" and specs is not None:
        out.setdefault("version", 1)
    hooks = out.get("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallError(f"{where}: \"hooks\" is not an object; fix it, then run again")
    merged = {}
    for name, entries in hooks.items():
        kept = [x for x in entries if not _ours(x)] if isinstance(entries, list) else entries
        if kept != []:
            merged[name] = kept
    for name, entries in (specs or {}).items():
        merged[name] = (merged[name] if isinstance(merged.get(name), list) else []) + entries
    out["hooks"] = merged
    return out


def mcp_args(kit: Path, agent: str) -> list[str]:
    """The MCP server's arguments: no --state, so it finds the console from the project it runs in."""
    return [str(kit / "mcp_server.py"), "--as", agent]


TOML_TABLE = re.compile(r"^\[mcp_servers\.overture\]\s*$", re.M)


def codex_mcp_block(kit: Path, agent: str) -> str:
    args = ", ".join(json.dumps(a) for a in mcp_args(kit, agent))
    return f"[mcp_servers.{MCP_NAME}]\ncommand = \"python3\"\nargs = [{args}]\n"


def install(vendor: str, kit: Path, agent: str, home: Path | None = None) -> list[str]:
    """Write the vendor's user-level hooks and MCP config (V3); return one line per file written."""
    if vendor not in VENDORS:
        raise InstallError(f"--vendor must be one of {', '.join(VENDORS)}")
    where = paths(vendor, home)
    done = []
    doc = merge_hooks(_load_json(where["hooks"]), hook_specs(kit, vendor), vendor, where["hooks"])
    _write_text(where["hooks"], json.dumps(doc, indent=2) + "\n")
    done.append(f"hooks: {where['hooks']}")
    if vendor == "codex":
        cfg = where["mcp"].read_text(encoding="utf-8") if where["mcp"].exists() else ""
        if TOML_TABLE.search(cfg):
            done.append(f"mcp: {where['mcp']} already has [mcp_servers.{MCP_NAME}]; left as it is")
        else:
            sep = "" if not cfg else ("\n" if cfg.endswith("\n") else "\n\n")
            _write_text(where["mcp"], cfg + sep + codex_mcp_block(kit, agent))
            done.append(f"mcp: {where['mcp']}")
        return done
    mdoc = _load_json(where["mcp"])
    servers = mdoc.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise InstallError(f"{where['mcp']}: \"mcpServers\" is not an object; fix it, then run again")
    server: dict = {"command": "python3", "args": mcp_args(kit, agent)}
    if vendor == "copilot":
        server = {"type": "local", **server, "tools": ["*"]}
    mdoc["mcpServers"] = {**servers, MCP_NAME: server}
    _write_text(where["mcp"], json.dumps(mdoc, indent=2) + "\n")
    done.append(f"mcp: {where['mcp']}")
    return done


def uninstall(vendor: str, home: Path | None = None) -> list[str]:
    """Remove our hooks and MCP entry from the vendor's user config; everyone else's stay."""
    if vendor not in VENDORS:
        raise InstallError(f"--vendor must be one of {', '.join(VENDORS)}")
    where = paths(vendor, home)
    done = []
    if where["hooks"].exists():
        doc = merge_hooks(_load_json(where["hooks"]), None, vendor, where["hooks"])
        if vendor == "copilot" or (not doc["hooks"] and set(doc) <= {"hooks", "version"}):
            where["hooks"].unlink()   # a file of our own, or one with nothing left in it (real run, 2026-10-22)
        else:
            _write_text(where["hooks"], json.dumps(doc, indent=2) + "\n")
        done.append(f"hooks: {where['hooks']}")
    if not where["mcp"].exists():
        return done
    if vendor == "codex":
        cfg = where["mcp"].read_text(encoding="utf-8")
        m = TOML_TABLE.search(cfg)
        if m:
            nxt = re.compile(r"^\[", re.M).search(cfg, m.end())
            head = cfg[:m.start()].rstrip("\n")
            tail = cfg[nxt.start():] if nxt else ""
            _write_text(where["mcp"], head + ("\n\n" if head and tail else "\n" if head else "") + tail)
            done.append(f"mcp: {where['mcp']}")
        return done
    mdoc = _load_json(where["mcp"])
    servers = mdoc.get("mcpServers")
    if isinstance(servers, dict) and MCP_NAME in servers:
        mdoc["mcpServers"] = {k: v for k, v in servers.items() if k != MCP_NAME}
        _write_text(where["mcp"], json.dumps(mdoc, indent=2) + "\n")
        done.append(f"mcp: {where['mcp']}")
    return done


AGENTS_BLOCK = """## Owner console (Overture)

This project's decisions are made by its owner in an Overture console.

- Ask every question the owner must decide with the overture MCP `ask` tool; a question written only in a reply or a document never reaches the owner. Run `lesson_match` on a draft first, and read `answers` so you do not ask what is already decided.
- Before changing a file, `rulings` with {"paths": ["the/file"]} lists the owner's rulings on it. Follow them; to go against one, ask first.
- `todo` lists what is waiting on you.
"""


def agents_md(text: str) -> str:
    """`text` (a project's AGENTS.md, maybe empty) with our block written or replaced; the rest kept as it is."""
    block = f"{AGENTS_BEGIN}\n{AGENTS_BLOCK}{AGENTS_END}\n"
    a = text.find(AGENTS_BEGIN)
    b = text.find(AGENTS_END, a + 1) if a >= 0 else -1
    if a >= 0 and b > a:
        return text[:a] + block + text[b + len(AGENTS_END):].lstrip("\n")
    return (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
