#!/usr/bin/env python3
"""Regression: a killed benchlock wrapper must not unlock a live measurement."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BL = Path(__file__).with_name("benchlock").resolve()


def status(env: dict[str, str]) -> tuple[int, str]:
    result = subprocess.run(
        [str(BL), "status"], env=env, capture_output=True, text=True, check=True
    )
    first = result.stdout.splitlines()[0]
    match = re.search(r"capacity (\d+)  free (\d+)  in_use (\d+)", first)
    if not match:
        raise AssertionError(f"unrecognized benchlock status: {result.stdout}")
    return int(match.group(2)), result.stdout


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bng3-benchlock-fd-") as tmp:
        root = Path(tmp)
        pid_file = root / "child.pid"
        log = root / "holder.log"
        env = dict(
            os.environ,
            BENCHLOCK_DIR=str(root / "locks"),
            BENCHLOCK_MAX="1",
            BENCHLOCK_POLL="0.02",
        )
        code = (
            "import os,pathlib,sys,time;"
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));"
            "time.sleep(30)"
        )
        with log.open("w") as out:
            wrapper = subprocess.Popen(
                [
                    str(BL),
                    "acquire",
                    "--agent",
                    "signal-test",
                    "--what",
                    "child fd lifetime",
                    "--",
                    sys.executable,
                    "-c",
                    code,
                    str(pid_file),
                ],
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
            )

        child_pid = None
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and wrapper.poll() is None:
                if pid_file.exists():
                    child_pid = int(pid_file.read_text())
                    break
                time.sleep(0.02)
            if child_pid is None:
                print(f"FAIL: benchmark child did not start; log: {log.read_text()}")
                return 1

            wrapper.kill()
            wrapper.wait()
            free, output = status(env)
            if free != 0:
                print(
                    "FAIL: killing benchlock released slot while measured child "
                    f"still lived (free={free})"
                )
                print(output, end="")
                return 1

            print("PASS: live child retained slot after wrapper SIGKILL")
        finally:
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if wrapper.poll() is None:
                wrapper.kill()
                wrapper.wait()

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            free, output = status(env)
            if free == 1:
                print("PASS: slot released after measured child exited")
                return 0
            time.sleep(0.05)
        print("FAIL: slot stayed held after child exit")
        print(output, end="")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
