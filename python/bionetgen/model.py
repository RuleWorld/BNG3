"""High-level Python model interface wrapping the C++ BioNetGen engine."""

from __future__ import annotations

import math
import operator
from pathlib import Path
import sys
from typing import Optional, Union

try:
    from . import _bionetgen_cpp as _cpp
except ImportError:
    try:
        import _bionetgen_cpp as _cpp
    except ImportError:
        _cpp = None
    else:
        # CMake's development build places the extension in build/cpp rather
        # than inside the source package.  Register that fallback under the
        # package name so ``import bionetgen._bionetgen_cpp`` works exactly as
        # it does from an installed wheel.
        _module_name = f"{__package__}._bionetgen_cpp"
        sys.modules.setdefault(_module_name, _cpp)
        _package = sys.modules.get(__package__)
        if _package is not None:
            setattr(_package, "_bionetgen_cpp", _cpp)

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

    @property
    def source_path(self) -> Optional[str]:
        return self._source_path

    def get_parameter(self, name: str):
        return self._model.get_parameter(name)

    def set_parameter(self, name: str, value: float) -> None:
        self._model.set_parameter(name, value)

    def parameter_scan(self, *args, **kwargs):
        from bionetgen.scan import parameter_scan as _parameter_scan

        return _parameter_scan(self, *args, **kwargs)

    def parameter_scan_2d(self, *args, **kwargs):
        from bionetgen.scan import parameter_scan_2d as _parameter_scan_2d

        return _parameter_scan_2d(self, *args, **kwargs)

    def sensitivity_analysis(self, *args, **kwargs):
        from bionetgen.sensitivity import sensitivity_analysis as _sensitivity

        return _sensitivity(self, *args, **kwargs)

    def contact_map(self, path: Optional[str] = None):
        from bionetgen.viz import write_contact_map

        return write_contact_map(self, path)

    def regulatory_graph(self, path: Optional[str] = None):
        from bionetgen.viz import write_regulatory_graph

        return write_regulatory_graph(self, path)

    def rule_influence_graph(self, path: Optional[str] = None):
        from bionetgen.viz import write_rule_influence_graph

        return write_rule_influence_graph(self, path)

    def reaction_network_graph(self, path: Optional[str] = None):
        from bionetgen.viz import write_reaction_network_graph

        return write_reaction_network_graph(self, path)

    def ruleviz_pattern(self, path: Optional[str] = None):
        from bionetgen.viz import write_ruleviz_pattern

        return write_ruleviz_pattern(self, path)

    def ruleviz_operation(self, path: Optional[str] = None):
        from bionetgen.viz import write_ruleviz_operation

        return write_ruleviz_operation(self, path)

    def process_graph(self, path: Optional[str] = None):
        from bionetgen.viz import write_process_graph

        return write_process_graph(self, path)

    def sbml_multi(self, path: Optional[str] = None):
        from bionetgen.viz import write_sbml_multi

        return write_sbml_multi(self, path)

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
        pla_config: str = "",
        psa_poplevel: float = 100.0,
        verbose: bool = False,
        max_step: float = 0.0,
        steady_state: bool = False,
        steady_state_tol: Optional[float] = None,
        stop_if: str = "",
        sample_times=None,
        max_sim_steps: int = 0,
        output_step_interval: int = 0,
        sparse: bool = False,
        check_product_scale: float = 0.0,
        equilibrate: float = 0.0,
        traversal_limit: int = -1,
    ) -> SimResult:
        """Run a simulation using the specified method.

        Parameters
        ----------
        method : str
            One of "ode", "ssa", "nf" (network-free), "pla", or "psa".
        t_end : float
            End time for simulation.
        n_steps : int
            Number of output time steps.
        t_start : float
            Start time for ODE, SSA, PLA, or PSA simulation. NF currently
            supports only the default start time of zero.
        rtol, atol : float
            Relative and absolute tolerances (ODE only).
        seed : int
            Random seed (SSA/NF only; 0 = system default).
        pla_config : str
            PLA configuration string (PLA only).
        psa_poplevel : float
            Population level threshold for PSA (PSA only).
        verbose : bool
            Print progress information.
        max_step : float
            Maximum internal CVODE step size (ODE only; 0 disables the limit).
        steady_state : bool
            Stop an ODE run when the derivative norm is below the tolerance.
        steady_state_tol : float, optional
            Derivative tolerance for steady-state stopping.
        stop_if : str
            Expression evaluated at output points/events; a nonzero value stops
            ODE/SSA simulation.
        sample_times : sequence of float, optional
            Strictly increasing ODE/SSA/NF output times between ``t_start``
            and ``t_end``. If the final time is omitted, ``t_end`` is appended.
        max_sim_steps : int
            Maximum internal SSA reaction events (0 = unlimited).
        output_step_interval : int
            Output every N internal SSA reaction events when ``sample_times``
            is not set.
        sparse : bool
            Request the sparse CVODE linear solver.
        check_product_scale : float
            Warn when an ODE species exceeds this positive threshold.
        traversal_limit : int
            NFsim bonded-neighborhood traversal depth. ``-1`` uses the
            adapter's model-derived recommendation; non-negative values mirror
            NFsim's ``-utl`` control. NF only.

        Returns
        -------
        SimResult
            Object containing time, observable, and concentration arrays.
        """
        if not isinstance(method, str):
            raise TypeError("method must be a string")
        method = method.lower()
        if method not in {"ode", "ssa", "nf", "pla", "psa"}:
            raise ValueError(
                "Unknown simulation method: "
                f"{method!r}. Use 'ode', 'ssa', 'nf', 'pla', or 'psa'."
            )
        if not math.isfinite(float(t_start)) or not math.isfinite(float(t_end)):
            raise ValueError("t_start and t_end must be finite")
        if t_end < t_start:
            raise ValueError("t_end must be greater than or equal to t_start")
        if isinstance(n_steps, bool):
            raise TypeError("n_steps must be a positive integer")
        try:
            n_steps = operator.index(n_steps)
        except TypeError as exc:
            raise TypeError("n_steps must be a positive integer") from exc
        if n_steps < 0 or (n_steps == 0 and sample_times is None):
            raise ValueError("n_steps must be positive unless sample_times is set")
        if not math.isfinite(float(rtol)) or rtol <= 0.0:
            raise ValueError("rtol must be finite and positive")
        if not math.isfinite(float(atol)) or atol <= 0.0:
            raise ValueError("atol must be finite and positive")
        if not math.isfinite(float(psa_poplevel)):
            raise ValueError("psa_poplevel must be finite")
        if not math.isfinite(float(max_step)) or max_step < 0.0:
            raise ValueError("max_step must be finite and non-negative")
        if steady_state_tol is None:
            steady_state_tol = atol
        if not math.isfinite(float(steady_state_tol)) or steady_state_tol <= 0.0:
            raise ValueError("steady_state_tol must be finite and positive")
        if not isinstance(stop_if, str):
            raise TypeError("stop_if must be a string")
        if not math.isfinite(float(check_product_scale)) or check_product_scale < 0.0:
            raise ValueError("check_product_scale must be finite and non-negative")
        if not math.isfinite(float(equilibrate)) or equilibrate < 0.0:
            raise ValueError("equilibrate must be finite and non-negative")
        if isinstance(traversal_limit, bool):
            raise TypeError("traversal_limit must be -1 or a non-negative integer")
        try:
            traversal_limit = operator.index(traversal_limit)
        except TypeError as exc:
            raise TypeError(
                "traversal_limit must be -1 or a non-negative integer"
            ) from exc
        if traversal_limit < -1:
            raise ValueError("traversal_limit must be -1 or a non-negative integer")
        if method != "nf" and equilibrate != 0.0:
            raise ValueError("equilibrate is supported only for method='nf'")
        if method != "nf" and traversal_limit != -1:
            raise ValueError("traversal_limit is supported only for method='nf'")
        for option_name, option_value in {
            "max_sim_steps": max_sim_steps,
            "output_step_interval": output_step_interval,
        }.items():
            if isinstance(option_value, bool):
                raise TypeError(f"{option_name} must be a non-negative integer")
            try:
                option_value = operator.index(option_value)
            except TypeError as exc:
                raise TypeError(
                    f"{option_name} must be a non-negative integer"
                ) from exc
            if option_value < 0:
                raise ValueError(f"{option_name} must be a non-negative integer")
            if option_name == "max_sim_steps":
                max_sim_steps = option_value
            else:
                output_step_interval = option_value

        normalized_sample_times = []
        if sample_times is not None:
            try:
                normalized_sample_times = [float(value) for value in sample_times]
            except (TypeError, ValueError) as exc:
                raise TypeError("sample_times must be a sequence of numbers") from exc
            if not normalized_sample_times:
                raise ValueError("sample_times must not be empty")
            if any(not math.isfinite(value) for value in normalized_sample_times):
                raise ValueError("sample_times must contain only finite values")
            if any(
                later <= earlier
                for earlier, later in zip(
                    normalized_sample_times, normalized_sample_times[1:]
                )
            ):
                raise ValueError("sample_times must be strictly increasing")
            if (
                normalized_sample_times[0] < t_start
                or normalized_sample_times[-1] > t_end
            ):
                raise ValueError("sample_times must lie between t_start and t_end")
            if normalized_sample_times[-1] < t_end:
                normalized_sample_times.append(float(t_end))
        if n_steps == 0 and not normalized_sample_times:
            raise ValueError("n_steps must be positive unless sample_times is set")

        ode_only_options = (
            max_step > 0.0 or steady_state or sparse or check_product_scale > 0.0
        )
        if method != "ode" and ode_only_options:
            raise ValueError(
                "max_step, steady-state, sparse, and check_product_scale are "
                "supported only for method='ode'"
            )
        if method == "ode" and (max_sim_steps or output_step_interval):
            raise ValueError(
                "max_sim_steps and output_step_interval are supported only "
                "for method='ssa'"
            )
        if method not in {"ode", "ssa", "nf"} and (
            stop_if or max_sim_steps or output_step_interval
        ):
            raise ValueError(
                "stop_if, max_sim_steps, and output_step_interval are supported "
                "only for method='ode' or method='ssa'"
            )
        if method == "nf" and (stop_if or max_sim_steps or output_step_interval):
            raise ValueError(
                "stop_if, max_sim_steps, and output_step_interval are supported "
                "only for method='ode' or method='ssa'"
            )

        if method == "nf":
            if t_start != 0.0:
                raise ValueError("NF simulation currently supports only t_start=0.0")
            raw = _cpp.simulate_nf(
                self._model,
                t_end=t_end,
                n_steps=n_steps,
                seed=seed,
                verbose=verbose,
                equilibrate=equilibrate,
                source_path=self._source_path or "",
                sample_times=normalized_sample_times,
                traversal_limit=traversal_limit,
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
                    method="cvode",
                    max_step=max_step,
                    steady_state=steady_state,
                    steady_state_tol=steady_state_tol,
                    stop_if=stop_if,
                    sample_times=normalized_sample_times,
                    max_sim_steps=max_sim_steps,
                    output_step_interval=output_step_interval,
                    sparse=sparse,
                    check_product_scale=check_product_scale,
                )
            elif method == "ssa":
                raw = _cpp.simulate_ssa(
                    self._model,
                    self._network,
                    t_end=t_end,
                    n_steps=n_steps,
                    t_start=t_start,
                    seed=seed,
                    stop_if=stop_if,
                    sample_times=normalized_sample_times,
                    max_sim_steps=max_sim_steps,
                    output_step_interval=output_step_interval,
                )
            elif method == "pla":
                raw = _cpp.simulate_pla(
                    self._model,
                    self._network,
                    t_end=t_end,
                    n_steps=n_steps,
                    config_str=pla_config,
                    t_start=t_start,
                )
            elif method == "psa":
                raw = _cpp.simulate_psa(
                    self._model,
                    self._network,
                    t_end=t_end,
                    n_steps=n_steps,
                    poplevel=psa_poplevel,
                    t_start=t_start,
                )
            else:
                raise AssertionError("validated method dispatch is incomplete")

        return SimResult(raw)

    def execute(self, verbose: bool = False) -> None:
        """Execute all actions defined in the model's action block."""
        source = self._source_path or "."
        _cpp.execute(self._model, source, verbose=verbose)

    def write_xml(self, path: str) -> None:
        _cpp.io.write_xml(self._model, path)

    def to_xml(self) -> str:
        """Serialize the model to an in-memory BNG-XML string."""
        return _cpp.io.write_xml_string(self._model)

    def write_bngl(self, path: str) -> None:
        _cpp.io.write_bngl(self._model, path)

    def to_bngl(self) -> str:
        """Serialize the model to an in-memory BNGL string."""
        return _cpp.io.write_bngl_string(self._model)

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

    def _repr_html_(self) -> str:
        from bionetgen.display import render_model_html

        return render_model_html(self)


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
