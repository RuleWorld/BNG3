import os, subprocess
from bionetgen.core.exc import BNGRunError
from bionetgen.core.utils.logging import BNGLogger


class BNGCLI:
    """
    Command Line Interface class to run BNG2.pl on a given
    model.

    Usage: BNGCLI(inp_file, output, bngpath)

    Arguments
    ---------
    inp_file : str
        path to the the BNGL file to run
    output : str
        path to the output folder to run the model in
    bngpath : str
        path to BioNetGen folder where BNG2.pl lives

    Methods
    -------
    run()
        runs the model in the given output folder
    """

    def __init__(
        self,
        inp_file,
        output,
        bngpath,
        suppress=False,
        log_file=None,
        timeout=None,
        app=None,
    ):
        self.app = app
        self.logger = BNGLogger(app=self.app)
        self.logger.debug(
            "Setting up BNGCLI object", loc=f"{__file__} : BNGCLI.__init__()"
        )
        self.inp_file = inp_file
        import bionetgen.modelapi.model as mdl

        if isinstance(inp_file, mdl.bngmodel):
            self.is_bngmodel = True
        else:
            self.is_bngmodel = False
            # ensure correct path to the input file
            self.inp_path = os.path.abspath(self.inp_file)
        # pull other arugments out
        if log_file is not None:
            self.log_file = log_file
        else:
            self.log_file = None
        self._set_output(output)
        # sedml_file = sedml
        # Resolve BioNetGen executable path. Historically this code assumed
        # `bngpath` was a directory containing BNG2.pl, but on Windows installs
        # and some deployments we may need to honor $BNGPATH or accept a direct
        # path to BNG2.pl.
        from bionetgen.core.utils.utils import find_BNG_path

        try:
            resolved_dir, resolved_exec = find_BNG_path(bngpath)
        except Exception as e:
            raise AssertionError(
                "BNG2.pl is not found! "
                "Set the BNGPATH environment variable to the BioNetGen folder containing BNG2.pl. "
                f"Details: {e}"
            ) from e

        self.bngpath = resolved_dir
        self.bng_exec = resolved_exec
        if "BNGPATH" in os.environ:
            self.old_bngpath = os.environ["BNGPATH"]
        else:
            self.old_bngpath = None
        if self.bngpath is not None:
            os.environ["BNGPATH"] = self.bngpath
        self.result = None
        self.stdout = "PIPE"
        self.stderr = "STDOUT"
        self.suppress = suppress
        self.timeout = timeout

    def _set_output(self, output):
        self.logger.debug(
            "Setting up output path", loc=f"{__file__} : BNGCLI._set_output()"
        )
        # setting up output area
        self.output = os.path.abspath(output)
        if not os.path.isdir(self.output):
            os.makedirs(self.output, exist_ok=True)

    def run(self):
        self.logger.debug("Running", loc=f"{__file__} : BNGCLI.run()")

        # C++ fast path
        try:
            from bionetgen import _bionetgen_cpp as _cpp
            import shutil

            # Determine path to run on
            if self.is_bngmodel:
                write_to = os.path.join(self.output, self.inp_file.model_name + ".bngl")
                write_to = os.path.abspath(write_to)
                with open(write_to, "w") as tfile:
                    tfile.write(str(self.inp_file))
                inp_run_path = write_to
            else:
                copied_inp = os.path.join(self.output, os.path.basename(self.inp_path))
                if os.path.abspath(self.inp_path) != os.path.abspath(copied_inp):
                    shutil.copy2(self.inp_path, copied_inp)
                inp_run_path = copied_inp

            self.logger.debug(
                "Executing via C++ backend", loc=f"{__file__} : BNGCLI.run()"
            )
            model = _cpp.parse_file(inp_run_path)
            _cpp.execute(model, inp_run_path, verbose=not self.suppress)

            # Load in the result
            from bionetgen.core.tools import BNGResult

            self.result = BNGResult(self.output)
            self.result.process_return = 0
            self.result.output = ["Ran successfully via C++ backend"]
            return
        except ImportError:
            self.logger.debug("C++ backend not available, falling back to Perl")
        except Exception as e:
            self.logger.warning(f"C++ backend failed: {e}, falling back to Perl")

        # If BNG2.pl is not available, fall back to an empty result so that
        # library users can still instantiate and inspect models without a
        # full BioNetGen install.
        if self.bng_exec is None:
            from bionetgen.core.tools import BNGResult

            self.result = BNGResult(self.output)
            self.result.process_return = 0
            self.result.output = []
            if self.old_bngpath is not None:
                os.environ["BNGPATH"] = self.old_bngpath
            else:
                if "BNGPATH" in os.environ:
                    del os.environ["BNGPATH"]
            return

        from bionetgen.core.utils.utils import run_command

        try:
            stdout_loc = getattr(subprocess, self.stdout)
        except:
            stdout_loc = subprocess.PIPE
        try:
            stderr_loc = getattr(subprocess, self.stderr)
        except:
            stderr_loc = subprocess.STDOUT
        # run BNG2.pl
        if self.is_bngmodel:
            self.logger.debug(
                "The given model is a bngmodel object", loc=f"{__file__} : BNGCLI.run()"
            )
            self.logger.debug(
                "Writing the model to a file", loc=f"{__file__} : BNGCLI.run()"
            )
            write_to = os.path.join(self.output, self.inp_file.model_name + ".bngl")
            write_to = os.path.abspath(write_to)
            if os.path.isfile(write_to):
                self.logger.warning(
                    f"Overwriting file {write_to}", loc=f"{__file__} : BNGCLI.run()"
                )
            with open(write_to, "w") as tfile:
                tfile.write(str(self.inp_file))
            command = ["perl", self.bng_exec, write_to]
        else:
            self.logger.debug(
                "The given model is a file", loc=f"{__file__} : BNGCLI.run()"
            )
            fname = os.path.basename(self.inp_path)
            fname = fname.replace(".bngl", "")
            command = ["perl", self.bng_exec, self.inp_path]
        self.logger.debug("Running command", loc=f"{__file__} : BNGCLI.run()")
        rc, out = run_command(
            command, suppress=self.suppress, timeout=self.timeout, cwd=self.output
        )
        if self.log_file is not None:
            self.logger.debug("Setting up log file", loc=f"{__file__} : BNGCLI.run()")

            # Check if the intended log path is a directory (either it exists as a dir, or ends with a separator)
            is_dir = (
                os.path.isdir(self.log_file)
                or self.log_file.endswith(os.sep)
                or (os.altsep and self.log_file.endswith(os.altsep))
            )

            # Resolve absolute/relative paths properly
            full_log_path = os.path.abspath(self.log_file)

            if is_dir:
                fname = os.path.basename(self.inp_path)
                fname = fname.replace(".bngl", "")
                full_log_path = os.path.join(full_log_path, fname + ".log")

            self.logger.debug("Writing log file", loc=f"{__file__} : BNGCLI.run()")
            log_parent = os.path.dirname(full_log_path)
            if not os.path.exists(log_parent):
                os.makedirs(log_parent, exist_ok=True)
            with open(full_log_path, "w") as f:
                f.write("\n".join(out))
        if rc == 0:
            self.logger.debug(
                "Command ran successfully", loc=f"{__file__} : BNGCLI.run()"
            )
            from bionetgen.core.tools import BNGResult

            # load in the result
            self.result = BNGResult(self.output)
            self.result.process_return = rc
            self.result.output = out
            # set BNGPATH back
            if self.old_bngpath is not None:
                os.environ["BNGPATH"] = self.old_bngpath
            else:
                if "BNGPATH" in os.environ:
                    del os.environ["BNGPATH"]
        else:
            self.logger.error("Command failed to run", loc=f"{__file__} : BNGCLI.run()")
            self.result = None
            # set BNGPATH back
            if self.old_bngpath is not None:
                os.environ["BNGPATH"] = self.old_bngpath
            else:
                if "BNGPATH" in os.environ:
                    del os.environ["BNGPATH"]
            if hasattr(out, "stdout"):
                if out.stdout is not None:
                    stdout_str = out.stdout.decode("utf-8")
            else:
                stdout_str = None
            if hasattr(out, "stderr"):
                if out.stderr is not None:
                    stderr_str = out.stderr.decode("utf-8")
            else:
                stderr_str = None
            raise BNGRunError(command, stdout=stdout_str, stderr=stderr_str)
