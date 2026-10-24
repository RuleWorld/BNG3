"""Flushed child-process phase breadcrumbs for timeout evidence."""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Iterator


def write_phase_breadcrumb(prefix: str, phase: str, state: str) -> None:
    """Write one stable marker that a parent can recover after child timeout."""

    print(f"{prefix} {state} {phase}", file=sys.stderr, flush=True)


@contextlib.contextmanager
def case_phase_scope(prefix: str, phase: str) -> Iterator[None]:
    """Record when a phase starts and whether it completes or raises."""

    write_phase_breadcrumb(prefix, phase, "started")
    try:
        yield
    except BaseException:
        write_phase_breadcrumb(prefix, phase, "failed")
        raise
    else:
        write_phase_breadcrumb(prefix, phase, "completed")


def phase_progress(log: str | bytes, prefix: str) -> dict[str, str | list[str] | None]:
    """Recover completed phases and the active phase from captured output."""

    if isinstance(log, bytes):
        log = log.decode("utf-8", errors="replace")
    last_completed = None
    completed: list[str] = []
    active: list[str] = []
    for line in log.splitlines():
        if not line.startswith(prefix + " "):
            continue
        parts = line.split(" ", 2)
        if len(parts) != 3:
            continue
        _, state, phase = parts
        if not phase or state not in {"started", "completed", "failed"}:
            continue
        if state == "started":
            active.append(phase)
        elif state == "completed":
            last_completed = phase
            completed.append(phase)
            if phase in active:
                del active[active.index(phase) :]
        elif state == "failed":
            active.append(phase)
    return {
        "last_completed_phase": last_completed,
        "active_phase": active[-1] if active else None,
        "completed_phases": completed,
    }
