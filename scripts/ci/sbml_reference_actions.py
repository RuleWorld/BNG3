"""Execute a generated BNGL action block on an official reference grid.

The SBML Test Suite compares deterministic cases against an official time
course and stochastic cases against official mean/standard-deviation series.
When the Atomizer lowers SBML events into BNGL scheduled actions, the model
carries a phase-structured ``begin actions`` block whose ``simulate`` actions
use their own output grids.  The in-memory CVODE runner used by the official
reference comparison cannot execute actions at all, so this module runs the
action block through the *native* action dispatcher instead.

Two properties matter for validation integrity and are enforced here:

* Only the **output grid** of each ``simulate`` action is rewritten.  Every
  event trigger, event assignment, phase boundary and simulation method stays
  exactly as the Atomizer emitted it, so the executed semantics are the
  model's own scheduled-action semantics.
* The rewritten grid is the *official* grid.  No sample is dropped, no
  tolerance is widened and no phase is merged.

The dispatcher writes its trajectory to ``<source stem>.gdat``; the module
reads that file back and maps the rows onto the official grid.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

# ``simulate({...})`` and its explicit method spellings.
SIMULATE_ACTION_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<name>simulate(?:_ode|_ssa)?)\((?P<args>\{.*\})\)"
    r"[ \t]*$"
)
# Assignments that can change the state discontinuously at a phase boundary.
SPECIES_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*(?:setConcentration|addConcentration|setAmount|addAmount|setVolume)\b"
)
PARAMETER_ASSIGNMENT_RE = re.compile(r"^[ \t]*setParameter\(\s*\"(?P<target>[^\"]*)\"")
# ``generate_network`` prepares the network before the first simulation phase.
GENERATE_NETWORK_RE = re.compile(r"^[ \t]*generate_network\b")
MOLECULE_TOKEN_RE = re.compile(r"M_([A-Za-z_][A-Za-z_0-9]*)")

#: Action names that the native dispatcher executes as a simulation phase.
SIMULATION_ACTION_NAMES = ("simulate", "simulate_ode", "simulate_ssa")

#: Solver settings used for the official reference comparison.  They match the
#: in-memory reference runner so the action path is not more permissive.
REFERENCE_SOLVER_RTOL = 1e-9
REFERENCE_SOLVER_ATOL = 1e-14


class ActionGridError(ValueError):
    """Raised when an action block cannot be executed on a requested grid."""


@dataclass(frozen=True)
class ActionPhase:
    """One ``simulate`` action inside a generated action block."""

    index: int
    name: str
    line_index: int
    t_start: float
    t_end: float
    method: str
    continued: bool
    arguments: str


@dataclass(frozen=True)
class ActionBlock:
    """The parsed structure of a generated ``begin actions`` block."""

    phases: tuple[ActionPhase, ...]
    #: Assignment action lines that follow each phase, i.e. the assignments
    #: that are applied at that phase's end time.
    assignments: tuple[tuple[int, tuple[str, ...]], ...]
    start_line: int
    end_line: int


def _argument_value(arguments: str, key: str) -> str | None:
    match = re.search(
        rf"(?<![A-Za-z_]){re.escape(key)}\s*=>\s*(\"[^\"]*\"|[^,}}]+)", arguments
    )
    if match is None:
        return None
    return match.group(1).strip().strip('"')


def parse_action_block(bngl: str) -> ActionBlock:
    """Parse the ``simulate`` phases and assignments of a BNGL action block.

    The parser is deliberately narrow: it understands the action spellings the
    modern Atomizer emits (``simulate({...})`` plus ``setConcentration`` /
    ``setParameter`` / ``setVolume`` assignments) and refuses anything else so
    an unrecognised action can never be silently ignored.
    """

    lines = bngl.splitlines()
    start = None
    end = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if start is None and stripped == "begin actions":
            start = index
            continue
        if start is not None and stripped == "end actions":
            end = index
            break
    if start is None or end is None:
        raise ActionGridError("generated BNGL has no begin actions/end actions block")

    phases: list[ActionPhase] = []
    assignments: dict[int, list[str]] = {}
    current = -1
    for index in range(start + 1, end):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        simulate = SIMULATE_ACTION_RE.match(line)
        if simulate is not None:
            arguments = simulate.group("args")
            t_start_text = _argument_value(arguments, "t_start")
            t_end_text = _argument_value(arguments, "t_end")
            if t_end_text is None:
                raise ActionGridError(
                    f"action {simulate.group('name')} on line {index + 1} has no t_end"
                )
            try:
                t_start = float(t_start_text) if t_start_text is not None else 0.0
                t_end = float(t_end_text)
            except ValueError as exc:
                raise ActionGridError(
                    f"action {simulate.group('name')} on line {index + 1} has a "
                    f"non-numeric time: {exc}"
                ) from exc
            if not (math.isfinite(t_start) and math.isfinite(t_end)):
                raise ActionGridError(
                    f"action {simulate.group('name')} on line {index + 1} has a "
                    "non-finite time"
                )
            continued = (_argument_value(arguments, "continue") or "0") in {
                "1",
                "true",
            }
            method = _argument_value(arguments, "method") or "ode"
            current = len(phases)
            phases.append(
                ActionPhase(
                    index=current,
                    name=simulate.group("name"),
                    line_index=index,
                    t_start=t_start,
                    t_end=t_end,
                    method=method,
                    continued=continued,
                    arguments=arguments,
                )
            )
            assignments.setdefault(current, [])
            continue
        if SPECIES_ASSIGNMENT_RE.match(line) or PARAMETER_ASSIGNMENT_RE.match(line):
            # Assignments before the first phase belong to the model's initial
            # state; they are recorded against phase index -1 so the caller
            # can tell them apart from a phase-boundary assignment.
            assignments.setdefault(current, []).append(stripped)
            continue
        if GENERATE_NETWORK_RE.match(line):
            continue
        raise ActionGridError(
            f"unsupported action on line {index + 1} of the generated action block: {stripped}"
        )

    if not phases:
        raise ActionGridError("generated action block contains no simulation phase")
    indices = [-1, *range(len(phases))]
    return ActionBlock(
        phases=tuple(phases),
        assignments=tuple(
            (index, tuple(assignments.get(index, ()))) for index in indices
        ),
        start_line=start,
        end_line=end,
    )


def _grid_points(times: Sequence[float], t_start: float, t_end: float) -> list[float]:
    """Return the official grid points that fall inside one phase."""

    tolerance = 1e-12 * max(1.0, abs(t_start), abs(t_end))
    return [
        float(value)
        for value in times
        if t_start - tolerance <= value <= t_end + tolerance
    ]


def rewrite_action_output_grid(
    bngl: str,
    times: Sequence[float],
    *,
    rtol: float = REFERENCE_SOLVER_RTOL,
    atol: float = REFERENCE_SOLVER_ATOL,
    seeds: Sequence[int] | None = None,
) -> tuple[str, ActionBlock]:
    """Rewrite only the output grid of every ``simulate`` action.

    ``sample_times`` replaces ``n_steps`` so each phase reports exactly the
    official grid points inside its own interval.  The solver tolerances are
    pinned to the values the in-memory reference runner uses so the action
    path is not more permissive than the non-action path.  ``seeds`` supplies
    one seed per phase for stochastic ensembles.
    """

    block = parse_action_block(bngl)
    lines = bngl.splitlines()
    rewritten: list[str] = []
    phase_seeds = list(seeds) if seeds is not None else None
    for phase in block.phases:
        arguments = phase.arguments
        points = _grid_points(times, phase.t_start, phase.t_end)
        # ``n_steps`` takes precedence over ``sample_times`` in the native
        # dispatcher, so it has to be removed when a sample grid is supplied.
        arguments = re.sub(r"(?<![A-Za-z_])n_steps\s*=>\s*[^,}]+", "", arguments)
        arguments = re.sub(r"(?<![A-Za-z_])n_output_steps\s*=>\s*[^,}]+", "", arguments)
        arguments = re.sub(
            r"(?<![A-Za-z_])sample_times\s*=>\s*\[[^\]]*\]", "", arguments
        )
        arguments = arguments.strip()
        if arguments.startswith("{") and arguments.endswith("}"):
            arguments = arguments[1:-1]
        parts = [part.strip() for part in arguments.split(",") if part.strip()]
        if points:
            parts.append(
                "sample_times=>["
                + ", ".join(repr(float(value)) for value in points)
                + "]"
            )
        parts.append("print_functions=>1")
        parts.append("print_CDAT=>0")
        parts.append(f"rtol=>{rtol!r}")
        parts.append(f"atol=>{atol!r}")
        if phase_seeds is not None:
            if phase.index >= len(phase_seeds):
                raise ActionGridError("not enough phase seeds for the action block")
            parts.append(f"seed=>{int(phase_seeds[phase.index])}")
        text = "{" + ", ".join(parts) + "}"
        indent = lines[phase.line_index][
            : len(lines[phase.line_index]) - len(lines[phase.line_index].lstrip())
        ]
        rewritten.append(f"{indent}{phase.name}({text})")

    output = list(lines)
    for phase, text in zip(block.phases, rewritten):
        output[phase.line_index] = text
    return "\n".join(output) + ("\n" if bngl.endswith("\n") else ""), block


def _parse_gdat(path: Path) -> tuple[list[str], list[list[float]]]:
    text = path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ActionGridError(f"{path.name} is empty")
    header = lines[0].strip().lstrip("#").strip().split()
    rows: list[list[float]] = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            rows.append([float(cell) for cell in stripped.split()])
        except ValueError as exc:
            raise ActionGridError(f"{path.name} has a non-numeric row: {exc}") from exc
    if not rows:
        raise ActionGridError(f"{path.name} has no data rows")
    return header, rows


def _match_official_grid(
    times: Sequence[float], observed: Sequence[float]
) -> dict[int, int]:
    """Map every official grid point onto its row in the dispatcher output."""

    mapping: dict[int, int] = {}
    for index, target in enumerate(times):
        best = None
        best_error = math.inf
        for row, value in enumerate(observed):
            error = abs(value - target)
            if error < best_error:
                best_error = error
                best = row
        tolerance = 1e-9 * max(1.0, abs(target))
        if best is None or best_error > tolerance:
            raise ActionGridError(
                "the native action dispatcher did not report the official output "
                f"grid point {target!r} (closest reported time differs by "
                f"{best_error!r})"
            )
        mapping[index] = best
    return mapping


@dataclass
class ActionRun:
    """The trajectory produced by executing one action block."""

    times: list[float]
    values: dict[str, list[float]]
    columns: list[str]
    source: str


def execute_action_block(
    cpp: Any,
    bngl: str,
    work_dir: Path,
    *,
    times: Sequence[float],
    aliases: dict[str, str],
    rtol: float = REFERENCE_SOLVER_RTOL,
    atol: float = REFERENCE_SOLVER_ATOL,
    source_name: str = "reference",
) -> ActionRun:
    """Execute a rewritten action block and read its trajectory back.

    The block is executed by the native action dispatcher, so every scheduled
    action in the model runs exactly as the model declares it.
    """

    work_dir.mkdir(parents=True, exist_ok=True)
    source = work_dir / f"{source_name}.bngl"
    source.write_text(bngl, encoding="utf-8")
    model = cpp.parse_string(bngl)
    cpp.execute(model, str(source), False)
    gdat = work_dir / f"{source_name}.gdat"
    if not gdat.is_file():
        raise ActionGridError(
            "the native action dispatcher produced no trajectory file"
        )
    header, rows = _parse_gdat(gdat)
    if len(set(header)) != len(header):
        raise ActionGridError("the dispatcher trajectory has duplicate columns")
    observed = [row[0] for row in rows]
    mapping = _match_official_grid(times, observed)
    values: dict[str, list[float]] = {}
    for variable, alias in aliases.items():
        if alias not in header:
            raise ActionGridError(
                f"the dispatcher trajectory has no column for {alias!r}"
            )
        column = header.index(alias)
        values[variable] = [rows[mapping[index]][column] for index in range(len(times))]
    return ActionRun(
        times=[float(value) for value in times],
        values=values,
        columns=header,
        source=str(source),
    )


def assignment_affects_outputs(
    assignments: Iterable[str],
    *,
    requested_ids: Iterable[str],
    target_symbols: Iterable[str],
) -> bool:
    """Report whether an assignment can change a requested output value.

    Only assignments that can move a requested quantity discontinuously count:
    a species amount, a compartment volume, or a parameter that is itself a
    requested output.  Rate-only parameters change the trajectory smoothly and
    therefore do not make a phase boundary ambiguous.
    """

    ids = {str(value) for value in requested_ids}
    symbols = {str(value) for value in target_symbols}
    for line in assignments:
        stripped = line.strip()
        if SPECIES_ASSIGNMENT_RE.match(stripped):
            if stripped.startswith("setVolume"):
                return True
            for token in MOLECULE_TOKEN_RE.findall(stripped):
                if token in ids or f"{token}_amt" in symbols:
                    return True
            continue
        match = PARAMETER_ASSIGNMENT_RE.match(stripped)
        if match is None:
            continue
        target = match.group("target")
        if target in ids or target in symbols:
            return True
        if target.startswith("__compartment_"):
            compartment = (
                target[len("__compartment_") : -2] if target.endswith("__") else target
            )
            if compartment in ids or f"{compartment}_amt" in symbols:
                return True
    return False
