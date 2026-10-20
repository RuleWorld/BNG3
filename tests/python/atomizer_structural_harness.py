"""Reusable measurement harness for SBML structural atomization.

The harness keeps four metrics apart, because they answer different
questions and must not be conflated:

``translation``
    did the SBML source translate to BNGL at all?
``equivalence``
    do the flat and the atomized translations implement the same
    mathematics?  The gate is the same number of generated species, the
    same number of generated reactions, and identical deterministic
    trajectories on a fixed grid.
``structural``
    how many species received a molecular interpretation, and how confident
    was that interpretation?
``ground_truth``
    does the inferred structure match a synthetic model whose molecular
    structure is known by construction?

Only the last metric is an independent correctness claim about the inferred
structure.  For real-world models no such oracle exists, so the structural
metric is reported as a coverage count, never as proof of correctness.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bionetgen.atomizer.modern import Atomizer

__all__ = [
    "GROUND_TRUTH_MODELS",
    "GroundTruthModel",
    "build_sbml",
    "compare_flat_and_atomized",
    "structural_metrics",
    "reaction_rule_count",
]


# ---------------------------------------------------------------------------
# Synthetic SBML construction
# ---------------------------------------------------------------------------


def _species_xml(
    species_id: str,
    name: str,
    amount: float,
    sbo_term: Optional[str] = None,
) -> str:
    attributes = [
        f'id="{species_id}"',
        f'name="{name}"',
        'compartment="c"',
        f'initialAmount="{amount}"',
        'hasOnlySubstanceUnits="true"',
        'constant="false"',
    ]
    if sbo_term:
        attributes.append(f'sboTerm="{sbo_term}"')
    return f"      <species {' '.join(attributes)}/>"


def _reaction_xml(
    reaction_id: str,
    reactants: Sequence[str],
    products: Sequence[str],
    rate: str,
    rate_factors: Sequence[str] = (),
    stoichiometries: Optional[Dict[str, int]] = None,
) -> str:
    stoichiometries = stoichiometries or {}

    def reference(species: str) -> str:
        value = stoichiometries.get(species)
        if value is None or value == 1:
            return f'          <speciesReference species="{species}"/>'
        return (
            f'          <speciesReference species="{species}" '
            f'stoichiometry="{value}"/>'
        )

    reactant_xml = "\n".join(reference(species) for species in reactants)
    product_xml = "\n".join(reference(species) for species in products)
    factor_xml = "".join(f"<ci>{factor}</ci>" for factor in rate_factors)
    return f"""      <reaction id="{reaction_id}" reversible="false">
        <listOfReactants>
{reactant_xml}
        </listOfReactants>
        <listOfProducts>
{product_xml}
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>{rate}</ci>{factor_xml}</apply>
          </math>
        </kineticLaw>
      </reaction>"""


def build_sbml(
    model_id: str,
    species: Sequence[Tuple[str, str, float, Optional[str]]],
    reactions: Sequence[str],
    parameters: Sequence[Tuple[str, float]] = (),
) -> str:
    """Build a small SBML Level 3 document from plain data."""

    species_xml = "\n".join(
        _species_xml(species_id, name, amount, sbo_term)
        for species_id, name, amount, sbo_term in species
    )
    parameter_xml = "\n".join(
        f'      <parameter id="{parameter_id}" value="{value}" constant="true"/>'
        for parameter_id, value in parameters
    )
    reaction_xml = "\n".join(reactions)
    parameter_block = (
        f"""    <listOfParameters>
{parameter_xml}
    </listOfParameters>
"""
        if parameter_xml
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="{model_id}" name="{model_id}">
    <listOfCompartments>
      <compartment id="c" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
{species_xml}
    </listOfSpecies>
{parameter_block}    <listOfReactions>
{reaction_xml}
    </listOfReactions>
  </model>
</sbml>
"""


# ---------------------------------------------------------------------------
# Ground-truth models
# ---------------------------------------------------------------------------


