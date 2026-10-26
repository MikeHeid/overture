"""Same-user isolation (1.60.0, OPEN-DECISIONS I1-I4): sandbox rules that keep a session out of every console's
STATE, and the check a session runs inside itself to prove they hold.

An agent running as your OS user can read any file you can: every project's store, the GitHub trigger
secrets (1.59), the webhook URL (1.45), the roles. Claude Code's sandbox narrows that for the commands a
session runs (bubblewrap on Linux, Seatbelt on macOS), and its `Read(...)` deny rules narrow the built-in
tools. `settings()` writes those rules for this machine's registered consoles. They belong in managed
settings (I3), which neither a session nor a project can loosen and which an agent cannot edit.

What the rules leave each session (I1, I4):
- every console's agent socket, the only door an agent needs;
- the doorbell (`inbox.jsonl`), which the steward's watch reads and which says nothing the socket does not;
- `STATE/steward/`, the steward's cursor and heartbeat, written there and nowhere else in STATE.

Measured under Claude Code's sandbox on Linux (the 1.60 real run), and why each rule is shaped as it is: a
write-allowed folder is a readable one, so the steward writes only into a folder holding nothing else; a
socket inside a denied folder is reached only when `allowRead` re-opens it AND `allowAllUnixSockets` is on
(`allowUnixSockets` is macOS-only), so every socket that hands out more than a file read (Docker's, and the
user's runtime folder with its session bus and systemd) is denied by path.

`check()` is the proof, not the settings: run it inside a session and it tries each door.
"""

from __future__ import annotations

import errno
import json
import os
import socket
import sys
from pathlib import Path

from . import devices as DV
from . import doorbell as D
from . import notify as NT
from . import operators as OP
from . import peers as PE
from . import roles as RO
from . import settings as SET
from . import triggers as TR

AGENT_SOCKET = "agent.sock"
DOORBELL = "inbox.jsonl"
ALLOWED = frozenset({AGENT_SOCKET, DOORBELL, D.STEWARD_DIR})   # all a session may see in a STATE folder
# The secrets and records a session must never read, by each module's own name for them.
PROTECTED = ("store.jsonl", NT.URL_FILE, NT.STATE_FILE, TR.SECRET_DIR, PE.SECRETS_DIR, RO.FILE, RO.LOG_FILE,
             SET.FILE, DV.FILE, OP.FILE, OP.NAMES_FILE)
# Sockets that run something for whoever connects: a container (root on most hosts), or the user's own
# services through the session bus and systemd, which would start a process outside the sandbox.
ESCAPE_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock", "/run/containerd/containerd.sock",
                  "/run/podman/podman.sock", "/var/run/podman/podman.sock")
MANAGED = {"linux": Path("/etc/claude-code/managed-settings.json"),
           "darwin": Path("/Library/Application Support/ClaudeCode/managed-settings.json")}
MUST = (("enabled", True), ("failIfUnavailable", True), ("allowUnsandboxedCommands", False))
SANDBOX_ENV = "SANDBOX_RUNTIME"   # "1" inside Claude Code's sandbox (measured, 1.60 real run)


def runtime_dir(env=os.environ, uid: int | None = None) -> Path:
    return Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid() if uid is None else uid}")


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


def settings(states: list[Path], env=os.environ, uid: int | None = None) -> dict:
    """The managed-settings document for these consoles (I1, I3, I4)."""
    deny = [str(s) for s in states] + list(ESCAPE_SOCKETS) + [str(runtime_dir(env, uid))]
    if env.get("SSH_AUTH_SOCK"):   # an agent that reaches your ssh-agent signs as you
        deny.append(env["SSH_AUTH_SOCK"])
    allow_read = [str(s / name) for s in states for name in (AGENT_SOCKET, DOORBELL, D.STEWARD_DIR)]
    return {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,          # no sandbox, no session: never a quiet run without one
            "allowUnsandboxedCommands": False,  # no dangerouslyDisableSandbox retry
            "filesystem": {"denyRead": deny, "allowRead": allow_read,
                           "allowWrite": [str(s / D.STEWARD_DIR) for s in states]},
            "network": {"allowAllUnixSockets": True},
        },
        "permissions": {"deny": [f"{kind}(/{s}/**)" for s in states for kind in ("Read", "Edit")]},
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


def _connect(path: str) -> tuple[str, str]:
    """("open", "") when something answers; ("blocked", why) when the sandbox or permissions refuse;
    ("absent", why) when nothing is there to reach."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3)
    try:
        s.connect(path)
        return "open", ""
    except FileNotFoundError:
        return "absent", "ENOENT"
    except ConnectionRefusedError:
        return "absent", "nothing listening"
    except OSError as e:
        return "blocked", errno.errorcode.get(e.errno, type(e).__name__)
    finally:
        s.close()


def _managed(platform: str) -> tuple[str, str]:
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
    return ("weak", f"{p}: " + ", ".join(weak)) if weak else ("set", str(p))


def check(states: list[Path], env=os.environ, uid: int | None = None, platform: str = sys.platform) -> list[dict]:
    """Try every door from inside this session. Each row: what, path, want, got, detail, ok.

    A secret must read as blocked or absent (inside the sandbox a denied file is not there at all); a STATE
    folder may show only ALLOWED names; a console's socket must answer when it runs; no escape socket may.
    """
    rows: list[dict] = []

    def row(what, path, want, got, detail=""):
        rows.append({"what": what, "path": str(path), "want": "/".join(want), "got": got, "detail": detail,
                     "ok": got in want})

    inside = env.get(SANDBOX_ENV) == "1"
    row("inside Claude Code's sandbox", "", ("yes",), "yes" if inside else "no",
        "" if inside else f"{SANDBOX_ENV} is not set: run this from a sandboxed session")
    got, detail = _managed(platform)
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
        got, why = _connect(str(s / AGENT_SOCKET))
        row("reach the agent socket", s / AGENT_SOCKET, ("open", "absent"), got, why)
    for path in ESCAPE_SOCKETS:
        if inside or os.path.lexists(path):
            got, why = _connect(path)
            row("reach an escape socket", path, ("blocked", "absent"), got, why)
    got, seen = _read_attempt(runtime_dir(env, uid))
    if got == "open" and not seen:
        got = "narrowed"   # the sandbox shows a denied folder as empty
    elif got == "blocked" and seen == "ENOENT":
        got = "absent"
    row("list the runtime folder", runtime_dir(env, uid), ("blocked", "narrowed", "absent"), got, seen)
    return rows


def render(rows: list[dict]) -> str:
    lines = [f"{'ok  ' if r['ok'] else 'FAIL'}  {r['got']:<9} {r['what']}{(' ' + r['path']) if r['path'] else ''}"
             + (f" ({r['detail']})" if r["detail"] and not r["ok"] else "") for r in rows]
    bad = sum(not r["ok"] for r in rows)
    lines.append("isolation holds" if not bad else f"isolation does NOT hold: {bad} finding(s)")
    return "\n".join(lines)
