"""Data contracts for the Playground-derived Python atomizer."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple, Union

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
    compartment_type: Optional[str] = None
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
    # ``None`` represents an unavailable raw-SBML presence flag.  This mirrors
    # the Playground contract, where an absent flag falls back to a non-zero
    # parsed value while an explicit false remains authoritative.
    initial_amount_set: Optional[bool] = None
    initial_concentration_set: Optional[bool] = None
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


@dataclass
class SBMLModifierSpeciesReference:
    species: str


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
    modifiers: List[Union[str, SBMLModifierSpeciesReference]] = field(
        default_factory=list
    )
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
class SBMLImportWarning(MappingABC[str, Any]):
    """Structured import diagnostic matching the Playground record contract.

    The mapping view preserves BNG3's existing ``warning["category"]`` and
    ``warning.get(...)`` callers while exposing the source-shaped attributes.
    """

    category: str
    message: str
    count: int
    severity: str

    _FIELDS = ("category", "message", "count", "severity")

    def __getitem__(self, key: str) -> Any:
        if key not in self._FIELDS:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._FIELDS)

    def __len__(self) -> int:
        return len(self._FIELDS)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


def coerce_import_warning(warning: Any) -> SBMLImportWarning:
    """Convert legacy dictionary diagnostics to source-shaped records."""

    if isinstance(warning, SBMLImportWarning):
        return warning
    if isinstance(warning, Mapping):
        try:
            count = int(warning.get("count", 1))
        except (TypeError, ValueError):
            count = 1
        return SBMLImportWarning(
            category=str(warning.get("category", "import")),
            message=str(warning.get("message", "")),
            count=count,
            severity=str(warning.get("severity", "info")),
        )
    return SBMLImportWarning(
        category="import", message=str(warning), count=1, severity="info"
    )


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
    version: Optional[int] = None
    substance_units: str = ""
    time_units: str = ""
    volume_units: str = ""
    area_units: str = ""
    length_units: str = ""
    extent_units: str = ""
    conversion_factor: Optional[str] = None
    constraint_count: int = 0
    multi_molecule_types: List[str] = field(default_factory=list)
    multi_complex_patterns: List[str] = field(default_factory=list)
    multi_seed_patterns: List[str] = field(default_factory=list)
    import_warnings: List[Union[Dict[str, Any], SBMLImportWarning]] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        self.import_warnings = [
            coerce_import_warning(warning) for warning in self.import_warnings
        ]


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


def _alias_property(target: str) -> property:
    """Create a writable camel-case view over a snake_case data field."""

    return property(
        lambda instance: getattr(instance, target),
        lambda instance, value: setattr(instance, target, value),
    )


# Preserve the public field spellings from the TypeScript config contracts
# alongside BNG3's snake_case Python data model.
AnnotationInfo.qualifierType = _alias_property("qualifier_type")
AnnotationInfo.biologicalQualifier = _alias_property("biological_qualifier")
AnnotationInfo.modelQualifier = _alias_property("model_qualifier")

SBMLCompartment.spatialDimensions = _alias_property("spatial_dimensions")
SBMLCompartment.sizeSet = _alias_property("size_set")

SBMLSpecies.initialConcentration = _alias_property("initial_concentration")
SBMLSpecies.initialAmount = _alias_property("initial_amount")
SBMLSpecies.substanceUnits = _alias_property("substance_units")
SBMLSpecies.hasOnlySubstanceUnits = _alias_property("has_only_substance_units")
SBMLSpecies.boundaryCondition = _alias_property("boundary_condition")
SBMLSpecies.initialAmountSet = _alias_property("initial_amount_set")
SBMLSpecies.initialConcentrationSet = _alias_property("initial_concentration_set")
SBMLSpecies.sboTerm = _alias_property("sbo_term")
SBMLSpecies.conversionFactor = _alias_property("conversion_factor")
SBMLSpecies.speciesType = _alias_property("species_type")

SBMLSpeciesReference.stoichiometrySet = _alias_property("stoichiometry_set")
SBMLSpeciesReference.variableStoichiometry = _alias_property("variable_stoichiometry")

SBMLKineticLaw.mathML = _alias_property("math_ml")
SBMLKineticLaw.localParameters = _alias_property("local_parameters")

SBMLReaction.kineticLaw = _alias_property("kinetic_law")
SBMLReaction.conversionFactor = _alias_property("conversion_factor")

SBMLEvent.useValuesFromTriggerTime = _alias_property("use_values_from_trigger_time")
SBMLEvent.triggerInitialValue = _alias_property("trigger_initial_value")
SBMLEvent.triggerPersistent = _alias_property("trigger_persistent")

SBMLModel.functionDefinitions = _alias_property("function_definitions")
SBMLModel.speciesByCompartment = _alias_property("species_by_compartment")
SBMLModel.substanceUnits = _alias_property("substance_units")
SBMLModel.timeUnits = _alias_property("time_units")
SBMLModel.volumeUnits = _alias_property("volume_units")
SBMLModel.areaUnits = _alias_property("area_units")
SBMLModel.lengthUnits = _alias_property("length_units")
SBMLModel.extentUnits = _alias_property("extent_units")
SBMLModel.conversionFactor = _alias_property("conversion_factor")
SBMLModel.constraintCount = _alias_property("constraint_count")
SBMLModel.multiMoleculeTypes = _alias_property("multi_molecule_types")
SBMLModel.multiComplexPatterns = _alias_property("multi_complex_patterns")
SBMLModel.multiSeedPatterns = _alias_property("multi_seed_patterns")
SBMLModel.importWarnings = _alias_property("import_warnings")

SCTEntry.sbmlId = _alias_property("sbml_id")
SCTEntry.isElemental = _alias_property("is_elemental")
SpeciesCompositionTable.reverseDependencies = _alias_property("reverse_dependencies")
SpeciesCompositionTable.sortedSpecies = _alias_property("sorted_species")
SeedSpeciesEntry.sbmlId = _alias_property("sbml_id")
AtomizerResult.observableMap = _alias_property("observable_map")


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


_SBML_TO_BNGL_TRANSLATION = {
    "^": "",
    "'": "",
    "*": "m",
    " ": "_",
    "#": "sh",
    ":": "_",
    "\u03b1": "a",
    "\u03b2": "b",
    "\u03b3": "g",
    "\u03b4": "d",
    "\u03b5": "e",
    "\u03b6": "z",
    "\u03b7": "h",
    "\u03b8": "th",
    "\u03b9": "i",
    "\u03ba": "k",
    "\u03bb": "l",
    "\u03bc": "u",
    "\u03bd": "n",
    "\u03be": "x",
    "\u03bf": "o",
    "\u03c0": "pi",
    "\u03c1": "r",
    "\u03c2": "s",
    "\u03c3": "s",
    "\u03c4": "t",
    "\u03c5": "u",
    "\u03c6": "ph",
    "\u03c7": "ch",
    "\u03c8": "ps",
    "\u03c9": "o",
    "\u0391": "A",
    "\u0392": "B",
    "\u0393": "G",
    "\u0394": "D",
    "\u0395": "E",
    "+": "pl",
    "/": "_",
    "-": "_",
    ".": "_",
    "?": "unkn",
    ",": "_",
    "(": "",
    ")": "",
    "[": "",
    "]": "",
    ">": "_",
    "<": "_",
    "&": "and",
    "|": "or",
    "=": "eq",
    "%": "pct",
    "@": "at",
    "!": "",
    "~": "",
    "`": "",
    '"': "",
    "\\": "_",
}

# Keep this synchronized with the generated BNGL lexer.  Exact keyword
# collisions are lexical errors, even when the spelling is otherwise a valid
# identifier (for example, an SBML species named ``time``).
BNGL_LEXER_KEYWORDS = frozenset(
    {
        "_e",
        "_pi",
        "abs",
        "acos",
        "acosh",
        "actions",
        "addConcentration",
        "argfile",
        "Arrhenius",
        "asin",
        "asinh",
        "atan",
        "atanh",
        "atol",
        "atomize",
        "avg",
        "background",
        "bdf",
        "begin",
        "bifurcate",
        "binary_output",
        "blocks",
        "check_iso",
        "collapse",
        "compartments",
        "complex",
        "continue",
        "cos",
        "cosh",
        "Counter",
        "DeleteMolecules",
        "end",
        "energy",
        "equil",
        "evaluate_expressions",
        "exclude_products",
        "exclude_reactants",
        "execute",
        "exp",
        "false",
        "file",
        "format",
        "FunctionProduct",
        "functions",
        "generate_hybrid_model",
        "get_final_state",
        "gml",
        "groups",
        "Hill",
        "if",
        "include_model",
        "include_network",
        "include_products",
        "include_reactants",
        "ln",
        "log_scale",
        "log10",
        "log2",
        "max",
        "max_agg",
        "max_conv_fails",
        "max_err_test_fails",
        "max_iter",
        "max_num_steps",
        "max_sim_steps",
        "max_step",
        "max_stoich",
        "maxOrder",
        "method",
        "min",
        "MM",
        "model",
        "molecular",
        "molecule_types",
        "molecules",
        "MoveConnected",
        "mratio",
        "n_output_steps",
        "n_scan_pts",
        "netfile",
        "nf",
        "nocslf",
        "notf",
        "observables",
        "ode",
        "opts",
        "output_step_interval",
        "overwrite",
        "par_max",
        "par_min",
        "param",
        "parameter",
        "parameter_scan",
        "parameters",
        "patterns",
        "pla",
        "pla_config",
        "pla_output",
        "population",
        "prefix",
        "pretty_formatting",
        "print_CDAT",
        "print_end",
        "print_functions",
        "print_iter",
        "print_net",
        "print_on_stop",
        "priority",
        "quit",
        "reaction",
        "reaction_rules",
        "readFile",
        "reset_conc",
        "resetConcentrations",
        "resetParameters",
        "rint",
        "rtol",
        "rules",
        "safe",
        "sample_times",
        "Sat",
        "save_progress",
        "saveConcentrations",
        "saveParameters",
        "seed",
        "setConcentration",
        "setModelName",
        "setOption",
        "setParameter",
        "setVolume",
        "simulate",
        "simulate_nf",
        "simulate_ode",
        "simulate_pla",
        "simulate_psa",
        "simulate_rm",
        "sin",
        "sinh",
        "skip_actions",
        "sparse",
        "species",
        "sqrt",
        "ssa",
        "stats",
        "steady_state",
        "stiff",
        "stop_if",
        "substanceUnits",
        "suffix",
        "sum",
        "t_end",
        "t_start",
        "tan",
        "tanh",
        "TextReaction",
        "TextSpecies",
        "TFUN",
        "time",
        "TotalRate",
        "true",
        "type",
        "types",
        "utl",
        "verbose",
        "version",
        "visualize",
        "writeFile",
        "writeLatex",
        "writeMDL",
        "writeMexfile",
        "writeMfile",
        "writeModel",
        "writeNetwork",
        "writeSBML",
        "writeSSC",
        "writeSSCcfg",
        "writeXML",
    }
)


def standardize_name(value: str) -> str:
    """Return a BNGL-safe identifier, matching Playground normalization."""

    import re

    result = str(value or "")
    for character, replacement in _SBML_TO_BNGL_TRANSLATION.items():
        result = result.replace(character, replacement)
    result = re.sub(r"[^A-Za-z0-9_]", "_", result)
    if not result:
        result = "unnamed"
    if result[0].isdigit():
        result = "_" + result
    if result in BNGL_LEXER_KEYWORDS:
        result += "_id"
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
    "BNGL_LEXER_KEYWORDS",
    "ReactionPattern",
    "SBMLEvent",
    "SBMLCompartment",
    "SBMLFunctionDefinition",
    "SBMLInitialAssignment",
    "SBMLImportWarning",
    "SBMLKineticLaw",
    "SBMLModel",
    "SBMLModifierSpeciesReference",
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
