"""Type stubs for the _bionetgen_cpp C++ extension module."""

from typing import Dict, List, Optional

class ParseError(Exception):
    """Raised when BNGL parsing fails."""

    ...

# ─── AST Types ────────────────────────────────────────────────────────────────

class Expression:
    """A mathematical expression in the model (parameter value, rate law, etc.)."""

    def __str__(self) -> str: ...
    def to_string(self) -> str: ...

class Parameter:
    """A model parameter with a name and expression/value."""

    @property
    def name(self) -> str: ...
    @property
    def expression(self) -> Expression: ...
    @property
    def value(self) -> Optional[float]: ...
    @value.setter
    def value(self, v: float) -> None: ...
    def __repr__(self) -> str: ...

class ParameterList:
    """Dict-like container of Parameters."""

    def __len__(self) -> int: ...
    def __contains__(self, name: str) -> bool: ...
    def __getitem__(self, name: str) -> Parameter: ...
    def all(self) -> List[Parameter]: ...
    def evaluate_all(self, t: float = 0.0) -> None: ...

class ComponentType:
    """A component type definition within a MoleculeType."""

    name: str
    allowed_states: List[str]

class MoleculeType:
    """A molecule type definition."""

    @property
    def name(self) -> str: ...
    @property
    def components(self) -> List[ComponentType]: ...
    @property
    def is_population(self) -> bool: ...
    def __repr__(self) -> str: ...

class Observable:
    """An observable definition (monitors species matching patterns)."""

    @property
    def name(self) -> str: ...
    @property
    def type(self) -> str: ...
    @property
    def patterns(self) -> List[str]: ...
    def __repr__(self) -> str: ...

class SeedSpecies:
    """A seed species (initial condition)."""

    @property
    def pattern(self) -> str: ...
    @property
    def amount(self) -> Expression: ...
    @property
    def is_constant(self) -> bool: ...
    @property
    def compartment(self) -> str: ...
    def __repr__(self) -> str: ...

class ReactionRule:
    """A reaction rule definition."""

    @property
    def label(self) -> str: ...
    @property
    def is_bidirectional(self) -> bool: ...
    @property
    def reactant_patterns(self) -> List[str]: ...
    @property
    def product_patterns(self) -> List[str]: ...
    @property
    def rates(self) -> List[str]: ...
    @property
    def modifiers(self) -> List[str]: ...
    def __repr__(self) -> str: ...

class Function:
    """A user-defined function."""

    @property
    def name(self) -> str: ...
    @property
    def args(self) -> List[str]: ...
    @property
    def expression(self) -> Expression: ...
    def __repr__(self) -> str: ...

class Compartment:
    """A compartment definition."""

    @property
    def name(self) -> str: ...
    @property
    def dimension(self) -> int: ...
    def __repr__(self) -> str: ...

class Action:
    """An action from the actions block."""

    name: str
    arguments: Dict[str, str]
    def __repr__(self) -> str: ...

class Model:
    """The C++ AST model object. Created by parse_file() or parse_string()."""

    @property
    def parameters(self) -> List[Parameter]: ...
    @property
    def parameter_list(self) -> ParameterList: ...
    @property
    def molecule_types(self) -> List[MoleculeType]: ...
    @property
    def seed_species(self) -> List[SeedSpecies]: ...
    @property
    def observables(self) -> List[Observable]: ...
    @property
    def reaction_rules(self) -> List[ReactionRule]: ...
    @property
    def functions(self) -> List[Function]: ...
    @property
    def compartments(self) -> List[Compartment]: ...
    @property
    def actions(self) -> List[Action]: ...
    @property
    def model_name(self) -> str: ...
    @property
    def version(self) -> str: ...
    def set_parameter(self, name: str, value: float) -> None: ...
    def get_parameter(self, name: str) -> Parameter: ...
    def __repr__(self) -> str: ...

# ─── Engine Types ─────────────────────────────────────────────────────────────

class GeneratedNetwork:
    """A generated reaction network (species + reactions)."""

    @property
    def num_species(self) -> int: ...
    @property
    def num_reactions(self) -> int: ...
    @property
    def species_names(self) -> List[str]: ...
    @property
    def reaction_strings(self) -> List[str]: ...
    def __repr__(self) -> str: ...

class OdeOptions:
    """Configuration options for ODE/SSA integration."""

    t_start: float
    t_end: float
    n_steps: int
    rtol: float
    atol: float
    method: str
    max_step: float
    steady_state: bool
    steady_state_tol: float
    stop_if: str
    sample_times: List[float]
    max_sim_steps: int
    output_step_interval: int
    sparse: bool
    check_product_scale: float
    def __init__(self) -> None: ...

# ─── Result Type ──────────────────────────────────────────────────────────────

class SimResultDict:
    """TypedDict-like result from simulation functions.

    Keys:
        time: numpy array of time points
        observables: dict mapping observable name to numpy array
        concentrations: numpy array of shape (n_steps, n_species) [ODE/SSA only]
    """

    ...

# ─── Top-level Functions ──────────────────────────────────────────────────────

