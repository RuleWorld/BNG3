"""Command-line entry point for the locked external-oracle checkout helper."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.ci.oracle_sources import main

if __name__ == "__main__":
    raise SystemExit(main())