class GroundTruthModel:
    """A synthetic model whose molecular structure is known by construction.

    ``expectations`` maps a species id onto the expected structural
    inference.  The expectation states what the SBML source determines:

    ``molecules``
        the molecules the species is composed of;
    ``modification_sites``
        the sites that carry a modification state;
    ``states``
        the active state of each modification site;
    ``bonded``
        whether the molecules of the species are bound to each other;
    ``binding_sites``
        the number of binding sites.  The *names* of the binding sites of an
        inferred complex are synthetic placeholders (``b1``, ``b2``, ...), so
        only their number is meaningful; sites that come from the source
        keep their source name and are listed in ``modification_sites`` or
        counted in ``binding_sites``;
    ``confidence``
        the confidence the inference is expected to carry.
    """

    def __init__(
        self,
        name: str,
        sbml: str,
        expectations: Dict[str, Dict[str, Any]],
        t_end: float = 5.0,
        n_steps: int = 11,
    ) -> None:
        self.name = name
        self.sbml = sbml
        self.expectations = expectations
        self.t_end = t_end
        self.n_steps = n_steps


def _complex_model() -> GroundTruthModel:
    sbml = build_sbml(
        "complex_model",
        [
            ("A", "A", 10.0, None),
            ("B", "B", 5.0, None),
            ("AB", "A.B", 0.0, None),
        ],
        [
            _reaction_xml("bind", ["A", "B"], ["AB"], "kon", ["A", "B"]),
        ],
        [("kon", 0.5)],
    )
    return GroundTruthModel(
        "complex",
        sbml,
        {
            "AB": {
                "molecules": ["A", "B"],
                "modification_sites": [],
                "states": {},
                "bonded": True,
                "binding_sites": 1,
                "confidence": "reaction-topology",
            }
        },
    )


def _phosphorylation_model() -> GroundTruthModel:
    sbml = build_sbml(
        "phosphorylation_model",
        [
            ("A", "A", 10.0, None),
            ("AP", "A-P", 0.0, "SBO:0000216"),
        ],
        [
            _reaction_xml("phos", ["A"], ["AP"], "kcat", ["A"]),
        ],
        [("kcat", 0.1)],
    )
    return GroundTruthModel(
        "phosphorylation",
        sbml,
        {
            "AP": {
                "molecules": ["A"],
                "modification_sites": ["phosphorylation"],
                "states": {"phosphorylation": "P"},
                "bonded": False,
                "binding_sites": 0,
                "confidence": "sbo-term",
            }
        },
    )


def _name_modification_model() -> GroundTruthModel:
    sbml = build_sbml(
        "name_modification_model",
        [
            ("A", "A", 10.0, None),
            ("AP", "A-P", 0.0, None),
        ],
        [
            _reaction_xml("phos", ["A"], ["AP"], "kcat", ["A"]),
        ],
        [("kcat", 0.1)],
    )
    return GroundTruthModel(
        "name-modification",
        sbml,
        {
            "AP": {
                "molecules": ["A"],
                "modification_sites": ["phosphorylation"],
                "states": {"phosphorylation": "P"},
                "bonded": False,
                "binding_sites": 0,
                "confidence": "name-heuristic",
            }
        },
    )


def _binding_site_model() -> GroundTruthModel:
    sbml = build_sbml(
        "binding_site_model",
        [
            ("A", "A(b1)", 10.0, None),
            ("B", "B(b1)", 5.0, None),
            ("AB", "A!B", 0.0, None),
        ],
        [
            _reaction_xml("bind", ["A", "B"], ["AB"], "kon", ["A", "B"]),
        ],
        [("kon", 0.5)],
    )
    return GroundTruthModel(
        "binding-site",
        sbml,
        {
            "A": {
                "molecules": ["A"],
                "modification_sites": [],
                "states": {},
                "bonded": False,
                "binding_sites": 1,
                "confidence": "explicit-pattern",
            }
        },
    )


