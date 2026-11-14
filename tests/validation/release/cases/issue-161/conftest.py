"""Pytest configuration for Issue #161 test suite."""

import sys
from pathlib import Path

_CASE_DIR = str(Path(__file__).resolve().parent)
if _CASE_DIR not in sys.path:
    sys.path.insert(0, _CASE_DIR)
