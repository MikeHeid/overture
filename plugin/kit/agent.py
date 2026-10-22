#!/usr/bin/env python3
"""The agent's side of the owner console: talk to the server's agent door (a user-only Unix socket).

    agent.py --state DIR inbox [--since SEQ | --all]
                                                the owner's writes from the doorbell, after the agent's cursor
    agent.py --state DIR watch [--since SEQ] [--timeout SECONDS]
                                                block until the owner sends 'process', 'fork', 'chat' or
                                                'visual', print it, exit
    agent.py --state DIR todo [--full]          what is waiting on the agent, as JSON: forks not done (id,
                                                item, kind, mode, roles), awaiting_agent, chat, visual
                                                requests, inbox qids, seq; filtered from `view`, never
                                                worked out a second way
    agent.py --state DIR view [--item ID] [--since SEQ] [--full]
                                                the current view as JSON; --item narrows to that item and
                                                everything under it (@chat: the chat), --since to what
                                                changed after a store seq
    agent.py --state DIR health                 the server's health as JSON; exit 0 healthy, 1 not, 2 unreachable
    agent.py --state DIR answers [--item ID] [--fork RECORD_ID] [--since SEQ] [--json] [--full]
                                                every question in a scope with every answer it got (§7.6)
    agent.py --state DIR fork-context FORK_ID   the round's bundle for its committee (§6.3, D14)
    agent.py --state DIR check [--json]         why each stale answer is stale, condition by condition (0.5.0)
    agent.py --state DIR reanchor [--dry-run] [--json]
                                                re-anchor stale locks that git history shows were cited
                                                text still in the file; the server computes every anchor
    agent.py --state DIR reply ITEM TEXT [--reply-to RECORD_ID]
    agent.py --state DIR ask QUESTION.json [...]
                                                append questions (each the record without type or by), in
                                                order; stops at the first refusal and names what was not sent
    agent.py --state DIR transcript FORK_ID FILE
                                                store a roar panel's transcript (Markdown, at most 48 KiB)
                                                on the roar fork it ran; one per fork, refused if larger
    agent.py --state DIR visual REQUEST_ID --format mermaid|html --file FILE --doc DOC.md --title TITLE
                                                answer an owner's visual request: the server stores FILE
                                                and its doc in its STATE dir (never in the project) and
                                                shows it on the item
    agent.py --state DIR asset ITEM --file IMAGE --caption TEXT [--kind before|after|screenshot|recording]
                               [--qid QID] [--pr N] [--ticket T-ID]
                                                post a screenshot or recording on an item (1.32): PNG,
                                                JPEG, WebP or GIF, judged by its bytes; it shows in the
                                                Feed and on the item. The server stores it in STATE.
    agent.py --state DIR ux-export --project WORKTREE --save MESSAGE_ID
                                                land an owner's ux-save (1.32): write components/<item>.md
                                                (+ .css) in YOUR worktree, the old version kept under
                                                components/.history/; then open the PR yourself
    agent.py --state DIR visual-export --project WORKTREE [--visual ID ...]
                                                copy stored visuals (default: all; identical files are
                                                skipped) into WORKTREE/<visuals_dir>/ and regenerate its
                                                INDEX.md there, to land by PR. WORKTREE is the TOP of
                                                your own git work tree, on a branch (never a folder
                                                inside it, never the server's checkout); a different
                                                file already at a target path is refused. Exits 0 when
                                                every chosen visual was exported, 3 when files were
                                                written but at least one visual was refused (each is
                                                named), 1 when nothing was written, 2 when the server
                                                cannot be reached
    agent.py --state DIR next-step refine|drill --project DIR
                                                print the installed user skill .overture.json's
                                                `next_step` names for that kind; exit 1 naming why when
                                                it is unset, not installed, or resolves into the project
    agent.py --state DIR working ITEM [ITEM ...]
                                                show the owner "agent active" on these items; this
                                                session's next `synced` clears it (0.8.2: only its own
                                                marks, by --as name), and it lapses after an hour. Run
                                                from inside an agent worktree it also says which branch
                                                (1.50.0; the branch and folder name only, never a path)
    agent.py --state DIR worktree new --item ITEM --kind KIND [--project REPO] [--json]
                                                make (or, for the same agent, kind and item, give back)
                                                this agent's worktree, ~/.overture/worktrees/<project>/
                                                overture/<kind>/<item>[-n], branched from origin/main
                                                after a fetch, and mark the item worked on with its
                                                branch; prints the path. KIND: ticket, visual, ux,
                                                playbook, round or fix. Needs this session's agent
                                                name (--as, OVERTURE_AGENT or /overture:as). Another
                                                agent on the item is named (an overlap warning, W4)
                                                and it still exits 0. A worktree whose PR merged or
                                                closed is never handed back. A project's
                                                worktree_setup is PRINTED, never run: run it yourself
    agent.py --state DIR worktree list [--project REPO] [--json]
                                                every agent worktree of this project: branch, item,
                                                kind, agent, age, last commit, ahead/behind, dirty,
                                                unpushed, PR (via gh, when it is there) and stale
    agent.py --state DIR worktree prune [--project REPO] [--dry-run] [--json]
                                                remove the clean worktrees that LANDED (PR merged at
                                                exactly their HEAD, by one `gh pr list`) or whose PR
                                                closed with every commit on a remote; keep and explain
                                                the rest (W3). Never --force, never branch -D, never a
                                                remote branch. `watch` runs it at most every 10 minutes
    agent.py --state DIR synced [--through SEQ] [--rx-through RX] [--error MSG]
                                                record that the agent has processed the doorbell up to SEQ
    agent.py --state DIR costs collect | show --fork RECORD_ID
                                                collect: sum this project's subagent transcripts (usage, id
                                                and agentType only, deduplicated by message id) into
                                                STATE/costs.jsonl, a sidecar the store never holds;
                                                show: one fork's bill, unattributed subagents apart (K2)
    agent.py --state DIR server add NAME --hostname HOST --aud AUD --port PORT --team-domain TEAM
                       [--root DIR] [--page PATH] [--slug SLUG ...]
                                                host this console on the one console server (K3): writes
                                                server.json beside your registry, never the registry (you
                                                run this, never a session); it also writes the project's
                                                agent token to tokens/NAME beside server.json (K4)
    agent.py --state DIR server token rotate NAME
                                                a new token for the project; the old one is refused at once
    agent.py --state DIR register --project DIR [--steward NAME]
                                                switch the plugin on for a project (you run this, never a session)
    agent.py --state DIR steward [NAME | --clear]
                                                show, set or clear the console's steward in your registry (0.8.3;
                                                you run this, never a session)
    agent.py --state DIR operator-name [EMAIL [NAME | --clear]]
                                                the short name a login's locks carry in exported ruling files;
                                                the email itself never leaves the console (1.38; you run this)
    agent.py --state DIR access [EMAIL [owner | member ITEM... | viewer | --clear]]
                                                who may do what in the console: no roles file, every login is
                                                the owner; with one, an unlisted login only reads (1.39; you
                                                run this, never a session)
    agent.py --state DIR invite EMAIL [--origin URL]
                                                a sign-in link for a console with --auth link (1.46): it works
                                                once, within 24 hours, and is printed once, never stored (you
                                                run this, never a session)
    agent.py --state DIR devices [--revoke ID]
                                                the browsers signed in by link on this machine, or sign one
                                                out at once (1.46; revoking is yours, never a session's)
    agent.py --state DIR server auth [cloudflare | link]
                                                show or set how the one server's owner doors sign browsers in
                                                (1.46; in force at its next start)
    agent.py --state DIR server listen [ADDR | --clear]
                                                show or set the one ZeroTier or Tailscale address every owner
                                                door listens on beside 127.0.0.1 (1.47; link mode only)

**Slim reads (K1).** JSON goes out compact when stdout is not a terminal.
`todo`, `view` and `answers` refuse a read over 64 KiB unless given --full:
they print nothing on stdout, name the narrower command on stderr and exit 4,
since a cut read would look whole.

`register` records, in your own registry (~/.config/overture/projects.json),
the project, this state dir, and the kit this agent.py lives in. The plugin
acts only in registered projects and takes the paths it runs from there, never
from the repository (§7.7).

While `watch` waits it records so in watch.json beside the doorbell, and the
owner's console shows "agent listening" until it exits or stops renewing it.

`watch` exits 0 with the waiting lines, or 3 when --timeout runs out. The
agent's cursor moves only through `synced --through`, and never backwards, so
a signal that arrives while the agent works is not marked processed.

The server stamps every write from this door `by: agent`.

**The one server and project tokens (K4).** When the console is hosted on the
one console server (`server add`), agent.py takes its project from the
directory it runs in: the registered root holding it names the console, and
server.json names that console's project and its token file,
tokens/NAME beside server.json. --state must name that same console, or
nothing is sent; there is no --token and no --project flag. The token file is
read on every call, so `server token rotate` needs no session restart, and the
token is never printed. A console server.json does not host keeps its own
STATE/agent.sock, as before.

**Agent names (0.8.2).** When several sessions share one console, each may
say who it is: `agent.py --as agent-6 ...` (before the subcommand), or
OVERTURE_AGENT=agent-6 in its environment; `--as` wins. The name is 1 to 32
lowercase letters, digits and single hyphens, starting with a letter, and
neither "agent" nor "owner"; anything else is refused by name (exit 2) and
nothing is sent. The owner's console shows it on the questions, replies,
visuals and transcripts this session writes, and `working`/`synced` then keep
and clear this session's own "agent active" marks, never another's. With no
name, everything is exactly as in 0.8.1, and the unnamed sessions share one
set of marks.

**The steward (0.8.3).** The doorbell has one cursor, so when several
sessions share a console, the user may name one of them its steward, in their
own registry: `agent.py --state DIR steward agent-5` (or `register ...
--steward agent-5`). Then `watch` and `synced` (and `fold.py`) refuse, exit 1,
unless this session's name (`--as`, or OVERTURE_AGENT) is the steward's; the
refusal names the steward and points at `ask`, `reply` and `working`, which
stay open to every session, named or not. The repository's `.overture.json`
cannot set it. With no steward, everything is as in 0.8.2. It is a guardrail
between cooperating sessions of one user, not a security boundary: any process
running as that user can edit the registry or the cursor.

**Session names (0.8.4).** The user may name a Claude Code session by typing
`/overture:as agent-5` in it; the plugin records that session's id against
the name in DIR/sessions.jsonl and puts the id in the session's Bash
environment as OVERTURE_SESSION. This session's name is then, in order:
`--as`, the name recorded for OVERTURE_SESSION, OVERTURE_AGENT.
"""

import argparse
import base64
import contextlib
import datetime as dt
import json
import os
import secrets
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overture.posix import require  # noqa: E402
require("agent.py")   # 1.53.2: before the imports below, which fail on native Windows
from overture import anchors as A  # noqa: E402
from overture import bundle as B  # noqa: E402
from overture import devices as DV  # noqa: E402
from overture import doorbell as D  # noqa: E402
from overture import gitseam as G  # noqa: E402
from overture import lookup as L  # noqa: E402
from overture import names as N  # noqa: E402
from overture import playbooks as PB  # noqa: E402
from overture import notify as NT  # noqa: E402
from overture import operators as OP  # noqa: E402
from overture import roles as RO  # noqa: E402
from overture import registry as R  # noqa: E402
from overture import sessions as SN  # noqa: E402
from overture import settings as SET  # noqa: E402
from overture import symbols as SY  # noqa: E402
from overture import view as V  # noqa: E402
from overture.server import agent_request  # noqa: E402


class DoorRefused(Exception):
    """agent.py will not send anything: the project it runs in and the one it was told do not agree (K4)."""


class _Door:
    """Where this call goes: a per-project server's STATE/agent.sock, or the one server's `/p/<project>`.

    On the one server the token is read from its file on EVERY call (K4, AC4.3),
    so a rotation needs no session restart; it is sent as a bearer header and
    never printed, logged or put in a message.
    """

    def __init__(self, sock: Path, project: str | None = None) -> None:
        self.sock, self.project = sock, project

    def request(self, method: str, path: str, body=None, agent: str | None = None):
        if self.project is None:
            return agent_request(self.sock, method, path, body, agent=agent)
        from overture import serverfile as SF
        try:
            tok = SF.read_token(self.project)
        except SF.ServerFileError as e:
            raise DoorRefused(f"refused, nothing sent: {e}") from None
        return agent_request(self.sock, method, f"/p/{self.project}{path}", body, agent=agent, token=tok)


_DOOR: _Door | None = None   # set by main() once the working directory has chosen the project


def _door(state: Path) -> _Door:
    return _DOOR if _DOOR is not None else _Door(Path(state) / "agent.sock")


def _req(state: Path, method: str, path: str, body=None, agent: str | None = None):
    return _door(state).request(method, path, body, agent=agent)


def _where(state: Path) -> str:
    d = _door(state)
    return f"{d.sock} (project {d.project})" if d.project else str(d.sock)


def resolve_door(state: Path) -> _Door:
    """Pick the door from WHERE this process runs, never from what it was asked (K4, spec §3.5, AC4.5).

    The registered root holding the working directory names a console (the
    registry lookup the plugin already does); server.json maps that console to
    a project, and the project to its token file. When either the working
    directory's console or --state's is hosted on the one server: run outside
    every registered root, or with --state naming another console, this
    refuses, naming both, before anything is sent. There is no --token and no
    --project flag. A console no server.json entry hosts keeps its own
    per-project socket, STATE/agent.sock, exactly as before the one server.
    """
    from overture import serverfile as SF
    from overture.multiserver import socket_path
    s = os.path.realpath(state)
    try:
        hosted = {os.path.realpath(e["state"]): n for n, e in SF.load()["projects"].items()
                  if isinstance(e, dict) and isinstance(e.get("state"), str)}
    except SF.ServerFileError as e:
        raise DoorRefused(f"refused, nothing sent: {e}") from None
    cwd = Path.cwd()
    here = R.enclosing(cwd) or _enclosing_via_worktree(cwd)
    here_state = os.path.realpath(here[1]["state"]) if here and isinstance(here[1].get("state"), str) else None
    if s not in hosted and here_state not in hosted:
        return _Door(Path(state) / "agent.sock")
    if here is None:
        raise DoorRefused(f"refused, nothing sent: {cwd} is inside no registered project root. agent.py takes its "
                          f"project from the directory it runs in; run it from inside your project's checkout")
    if here_state != s:
        raise DoorRefused(f"refused, nothing sent: --state {s} is not this project's console. {cwd} is in "
                          f"{here[0]}, registered on the console at {here_state}; agent.py takes its project from "
                          f"the directory it runs in, so pass that console's --state or run it from the other "
                          f"project's checkout")
    return _Door(socket_path(SF.location()), hosted[s])


def _enclosing_via_worktree(cwd: Path):
    """1.50.0: an agent worktree (~/.overture/worktrees/...) sits outside every registered root, so the project
    it runs in is the one its main checkout is in: asked of git, here, only for a folder under that base."""
    from overture import worktrees as WT
    try:
        base = os.path.realpath(WT.base_dir())
        if not os.path.realpath(cwd).startswith(base + os.sep):
            return None
        main = WT.main_checkout(cwd)
    except WT.WorktreeError:
        return None
    return R.enclosing(main) if main is not None else None


def _get_view(state: Path):
    """The view and items from the agent door, or an exit code after saying why not."""
    try:
        code, out = _req(state, "GET", "/view", None)
    except OSError as e:
        print(f"cannot reach the console server at {_where(state)}: {e}", file=sys.stderr)
        return None, 2
    if code != 200:
        sys.stdout.write(_json(out))
        return None, 1
    return out, 0


MAX_READ = 64 * 1024  # bytes of UTF-8 a read prints without --full (K1, E4)
TOO_LARGE = 4         # the exit code of a read refused for its size: nothing was printed


def _json(obj) -> str:
    """JSON for stdout: indented for a person at a terminal, compact for anything else (K1, E3)."""
    if sys.stdout.isatty():
        return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"


def _emit(text: str, full: bool, what: str, narrower: str) -> int:
    """Print `text` whole, or refuse it whole when it is over MAX_READ and --full was not given (K1, E4).

    A cut read would look complete when it is not, so nothing is printed on a
    refusal; the message names the size and the narrower command that answers it.
    """
    size = len(text.encode("utf-8"))
    if size > MAX_READ and not full:
        print(f"refused: `{what}` would print {size} bytes, over the {MAX_READ}-byte (64 KiB) cap; nothing was "
              f"printed. Read less with {narrower}, or pass --full to print all of it.", file=sys.stderr)
        return TOO_LARGE
    sys.stdout.write(text)
    return 0


def _slim_view(state: Path, since: bool = False):
    """The view for a slim read, or an exit code after saying why not.

    The client upgrades with the plugin and the server only when restarted, so
    the view can come from an older kit. What the slim reads need is checked
    first; a view lacking it is refused in one line naming the server's version.
    """
    out, rc = _get_view(state)
    if out is None:
        return None, rc
    try:
        V.check_view(out.get("view") if isinstance(out, dict) else None)
        if not isinstance(out.get("items"), dict):
            raise V.ViewTooOld("the payload has no items")
        if since:
            V.check_since(out["view"])
    except V.ViewTooOld as e:
        try:
            _code, health = _req(state, "GET", "/health", None)
            ver = health.get("version", "unknown") if isinstance(health, dict) else "unknown"
        except OSError:
            ver = "unknown"
        print(f"refused: the console server runs kit {ver} and {e}, which this client (kit {_kit_version()}) "
              f"needs; restart the console server so it runs this kit", file=sys.stderr)
        return None, 1
    return out, 0


def _kit_version() -> str:
    from overture import __version__
    return __version__


def _view(state: Path, item: str | None, since: int | None, full: bool) -> int:
    """The view, narrowed to an item (E2) and to what changed after a seq (E5), capped (E4)."""
    out, rc = _slim_view(state, since=since is not None)
    if out is None:
        return rc
    if item is not None:
        try:
            out = V.item_view(out, item)
        except KeyError as e:
            print(e.args[0], file=sys.stderr)
            return 1
    else:   # a proposal's text can be 40 KB: a whole read names it by digest, `--item` prints it
        out = {**out, "view": V.slim_refactor(out["view"])}
    if since is not None:
        out = {**out, "view": V.since(out["view"], since)}
    what = "view" + (f" --item {item}" if item is not None else "") + (f" --since {since}" if since is not None else "")
    return _emit(_json(out), full, what, "`todo` (what is waiting), `view --item ID` (one item and everything "
                                          "under it) or `view --since SEQ` (only what changed after a store seq)")