def parse_file(path: str) -> Model:
    """Parse a BNGL file and return a Model object.

    Parameters
    ----------
    path : str
        Path to the .bngl file.

    Returns
    -------
    Model
        The parsed model.

    Raises
    ------
    ParseError
        If the file cannot be opened or has syntax errors.
    """
    ...

def parse_string(text: str) -> Model:
    """Parse a BNGL string and return a Model object.

    Parameters
    ----------
    text : str
        BNGL model text.

    Returns
    -------
    Model
        The parsed model.

    Raises
    ------
    ParseError
        If the text has syntax errors.
    """
    ...

def generate_network(model: Model, max_iter: int = 100) -> GeneratedNetwork:
    """Generate the reaction network from a model.

    Iteratively applies reaction rules to seed species until no new species
    are generated or max_iter is reached.

    Parameters
    ----------
    model : Model
        The parsed model.
    max_iter : int
        Maximum number of rule-application iterations.

    Returns
    -------
    GeneratedNetwork
        The generated species and reactions.
    """
    ...

def simulate_ode(
    model: Model,
    network: GeneratedNetwork,
    t_end: float = 100.0,
    n_steps: int = 100,
    t_start: float = 0.0,
    rtol: float = 1e-8,
    atol: float = 1e-8,
    method: str = "cvode",
    max_step: float = 0.0,
    steady_state: bool = False,
    steady_state_tol: float = 1e-8,
    stop_if: str = "",
    sample_times: List[float] = [],
    max_sim_steps: int = 0,
    output_step_interval: int = 0,
    sparse: bool = False,
    check_product_scale: float = 0.0,
) -> Dict[str, object]:
    """Run ODE simulation on a generated network.

    Parameters
    ----------
    model : Model
        The parsed model (provides parameters and observables).
    network : GeneratedNetwork
        The generated reaction network.
    t_end : float
        End time for simulation.
    n_steps : int
        Number of output time steps.
    t_start : float
        Start time.
    rtol : float
        Relative tolerance.
    atol : float
        Absolute tolerance.
    method : str
        Integration method: "cvode", "euler", or "rk4".
    max_step : float
        Maximum internal CVODE step size; zero disables the limit.
    steady_state : bool
        Stop when the derivative norm is below ``steady_state_tol``.
    steady_state_tol : float
        Derivative threshold for steady-state stopping.
    stop_if : str
        Expression evaluated at output points; nonzero stops the run.
    sample_times : list[float]
        Strictly increasing output times between ``t_start`` and ``t_end``.
    max_sim_steps : int
        Stochastic-only option; must be zero for ``simulate_ode``.
    output_step_interval : int
        Stochastic-only option; must be zero for ``simulate_ode``.
    sparse : bool
        Request the sparse CVODE linear solver.
    check_product_scale : float
        Warn when a species exceeds this threshold.

    Returns
    -------
    dict
        Keys: "time" (ndarray), "observables" (dict[str, ndarray]),
        "concentrations" (ndarray of shape n_steps+1 × n_species).
    """
    ...

def simulate_ssa(
    model: Model,
    network: GeneratedNetwork,
    t_end: float = 100.0,
    n_steps: int = 100,
    t_start: float = 0.0,
    seed: int = 0,
    stop_if: str = "",
    sample_times: List[float] = [],
    max_sim_steps: int = 0,
    output_step_interval: int = 0,
) -> Dict[str, object]:
    """Run SSA (stochastic) simulation on a generated network.

    Parameters
    ----------
    model : Model
        The parsed model.
    network : GeneratedNetwork
        The generated reaction network.
    t_end : float
        End time.
    n_steps : int
        Number of output time steps.
    t_start : float
        Start time.
    seed : int
        Random seed (0 = system default).
    stop_if : str
        Expression evaluated after each reaction; nonzero stops the run.
    sample_times : list[float], optional
        Strictly increasing output times between ``t_start`` and ``t_end``.
    max_sim_steps : int
        Maximum number of reaction events (0 = unlimited).
    output_step_interval : int
        Output every N reaction events when ``sample_times`` is not set.

    Returns
    -------
    dict
        Keys: "time" (ndarray), "observables" (dict[str, ndarray]),
        "concentrations" (ndarray).
    """
    ...

def simulate_pla(
    model: Model,
    network: GeneratedNetwork,
    t_end: float = 100.0,
    n_steps: int = 100,
    config_str: str = "",
    t_start: float = 0.0,
) -> Dict[str, object]:
    """Run PLA simulation on a generated network.

    Parameters
    ----------
    model : Model
        The parsed model.
    network : GeneratedNetwork
        The generated reaction network.
    t_end : float
        End time.
    n_steps : int
        Number of output time steps.
    config_str : str
        PLA configuration string.
    t_start : float
        Start time.

    Returns
    -------
    dict
        Keys: "time" (ndarray), "observables" (dict[str, ndarray]),
        "concentrations" (ndarray).
    """
    ...

