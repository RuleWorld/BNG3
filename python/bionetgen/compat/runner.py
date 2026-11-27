"""Explicit PyBioNetGen-compatible file runner backed by BNG3."""

from __future__ import annotations

import math
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

import numpy as np

from bionetgen.core.exc import BNGError
from bionetgen.core.tools.result import BNGResult


def _run_in_directory(
    inp: Path,
    output: Path,
    *,
    suppress: bool,
    method: str | None,
) -> BNGResult:
    if inp.suffix.lower() != ".bngl":
        raise NotImplementedError(
            "The BNG3 compatibility runner currently accepts BNGL input only"
        )
    if method is not None:
        raise NotImplementedError(
            "method overrides are not supported by the compatibility runner; "
            "edit the model actions or use load(...).simulate(...)"
        )
    output.mkdir(parents=True, exist_ok=True)
    copied = output / inp.name
    if copied.resolve() != inp.resolve():
        shutil.copy2(inp, copied)

    try:
        from bionetgen import _bionetgen_cpp as cpp
    except ImportError as exc:
        raise BNGError(
            "The BNG3 C++ backend is required for bionetgen.run(input, out)"
        ) from exc

    try:
        model = cpp.parse_file(str(copied))
        cpp.execute(model, str(copied), verbose=not suppress)
    except Exception as exc:
        raise BNGError(f"BNG3 failed while running {inp}: {exc}") from exc

    result = BNGResult(path=str(output))
    result.process_return = 0
    result.output = ["Ran successfully via BNG3"]
    return result


def _write_sim_result(model, result, output: Path, stem: str) -> BNGResult:
    """Materialize the modern in-memory result as the legacy ``.gdat`` API."""
    output.mkdir(parents=True, exist_ok=True)
    names = list(result.observables)
    columns = [np.asarray(result.time, dtype=float)]
    columns.extend(np.asarray(result.observables[name], dtype=float) for name in names)
    data = np.column_stack(columns) if columns else np.empty((0, 0))
    gdat = output / f"{stem}.gdat"
    with gdat.open("w", encoding="utf-8") as handle:
        handle.write("# " + " ".join(["time", *names]) + "\n")
        if data.size:
            np.savetxt(handle, data, fmt="%.17g")
    result = BNGResult(path=str(output))
    result.process_return = 0
    result.output = ["Ran successfully via BNG3 modern simulation API"]
    return result


_SIMULATION_ACTIONS = {
    "simulate",
    "simulate_ode",
    "simulate_ssa",
    "simulate_nf",
    "simulate_pla",
    "simulate_psa",
}


def _finite_time(name: str, value) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _positive_steps(name: str, value, minimum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer of at least {minimum}")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be an integer of at least {minimum}") from exc
    try:
        is_integral = number == value
    except (TypeError, ValueError):
        is_integral = False
    if not is_integral or number < minimum:
        raise ValueError(f"{name} must be an integer of at least {minimum}")
    return number


def _normalize_time_options(*, t_span, t_start, t_end, n_points, n_steps):
    if t_span is not None:
        if isinstance(t_span, (str, bytes)) or len(t_span) != 2:
            raise ValueError("t_span must be a (t_start, t_end) pair")
        if t_start is not None or t_end is not None:
            raise TypeError("t_span cannot be combined with t_start or t_end")
        start = _finite_time("t_start", t_span[0])
        end = _finite_time("t_end", t_span[1])
    else:
        start = None if t_start is None else _finite_time("t_start", t_start)
        end = None if t_end is None else _finite_time("t_end", t_end)
    if start is not None and end is not None and end < start:
        raise ValueError("t_end must be greater than or equal to t_start")

    if n_points is not None and n_steps is not None:
        raise TypeError("n_points and n_steps cannot both be specified")
    if n_points is not None:
        # Top-level bionetgen.run(..., out=..., n_points=n) emits n rows
        # including both endpoints (verified against pinned PyBioNetGen),
        # so the in-process simulation needs n-1 steps.
        steps = _positive_steps("n_points", n_points, 2) - 1
    elif n_steps is not None:
        steps = _positive_steps("n_steps", n_steps, 1)
    else:
        steps = None
    return start, end, steps


def _format_number(value: float) -> str:
    return format(value, ".17g")