def _todo(state: Path, full: bool) -> int:
    """What is waiting on the agent, filtered from the same view the page shows (E1)."""
    out, rc = _slim_view(state)
    if out is None:
        return rc
    return _emit(_json(V.todo(out["view"])), full, "todo", "`view --item ID` for one item")


def _answers(state: Path, item: str | None, fork: str | None, as_json: bool, since: int | None = None,
             full: bool = False) -> int:
    """Print the answers sheet the page shows, from the same view (§7.6)."""
    out, rc = _slim_view(state, since=since is not None)
    if out is None:
        return rc
    if item is not None and item not in out["items"]:
        print(f"no item {item!r} in the project's item list", file=sys.stderr)
        return 1
    if fork is not None and fork not in out["view"]["forks"]:
        print(f"no fork {fork!r}", file=sys.stderr)
        return 1
    view = out["view"] if item is not None else V.slim_refactor(out["view"])   # as `view`: --item keeps the text
    if since is not None:  # only the questions changed after SEQ (E5); the forks stay for --fork
        view = {**view, "questions": V.since(view, since)["questions"]}
    sheet = V.answers_sheet(view, out["items"], item=item, fork=fork)
    return _emit(_json(sheet) if as_json else V.sheet_markdown(sheet), full, "answers",
                 "`answers --item ID`, `answers --fork RECORD_ID` or `answers --since SEQ`")


def _fork_context(state: Path, fork: str) -> int:
    out, rc = _get_view(state)
    if out is None:
        return rc
    try:
        print(B.fork_context(out["view"], out["items"], fork), end="")
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        return 1
    except B.BundleTooLarge as e:
        print(e, file=sys.stderr)
        return 1
    return 0


def _check(state: Path, as_json: bool) -> int:
    try:
        code, out = _req(state, "GET", "/check", None)
    except OSError as e:
        print(f"cannot reach the console server at {_where(state)}: {e}", file=sys.stderr)
        return 2
    if code != 200 or as_json:
        sys.stdout.write(_json(out))
        return 0 if code == 200 else 1
    stale = out["stale"]
    if out.get("history"):
        print(f"git history: {out['history']}", file=sys.stderr)
    if not stale:
        print("No answer is stale.")
    for qid, s in stale.items():
        print(f"{qid} (anchored by {s['anchored_by']}):")
        for c in s["conditions"]:
            print(f"  {'holds' if c['holds'] else 'FAILS'}: {c['words']}")
            if c.get("diff"):
                print("\n".join("      " + ln for ln in c["diff"].splitlines()))
    return 0


