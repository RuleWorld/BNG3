"""Pytest fixtures for Issue 154 release acceptance suite."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))