def _unbinding_model() -> GroundTruthModel:
    """A complex whose name does not spell out its constituents."""

    sbml = build_sbml(
        "unbinding_model",
        [
            ("A", "A", 4.0, None),
            ("B", "B", 4.0, None),
            ("CPLX", "assembled entity", 2.0, None),
        ],
        [
            _reaction_xml("assemble", ["A", "B"], ["CPLX"], "kon", ["A", "B"]),
            _reaction_xml("disassemble", ["CPLX"], ["A", "B"], "koff", ["CPLX"]),
        ],
        [("kon", 0.4), ("koff", 0.2)],
    )
    return GroundTruthModel(
        "unbinding",
        sbml,
        {
            "CPLX": {
                "molecules": ["A", "B"],
                "modification_sites": [],
                "states": {},
                "bonded": True,
                "binding_sites": 1,
                "confidence": "reaction-topology",
            }
        },
    )


def _name_complex_model() -> GroundTruthModel:
    """A complex named after its constituents without a reaction."""

    sbml = build_sbml(
        "name_complex_model",
        [
            ("A", "A", 4.0, None),
            ("B", "B", 4.0, None),
            ("AB", "A-B", 2.0, None),
        ],
        [],
        [],
    )
    return GroundTruthModel(
        "name-complex",
        sbml,
        {
            "AB": {
                "molecules": ["A", "B"],
                "modification_sites": [],
                "states": {},
                "bonded": True,
                "binding_sites": 1,
                "confidence": "name-heuristic",
            }
        },
    )


def _mixed_model() -> GroundTruthModel:
    """A model that combines binding, phosphorylation and degradation."""

    sbml = build_sbml(
        "mixed_model",
        [
            ("A", "A", 10.0, None),
            ("B", "B", 6.0, None),
            ("AB", "A.B", 1.0, None),
            ("AP", "A-P", 0.0, "SBO:0000216"),
            ("APP", "A-PP", 0.0, None),
        ],
        [
            _reaction_xml("bind", ["A", "B"], ["AB"], "kon", ["A", "B"]),
            _reaction_xml("unbind", ["AB"], ["A", "B"], "koff", ["AB"]),
            _reaction_xml("phos", ["A"], ["AP"], "kcat", ["A"]),
            _reaction_xml("phos2", ["AP"], ["APP"], "kcat", ["AP"]),
            _reaction_xml("degrade", ["APP"], [], "kdeg", ["APP"]),
        ],
        [("kon", 0.5), ("koff", 0.2), ("kcat", 0.1), ("kdeg", 0.05)],
    )
    return GroundTruthModel(
        "mixed",
        sbml,
        {
            "AB": {
                "molecules": ["A", "B"],
                "modification_sites": ["phosphorylation"],
                "states": {"phosphorylation": "0"},
                "bonded": True,
                "binding_sites": 1,
                "confidence": "reaction-topology",
            },
            "AP": {
                "molecules": ["A"],
                "modification_sites": ["phosphorylation"],
                "states": {"phosphorylation": "P"},
                "bonded": False,
                "binding_sites": 1,
                "confidence": "sbo-term",
            },
            "APP": {
                "molecules": ["A"],
                "modification_sites": ["phosphorylation"],
                "states": {"phosphorylation": "PP"},
                "bonded": False,
                "binding_sites": 1,
                "confidence": "name-heuristic",
            },
        },
    )


GROUND_TRUTH_MODELS: Tuple[GroundTruthModel, ...] = (
    _complex_model(),
    _phosphorylation_model(),
    _name_modification_model(),
    _binding_site_model(),
    _unbinding_model(),
    _name_complex_model(),
    _mixed_model(),
)


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------


def reaction_rule_count(bngl: str) -> int:
    """Count the reaction rules in a generated BNGL document."""

    count = 0
    inside = False
    for line in bngl.splitlines():
        stripped = line.strip()
        if stripped.startswith("begin reaction rules"):
            inside = True
            continue
        if stripped.startswith("end reaction rules"):
            inside = False
            continue
        if inside and stripped and not stripped.startswith("#"):
            count += 1
    return count


def _translate(sbml: str, atomize: bool) -> Any:
    return Atomizer({"atomize": atomize, "quiet_mode": True}).atomize(sbml)


