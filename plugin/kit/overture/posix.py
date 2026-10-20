"""Refuse by name, before an import that fails there, to run a kit entry point on native Windows (1.53.2).

The console's modules lock with fcntl and talk over Unix sockets, so on native
Windows Python an entry script would die in its imports with a traceback. Each
entry script calls `require` first instead. Standard library only, and nothing
happens on import: this module must load on Windows to say why nothing else will.
"""

import os
import sys

WHY = "Overture's console needs a POSIX system; on Windows run Claude Code inside WSL (docs/features/hosting.md#windows)."


def missing() -> bool:
    """True where the console cannot run: not POSIX, or no fcntl (native Windows Python has neither)."""
    if os.name != "posix":
        return True
    try:
        import fcntl  # noqa: F401
    except ImportError:
        return True
    return False


def require(prog: str) -> None:
    """Exit 2 with one line on stderr naming `prog` and the fix, unless this system can run the console."""
    if missing():
        sys.stderr.write(f"{prog}: {WHY}\n")
        sys.exit(2)
