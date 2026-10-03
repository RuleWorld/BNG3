#!/usr/bin/env python3
"""Advisory failures stay explicit and worktree candidates cover this host."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import patch

BL = Path(__file__).with_name("benchlock").resolve()
loader = importlib.machinery.SourceFileLoader("benchlock_module", str(BL))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


def main() -> int:
    failed_ps = subprocess.CompletedProcess(
        ["ps", "-axo", "pid=,command="], 1, "", "permission denied")
    with patch.object(module.subprocess, "run", return_value=failed_ps):
        try:
            module.snapshot()
        except RuntimeError as exc:
            assert "permission denied" in str(exc)
        else:
            raise AssertionError("nonzero ps exit was silently accepted")

    module._BASELINE_ERROR = "ps exited 1: permission denied"
    message = module.cotenant_advisory({}, "test")
    assert "class=ERROR" in message and "class=NONE" not in message, message
    module._BASELINE_ERROR = ""

    for command in (
        "/private/tmp/bng3-20261002-performance/custom_tool",
        "/Users/akutuva/Documents/Codex/bng3-main/custom_tool",
        "/Users/akutuva/Documents/BioNetGen/BNG3-netgen/custom_tool",
    ):
        assert module.is_candidate(command), command
    assert not module.is_candidate("/private/tmp/unrelated/custom_tool")
    print("PASS: ps failure is explicit; this host's BNG3 worktree paths match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
