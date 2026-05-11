import platform, os, subprocess
from cement import init_defaults
from cement.utils.version import get_version_banner
from .version import get_version


def get_latest_bng_version():
    """
    Pulls the currently used BNG version.

    First tries bionetgen.__version__, then falls back to assets/BNGVERSION file.
    """
    try:
        import bionetgen

        return bionetgen.__version__
    except Exception:
        pass
    # fallback to BNGVERSION file
    libpath = os.path.abspath(__file__)
    libpath = libpath.split(os.path.sep)
    verpath = os.path.sep.join(libpath[:-2] + ["assets", "BNGVERSION"])
    if os.path.isfile(verpath):
        with open(verpath) as f:
            tag = f.read()
        return tag
    else:
        return "UNKNOWN"


def _has_cpp_backend():
    """Check if the C++ backend extension is importable."""
    try:
        import bionetgen._bionetgen_cpp  # noqa: F401

        return True
    except ImportError:
        return False


class BNGDefaults:
    """
    A class to define the default configuration for cement apps

    Attributes
    ----------
    system : str
        the name of the OS that's running the app
    bng_name : str
        OS appropriate name of the BNG folder
    bng_path : str
        full absolute path to the BNG folder (None if not found)
    lib_path : str
        path to CLI library
    stdout : str
        the name of the subprocess attribute to pass stdout to
    stderr : str
        the name of the subprocess attribute to pass stderr to
    config : dict
        dictionary containing the application defaults
    banner : str
        app banner that gets printed when ran with -v
    has_cpp_backend : bool
        whether the C++ backend extension is available
    """

    def __init__(self):
        # determine what bng we are using
        system = platform.system()
        if system == "Linux":
            bng_name = "bng-linux"
        elif system == "Windows":
            bng_name = "bng-win"
        elif system == "Darwin":
            bng_name = "bng-mac"
        else:
            bng_name = None
        # set attributes
        self.system = system
        self.bng_name = bng_name
        self.has_cpp_backend = _has_cpp_backend()
        # configuration defaults
        CONFIG = init_defaults("bionetgen")
        lib_path = os.path.dirname(__file__)
        lib_path = os.path.split(lib_path)[0]
        # Only set bng_path if the directory actually exists
        if bng_name is not None:
            candidate_path = os.path.join(lib_path, bng_name)
            if os.path.isdir(candidate_path):
                CONFIG["bionetgen"]["bngpath"] = candidate_path
                self.bng_path = candidate_path
            else:
                CONFIG["bionetgen"]["bngpath"] = None
                self.bng_path = None
        else:
            CONFIG["bionetgen"]["bngpath"] = None
            self.bng_path = None
        # notebook
        CONFIG["bionetgen"]["notebook"] = {}
        notebook_path = os.path.join(lib_path, "assets", "bionetgen.ipynb")
        template_path = os.path.join(lib_path, "assets", "bionetgen-temp.ipynb")
        CONFIG["bionetgen"]["notebook"]["path"] = (
            notebook_path if os.path.isfile(notebook_path) else None
        )
        CONFIG["bionetgen"]["notebook"]["template"] = (
            template_path if os.path.isfile(template_path) else None
        )
        CONFIG["bionetgen"]["notebook"]["name"] = "bng-notebook.ipynb"
        # cvode paths
        CONFIG["bionetgen"]["cvode_lib"] = None
        CONFIG["bionetgen"]["cvode_include"] = None
        # set attributes
        self.lib_path = lib_path
        # version banner
        VERSION_BANNER = (
            "BioNetGen simple command line interface {}\n" "BioNetGen version: {}\n{}\n"
        ).format(get_version(), get_latest_bng_version(), get_version_banner())
        # set attributes
        self.banner = VERSION_BANNER
        # stdout
        CONFIG["bionetgen"]["stdout"] = "PIPE"
        CONFIG["bionetgen"]["stderr"] = "STDOUT"
        self.stdout = subprocess.PIPE
        self.stderr = subprocess.PIPE
        self.config = CONFIG


defaults = BNGDefaults()
