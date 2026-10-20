#!/usr/bin/env python3
"""Command-line entry for `overture.rulecheck`: which locked rulings a change breaks, with no server (CI)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overture.posix import require  # noqa: E402
require("rulecheck.py")   # 1.53.2: before the imports below, which fail on native Windows
from overture.rulecheck import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
