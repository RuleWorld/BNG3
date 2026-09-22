"""Explicit PyBioNetGen-compatible file runner backed by BNG3."""

from __future__ import annotations

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
    timeout: int | None,
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
    if timeout is not None:
        raise NotImplementedError(
            "timeout is not supported by the in-process BNG3 compatibility runner"
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


def _run_override(
    inp: Path,
    output: Path,
    *,
    suppress: bool,
    method: str | None,
    t_span,
    n_points: int | None,
    t_end: float,
    n_steps: int,
) -> BNGResult:
    """Run a documented method/time override through the modern BNG3 API."""
    if inp.suffix.lower() != ".bngl":
        raise NotImplementedError(
            "method/time overrides currently require BNGL input; "
            "use sbml_to_bngl() for SBML conversion"
        )
    from bionetgen import load

    output.mkdir(parents=True, exist_ok=True)
    copied = output / inp.name
    if copied.resolve() != inp.resolve():
        shutil.copy2(inp, copied)
    if t_span is None:
        t_start = 0.0
        end = float(t_end)
    else:
        if isinstance(t_span, (str, bytes)) or len(t_span) != 2:
            raise ValueError("t_span must be a (t_start, t_end) pair")
        t_start, end = (float(value) for value in t_span)
        if end < t_start:
            raise ValueError("t_span end must be greater than or equal to start")
    if n_points is None:
        points = int(n_steps) + 1
    else:
        if isinstance(n_points, bool) or int(n_points) != n_points or n_points < 2:
            raise ValueError("n_points must be an integer of at least two")
        points = int(n_points)
    if points < 2:
        raise ValueError("at least two output points are required")
    if method is None:
        method = "ode"
    method = str(method).lower()
    if method not in {"ode", "ssa", "nf", "pla", "psa"}:
        raise ValueError(
            f"unsupported method {method!r}; use ode, ssa, nf, pla, or psa"
        )

    model = load(str(copied))
    simulation = model.simulate(
        method=method,
        t_start=t_start,
        t_end=end,
        n_steps=points - 1,
    )
    return _write_sim_result(model, simulation, output, inp.stem)


def run(
    inp,
    out=None,
    suppress=False,
    timeout=None,
    simulator="auto",
    format=None,
    method=None,
    t_span=None,
    n_points=None,
    t_end=100.0,
    n_steps=100,
    **kwargs,
):
    """Run a BNGL file into a PyBioNetGen-style result directory.

    This first compatibility slice intentionally preserves the input model's
    declared actions. Unsupported legacy options fail explicitly rather than
    silently selecting a different simulator or output contract.
    """
    if kwargs:
        names = ", ".join(sorted(kwargs))
        raise TypeError(f"unsupported compatibility runner option(s): {names}")
    if simulator != "auto":
        raise NotImplementedError(
            "only simulator='auto' is supported by the BNG3 compatibility runner"
        )
    if format not in (None, "bngl"):
        raise NotImplementedError(
            "only BNGL input is supported by the BNG3 compatibility runner"
        )

    inp_path = Path(inp).expanduser().resolve()
    if not inp_path.is_file():
        raise FileNotFoundError(inp_path)

    if out is None:
        with TemporaryDirectory(prefix="bionetgen-run-") as temp:
            override = (
                method is not None
                or t_span is not None
                or n_points is not None
                or t_end != 100.0
                or n_steps != 100
            )
            if override:
                return _run_override(
                    inp_path,
                    Path(temp),
                    suppress=suppress,
                    method=method,
                    t_span=t_span,
                    n_points=n_points,
                    t_end=t_end,
                    n_steps=n_steps,
                )
            return _run_in_directory(
                inp_path,
                Path(temp),
                suppress=suppress,
                method=method,
                timeout=timeout,
            )

    output = Path(out).expanduser().resolve()
    if output.exists() and not output.is_dir():
        raise NotADirectoryError(output)
    override = (
        method is not None
        or t_span is not None
        or n_points is not None
        or t_end != 100.0
        or n_steps != 100
    )
    if override:
        return _run_override(
            inp_path,
            output,
            suppress=suppress,
            method=method,
            t_span=t_span,
            n_points=n_points,
            t_end=t_end,
            n_steps=n_steps,
        )
    return _run_in_directory(
        inp_path,
        output,
        suppress=suppress,
        method=method,
        timeout=timeout,
    )
