import logging
import os
from tempfile import TemporaryDirectory

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

    Returns a :class:`bionetgen.core.tools.result.BNGResult`.
    """
    from bionetgen.compat.runner import run as compat_run

    # Preserve PyBioNetGen's argument surface. BNG3 implements the runner via
    # the compatibility backend; unsupported legacy combinations raise explicit
    # errors from the compat layer.
    if format is not None and str(format).lower() != "bngl":
        from bionetgen.core.exc import BNGFormatError

        raise BNGFormatError(
            inp,
            f"run() accepts BNGL input only, not format={format!r}; convert "
            "SBML with bionetgen.atomizer first",
        )
    if simulator not in {"auto", "native", "subprocess", "bngsim"}:
        raise ValueError("simulator must be 'auto', 'native', 'subprocess' or 'bngsim'")

    # Explicit method/t_span/n_points are handled by compat runner as overrides.
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
