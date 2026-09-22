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
    functions : dict[str, np.ndarray]
        Exported zero-argument function name → values at each time point.
    concentrations : np.ndarray or None
        2D array (n_steps × n_species) of species concentrations (ODE/SSA only).
    construction_path : str or None
        Backend construction route when reported by the simulator. For NFsim this
        is ``"direct"``, ``"in-memory-xml"``, or ``"on-disk-xml"``.
    backend : str or None
        Finite-network backend that produced the result: ``"native"``,
        ``"bngsim"``, or ``"nfsim"`` (diagnostic, ADR 0003).
    direct_unavailable_reason : str or None
        For NFsim, the precise reason the direct AST path declined, when it did.
        Empty or ``None`` on the ``"direct"`` path. Names the failing
        construction stage (for example ``stage 'reaction rules' could not be
        constructed directly``), the capability diagnostic, or the thrown
        message, so a compatibility fallback can be audited rather than just
        observed.
    """

    def __init__(self, raw: dict):
        self.time: np.ndarray = raw.get("time", np.array([]))
        self.observables: Dict[str, np.ndarray] = raw.get("observables", {})
        self.functions: Dict[str, np.ndarray] = raw.get("functions", {})
        self.concentrations: Optional[np.ndarray] = raw.get("concentrations", None)
        self.construction_path: Optional[str] = raw.get("construction_path", None)
        # Finite-network backend diagnostic (ADR 0003): "native", "bngsim", or "nfsim".
        self.backend: Optional[str] = raw.get("backend", None)
        self.direct_unavailable_reason: Optional[str] = raw.get(
            "direct_unavailable_reason", None
        )

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
        b = f" backend={self.backend}" if self.backend else ""
        return (
            f"<SimResult steps={self.n_steps} observables={len(self.observables)}{b}>"
        )

    def _repr_html_(self) -> str:
        from bionetgen.display import render_sim_result_html

        return render_sim_result_html(self)
