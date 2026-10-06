"""Host-contention admission: measure the noise floor, and serialise against peers.

This host is shared. Independent measurement on it found the 1-minute load
average moving inside a band of 70 to 131, with 46 to 74 runnable threads,
which is enough load variation to manufacture any speedup a lane wants to
report. Two responses live here.

**Admission.** The repository already carries a host-wide benchmark lock
(`tools/benchlock/benchlock`) that limits how many timing-sensitive benchmarks
run at once, regardless of which lane owns them. This module wraps that tool
when it is present, so a GPU measurement joins the same protocol as every other
benchmark on the host rather than inventing a second one. When the lock is
absent, the run proceeds but says so in its report: a measurement on an
unserialised host is still valid, but it is weaker evidence, and the report must
not pretend otherwise.

**Measurement of the noise floor.** Admitting a benchmark does not make the host
quiet. The harness therefore samples the host state around every round and
reports the drift. This is a different fact from the A/A null band - the null
band measures the noise that actually reached the arms, while this measures the
environment they ran in - and both are recorded, because a large effect inside a
band measured during a load spike deserves more suspicion than the same effect
inside a band measured during a quiet window.

The load readings come from `getloadavg` (POSIX, stdlib) and, where the platform
allows it, from the number of runnable threads. A runnable count is a better
contention signal than a load average because a load average is an exponentially
smoothed quantity that lags the moment a benchmark is actually running.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

_LOCK_RELATIVE = os.path.join("tools", "benchlock", "benchlock")


def _repo_root() -> str:
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return here


def loadavg() -> tuple[float, float, float]:
    """(1, 5, 15)-minute load averages, or NaNs where unavailable."""
    try:
        return os.getloadavg()
    except (AttributeError, OSError):
        return (float("nan"),) * 3


def runnable_threads() -> int | None:
    """Count runnable threads, or None where the platform cannot say.

    On Linux this is the sum of the runnable and uninterruptible states from
    /proc/loadavg's runnable field plus the process count; the cheap portable
    proxy used here is the /proc/stat run-queue delta, which is not available
    everywhere. Returning None is a legitimate answer and the caller records it,
    rather than substituting a load average and calling it a thread count.
    """
    try:
        with open("/proc/loadavg", encoding="utf-8") as handle:
            fields = handle.read().split()
        # /proc/loadavg's second field is runnable/total; total is a long-lived
        # constant on Linux, so the ratio is not a queue depth. Use it only as
        # a coarse signal and label it as such.
        running, _, total = fields[3].partition("/")
        return int(running)
    except (OSError, IndexError, ValueError):
        return None


@dataclass
class HostSample:
    """The host state at one instant."""

    t: float
    loadavg: tuple[float, float, float]
    runnable: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "t": self.t,
            "loadavg_1min": self.loadavg[0],
            "loadavg_5min": self.loadavg[1],
            "loadavg_15min": self.loadavg[2],
            "runnable_threads": self.runnable,
        }


def sample() -> HostSample:
    return HostSample(
        t=time.monotonic(), loadavg=loadavg(), runnable=runnable_threads()
    )


@dataclass
class ContentionTrace:
    """Host samples taken across a run, summarised rather than just stored."""

    samples: list[HostSample] = field(default_factory=list)
    lock_path: str | None = None
    lock_held: bool = False
    lock_detail: str = "not acquired"

    def mark(self) -> None:
        self.samples.append(sample())

    def summary(self) -> dict[str, Any]:
        if not self.samples:
            return {"n": 0, "note": "no host samples were taken"}
        ones = [s.loadavg[0] for s in self.samples]
        fives = [s.loadavg[1] for s in self.samples]
        runnables = [s.runnable for s in self.samples if s.runnable is not None]
        out: dict[str, Any] = {
            "n": len(self.samples),
            "loadavg_1min": {
                "start": ones[0],
                "end": ones[-1],
                "min": min(ones),
                "max": max(ones),
                "drift": ones[-1] - ones[0],
            },
            "loadavg_5min": {
                "start": fives[0],
                "end": fives[-1],
                "min": min(fives),
                "max": max(fives),
                "drift": fives[-1] - fives[0],
            },
            "load_ratio_max_over_min": (
                (max(ones) / min(ones)) if min(ones) > 0 else None
            ),
            "lock_path": self.lock_path,
            "lock_held": self.lock_held,
            "lock_detail": self.lock_detail,
        }
        if runnables:
            out["runnable_threads"] = {
                "start": runnables[0],
                "end": runnables[-1],
                "min": min(runnables),
                "max": max(runnables),
            }
        out["interpretation"] = _interpret(out)
        return out


def _interpret(summary: dict[str, Any]) -> str:
    """Turn the contention trace into a sentence a reviewer can act on."""
    one = summary.get("loadavg_1min", {})
    ratio = summary.get("load_ratio_max_over_min")
    bits: list[str] = []
    if one.get("drift") is not None and one["drift"] > 0.25 * max(
        one.get("start", 1.0), 1.0
    ):
        bits.append(
            f"the 1-minute load average moved {one['drift']:+.1f} over the run "
            f"({one['start']:.1f} -> {one['end']:.1f}), which is large enough to "
            f"explain an effect on its own"
        )
    if ratio and ratio >= 2.0:
        bits.append(
            f"host load varied by {ratio:.1f}x during the run; wall-clock "
            f"figures from this session are not comparable to each other "
            f"without the A/A band"
        )
    if not summary.get("lock_held"):
        bits.append(
            "the host-wide benchmark lock was not held, so this run was not "
            "serialised against concurrent benchmark lanes"
        )
    if not bits:
        bits.append(
            "host load was stable and the benchmark lock was held; no "
            "contention concern beyond the measured A/A band"
        )
    return "; ".join(bits)


class BenchmarkSlot:
    """Context manager wrapping the repository's host-wide benchmark lock.

    Serialisation across lanes cannot be fixed from inside a single benchmark
    process: it needs every lane to take the same lock. The repository already
    provides one, so this joins it rather than adding a second protocol that
    other lanes would not honour.

    Usage is safe when the lock tool is missing: the slot still works, records
    that it did not serialise, and the report carries that fact through to the
    verdict. A benchmark that refuses to run because a convenience tool is
    absent would be less useful, not more trustworthy.
    """

    def __init__(
        self,
        agent: str,
        what: str,
        timeout: float = 0.0,
        worktree: str | None = None,
        enabled: bool = True,
    ) -> None:
        self.agent = agent
        self.what = what
        self.timeout = timeout
        self.worktree = worktree or _repo_root()
        self.enabled = enabled
        self.path = os.path.join(self.worktree, _LOCK_RELATIVE)
        self.token: str | None = None
        self.detail = "disabled by request"

    def __enter__(self) -> "BenchmarkSlot":
        if not self.enabled:
            return self
        if not os.path.exists(self.path):
            self.detail = f"lock tool not present at {self.path}; run unserialised"
            return self
        if shutil.which("python3") is None:
            self.detail = "no python3 to run the lock tool; run unserialised"
            return self
        argv = [
            sys.executable,
            self.path,
            "acquire",
            "--agent",
            self.agent,
            "--what",
            self.what,
            "--worktree",
            self.worktree,
        ]
        if self.timeout > 0:
            argv += ["--timeout", str(self.timeout)]
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                argv,
                capture_output=True,
                text=True,
                timeout=None if self.timeout <= 0 else self.timeout + 60,
            )
        except Exception as exc:  # noqa: BLE001 - lock failure must not kill the run
            self.detail = f"lock tool failed: {type(exc).__name__}: {exc}"
            return self
        self.token = proc.stdout.strip()
        if proc.returncode == 0 and self.token:
            self.detail = f"held: {self.token}"
        else:
            self.detail = (
                f"not held (exit {proc.returncode}): "
                f"{(proc.stderr or proc.stdout).strip()[:200]}"
            )
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # The lock tool holds the slot for the lifetime of the process it
        # wrapped; there is no separate unlock, and the kernel releases the
        # flock on exit. Nothing to do here beyond recording the outcome.
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "held": bool(self.token),
            "detail": self.detail,
            "agent": self.agent,
            "what": self.what,
        }


def contention_caveat(summary: dict[str, Any]) -> str | None:
    """A caveat to attach to a verdict, or None when the host was quiet.

    Kept separate from `_interpret` so the reporting layer decides what to do
    with it: a caveat can be attached to a passing result without making it fail.
    A measurement taken under a load spike is not wrong, it is weakly supported.
    """
    interp = summary.get("interpretation", "")
    if "unserialised" in interp or "varied by" in interp or "moved" in interp:
        return interp
    return None


def write_trace(trace: ContentionTrace, path: str) -> None:
    """Persist the contention trace alongside the measurement JSON."""
    payload = {
        "summary": trace.summary(),
        "samples": [s.as_dict() for s in trace.samples],
    }
    tmp = f"{path}.contention.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
    os.replace(tmp, path)


def read_baseline_revision(root: str | None = None) -> str | None:
    """The recorded baseline revision, so a report states what it was compared to."""
    root = root or _repo_root()
    candidate = os.path.join(root, "bench", "baseline.json")
    try:
        with open(candidate, encoding="utf-8") as handle:
            return json.load(handle).get("revision")
    except (OSError, ValueError):
        return None
