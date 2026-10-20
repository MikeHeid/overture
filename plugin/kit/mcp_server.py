#!/usr/bin/env python3
"""The agent's side of the owner console as an MCP server, so any MCP client can ask the owner (1.35).

    mcp_server.py --state DIR [--project DIR] [--as NAME]

Cursor, Codex, Copilot, Claude or any other client that speaks the Model
Context Protocol launches this over stdio and gets the agent door as tools:
read what is waiting, ask questions, read rulings, check for stale ones and
for lessons, reply on an item. The owner answers in the console as always.

Every tool runs `agent.py` in this process, with the arguments built here, so
there is one client and one set of checks: the project the working directory
is in picks the console and its token (K4), the agent name rules hold, a
`view`, `todo` or `answers` read over 64 KiB is refused whole, and the server
validates every write. The door
needs nothing beyond the standard library, and neither does this.

`--project` is the checkout to run in, for a client that starts servers
somewhere else; the door is chosen from it exactly as agent.py chooses it from
its working directory. `--as` names this client's session (0.8.2), checked at
start, so every write it makes carries that name.

What is NOT here, on purpose: the steward's commands (watch, synced, inbox: one
cursor, one steward), the owner's (register, server, steward, role), and every
command that writes into a checkout (the exports, `lessons --fold`). A client
that needs them runs agent.py.

Both protocol eras are spoken: the 2025 `initialize` handshake, and the
stateless 2026-07-28 revision (`server/discover`, the version in each
request's `_meta`). stdout carries only protocol messages; anything else that
prints goes to stderr.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent as AG  # noqa: E402
from overture import __version__  # noqa: E402
from overture import names as N  # noqa: E402

MODERN = ("2026-07-28",)                                          # per-request `_meta` version, no handshake
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")  # the `initialize` handshake; newest first
META_VERSION = "io.modelcontextprotocol/protocolVersion"
SERVER_INFO = {"name": "overture", "title": "Overture owner console", "version": __version__}

INSTRUCTIONS = """\
Overture is the owner's console. When you need a decision from the person who owns this project, ask it here
instead of guessing or stopping in your terminal; the owner answers in a browser, and a locked answer (a
ruling) holds for every agent until the code it rests on changes.

1. `todo` first: what is already waiting on you. `answers` (with `item`) shows every question and the answer
   it got; read it before asking, and follow the rulings you find.
2. Before asking, run `lesson_match` with your question text and item. A match is a ruling the owner withdrew
   or stopped checking, with the reason; rephrase, or cite it in your question.
3. `ask` posts one question. `qid` is `<item>/Q<n>` with n the next unused number on that item. Each option
   needs a one-line `description` saying what it does and what it costs; `star` is the one you recommend.
   `valid_if` says what must stay true for the answer to stand: prefer an excerpt of the lines it rests on,
   {"kind": "excerpt", "path": "docs/x.md", "text": "the exact sentence"}; never hash a big living file.
