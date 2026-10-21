#!/usr/bin/env python3
"""The hook other agent vendors run (Wave 4, owner V1-V4): `adapter_hook.py VENDOR EVENT`.

    VENDOR  codex | cursor | copilot
    EVENT   session-start | edit

`agent.py adapter install --vendor VENDOR` writes it into the vendor's user
config (V3). It reads the vendor's hook input on stdin and prints the note in
the vendor's shape (`overture/adapters.py`), or nothing to add.

**It fails open, always.** Any error, any input it cannot read, a native Windows
Python without the kit's POSIX reads: it prints the vendor's "nothing to add"
and exits 0. Copilot CLI blocks a tool when its preToolUse hook exits non-zero,
so none is ever installed there, and this never exits non-zero anyway. It never
prints a permission decision: it informs, it does not decide (V2).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True   # never leave a __pycache__ in the installed kit
sys.path.insert(0, str(Path(__file__).resolve().parent))   # this kit, never a project's


def main(argv: list[str]) -> int:
    vendor, event = (argv + ["", ""])[:2]
    quiet = "" if vendor == "codex" else "{}"
    try:
        import json

        from overture import adapters as AD
        raw = sys.stdin.read(AD.MAX_INPUT + 1)
        text = AD.note(vendor, event, json.loads(raw)) if raw.strip() and len(raw) <= AD.MAX_INPUT else None
        out = AD.render(vendor, event, text)
    except Exception:  # noqa: BLE001 - fail open: an adapter never costs the owner a session or an edit
        out = quiet
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
