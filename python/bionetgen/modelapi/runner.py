import logging

logger = logging.getLogger(__name__)


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
):
    """
    PyBioNetGen-compatible runner API.

    For action-workflow runs, returns a :class:`bionetgen.core.tools.result.BNGResult`.
    When a single-simulation override is requested (``method``, ``t_span`` or
    ``n_points``), returns the modern in-memory simulation result for direct
    analysis.
    """
    # Preserve PyBioNetGen's argument surface.
    if format is not None and str(format).lower().strip() != "bngl":
        from bionetgen.core.exc import BNGFormatError

        raise BNGFormatError(
            inp,
            f"run() accepts BNGL input only, not format={format!r}; convert "
            "SBML with bionetgen.atomizer first",
        )
    if simulator not in {"auto", "native", "subprocess", "bngsim"}:
        raise ValueError("simulator must be 'auto', 'native', 'subprocess' or 'bngsim'")

    wants_single_sim = simulator == "bngsim" or any(
        value is not None for value in (method, t_span, n_points)
    )
    if wants_single_sim:
        if out is not None:
            raise NotImplementedError(
                "out is not supported with in-memory simulation overrides"
            )
        from bionetgen.compat.runner import (
            _is_bngmodel_object,
            _materialize_bngmodel,
            _normalize_time_options,
            _positive_steps,
        )
        from bionetgen.model import load

        t_start, t_end, steps = _normalize_time_options(
            t_span=(0.0, 100.0) if t_span is None else t_span,
            t_start=None,
            t_end=None,
            n_points=None,
            n_steps=None,
        )
        if n_points is not None:
            # Pinned PyBioNetGen's modelapi runner.run(method=...,
            # n_points=n) emits n+1 points (it forwards n_points as the
            # backend's step count). The top-level bionetgen.run(..., out=)
            # path instead emits n rows; the two entry points are normalized
            # separately so both pinned contracts hold.
            steps = _positive_steps("n_points", n_points, 2)
        simulation_options = {
            "method": method or "ode",
            "t_start": float(t_start),
            "t_end": float(t_end),
            "n_steps": 100 if steps is None else steps,
            "backend": "bngsim" if simulator == "bngsim" else "native",
            "verbose": not suppress,
        }
        if _is_bngmodel_object(inp):
            from pathlib import Path
            from tempfile import TemporaryDirectory

            with TemporaryDirectory(prefix="bng3-model-") as model_dir:
                source = _materialize_bngmodel(inp, Path(model_dir))
                if simulator == "subprocess" or timeout is not None:
                    from bionetgen.compat._native_process import execute_native

                    with TemporaryDirectory(prefix="bng3-simulation-") as directory:
                        return execute_native(
                            source,
                            directory,
                            suppress=suppress,
                            timeout=timeout,
                            options=simulation_options,
                            result_file=Path(directory) / "simulation.npz",
                        )
                return load(source).simulate(**simulation_options)
        if simulator == "subprocess" or timeout is not None:
            from pathlib import Path
            from tempfile import TemporaryDirectory

            from bionetgen.compat._native_process import execute_native

            source = Path(inp).expanduser().resolve()
            if not source.is_file():
                raise FileNotFoundError(source)
            with TemporaryDirectory(prefix="bng3-simulation-") as directory:
                return execute_native(
                    source,
                    directory,
                    suppress=suppress,
                    timeout=timeout,
                    options=simulation_options,
                    result_file=Path(directory) / "simulation.npz",
                )
        return load(inp).simulate(**simulation_options)

    from bionetgen.compat.runner import run as compat_run

    return compat_run(
        inp,
        out=out,
        suppress=suppress,
        timeout=timeout,
        simulator=simulator,
        format=format,
        method=method,
        t_span=t_span,
        n_points=n_points,
    )