4. The owner answers later. Poll `answers` (or `view` with `since`) for it; do not re-ask.
5. `check` lists stale rulings, condition by condition. A stale ruling's evidence moved: do not rely on it.
6. Before editing a file, `rulings` with its path (or `dir/` before a larger change) lists the rulings on it.
"""

_READ = {"readOnlyHint": True, "openWorldHint": False}
_WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
_ITEM = {"type": "string", "description": "an item id, as `view` lists them under `items`"}
_SINCE = {"type": "integer", "minimum": 0, "description": "only what changed after this store seq"}

QUESTION_SCHEMA = {
    "type": "object",
    "description": "the question as an agent posts it; the server stamps who wrote it",
    "required": ["qid", "item", "text", "kind", "options", "star", "valid_if", "source"],
    "properties": {
        "qid": {"type": "string", "description": "<item>/Q<n>, n the next number unused on that item"},
        "item": _ITEM,
        "text": {"type": "string", "description": "what to decide, with the facts it rests on"},
        "kind": {"type": "string", "enum": ["single", "multi", "free"]},
        "options": {"type": "array", "maxItems": 12, "items": {
            "type": "object", "required": ["id", "label"],
            "properties": {"id": {"type": "string", "description": "lowercase letters, digits and _"},
                           "label": {"type": "string"},
                           "description": {"type": "string", "description": "what it does and what it costs"}}}},
        "star": {"type": ["string", "null"], "description": "the option id you recommend, or null"},
        "star_by": {"type": "string", "description": "whose recommendation the star is, e.g. architect"},
        "valid_if": {"type": "array", "description": "conditions that must keep holding for the answer to stand"},
        "source": {"type": "string", "description": "the repo path it rests on, optionally :line or :line-line"},
        "evidence": {"type": "array", "description": "up to 8 {cite, command?, result?} rows"},
    },
}

# name -> (description, input schema, annotations). Each is built into agent.py arguments by _argv.
TOOLS = {
    "todo": ("What is waiting on you: open deliberations, threads and chat awaiting an agent, visual requests, "
             "the owner's inbox and the store seq.", {}, _READ),
    "view": ("The console's current view as JSON, narrowed to one item and everything under it, and to what "
             "changed after a store seq. Refused whole (never cut) over 64 KiB: narrow it.",
             {"item": _ITEM, "since": _SINCE}, _READ),
    "answers": ("Every question in a scope with every answer it got, as JSON. Read before asking: a locked "
                "answer is a ruling to follow.", {"item": _ITEM, "since": _SINCE}, _READ),
    "check": ("Why each stale ruling is stale, condition by condition, with a diff of the cited text. A stale "
              "ruling's evidence has moved; do not rely on it.", {}, _READ),
    "lesson_match": ("Check a question draft against the owner's lessons BEFORE asking: past rulings on the same "
                     "item that were withdrawn or left unchecked, with the owner's reason. No match is not an "
                     "error.", {"text": {"type": "string", "description": "the question text"}, "item": _ITEM},
                     _READ),
    "health": ("The console server's health: version, whether it is reachable.", {}, _READ),
    "ask": ("Post one question for the owner. Refused, with the reason, when it is malformed, its item does not "
            "exist, or its qid was used before.", {"question": QUESTION_SCHEMA}, _WRITE),
    "reply": ("Post a message on an item's thread, optionally replying to a record id.",
              {"item": _ITEM, "text": {"type": "string"},
               "reply_to": {"type": "string", "description": "the record id replied to"}}, _WRITE),
    "working": ("Show the owner 'agent active' on these items; it lapses after an hour.",
                {"items": {"type": "array", "items": _ITEM, "minItems": 1}}, _WRITE),
    "rulings": ("The owner's rulings on these files or folders, BEFORE you edit them (1.52.0). Each is labelled "
                "`holds` (a condition deciding it is on the path: an edit can break it) or `cites` (the path is "
                "its source or evidence: context). Follow them; a `stale` one's evidence moved since it was locked.",
                {"paths": {"type": "array", "minItems": 1, "maxItems": 50, "items": {
                    "type": "string", "description": "project-relative; a folder ends in /"}}}, _READ),
}
REQUIRED = {"lesson_match": ["text", "item"], "ask": ["question"], "reply": ["item", "text"], "working": ["items"],
            "rulings": ["paths"]}


class BadArguments(Exception):
    """A tool's arguments are not the shape it takes; the message says which."""


def _str(args: dict, key: str, required: bool = False) -> str | None:
    v = args.get(key)
    if v is None and not required:
        return None
    if not isinstance(v, str) or not v:
        raise BadArguments(f"`{key}` must be a non-empty string")
    if v == "--":   # argparse eats a bare `--` even after the first (3.11 hands back []); refused, not mangled
        raise BadArguments(f"`{key}` cannot be exactly `--`")
    return v


