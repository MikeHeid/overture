#!/usr/bin/env python3
"""Command-line entry for `overture.server`: see that module for the two doors and the Access check."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    if sys.argv[1:2] and sys.argv[1] in ("daemon", "service", "status", "health"):
        import hosting   # D1: run it detached, as a service, or ask how it is; the server never imports this
        sys.exit(hosting.main(sys.argv[1:]))
    if "--all" in sys.argv[1:]:   # K3: the one server for every project in server.json
        from overture.multiserver import main as multi_main  # noqa: E402
        sys.exit(multi_main())
    from overture.server import main  # noqa: E402  (the single-project server, unchanged)
    sys.exit(main())
