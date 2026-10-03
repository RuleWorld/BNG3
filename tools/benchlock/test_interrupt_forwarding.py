#!/usr/bin/env python3
"""A caught wrapper signal must not unlock a live measured child."""
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
    result = subprocess.run([str(BL), "status"], env=env, capture_output=True,
                            text=True, check=True)
    match = re.search(r"capacity (\d+)  free (\d+)  in_use (\d+)", result.stdout)
    if not match:
        raise AssertionError(f"unrecognized benchlock status: {result.stdout}")
    return int(match.group(2)), result.stdout


def exercise_signal(root: Path, env: dict[str, str], signum: int) -> None:
    label = signal.Signals(signum).name
    pid_file = root / f"{label}.pid"
    log = root / f"{label}.log"
    code = (
        "import os,pathlib,signal,sys,time;"
        "signal.signal(signal.SIGINT, signal.SIG_IGN);"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));"
        "time.sleep(30)"
    )
    with log.open("w") as out:
        wrapper = subprocess.Popen(
            [str(BL), "acquire", "--agent", "signal-test",
             "--what", f"{label} child lifetime", "--", sys.executable,
             "-c", code, str(pid_file)],
            env=env, stdout=out, stderr=subprocess.STDOUT)

    child_pid = None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and wrapper.poll() is None:
            if pid_file.exists():
                child_pid = int(pid_file.read_text())
                break
            time.sleep(0.02)
        if child_pid is None:
            raise AssertionError(f"{label}: benchmark child did not start; {log.read_text()}")

        os.kill(wrapper.pid, signum)
        time.sleep(0.15)
        if wrapper.poll() is not None:
            raise AssertionError(f"{label}: wrapper exited instead of waiting for child")
        free, output = status(env)
        if free != 0:
            raise AssertionError(f"{label}: child lives but slot is free\n{output}")

        os.kill(child_pid, signal.SIGKILL)
        wrapper.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            free, output = status(env)
            if free == 1:
                return
            time.sleep(0.05)
        raise AssertionError(f"{label}: slot stayed held after child exit\n{output}")
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.wait()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bng3-benchlock-signal-") as tmp:
        root = Path(tmp)
        env = dict(os.environ, BENCHLOCK_DIR=str(root / "locks"),
                   BENCHLOCK_MAX="1", BENCHLOCK_POLL="0.02")
        for signum in (signal.SIGINT, signal.SIGTERM):
            exercise_signal(root, env, signum)
            print(f"PASS: wrapper forwarded {signal.Signals(signum).name}, "
                  "waited for child, and released slot after child exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