def _seq(args: dict) -> int | None:
    v = args.get("since")
    if v is None:
        return None
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:  # bool is an int to Python, never a seq
        raise BadArguments("`since` must be a whole number, 0 or more")
    return v


def _argv(name: str, args: dict, tmp: Path) -> list[str]:
    """agent.py's arguments for one tool call.

    A value goes in as `--opt=VALUE`, and positionals after `--`, so text
    starting with a dash (a reply that reads "--as owner", or "-h") stays
    data: argparse would otherwise take it as an option.
    """
    unknown = sorted(set(args) - set(TOOLS[name][1]))
    if unknown:
        raise BadArguments(f"unknown argument(s) {', '.join(unknown)}; `{name}` takes "
                           f"{', '.join(TOOLS[name][1]) or 'none'}")
    opt = lambda flag, v: [f"--{flag}={v}"] if v is not None else []  # noqa: E731
    if name in ("todo", "check", "health"):
        return [name] + (["--json"] if name == "check" else [])
    if name in ("view", "answers"):
        return [name, *(["--json"] if name == "answers" else []), *opt("item", _str(args, "item")),
                *opt("since", _seq(args))]
    if name == "lesson_match":
        return ["lesson-match", *opt("item", _str(args, "item", True)), "--", _str(args, "text", True)]
    if name == "reply":
        return ["reply", *opt("reply-to", _str(args, "reply_to")), "--", _str(args, "item", True),
                _str(args, "text", True)]
    if name == "working":
        items = args.get("items")
        if not isinstance(items, list) or not items or not all(isinstance(i, str) and i and i != "--" for i in items):
            raise BadArguments("`items` must be a non-empty list of item ids, none exactly `--`")
        return ["working", "--", *items]
    if name == "rulings":
        paths = args.get("paths")
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
            raise BadArguments("`paths` must be a non-empty list of project-relative paths")
        return ["rulings", "--json", *(f"--path={p}" for p in paths)]
    q = args.get("question")
    if not isinstance(q, dict):
        raise BadArguments("`question` must be a JSON object")
    f = tmp / "question.json"   # agent.py asks from a file; this one lives in a 0700 directory of our own
    f.write_text(json.dumps(q), encoding="utf-8")
    return ["ask", "--", str(f)]


class Door:
    """agent.py for one console: its state dir and this client's agent name, fixed at start."""

    def __init__(self, state: Path, agent: str | None) -> None:
        self.state, self.agent = state, agent

    def call(self, name: str, args: dict) -> dict:
        """A tools/call result. A refusal is a result with isError, so the model reads why and can retry.

        So is a failure of this machine (no temp dir, a disk full, an error agent.py did not expect):
        one tool call fails and says why, and the server and every other tool stay up.
        """
        try:
            with tempfile.TemporaryDirectory(prefix="overture-mcp-") as tmp:
                try:
                    argv = _argv(name, args, Path(tmp))
                except BadArguments as e:
                    return _text(str(e), True)
                rc, out, err = self._run(argv)
        except Exception as e:  # noqa: BLE001 — reported to the client and logged, never swallowed
            traceback.print_exc(file=sys.stderr)
            return _text(f"`{name}` failed inside the MCP server: {type(e).__name__}: {e}", True)
        ok = rc == 0 or (name == "lesson_match" and rc == 1)  # 1 is "no lesson matches": an answer
        text = out if not err else (out + ("\n" if out and not out.endswith("\n") else "") + err)
        return _text(text.strip() or ("done" if ok else f"agent.py exited {rc}"), not ok)

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        full = ["--state", str(self.state), *(["--as", self.agent] if self.agent else []), *argv]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = AG.main(full)
            except SystemExit as e:  # argparse refuses by exiting; never expected from argv built here, but an
                # exit inside a tool call must not end the server
                rc = e.code if isinstance(e.code, int) else 2
        return rc, out.getvalue(), err.getvalue()


