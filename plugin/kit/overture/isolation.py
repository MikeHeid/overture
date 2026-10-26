"""Same-user isolation (1.60.0, OPEN-DECISIONS I1-I7): sandbox rules that keep a session out of every console's
STATE, and the check a session runs inside itself to prove they hold.

An agent running as your OS user can read any file you can: every project's store, the GitHub trigger
secrets (1.59), the webhook URL (1.45), the roles. Claude Code's sandbox narrows that for the commands a
session runs (bubblewrap on Linux, Seatbelt on macOS), and its `Read(...)` deny rules narrow the built-in
tools. `settings()` writes those rules for this machine's registered consoles. They belong in managed
settings (I3), which neither a session nor a project can loosen and which an agent cannot edit. agent.py
stays inside the sandbox (I5): it runs git and the project's adapter, which a session can write, so it never
runs outside an agent's jail (CONSOLE-kit/Q23).

What the rules leave each session (I1, I4, I7):
- every console's agent socket, the only door an agent needs;
- `inbox.jsonl` (the doorbell), `sessions.jsonl` and `lessons.jsonl`, to read: none holds a secret;
- `STATE/steward/`, to read and write: the files a session writes in STATE (doorbell.STEWARD_FILES), and
  nothing else. Any session may therefore fake the steward's cursor or heartbeat (I7, accepted).

Measured under Claude Code's sandbox on Linux (the 1.60 real run), and why each rule is shaped as it is:
- a write-allowed folder is a readable one, so sessions write only into a folder holding nothing else;
- a `permissions` Edit rule becomes a sandbox write denial that beats allowWrite, so no Edit rule covers
  steward/: the files around it are denied by name;
- `allowUnixSockets`, the per-path socket list, is macOS-only. On Linux the one way to reach agent.sock is
  `allowAllUnixSockets`, which opens every socket not denied by path, and some sockets run a command for
  whoever connects (Claude Code's and Codex's daemons, X11, dbus, Docker). So on Linux every socket the
  machine has when `settings()` runs is denied, plus the folders daemons keep theirs in (I5). That is
  best-effort: software installed later adds sockets, which is why `check()` tries every one it finds (I6).

`check()` is the proof, not the settings: run it inside a session and it tries each door.
"""

from __future__ import annotations

import errno
import fnmatch
import json
import os
import re
import socket
import stat
import sys
from pathlib import Path

from . import doorbell as D
from . import items as IT
from . import lessons as LE
from . import multiserver as MS
from . import names as NM
from . import notify as NT
from . import operators as OP
from . import peers as PE
from . import roles as RO
from . import sessions as SE
from . import settings as SET
from . import triggers as TR
from . import twokey as TK

AGENT_SOCKET = "agent.sock"
DOORBELL = "inbox.jsonl"
READABLE = (DOORBELL, SE.FILE, LE.FILE)   # read by a session's own commands (watch, whoami, lesson-match)
ALLOWED = frozenset({AGENT_SOCKET, D.STEWARD_DIR, *READABLE})   # all a session may see in a STATE folder
# The secrets and records a session must never read or write, by each module's own name for them; the server's
# other files (refs, PRs, drafts, favourites, assets, visuals) are named here too, since an Edit rule goes by name.
PROTECTED = ("store.jsonl", NT.URL_FILE, NT.STATE_FILE, TR.SECRET_DIR, PE.SECRETS_DIR, RO.FILE, RO.LOG_FILE,
             SET.FILE, OP.FILE, OP.NAMES_FILE, TK.FILE, NM.FILE, IT.ITEMS, MS.LOCK, "refs.json", "prs.json",
             "issues.json", "drafts.json", "favorites.json", "assets", "visuals")
# Sockets that run something for whoever connects: a container (root on most hosts).
ESCAPE_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock", "/run/containerd/containerd.sock",
                  "/run/podman/podman.sock", "/var/run/podman/podman.sock")
# Folders that daemons keep their sockets in, denied whole so a socket made there later is covered too ({uid},
# {home}). Never a folder the sandbox needs for anything else: /run/systemd holds resolv.conf on many hosts, so its
# sockets are denied one by one instead.
SOCKET_DIRS = ("/tmp/cc-daemon-{uid}", "/tmp/codex-daemon-{uid}", "/tmp/.X11-unix", "/tmp/.ICE-unix",
               "/tmp/tmux-{uid}", "/tmp/screen", "/run/screen", "/var/run/screen", "/run/dbus", "/var/run/dbus",
               "{home}/.gnupg")
