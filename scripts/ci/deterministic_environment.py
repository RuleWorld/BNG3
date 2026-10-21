"""Make the artifacts a harness run produces reproducible.

Python randomises the hash seed of every fresh interpreter, and the Atomizer
emits part of its output in set-iteration order.  Two runs of the same case
can therefore produce byte-different BNGL, which makes the campaign's
artifact diffs meaningless: a difference in the text is indistinguishable
from a difference in the conversion.

The harness pins the seed that the processes producing the artifacts use, and
records the effective seed in the report so that a reader can tell whether a
run's artifacts are comparable with another run's.

``PYTHONHASHSEED`` is read when the interpreter starts, so setting it in the
environment cannot change a running process.  A forked worker inherits the
parent's seed, so the harness itself has to start with the fixed seed:
re-executing the harness once, before it does any work, is the only way to
guarantee that.  The re-execution is invisible apart from the process id and
never changes the harness's arguments or its output.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FIXED_HASH_SEED = "0"
_REEXEC_MARKER = "BNG3_HARNESS_FIXED_HASH_SEED"


def startup_hash_seed() -> str:
    """Return the hash seed this interpreter started with, or ``random``."""

    value = os.environ.get("PYTHONHASHSEED", "").strip()
    return value if value.isdigit() else "random"


# Captured at import time, before anything can change the environment.
STARTUP_HASH_SEED = startup_hash_seed()


def fixed_hash_seed_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environment whose interpreter hash seed is fixed."""

    environment = dict(os.environ if base is None else base)
    environment["PYTHONHASHSEED"] = FIXED_HASH_SEED
    return environment


def _reexecutable() -> bool:
    """Report whether this process can re-execute itself with the same script."""

    script = sys.argv[0] if sys.argv else ""
    return bool(script) and script.endswith(".py") and Path(script).is_file()


def ensure_fixed_hash_seed() -> str:
    """Pin this interpreter's hash seed and return the seed in effect.

    The seed is forced for every process the harness starts afterwards.  When
    this interpreter did not start with the fixed seed, the harness is
    re-executed once with it, because a forked worker inherits the parent's
    seed and the parent's seed is the one the artifacts depend on.
    """

    os.environ["PYTHONHASHSEED"] = FIXED_HASH_SEED
    if STARTUP_HASH_SEED == FIXED_HASH_SEED:
        return FIXED_HASH_SEED
    if os.environ.get(_REEXEC_MARKER) or not _reexecutable():
        return STARTUP_HASH_SEED
    os.environ[_REEXEC_MARKER] = "1"
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, *sys.argv])
    raise SystemExit(0)
