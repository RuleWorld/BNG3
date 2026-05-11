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
    # Try C++ backend first
    try:
        from bionetgen import _bionetgen_cpp as _cpp

        model = _cpp.parse_file(inp)
        return _cpp.execute(model, inp)
    except (ImportError, AttributeError, Exception):
        pass

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
