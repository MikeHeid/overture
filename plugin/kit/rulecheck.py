#!/usr/bin/env python3
"""Command-line entry for `overture.rulecheck`: which locked rulings a change breaks, with no server (CI)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overture.rulecheck import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
