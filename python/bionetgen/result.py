"""Simulation result container."""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np


class SimResult:
    """Container for simulation output.

    Attributes
    ----------
    time : np.ndarray
        1D array of time points.
    observables : dict[str, np.ndarray]
        Observable name → 1D array of values at each time point.
    concentrations : np.ndarray or None
        2D array (n_steps × n_species) of species concentrations (ODE/SSA only).
    """

    def __init__(self, raw: dict):
        self.time: np.ndarray = raw.get("time", np.array([]))
        self.observables: Dict[str, np.ndarray] = raw.get("observables", {})
        self.concentrations: Optional[np.ndarray] = raw.get("concentrations", None)

    @property
    def n_steps(self) -> int:
        return len(self.time)

    @property
    def observable_names(self) -> list:
        return list(self.observables.keys())

    def to_dataframe(self):
        """Convert results to a pandas DataFrame.

        Requires pandas to be installed.
        """
        import pandas as pd

        data = {"time": self.time}
        for name, values in self.observables.items():
            data[name] = values
        return pd.DataFrame(data)

    def plot(self, observables=None, show=True, **kwargs):
        """Plot observable time courses.

        Parameters
        ----------
        observables : list of str, optional
            Subset of observables to plot. If None, plot all.
        show : bool, optional
            Whether to call plt.show() after creating the plot. Default is True.
        **kwargs
            Passed to matplotlib's plot function.
        """
        import matplotlib.pyplot as plt

        if observables is None:
            observables = self.observable_names

        fig, ax = plt.subplots()
        for name in observables:
            if name in self.observables:
                ax.plot(self.time, self.observables[name], label=name, **kwargs)
        ax.set_xlabel("Time")
        ax.set_ylabel("Count / Concentration")
        ax.legend()

        if show:
            plt.show()

        return fig, ax

    def __repr__(self) -> str:
        return (
            f"<SimResult steps={self.n_steps} " f"observables={len(self.observables)}>"
        )

    def _repr_html_(self) -> str:
        from bionetgen.display import render_sim_result_html

        return render_sim_result_html(self)
