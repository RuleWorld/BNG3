"""One bounded process boundary for native action execution."""

import os
from pathlib import Path
import subprocess
import sys

from bionetgen.core.exc import BNGRunError
from bionetgen.core.tools.result import BNGResult


def _write_log(log_file, text, input_path):
    if log_file is None:
        return
    requested = os.fspath(log_file)
    destination = Path(requested).absolute()
    if destination.is_dir() or requested.endswith(
        tuple(separator for separator in (os.sep, os.altsep) if separator)
    ):
        destination /= Path(input_path).stem + ".log"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def execute_native(input_path, output, *, suppress=False, timeout=None, log_file=None):
    import bionetgen
    from bionetgen.model import _cpp

    worker = Path(__file__).with_name("_native_cli_worker.py")
    command = [
        sys.executable,
        str(worker),
        str(input_path),
        str(Path(bionetgen.__file__).resolve()),
        str(Path(_cpp.__file__).resolve()),
        "1" if log_file is not None or not suppress else "0",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=output,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        _write_log(log_file, partial, input_path)
        raise
    _write_log(log_file, completed.stdout, input_path)
    if not suppress:
        print(completed.stdout, end="")
    if completed.returncode:
        raise BNGRunError(
            command,
            message="BNG3 native action execution failed",
            stdout=completed.stdout,
        )
    result = BNGResult(str(output))
    result.process_return = completed.returncode
    result.output = completed.stdout.splitlines()
    return result