# Socket names a program makes afresh in a shared folder, one per process (a .NET runtime's diagnostics port, which
# newer runtimes load code through; VS Code's IPC; an ssh-agent's folder). A denyRead glob is expanded to the paths it
# matches when a session starts (Claude Code's docs, Linux), so it covers more than a list made by `settings`.
SOCKET_GLOBS = ("/tmp/dotnet-diagnostic-*", "/tmp/vscode-ipc-*", "/tmp/vscode-git-*", "/tmp/ssh-*")
# The sandbox's own plumbing, made per session for its network proxy (measured, 1.60 real run: claude-http-<hex>.sock,
# srt-mux-<pid>-<n>.sock): never denied, which would cut the session's network, and shown by the check on a row of its
# own rather than counted. Only a name of exactly that shape, directly in SANDBOX_OWN_DIR and owned by this user.
SANDBOX_OWN_DIR = "/tmp"
SANDBOX_OWN = (re.compile(r"claude-http-[0-9a-f]{8,64}\.sock\Z"), re.compile(r"srt-mux-[0-9]{1,10}-[0-9]{1,6}\.sock\Z"))
SOCKET_ROOTS = ("/tmp", "/run", "/var/run")   # walked for sockets, with the home folder (I5, I6)
WALK_DEPTH = 4
WALK_LIMIT = 20000   # entries visited per root; a check that never ends proves nothing
MANAGED = {"linux": Path("/etc/claude-code/managed-settings.json"),
           "darwin": Path("/Library/Application Support/ClaudeCode/managed-settings.json")}
MUST = (("enabled", True), ("failIfUnavailable", True), ("allowUnsandboxedCommands", False))
SANDBOX_ENV = "SANDBOX_RUNTIME"   # "1" inside Claude Code's sandbox (measured, 1.60 real run)


def runtime_dir(env=os.environ, uid: int | None = None) -> Path:
    return Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid() if uid is None else uid}")


def config_dir(env=os.environ) -> Path:
    """The user's overture folder (registry.location's), which holds the registry and the sign-in devices
    (devices.py): a session may read them, which says nothing the socket does not, but never write them."""
    return Path(env.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")) / "overture"


def _home(env) -> str:
    return env.get("HOME") or os.path.expanduser("~")


def consoles(registry: dict) -> list[Path]:
    """Every registered console's STATE folder, once each, as real paths."""
    out: list[Path] = []
    for entry in registry.values():
        s = entry.get("state") if isinstance(entry, dict) else None
        if isinstance(s, str):
            p = Path(os.path.realpath(s))
            if p not in out:
                out.append(p)
    return out


def find_sockets(env=os.environ, roots: tuple[str, ...] | None = None, proc: Path = Path("/proc/net/unix"),
                 cut: list[str] | None = None) -> list[str]:
    """Every Unix socket on a path this process can see: a walk of SOCKET_ROOTS and the home folder (no link
    followed, at most WALK_DEPTH deep and WALK_LIMIT entries a root), and on Linux every bound path in
    /proc/net/unix. Abstract sockets have no path and are left out: the sandbox gives a session its own
    network namespace, where none of the host's abstract sockets exists. Each root whose walk stopped at
    WALK_LIMIT is appended to `cut`, so a partial sweep says so (1.60 review M2)."""
    found: set[str] = set()
    for root in (roots if roots is not None else (*SOCKET_ROOTS, _home(env))):
        base = len(Path(root).parts)
        seen = 0
        for top, dirs, files in os.walk(root, followlinks=False, onerror=lambda e: None):
            seen += len(dirs) + len(files)
            if seen > WALK_LIMIT or len(Path(top).parts) - base >= WALK_DEPTH:
                dirs[:] = []
            for name in files:
                p = os.path.join(top, name)
                try:
                    if stat.S_ISSOCK(os.lstat(p).st_mode):
                        found.add(p)
                except OSError:
                    pass
            if seen > WALK_LIMIT:
                if cut is not None:
                    cut.append(root)
                break
    try:
        for line in proc.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
            parts = line.split(None, 7)   # the path is the last field and may hold a space (review M2)
            if len(parts) >= 8 and parts[7].startswith("/"):
                found.add(parts[7])
    except OSError:
        pass
    return sorted(found)


def _doors(states: list[Path]) -> set[str]:
    return {str(s / AGENT_SOCKET) for s in states}


def _sandbox_own(p: str) -> bool:
    """A socket of the sandbox's own proxy: one name of SANDBOX_OWN's shape, directly in SANDBOX_OWN_DIR (no
    folder in between, so `*` never spans one), and owned by this user."""
    if os.path.dirname(p) != SANDBOX_OWN_DIR or not any(r.match(os.path.basename(p)) for r in SANDBOX_OWN):
        return False
    try:
        st = os.lstat(p)
    except OSError:
        return False
    return stat.S_ISSOCK(st.st_mode) and st.st_uid == os.getuid()


def settings(states: list[Path], env=os.environ, uid: int | None = None, platform: str = sys.platform,
             sockets: list[str] | None = None) -> dict:
    """The managed-settings document for these consoles (I1, I3, I5, I7). `sockets`: those to deny, found by
    find_sockets() when not given."""
    uid = os.getuid() if uid is None else uid
    doors = _doors(states)
    deny = [str(s) for s in states] + list(ESCAPE_SOCKETS) + [str(runtime_dir(env, uid))]
    deny += [d.format(uid=uid, home=_home(env)) for d in SOCKET_DIRS] + list(SOCKET_GLOBS)
    if env.get("SSH_AUTH_SOCK"):   # an agent that reaches your ssh-agent signs as you
        deny.append(env["SSH_AUTH_SOCK"])
    for p in find_sockets(env) if sockets is None else sockets:
        if p in doors or _sandbox_own(p) or any(fnmatch.fnmatchcase(p, g) for g in SOCKET_GLOBS):
            continue
        if not any(p == d or p.startswith(d + "/") for d in deny):
            deny.append(p)
    allow_read = [str(s / name) for s in states for name in (AGENT_SOCKET, *READABLE, D.STEWARD_DIR)]
    # macOS has the per-path list (strict); Linux has only all-or-nothing, so every other socket is denied above.
    network = ({"allowUnixSockets": sorted(doors)} if platform == "darwin" else {"allowAllUnixSockets": True})
    edits = []
    for s in states:
        names = set(PROTECTED) | {DOORBELL}
        try:   # F4: whatever else STATE holds today, by name, since an Edit rule cannot say "all but steward/"
            names |= {n for n in os.listdir(s) if n not in (D.STEWARD_DIR, AGENT_SOCKET)}
        except OSError:
            pass
        edits += [f"Edit(/{s / n}{tail})" for n in sorted(names) for tail in ("", "/**")]
    return {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,          # no sandbox, no session: never a quiet run without one
            "allowUnsandboxedCommands": False,  # no dangerouslyDisableSandbox retry
            "filesystem": {"denyRead": deny, "allowRead": allow_read,
                           "allowWrite": [str(s / D.STEWARD_DIR) for s in states]},
            "network": network,
        },
        # The built-in tools, which the sandbox does not cover. Claude Code also turns an Edit rule into a sandbox
        # write denial that beats allowWrite (measured, 1.60 real run), so an Edit rule on all of STATE would make
        # steward/ read-only: each name in STATE is denied by itself instead. A device a session wrote into
        # devices.json would sign its browser in, so the user's overture folder is denied too.
        "permissions": {"deny": [f"Read(/{s}/**)" for s in states] + edits + [f"Edit(/{config_dir(env)}/**)"]},
    }


