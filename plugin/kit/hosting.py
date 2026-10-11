#!/usr/bin/env python3
"""Run the one console server (`server.py --all`) in the foreground, as a daemon, or as a service (D1-D3).

    server.py --all                      foreground; Ctrl+C stops it (unchanged)
    server.py daemon start|stop          detached, with a pid file and a log file
    server.py service install|uninstall  a systemd user unit (Linux, WSL); launchd comes next (D2)
    server.py status                     running? which mode? pid, port per project, last start
    server.py health                     per project: door, agent socket, version skew; linger; stale files

`status` and `health` only read: they never start anything. The server process never imports this file (it
starts processes, which the server must not do), so `server.py --all` is exactly what it was.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from overture import serverfile as SF  # noqa: E402

UNIT = "overture-console.service"
KIT = Path(__file__).resolve().parent
PLAIN = re.compile(r"^/[A-Za-z0-9_./-]*\Z")   # a path a systemd unit can carry safely, as deploy/install.sh holds
LOG_MAX = 5 << 20


def run_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")) / "overture"


def pid_file() -> Path:
    return run_dir() / "server.pid"


def log_file() -> Path:
    return run_dir() / "server.log"


def unit_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")) / "systemd" / "user" / UNIT


def _systemctl(*args: str) -> tuple[int, str]:
    """`systemctl --user ARGS`: (exit code, output); 127 when systemctl is not there (macOS, a bare container)."""
    try:
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=20, check=False)
    except FileNotFoundError:
        return 127, "systemctl is not installed here"
    except (OSError, subprocess.SubprocessError) as e:
        return 126, str(e)
    return r.returncode, (r.stdout + r.stderr).strip()


# -- what is running -------------------------------------------------------------------------------------

def _cmdline(pid: int) -> list[str] | None:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace").rstrip("\0").split("\0")
    except OSError:
        pass
    try:
        r = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.split() if r.returncode == 0 and r.stdout.strip() else None


def is_our_server(pid: int) -> bool:
    """Whether `pid` is alive AND is `server.py --all`: a recycled pid is never mistaken for it."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    cmd = _cmdline(pid)
    return bool(cmd) and any(a.endswith("server.py") for a in cmd) and "--all" in cmd


def read_pid() -> dict | None:
    """The pid file's record, or None when absent or unreadable."""
    try:
        doc = json.loads(pid_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("pid"), int) else None


def service_state() -> str:
    """'active', 'inactive', 'failed', 'not installed', or 'unavailable' (no systemd here)."""
    if not unit_path().exists():
        return "not installed"
    code, out = _systemctl("is-active", UNIT)
    if code in (126, 127):
        return "unavailable"
    return out.splitlines()[0] if out else "inactive"


def agent_socket(sf: Path) -> Path:
    from overture import multiserver as MS
    return MS.socket_path(sf)


def socket_answers(sock: Path) -> dict | None:
    """The server's /health over its agent socket, or None when nothing answers there."""
    if not sock.exists():
        return None
    from overture import server as SV
    try:
        code, out = SV.agent_request(sock, "GET", "/health")
    except OSError:
        return None
    return out if code == 200 and isinstance(out, dict) else None


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def mode() -> tuple[str, int | None]:
    """('service' | 'daemon' | 'stopped', pid)."""
    if service_state() == "active":
        code, out = _systemctl("show", UNIT, "-p", "MainPID", "--value")
        try:
            pid = int(out.strip()) if code == 0 else None
        except ValueError:
            pid = None
        return "service", pid or None
    rec = read_pid()
    if rec and is_our_server(rec["pid"]):
        return "daemon", rec["pid"]
    return "stopped", None


def projects(sf: Path) -> dict:
    try:
        return SF.load(sf).get("projects", {})
    except (SF.ServerFileError, OSError, ValueError):
        return {}


# -- daemon --------------------------------------------------------------------------------------------------