def _run_modern_override(
    inp: Path,
    output: Path,
    *,
    suppress: bool,
    method: str,
    t_start: float | None,
    t_end: float | None,
    n_steps: int | None,
    solver_options: dict,
) -> BNGResult:
    """Run an explicitly selected single method through the modern API."""
    if inp.suffix.lower() != ".bngl":
        raise NotImplementedError(
            "method/time overrides currently require BNGL input; "
            "use sbml_to_bngl() for SBML conversion"
        )
    from bionetgen import load

    start = 0.0 if t_start is None else t_start
    end = 100.0 if t_end is None else t_end
    steps = 100 if n_steps is None else n_steps
    output.mkdir(parents=True, exist_ok=True)
    copied = output / inp.name
    if copied.resolve() != inp.resolve():
        shutil.copy2(inp, copied)
    model = load(str(copied))
    simulation = model.simulate(
        method=method,
        t_start=start,
        t_end=end,
        n_steps=steps,
        verbose=not suppress,
        **solver_options,
    )
    return _write_sim_result(model, simulation, output, inp.stem)


def _action_arguments(action) -> dict[str, str]:
    return dict(action.arguments)


def _truthy_action_argument(value: str) -> bool:
    return str(value).strip().strip("'\"").lower() in {"1", "true", "yes", "on"}


def _run_action_time_override(
    inp: Path,
    output: Path,
    *,
    suppress: bool,
    model,
    t_start: float | None,
    t_end: float | None,
    n_steps: int | None,
) -> BNGResult:
    """Run declared model actions with a temporary, uniform output grid."""
    overrides = {}
    simulation_count = 0
    for index, action in enumerate(model.actions):
        action_name = action.name.lower()
        if action_name not in _SIMULATION_ACTIONS:
            continue
        simulation_count += 1
        arguments = _action_arguments(action)
        if arguments.get("sample_times", "").strip().strip("'\""):
            raise NotImplementedError(
                "time-grid overrides cannot be combined with action sample_times"
            )
        if _truthy_action_argument(arguments.get("continue", "0")):
            raise NotImplementedError(
                "time-grid overrides cannot be combined with action continue"
            )

        values = {}
        if t_start is not None:
            values["t_start"] = _format_number(t_start)
        if t_end is not None:
            values["t_end"] = _format_number(t_end)
        if n_steps is not None:
            values["n_steps"] = str(n_steps)
        if values:
            overrides[index] = values

    if simulation_count == 0:
        raise NotImplementedError(
            "time-grid overrides require at least one direct simulation action"
        )

    output.mkdir(parents=True, exist_ok=True)
    copied = output / inp.name
    if copied.resolve() != inp.resolve():
        shutil.copy2(inp, copied)

    try:
        from bionetgen import _bionetgen_cpp as cpp

        cpp.execute(
            model,
            str(copied),
            verbose=not suppress,
            action_overrides=overrides,
        )
    except Exception as exc:
        raise BNGError(f"BNG3 failed while running {inp}: {exc}") from exc

    result = BNGResult(path=str(output))
    result.process_return = 0
    result.output = ["Ran successfully via BNG3 action time override"]
    return result


def _is_bngmodel_object(obj) -> bool:
    """Return True for PyBioNetGen-style in-memory ``bngmodel`` objects."""
    return (
        not isinstance(obj, (str, os.PathLike))
        and hasattr(obj, "write_model")
        and hasattr(obj, "model_name")
    )


def _materialize_bngmodel(model_obj, directory: Path) -> Path:
    """Serialize a ``bngmodel`` instance to ``<directory>/<model_name>.bngl``."""
    raw_name = str(getattr(model_obj, "model_name", "") or "model").strip()
    safe_name = Path(raw_name).name or "model"
    if safe_name in {".", ".."}:
        safe_name = "model"
    if not safe_name.lower().endswith(".bngl"):
        safe_name = f"{safe_name}.bngl"
    target = Path(directory) / safe_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(model_obj), encoding="utf-8")
    return target