def _text(text: str, is_error: bool) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _tool_list() -> list[dict]:
    return [{"name": n, "description": d,
             "inputSchema": {"type": "object", "properties": props, "required": REQUIRED.get(n, []),
                             "additionalProperties": False},
             "annotations": ann} for n, (d, props, ann) in TOOLS.items()]


def _error(mid, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": mid, "error": err}


def handle(door: Door, msg: object) -> dict | None:
    """One JSON-RPC message in, its response out (None for a notification, which gets none)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    if "id" not in msg:
        return None   # notifications/initialized, cancelled, progress: nothing to say back
    mid, method, params = msg["id"], msg["method"], msg.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _error(mid, -32602, "params must be an object")
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    asked = meta.get(META_VERSION)
    modern = asked is not None
    if modern and asked not in MODERN + LEGACY:
        return _error(mid, -32022, "Unsupported protocol version", {"supported": list(MODERN), "requested": asked})

    def ok(result: dict) -> dict:
        if modern:   # the stateless revision: say the result is whole, and who answered (SEP-2575)
            result = {"resultType": "complete", **result, "_meta": {"io.modelcontextprotocol/serverInfo": SERVER_INFO}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    caps = {"tools": {"listChanged": False}}
    if method == "initialize":
        want = params.get("protocolVersion")
        return ok({"protocolVersion": want if want in LEGACY else LEGACY[0], "capabilities": caps,
                   "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS})
    if method == "server/discover":
        return ok({"supportedVersions": list(MODERN), "capabilities": caps, "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": _tool_list()})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments", {})
        if not isinstance(name, str) or name not in TOOLS:   # a list name is unhashable: checked first
            return _error(mid, -32602, f"Unknown tool: {name}")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return _error(mid, -32602, "arguments must be an object")
        return ok(door.call(name, args))
    return _error(mid, -32601, f"Method not found: {method}")


def serve(door: Door, rx, tx) -> None:
    """Read newline-delimited JSON-RPC from `rx` until it closes, answering each request on `tx`.

    No one message can end the loop: a client bug or a hostile line costs that
    request an error, never every tool for the rest of the session.
    """
    for raw in rx:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except (ValueError, RecursionError):   # UnicodeDecodeError is a ValueError; [[[[… nests past the stack
            resp = _error(None, -32700, "Parse error")
        else:
            try:
                resp = handle(door, msg)
            except Exception as e:  # noqa: BLE001 — answered and logged, never swallowed
                traceback.print_exc(file=sys.stderr)
                resp = _error(msg.get("id") if isinstance(msg, dict) else None, -32603, f"Internal error: {e!r}")
        if resp is not None:
            # ASCII escapes: a lone surrogate echoed from the request cannot fail to encode, and
            # json.dumps escapes every newline in a string, so one message stays one line.
            tx.write(json.dumps(resp, separators=(",", ":")).encode("ascii") + b"\n")
            tx.flush()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", type=Path, required=True, help="the console's state dir, as agent.py takes it")
    ap.add_argument("--project", type=Path, help="the checkout to run in (default: the working directory)")
    ap.add_argument("--as", dest="agent", metavar="NAME", help="this client's agent name, e.g. cursor-1")
    a = ap.parse_args(argv)
    if a.agent is not None and N.problem(a.agent):
        print(f"mcp_server.py: --as: {N.problem(a.agent)}", file=sys.stderr)
        return 2
    state = a.state.resolve()   # before --project moves us: a relative --state means where we were started
    if a.project is not None:
        try:
            os.chdir(a.project)   # agent.py picks the console and its token from where it runs (K4)
        except OSError as e:
            print(f"mcp_server.py: --project {a.project}: {e}", file=sys.stderr)
            return 2
    tx = sys.stdout.buffer
    sys.stdout = sys.stderr   # a stray print must never corrupt the protocol stream
    serve(Door(state, a.agent), sys.stdin.buffer, tx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