def daemon_start(sf: Path) -> int:
    svc = service_state()
    if svc == "active":
        return _refuse(f"the service {UNIT} is running; stop it first (`systemctl --user stop {UNIT}`) or use "
                       f"`server.py service uninstall`. One server at a time")
    m, pid = mode()
    if m == "daemon":
        return _refuse(f"already running as a daemon (pid {pid}); `server.py daemon stop` first")
    if not projects(sf):
        return _refuse(f"{sf} holds no projects (or cannot be read); add one with `agent.py server add` "
                       f"(docs/JOIN.md)")
    rd = run_dir()
    rd.mkdir(parents=True, exist_ok=True)
    os.chmod(rd, 0o700)
    log = log_file()
    if log.exists() and log.stat().st_size > LOG_MAX:
        log.replace(log.with_suffix(".log.1"))
    sock = agent_socket(sf)
    with open(log, "ab") as out:
        proc = subprocess.Popen([sys.executable, str(KIT / "server.py"), "--all", "--server-file", str(sf)],
                                stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True,
                                close_fds=True)
    rec = {"pid": proc.pid, "mode": "daemon", "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "server_file": str(sf)}
    tmp = pid_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(rec), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(pid_file())
    for _ in range(50):
        if proc.poll() is not None:
            pid_file().unlink(missing_ok=True)
            return _refuse(f"the server exited at once (code {proc.returncode}); see {log}")
        if socket_answers(sock) is not None:
            print(f"daemon started: pid {proc.pid}, log {log}")
            return 0
        time.sleep(0.1)
    print(f"daemon started (pid {proc.pid}) but its agent door is not answering yet; see {log}", file=sys.stderr)
    return 0


def daemon_stop() -> int:
    if service_state() == "active":
        return _refuse(f"the service {UNIT} is running, not a daemon; stop it with `systemctl --user stop {UNIT}`")
    rec = read_pid()
    if not rec:
        return _refuse("no daemon is recorded as running")
    pid = rec["pid"]
    if not is_our_server(pid):
        pid_file().unlink(missing_ok=True)
        print(f"cleaned up a stale pid file (pid {pid} is not the server)")
        return 0
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        if not is_our_server(pid):
            pid_file().unlink(missing_ok=True)
            print(f"daemon stopped (pid {pid})")
            return 0
        time.sleep(0.1)
    return _refuse(f"pid {pid} did not stop within 10 s after SIGTERM; it is left running")


# -- service -------------------------------------------------------------------------------------------------

def render_unit(sf: Path, python: str | None = None) -> str:
    """The unit file text: plain values only, refused by name when a path holds a character systemd treats."""
    tpl = (KIT / "deploy" / "overture-console.service.in").read_text(encoding="utf-8")
    vals = {"KIT": str(KIT), "PYTHON": python or sys.executable, "SERVER_FILE": str(sf)}
    for k, v in vals.items():
        if not PLAIN.match(v):
            raise ValueError(f"the {k.lower().replace('_', ' ')} path {v!r} holds a character a systemd unit "
                             f"cannot take safely; only letters, digits and _ . / - are allowed")
    for k, v in vals.items():
        tpl = tpl.replace(f"@{k}@", v)
    return tpl


def service_install(sf: Path, start: bool) -> int:
    if sys.platform == "darwin":
        return _refuse("macOS has no systemd; the launchd installer arrives next (D2). Use `server.py daemon start`")
    m, pid = mode()
    if m == "daemon":
        return _refuse(f"a daemon is running (pid {pid}); `server.py daemon stop` first. One server at a time")
    if not projects(sf):
        return _refuse(f"{sf} holds no projects; add one with `agent.py server add` (docs/JOIN.md)")
    try:
        text = render_unit(sf)
    except ValueError as e:
        return _refuse(str(e))
    up = unit_path()
    up.parent.mkdir(parents=True, exist_ok=True)
    up.write_text(text, encoding="utf-8")
    code, out = _systemctl("daemon-reload")
    if code in (126, 127):
        return _refuse(f"the unit was written to {up}, but {out}")
    _systemctl("enable", UNIT)
    print(f"unit: {up}")
    if start:
        code, out = _systemctl("restart", UNIT)
        print("started" if code == 0 else f"could not start: {out}")
        return 0 if code == 0 else 1
    print(f"installed, not started: `systemctl --user start {UNIT}`, or re-run with --start")
    return 0


def service_uninstall() -> int:
    up = unit_path()
    if not up.exists():
        return _refuse(f"{UNIT} is not installed")
    _systemctl("disable", "--now", UNIT)
    up.unlink()
    _systemctl("daemon-reload")
    print(f"removed {up}")
    return 0


# -- status and health -----------------------------------------------------------------------------------------

def status(sf: Path) -> dict:
    m, pid = mode()
    projs = projects(sf)
    rec = read_pid()
    sock = agent_socket(sf)
    out = {"mode": m, "pid": pid, "service": service_state(),
           "answering": socket_answers(sock) is not None, "server_file": str(sf),
           "projects": {n: {"port": p.get("port"), "hostname": p.get("hostname"), "port_open": port_open(p["port"])
                            if isinstance(p.get("port"), int) else False} for n, p in projs.items()}}
    if m == "daemon" and rec:
        out["started_at"] = rec.get("started_at")
    if m == "service":
        code, ts = _systemctl("show", UNIT, "-p", "ActiveEnterTimestamp", "--value")
        out["started_at"] = ts.strip() if code == 0 else None
    return out


def health(sf: Path) -> dict:
    """What is wrong, in words. Cleans a stale pid file or socket left by a dead process (nothing else)."""
    problems: list[str] = []
    cleaned: list[str] = []
    st = status(sf)
    rec = read_pid()
    if rec and not is_our_server(rec["pid"]) and st["mode"] != "daemon":
        pid_file().unlink(missing_ok=True)
        cleaned.append(f"stale pid file (pid {rec['pid']} is not the server)")
    sock = agent_socket(sf)
    if st["mode"] == "stopped" and sock.exists() and socket_answers(sock) is None:
        sock.unlink(missing_ok=True)
        cleaned.append(f"stale socket {sock}")
    if st["mode"] == "stopped":
        problems.append("the server is not running: `server.py daemon start`, or `server.py service install --start`")
    elif not st["answering"]:
        problems.append(f"the server is running but its agent door ({sock}) is not answering")
    for name, p in st["projects"].items():
        if st["mode"] != "stopped" and not p["port_open"]:
            problems.append(f"{name}: its owner door is not listening on port {p['port']} (see the log for a refusal)")
    h = socket_answers(sock) or {}
    want = (KIT / "VERSION").read_text().strip() if (KIT / "VERSION").exists() else None
    if h.get("version") and want and h["version"] != want:
        problems.append(f"version skew: the running server is {h['version']}, the installed kit is {want}; restart it")
    linger = None
    if sys.platform.startswith("linux"):
        try:
            r = subprocess.run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger", "--value"],
                               capture_output=True, text=True, timeout=5, check=False)
            linger = r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            linger = None
        if st["service"] != "not installed" and linger == "no":
            problems.append("linger is off, so the service stops when you log out: `loginctl enable-linger $USER`")
    return {**st, "version": h.get("version"), "linger": linger, "problems": problems, "cleaned": cleaned,
            "ok": not problems}


