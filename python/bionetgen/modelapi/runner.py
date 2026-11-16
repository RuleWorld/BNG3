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
    if format is not None and str(format).lower() != "bngl":
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
        if simulator == "subprocess":
            raise NotImplementedError(
                "simulator='subprocess' with simulation overrides is not supported"
            )
        if out is not None:
            raise NotImplementedError(
                "out is not supported with in-memory simulation overrides"
            )
        if timeout is not None:
            raise NotImplementedError(
                "timeout is not supported with in-memory simulation overrides"
            )
        from bionetgen.model import load

        if t_span is None:
            t_start, t_end = 0.0, 100.0
        else:
            t_start, t_end = t_span
        return load(inp).simulate(
            method=method or "ode",
            t_start=float(t_start),
            t_end=float(t_end),
            n_steps=int(n_points if n_points is not None else 100),
            backend="bngsim" if simulator == "bngsim" else "native",
            verbose=not suppress,
        )

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
