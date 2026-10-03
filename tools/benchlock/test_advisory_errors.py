#!/usr/bin/env python3
"""Advisory failures stay explicit and worktree candidates cover this host."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
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

    # ps reports argv but not cwd. A generic long-lived process started in the
    # BNG3 checkout must not be reported as a worktree match when argv omits it.
    with subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=Path(__file__).resolve().parents[1],
    ) as process:
        try:
            command = module.snapshot()[process.pid]
            assert str(Path(__file__).resolve().parents[1]) not in command, command
            assert not module.is_candidate(command), command
        finally:
            process.terminate()
            process.wait(timeout=5)

    print("PASS: ps errors stay explicit; argv checkout paths match; cwd-only "
          "processes remain outside the advisory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
