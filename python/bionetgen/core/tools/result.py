import os
import numpy as np

from bionetgen.core.exc import BNGFileError
from bionetgen.core.utils.logging import BNGLogger


class BNGResult:
    """
    Class that loads in gdat/cdat/scan files

    Usage: BNGResult(path="/path/to/folder") OR
           BNGResult(path="/path/to/file.gdat")

    Arguments
    ---------
    path : str
        path that points to a folder containing files to be
        loaded by the class, or a direct path to a file
    direct_path : str
        (Deprecated) path that directly points to a file to load

    Methods
    -------
    load(fpath)
        loads in the direct path to the file and returns
        numpy.recarray
    """

    def __init__(self, path=None, direct_path=None, ext=None, app=None):
        self.app = app
        self.logger = BNGLogger(app=self.app)
        self.logger.debug(
            "Setting up BNGResult object", loc=f"{__file__} : BNGResult.__init__()"
        )
        # defaults
        self.process_return = None
        self.output = None
        if ext is not None:
            if isinstance(ext, str):
                self.ext = [ext]
            else:
                self.ext = list(ext)
        else:
            self.ext = None

        self.gdats = {}
        self.cdats = {}
        self.scans = {}
        self.cnames = {}
        self.snames = {}
        self.gnames = {}
        if direct_path is not None:
            path = direct_path

        if path is not None:
            if os.path.isfile(path):
                dpath, fname = os.path.split(path)
                fnoext, fext = os.path.splitext(fname)
                self.direct_path = path
                self.file_name = fnoext
                self.file_extension = fext
                self.gnames[fnoext] = path
                self.gdats[fnoext] = self.load(path)
            elif os.path.isdir(path):
                self.path = path
                self.find_dat_files()
                self.load_results()
            else:
                self.logger.info(
                    f"BNGResult path {path} is neither a file nor a directory",
                    loc=f"{__file__} : BNGResult.__init__()",
                )
        else:
            self.logger.info(
                "BNGResult needs a path kwarg to load gdat/cdat/scan files from",
                loc=f"{__file__} : BNGResult.__init__()",
            )

    def __repr__(self) -> str:
        s = f"gdats from {len(self.gdats)} models: "
        if self.gdats:
            s += " ".join(self.gdats) + " "
        if self.cdats:
            s += f"\ncdats from {len(self.cdats)} models: " + " ".join(self.cdats) + " "
        if self.scans:
            s += f"\nscans from {len(self.scans)} models: " + " ".join(self.scans) + " "
        return s

    def __getitem__(self, key):
        if isinstance(key, int):
            k = list(self.gdats.keys())[key]
            it = self.gdats[k]
        else:
            it = self.gdats[key]
        return it

    def __iter__(self):
        return self.gdats.__iter__()

    def load(self, fpath):
        self.logger.debug(f"Loading file {fpath}", loc=f"{__file__} : BNGResult.load()")
        path, fname = os.path.split(fpath)
        fnoext, fext = os.path.splitext(fname)
        if fext == ".gdat" or fext == ".cdat":
            return self._load_dat(fpath)
        elif fext == ".scan":
            return self._load_scan(fpath)
        else:
            self.logger.info(
                "BNGResult doesn't know the file type of {}".format(fpath),
                loc=f"{__file__} : BNGResult.load()",
            )
            return None

    def _load_scan(self, fpath):
        return self._load_dat(fpath)

    def find_dat_files(self, folder_path=None):
        folder_path = folder_path or getattr(self, "path", None)
        if folder_path is None:
            self.logger.info(
                "BNGResult.find_dat_files needs a folder path.",
                loc=f"{__file__} : BNGResult.find_dat_files()",
            )
            return

        self.logger.debug(
            f"Scanning for valid files in folder {folder_path}",
            loc=f"{__file__} : BNGResult.find_dat_files()",
        )
        files = os.listdir(folder_path)

        exts_to_load = ["gdat", "cdat", "scan"]
        if self.ext is not None:
            exts_to_load = [e for e in self.ext if e in exts_to_load]

        if "gdat" in exts_to_load:
            ext = "gdat"
            gdat_files = filter(lambda x: x.endswith(f".{ext}"), files)
            for dat_file in gdat_files:
                name = dat_file.replace(f".{ext}", "")
                self.gnames[name] = dat_file

        if "cdat" in exts_to_load:
            ext = "cdat"
            cdat_files = filter(lambda x: x.endswith(f".{ext}"), files)
            for dat_file in cdat_files:
                name = dat_file.replace(f".{ext}", "")
                self.cnames[name] = dat_file

        if "scan" in exts_to_load:
            ext = "scan"
            scan_files = filter(lambda x: x.endswith(f".{ext}"), files)
            for dat_file in scan_files:
                name = dat_file.replace(f".{ext}", "")
                self.snames[name] = dat_file

    def load_results(self, folder_path=None):
        folder_path = folder_path or getattr(self, "path", None)
        if folder_path is None:
            self.logger.info(
                "BNGResult.load_results needs a folder path.",
                loc=f"{__file__} : BNGResult.load_results()",
            )
            return

        self.logger.debug(
            f"Loading results from {folder_path}",
            loc=f"{__file__} : BNGResult.load_results()",
        )
        # load gdat files
        for name in self.gnames:
            gdat_path = os.path.join(folder_path, self.gnames[name])
            self.gdats[name] = self.load(gdat_path)
        # load cdat files
        for name in self.cnames:
            cdat_path = os.path.join(folder_path, self.cnames[name])
            self.cdats[name] = self.load(cdat_path)
        # load scan files
        for name in self.snames:
            scan_path = os.path.join(folder_path, self.snames[name])
            self.scans[name] = self.load(scan_path)

    def _load_dat(self, path, dformat="f8"):
        """
        This function takes a path to a gdat/cdat file as a string and loads that
        file into a numpy structured array, including the correct header info.

        Optional argument allows you to set the data type for every column. See
        numpy dtype/data type strings for what's allowed. Note: https://numpy.org/doc/stable/reference/arrays.dtypes.html
        """
        # First step is to read the header,
        # we gotta open the file and pull that line in
        with open(path, "r") as f:
            header = f.readline()
        # Ensure the header info is actually there
        if not header.startswith("#"):
            self.logger.error(
                "No header line that starts with # in file {}".format(path),
                loc=f"{__file__} : BNGResult._load_dat()",
            )
            raise BNGFileError(path, "No header line that starts with #")
        # Now turn it into a list of names for our struct array
        header = header.replace("#", "")
        headers = header.split()
        # For a magical reason this is how numpy.loadtxt wants it,
        # in tuples passed as a dictionary with names/formats as keys
        names = tuple(headers)
        formats = tuple([dformat for i in range(len(headers))])
        # return the loadtxt result as a record array
        # which is similar to pandas data format without the helper functions
        return np.rec.array(
            np.loadtxt(path, dtype={"names": names, "formats": formats})
        )
