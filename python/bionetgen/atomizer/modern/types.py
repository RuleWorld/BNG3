"""Data contracts for the Playground-derived Python atomizer."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .structures import Species


@dataclass
class AnnotationInfo:
    qualifier_type: int = -1
    biological_qualifier: Optional[int] = None
    model_qualifier: Optional[int] = None
    resources: List[str] = field(default_factory=list)


@dataclass
class SBMLCompartment:
    id: str
    name: str = ""
    spatial_dimensions: float = 3
    size: float = 1
    units: str = ""
    constant: bool = True
    outside: Optional[str] = None
    size_set: bool = False


@dataclass
class SBMLParameter:
    id: str
    name: str = ""
    value: float = 0
    units: str = ""
    constant: bool = True
    scope: str = "global"


@dataclass
class SBMLSpecies:
    id: str
    name: str = ""
    compartment: str = ""
    initial_concentration: float = 0
    initial_amount: float = 0
    substance_units: str = ""
    has_only_substance_units: bool = False
    boundary_condition: bool = False
    constant: bool = False
    annotations: List[AnnotationInfo] = field(default_factory=list)
    initial_amount_set: bool = False
    initial_concentration_set: bool = False
    sbo_term: Optional[str] = None
    conversion_factor: Optional[str] = None
    charge: Optional[float] = None
    species_type: Optional[str] = None


@dataclass
class SBMLSpeciesReference:
    species: str
    stoichiometry: float = 1
    constant: bool = True
    id: Optional[str] = None
    stoichiometry_set: bool = False
    variable_stoichiometry: bool = False


class SBMLKineticLaw(dict):
    """Mapping-compatible kinetic law with convenient attribute access."""

    def __init__(
        self,
        math: str = "",
        math_ml: str = "",
        local_parameters: Optional[List[SBMLParameter]] = None,
    ) -> None:
        super().__init__(
            math=math, mathML=math_ml, localParameters=local_parameters or []
        )
        self.math = math
        self.math_ml = math_ml
        self.local_parameters = local_parameters or []


@dataclass
class SBMLReaction:
    id: str
    name: str = ""
    reversible: bool = False
    fast: bool = False
    reactants: List[SBMLSpeciesReference] = field(default_factory=list)
    products: List[SBMLSpeciesReference] = field(default_factory=list)
    modifiers: List[str] = field(default_factory=list)
    kinetic_law: Optional[Any] = None
    compartment: Optional[str] = None
    conversion_factor: Optional[str] = None


@dataclass
class SBMLRule:
    type: str
    variable: Optional[str] = None
    math: str = ""


@dataclass
class SBMLFunctionDefinition:
    id: str
    name: str = ""
    math: str = ""
    arguments: List[str] = field(default_factory=list)


@dataclass
class SBMLEvent:
    id: str
    name: str = ""
    trigger: str = ""
    delay: Optional[str] = None
    use_values_from_trigger_time: bool = True
    assignments: List[Tuple[str, str]] = field(default_factory=list)
    trigger_initial_value: Optional[bool] = None
    trigger_persistent: Optional[bool] = None
    priority: Optional[str] = None


@dataclass
class SBMLInitialAssignment:
    symbol: str
    math: str


@dataclass
class SBMLModel:
    id: str
    name: str = ""
    compartments: Mapping[str, SBMLCompartment] = field(default_factory=OrderedDict)
    species: Mapping[str, SBMLSpecies] = field(default_factory=OrderedDict)
    parameters: Mapping[str, SBMLParameter] = field(default_factory=OrderedDict)
    reactions: Mapping[str, SBMLReaction] = field(default_factory=OrderedDict)
    rules: List[SBMLRule] = field(default_factory=list)
    function_definitions: Mapping[str, SBMLFunctionDefinition] = field(
        default_factory=OrderedDict
    )
    events: List[SBMLEvent] = field(default_factory=list)
    initial_assignments: List[SBMLInitialAssignment] = field(default_factory=list)
    species_by_compartment: Mapping[str, List[str]] = field(default_factory=OrderedDict)
    unit_definitions: Mapping[str, Any] = field(default_factory=OrderedDict)
    level: Optional[int] = None
    import_warnings: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ReactionPattern:
    type: str
    reactants: List[str]
    products: List[str]
    modifiers: List[str] = field(default_factory=list)
    catalyst: Optional[str] = None


@dataclass
class SCTEntry:
    structure: Species
    components: List[str]
    sbml_id: str
    is_elemental: bool
    modifications: Dict[str, str] = field(default_factory=dict)
    weight: int = 0
    bonds: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class SpeciesCompositionTable:
    entries: Mapping[str, SCTEntry] = field(default_factory=OrderedDict)
    dependencies: Mapping[str, set] = field(default_factory=OrderedDict)
    reverse_dependencies: Mapping[str, set] = field(default_factory=OrderedDict)
    sorted_species: List[str] = field(default_factory=list)
    weights: List[Tuple[str, int]] = field(default_factory=list)


@dataclass
class SeedSpeciesEntry:
    species: Species
    concentration: str
    compartment: str
    sbml_id: str


@dataclass
class AtomizerResult:
    bngl: str
    database: Any = None
    annotation: Any = None
    observable_map: Mapping[str, str] = field(default_factory=OrderedDict)
    log: List[str] = field(default_factory=list)
    success: bool = True
    error: Optional[str] = None


DEFAULT_NAMING_PATTERNS = {
    ("+ p",): "Phosphorylation",
    ("+ P",): "Phosphorylation",
    ("+ _", "+ p"): "Phosphorylation",
    ("+ _", "+ P"): "Phosphorylation",
    ("+ p", "+ p"): "Double-Phosphorylation",
    ("+ P", "+ P"): "Double-Phosphorylation",
    ("+ p", "+ p", "+ p"): "Triple-Phosphorylation",
    ("+ P", "+ P", "+ P"): "Triple-Phosphorylation",
    ("+ u", "+ b"): "Ubiquitination",
    ("+ U", "+ b"): "Ubiquitination",
    ("+ a", "+ c"): "Acetylation",
    ("+ A", "+ c"): "Acetylation",
    ("+ m", "+ e"): "Methylation",
    ("+ M", "+ e"): "Methylation",
    ("+ a",): "Activation",
    ("+ A",): "Activation",
    ("+ i",): "Inactivation",
    ("+ I",): "Inactivation",
    ("+ _",): "Binding",
}


def standardize_name(value: str) -> str:
    """Return a BNGL-safe identifier, matching Playground normalization."""

    import re

    result = re.sub(r"[^A-Za-z0-9_]", "_", str(value or ""))
    result = re.sub(r"_+", "_", result).strip("_")
    if not result:
        result = "unnamed"
    if result[0].isdigit():
        result = "_" + result
    return result


def get_kinetic_math(kinetic_law: Any) -> str:
    if kinetic_law is None:
        return ""
    if isinstance(kinetic_law, Mapping):
        return str(kinetic_law.get("math", ""))
    return str(getattr(kinetic_law, "math", ""))


__all__ = [
    "AnnotationInfo",
    "AtomizerResult",
    "ReactionPattern",
    "SBMLEvent",
    "SBMLCompartment",
    "SBMLFunctionDefinition",
    "SBMLInitialAssignment",
    "SBMLKineticLaw",
    "SBMLModel",
    "SBMLParameter",
    "SBMLReaction",
    "SBMLRule",
    "SBMLSpecies",
    "SBMLSpeciesReference",
    "SCTEntry",
    "SeedSpeciesEntry",
    "SpeciesCompositionTable",
    "DEFAULT_NAMING_PATTERNS",
    "get_kinetic_math",
    "standardize_name",
]