def _rulings(state: Path, raw: list[str], as_json: bool) -> int:
    """The owner's rulings on each path (1.52.0): the console server, else the rulings committed in this checkout.

    The same lookup the PreToolUse hook makes, in the same entry shape. Exit 2
    for a path it will not look up (named); otherwise 0, whatever it found.
    """
    root = L.project_root(Path.cwd())
    try:
        paths = [L.clean_path(_inside_root(p, root)) for p in raw]
    except L.PathRefused as e:
        print(f"rulings: {e}", file=sys.stderr)
        return 2
    try:
        res = L.lookup(state, root, paths)
    except L.Refused as e:   # the server answered, and refused
        print(f"rulings: the console server refused: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - no server and no readable committed rulings: said, not raised
        print(f"rulings: no rulings could be read: {e}", file=sys.stderr)
        return 0
    if as_json:
        sys.stdout.write(_json(res))
        return 0
    out = [res["note"]] if res.get("note") else []
    for p in paths:
        out.append(f"{p}:")
        out += [L.line_of(h) for h in res["rulings"].get(p) or []] or ["  no rulings"]
    print("\n".join(out))
    return 0


def _adapter(a) -> int:
    """`adapter install|uninstall --vendor V`, `adapter agents-md` (Wave 4, V1-V4); refused inside a session.

    A session writing its own guardrails' config is what the owner's terminal is
    for, as with `server auth`. Codex runs new hooks only once the user trusts
    them (`/hooks`), so install says so.
    """
    from overture import adapters as AD
    if os.environ.get("CLAUDECODE"):
        print("agent.py: adapter: " + SESSION_REFUSAL.format(what="an agent's hooks are set"), file=sys.stderr)
        return 2
    kit = Path(__file__).resolve().parent
    try:
        if a.ad_cmd == "agents-md":
            hit = R.enclosing(a.project)
            if hit is None:
                print(f"agent.py: adapter agents-md: {a.project.resolve()} is not in a registered project; run "
                      f"`agent.py register` first. Nothing was written", file=sys.stderr)
                return 2
            p = Path(hit[0]) / "AGENTS.md"
            old = p.read_text(encoding="utf-8") if p.exists() else ""
            new = AD.agents_md(old)
            if new != old:
                AD._write_text(p, new)
            print(f"{p}: {'written' if new != old else 'already current'}; commit it with the project")
            return 0
        if a.ad_cmd == "install":
            name = a.name or a.vendor
            if N.problem(name):
                print(f"agent.py: adapter install: --name: {N.problem(name)}; nothing was written", file=sys.stderr)
                return 2
            done = AD.install(a.vendor, kit, name)
        else:
            done = AD.uninstall(a.vendor)
    except (AD.InstallError, R.RegistryError, OSError, UnicodeDecodeError) as e:
        print(f"agent.py: adapter {a.ad_cmd}: {e}", file=sys.stderr)
        return 2
    print("\n".join(done) if done else f"{a.vendor}: nothing of ours was installed")
    if a.ad_cmd == "install":
        print(f"They act only in projects registered on this machine (`agent.py register`)."
              + (" Codex runs new hooks once you trust them: type /hooks in Codex and approve these two."
                 if a.vendor == "codex" else "") + " Restart the agent to load them.")
    return 0


def _symbol_at(source: str, as_json: bool) -> int:
    """1.54 (K1): the `path::Class.method` condition for the definition that holds `source`'s lines, or why not.

    Read from this checkout through `anchors.Tree` (the same confinement and
    secrets rule the server reads with); the server reads it again, and fills
    in the hash, when the question is asked.
    """
    root = L.project_root(Path.cwd())
    rng_path = A.SOURCE_RANGE.match(source or "")
    if root is None or rng_path is None:
        print(f"symbol-at: {source!r} is not PATH:FIRST-LAST inside a git checkout", file=sys.stderr)
        return 2
    try:
        path = L.clean_path(_inside_root(rng_path.group("path"), root))
    except L.PathRefused as e:
        print(f"symbol-at: {e}", file=sys.stderr)
        return 2
    first = int(rng_path.group("a"))
    last = int(rng_path.group("b") or first)
    status, text = A.Tree(root, {}).text(path)
    if status != "ok":
        print(f"symbol-at: {path} {A.UNREADABLE[status]}", file=sys.stderr)
        return 2
    r = SY.enclosing(path, text, first, last)
    if r.state != "found":
        print(f"symbol-at: {r.reason}; anchor on the lines with an excerpt instead", file=sys.stderr)
        return 1
    ref = A.symbol_ref(path, r.symbol.qualname)
    if as_json:
        sys.stdout.write(_json({"kind": "symbol", "path": path, "symbol": r.symbol.qualname,
                                "sha256": r.symbol.body_sha256, "lines": [r.symbol.start_line, r.symbol.end_line]}))
    else:
        print(ref)
    return 0


def _inside_root(p: str, root: Path | None) -> str:
    """An absolute path inside the checkout, made relative to it (a trailing "/" kept); anything else as given."""
    if root is None or not p.startswith("/"):
        return p
    try:
        rel = Path(os.path.realpath(p)).relative_to(root).as_posix()
    except ValueError:
        return p
    return rel + ("/" if p.endswith("/") and rel != "." else "")


def _reanchor(state: Path, dry_run: bool, as_json: bool) -> int:
    """Ask the server to re-anchor; print what changed (or would), and what stays stale and why."""
    try:
        code, out = _req(state, "POST", "/reanchor", {"dry_run": dry_run})
    except OSError as e:
        print(f"cannot reach the console server at {_where(state)}: {e}", file=sys.stderr)
        return 2
    if code != 200 or as_json:
        sys.stdout.write(_json(out))
        return 0 if code == 200 else 1
    if out.get("history"):
        print(f"git history: {out['history']}", file=sys.stderr)
    verb = "would re-anchor" if dry_run else "re-anchored"
    not_done = {p["lock"] for p in out["plan"] if p.get("skipped") or p.get("error")}
    done = [p for p in out["plan"] if p["changes"] and p["lock"] not in not_done]
    for p in out["plan"]:
        tail = "" if p["fresh"] else " (still stale)"
        if p["lock"] in not_done:
            print(f"{p['qid']}: not re-anchored: {p.get('skipped') or p.get('error')}")
            continue
        for c in p["changes"]:
            print(f"{p['qid']}: {verb} {c['from']['path']}: {c['why']}{tail}")
        for c in p["unresolved"]:
            where = c["from"].get("path") or c["from"].get("item")
            print(f"{p['qid']}: left stale, {where}: {c['why']}")
    print(f"{len(done)} of {len(out['plan'])} stale answer(s) {verb}"
          + ("; nothing was written (dry run)" if dry_run else ""), file=sys.stderr)
    return 0


def _call(state: Path, method: str, path: str, body=None, agent: str | None = None) -> int:
    try:
        code, out = _req(state, method, path, body, agent=agent)
    except OSError as e:
        print(f"cannot reach the console server at {_where(state)}: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(_json(out))
    return 0 if code == 200 else 1


READ_CAP = 1 << 20  # a transcript or visual file larger than this is refused before it is sent
ASSET_READ_CAP = 8 << 20  # 1.32: an asset (a GIF at most 8 MiB); the server applies the per-format limits


def _read_text(path: Path, what: str) -> str | None:
    """A local UTF-8 file's text, or None after saying why not. The server applies the real limits."""
    try:
        data = R.read_regular(path, READ_CAP + 1)
    except R.RegistryError as e:
        print(f"{what} {path}: {e}", file=sys.stderr)
        return None
    if data is None:
        print(f"{what} {path} does not exist", file=sys.stderr)
        return None
    if len(data) > READ_CAP:
        print(f"{what} {path} is over {READ_CAP} bytes; refused, not cut", file=sys.stderr)
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        print(f"{what} {path} is not UTF-8 text", file=sys.stderr)
        return None


def _git_top(d: Path) -> Path | None:
    """The top of the git work tree holding `d`, or None when `d` is in none. Read-only: no optional locks.

    Agent side: this runs in `agent.py`, inside the agent's own jail, so it may
    use git (the server may not, CONSOLE-kit/Q23); it still goes through gitseam.
    """
    out = G.run(["rev-parse", "--is-inside-work-tree", "--show-toplevel"], d, timeout=30, text=True)
    if not isinstance(out, str):
        return None
    lines = out.splitlines()
    if len(lines) != 2 or lines[0].strip() != "true":
        return None
    return Path(lines[1]).resolve()


def _ux_export(state: Path, project: Path, save: str) -> int:
    """Write the owner's saved component into PROJECT/components (1.32). 0 written or unchanged; 1 refused; 2 no server."""
    from overture import components as CO
    dest = Path(project).resolve()
    top = _git_top(dest)
    if top is None or top != dest:
        print(f"refused: {project} must be the top of your own git worktree, on a branch (make one with "
              f"`agent.py worktree new --kind ux --item ITEM`)", file=sys.stderr)
        return 1
    try:
        code, out = _req(state, "POST", "/ux-export", {"save": save})
    except OSError as e:
        print(f"cannot reach the console server at {_where(state)}: {e}", file=sys.stderr)
        return 2
    if code != 200:
        print(f"refused: {out.get('error', out)}", file=sys.stderr)
        return 1
    server_root = Path(out["root"]).resolve()
    if dest in (server_root, _git_top(server_root)):
        print(f"refused: {project} is the directory the console server runs from ({server_root}); write into "
              f"your own worktree on a branch and land it by PR", file=sys.stderr)
        return 1
    try:
        done = CO.write(dest, out["item"], out)
    except (CO.ComponentError, OSError) as e:
        print(f"refused, nothing overwritten: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(_json({"project": str(dest), "item": out["item"], **done}))
    return 0


def _visual_export(state: Path, project: Path, ids: list[str]) -> int:
    """Copy stored visuals into PROJECT/<visuals_dir>/ and regenerate its INDEX.md (0.8.1).

    PROJECT is the agent's OWN worktree, on a branch, to be landed by PR. It
    must be the top of a git work tree, and it is refused when it is the
    directory the console server runs from (or that directory's work tree):
    the server's checkout follows main and must never gain untracked files.

    Exit codes (0.8.2): 0 every chosen visual exported (or already there,
    identical); 3 some files written, at least one visual refused and named;
    1 nothing written (refused, or every chosen visual refused); 2 the server
    cannot be reached.
    """
    from overture import projectcfg as PC
    from overture import visuals as VIS
    dest = Path(project).resolve()
    top = _git_top(dest)
    if top is None:
        print(f"refused: {project} is not a git work tree; export into your own worktree on a branch",
              file=sys.stderr)
        return 1
    if top != dest:
        print(f"refused: {project} is inside the work tree {top}; pass the top of your worktree, since "
              f"visuals_dir is a path from the repository's top", file=sys.stderr)
        return 1
    try:
        code, out = _req(state, "POST", "/visual-export", {"ids": ids})
    except OSError as e:
        print(f"cannot reach the console server at {_where(state)}: {e}", file=sys.stderr)
        return 2
    if code != 200:
        print(f"refused: {out.get('error', out)}", file=sys.stderr)
        return 1
    server_root = Path(out["root"]).resolve()
    server_top = _git_top(server_root)
    if dest in (server_root, server_top):
        print(f"refused: {project} is the directory the console server runs from ({server_root}). Its checkout "
              f"follows main, and a file written there blocks the next fast-forward. Export into your own "
              f"worktree on a branch (`agent.py worktree new --kind visual --item ITEM` prints one) and land it "
              f"by PR",
              file=sys.stderr)
        return 1
    for r in out["refused"]:
        print(f"not exported: visual {r['id']}: {r['why']}", file=sys.stderr)
    if out["refused"] and not out["visuals"]:
        # Every chosen visual was refused: write nothing at all, not even a regenerated INDEX.md.
        print(f"refused: none of the {len(out['refused'])} chosen visual(s) could be exported; nothing was "
              f"written", file=sys.stderr)
        return 1
    try:
        vdir = PC._dir(dest, out["visuals_dir"], "visuals_dir")   # the same jail, now against YOUR tree
        plan = VIS.export_plan(dest, vdir, out["visuals"])
        VIS.check_index(dest, vdir)
        done = VIS.export_write(dest, vdir, plan, out["records"])
    except (PC.ConfigError, VIS.VisualError, OSError) as e:
        print(f"refused, nothing overwritten: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(_json({"project": str(dest), "visuals_dir": vdir, **done, "refused": out["refused"]}))
    if not out["refused"]:
        return 0
    # 3: a partial export, told apart from 1 ("nothing was written") so a caller knows files landed.
    return 3 if done["written"] else 1


# -- 1.50.0: agent worktrees (OPEN-DECISIONS.md W1-W4) --------------------------------------------------

def _project_name(state: Path, main: Path) -> str:
    """The console's project name for `~/.overture/worktrees/<project>`: the one server's name for this console,
    else the registered project root's folder name, else the checkout's."""
    from overture import serverfile as SF
    s = os.path.realpath(state)
    try:
        for n, e in SF.load()["projects"].items():
            if isinstance(e, dict) and isinstance(e.get("state"), str) and os.path.realpath(e["state"]) == s:
                return n
    except SF.ServerFileError:
        pass
    here = R.enclosing(main)
    return Path(here[0]).name if here else Path(main).name


def _post_working(state: Path, items: list[str], where: dict | None, agent: str | None) -> tuple[int, dict, str]:
    """POST /working with the branch when there is one: (exit code, the server's answer, a note).

    An older server (before 1.50) refuses the extra keys; the mark is then sent again without them, and the
    note says the branch was not shown. Only that refusal, by its words: a 1.50 server's refusal of the branch
    itself is reported as it is (1.50 review L1).
    """
    body = {"items": items, **(where or {})}
    try:
        code, out = _req(state, "POST", "/working", body, agent=agent)
        if code == 400 and where and _older_than_branches(out):
            code, out = _req(state, "POST", "/working", {"items": items}, agent=agent)
            if code == 200:
                return 0, out, ("the console server did not take the branch (older than 1.50?): the item is "
                                "marked worked on, without it")
    except OSError as e:
        return 2, {}, f"cannot reach the console server at {_where(state)}: {e}"
    except DoorRefused as e:   # the worktree (if any) is made already: say so, never lose it to a traceback
        return 1, {}, str(e)
    if not isinstance(out, dict):
        out = {"error": str(out)}
    return (0 if code == 200 else 1), out, ("" if code == 200 else f"refused: {out.get('error', out)}")


OLD_WORKING = 'working takes {"items": ['   # a 1.49 server's whole refusal of any key but "items"


def _older_than_branches(out: object) -> bool:
    """Whether a 400 from /working is a server older than 1.50 refusing the unknown "branch" key."""
    err = out.get("error") if isinstance(out, dict) else None
    return isinstance(err, str) and err.startswith(OLD_WORKING) and '"branch"' not in err


def _here_branch() -> dict | None:
    from overture import worktrees as WT
    try:
        e = WT.registered_here(Path.cwd())
    except WT.WorktreeError:
        return None
    if not e:
        return None
    return {"branch": e["branch"], **({"worktree": e["worktree"]} if e.get("worktree") else {})}


def _worktree(a) -> int:
    from overture import worktrees as WT
    repo = Path(a.project) if a.project else Path.cwd()
    try:
        main = WT.main_checkout(repo)
        if main is None:
            raise WT.WorktreeError(f"refused: {repo} is not inside a git repository with a .git folder")
        name = _project_name(a.state, main)
        if a.wt_cmd == "new":
            return _worktree_new(a, WT, repo, name)
        if a.wt_cmd == "list":
            res = WT.list_worktrees(repo, name)
            if a.json:
                sys.stdout.write(_json(res))
                return 0
            for n in res["notes"]:
                print(n, file=sys.stderr)
            if not res["worktrees"]:
                print(f"no agent worktrees for {res['project']}")
            for r in res["worktrees"]:
                pr = (f"PR #{r['pr']['number']} {r['pr']['state']}" if r["pr"] else
                      ("PR unknown" if r["pr_unknown"] else "no PR"))
                flags = [f"{r['ahead']} ahead, {r['behind']} behind" if r["ahead"] is not None else "",
                         "dirty" if r["dirty"] else "", f"{r['unpushed']} unpushed" if r["unpushed"] else "",
                         "STALE" if r["stale"] else ""]
                print(f"{r['branch']}  {r['item'] or '?'}  {r['kind'] or '?'}  {r['agent'] or '?'}  "
                      f"{r['age_days'] if r['age_days'] is not None else '?'}d  {pr}  "
                      + "  ".join(f for f in flags if f) + f"\n    {r['path']}")
            return 0
        res = WT.prune(repo, name, dry_run=a.dry_run)
        if a.json:
            sys.stdout.write(_json(res))
            return 0
        for n in res["notes"]:
            print(n, file=sys.stderr)
        for r in res["removed"]:
            print(("would remove " if a.dry_run else "removed ") + r["branch"]
                  + (f" (local branch kept: {r['branch_kept']})" if r.get("branch_kept") else ""))
        for r in res["kept"]:
            print(f"kept {r['branch']}: {r['why']}")
        return 0
    except WT.WorktreeError as e:
        print(str(e), file=sys.stderr)
        return 1


def _worktree_new(a, WT, repo: Path, name: str) -> int:
    res = WT.new(repo, name, a.kind, a.item, a.agent)
    where = {"branch": res["branch"], **({"worktree": res["worktree"]} if WT.BASENAME.match(res["worktree"]) else {})}
    rc, out, note = _post_working(a.state, [a.item], where, a.agent)
    res["marked"] = rc == 0
    if note:
        res["notes"].append(note if rc == 0 else note + "; the worktree is made: run `agent.py working` from it "
                                                         "when the console is back")
    # W4: another agent on this item, whether this machine made its worktree or the console knows its mark.
    seen = {o["branch"] for o in res["overlap"]}
    me = a.agent or N.UNNAMED
    for bucket, marks in (out.get("branches") or {}).items() if isinstance(out, dict) else ():
        b = (marks or {}).get(a.item) if isinstance(marks, dict) else None
        if bucket != me and isinstance(b, dict) and b.get("branch") not in seen | {res["branch"]}:
            res["overlap"].append({"branch": b.get("branch"), "agent": bucket, "kind": None})
            seen.add(b.get("branch"))
    if a.json:
        sys.stdout.write(_json(res))
    else:
        print(res["path"])
    for n in res["notes"]:
        print(n, file=sys.stderr)
    if res["reused"]:
        print(f"your worktree for {a.kind} {a.item} already exists, on {res['branch']}: carry on there",
              file=sys.stderr)
    for o in res["overlap"]:
        print(f"overlap: {o['agent']} is also on {a.item}, in {o['branch']}. You are on {res['branch']}: warned, "
              f"not blocked (W4); talk on the item before you touch the same files", file=sys.stderr)
    return 0


GH_NOTE = ".worktrees-no-gh"   # in STATE: the steward was told once that prune needs gh
PRUNE_FILE = ".worktrees-prune.json"   # in STATE: when the watch last pruned, what was stale, where it stopped
PRUNE_EVERY = 600.0    # 1.50 review C2: the watch prunes at most once per 10 minutes...
PRUNE_BUDGET = 60.0    # ...and spends at most this long in all (its gh call too), then takes up there next time
MAX_PRUNE_FILE = 16384


def _prune_record(state: Path) -> dict:
    """The watch's last prune: {"at": epoch, "stale": list | None, "resume_after": branch | None}; {} if none."""
    try:
        data = R.read_regular(Path(state) / PRUNE_FILE, MAX_PRUNE_FILE, nofollow=True)
        rec = json.loads(data.decode("utf-8")) if data is not None else {}
    except (OSError, ValueError, RecursionError, R.RegistryError):   # Z3: nested past the parser's depth: no record
        return {}
    if not (isinstance(rec, dict) and isinstance(rec.get("at"), (int, float)) and not isinstance(rec["at"], bool)):
        return {}
    stale = rec.get("stale")
    after = rec.get("resume_after")
    return {"at": float(rec["at"]), "stale": stale if isinstance(stale, list) else None,
            "resume_after": after if isinstance(after, str) else None}


def _write_prune_record(state: Path, rec: dict) -> None:
    import tempfile
    p = Path(state) / PRUNE_FILE
    with contextlib.suppress(OSError):
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".worktrees-prune.", suffix=".tmp")   # 0600
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
            os.replace(tmp, p)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _watch_prune(state: Path, now: float | None = None, beat=None) -> list | None:
    """The steward's prune (W3): the stale ones for the heartbeat, or None (nothing said).

    Only for the project the working directory is in AND whose console this is (--state), so a watch run
    anywhere else touches nothing. 1.50 review C2: called after the watch's first heartbeat, it prunes at most
    once per PRUNE_EVERY (the time kept in STATE; in between it hands back the last stale list), makes ONE gh
    call, and stops looking after PRUNE_BUDGET seconds, to take up where it stopped on the next cycle. Without
    gh nothing can be judged: it is skipped, said once. Clearing round Z2: PRUNE_BUDGET is one deadline for
    all of it, gh included (`WT.Cycle`); each call is held to what is left and to under the heartbeat's grace,
    and `beat` (the watch's Heartbeat) is run before every call, so "listening" never lapses meanwhile.
    """
    import time as _time
    from overture import worktrees as WT
    t = _time.time() if now is None else now
    rec = _prune_record(state)
    if rec and not rec["resume_after"] and 0 <= t - rec["at"] < PRUNE_EVERY:
        return rec["stale"]
    cycle = WT.Cycle(PRUNE_BUDGET, tick=beat, call_max=D.BEAT_GRACE * 0.75)   # Z2: from here, all of it
    try:
        cwd = Path.cwd()
        here = R.enclosing(cwd) or _enclosing_via_worktree(cwd)
        if not here or os.path.realpath(here[1].get("state", "")) != os.path.realpath(state):
            return None
        main = WT.main_checkout(cwd, cycle)
        if main is None:
            return None
        name = _project_name(state, main)
        if not (WT.base_dir() / WT.project_slug(name, main)).is_dir():
            _write_prune_record(state, {"at": t, "stale": [], "resume_after": None})
            return []
        prs, why = WT.gh_prs(main, cycle)
        note = Path(state) / GH_NOTE
        if prs is None:
            if not note.exists():
                print(f"worktree prune skipped: {why}; agent worktrees are kept until gh is there (said once)",
                      file=sys.stderr)
                with contextlib.suppress(OSError):
                    note.write_text("1\n")
            _write_prune_record(state, {"at": t, "stale": None, "resume_after": None})
            return None
        with contextlib.suppress(OSError):
            note.unlink()
        res = WT.prune(main, name, prs=prs, cycle=cycle, start_after=rec.get("resume_after"))
    except (WT.WorktreeError, R.RegistryError, OSError) as e:
        print(f"worktree prune skipped: {e}", file=sys.stderr)
        return None
    for r in res["removed"]:
        print(f"worktree prune: removed {r['branch']}", file=sys.stderr)
    stale = res["stale"]
    if rec.get("resume_after"):   # a pass taken up again: what the first part found stale still counts
        seen = {s["branch"] for s in stale}
        stale = [*stale, *[s for s in rec.get("stale") or [] if isinstance(s, dict) and s.get("branch") not in seen
                          and isinstance(s.get("branch"), str) and s["branch"] <= rec["resume_after"]]]
    if res["unfinished"]:
        print(f"worktree prune: stopped after {PRUNE_BUDGET:g} s at {res['unfinished']}; the rest next cycle",
              file=sys.stderr)
    _write_prune_record(state, {"at": t, "stale": stale[:WT.MAX_STALE_REPORT], "resume_after": res["unfinished"]})
    return stale[:WT.MAX_STALE_REPORT]


NOTES_FILE = ".notes-check.json"   # in STATE: when the watch last checked the area notes, and its counts
NOTES_EVERY = 86400.0   # 1.53.0: the watch checks the area notes at most once a day
MAX_NOTES_FILE = 4096


def _notes_record(state: Path) -> dict:
    """The watch's last notes check: {"at": epoch, "counts": dict | None}; {} if none."""
    try:
        data = R.read_regular(Path(state) / NOTES_FILE, MAX_NOTES_FILE, nofollow=True)
        rec = json.loads(data.decode("utf-8")) if data is not None else {}
    except (OSError, ValueError, RecursionError, R.RegistryError):
        return {}
    if not (isinstance(rec, dict) and isinstance(rec.get("at"), (int, float)) and not isinstance(rec["at"], bool)):
        return {}
    c = rec.get("counts")
    ok = isinstance(c, dict) and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in c.values())
    return {"at": float(rec["at"]), "counts": {k: c[k] for k in sorted(c) if isinstance(k, str)} if ok else None}


def _write_notes_record(state: Path, rec: dict) -> None:
    import tempfile
    p = Path(state) / NOTES_FILE
    with contextlib.suppress(OSError):
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".notes-check.", suffix=".tmp")   # 0600
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
            os.replace(tmp, p)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _watch_notes(state: Path, now: float | None = None, beat=None) -> dict | None:
    """The steward's daily area-notes check (1.53.0): its counts for the heartbeat, or None (nothing said).

    Modelled on `_watch_prune`'s throttle: called after the watch's first heartbeat, only for the project the
    working directory is in AND whose console this is, at most once per NOTES_EVERY (the time kept in STATE; in
    between, and from any other working directory, it hands back the last counts: 1.53 review C5). `beat` runs
    while each git call waits, so "listening" never lapses. A project whose `.overture.json` declares no areas is left alone, silently. Any error is said once, on
    stderr, and never stops the watch: the time is recorded either way, so it is tried again the next day.
    """
    import time as _time
    from overture import notes as NO
    t = _time.time() if now is None else now
    rec = _notes_record(state)
    if rec and 0 <= t - rec["at"] < NOTES_EVERY:
        return rec["counts"]
    counts = None
    try:
        cwd = Path.cwd()
        here = R.enclosing(cwd) or _enclosing_via_worktree(cwd)
        if not here or os.path.realpath(here[1].get("state", "")) != os.path.realpath(state):
            return (rec or {}).get("counts")   # 1.53 review C5 (N1: no record yet on a first watch): not this console's project; keep the counts the beat holds
        root = Path(here[0])
        if "areas" in _json_or_empty(root / NO.CONFIG):
            counts = NO.counts(NO.check(root, tick=beat))
    except Exception as e:  # noqa: BLE001 - a broken check (git, a bug) never costs the owner the steward's watch
        print(f"notes check skipped: {e}", file=sys.stderr)
    _write_notes_record(state, {"at": t, "counts": counts})
    return counts


def _json_or_empty(p: Path) -> dict:
    """A small JSON object file, or {} when it is absent or is not one (the check itself names a bad file)."""
    try:
        data = R.read_regular(p, 64 * 1024, nofollow=True)
        doc = json.loads(data.decode("utf-8")) if data is not None else {}
    except (OSError, ValueError, RecursionError, R.RegistryError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _notes(a) -> int:
    """`notes check [--root DIR] [--memory DIR] [--json]` / `notes stamp AREA [--root DIR]` (1.53.0).

    Exit 0, 1 a finding, 2 refused. `check` never writes; `stamp` is its own verb (1.53 review C4).
    """
    from overture import notes as NO
    try:
        root = a.root if a.root is not None else NO.top_of(Path.cwd())
        if a.notes_cmd == "stamp":
            got = NO.stamp(root, a.area)
            print(f"{got['note']}: checked {got['was']} -> {got['checked']}")
            return 0
        res = NO.check(root, memory=a.memory)
    except NO.NotesError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    if a.json:
        sys.stdout.write(_json(res))
    else:
        print("\n".join(NO.lines(res)))
    return 0 if res["ok"] else 1


def _costs(a) -> int:
    """`costs collect` / `costs show --fork ID` (K2). Reads transcripts here, in the session; the server never does."""
    from overture import costs as C
    if a.action == "show" and not a.fork:
        print("costs show needs --fork RECORD_ID", file=sys.stderr)
        return 1
    if a.action == "collect":
        why = steward_refusal(a.state, a.agent, "`costs collect`")   # §8.5: the steward runs it
        if why:
            print(why, file=sys.stderr)
            return 1
    try:
        if a.action == "show":
            rows, bad = C.read_counted(a.state)
            out = C.fork_card(rows, a.fork)
        else:
            lines, stats = C.collect(a.state, agent=a.agent)
            out = {**C.write(a.state, lines), **stats}
            bad = out["dropped_malformed"]
    except (C.CostError, R.RegistryError, OSError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    if bad:
        print(f"note: {bad} malformed line(s) in {a.state / C.FILE} were dropped", file=sys.stderr)
    sys.stdout.write(_json(out))
    return 0


def _items_push(a) -> int:
    """`items-push` (K3, Q24): the adapter runs in THIS process; the server receives its three results as data.

    Through the door the working directory chose (K4): the one server, with
    this project's token, or a console's own single server (STATE/agent.sock).
    Neither server ever runs the adapter itself.
    """
    from overture import fold as FO
    state = os.path.realpath(a.state)
    door = _door(a.state)
    found = R.enclosing(a.project)
    if found is None or found[1].get("state") != state:
        print(f"refused, nothing sent: {Path(a.project).resolve()} is not a project registered on the console at "
              f"{state}", file=sys.stderr)
        return 1
    root = Path(found[0])
    if door.project is None and not door.sock.is_socket():   # before the adapter runs: nothing for no server
        print(f"no console server answers for {state}: no {door.sock}, and server.json hosts no project there; "
              f"nothing was sent", file=sys.stderr)
        return 2
    try:
        adapter = FO.load_adapter(FO.inside(root, a.adapter, "--adapter"))
        board = getattr(adapter, "board", None)
        body = {"items": adapter.items(), "seed_questions": adapter.seed_questions(),
                "board": board() if callable(board) else None}
    except FO.FoldError as e:
        print(f"refused, nothing sent: {e}", file=sys.stderr)
        return 1
    try:
        code, out = door.request("POST", "/items", body, agent=a.agent)
    except OSError as e:
        print(f"the console server is not answering on {door.sock}: {e}; nothing was sent", file=sys.stderr)
        return 2
    if code != 200:
        print(f"refused ({code}): {out.get('error')}", file=sys.stderr)
        return 1
    sys.stdout.write(_json(out))
    # 0.9.13: --sync-dashboard DIR inserts a <details id="item-X" data-ck-item="X"> stub into the given
    # dashboard page for every item not already present, nested under its parent. Idempotent.
    if getattr(a, "sync_dashboard", None):
        _sync_dashboard_write(root, a.sync_dashboard, body["items"])
    return 0


def _portfolio(a) -> int:
    """0.13.0: cross-project overview, read from each project's STATE directory, no HTTP.

    Scans the registry (`~/.config/overture/projects.json`), opens each state's `store.jsonl` and
    `items.json` directly, and tallies open-question backlog + last-locked-at per project. One line per
    project; `--json` emits a list of dicts for programmatic use.
    """
    from overture.store import Store
    from overture import items as IT
    from overture import registry as R
    import datetime as _dt
    import json as _json

    try:
        found = R.load()
    except R.RegistryError as e:
        print(f"portfolio: {e}", file=sys.stderr)
        return 1
    if not found:
        print("portfolio: no projects are registered (`agent.py register`).")
        return 0

    rows: list[dict] = []
    for project_root, entry in sorted(found.items()):
        state = entry.get("state", "")
        row: dict = {"project": project_root, "state": state,
                     "awaiting_you": 0, "unlocked": 0, "locked": 0, "visuals_waiting": 0,
                     "last_locked_at": None, "error": None}
        try:
            store = Store(Path(state) / "store.jsonl") if (Path(state) / "store.jsonl").exists() else None
            items_doc = IT.SnapshotAdapter(Path(state), tolerant=True)
            known = items_doc.items()
            row["items"] = len(known)
            if store is None:
                row["error"] = "no store.jsonl"
                rows.append(row); continue
            # Count: a locked question has a lock on its latest answer.
            # unlocked = has answer, no lock. awaiting_you = question, no answer.
            records = store.records()
            answers_by_qid: dict[str, dict] = {}
            questions: dict[str, dict] = {}
            locked_at: dict[str, str] = {}
            visual_requests: set[str] = set()
            visual_drawn_for: set[str] = set()
            for r in records:
                t = r.get("type")
                if t == "question":
                    questions[r["qid"]] = r
                elif t == "answer":
                    # keep the latest answer per qid
                    cur = answers_by_qid.get(r["qid"])
                    if cur is None or r["seq"] > cur["seq"]:
                        answers_by_qid[r["qid"]] = r
                elif t == "lock":
                    locked_at[r["qid"]] = r.get("ts", "")
                elif t == "message" and r.get("intent") == "visual" and r.get("by") == "owner":
                    visual_requests.add(r["id"])
                elif t == "visual":
                    req = r.get("request")
                    if req:
                        visual_drawn_for.add(req)
            for qid, q in questions.items():
                if qid in locked_at:
                    row["locked"] += 1
                elif qid in answers_by_qid:
                    row["unlocked"] += 1
                else:
                    row["awaiting_you"] += 1
            row["visuals_waiting"] = len(visual_requests - visual_drawn_for)
            if locked_at:
                row["last_locked_at"] = max(locked_at.values())
        except Exception as e:  # noqa: BLE001 — never break the whole portfolio over one bad project
            row["error"] = f"{type(e).__name__}: {e}"
        rows.append(row)

    if a.json:
        print(_json.dumps(rows, indent=2))
        return 0

    # Compact table.
    def _rel(ts: str | None) -> str:
        if not ts:
            return "—"
        try:
            when = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return ts
        delta = _dt.datetime.now(when.tzinfo) - when
        s = int(delta.total_seconds())
        if s < 3600: return f"{s // 60}m ago"
        if s < 86400: return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"

    print(f"{'Project':<40} {'Items':>5} {'?You':>5} {'~Unl':>5} {'oLock':>5} {'◫Vis':>5} {'LastLock':<12}")
    print("-" * 80)
    for r in rows:
        proj = r["project"] if len(r["project"]) <= 40 else "…" + r["project"][-39:]
        if r["error"]:
            print(f"{proj:<40}  (error: {r['error']})")
            continue
        print(f"{proj:<40} {r.get('items', 0):>5} {r['awaiting_you']:>5} "
              f"{r['unlocked']:>5} {r['locked']:>5} {r['visuals_waiting']:>5} {_rel(r['last_locked_at']):<12}")
    return 0


def _sync_dashboard(a) -> int:
    """0.9.13: insert a stub section into the dashboard page for every item not already there."""
    from overture import fold as FO
    state = os.path.realpath(a.state)
    found = R.enclosing(a.project)
    if found is None or found[1].get("state") != state:
        print(f"refused: {Path(a.project).resolve()} is not a project registered on the console at {state}",
              file=sys.stderr)
        return 1
    root = Path(found[0])
    try:
        adapter = FO.load_adapter(FO.inside(root, a.adapter, "--adapter"))
        items = adapter.items()
    except FO.FoldError as e:
        print(f"refused, nothing written: {e}", file=sys.stderr)
        return 1
    return _sync_dashboard_write(root, a.page, items)


def _sync_dashboard_write(root: Path, page_rel: str, items: dict) -> int:
    """Shared write-step for `sync-dashboard` and `items-push --sync-dashboard`."""
    from overture import scaffold as SC
    page = (Path(root) / page_rel).resolve()
    if Path(root).resolve() not in page.parents:
        print(f"refused: {page} is not inside {root}", file=sys.stderr)
        return 1
    try:
        before = page.read_text(encoding="utf-8") if page.exists() else ""
    except OSError as e:
        print(f"refused: cannot read {page}: {e}", file=sys.stderr)
        return 1
    after, added = SC.sync_items_block(before or "<!doctype html>\n<html><body>\n</body></html>\n", items)
    if not added and before:
        print("sync-dashboard: every item already on the page; nothing changed.")
        return 0
    try:
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(after, encoding="utf-8")
    except OSError as e:
        print(f"refused: cannot write {page}: {e}", file=sys.stderr)
        return 1
    print(f"sync-dashboard: {len(added)} item{'' if len(added) == 1 else 's'} inserted into "
          f"{page.relative_to(Path(root)).as_posix()}:")
    for i in added:
        print(f"  + {i}")
    print()
    print("Next: review the diff, `git commit`, then `agent.py page-snapshot --path "
          f"{Path(page_rel).as_posix()}` and press 'Use this page' in the console.")
    return 0


def _item_move(a) -> int:
    """1.17.0: record a re-parent intent on an item via the agent socket (owner-privileged).

    The item move is written as a `message` with intent "move" to the item's thread; the project's
    adapter stays the source of truth for parent relations. The move surfaces in the Feed and the
    item's thread until items() catches up.
    """
    import time as _t
    door = _door(a.state)
    if door.project is None and not door.sock.is_socket():
        print(f"no console server answers for {a.state}: no {door.sock}, and server.json hosts no project "
              f"there", file=sys.stderr)
        return 2
    parent = None if a.to_root else a.to
    body = {"item": a.item, "parent": parent, "nonce": f"move-{a.item}-{int(_t.time())}"}
    if a.text:
        body["text"] = a.text
    try:
        code, out = door.request("POST", "/item-move", body, agent=a.agent)
    except OSError as e:
        print(f"the console server is not answering on {door.sock}: {e}", file=sys.stderr)
        return 2
    if code != 200:
        print(f"refused ({code}): {out.get('error')}", file=sys.stderr)
        return 1
    sys.stdout.write(_json(out))
    return 0


def _playbook_run(a) -> int:
    """0.18.0, 1.47 (U7, owner): a playbook's steps are the owner's (every intent is owner-only since 1.30.1), so
    a session cannot run one. Say so before anything runs (no request reaches the server) and exit non-zero;
    through 1.46 this sent each step into a refusal and printed `{records: [], skipped: [...]}`."""
    print(f"not run: {a.name}: {PB.OWNER_ONLY}", file=sys.stderr)
    return 1


REVIEWED_FALLBACK = "origin/main"   # Q28: used when origin/HEAD does not resolve
GIT_SECONDS = 60


def _scaffold_dashboard(a) -> int:
    """0.9.3: write a dashboard page and inject board() into the project's adapter.

    Idempotent. The page is wrapped in `scaffold:<name> start/end` markers so re-running adds missing
    sections without clobbering hand edits; `board()` is only added when it is absent.
    """
    from overture import scaffold as SC
    try:
        plan = SC.prepare(a.project, a.page, a.adapter,
                          a.project_name_display or Path(a.project).resolve().name)
        touched = SC.apply(plan)
    except SC.ScaffoldError as e:
        print(f"refused, nothing written: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    if not touched:
        print("scaffold: already in place; nothing to write.")
        return 0
    for line in touched:
        print(line)
    print()
    print("Next:")
    print("  1. Review the page and the adapter; both are yours to edit.")
    print(f"  2. Commit so page-snapshot can read it: `git add -A && git commit -m 'scaffold dashboard'`.")
    print(f"  3. python3 agent.py --state <STATE> page-snapshot --path {Path(a.page).as_posix()}")
    print("     then press 'Use this page' in the console.")
    print(f"  4. python3 agent.py --state <STATE> items-push --adapter {Path(a.adapter).as_posix()}")
    print("  5. (Optional) keep the values fresh:")
    print(f"     python3 agent.py --state <STATE> items-watch --adapter {Path(a.adapter).as_posix()}")
    return 0


def _items_watch(a) -> int:
    """0.9.3: poll the project's items + adapter and re-run items-push whenever anything changes.

    Watches `--adapter`, `.overture/items.json`, `.overture.json`, and any extra paths named by
    `--watch` (comma-separated, project-relative). An initial push runs at startup; subsequent pushes
    fire when any file's (mtime, size) fingerprint changes. Ctrl+C exits cleanly. No file-watcher
    dependency: a plain stat loop at `--interval` seconds (default 5).
    """
    import time
    import argparse as _ap
    root = Path(a.project).resolve()
    adapter_rel = Path(a.adapter).as_posix()
    adapter_abs = (root / a.adapter).resolve() if not Path(a.adapter).is_absolute() else Path(a.adapter)

    paths: list[Path] = [adapter_abs]
    for rel in (".overture/items.json", ".overture.json"):
        paths.append((root / rel).resolve())
    for extra in (a.watch or "").split(","):
        extra = extra.strip()
        if extra:
            paths.append((root / extra).resolve() if not Path(extra).is_absolute() else Path(extra))

    def fingerprint() -> dict[str, tuple[float, int] | None]:
        out: dict[str, tuple[float, int] | None] = {}
        for p in paths:
            try:
                st = p.stat()
                out[str(p)] = (st.st_mtime, st.st_size)
            except FileNotFoundError:
                out[str(p)] = None
        return out

    print(f"items-watch: {len(paths)} path(s) under {root}, every {a.interval:g}s")
    for p in paths:
        print(f"  {p}")
    print()
    seen: dict[str, tuple[float, int] | None] = {}
    interval = max(1.0, min(300.0, float(a.interval)))
    try:
        while True:
            fp = fingerprint()
            if fp != seen:
                # Build a Namespace with the same fields _items_push reads; keep agent name through.
                ns = _ap.Namespace(state=a.state, project=root, adapter=adapter_rel, agent=a.agent)
                rc = _items_push(ns)
                if rc != 0:
                    print(f"items-watch: push failed (rc={rc}); will retry on the next change",
                          file=sys.stderr)
                seen = fp
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nitems-watch: stopped")
        return 0


def _resolve_reviewed(root: Path) -> str:
    """0.9.1: the remote's default branch, e.g. `origin/main` or `origin/dev`.

    Reads `git symbolic-ref --short refs/remotes/origin/HEAD`, so a project whose default branch is not
    `main` (`claude/foo-bar`, `dev`, `trunk`, ...) still has a working `page-snapshot` default. Falls back
    to `origin/main` when the symbolic ref is absent — the owner then needs to pass `--from-ref` or run
    `git remote set-head origin --auto` once.
    """
    out = G.run(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], root, timeout=GIT_SECONDS, text=True)
    if out:
        s = out.strip()
        if s:
            return s
    return REVIEWED_FALLBACK


def _page_snapshot(a) -> int:
    """`page-snapshot` (Q28): the page read from a COMMIT here, never from the working tree; sent as data.

    The server stores what it is given and never runs git. So the guard is
    here: the commit must be an ancestor of origin's default branch (reviewed
    and merged) unless `--unreviewed` says otherwise, and then the footer says
    so. The default is read from `origin/HEAD` (0.9.1), so a project whose
    default branch is `claude/foo-bar` or `dev` works without `--from-ref`.
    The page is the blob at `--path` in that commit, a plain file (never a
    link), read with `git cat-file`; an edit in the working tree never
    reaches it.
    """
    import base64
    from overture import pagesnap as PS
    from overture import serverfile as SF

    def refuse(why: str, rc: int = 1) -> int:
        print(f"refused, nothing sent: {why}", file=sys.stderr)
        return rc

    state = os.path.realpath(a.state)
    found = R.enclosing(a.project)
    if found is None or found[1].get("state") != state:
        return refuse(f"{Path(a.project).resolve()} is not a project registered on the console at {state}")
    root = Path(found[0])
    door = _door(a.state)
    if door.project is None and not door.sock.is_socket():
        return refuse(f"no console server answers for {state}: no {door.sock}, and server.json hosts no project "
                      f"there", 2)
    path = a.path
    if path is None and door.project is not None:   # the one server: server.json's page is the default
        path = SF.load()["projects"].get(door.project, {}).get("page")
    if path is None:
        return refuse("pass --path, the page's path in the repository (e.g. docs/dashboard/index.html)")
    why = SF._page_problem(path)
    if why:
        return refuse(why)
    reviewed = _resolve_reviewed(root)   # 0.9.1: origin's default branch, not hard-coded
    from_ref = a.from_ref or reviewed
    if not PS.REF.match(from_ref):
        return refuse(f"--from-ref {from_ref!r}: a ref of plain characters, such as origin/main or a tag")
    out = G.run(["rev-parse", "--verify", "--quiet", f"{from_ref}^{{commit}}"], root, timeout=GIT_SECONDS,
                text=True)
    if not out:
        return refuse(f"{from_ref} names no commit in {root}; for {reviewed}, run `git fetch` first")
    commit = out.strip()
    if not a.unreviewed:
        if not G.run(["rev-parse", "--verify", "--quiet", f"{reviewed}^{{commit}}"], root, timeout=GIT_SECONDS):
            return refuse(f"{reviewed} is not in {root}: run `git fetch`, or pass --unreviewed to send a page "
                          f"nobody reviewed (the footer will say so)")
        if G.run(["merge-base", "--is-ancestor", commit, reviewed], root, timeout=GIT_SECONDS) is None:
            return refuse(f"{from_ref} @ {commit[:12]} is not in {reviewed}, so it was not reviewed and merged. "
                          f"Merge it first, or pass --unreviewed (the footer will say \"unreviewed ref\")")
    a.from_ref = from_ref   # the body echoes it below; keep it consistent after the default resolved
    entry = G.run(["ls-tree", "-z", commit, "--", path], root, timeout=GIT_SECONDS)
    head, _, name = (entry or b"").rstrip(b"\0").partition(b"\t")
    fields = head.split()
    if name.decode("utf-8", "replace") != path or len(fields) != 3 or fields[1] != b"blob" \
            or fields[0] not in (b"100644", b"100755"):
        return refuse(f"{path} is not a plain file at {a.from_ref} @ {commit[:12]} (absent, a link or a folder)")
    raw = G.run(["cat-file", "blob", fields[2].decode("ascii")], root, timeout=GIT_SECONDS)
    if raw is None:
        return refuse(f"git could not read {path} at {commit[:12]}")
    body = {"content": base64.b64encode(raw).decode("ascii"), "ref": a.from_ref, "commit": commit, "path": path,
            "reviewed": not a.unreviewed}
    why = PS.snapshot_problem(body)   # the server's own check, here first, so a bad page is named before sending
    if why:
        return refuse(why)
    try:
        code, out = door.request("POST", "/page-snapshot", body, agent=a.agent)
    except OSError as e:
        return refuse(f"the console server is not answering on {door.sock}: {e}", 2)
    if code != 200:
        print(f"refused ({code}): {out.get('error')}", file=sys.stderr)
        return 1
    sys.stdout.write(_json(out))
    # Q29: staged only. Nothing served changes until the owner presses the button; no agent can.
    print(f"staged {commit[:12]}: the console shows it as a proposal; it is served once the owner presses "
          f"\"{PS.USE}\"", file=sys.stderr)
    return 0


def _history_push(a) -> int:
    """`history-push` (Q23 part 2): git runs HERE; the server gets past versions and spec times as data."""
    from overture import stewardgit as SG
    state = os.path.realpath(a.state)
    found = R.enclosing(a.project)
    if found is None or found[1].get("state") != state:
        print(f"refused, nothing sent: {Path(a.project).resolve()} is not a project registered on the console at "
              f"{state}", file=sys.stderr)
        return 1
    root = Path(found[0])
    # The door the working directory chose (K4): this console's own socket, or the one server with its token.
    door = _door(a.state)
    try:
        code, want = door.request("GET", "/history-wants", None, agent=a.agent)
        if code != 200:
            print(f"refused ({code}): {want.get('error')}", file=sys.stderr)
            return 1
        blobs, specs = SG.collect(root, want)
        refused = []
        for b in blobs:
            code, out = door.request("POST", "/history-blob", b, agent=a.agent)
            if code != 200:
                refused.append(f"{b['sha256'][:12]}: {out.get('error')}")
        code, out = door.request("POST", "/history-specs", {"specs": specs}, agent=a.agent)
        if code != 200:
            refused.append(f"spec times: {out.get('error')}")
    except OSError as e:
        print(f"the console server is not answering on {door.sock}: {e}", file=sys.stderr)
        return 2
    asked = len(want.get("blobs") or [])
    sys.stdout.write(_json({"blobs": {"asked": asked, "sent": len(blobs) - len(refused), "not_in_history":
                                      asked - len(blobs)},
                            "specs": out if code == 200 else None, "refused": refused}))
    for r in refused:
        print(f"refused: {r}", file=sys.stderr)
    return 1 if refused else 0


def _with_trust(root: Path, body: dict, key: str, kind: str) -> dict:
    """1.58 (T1): `body` with each PR's or issue's GitHub author association, from one `gh api graphql` call.

    `gh pr list` and `gh issue list` cannot give it. A lookup that fails, in whole or in part, is named
    on stderr and the push goes on: a row with no association shows as an outside author, never trusted.
    """
    from overture import trust as T
    numbers = [r["number"] for r in body[key]]
    if not numbers:
        return body
    out = G.gh(T.gh_query(body["repo"], kind, numbers), root)
    found: dict[int, str] = {}
    if isinstance(out, G.Unavailable):
        why = f"gh is {out.reason}"
    else:
        rc, stdout, stderr = out   # GraphQL answers what it can and exits 1 for the rest: read stdout anyway
        try:
            found = T.from_gh(json.loads(stdout), numbers)
            why = None
        except ValueError:
            why = f"`gh api graphql` failed ({rc}): {stderr.strip()[:300] or 'no message'}"
    if why or len(found) < len(numbers):
        print(f"warning: GitHub gave no author association for {len(numbers) - len(found)} of {len(numbers)}"
              f"{f' ({why})' if why else ''}; their backlinks show as from outside authors", file=sys.stderr)
    return T.with_associations(body, key, found)


def _prs_push(a) -> int:
    """`prs-push`: gh runs HERE, in the steward's process; the server gets the pull requests as data.

    Open pull requests, plus those merged or closed in the last `--days`, at
    most `--limit` of each, for the GitHub repository of the checkout this
    runs in. The server checks the same closed schema again; it never talks to
    GitHub and starts no process.
    """
    from overture import prs as PR

    def refuse(why: str, rc: int = 1) -> int:
        print(f"refused, nothing sent: {why}", file=sys.stderr)
        return rc

    state = os.path.realpath(a.state)
    found = R.enclosing(a.project)
    if found is None or found[1].get("state") != state:
        return refuse(f"{Path(a.project).resolve()} is not a project registered on the console at {state}")
    root = Path(found[0])
    if not 1 <= a.days <= PR.MAX_DAYS:
        return refuse(f"--days is a whole number from 1 to {PR.MAX_DAYS}")
    if not 1 <= a.limit <= PR.MAX_LIMIT:
        return refuse(f"--limit is a whole number from 1 to {PR.MAX_LIMIT}")
    door = _door(a.state)
    if door.project is None and not door.sock.is_socket():
        return refuse(f"no console server answers for {state}: no {door.sock}, and server.json hosts no project "
                      f"there", 2)
    got = []
    for args in PR.gh_lists(a.days, a.limit):
        out = G.gh(args, root)
        if isinstance(out, G.Unavailable):   # never in this process: the seam closes only in the server
            return refuse(f"gh is {out.reason}")
        rc, stdout, stderr = out
        if rc != 0:
            return refuse(f"`gh {' '.join(args[:3])}` failed ({rc}): {stderr.strip()[:500] or 'no message'}")
        try:
            got.append(json.loads(stdout))
        except ValueError as e:
            return refuse(f"`gh {' '.join(args[:3])}` did not print JSON: {e}")
    try:
        body = PR.from_gh(got[0], got[1], got[2], a.days)
    except PR.PushError as e:
        return refuse(str(e))
    body = _with_trust(root, body, "prs", "pr")
    why = PR.snapshot_problem(body)   # the server's own check, here first, so a bad push is named before sending
    if why:
        return refuse(why)
    try:
        code, out = door.request("POST", "/prs", body, agent=a.agent)
    except OSError as e:
        return refuse(f"the console server is not answering on {door.sock}: {e}", 2)
    if code != 200:
        print(f"refused ({code}): {out.get('error')}", file=sys.stderr)
        return 1
    sys.stdout.write(_json(out))
    return 0


def _pr_merge(a) -> int:
    """`pr-merge`: merge the pull request the owner asked for from the PR tab (1.33, D7), with THIS process's gh.

    Re-reads the PR from GitHub now, refuses by name when it is not open, ready, passing and still at the
    commit the owner saw (or the request is over 24 hours old), merges with `--match-head-commit`, and replies
    on @prs either way. `--dry-run` checks and prints, merges and replies to nothing. 0 merged (or dry run ok);
    1 refused (and the reply says why); 2 the server cannot be reached.
    """
    import datetime as dt
    from overture import prs as PR
    from overture import schema as S
    state = os.path.realpath(a.state)
    found = R.enclosing(a.project)
    if found is None or found[1].get("state") != state:
        print(f"refused: {Path(a.project).resolve()} is not a project registered on the console at {state}", file=sys.stderr)
        return 1
    root = Path(found[0])
    try:
        code, view = _req(state, "GET", "/view", None, agent=a.agent)
    except OSError as e:
        print(f"cannot reach the console server at {_where(state)}: {e}", file=sys.stderr)
        return 2
    if code != 200:
        print(f"refused: {view.get('error', view)}", file=sys.stderr)
        return 1
    msgs = (view.get("view") or view).get("threads", {}).get(S.PRS_ITEM, [])
    req = next((m for m in msgs if m["id"] == a.request), None)
    if req is None or req["by"] != "owner" or req.get("intent") != "pr-merge":
        print(f"refused: {a.request} is not an owner pr-merge request on {S.PRS_ITEM}", file=sys.stderr)
        return 1
    if any(m["by"] == "agent" and m.get("reply_to") == req["id"] for m in msgs):
        print(f"refused: {a.request} already has an answer", file=sys.stderr)
        return 1

    def reply(text: str) -> bool:
        if a.dry_run:
            return True
        try:
            code, out = _req(state, "POST", "/message", {"item": S.PRS_ITEM, "text": text[:2000], "reply_to": req["id"],
                                                          "nonce": secrets.token_urlsafe(12)}, agent=a.agent)
        except OSError as e:
            code, out = 0, {"error": str(e)}
        if code != 200:
            print(f"warning: the reply on {S.PRS_ITEM} was not stored ({out.get('error', code)}); say so to the "
                  f"owner, the request is still unanswered", file=sys.stderr)
        return code == 200

    def gh_json(args: list[str]):
        out = G.gh(args, root)
        if isinstance(out, G.Unavailable):
            return None, f"gh is {out.reason}"
        rc, stdout, stderr = out
        if rc != 0:
            return None, f"`gh {' '.join(args[:3])}` failed ({rc}): {stderr.strip()[:300] or 'no message'}"
        try:
            return json.loads(stdout), None
        except ValueError as e:
            return None, f"`gh {' '.join(args[:3])}` did not print JSON: {e}"

    def refuse(why: str) -> int:
        reply(why if why.startswith("Merge refused") else f"Merge refused: {why}. Nothing was merged")
        print(f"refused: {why}", file=sys.stderr)
        return 1

    repo_doc, why = gh_json(["repo", "view", "--json", "nameWithOwner"])
    if why:
        return refuse(why)
    repo = repo_doc.get("nameWithOwner") if isinstance(repo_doc, dict) else None
    if not isinstance(repo, str) or not PR.REPO.match(repo):
        return refuse("gh gave no repository name")
    row, why = gh_json(["pr", "view", str(req["pr"]), "--json", PR.GH_MERGE_FIELDS])
    if why:
        return refuse(why)
    why = PR.merge_problem(req, row, repo, dt.datetime.now(dt.timezone.utc))
    if why:
        return refuse(why)
    if a.dry_run:
        print(_json({"would_merge": req["pr"], "repo": repo, "head": req["expected_head_sha"], "method": a.method}))
        return 0
    out = G.gh(["pr", "merge", str(req["pr"]), f"--{a.method}", "--match-head-commit", req["expected_head_sha"]], root)
    if isinstance(out, G.Unavailable):
        return refuse(f"gh is {out.reason}")
    rc, _stdout, stderr = out
    if rc != 0:
        return refuse(f"gh refused the merge ({rc}): {stderr.strip()[:300] or 'no message'}")
    stored = reply(f"Merged #{req['pr']} \"{str(row.get('title'))[:120]}\" into {row.get('baseRefName')} "
                   f"({a.method}), head {req['expected_head_sha'][:8]}.")
    print(_json({"merged": req["pr"], "repo": repo, "method": a.method, "replied": stored}))
    return 0 if stored else 3


def _issues_push(a) -> int:
    """`issues-push`: mirror of `_prs_push` against gh issue list. See prs-push for the full contract."""
    from overture import issues as IS

    def refuse(why: str, rc: int = 1) -> int:
        print(f"refused, nothing sent: {why}", file=sys.stderr)
        return rc

    state = os.path.realpath(a.state)
    found = R.enclosing(a.project)
    if found is None or found[1].get("state") != state:
        return refuse(f"{Path(a.project).resolve()} is not a project registered on the console at {state}")
    root = Path(found[0])
    if not 1 <= a.days <= IS.MAX_DAYS:
        return refuse(f"--days is a whole number from 1 to {IS.MAX_DAYS}")
    if not 1 <= a.limit <= IS.MAX_LIMIT:
        return refuse(f"--limit is a whole number from 1 to {IS.MAX_LIMIT}")
    door = _door(a.state)
    if door.project is None and not door.sock.is_socket():
        return refuse(f"no console server answers for {state}: no {door.sock}, and server.json hosts no project "
                      f"there", 2)
    got = []
    for args in IS.gh_lists(a.days, a.limit):
        out = G.gh(args, root)
        if isinstance(out, G.Unavailable):
            return refuse(f"gh is {out.reason}")
        rc, stdout, stderr = out
        if rc != 0:
            return refuse(f"`gh {' '.join(args[:3])}` failed ({rc}): {stderr.strip()[:500] or 'no message'}")
        try:
            got.append(json.loads(stdout))
        except ValueError as e:
            return refuse(f"`gh {' '.join(args[:3])}` did not print JSON: {e}")
    try:
        body = IS.from_gh(got[0], got[1], got[2], a.days)
    except IS.PushError as e:
        return refuse(str(e))
    body = _with_trust(root, body, "issues", "issue")
    why = IS.snapshot_problem(body)
    if why:
        return refuse(why)
    try:
        code, out = door.request("POST", "/issues", body, agent=a.agent)
    except OSError as e:
        return refuse(f"the console server is not answering on {door.sock}: {e}", 2)
    if code != 200:
        print(f"refused ({code}): {out.get('error')}", file=sys.stderr)
        return 1
    sys.stdout.write(_json(out))
    return 0


def _lesson_match(a) -> int:
    """Check a question draft against the owner's recorded lessons (ask-side mirror of the
    chip the console surfaces to the owner).

    Reads STATE/lessons.jsonl, calls `lessons.match()` with the same algorithm the server uses
    for the owner card, and prints the top matches as Markdown so the posting agent can decide:
    rephrase, cite them in the ask, or go ahead. Exit 0 on any match, 1 when none — a script
    can gate on this (`agent.py lesson-match "..." --item X && echo clear`).
    """
    from overture import lessons as LN

    state = Path(os.path.realpath(a.state))
    try:
        rows = LN.load(state)
    except (LN.LessonError, OSError) as e:
        print(f"lesson-match: cannot read {state}/{LN.FILE}: {e}", file=sys.stderr)
        return 2
    matches = LN.match(a.text, a.item, rows, top_k=a.top, threshold=a.threshold)
    if not matches:
        print(f"No lessons match (checked {len(rows)} on item {a.item!r}; threshold {a.threshold}).")
        return 1
    print(f"# {len(matches)} related ruling(s) on item {a.item}")
    print()
    print("The owner has recorded a reason for the ruling(s) below. Read them before posting;")
    print("rephrase, cite, or let the owner decide. The console surfaces the same list on the")
    print("owner's card, so skipping this step does not hide them.")
    print()
    label = {"withdraw": "withdrawn", "untrack": "kept unchecked"}
    for m in matches:
        date = m["ts"][:10]
        klabel = label.get(m["kind"], m["kind"])
        print(f"## {date} — {m['qid']} ({klabel}, score {m['score']})")
        print()
        for line in LN.reason_lines(m["reason_preview"]):
            print("    " + line)
        print()
    return 0


def _lessons(a) -> int:
    """Print or fold the lessons recorded by withdraw/untrack rulings.

    `agent.py --state STATE lessons`                 → prints the Markdown to stdout
    `agent.py --state STATE lessons --fold PATH`     → writes PATH atomically from the stored jsonl

    No network, no store writes. Reads STATE/lessons.jsonl via the same atfile pattern the server
    writes it with. Owner-only in spirit; the agent socket is 0600 under a 0700 dir, so the OS
    user is the trust boundary. `--fold` writes the Markdown through atfile.write_at on an open
    descriptor on PATH's parent directory, so the write is O_EXCL + fsync + rename and refuses
    a symlink in PATH's place (a peer who plants `~/foo -> ~/.bashrc` would otherwise coax a
    session into overwriting it).
    """
    from overture import atfile as AF
    from overture import lessons as LN

    state = Path(os.path.realpath(a.state))
    try:
        rows = LN.load(state)
    except (LN.LessonError, OSError) as e:
        print(f"lessons: cannot read {state}/{LN.FILE}: {e}", file=sys.stderr)
        return 1
    md = LN.to_markdown(rows).encode("utf-8")
    if getattr(a, "fold", None):
        # Resolve only the parent: a symlink AT PATH must be replaced, never followed.
        target = Path(a.fold)
        parent = target.parent.resolve()
        name = target.name
        if not name or name in (".", ".."):
            print(f"lessons: --fold PATH must name a file; got {a.fold!r}", file=sys.stderr)
            return 1
        try:
            parent.mkdir(parents=True, exist_ok=True)
            dfd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_CLOEXEC)
        except OSError as e:
            print(f"lessons: cannot open parent {parent}: {e}", file=sys.stderr)
            return 1
        try:
            AF.write_at(dfd, name, md)
        except OSError as e:
            print(f"lessons: cannot write {parent / name}: {e}", file=sys.stderr)
            return 1
        finally:
            os.close(dfd)
        print(f"wrote {len(rows)} lesson(s) to {parent / name}")
        return 0
    sys.stdout.write(md.decode("utf-8"))
    return 0


def _refused_note(files: list, n: int, why: str | None, rc: int = 1) -> int:
    """A batch ask stopped at files[n]: say what was posted and what was not, so a re-run sends only the rest."""
    if why:
        print(why, file=sys.stderr)
    if len(files) > 1:
        print(f"posted {n} of {len(files)}; not sent: {' '.join(str(f) for f in files[n:])}", file=sys.stderr)
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", type=Path, help="the console's state folder (required by every command but `notes`)")
    ap.add_argument("--as", dest="agent", metavar="NAME",
                    help=f"this session's agent name, e.g. agent-6 (default: this session's /overture:as, "
                         f"then ${N.ENV}; none: unnamed, as in 0.8.1)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("inbox")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--since", type=int)
    g.add_argument("--all", action="store_true")
    s = sub.add_parser("watch")
    s.add_argument("--since", type=int)
    s.add_argument("--timeout", type=float)
    s.add_argument("--poll", type=float, default=2.0)
    s = sub.add_parser("todo", description="What is waiting on the agent: forks not done, threads and the chat "
                       "awaiting it, visual requests, the owner's inbox and the store seq (K1).")
    s.add_argument("--full", action="store_true", help=f"print it even when over {MAX_READ} bytes")
    s = sub.add_parser("view")
    s.add_argument("--item", metavar="ID", help="only this item and everything under it (@chat: the chat)")
    s.add_argument("--since", type=int, metavar="SEQ",
                   help="only what changed after this store seq: a question when any record on it (asked, "
                        "answered, locked, re-anchored) is newer, and every stale one, since staleness has no "
                        "seq; a question that became valid again with no new record is not shown")
    s.add_argument("--full", action="store_true", help=f"print it even when over {MAX_READ} bytes")
    sub.add_parser("health")
    s = sub.add_parser("answers")
    s.add_argument("--item")
    s.add_argument("--fork")
    s.add_argument("--json", action="store_true")
    s.add_argument("--since", type=int, metavar="SEQ",
                   help="only questions with a record (asked, answered, locked, re-anchored) after this store "
                        "seq, and every stale one; one that became valid again with no new record is not shown")
    s.add_argument("--full", action="store_true", help=f"print it even when over {MAX_READ} bytes")
    s = sub.add_parser("fork-context")
    s.add_argument("fork")
    s = sub.add_parser("check")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("rulings")   # 1.52.0: the owner's rulings on these paths, before an edit
    s.add_argument("--path", action="append", required=True, metavar="P",
                   help="a project-relative file, or a folder ending in /; repeat for more")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("notes", description="1.53.0 (owner M1-M4): `check` the repository's area notes (a short "
                       "CLAUDE.md in a folder `.overture.json` \"areas\" declares): stale since the commit each was "
                       "checked at, undeclared, or malformed; with --memory, the auto-memory index too. Reads git "
                       "here, never writes, needs no console. `stamp AREA` marks a re-read note checked at HEAD. "
                       "Exit 0 all current, 1 a finding, 2 refused.")
    ns = s.add_subparsers(dest="notes_cmd", required=True)
    s = ns.add_parser("check")
    s.add_argument("--root", type=Path, help="the top of the git checkout (default: the one the working directory is in)")
    s.add_argument("--memory", type=Path, metavar="DIR", help="also check DIR/MEMORY.md, the auto-memory index")
    s.add_argument("--json", action="store_true")
    s = ns.add_parser("stamp", description="after re-reading AREA, stamp its note as checked at HEAD: only the "
                      "note's first line changes; refused while AREA has uncommitted changes, or when its folder "
                      "or note is a symlink leading out of the checkout")
    s.add_argument("area", metavar="AREA", help="a folder `.overture.json` \"areas\" declares, e.g. docs")
    s.add_argument("--root", type=Path, help="the top of the git checkout (default: the one the working directory is in)")
    s = sub.add_parser("reanchor")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("reply")
    s.add_argument("item")
    s.add_argument("text")
    s.add_argument("--reply-to")
    s = sub.add_parser("ask")
    s.add_argument("files", type=Path, nargs="+", metavar="file")
    s = sub.add_parser("propose-anchor", description=(
        "PROPOSE a new anchor for a stale answer (CONSOLE-kit/Q31). Name the lines the ruling rests on; the "
        "server reads them now, each must be in its file exactly once, and nothing changes until the owner "
        "confirms the proposal on the console. To replace a stale ruling with a new question instead, `ask` it "
        "with \"replaces\": \"<qid>\" in the question file."))
    s.add_argument("qid")
    s.add_argument("--cite", action="append", metavar="PATH:FIRST-LAST",
                   help="lines the ruling rests on, read by the server; repeat for up to 4")
    s.add_argument("--symbol", action="append", metavar="PATH::NAME",
                   help="1.54: the definition the ruling's code moved to (path::Class.method), read by the server; "
                        "repeat for more, up to 4 with the cites")
    s.add_argument("--basis", required=True, help="why these lines carry the ruling now, shown to the owner")
    s = sub.add_parser("symbol-at", description=(
        "1.54 (owner K1): the definition that holds a question's source lines, as the `path::Class.method` "
        "condition `ask` takes in valid_if. Reads the file in this checkout; prints nothing to the console. "
        "Exit 1 when no single definition holds them (an excerpt is then the anchor), 2 for a bad source."))
    s.add_argument("source", metavar="PATH:FIRST-LAST", help="a question's source, e.g. src/pay.py:12-30")
    s.add_argument("--json", action="store_true", help="print the condition object instead of the short form")
    s = sub.add_parser("adapter", description=(
        "Wave 4 (owner V1-V4): the plugin's guardrails for other agent vendors. `install --vendor V` writes V's "
        "user-level hooks (the session-start note, the owner's rulings around an edit) and its MCP config; "
        "`uninstall` takes them out again; both leave everyone else's entries alone. They act only in projects "
        "registered here. `agents-md` writes the console's block into this project's AGENTS.md. You run these, "
        "never a session."))
    ads = s.add_subparsers(dest="ad_cmd", required=True)
    for name in ("install", "uninstall"):
        t = ads.add_parser(name)
        t.add_argument("--vendor", required=True, choices=("codex", "cursor", "copilot"))
        if name == "install":
            t.add_argument("--name", metavar="NAME", help="the agent name its MCP writes carry (default: the vendor)")
    t = ads.add_parser("agents-md")
    t.add_argument("--project", type=Path, default=Path("."), help="a registered checkout (default: here)")
    s = sub.add_parser("advise", description=(
        "Answer a scan for a resolve (CONSOLE-kit/Q40) with a star recommendation for one stale ruling: withdraw "
        "it or keep it, with the evidence. It changes nothing; the owner's own Withdraw or Keep does. Prefer "
        "`propose-anchor` when the ruling's premise moved to lines that still carry it, and `ask` with "
        "\"replaces\" when the question itself must be asked again."))
    s.add_argument("qid")
    s.add_argument("--star", required=True, choices=("withdraw", "keep"))
    s.add_argument("--evidence", required=True,
                   help="where the cited text went, whether the premise holds, and what replaced it")
    s = sub.add_parser("transcript")
    s.add_argument("fork")
    s.add_argument("file", type=Path)
    s = sub.add_parser("visual")
    s.add_argument("request")
    s.add_argument("--format", required=True, choices=("mermaid", "html"))
    s.add_argument("--file", type=Path, required=True)
    s.add_argument("--doc", type=Path, required=True)
    s.add_argument("--title", required=True)
    s = sub.add_parser("asset", description=(
        "Post a screenshot or recording on an item (1.32, FEED-ASSETS.md). PNG, JPEG, WebP or GIF, judged by "
        "the file's own bytes; at most 2 MiB for a still and 8 MiB for a GIF. It shows in the owner's Feed "
        "and on the item. Post a `before` and an `after` for every visible change to a UX item."))
    s.add_argument("item")
    s.add_argument("--file", type=Path, required=True)
    s.add_argument("--caption", required=True, help="one line, at most 200 characters")
    s.add_argument("--kind", default="screenshot", choices=("before", "after", "screenshot", "recording"))
    s.add_argument("--qid", help="the question it illustrates")
    s.add_argument("--pr", type=int, help="the pull request it shows (an asset linked to a PR is never pruned)")
    s.add_argument("--ticket", help="the ticket it shows")
    s = sub.add_parser("design-inventory", description=(
        "List the artifacts of the owner's Claude Design project for UX View's picker . Open the design the "
        "way you read it for a component (the owner's login), then send what is in it: FILE is JSON "
        "([{\"path\": \"buttons/primary.html\", \"title\": \"Primary button\"}, ...]) or one path per line. "
        "At most 300 artifacts; a new list replaces the last one for that link. The owner picks from it; the "
        "console never reads or opens the design."))
    s.add_argument("--url", required=True, help="the design link, https://claude.ai/design/p/<project id>")
    s.add_argument("--file", type=Path, required=True)
    s = sub.add_parser("component-source", description=(
        "Store the raw, scripted source of an HTML visual you already posted (1.33, UX-VIEW.md): the visual stays "
        "the sanitized, script-free version, and this is its progressive enhancement. Nothing runs it until the "
        "owner switches Scripts on for that version in UX View. Write-once per visual; see the console-ux skill's "
        "scripts.md for how to write it."))
    s.add_argument("--visual", required=True, metavar="ID", help="the HTML visual's record id")
    s.add_argument("--file", type=Path, required=True, help="the scripted HTML document")
    s = sub.add_parser("pr-merge", description=(
        "Merge the pull request the owner asked for from the PR tab (1.33, UX-VIEW.md D7), using YOUR gh in "
        "PROJECT's checkout. It re-reads the PR from GitHub, refuses (and replies on @prs saying why) unless it is "
        "open, not a draft, passing, still at the head commit the owner saw, and the request is under 24 hours "
        "old; then runs `gh pr merge --match-head-commit`. The console server merges nothing."))
    s.add_argument("--project", type=Path, required=True, help="a checkout of the repository, registered on the console")
    s.add_argument("--request", required=True, metavar="MESSAGE_ID", help="the owner's pr-merge message id (todo.merge)")
    s.add_argument("--method", default="squash", choices=("squash", "merge", "rebase"))
    s.add_argument("--dry-run", action="store_true", help="check and print; merge and reply to nothing")
    s = sub.add_parser("ux-export", description=(
        "Land the owner's ux-save (1.32, UX-VIEW.md): write components/<item>.md and components/<item>.css into "
        "PROJECT, the top of YOUR git worktree on a branch (never the server's checkout). A previous version is "
        "moved to components/.history/<item>-<hash>.md first; running it twice changes nothing. It writes files "
        "only: commit them and open the pull request yourself."))
    s.add_argument("--project", type=Path, required=True)
    s.add_argument("--save", required=True, metavar="MESSAGE_ID", help="the owner's ux-save message id (from todo.ux)")
    s = sub.add_parser("visual-export", description=(
        "Copy stored visuals into PROJECT/<visuals_dir>/ and regenerate its INDEX.md, to land by PR. PROJECT "
        "must be the top of your own git work tree (visuals_dir is a path from the repository's top), never a "
        "folder inside it and never the server's checkout. It exits 0 when every chosen visual was exported, "
        "exits 3 when files were written but at least one visual was refused (each refusal is named), exits 1 "
        "when nothing was written, and exits 2 when the server cannot be reached."))
    s.add_argument("--project", type=Path, required=True,
                   help="YOUR worktree: the TOP of a git work tree, never a folder inside it or the server's checkout")
    s.add_argument("--visual", action="append", default=[], metavar="ID",
                   help="a visual record id; repeat for more (default: every stored visual)")
    s = sub.add_parser("next-step")
    s.add_argument("kind", choices=("refine", "drill"))
    s.add_argument("--project", type=Path, required=True)
    s = sub.add_parser("working")
    s.add_argument("items", nargs="+", help="the item ids this session is now working on")
    s = sub.add_parser("worktree", description=(
        "1.50.0 (W1-W4): this agent's own worktree for a request that changes files, under "
        "~/.overture/worktrees/<project>/, made, listed and pruned HERE, in your process (the console server "
        "starts no git). `new` prints the path to work, commit, push and open the PR from."))
    ws = s.add_subparsers(dest="wt_cmd", required=True)
    w = ws.add_parser("new")
    w.add_argument("--item", required=True, help="the item id the work is for")
    w.add_argument("--kind", required=True, help="ticket, visual, ux, playbook, round or fix")
    w.add_argument("--project", type=Path, help="a checkout of the repository (default: the working directory)")
    w.add_argument("--json", action="store_true")
    w = ws.add_parser("list")
    w.add_argument("--project", type=Path)
    w.add_argument("--json", action="store_true")
    w = ws.add_parser("prune")
    w.add_argument("--project", type=Path)
    w.add_argument("--dry-run", action="store_true", help="say what would be removed; remove nothing")
    w.add_argument("--json", action="store_true")
    s = sub.add_parser("synced")
    s.add_argument("--through", type=int)
    s.add_argument("--rx-through", type=int, help="the highest `rx` among the scan lines processed (Q40)")
    s.add_argument("--error")
    s = sub.add_parser("register")
    s.add_argument("--project", type=Path, required=True)
    s.add_argument("--steward", metavar="NAME",
                   help="the one session that may watch, sync and fold this console (0.8.3; default: keep it)")
    s = sub.add_parser("role", description="Show or set what THIS machine is for (D11, 1.33): `worker` means no "
                       "session on this machine is ever the steward, whatever it is named; `steward` says the steward "
                       "runs here; `clear` removes it. Stored in your own registry; the plugin's Machine role setting "
                       "says the same thing to the hooks, and the stricter of the two holds.")
    s.add_argument("value", nargs="?", choices=("steward", "worker", "clear"))
    s = sub.add_parser("operator-name", description="Show, set or clear the short name a login's locks carry in the "
                       "committed ruling files (1.38). The console keeps each owner decision's Access email beside "
                       "its store; the email never leaves it, and an export names the login only by a name set "
                       "here. You run this, never a session.")
    s.add_argument("email", nargs="?", help="the Access login, e.g. you@example.com (none: list every name)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("short", nargs="?", metavar="NAME", help="the short name, e.g. michael")
    g.add_argument("--clear", action="store_true", help="remove this login's name: its locks are exported unnamed")
    s = sub.add_parser("notify-url", description="Show, set or clear the incoming webhook (Slack, Mattermost, or "
                       "Discord's /slack URL) the console posts its digest of waiting questions to (1.45). Whoever "
                       "holds the URL can post to that channel, so it is set here, never from the console or a "
                       "session; the console shows only its host. Turn notifications on, and set how often and the "
                       "quiet hours, under Settings. You run this, never a session.")
    g = s.add_mutually_exclusive_group()
    g.add_argument("url", nargs="?", help="the webhook URL, https://... (none: show its host)")
    g.add_argument("--clear", action="store_true", help="remove the webhook: nothing is sent")
    g.add_argument("--test", action="store_true", help="post one test message to the webhook now")
    s = sub.add_parser("access", description="Show, set or clear what an Access login may do in the console (1.39). "
                       "With no roles set, every login that passes Access is the owner. Once one is set, an unlisted "
                       "login only reads. owner: everything; member AREA...: answers, locks and plain messages on "
                       "those items and everything under them; viewer: reads only. Kept in STATE/roles.json, never "
                       "committed. You run this, never a session.")
    s.add_argument("email", nargs="?", help="the Access login, e.g. you@example.com (none: list every role)")
    s.add_argument("role", nargs="?", choices=RO.ROLES, help="the login's role")
    s.add_argument("areas", nargs="*", metavar="ITEM", help="a member's areas: item ids (a viewer may name some "
                   "too, for what its Inbox opens on)")
    s.add_argument("--clear", action="store_true", help="remove this login's role: it only reads, or, when it was "
                   "the last one listed, roles are off again")
    s.add_argument("--director", action="store_true", help="a member or viewer whose Inbox opens on everything "
                   "(1.41); it decides no more than its role allows")
    s = sub.add_parser("invite", description="Make a sign-in link for a console that runs with --auth link "
                       "(1.46): no Cloudflare. The link works once and lapses after 24 hours; the browser that "
                       "opens it stays signed in until revoked (People, or `agent.py devices --revoke`). Only its "
                       "hash is kept, so it is printed once, here. You run this, never a session.")
    s.add_argument("email", help="who the link signs in, e.g. bob@example.com; their role in this project decides "
                   "what they may do")
    s.add_argument("--origin", help="the console's address as the browser sees it, e.g. "
                   "https://box.tailnet.ts.net (default: from server.json, else the link's path only)")
    s = sub.add_parser("devices", description="List the browsers signed in by link on this machine (1.46), or "
                       "sign one out: its next request is refused. Revoking is yours, never a session's.")
    s.add_argument("--revoke", metavar="ID", help="the device id to sign out (12 hex digits, from the list)")
    s = sub.add_parser("steward", description="Show, set or clear this console's steward in your own registry "
                       "(0.8.3). You run this, never a session.")
    g = s.add_mutually_exclusive_group()
    g.add_argument("name", nargs="?", help="the steward's agent name, e.g. agent-5")
    g.add_argument("--clear", action="store_true", help="no steward: every session may watch, sync and fold")
    s = sub.add_parser("costs", description="The cost sidecar (K2): `collect` sums this project's subagent "
                       "transcripts into STATE/costs.jsonl; `show --fork ID` prints that fork's bill.")
    s.add_argument("action", choices=("collect", "show"))
    s.add_argument("--fork", help="show: the fork record id whose tagged subagents to total")
    s = sub.add_parser("items-push", description="Run this project's adapter HERE, in your own process, and send "
                       "its items, seed questions and board to the console server as data: the single server or "
                       "the one server that hosts this console (K3 §3.6, Q24). Neither server ever runs project "
                       "code. Run it after an upgrade, and whenever the register changes.")
    s.add_argument("--adapter", required=True, help="the adapter, a path inside the project")
    s.add_argument("--project", type=Path, default=Path.cwd(), help="the project root (default: here)")
    s.add_argument("--sync-dashboard", default=None, metavar="PAGE",
                   help="0.9.13: after a successful push, insert a <details data-ck-item=...> stub into PAGE "
                        "for every item not already there (idempotent, nested by parent). You still commit "
                        "and run page-snapshot yourself.")
    sub.add_parser("trigger-token", description="0.12.0: mint a fresh bearer token and its sha256 for a "
                   "trigger. Print the plaintext (for the sender) and the sha256 (for triggers.json).")
    sub.add_parser("portfolio-token", description="0.19.0: print the layout the operator uses to wire a "
                   "Cloudflare Access service token into .overture/portfolio.json + "
                   "STATE/portfolio-secrets/<peer>.json so the home console can fetch a peer's slim view.")
    s = sub.add_parser("portfolio", description="0.13.0: list every project registered on this machine with "
                       "its open-question backlog read from each STATE directly. Read-only; no HTTP calls.")
    s.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    s = sub.add_parser("playbook", description="0.18.0; 1.47 (U7): refuses, and says why. A playbook's steps are "
                       "the owner's, so playbooks run from the console's Playbooks tab, not from a session. "
                       "Nothing runs and the exit code is 1.")
    s.add_argument("name", help="the playbook's slug (file basename without .json)")
    s = sub.add_parser("item-move", description="1.17.0: record the owner's intent to re-parent an item. "
                       "Writes a `message` with intent 'move' to the item's thread; the project's adapter "
                       "stays the source of truth for parents, but the move is now in the Feed and the "
                       "item's thread until items() catches up.")
    s.add_argument("item", help="the item id to re-parent")
    moveto = s.add_mutually_exclusive_group(required=True)
    moveto.add_argument("--to", default=None, help="the target parent's item id")
    moveto.add_argument("--to-root", action="store_true", help="move to top level (no parent)")
    s.add_argument("--text", default=None, help="optional note; defaults to \"Move under <parent>\"")
    s = sub.add_parser("sync-dashboard", description="0.9.13: insert a <details id=item-X data-ck-item=X> stub "
                       "into the dashboard page for every item not already there. Nested by parent via per-item "
                       "markers so re-runs preserve hand-edits inside each node.")
    s.add_argument("--adapter", default=".overture/adapter.py", help="the adapter, a path inside the project")
    s.add_argument("--page", default="docs/console/page.html",
                   help="the dashboard page to update (project-relative)")
    s.add_argument("--project", type=Path, default=Path.cwd(), help="the project root (default: here)")
    s = sub.add_parser("items-watch", description="0.9.3: watch the project's adapter and items files and re-run "
                       "items-push whenever any of them changes. A plain stat loop (no file-watcher dependency); "
                       "Ctrl+C exits cleanly. Pair with the scaffolded board() to keep the dashboard fresh.")
    s.add_argument("--adapter", required=True, help="the adapter, a path inside the project")
    s.add_argument("--project", type=Path, default=Path.cwd(), help="the project root (default: here)")
    s.add_argument("--interval", type=float, default=5.0, help="poll seconds (default: 5; clamped to 1..300)")
    s.add_argument("--watch", default="", help="comma-separated project-relative paths to watch in addition to the "
                   "adapter, .overture/items.json and .overture.json")
    s = sub.add_parser("scaffold-dashboard", description="0.9.3: write a dashboard page with Items / Rollout / "
                       "Engine / Spec / Footer sections and inject a matching board() into the project's adapter. "
                       "Idempotent: re-run adds missing sections without clobbering hand edits.")
    s.add_argument("--adapter", default=".overture/adapter.py",
                   help="the adapter, a path inside the project (default: .overture/adapter.py)")
    s.add_argument("--page", default="docs/console/page.html",
                   help="where to write the dashboard page (default: docs/console/page.html)")
    s.add_argument("--project", type=Path, default=Path.cwd(), help="the project root (default: here)")
    # The dest avoids the shared `a.name` validator in the main entry (which treats `name` as an
    # agent name shape). The flag spelling stays `--project-name`; `--name` is kept as a hidden
    # alias so older scripts still work, but a value with spaces or capitals no longer refuses.
    s.add_argument("--project-name", "--name", dest="project_name_display", default=None,
                   help="the project name shown in the header (default: the directory name). "
                        "Any string you'd put in an <h1>; not an agent name.")
    s = sub.add_parser("page-snapshot", description="Read the console's page from a COMMIT here (git cat-file, "
                       "never the working tree) and send it to the console server, which serves only that "
                       "snapshot (CONSOLE-kit/Q28). Refuses a commit that is not in origin's default branch "
                       "unless --unreviewed. Run it after an upgrade, and whenever the page's merged "
                       "version changes.")
    s.add_argument("--from-ref", default=None, help="the ref to read the page from (default: origin/HEAD, "
                   "the remote's default branch after a `git fetch` you run; origin/main is the fallback)")
    s.add_argument("--path", default=None, help="the page's path in the repository (default on the one server: "
                   "the project's page in server.json)")
    s.add_argument("--unreviewed", action="store_true", help="send a commit that is not in origin's default "
                   "branch; the footer says \"unreviewed ref\" instead of \"from the steward\"")
    s.add_argument("--project", type=Path, default=Path.cwd(), help="the project root (default: here)")
    s = sub.add_parser("history-push", description="Read git HERE, in your own process, for what the console "
                       "server asks (the version each stale lock was taken against, the cited specs' last-commit "
                       "times) and send it as data. The server starts no git (CONSOLE-kit/Q23).")
    s.add_argument("--project", type=Path, default=Path.cwd(), help="the project root (default: here)")
    s = sub.add_parser("prs-push", description="Run `gh pr list` HERE, in your own process, for the GitHub "
                       "repository of this checkout, and send the console server its open pull requests and those "
                       "merged or closed in the last --days, as data. The server never talks to GitHub and starts "
                       "no process. Run it after an upgrade, and whenever you want the PRs view fresh.")
    s.add_argument("--project", type=Path, default=Path.cwd(), help="the project root (default: here)")
    s.add_argument("--days", type=int, default=30, help="merged and closed PRs from this many days back "
                   "(default: 30, at most 365)")
    s.add_argument("--limit", type=int, default=50, help="at most this many open PRs, and as many merged or "
                   "closed ones (default: 50, at most 100)")
    s = sub.add_parser("issues-push", description="Run `gh issue list` HERE, in your own process, for the GitHub "
                       "repository of this checkout, and send the console server its open issues and those closed "
                       "in the last --days, as data. The server never talks to GitHub (1.27.0, mirrors prs-push).")
    s.add_argument("--project", type=Path, default=Path.cwd(), help="the project root (default: here)")
    s.add_argument("--days", type=int, default=30, help="closed issues from this many days back "
                   "(default: 30, at most 365)")
    s.add_argument("--limit", type=int, default=50, help="at most this many open issues, and as many closed "
                   "ones (default: 50, at most 100)")
    s = sub.add_parser("lessons", description="Print the lessons recorded from withdrawn and kept-unchecked "
                       "rulings as Markdown. --fold PATH writes PATH atomically; the SessionStart hook of every "
                       "machine then reads the file from the commit.")
    s.add_argument("--fold", metavar="PATH", help="write to PATH instead of stdout (atomic). Commit the file so "
                   "every machine's agents read it on session start.")
    s = sub.add_parser("lesson-match", description="Check a question draft against the owner's recorded lessons "
                       "BEFORE posting it. Prints any past withdrawn/untracked rulings on the same item whose "
                       "text looks similar (trigram Jaccard; 1.34), so an agent can rephrase or cite them in "
                       "the ask rather than invite the owner to re-litigate the same ground. Exit 0 when matches "
                       "exist, 1 when none; the console always surfaces the same matches on the owner's card, "
                       "so skipping this step still gives the owner the chip — this is the ASK-side mirror.")
    s.add_argument("text", metavar="TEXT", help="the question text to check (one line is fine; wrap in quotes)")
    s.add_argument("--item", metavar="ITEM", required=True, help="the item the question belongs to")
    s.add_argument("--top", type=int, default=5, help="print at most this many matches (default: 5)")
    s.add_argument("--threshold", type=float, default=0.15, help="refuse matches below this Jaccard score "
                   "(default: 0.15; raise to tighten, lower to see more)")
    s = sub.add_parser("server", description="Host this console on the one console server (K3): `add NAME` "
                       "writes the project to server.json beside your registry. You run this, never a session.")
    ss = s.add_subparsers(dest="server_cmd", required=True)
    s = ss.add_parser("add")
    s.add_argument("project_name", metavar="NAME", help="the project's name, e.g. myproject (the agent-name shape)")
    # 1.46.0: the three Access values are required behind Cloudflare (checked in _run, by the server's mode) and
    # optional on a server in link mode (`server auth link`), which takes --origin instead.
    s.add_argument("--hostname", help="the project console's public hostname, a bare DNS name (Cloudflare)")
    s.add_argument("--aud", help="the project's Access application AUD tag (Cloudflare)")
    s.add_argument("--port", type=int, required=True, help="the project's owner-door loopback port")
    s.add_argument("--team-domain", help="e.g. yourteam.cloudflareaccess.com (Cloudflare)")
    s.add_argument("--origin", help="sign-in links: the console's address as the browser sees it (default "
                   "http://127.0.0.1:PORT; https://NAME behind `tailscale serve`)")
    s.add_argument("--root", type=Path, help="the main root, when several are registered on --state")
    s.add_argument("--page", default="index.html", help="the host page, a path under the root")
    s.add_argument("--slug", action="append", dest="slugs", metavar="SLUG",
                   help="an extra transcript slug for the cost collector; repeat for more")
    s = ss.add_parser("token", description="The project's agent token (K4): `rotate NAME` writes a new token "
                      "file and hash; the old token is refused from the next request. The token itself is never "
                      "printed.")
    s.add_argument("token_cmd", choices=("rotate",))
    s.add_argument("project_name", metavar="NAME")
    s = ss.add_parser("auth", description="Show or set how every owner door of the one server signs a browser in "
                      "(1.46, L5 L6): cloudflare (Access, the default) or link (sign-in links from `agent.py "
                      "invite`, no Cloudflare). In force at the server's next start. You run this, never a session.")
    s.add_argument("mode", nargs="?", choices=("cloudflare", "link"))
    s = ss.add_parser("listen", description="Show, set or clear the one address every owner door of the one "
                      "server listens on beside 127.0.0.1 (same port) (1.47, L4 L14): a ZeroTier (zt…) or Tailscale "
                      "(tailscale0, 100.64/10) address, with sign-in links only. Set while ZeroTier is down, it is "
                      "waited for at start (up to 2 minutes). In force at the server's next start. You run this, "
                      "never a session.")
    g = s.add_mutually_exclusive_group()
    g.add_argument("address", nargs="?", metavar="ADDR")
    g.add_argument("--clear", action="store_true", help="every owner door on 127.0.0.1 only")
    a = ap.parse_args(argv)
    if a.cmd == "notes":   # 1.53.0: a reading of the repository alone; no console, no door, no agent name
        return _notes(a)
    if a.cmd == "symbol-at":   # 1.54: a reading of this checkout alone, like `notes`
        return _symbol_at(a.source, a.json)
    if a.cmd == "adapter":   # Wave 4: the user's own vendor config and a checkout's AGENTS.md; no console, no door
        return _adapter(a)
    if a.state is None:
        ap.error("the following arguments are required: --state")
    # The agent name: --as, then this session's /overture:as (0.8.4), then OVERTURE_AGENT (0.8.2);
    # an empty variable counts as unset.
    a.agent, where = SN.resolve(a.agent, a.state)
    if a.agent is not None:
        why = N.problem(a.agent)
        if why:
            print(f"agent.py: {where}: {why}; nothing was sent", file=sys.stderr)
            return 2
    for given in (getattr(a, "steward", None), getattr(a, "name", None)):
        if given is not None and N.problem(given):
            print(f"agent.py: steward: {N.problem(given)}; nothing was written", file=sys.stderr)
            return 2
    bell = a.state / "inbox.jsonl"
    global _DOOR
    try:
        # The user's own commands write the user's files; every other command reaches (or, for watch, inbox and
        # synced, reads) ONE project's console, and that project is the one the working directory is in (K4).
        # 1.50.0: `worktree list` and `prune` never reach the console, so they need no door.
        if a.cmd not in USER_COMMANDS and not (a.cmd == "worktree" and a.wt_cmd != "new"):
            _DOOR = resolve_door(a.state)
        return _run(a, bell)
    except R.RegistryError as e:  # an unsafe or unreadable console file, named
        print(str(e), file=sys.stderr)
        return 1
    except DoorRefused as e:
        print(str(e), file=sys.stderr)
        return 1
    finally:
        _DOOR = None


USER_COMMANDS = ("register", "steward", "role", "server", "costs", "next-step", "operator-name", "access",
                 "notify-url", "invite", "devices")


def steward_refusal(state: Path, agent: str | None, what: str) -> str | None:
    """Why this session may not `what` (watch, synced, the fold), or None when it may (0.8.3).

    The check lives HERE, in the client, and not on the agent socket: `watch`
    reads the doorbell file and writes its heartbeat without ever calling the
    server, `synced` moves the cursor file before its one POST, and the fold
    reads the store file directly. A server check would see only that POST.
    Raises R.RegistryError when the registry cannot be read or names two
    stewards: a lock the user set does not quietly switch itself off.
    """
    name = R.steward_for_state(state)
    if name is not None and agent == name and R.machine_role() == "worker":
        return (f"refused: {what} belongs to this console's steward, {name}, and this machine's role is `worker`, so "
                f"no session here is the steward, even one named {name}. Run it on the steward's machine. (The role "
                f"is set with `agent.py role` and the plugin's Machine role setting.)")
    if name is None or agent == name:
        return None
    who = f"this session ({agent})" if agent else "this session (unnamed)"
    return (f"refused: {what} belongs to this console's steward, {name}, and {who} is not it. Only the steward "
            f"watches the doorbell, marks it synced and folds answers. Use `ask`, `reply` and `working` instead, "
            f"signed with --as YOUR-NAME: the steward handles the owner's requests. (The steward is set in your "
            f"own registry, {R.location()}, with `agent.py steward`; a session named {name} runs as it: "
            f"--as {name}, /overture:as {name} typed in the session, or {N.ENV}={name}.)")


def _masked(email: str) -> str:
    """`a…@example.com`: enough to tell logins apart in a list, not enough to write to one."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}…@{domain}"


def _operator_name(state: Path, email: str | None, short: str | None, clear: bool) -> int:
    """`operator-name` (1.38): list, show, set or clear the export name of an Access login, in STATE."""
    try:
        if email is None:
            if short is not None or clear:
                print("agent.py: operator-name: name the login (EMAIL) first", file=sys.stderr)
                return 2
            got = OP.load_names(state)
            # The agent socket never shows an owner's email, so neither does this listing inside a Claude
            # Code session (CLAUDECODE is set there): a guardrail between the owner's own cooperating
            # sessions, as ask_guard is (Sourcery on PR #164). The owner's own terminal sees them whole.
            show = _masked if os.environ.get("CLAUDECODE") else str
            print("\n".join(f"{show(e)} {n}" for e, n in sorted(got.items())) if got else
                  "no operator names: locks are exported with no name")
            return 0
        if short is None and not clear:
            got = OP.load_names(state)
            print(f"{email} {got[email]}" if email in got else f"{email}: no name; its locks are exported unnamed")
            return 0
        # 1.44: through the role log's lock, as the console's Settings tab writes it, and logged (by: the terminal).
        SET.put_name(state, email, None if clear else short, by=None)
    except (OSError, OP.OperatorsError, RO.RolesError) as e:
        print(f"agent.py: operator-name: {e}; nothing was written", file=sys.stderr)
        return 2
    print(f"{email}: name cleared" if clear else f"{email} {short}: its locks carry this name in the next export")
    return 0


def _notify_url(state: Path, url: str | None, clear: bool, test: bool) -> int:
    """`notify-url` (1.45): show the webhook's host, set it, clear it, or post a test. Never prints the URL:
    its path is what lets anyone post to the channel, and a terminal's scrollback is shared more than STATE."""
    try:
        if (url is not None or clear or test) and os.environ.get("CLAUDECODE"):
            # As `access`: a session that could point the webhook elsewhere could carry the digest there, or
            # silence it, and one that could test it could post to the team's channel at will. A guardrail
            # between the owner's own sessions (the same user can still edit STATE); the owner's terminal does it.
            print("agent.py: notify-url: refused inside a Claude Code session: the webhook is set and tested by "
                  "you, in your own terminal", file=sys.stderr)
            return 2
        if url is not None or clear:
            NT.set_url(state, None if clear else url)
            print("notifications: webhook removed; nothing is sent" if clear else
                  f"notifications: webhook set ({NT.host(url)}); turn them on under Settings in the console")
            return 0
        current = NT.load_url(state)
        if current is None:
            print("notifications: no webhook; set one with agent.py notify-url https://...")
            return 0
        if test:
            NT.send(current, "overture: a test message. The console's digest of waiting questions comes here.")
            print(f"notifications: test sent to {NT.host(current)}")
            return 0
        print(f"notifications: webhook set ({NT.host(current)})")
        return 0
    except (OSError, NT.NotifyError, RO.RolesError) as e:
        print(f"agent.py: notify-url: {e}", file=sys.stderr)
        return 2


def _show_role(entry: dict) -> str:
    out = entry["role"]
    if entry.get("areas"):
        out += (" of " if entry["role"] == "member" else ", Inbox on ") + ", ".join(entry["areas"])
    return out + (", director" if entry.get("director") else "")


def _access(state: Path, email: str | None, role: str | None, areas: list[str], clear: bool,
            director: bool = False) -> int:
    """`access` (1.39): list, show, set or clear an Access login's role in the console, in STATE (roles.py)."""
    try:
        if email is None or (role is None and not clear):
            if areas:
                print("agent.py: access: name the role before its areas", file=sys.stderr)
                return 2
            got = RO.load(state)
            if got is None:
                print("no roles: every login that passes Access is the owner" if email is None else
                      f"{email}: owner (no roles are set: every login is the owner)")
                return 0
            if email is None:
                show = _masked if os.environ.get("CLAUDECODE") else str   # as operator-name's listing
                print("\n".join(f"{show(e)} {_show_role(r)}" for e, r in sorted(got.items())))
                return 0
            print(f"{email} {_show_role(RO.role_of(got, email))}" + ("" if email.lower() in got else " (not listed)"))
            return 0
        if role is not None and clear:
            print("agent.py: access: give a role or --clear, not both", file=sys.stderr)
            return 2
        if os.environ.get("CLAUDECODE"):
            # A session that could raise a login's role could raise its owner's colleague, or itself through a
            # login it controls. Like ask_guard, a guardrail between the owner's own sessions: the same user can
            # still edit the file, but nothing in a session's ordinary path does.
            print("agent.py: access: refused inside a Claude Code session: roles are set by you, in your own "
                  "terminal", file=sys.stderr)
            return 2
        got = RO.set_role(state, email, None if clear else role, areas, director=director)
    except (OSError, RO.RolesError) as e:
        print(f"agent.py: access: {e}; nothing was written", file=sys.stderr)
        return 2
    if not got:
        print(f"{email}: cleared; no roles are left, so every login is the owner again")
    elif clear:
        print(f"{email}: cleared; it only reads now")
    else:
        print(f"{email} {_show_role(got[email.lower()])}: in effect on its next write, no restart needed")
    return 0


SESSION_REFUSAL = "refused inside a Claude Code session: {what} by you, in your own terminal"


def _link_origin(state: Path) -> tuple[str | None, str]:
    """(the console's origin for a link, where it came from) from server.json when the one server hosts this
    console in link mode: the entry's origin, else http://127.0.0.1:PORT (1.47.0: http://LISTEN:PORT when the
    server has `server listen`, the one address its doors are on). (None, why) otherwise."""
    from overture import serverfile as SF
    try:
        doc = SF.load()
    except (SF.ServerFileError, R.RegistryError, OSError) as e:
        return None, f"server.json cannot be read ({e})"
    s = os.path.realpath(state)
    for name, e in sorted(doc["projects"].items()):
        if isinstance(e, dict) and e.get("state") == s:
            if doc["auth"] != "link":
                return None, "the one server signs in through Cloudflare (`agent.py server auth`)"
            port = e.get("port")
            host = doc["listen"] or "127.0.0.1"
            return (e.get("origin") or (f"http://{host}:{port}" if isinstance(port, int) else None)), name
    return None, "server.json hosts no project on this console"


def _console_listens(state: Path) -> set[str]:
    """1.47 (S2): the --listen address(es) of the console on `state`: server.json's `listen` when the one server
    hosts it, and CONSOLE_LISTEN in the .overture/console.env of each project registered on that state (a
    single server's unit passes it as --listen). Unreadable files say nothing; an empty set means none known."""
    from overture import serverfile as SF
    s, out = os.path.realpath(state), set()
    try:
        doc = SF.load()
        if doc["listen"] and any(isinstance(e, dict) and e.get("state") == s for e in doc["projects"].values()):
            out.add(doc["listen"])
    except (SF.ServerFileError, R.RegistryError, OSError):
        pass
    try:
        roots = [r for r, e in R.load().items() if isinstance(e, dict) and e.get("state") == s]
    except (R.RegistryError, OSError):
        roots = []
    for root in roots:
        try:
            raw = R.read_regular(Path(root) / ".overture" / "console.env", 1 << 16)
        except (R.RegistryError, OSError, ValueError):
            continue
        for line in (raw or b"").decode("utf-8", "replace").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "CONSOLE_LISTEN" and v.strip():
                out.add(v.strip())
    return out


def _invite_origin_problem(origin: str, state: Path) -> str | None:
    """1.47.0 (L15): an invite's --origin may also be http://ADDR[:PORT]. 1.47 (S2): only when ADDR is this
    console's own --listen address (`_console_listens`); through 1.47.0 any address netif would take by name
    passed, a LAN one included. It is only printed into the link; the console's own Origin and Host checks
    decide what a browser may do there."""
    host = DV.urlsplit_host(origin)
    listens = _console_listens(state)
    if isinstance(origin, str) and origin.startswith("http://") and host not in ("127.0.0.1", "localhost") \
            and host not in listens:
        return (f"--origin {origin} is refused: http is taken only on loopback and on this console's own --listen "
                f"address ({', '.join(sorted(listens)) or 'it has none'}); give https://NAME, or the listen address")
    return DV.origin_problem(origin, host if host in listens else None)


def _invite(state: Path, email: str, origin: str | None) -> int:
    """`invite` (1.46): a sign-in link, printed once. Only the token's hash is kept (devices.py)."""
    if os.environ.get("CLAUDECODE"):
        # As `access`: a session that could mint a link could sign a browser of its choosing in as anyone the
        # roles name, the owner included. A guardrail between the owner's own sessions, as ask_guard is.
        print("agent.py: invite: " + SESSION_REFUSAL.format(what="sign-in links are made"), file=sys.stderr)
        return 2
    why = OP.email_problem(email) or (origin is not None and _invite_origin_problem(origin, state))
    if why:
        print(f"agent.py: invite: {why}; nothing was written", file=sys.stderr)
        return 2
    where = None
    if origin is None:
        origin, where = _link_origin(state)
    try:
        roles = RO.load(state)
        _token, _ident = DV.invite(DV.location(), email, state)
    except (OSError, DV.DevicesError, RO.RolesError) as e:
        print(f"agent.py: invite: {e}; nothing was written", file=sys.stderr)
        return 2
    expires = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=DV.INVITE_HOURS)).strftime("%Y-%m-%d %H:%M UTC")
    path = f"/signin?t={_token}"
    print(f"A sign-in link for {email.lower()}. It works once, until {expires} (24 hours), and is shown only now:")
    print(f"  {DV.clean_origin(origin) + path if origin else path}")
    if not origin:   # no origin known here: the path, to open on the console's own address
        print(f"Open it on your console's address, e.g. http://127.0.0.1:PORT/signin?t=… ({where}; or pass "
              f"--origin).")
    print("The browser that opens it stays signed in until revoked (People, or agent.py devices --revoke ID).")
    if roles is not None and email.lower() not in roles:
        print(f"agent.py: invite: {email} has no role here, so it will only read until you give it a role: "
              f"agent.py access {email} ROLE", file=sys.stderr)
    return 0


def _devices(state: Path, revoke: str | None) -> int:
    """`devices` (1.46): the browsers signed in by link on this machine, or revoke one (logged, by the terminal)."""
    try:
        if revoke is not None:
            if os.environ.get("CLAUDECODE"):
                print("agent.py: devices: " + SESSION_REFUSAL.format(what="browsers are signed out"),
                      file=sys.stderr)
                return 2
            gone = DV.revoke(DV.location(), revoke, state, by=None)
            if gone is None:
                print(f"agent.py: devices: no signed-in browser has the id {revoke!r}; nothing was written",
                      file=sys.stderr)
                return 1
            print(f"{revoke}: signed out (it was {gone}'s); its next request is refused")
            return 0
        rows = DV.listing(DV.location())
    except (OSError, DV.DevicesError, RO.RolesError) as e:
        print(f"agent.py: devices: {e}", file=sys.stderr)
        return 2
    show = _masked if os.environ.get("CLAUDECODE") else str   # as `access`'s listing
    # Every device on the machine (the terminal is the machine's owner), with the projects it was invited from by
    # their state folder's name; a project whose roles list the email lets it in too (devices.admitted).
    print("\n".join(f"{d['id']}  {d['label']} · signed in {d['created']} · {show(d['email'])} · invited from "
                    f"{', '.join(os.path.basename(p) or p for p in d['projects'])}" for d in rows)
          if rows else "no browser is signed in by link on this machine")
    return 0


def _server_add(a) -> int:
    from overture import serverfile as SF
    try:
        doc = SF.load()
        auth = doc["auth"]
    except (SF.ServerFileError, R.RegistryError) as err:
        print(f"refused, nothing written: {err}", file=sys.stderr)
        return 1
    if auth == "cloudflare":
        missing = [f for f, v in (("--hostname", a.hostname), ("--aud", a.aud), ("--team-domain", a.team_domain))
                   if v is None]
        if missing:
            print(f"refused, nothing written: {', '.join(missing)} required: the one server signs in through "
                  f"Cloudflare Access (`agent.py server auth link` switches it to sign-in links)", file=sys.stderr)
            return 1
    try:   # the name is the user's word on this command line, never a key of the repository's config
        e = SF.add(a.project_name, a.state, a.hostname, a.aud, a.port, a.team_domain, root=a.root,
                   page=a.page, slugs=a.slugs, origin=a.origin)
    except SF.ServerFileError as err:
        print(f"refused, nothing written: {err}", file=sys.stderr)
        return 1
    # 1.47.0: with `server listen`, the default origin is the overlay one.
    where = e.get("hostname") or e.get("origin") or f"http://{doc['listen'] or '127.0.0.1'}:{e['port']}"
    print(f"server: project {a.project_name} on port {e['port']} ({where}), state {e['state']}, "
          f"root {e['root']} in {SF.location()}; its agents' token is in {SF.token_file(a.project_name)} "
          f"(mode 0600)")
    return 0


def _server_auth(mode: str | None) -> int:
    from overture import serverfile as SF
    try:
        if mode is None:
            now = SF.load()["auth"]
            print(f"server auth: {now}" + (" (sign-in links: agent.py invite EMAIL)" if now == "link" else
                                           " (Cloudflare Access)"))
            return 0
        if os.environ.get("CLAUDECODE"):
            print("agent.py: server auth: " + SESSION_REFUSAL.format(what="the way in is chosen"), file=sys.stderr)
            return 2
        SF.set_auth(mode)
    except (SF.ServerFileError, R.RegistryError, OSError) as err:
        print(f"refused, nothing written: {err}", file=sys.stderr)
        return 1
    print(f"server auth: {mode}, in {SF.location()}; restart the server for it to take effect")
    return 0


def _server_listen(address: str | None, clear: bool) -> int:
    """`server listen [ADDR | --clear]` (1.47.0, L4 L14): show, set or clear server.json's "listen". Setting or
    clearing is refused in a session, as `server auth` is: it decides who on which network can reach every
    console. Contract 1 by name (netif) and link mode (serverfile.set_listen); an address no interface holds
    yet is set with a warning (L16 waits for it at start), one on any other interface is refused."""
    from overture import netif as NI
    from overture import serverfile as SF
    try:
        if address is None and not clear:
            now = SF.load()["listen"]
            print(f"server listen: {now} (every owner door on 127.0.0.1 and that address)" if now else
                  "server listen: none (every owner door on 127.0.0.1)")
            return 0
        if os.environ.get("CLAUDECODE"):
            print("agent.py: server listen: " + SESSION_REFUSAL.format(what="the address the console listens on is "
                                                                       "chosen"), file=sys.stderr)
            return 2
        note = None
        if address is not None:
            got = NI.check(address)   # ListenError: refused by name, or on a non-overlay interface: nothing written
            note = (None if got else f"no ZeroTier or Tailscale interface holds {address} now; the server waits up "
                                     f"to 2 minutes for it when it starts")
            warnings = NI.overlap_warnings(address, got) if got else []
        SF.set_listen(None if clear else address)
    except NI.ListenError as err:
        print(f"refused, nothing written: {err}", file=sys.stderr)
        return 1
    except (SF.ServerFileError, R.RegistryError, OSError) as err:
        print(f"refused, nothing written: {err}", file=sys.stderr)
        return 1
    if clear:
        print(f"server listen: cleared, in {SF.location()}; every owner door is on 127.0.0.1 only from the "
              f"server's next "
              f"start")
        return 0
    print(f"server listen: {address}, in {SF.location()}; restart the server for it to take effect. A project "
          f"with no --origin is then at http://{address}:PORT")
    for line in ([f"agent.py: server listen: warning: {note}"] if note else []) + warnings:
        print(line, file=sys.stderr)
    return 0


def _run(a, bell: Path) -> int:
    if a.cmd == "invite":
        return _invite(a.state, a.email, a.origin)
    if a.cmd == "devices":
        return _devices(a.state, a.revoke)
    if a.cmd == "register":
        e = R.register(a.project, a.state, Path(__file__).resolve().parent, steward=a.steward)
        print(f"registered {Path(a.project).resolve()}: state {e['state']}, kit {e['kit']}"
              + (f", steward {e[R.STEWARD]}" if R.STEWARD in e else "") + f" in {R.location()}")
        return 0
    if a.cmd == "operator-name":
        return _operator_name(a.state, a.email, a.short, a.clear)
    if a.cmd == "notify-url":
        return _notify_url(a.state, a.url, a.clear, a.test)
    if a.cmd == "access":
        return _access(a.state, a.email, a.role, a.areas, a.clear, a.director)
    if a.cmd == "role":
        if a.value is None:
            r = R.machine_role()
            print(f"role: {r}" if r else "no role: any session here may be the steward, as the registry names it")
            return 0
        R.set_machine_role(None if a.value == "clear" else a.value)
        print(f"role {a.value}" if a.value != "clear" else "role cleared", f"in {R.location()}")
        return 0
    if a.cmd == "steward":
        if a.name is None and not a.clear:
            name = R.steward_for_state(a.state)
            print(f"steward: {name}" if name else "no steward: every session may watch, sync and fold")
            return 0
        roots = R.set_steward(a.state, None if a.clear else a.name)
        print((f"steward {a.name}" if a.name else "no steward") + f" for the console at "
              f"{Path(a.state).resolve()}: {', '.join(roots)} in {R.location()}")
        return 0
    if a.cmd == "costs":
        return _costs(a)
    if a.cmd == "items-push":
        return _items_push(a)
    if a.cmd == "items-watch":
        return _items_watch(a)
    if a.cmd == "scaffold-dashboard":
        return _scaffold_dashboard(a)
    if a.cmd == "sync-dashboard":
        return _sync_dashboard(a)
    if a.cmd == "portfolio":
        return _portfolio(a)
    if a.cmd == "playbook":
        return _playbook_run(a)
    if a.cmd == "item-move":
        return _item_move(a)
    if a.cmd == "portfolio-token":
        print("Create a service token in Cloudflare Zero Trust → Access → Service Auth.")
        print("Attach it to each PEER console's Access application (inbound ACL).")
        print()
        print("Then on the HOME console's machine, write STATE/portfolio-secrets/<peer>.json (0600):")
        print('  {"client_secret": "<the-plaintext-secret-from-Cloudflare>"}')
        print()
        print("Compute the URL-bound token hash (1.20.0: binds the secret to the peer URL so an")
        print("edit of url in portfolio.json without re-signing is caught by the drift check):")
        print("  python3 -c 'import hashlib,sys; s,u=sys.argv[1:3]; "
              "print(hashlib.sha256(s.encode()+b\"\\\\0\"+u.encode()).hexdigest())' "
              "'<secret>' 'https://peer-console.example.com'")
        print()
        print("Then paste into .overture/portfolio.json alongside the Cloudflare client_id:")
        print('  "peers": {"<peer-name>": {"url": "https://peer-console.example.com",')
        print('                             "client_id": "...access", "token_sha256": "<the hex above>"}}')
        print()
        print("Pre-1.20 shape sha256(secret) is still accepted with a one-line warning asking you")
        print("to rotate. The server refuses redirects and private/loopback peer URLs regardless.")
        return 0
    if a.cmd == "trigger-token":
        from overture import triggers as TR
        token, sha = TR.mint()
        print("Token (give to the sender — this is the plaintext):")
        print(f"  {token}")
        print()
        print("Put this in .overture/triggers.json under the trigger's token_sha256:")
        print(f"  {sha}")
        print()
        print("The sender calls POST /api/trigger/<name> with")
        print(f"  Authorization: Bearer {token}")
        return 0
    if a.cmd == "history-push":
        return _history_push(a)
    if a.cmd == "prs-push":
        return _prs_push(a)
    if a.cmd == "issues-push":
        return _issues_push(a)
    if a.cmd == "lessons":
        return _lessons(a)
    if a.cmd == "lesson-match":
        return _lesson_match(a)
    if a.cmd == "page-snapshot":
        return _page_snapshot(a)
    if a.cmd == "server" and a.server_cmd == "token":
        from overture import serverfile as SF
        try:
            f = SF.rotate(a.project_name)
        except SF.ServerFileError as err:
            print(f"refused, nothing written: {err}", file=sys.stderr)
            return 1
        print(f"server: project {a.project_name} has a new token in {f} (mode 0600); the old one is refused from "
              f"the next request, and agent.py reads the new one on its next call")
        return 0
    if a.cmd == "server" and a.server_cmd == "auth":
        return _server_auth(a.mode)
    if a.cmd == "server" and a.server_cmd == "listen":   # 1.47.0
        return _server_listen(a.address, a.clear)
    if a.cmd == "server":
        return _server_add(a)
    if a.cmd in ("watch", "synced"):
        why = steward_refusal(a.state, a.agent, f"`{a.cmd}`")
        if why:
            print(why, file=sys.stderr)
            return 1
    if a.cmd == "inbox":
        since = 0 if a.all else (a.since if a.since is not None else D.read_cursor(a.state))
        rx_since = 0 if a.all else D.read_rx_cursor(a.state)
        for line in D.pending(bell, since, intents=None, rx_since=rx_since):
            print(json.dumps(line, sort_keys=True))
        return 0
    if a.cmd == "watch":
        since = a.since if a.since is not None else D.read_cursor(a.state)
        beat = D.Heartbeat(a.state, a.poll, stale=_prune_record(a.state).get("stale"),   # "agent listening" (0.6.0)
                           notes=_notes_record(a.state).get("counts"))
        beat()   # 1.50 review C2: the owner sees "listening" first; the prune never holds that back
        if not D.pending(bell, since, rx_since=D.read_rx_cursor(a.state)):   # work waiting goes first
            beat.update(_watch_prune(a.state, beat=beat))   # W3: throttled and time-capped; the stale ones ride the heartbeat
            beat.update_notes(_watch_notes(a.state, beat=beat))   # 1.53.0: once a day; the counts ride it too
        # A session that ends kills its watch with SIGTERM or SIGHUP; turn those into an
        # ordinary exit so `finally` says "stopped" now, rather than the owner seeing
        # "listening" until the promise lapses. SIGKILL cannot be caught: that is the lapse's job.
        old = {sig: signal.signal(sig, lambda n, _f: sys.exit(128 + n)) for sig in (signal.SIGTERM, signal.SIGHUP)}
        try:
            found = D.watch(bell, since, poll=a.poll, timeout=a.timeout, heartbeat=beat,
                            rx_since=D.read_rx_cursor(a.state))
        finally:  # woken, timed out, or interrupted: the owner is told at once, not when the promise lapses
            beat.stop()
            for sig, h in old.items():
                signal.signal(sig, h)
        if not found:
            print(f"no 'process', 'fork', 'chat', 'visual' or 'scan' signal after seq {since} within {a.timeout:g}s",
                  file=sys.stderr)
            return 3
        for line in found:
            print(json.dumps(line, sort_keys=True))
        return 0
    if a.cmd == "todo":
        return _todo(a.state, a.full)
    if a.cmd == "view":
        return _view(a.state, a.item, a.since, a.full)
    if a.cmd == "health":
        return _call(a.state, "GET", "/health")
    if a.cmd == "answers":
        return _answers(a.state, a.item, a.fork, a.json, a.since, a.full)
    if a.cmd == "fork-context":
        return _fork_context(a.state, a.fork)
    if a.cmd == "check":
        return _check(a.state, a.json)
    if a.cmd == "rulings":
        return _rulings(a.state, a.path, a.json)
    if a.cmd == "reanchor":
        return _reanchor(a.state, a.dry_run, a.json)
    if a.cmd == "reply":
        body = {"item": a.item, "text": a.text, "nonce": secrets.token_urlsafe(12)}
        if a.reply_to:
            body["reply_to"] = a.reply_to
        return _call(a.state, "POST", "/message", body, agent=a.agent)
    if a.cmd == "working":
        rc, out, note = _post_working(a.state, a.items, _here_branch(), a.agent)
        if rc != 2:
            sys.stdout.write(_json(out))
        if note:
            print(note, file=sys.stderr)
        return rc
    if a.cmd == "worktree":
        return _worktree(a)
    if a.cmd == "next-step":
        from overture import projectcfg as PC
        try:
            cfg = PC.load(a.project)
            name = cfg.next_step.get(a.kind)
            if not name:
                raise PC.ConfigError(f".overture.json names no next_step skill for {a.kind!r}")
            path = PC.resolve_skill(name, a.project)
        except PC.ConfigError as e:
            print(f"refused: {e}", file=sys.stderr)
            return 1
        print(json.dumps({"kind": a.kind, "skill": name, "skill_md": str(path)}))
        return 0
    if a.cmd == "transcript":
        text = _read_text(a.file, "transcript")
        if text is None:
            return 1
        return _call(a.state, "POST", "/transcript", {"fork": a.fork, "text": text,
                                                       "nonce": secrets.token_urlsafe(12)}, agent=a.agent)
    if a.cmd == "visual":
        content, doc = _read_text(a.file, "visual"), _read_text(a.doc, "doc")
        if content is None or doc is None:
            return 1
        return _call(a.state, "POST", "/visual", {"request": a.request, "format": a.format, "title": a.title,
                                                  "content": content, "text": doc,
                                                  "nonce": secrets.token_urlsafe(12)}, agent=a.agent)
    if a.cmd == "asset":
        try:
            data = R.read_regular(a.file, ASSET_READ_CAP + 1)
        except R.RegistryError as e:
            print(f"asset {a.file}: {e}", file=sys.stderr)
            return 1
        if data is None:
            print(f"asset {a.file} does not exist", file=sys.stderr)
            return 1
        if len(data) > ASSET_READ_CAP:
            print(f"asset {a.file} is over {ASSET_READ_CAP} bytes; refused, not cut", file=sys.stderr)
            return 1
        body = {"item": a.item, "content_b64": base64.b64encode(data).decode("ascii"), "caption": a.caption,
                "kind": a.kind, "nonce": secrets.token_urlsafe(12)}
        for k in ("qid", "pr", "ticket"):
            if getattr(a, k) is not None:
                body[k] = getattr(a, k)
        return _call(a.state, "POST", "/asset", body, agent=a.agent)
    if a.cmd == "ux-export":
        return _ux_export(a.state, a.project, a.save)
    if a.cmd == "pr-merge":
        return _pr_merge(a)
    if a.cmd == "design-inventory":
        try:
            text = a.file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"refused: cannot read {a.file}: {e}", file=sys.stderr)
            return 1
        try:
            arts = json.loads(text)
        except ValueError:
            arts = [{"path": ln.strip()} for ln in text.splitlines() if ln.strip()]
        if isinstance(arts, list):
            arts = [{"path": x} if isinstance(x, str) else x for x in arts]
        return _call(a.state, "POST", "/design-inventory", {"url": a.url, "artifacts": arts,
                                                            "nonce": secrets.token_urlsafe(12)}, agent=a.agent)
    if a.cmd == "component-source":
        try:
            text = a.file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"refused: cannot read {a.file}: {e}", file=sys.stderr)
            return 1
        return _call(a.state, "POST", "/component-source", {"visual_id": a.visual, "content": text,
                                                            "nonce": secrets.token_urlsafe(12)}, agent=a.agent)
    if a.cmd == "visual-export":
        return _visual_export(a.state, a.project, a.visual)
    if a.cmd == "propose-anchor":
        if not a.cite and not a.symbol:
            print("propose-anchor: name the lines (--cite PATH:FIRST-LAST) or the definition (--symbol "
                  "PATH::NAME) the ruling rests on now", file=sys.stderr)
            return 2
        body = {"qid": a.qid, "basis": a.basis, "nonce": secrets.token_urlsafe(12)}
        body.update({"cites": a.cite} if a.cite else {})
        body.update({"symbols": a.symbol} if a.symbol else {})   # only when given: an older server's shape stays
        return _call(a.state, "POST", "/anchor-proposal", body, agent=a.agent)
    if a.cmd == "advise":
        return _call(a.state, "POST", "/refactor-advice", {"qid": a.qid, "star": a.star, "evidence": a.evidence,
                                                           "nonce": secrets.token_urlsafe(12)}, agent=a.agent)
    if a.cmd == "ask":
        for n, f in enumerate(a.files):
            try:
                body = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                return _refused_note(a.files, n, f"{f} is not a readable JSON question: {e}")
            if not isinstance(body, dict):
                return _refused_note(a.files, n, f"{f} is not a JSON object")
            body.setdefault("nonce", secrets.token_urlsafe(12))
            rc = _call(a.state, "POST", "/question", body, agent=a.agent)
            if rc:
                return _refused_note(a.files, n, None, rc)
        if len(a.files) > 1:
            print(f"posted {len(a.files)} questions", file=sys.stderr)
        return 0
    if a.through is not None or a.rx_through is not None:
        if (a.through or 0) < 0 or (a.rx_through or 0) < 0:
            print("--through and --rx-through take a doorbell seq, 0 or more", file=sys.stderr)
            return 1
        held = D.write_cursor(a.state, a.through or 0, a.rx_through)
        print(f"agent cursor: processed through seq {held}"
              + (f", refactor seq {D.read_rx_cursor(a.state)}" if a.rx_through is not None else ""), file=sys.stderr)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _call(a.state, "POST", "/cursor", {"last_synced_at": now, "last_error": a.error}, agent=a.agent)


if __name__ == "__main__":
    sys.exit(main())
