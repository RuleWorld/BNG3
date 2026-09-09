"""Helpers for turning unavailable validation infrastructure into CI failures."""

from __future__ import annotations

import os

import pytest


def require_oracle(condition: bool, message: str) -> None:
    """Fail in strict CI mode, otherwise preserve the local skip contract."""

    if condition:
        return
    if os.environ.get("BNG3_CI_STRICT_ORACLES") == "1":
        pytest.fail(message)
    pytest.skip(message)
