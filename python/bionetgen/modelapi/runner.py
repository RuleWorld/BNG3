import os
import logging
from tempfile import TemporaryDirectory
from bionetgen.main import BioNetGen
from bionetgen.core.tools import BNGCLI

# This allows access to the CLIs config setup
app = BioNetGen()
app.setup()
conf = app.config["bionetgen"]

logger = logging.getLogger(__name__)


def _load_cpp_backend():
    """Return the in-process backend when installed, otherwise ``None``.

    Backend import availability is the only condition that permits the
    legacy subprocess path.  Parse and execution errors must remain visible;
    otherwise a real BNG3 failure can be silently replaced by Perl behavior.
    """
    try:
        from bionetgen import _bionetgen_cpp as cpp
    except ImportError:
        return None
    return cpp


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
    Convenience function to run a BNGL model as a library

    Usage: run(path_to_input_file, output_folder)

    Arguments
    ---------
    inp : str
        Path to a BNGL file.
    out : str, optional
        Folder for the results of the model's actions.
    simulator : str
        'auto' or 'native' runs the BNG3 engine; 'subprocess' forces the
        legacy BNG2.pl route; 'bngsim' runs one simulation with the BNGsim
        backend and needs ``method``.
    format : str, optional
        Input format hint. Only 'bngl' is accepted; convert SBML with the
        Atomizer first.
    method, t_span, n_points : optional
        When any is given, run one simulation of the model with this method
        (default 'ode'), time span (t_start, t_end) (default (0, 100)) and
        number of output points (default 100), instead of the model's
        actions, and return its result.
    """
    from bionetgen.core.exc import BNGFormatError

    if format is not None and str(format).lower() != "bngl":
        raise BNGFormatError(
            inp,
            f"run() accepts BNGL input only, not format={format!r}; convert "
            "SBML with bionetgen.atomizer first",
        )
    if simulator not in {"auto", "native", "subprocess", "bngsim"}:
        raise ValueError("simulator must be 'auto', 'native', 'subprocess' or 'bngsim'")
    if simulator == "bngsim" or any(
        value is not None for value in (method, t_span, n_points)
    ):
        from bionetgen.model import load

        t_start, t_end = (0.0, 100.0) if t_span is None else t_span
        return load(inp).simulate(
            method=method or "ode",
            t_start=float(t_start),
            t_end=float(t_end),
            n_steps=int(n_points if n_points is not None else 100),
            backend="bngsim" if simulator == "bngsim" else "native",
        )
    if simulator == "subprocess":
        return _run_subprocess(inp, out, suppress, timeout)
    # Try C++ backend first.  Only an unavailable extension permits the
    # legacy subprocess path; backend failures are product failures.
    cpp = _load_cpp_backend()
    if cpp is not None:
        model = cpp.parse_file(inp)
        return cpp.execute(model, inp)

    return _run_subprocess(inp, out, suppress, timeout)


def _run_subprocess(inp, out, suppress, timeout):
    """Run the model's actions through the legacy BNG2.pl subprocess route."""
    # Fall back to the existing BNGCLI subprocess approach
    cur_dir = os.getcwd()
    if out is None:
        with TemporaryDirectory() as out:
            # instantiate a CLI object with the info
            cli = BNGCLI(inp, out, conf["bngpath"], suppress=suppress, timeout=timeout)
            try:
                cli.run()
                os.chdir(cur_dir)
            except Exception as e:
                os.chdir(cur_dir)
                logger.error("Couldn't run the simulation, see error")
                if hasattr(e, "stdout") and e.stdout is not None:
                    logger.error(f"STDOUT:\n{e.stdout}")
                if hasattr(e, "stderr") and e.stderr is not None:
                    logger.error(f"STDERR:\n{e.stderr}")
                raise e
    else:
        # instantiate a CLI object with the info
        cli = BNGCLI(inp, out, conf["bngpath"], suppress=suppress, timeout=timeout)
        try:
            cli.run()
            os.chdir(cur_dir)
        except Exception as e:
            os.chdir(cur_dir)
            logger.error("Couldn't run the simulation, see error")
            if hasattr(e, "stdout") and e.stdout is not None:
                logger.error(f"STDOUT:\n{e.stdout}")
            if hasattr(e, "stderr") and e.stderr is not None:
                logger.error(f"STDERR:\n{e.stderr}")
            raise e
    return cli.result
