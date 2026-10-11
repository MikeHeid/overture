"""One-shot post-install / post-upgrade reminder (1.0.0).

Prints an Overture banner and the agent-registration commands exactly once per
installed version — then writes a flag so it stays silent on later sessions.

The flag lives at `${XDG_STATE_HOME:-~/.local/state}/overture/install-notice-seen-<VERSION>`.
When the plugin upgrades (zip replaces this hook file), the version embedded here
changes and the flag path with it, so the banner fires again on the first session
after the upgrade. On the version it was written for, it never fires twice.

The banner names the registration path for Linux / macOS, WSL on Windows, and
PowerShell on Windows that drives WSL for the server side (the server runs on
POSIX; Windows users host it in WSL).

Trust: this hook does nothing more than stdout + one flag file write. It never
reads project state and never fails the session.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

def _read_version() -> str:
    """Read the plugin's version from `kit/overture/__init__.py` without importing it.

    The hook runs with its own PWD and no sys.path tweaks; a plain import would miss, and we would
    rather name the real version in the banner than fall through to a placeholder.
    """
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "kit" / "overture" / "__init__.py",):
        try:
            txt = candidate.read_text(encoding="utf-8")
            for line in txt.splitlines():
                if line.startswith("__version__"):
                    rhs = line.split("=", 1)[1].strip()
                    if rhs and rhs[0] in "\"'":
                        quote = rhs[0]
                        end = rhs.find(quote, 1)
                        if end > 0:
                            return rhs[1:end]
                    return rhs
        except OSError:
            continue
    return "1.0.0"


VERSION = _read_version()

BANNER = r"""
    ___                __
   / _ \_  _____ ____/ /___  _______
  / // / |/ / -_) __/ __/ // / __/ -_)
 /____/|___/\__/_/  \__/\_,_/_/  \__/     v{ver}
                                           the AI-operations cockpit
""".lstrip("\n")


def _state_root() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(base) / "overture"


def _flag_path() -> Path:
    return _state_root() / f"install-notice-seen-{VERSION}"


def _already_shown() -> bool:
    try:
        return _flag_path().exists()
    except OSError:
        return True   # cannot read the flag → err on the side of silence


def _prior_versions() -> list[str]:
    """Every version this hook has fired on before, oldest first.

    Enables install-vs-upgrade branching: an empty list means first install, any entry
    means an upgrade (or downgrade). A rollback to an older version whose flag was
    deleted re-fires naturally through `_already_shown`.
    """
    try:
        return sorted(
            p.name.removeprefix("install-notice-seen-")
            for p in _state_root().glob("install-notice-seen-*")
            if p.is_file() and p.name != f"install-notice-seen-{VERSION}"
        )
    except OSError:
        return []


def _mark_shown() -> None:
    try:
        _state_root().mkdir(parents=True, exist_ok=True)
        _flag_path().write_text(f"shown-at={os.getpid()}\n", encoding="utf-8")
    except OSError:
        pass   # cannot write → best effort; next session will see it again


def _is_windows_native() -> bool:
    """True on Windows Python (not WSL). WSL identifies as Linux."""
    return platform.system() == "Windows"


KIT = Path(__file__).resolve().parent.parent / "kit"   # the kit this plugin carries, wherever it was installed
JOIN = "https://github.com/MikeHeid/overture/blob/main/docs/JOIN.md"


def _install_lines() -> list[str]:
    """First-install banner body: the one next step, onboarding, and where the server comes from.

    Every command printed here must exist as printed (test_onboard.InstallNoticeTests).
    """
    lines: list[str] = [
        "Welcome to Overture " + VERSION + ".",
        "",
        "Next step: set up the console for this project. In the project, type:",
        "",
        "    /overture:console-onboard",
        "",
        "It asks for the project name and your Cloudflare details, writes the config,",
        "and prints the commands that install and start the console server as a user",
        "service. You run those yourself; nothing is installed behind your back.",
    ]
    if _is_windows_native():
        lines += [
            "",
            "  On Windows the server runs inside WSL2 (it needs POSIX file locks). Run the",
            "  printed install commands in your WSL shell, e.g. `wsl -d Ubuntu-24.04`.",
        ]
    lines += [
        "",
        "  Already running Overture for another project? Join this one to the same",
        "  server instead: " + JOIN,
        "  Optional: set your master agent's name in /plugin -> overture -> configure.",
        "",
        "  This reminder shows once per version.",
    ]
    return lines


def _upgrade_lines(prior: list[str]) -> list[str]:
    """Upgrade banner body: copy the new kit to the installed place and restart the server(s).

    Updating the plugin refreshes only the plugin's files; a running server keeps the kit
    `deploy/install.sh` copied, until install.sh copies the new one and restarts the unit.
    """
    from_ver = prior[-1] if prior else "an earlier version"
    install = KIT / "deploy" / "install.sh"
    lines: list[str] = [
        f"Upgraded to Overture {VERSION} (from {from_ver}).",
        "",
        "Your console server still runs the old kit until you re-install and restart it.",
        "For each onboarded project (this copies the new kit and restarts <name>-console):",
        "",
        f'    bash "{install}" --project <project dir> --start',
        "",
        "  Running the main server for several projects (docs/JOIN.md)? After install.sh:",
        "",
        "    systemctl --user restart overture-console",
    ]
    if _is_windows_native():
        lines += ["", "  On Windows, run these inside WSL."]
    lines += [
        "",
        "  Changelog: https://github.com/MikeHeid/overture/blob/main/CHANGELOG.md",
        "  This reminder shows once per version.",
    ]
    return lines


def _instructions() -> str:
    prior = _prior_versions()
    lines = _upgrade_lines(prior) if prior else _install_lines()
    return "\n".join(lines)


def main() -> int:
    if _already_shown():
        return 0
    # SessionStart hooks on Claude Code print context the session reads; the user sees it too.
    sys.stdout.write("\n")
    sys.stdout.write(BANNER.format(ver=VERSION))
    sys.stdout.write("\n")
    sys.stdout.write(_instructions())
    sys.stdout.write("\n")
    _mark_shown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
