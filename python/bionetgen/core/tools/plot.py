from bionetgen.core.exc import BNGError, BNGFileError
from bionetgen.core.tools import BNGResult
from bionetgen.core.utils.logging import BNGLogger


class BNGPlotter:
    """
    Class that does basic plotting for gdat/cdat files

    Usage BNGPlotter(inp, out, kwargs)

    Arguments
    ---------
    inp : str
        input file path, gdat/cdat/scan file
    out : str
        output file path
    kwargs : dict
        keywords arguments for matplotlib. For details check
        bionetgen plot -h

    Methods
    -------
    plot()
        plots the data from the input file and saves it to
        output file the class is initialized with
    """

    def __init__(self, inp, out, app=None, **kwargs):
        self.app = app
        self.logger = BNGLogger(app=self.app)
        self.logger.debug(
            "Setting up BNGPlotter object", loc=f"{__file__} : BNGPlotter.__init__()"
        )
        # read input and output paths
        self.inp = inp
        self.out = out
        # load in the result
        self.logger.debug(
            f"Loading BNG result file {inp}", loc=f"{__file__} : BNGPlotter.__init__()"
        )
        self.result = BNGResult(direct_path=inp, app=self.app)
        # get the keyword arguments
        self.kwargs = kwargs

    def plot(self):
        # let's determine the type of plot we are doing
        if (
            self.result.file_extension == ".gdat"
            or self.result.file_extension == ".cdat"
        ):
            self.logger.debug(
                "Input is a .gdat/.cdat file", loc=f"{__file__} : BNGPlotter.plot()"
            )
            self._datplot()
        elif self.result.file_extension == ".scan":
            self.logger.debug(
                "Input is a .scan file", loc=f"{__file__} : BNGPlotter.plot()"
            )
            self._datplot()
        else:
            self.logger.error(
                "File type not recognized, only gdat/cdat and scan files are implemented",
                loc=f"{__file__} : BNGPlotter.plot()",
            )
            raise NotImplementedError

    def _datplot(self):
        self.logger.debug(
            f"Plotting .gdat/.cdat/.scan file {self.result.file_name}",
            loc=f"{__file__} : BNGPlotter._datplot()",
        )
        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:
            raise ImportError(
                "Plotting requires matplotlib; install it with `pip install 'bionetgen[plotting]'`"
            ) from exc
        try:
            import seaborn as sbrn
        except ImportError:
            sbrn = None

        # get the data out of result object
        self.data = self.result[self.result.file_name]
        # get species names
        names = self.data.dtype.names
        x_name = names[0]
        # loop over and plot them all
        ctr = 0
        fig, ax = plt.subplots()
        for name in names:
            if name == x_name:
                continue
            if sbrn is not None:
                ax = sbrn.lineplot(
                    x=self.data[x_name], y=self.data[name], label=name, ax=ax
                )
            else:
                ax.plot(self.data[x_name], self.data[name], label=name)
            ctr += 1
        if ctr == 0:
            plt.close(fig)
            self.logger.error(
                "No data columns are found in file {}".format(self.result.direct_path),
                loc=f"{__file__} : BNGPlotter._datplot()",
            )
            raise BNGFileError(
                self.result.direct_path,
                "No data columns are found in file {}".format(self.result.direct_path),
            )

        fax = ax
        if self.kwargs.get("legend", False):
            fax.legend()
        else:
            existing_legend = fax.get_legend()
            if existing_legend is not None:
                existing_legend.remove()
        oxmin, oxmax = fax.get_xlim()
        oymin, oymax = fax.get_ylim()

        xmin = self.kwargs.get("xmin")
        xmax = self.kwargs.get("xmax")
        ymin = self.kwargs.get("ymin")
        ymax = self.kwargs.get("ymax")
        xmin = oxmin if xmin is None else xmin
        xmax = oxmax if xmax is None else xmax
        ymin = oymin if ymin is None else ymin
        ymax = oymax if ymax is None else ymax
        if not xmax > xmin:
            plt.close(fig)
            self.logger.error(
                "--xmin is bigger than --xmax!",
                loc=f"{__file__} : BNGPlotter._datplot()",
            )
            raise BNGError("--xmin is bigger than --xmax!")
        if not ymax > ymin:
            plt.close(fig)
            self.logger.error(
                "--ymin is bigger than --ymax!",
                loc=f"{__file__} : BNGPlotter._datplot()",
            )
            raise BNGError("--ymin is bigger than --ymax!")

        fax.set_xlim(left=xmin, right=xmax)
        fax.set_ylim(bottom=ymin, top=ymax)
        # labels and title
        fax.set_xlabel(self.kwargs.get("xlabel") or x_name)
        fax.set_ylabel(self.kwargs.get("ylabel") or "concentration")
        fax.set_title(self.kwargs.get("title") or self.result.file_name)

        self.logger.debug(
            f"Saving figure to {self.out}", loc=f"{__file__} : BNGPlotter._datplot()"
        )
        # save the figure
        fig.savefig(self.out)
        plt.close(fig)