def _read_attempt(p: Path) -> tuple[str, str]:
    """("open", what was seen) or ("blocked", why). A folder is listed; a file has one byte read."""
    try:
        if p.is_dir():
            names = sorted(os.listdir(p))
            return "open", ", ".join(names[:6]) + (" ..." if len(names) > 6 else "")
        with open(p, "rb") as fh:
            fh.read(1)
        return "open", "readable"
    except OSError as e:
        return "blocked", errno.errorcode.get(e.errno, type(e).__name__)


def _write_attempt(folder: Path) -> tuple[str, str]:
    """("open", "") when a new file could be made in `folder` (it is removed at once), else ("blocked", why). A name
    no Edit rule lists (review L1): the sandbox, not a rule by name, has to refuse it."""
    p = folder / f".isolation-probe-{os.getpid()}"
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except OSError as e:
        return "blocked", errno.errorcode.get(e.errno, type(e).__name__)
    os.close(fd)
    os.unlink(p)
    return "open", ""


def _connect(path: str, timeout: float = 3) -> tuple[str, str]:
    """("open", "") when something answers; ("blocked", why) when the sandbox or permissions refuse;
    ("absent", why) when nothing is there to reach."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path)
        return "open", ""
    except FileNotFoundError:
        return "absent", "ENOENT"
    except ConnectionRefusedError:
        return "absent", "nothing listening"
    except TimeoutError:   # review M2: something took the call and stalled: counted as answering, never as closed
        return "open", "stalled"
    except OSError as e:
        return "blocked", errno.errorcode.get(e.errno, type(e).__name__)
    finally:
        s.close()


def _managed(platform: str, states: list[Path]) -> tuple[str, str]:
    p = MANAGED["darwin" if platform == "darwin" else "linux"]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "absent", f"no {p}"
    except (OSError, ValueError) as e:
        return "blocked", f"{p}: {type(e).__name__}"
    sb = doc.get("sandbox") if isinstance(doc, dict) else None
    sb = sb if isinstance(sb, dict) else {}
    weak = [f"sandbox.{k} is not {str(want).lower()}" for k, want in MUST if sb.get(k) is not want]
    fs = sb.get("filesystem") if isinstance(sb.get("filesystem"), dict) else {}
    denied = fs.get("denyRead") if isinstance(fs.get("denyRead"), list) else []
    weak += [f"denyRead leaves out {s}" for s in states if str(s) not in denied]   # F3: a console added since
    return ("weak", f"{p}: " + ", ".join(weak)) if weak else ("set", str(p))


def check(states: list[Path], env=os.environ, uid: int | None = None, platform: str = sys.platform,
          sockets: list[str] | None = None) -> list[dict]:
    """Try every door from inside this session. Each row: what, path, want, got, detail, ok.

    A secret must read as blocked or absent (inside the sandbox a denied file is not there at all); a STATE
    folder may show only ALLOWED names; a console's socket must answer when it runs; no other socket the check
    can find may answer (I6). `sockets`: those to try, found by find_sockets() when not given.
    """
    rows: list[dict] = []

    def row(what, path, want, got, detail="", info=False):
        rows.append({"what": what, "path": str(path), "want": "/".join(want), "got": got, "detail": detail,
                     "ok": got in want, "info": info})

    inside = env.get(SANDBOX_ENV) == "1"
    row("inside Claude Code's sandbox", "", ("yes",), "yes" if inside else "no",
        "" if inside else f"{SANDBOX_ENV} is not set: run this from a sandboxed session")
    got, detail = _managed(platform, states)
    row("managed settings", detail if got == "set" else "", ("set",), got, "" if got == "set" else detail)
    for s in states:
        got, seen = _read_attempt(s)
        if got == "open":
            extra = sorted(set(os.listdir(s)) - ALLOWED)
            got, seen = ("open", ", ".join(extra[:6])) if extra else ("narrowed", "")
        row("list STATE", s, ("blocked", "narrowed"), got, seen)
        for name in PROTECTED:
            got, why = _read_attempt(s / name)
            row("read", s / name, ("blocked", "absent"), "absent" if why == "ENOENT" else got, why)
        got, why = _write_attempt(s)
        row("write a new file in STATE", s, ("blocked",), got, why)
        got, why = _connect(str(s / AGENT_SOCKET))
        row("reach the agent socket", s / AGENT_SOCKET, ("open", "absent"), got, why)
    for path in ESCAPE_SOCKETS:
        if inside or os.path.lexists(path):
            got, why = _connect(path)
            row("reach an escape socket", path, ("blocked", "absent"), got, why)
    doors = _doors(states)
    cut: list[str] = []
    found = [p for p in (find_sockets(env, cut=cut) if sockets is None else sockets) if p not in doors]
    own = [p for p in found if _sandbox_own(p)]
    others = [p for p in found if p not in own]
    answered = [p for p in others if _connect(p, timeout=1)[0] == "open"]
    row("reach any other socket", f"{len(others)} tried", ("blocked",), "open" if answered else "blocked",
        ", ".join(answered[:6]) + (" ..." if len(answered) > 6 else ""))
    # Shown, never counted: an unexpected listener of that shape stays visible to whoever reads the check.
    row("the sandbox's own proxy sockets", f"{len(own)} seen", ("listed",), "listed", ", ".join(own[:6]), info=True)
    row("the socket sweep", "", ("complete", "partial"), "partial" if cut else "complete",
        (f"stopped after {WALK_LIMIT} entries in " + ", ".join(cut)) if cut else "", info=True)
    got, seen = _read_attempt(runtime_dir(env, uid))
    if got == "open" and not seen:
        got = "narrowed"   # the sandbox shows a denied folder as empty
    elif got == "blocked" and seen == "ENOENT":
        got = "absent"
    row("list the runtime folder", runtime_dir(env, uid), ("blocked", "narrowed", "absent"), got, seen)
    cfg = config_dir(env)   # asked, never tried: a write that worked would change the user's sign-ins
    got = "absent" if not cfg.is_dir() else ("open" if os.access(cfg, os.W_OK) else "blocked")
    row("write the user's overture folder", cfg, ("blocked", "absent"), got)
    return rows


def render(rows: list[dict]) -> str:
    lines = [f"{'ok  ' if r['ok'] else 'FAIL'}  {r['got']:<9} {r['what']}{(' ' + r['path']) if r['path'] else ''}"
             + (f" ({r['detail']})" if r["detail"] and (not r["ok"] or r.get("info")) else "") for r in rows]
    bad = sum(not r["ok"] for r in rows)
    lines.append("isolation holds" if not bad else f"isolation does NOT hold: {bad} finding(s)")
    return "\n".join(lines)