def simulate_psa(
    model: Model,
    network: GeneratedNetwork,
    t_end: float = 100.0,
    n_steps: int = 100,
    poplevel: float = 100,
    t_start: float = 0.0,
) -> Dict[str, object]:
    """Run PSA simulation on a generated network.

    Parameters
    ----------
    model : Model
        The parsed model.
    network : GeneratedNetwork
        The generated reaction network.
    t_end : float
        End time.
    n_steps : int
        Number of output time steps.
    poplevel : float
        Population level threshold for PSA.
    t_start : float
        Start time.

    Returns
    -------
    dict
        Keys: "time" (ndarray), "observables" (dict[str, ndarray]),
        "concentrations" (ndarray).
    """
    ...

def simulate_nf(
    model: Model,
    t_end: float = 100.0,
    n_steps: int = 100,
    seed: int = 0,
    equilibrate: float = 0.0,
    verbose: bool = False,
    source_path: str = "",
    sample_times: List[float] = [],
) -> Dict[str, object]:
    """Run network-free (NFSim) simulation on a model.

    The model is serialized to XML and passed to the NFSim engine
    for stochastic simulation without network enumeration.

    Parameters
    ----------
    model : Model
        The parsed model.
    t_end : float
        End time.
    n_steps : int
        Number of output time steps.
    seed : int
        Random seed (0 = system default).
    equilibrate : float
        Equilibration time before simulation (0 = none).
    verbose : bool
        Print progress information.
    source_path : str
        Path to the source BNGL file for resolving relative TFUN tables.
    sample_times : list[float]
        Strictly increasing output times between zero and ``t_end``.  If the
        final time is omitted, ``t_end`` is appended.

    Returns
    -------
    dict
        Keys: "time" (ndarray), "observables" (dict[str, ndarray]), and
        "construction_path" ("direct", "in-memory-xml", or "on-disk-xml").
    """
    ...

def execute(model: Model, source_path: str, verbose: bool = False) -> None:
    """Execute all actions defined in the model's action block.

    Parameters
    ----------
    model : Model
        The parsed model containing actions.
    source_path : str
        Path to the source .bngl file (used for relative output paths).
    verbose : bool
        Print progress information.
    """
    ...

# ─── IO Submodule ─────────────────────────────────────────────────────────────

class io:
    """I/O writers for various output formats."""

    @staticmethod
    def write_xml(model: Model, path: str) -> None:
        """Write model to BioNetGen XML format."""
        ...

    @staticmethod
    def write_xml_string(model: Model) -> str:
        """Serialize model to BioNetGen XML string."""
        ...

    @staticmethod
    def write_net(model: Model, network: GeneratedNetwork, path: str) -> None:
        """Write generated network to .net format."""
        ...

    @staticmethod
    def write_bngl(model: Model, path: str) -> None:
        """Write model back to BNGL format."""
        ...

    @staticmethod
    def write_bngl_string(model: Model) -> str:
        """Serialize model to BNGL string."""
        ...

    @staticmethod
    def write_sbml(model: Model, network: GeneratedNetwork, path: str) -> None:
        """Write model to SBML format."""
        ...

    @staticmethod
    def write_matlab(model: Model, network: GeneratedNetwork, path: str) -> None:
        """Write model to MATLAB format."""
        ...

    @staticmethod
    def write_latex(model: Model, network: GeneratedNetwork, path: str) -> None:
        """Write model to LaTeX format."""
        ...

    @staticmethod
    def write_mex_string(
        model: Model,
        network: GeneratedNetwork,
        t_start: float = 0.0,
        t_end: float = 10.0,
        n_steps: int = 20,
        atol: float = 1e-6,
        rtol: float = 1e-8,
        max_num_steps: int = 2000,
        max_step: float = 0.0,
        sparse: bool = False,
    ) -> str:
        """Serialize a generated MEX ODE implementation."""
        ...

class viz:
    """Visualization graph writers exposed through the C++ extension."""

    @staticmethod
    def write_contact_map(model: Model, path: Optional[str] = None) -> str:
        """Write a contact map graph and return the serialized content."""
        ...

    @staticmethod
    def write_regulatory_graph(model: Model, path: Optional[str] = None) -> str:
        """Write a regulatory graph and return the serialized content."""
        ...

    @staticmethod
    def write_rule_influence_graph(model: Model, path: Optional[str] = None) -> str:
        """Write a rule influence graph and return the serialized content."""
        ...

    @staticmethod
    def write_reaction_network_graph(model: Model, path: Optional[str] = None) -> str:
        """Write a reaction network graph and return the serialized content."""
        ...

    @staticmethod
    def write_ruleviz_pattern(model: Model, path: Optional[str] = None) -> str:
        """Write a ruleviz pattern graph and return the serialized content."""
        ...

    @staticmethod
    def write_ruleviz_operation(model: Model, path: Optional[str] = None) -> str:
        """Write a ruleviz operation graph and return the serialized content."""
        ...

    @staticmethod
    def write_process_graph(model: Model, path: Optional[str] = None) -> str:
        """Write a process graph and return the serialized content."""
        ...

    @staticmethod
    def write_sbml_multi(model: Model, path: Optional[str] = None) -> str:
        """Write an SBML Multi document and return the serialized content."""
        ...
