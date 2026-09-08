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


def run(inp, out=None, suppress=False, timeout=None):
    """
    Convenience function to run BNG2.pl as a library

    Usage: run(path_to_input_file, output_folder)

    Arguments
    ---------
    path_to_input_file : str
        this has to point to a BNGL file
    output_folder : str
        (optional) this points to a folder to put the results
        into. If it doesn't exist, it will be created.
    """
    # Try C++ backend first.  Only an unavailable extension permits the
    # legacy subprocess path; backend failures are product failures.
    cpp = _load_cpp_backend()
    if cpp is not None:
        model = cpp.parse_file(inp)
        return cpp.execute(model, inp)

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
