#!/usr/bin/env python3
"""An event must not claim slot release while a descendant holds the fd."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path

BL = Path(__file__).with_name("benchlock").resolve()


def status(env: dict[str, str]) -> tuple[int, str]:
    result = subprocess.run(
        [str(BL), "status"], env=env, capture_output=True, text=True, check=True
    )
    match = re.search(r"capacity (\d+)  free (\d+)  in_use (\d+)", result.stdout)
    if not match:
        raise AssertionError(f"unrecognized benchlock status: {result.stdout}")
    return int(match.group(2)), result.stdout


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bng3-benchlock-descendant-") as tmp:
        root = Path(tmp)
        pid_file = root / "descendant.pid"
        log = root / "wrapper.log"
        env = dict(
            os.environ,
            BENCHLOCK_DIR=str(root / "locks"),
            BENCHLOCK_MAX="1",
            BENCHLOCK_POLL="0.02",
        )
        shell = '/bin/sleep 30 & echo $! > "$1"'
        with log.open("w") as out:
            wrapper = subprocess.Popen(
                [
                    str(BL),
                    "acquire",
                    "--agent",
                    "descendant-test",
                    "--what",
                    "inherited descriptor",
                    "--",
                    "sh",
                    "-c",
                    shell,
                    "sh",
                    str(pid_file),
                ],
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
            )

        descendant_pid = None
        try:
            wrapper.wait(timeout=5)
            if not pid_file.exists():
                raise AssertionError(
                    f"wrapped shell did not start sleep: {log.read_text()}"
                )
            descendant_pid = int(pid_file.read_text())
            output = log.read_text()
            if "BENCHLOCK_EVENT COMMAND_EXITED" not in output:
                raise AssertionError(
                    "event must say direct command exited, not that the slot is "
                    f"free while a descendant lives:\n{output}"
                )
            if "BENCHLOCK_EVENT RELEASED" in output:
                raise AssertionError(f"ambiguous RELEASED event:\n{output}")

            free, status_output = status(env)
            if free != 0:
                raise AssertionError(
                    "slot freed before inherited descendant exited\n" + status_output
                )
            os.kill(descendant_pid, signal.SIGKILL)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                free, status_output = status(env)
                if free == 1:
                    print(
                        "PASS: COMMAND_EXITED is distinct from slot release; "
                        "descendant held slot until exit"
                    )
                    return 0
                time.sleep(0.05)
            raise AssertionError(
                "slot stayed held after descendant exit\n" + status_output
            )
        finally:
            if descendant_pid is not None:
                try:
                    os.kill(descendant_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if wrapper.poll() is None:
                wrapper.kill()
                wrapper.wait()


if __name__ == "__main__":
    raise SystemExit(main())