def _refuse(why: str) -> int:
    print(f"refused: {why}", file=sys.stderr)
    return 1


def _print(doc: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(doc, indent=2))
        return
    print(f"mode: {doc['mode']}" + (f" (pid {doc['pid']})" if doc.get("pid") else "")
          + f" · service: {doc['service']} · agent door: {'answering' if doc['answering'] else 'not answering'}")
    if doc.get("started_at"):
        print(f"started: {doc['started_at']}")
    for n, p in doc["projects"].items():
        print(f"  {n}: port {p['port']} {'open' if p['port_open'] else 'closed'} ({p['hostname']})")
    if not doc["projects"]:
        print("  no projects in server.json")
    for k in ("version", "linger"):
        if doc.get(k):
            print(f"{k}: {doc[k]}")
    for c in doc.get("cleaned", []):
        print(f"cleaned: {c}")
    for p in doc.get("problems", []):
        print(f"problem: {p}")
    if "ok" in doc and doc["ok"]:
        print("healthy")


def main(argv: list[str] | None = None) -> int:
    if os.name != "posix":
        print("overture: hosting commands are POSIX-only; run them inside WSL, Linux or macOS", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(prog="server.py", description="Run the one console server.")
    ap.add_argument("--server-file", type=Path, help="default: server.json beside your registry")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daemon", help="run detached, with a pid file and a log")
    d.add_argument("action", choices=("start", "stop"))
    s = sub.add_parser("service", help="a systemd user unit (Linux, WSL)")
    s.add_argument("action", choices=("install", "uninstall"))
    s.add_argument("--start", action="store_true", help="install: also start it now")
    for name in ("status", "health"):
        x = sub.add_parser(name, help="read-only; starts nothing")
        x.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    sf = Path(a.server_file or SF.location())
    if a.cmd == "daemon":
        return daemon_start(sf) if a.action == "start" else daemon_stop()
    if a.cmd == "service":
        return service_install(sf, a.start) if a.action == "install" else service_uninstall()
    doc = status(sf) if a.cmd == "status" else health(sf)
    _print(doc, a.json)
    return 0 if a.cmd == "status" or doc["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