def _network(bngl: str) -> Any:
    import bionetgen._bionetgen_cpp as cpp

    model = cpp.parse_string(bngl)
    return cpp.generate_network(model, max_iter=100)


def _trajectories(bngl: str, t_end: float, n_steps: int) -> Dict[str, List[float]]:
    from bionetgen.model import BioNetGenModel
    import bionetgen._bionetgen_cpp as cpp

    model = BioNetGenModel(cpp.parse_string(bngl))
    result = model.simulate(method="ode", t_end=t_end, n_steps=n_steps)
    return {
        name: [float(value) for value in values]
        for name, values in result.observables.items()
    }


def compare_flat_and_atomized(
    sbml: str,
    t_end: float = 5.0,
    n_steps: int = 11,
    tolerance: float = 1e-8,
) -> Dict[str, Any]:
    """Compare the flat and the atomized translation of one SBML model.

    The comparison is the mathematical-equivalence gate: the atomized
    translation must produce the same number of species and reactions and
    the same deterministic trajectories as the flat translation.
    """

    flat = _translate(sbml, atomize=False)
    atomized = _translate(sbml, atomize=True)
    report: Dict[str, Any] = {
        "flat_success": flat.success,
        "atomized_success": atomized.success,
        "flat_error": flat.error,
        "atomized_error": atomized.error,
        "equivalent": False,
        "problems": [],
    }
    if not flat.success or not atomized.success:
        report["problems"].append("one of the two translations failed")
        return report

    flat_network = _network(flat.bngl)
    atomized_network = _network(atomized.bngl)
    report["flat_species"] = flat_network.num_species
    report["atomized_species"] = atomized_network.num_species
    report["flat_reactions"] = flat_network.num_reactions
    report["atomized_reactions"] = atomized_network.num_reactions
    report["flat_rules"] = reaction_rule_count(flat.bngl)
    report["atomized_rules"] = reaction_rule_count(atomized.bngl)

    if flat_network.num_species != atomized_network.num_species:
        report["problems"].append(
            f"generated species count differs: "
            f"{flat_network.num_species} vs {atomized_network.num_species}"
        )
    if flat_network.num_reactions != atomized_network.num_reactions:
        report["problems"].append(
            f"generated reaction count differs: "
            f"{flat_network.num_reactions} vs {atomized_network.num_reactions}"
        )
    if report["flat_rules"] != report["atomized_rules"]:
        report["problems"].append(
            f"reaction rule count differs: "
            f"{report['flat_rules']} vs {report['atomized_rules']}"
        )

    flat_trajectories = _trajectories(flat.bngl, t_end, n_steps)
    atomized_trajectories = _trajectories(atomized.bngl, t_end, n_steps)
    if sorted(flat_trajectories) != sorted(atomized_trajectories):
        report["problems"].append("the observable sets differ")
    else:
        worst = 0.0
        for name, values in flat_trajectories.items():
            other = atomized_trajectories[name]
            for left, right in zip(values, other):
                worst = max(worst, abs(left - right))
        report["max_trajectory_difference"] = worst
        if worst > tolerance:
            report["problems"].append(
                f"trajectories differ by {worst:g} (tolerance {tolerance:g})"
            )
    report["equivalent"] = not report["problems"]
    return report


def structural_metrics(sbml: str) -> Dict[str, Any]:
    """Return the structural atomization metrics of one SBML model."""

    result = _translate(sbml, atomize=True)
    report = result.structural_inference or {}
    summary = dict(report.get("summary") or {})
    total = int(summary.get("species_total", 0) or 0)
    structural = int(summary.get("structural_species", 0) or 0)
    return {
        "translated": bool(result.success),
        "error": result.error,
        "species_total": total,
        "structural_species": structural,
        "elemental_species": int(summary.get("elemental_species", 0) or 0),
        "structural_fraction": (structural / total) if total else 0.0,
        "confidence": dict(summary.get("confidence") or {}),
        "uncertain_species": list(summary.get("uncertain_species") or []),
        "species": report.get("species") or {},
    }


def _number(text: str) -> Optional[float]:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None
