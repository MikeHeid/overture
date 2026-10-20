"""What this machine still needs for Overture, with the command or link that sets each up (1.53.2).

INSTALL.md "What you need" is the list of record: a check added or dropped
there is added or dropped here. `scan()` asks only this machine: `shutil.which`,
the running interpreter, and on Linux or WSL one `systemctl --user` call with a
1 s timeout. It never touches the network. Standard library only, and nothing
happens on import, so the install banner (a 5 s hook) can run it on native
Windows too.

Each fix is a command for THIS platform; a third party's installer is named as
that party documents it, and where no one command is right only the link is given.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

TIMEOUT = 1.0   # seconds, per subprocess; scan() starts at most one
LINUX, WSL, MACOS, WINDOWS = "linux", "wsl", "macos", "windows"
OSRELEASE = Path("/proc/sys/kernel/osrelease")
APT = "   # Debian/Ubuntu; or your distribution's package manager"


def detect() -> str:
    """linux, wsl, macos or windows (native Windows Python; WSL is Linux with "microsoft" in its kernel)."""
    system = platform.system()
    if system == "Windows":
        return WINDOWS
    if system == "Darwin":
        return MACOS
    if os.environ.get("WSL_DISTRO_NAME"):
        return WSL
    try:
        if "microsoft" in OSRELEASE.read_text(encoding="utf-8", errors="replace").lower():
            return WSL
    except OSError:
        pass
    return LINUX


def _item(name: str, required: bool, ok: bool, why: str, fix: list[str], link: str) -> dict:
    return {"name": name, "required": required, "ok": ok, "why": why, "fix": fix, "link": link}


def _systemd_user() -> bool:
    """True when `systemctl --user` reaches a user manager within TIMEOUT."""
    if shutil.which("systemctl") is None:
        return False
    try:
        r = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def _base(plat: str) -> list[dict]:
    py_fix = {LINUX: ["sudo apt install python3" + APT], WSL: ["sudo apt install python3" + APT],
              MACOS: ["brew install python"], WINDOWS: []}[plat]
    items = [_item("Python 3.11 or newer", True, sys.version_info >= (3, 11),
                   f"the console, the kit and the hooks run on it (this is {platform.python_version()})",
                   py_fix, "https://www.python.org/downloads/")]
    if plat == WINDOWS:
        return items + [
            _item("Claude Code inside WSL", True, False,
                  "the console and its agent side run inside WSL, so run the Claude Code CLI there; "
                  "native Windows sessions get only the hooks, which stay silent",
                  ["wsl", "curl -fsSL https://claude.ai/install.sh | bash   # inside WSL"],
                  "https://code.claude.com/docs/en/setup"),
            _item("WSL", True, shutil.which("wsl") is not None, "the console server runs inside WSL2",
                  ["wsl --install"], "https://learn.microsoft.com/windows/wsl/install"),
            _item("Git for Windows (git and Git Bash)", True, shutil.which("git") is not None,
                  "agents use git for their own worktrees; Claude Code runs hooks in Git Bash, else PowerShell",
                  ["winget install --id Git.Git -e"], "https://git-scm.com/download/win"),
            _item("python3 on PATH", True, shutil.which("python3") is not None,
                  "the hooks run as `python3`; the Microsoft Store's Python provides it (a python.org "
                  "install gives only `python` and `py`, and `python3` then opens the Store)",
                  [], "https://apps.microsoft.com/search?query=python"),
            _item("gh, the GitHub CLI", False, shutil.which("gh") is not None,
                  "the PR tab, merging from it, and pruning an agent's worktree once its PR closes",
                  ["winget install --id GitHub.cli -e"], "https://cli.github.com"),
        ]
    pkg = (lambda name: [f"brew install {name}"]) if plat == MACOS else (lambda name: [f"sudo apt install {name}" + APT])
    items += [
        _item("git", True, shutil.which("git") is not None, "agents use it for their own worktrees",
              pkg("git"), "https://git-scm.com/downloads"),
        _item("gh, the GitHub CLI", False, shutil.which("gh") is not None,
              "the PR tab, merging from it, and pruning an agent's worktree once its PR closes",
              pkg("gh"), "https://cli.github.com"),
    ]
    if plat == MACOS:
        items.append(_item("launchd", True, shutil.which("launchctl") is not None,
                           "keeps the console server running (a LaunchAgent)", [],
                           "https://github.com/MikeHeid/overture/blob/main/INSTALL.md"))
    elif plat == WSL:
        items.append(_item("systemd --user", True, _systemd_user(),
                           "keeps the console server running; WSL starts systemd only when wsl.conf asks",
                           ["printf '[boot]\\nsystemd=true\\n' | sudo tee -a /etc/wsl.conf",
                            "wsl.exe --shutdown   # then open WSL again"],
                           "https://learn.microsoft.com/windows/wsl/systemd"))
    else:
        items.append(_item("systemd --user", True, _systemd_user(),
                           "keeps the console server running; `systemctl --user` must reach your user manager",
                           [], "https://github.com/MikeHeid/overture/blob/main/INSTALL.md"))
    return items


def _routes(plat: str) -> list[dict]:
    """The tools of the ways in, each optional and needed only for its own route (INSTALL.md)."""
    fixes = {
        "cloudflared": {MACOS: ["brew install cloudflared"], WINDOWS: ["winget install --id Cloudflare.cloudflared -e"]},
        "tailscale": {LINUX: ["curl -fsSL https://tailscale.com/install.sh | sh"],
                      WSL: ["curl -fsSL https://tailscale.com/install.sh | sh"],
                      WINDOWS: ["winget install --id Tailscale.Tailscale -e"]},
        "zerotier-cli": {LINUX: ["curl -s https://install.zerotier.com | sudo bash"],
                         WSL: ["curl -s https://install.zerotier.com | sudo bash"],
                         MACOS: ["brew install --cask zerotier-one"],
                         WINDOWS: ["winget install --id ZeroTier.ZeroTierOne -e"]},
    }
    rows = (("cloudflared", "for the Cloudflare Access route",
             "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"),
            ("tailscale", "for sign-in links on a Tailscale tailnet", "https://tailscale.com/download"),
            ("zerotier-cli", "for sign-in links with --listen on a ZeroTier network",
             "https://www.zerotier.com/download/"))
    return [_item(name, False, shutil.which(name) is not None, why, fixes[name].get(plat, []), link)
            for name, why, link in rows]


def scan(routes: bool = False, plat: str | None = None) -> list[dict]:
    """Every prerequisite for this platform, each {name, required, ok, why, fix, link}; `routes` adds the route tools."""
    plat = plat or detect()
    return _base(plat) + (_routes(plat) if routes else [])


def item_lines(it: dict) -> list[str]:
    """One item as the banner and `onboard.py prereqs` print it: what and why, then each fix, then the link."""
    tag = "required" if it["required"] else "optional"
    return ([f"  - {it['name']} ({tag}): {it['why']}"] + [f"      {c}" for c in it["fix"]]
            + [f"      {it['link']}"])


def missing_block(items: list[dict]) -> list[str]:
    """The banner's "Missing prerequisites" lines, or none when nothing is missing."""
    gone = [it for it in items if not it["ok"]]
    if not gone:
        return []
    return ["", "Missing prerequisites:"] + [line for it in gone for line in item_lines(it)]