def run(
    inp,
    out=None,
    suppress=False,
    timeout=None,
    simulator="auto",
    format=None,
    method=None,
    t_span=None,
    t_start=None,
    n_points=None,
    t_end=None,
    n_steps=None,
    rtol=None,
    atol=None,
    seed=None,
    pla_config=None,
    psa_poplevel=None,
    backend=None,
    log_file=None,
    **kwargs,
):
    """Run a BNGL file into a PyBioNetGen-style result directory.

    Declared actions are preserved unless a method override selects one
    simulation. Process isolation and timeouts use the same native executor
    and normalized options as direct execution.
    """
    if kwargs:
        names = ", ".join(sorted(kwargs))
        raise TypeError(f"unsupported compatibility runner option(s): {names}")
    if simulator not in {"auto", "native", "subprocess"}:
        raise NotImplementedError(
            f"simulator={simulator!r} is not supported by the BNG3 compatibility runner; "
            "use 'auto', 'native', or 'subprocess'"
        )
    if format is not None:
        format = str(format).lower().strip()
    if format not in (None, "bngl"):
        raise NotImplementedError(
            "only BNGL input is supported by the BNG3 compatibility runner"
        )
    if _is_bngmodel_object(inp):
        with TemporaryDirectory(prefix="bng3-model-") as model_dir:
            materialized = _materialize_bngmodel(inp, Path(model_dir))
            return run(
                materialized,
                out=out,
                suppress=suppress,
                timeout=timeout,
                simulator=simulator,
                format=format,
                method=method,
                t_span=t_span,
                t_start=t_start,
                n_points=n_points,
                t_end=t_end,
                n_steps=n_steps,
                rtol=rtol,
                atol=atol,
                seed=seed,
                pla_config=pla_config,
                psa_poplevel=psa_poplevel,
                backend=backend,
                log_file=log_file,
            )
    inp_path = Path(inp).expanduser().resolve()
    if not inp_path.is_file():
        raise FileNotFoundError(inp_path)

    start, end, steps = _normalize_time_options(
        t_span=t_span,
        t_start=t_start,
        t_end=t_end,
        n_points=n_points,
        n_steps=n_steps,
    )
    selected_method = None if method is None else str(method).lower()
    if selected_method is not None and selected_method not in {
        "ode",
        "ssa",
        "nf",
        "pla",
        "psa",
    }:
        raise ValueError(
            f"unsupported method {method!r}; use ode, ssa, nf, pla, or psa"
        )
    normalized_backend = None
    if backend is not None:
        from bionetgen.bngsim_backend import normalize_finite_backend

        normalized_backend = normalize_finite_backend(backend)
    solver_options = {
        key: value
        for key, value in {
            "rtol": rtol,
            "atol": atol,
            "seed": seed,
            "pla_config": pla_config,
            "psa_poplevel": psa_poplevel,
            "backend": normalized_backend,
        }.items()
        if value is not None
    }
    has_time_override = any(value is not None for value in (start, end, steps))
    if selected_method is None and solver_options:
        if list(solver_options.keys()) == ["backend"] and normalized_backend in {
            "auto",
            "native",
        }:
            solver_options.pop("backend")
        else:
            names = ", ".join(sorted(solver_options))
            raise NotImplementedError(
                "solver options require an explicit method override; action-preserving "
                f"time-grid runs do not apply: {names}"
            )

    def execute(output: Path) -> BNGResult:
        if log_file is not None or timeout is not None or simulator == "subprocess":
            if inp_path.suffix.lower() != ".bngl":
                raise NotImplementedError(
                    "native process execution requires BNGL input"
                )
            from bionetgen.compat._native_process import execute_native

            output.mkdir(parents=True, exist_ok=True)
            copied = output / inp_path.name
            if copied.resolve() != inp_path.resolve():
                shutil.copy2(inp_path, copied)
            return execute_native(
                copied,
                output,
                suppress=suppress,
                timeout=timeout,
                log_file=log_file,
                options={
                    "method": selected_method,
                    "t_start": start,
                    "t_end": end,
                    "n_steps": steps,
                    **solver_options,
                },
            )
        if selected_method is not None:
            return _run_modern_override(
                inp_path,
                output,
                suppress=suppress,
                method=selected_method,
                t_start=start,
                t_end=end,
                n_steps=steps,
                solver_options=solver_options,
            )
        if has_time_override:
            if inp_path.suffix.lower() != ".bngl":
                raise NotImplementedError(
                    "time-grid overrides currently require BNGL input"
                )
            if output.exists() and not output.is_dir():
                raise NotADirectoryError(output)
            try:
                from bionetgen import _bionetgen_cpp as cpp

                model = cpp.parse_file(str(inp_path))
            except Exception as exc:
                raise BNGError(f"BNG3 failed while parsing {inp_path}: {exc}") from exc
            return _run_action_time_override(
                inp_path,
                output,
                suppress=suppress,
                model=model,
                t_start=start,
                t_end=end,
                n_steps=steps,
            )
        return _run_in_directory(
            inp_path,
            output,
            suppress=suppress,
            method=None,
        )

    if out is None:
        with TemporaryDirectory(prefix="bionetgen-run-") as temp:
            return execute(Path(temp))

    output = Path(out).expanduser().resolve()
    if output.exists() and not output.is_dir():
        raise NotADirectoryError(output)
    return execute(output)
