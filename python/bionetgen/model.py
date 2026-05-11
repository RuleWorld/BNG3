"""High-level Python model interface wrapping the C++ BioNetGen engine."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

try:
    from . import _bionetgen_cpp as _cpp
except ImportError:
    try:
        import _bionetgen_cpp as _cpp
    except ImportError:
        _cpp = None

from bionetgen.result import SimResult


class BioNetGenModel:
    """A BNGL model backed by the C++ engine.

    Provides Pythonic access to model components (parameters, molecule types,
    reaction rules, observables, seed species) and simulation methods.
    """

    def __init__(self, cpp_model: _cpp.Model, source_path: Optional[str] = None):
        self._model = cpp_model
        self._source_path = source_path
        self._network: Optional[_cpp.GeneratedNetwork] = None

    @property
    def parameters(self) -> list:
        return self._model.parameters

    @property
    def molecule_types(self) -> list:
        return self._model.molecule_types

    @property
    def seed_species(self) -> list:
        return self._model.seed_species

    @property
    def observables(self) -> list:
        return self._model.observables

    @property
    def reaction_rules(self) -> list:
        return self._model.reaction_rules

    @property
    def functions(self) -> list:
        return self._model.functions

    @property
    def compartments(self) -> list:
        return self._model.compartments

    @property
    def actions(self) -> list:
        return self._model.actions

    @property
    def name(self) -> str:
        return self._model.model_name

    def set_parameter(self, name: str, value: float) -> None:
        self._model.set_parameter(name, value)

    def generate_network(self, max_iter: int = 100) -> _cpp.GeneratedNetwork:
        self._network = _cpp.generate_network(self._model, max_iter=max_iter)
        return self._network

    def simulate(
        self,
        method: str = "ode",
        t_end: float = 100.0,
        n_steps: int = 100,
        t_start: float = 0.0,
        rtol: float = 1e-8,
        atol: float = 1e-8,
        seed: int = 0,
        verbose: bool = False,
    ) -> SimResult:
        """Run a simulation using the specified method.

        Parameters
        ----------
        method : str
            One of "ode", "ssa", or "nf" (network-free).
        t_end : float
            End time for simulation.
        n_steps : int
            Number of output time steps.
        t_start : float
            Start time for simulation.
        rtol, atol : float
            Relative and absolute tolerances (ODE only).
        seed : int
            Random seed (SSA/NF only; 0 = system default).
        verbose : bool
            Print progress information.

        Returns
        -------
        SimResult
            Object containing time, observable, and concentration arrays.
        """
        if method == "nf":
            raw = _cpp.simulate_nf(
                self._model,
                t_end=t_end,
                n_steps=n_steps,
                seed=seed,
                verbose=verbose,
            )
        else:
            if self._network is None:
                self.generate_network()

            if method == "ode":
                raw = _cpp.simulate_ode(
                    self._model,
                    self._network,
                    t_end=t_end,
                    n_steps=n_steps,
                    t_start=t_start,
                    rtol=rtol,
                    atol=atol,
                )
            elif method == "ssa":
                raw = _cpp.simulate_ssa(
                    self._model,
                    self._network,
                    t_end=t_end,
                    n_steps=n_steps,
                    t_start=t_start,
                    seed=seed,
                )
            else:
                raise ValueError(
                    f"Unknown simulation method: {method!r}. Use 'ode', 'ssa', or 'nf'."
                )

        return SimResult(raw)

    def execute(self, verbose: bool = False) -> None:
        """Execute all actions defined in the model's action block."""
        source = self._source_path or "."
        _cpp.execute(self._model, source, verbose=verbose)

    def write_xml(self, path: str) -> None:
        _cpp.io.write_xml(self._model, path)

    def write_bngl(self, path: str) -> None:
        _cpp.io.write_bngl(self._model, path)

    def write_net(self, path: str) -> None:
        if self._network is None:
            self.generate_network()
        _cpp.io.write_net(self._model, self._network, path)

    def write_sbml(self, path: str) -> None:
        if self._network is None:
            self.generate_network()
        _cpp.io.write_sbml(self._model, self._network, path)

    def write_matlab(self, path: str) -> None:
        if self._network is None:
            self.generate_network()
        _cpp.io.write_matlab(self._model, self._network, path)

    def write_latex(self, path: str) -> None:
        if self._network is None:
            self.generate_network()
        _cpp.io.write_latex(self._model, self._network, path)

    def __repr__(self) -> str:
        name = self.name or "(unnamed)"
        return (
            f"<BioNetGenModel '{name}' "
            f"rules={len(self.reaction_rules)} "
            f"species={len(self.seed_species)}>"
        )


def load(path: Union[str, Path]) -> BioNetGenModel:
    """Load a BNGL model file.

    Parameters
    ----------
    path : str or Path
        Path to the .bngl file.

    Returns
    -------
    BioNetGenModel
        The loaded model.
    """
    path = str(Path(path).resolve())
    cpp_model = _cpp.parse_file(path)
    return BioNetGenModel(cpp_model, source_path=path)


def run(
    path: Union[str, Path],
    method: str = "ode",
    t_end: float = 100.0,
    n_steps: int = 100,
    **kwargs,
) -> SimResult:
    """Load a model and run its simulation in one call.

    Parameters
    ----------
    path : str or Path
        Path to the .bngl file.
    method : str
        Simulation method ("ode", "ssa", "nf").
    t_end : float
        End time.
    n_steps : int
        Number of output steps.

    Returns
    -------
    SimResult
        Simulation results.
    """
    model = load(path)
    return model.simulate(method=method, t_end=t_end, n_steps=n_steps, **kwargs)
