"""Focused regression tests for the structural SBML atomization path.

The tests cover the widened structural trigger, the ``sboTerm``-driven
modification inference, the stoichiometry-aware reaction-topology complex
inference, the machine-readable structural inference record, and the
flat-versus-atomized mathematical equivalence on synthetic models whose
molecular structure is known by construction.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from atomizer_structural_harness import (  # noqa: E402
    GROUND_TRUTH_MODELS,
    build_sbml,
    compare_flat_and_atomized,
    reaction_rule_count,
    structural_metrics,
)

from bionetgen.atomizer.modern import (  # noqa: E402
    Atomizer,
    analyze_structural_topology,
    infer_modification,
    normalize_sbo_term,
    sbo_modification,
)
from bionetgen.atomizer.modern.core import (  # noqa: E402
    _explicit_pattern_structure,
    _name_complex_candidates,
)
from bionetgen.atomizer.modern.parser import SBMLParser  # noqa: E402
from bionetgen.atomizer.modern.structures import (  # noqa: E402
    read_from_string,
    read_from_string_with_diagnostics,
)


def _atomize(sbml: str, atomize: bool = True):
    return Atomizer({"atomize": atomize, "quiet_mode": True}).atomize(sbml)


def _inference(sbml: str, species_id: str) -> dict:
    result = _atomize(sbml)
    assert result.success, result.error
    report = result.structural_inference
    assert report is not None
    return report["species"][species_id]


# ---------------------------------------------------------------------------
# The widened structural trigger
# ---------------------------------------------------------------------------


def test_explicit_pattern_trigger_accepts_multi_molecule_names():
    structure, unparsed = _explicit_pattern_structure("A.B")

    assert [molecule.name for molecule in structure.molecules] == ["A", "B"]
    assert unparsed == []


def test_explicit_pattern_trigger_accepts_sites_without_bonds():
    structure, unparsed = _explicit_pattern_structure("A(b1)")

    assert structure is not None
    assert structure.get_molecule_names() == ["A"]
    assert [component.name for component in structure.molecules[0].components] == [
        "b1"
    ]
    assert unparsed == []


def test_explicit_pattern_trigger_rejects_plain_names():
    structure, _unparsed = _explicit_pattern_structure("Insulin receptor")

    assert structure is None


def test_explicit_pattern_trigger_reads_bonded_pattern():
    structure, _unparsed = _explicit_pattern_structure("A(b1!1).B(b1!1)")

    assert structure is not None
    assert structure.get_molecule_names() == ["A", "B"]
    assert structure.molecules[0].components[0].bonds == ["1"]


def test_pattern_parser_reports_unparsable_fragments():
    species, unparsed = read_from_string_with_diagnostics("A!B")

    assert species.get_molecule_names() == []
    assert unparsed == ["A!B"]


def test_pattern_parser_keeps_its_historical_behaviour():
    assert read_from_string("A!B").get_molecule_names() == []


def test_unparsable_name_fragment_produces_an_explicit_diagnostic():
    sbml = build_sbml(
        "fragment_model",
        [("X", "A(b1", 1.0, None)],
        [],
    )

    atomized = Atomizer({"atomize": True, "quiet_mode": True})
    result = atomized.atomize(sbml)

    assert result.success, result.error
    messages = [
        warning.message
        for warning in atomized.model.import_warnings
        if getattr(warning, "category", "") == "structure"
    ]
    assert any('name fragment "A(b1"' in message for message in messages)


def test_unparsable_name_fragment_does_not_block_the_translation():
    sbml = build_sbml(
        "fragment_model",
        [("X", "A(b1", 1.0, None)],
        [],
    )

    result = _atomize(sbml)

    assert result.success, result.error
    assert "M_X()" in result.bngl


# ---------------------------------------------------------------------------
# sboTerm-driven modification inference
# ---------------------------------------------------------------------------


def test_sbo_term_is_normalized_from_every_spelling():
    assert normalize_sbo_term("SBO:0000216") == "SBO:0000216"
    assert normalize_sbo_term("0000216") == "SBO:0000216"
    assert (
        normalize_sbo_term("http://identifiers.org/SBO:0000216") == "SBO:0000216"
    )
    assert normalize_sbo_term("") is None
    assert normalize_sbo_term(None) is None


def test_sbo_term_maps_to_the_named_modification():
    assert sbo_modification("SBO:0000216") == ("Phosphorylation", "additive")
    assert sbo_modification("SBO:0000224") == ("Ubiquitination", "additive")
    assert sbo_modification("SBO:0000330") == ("Dephosphorylation", "removal")
    assert sbo_modification("SBO:0000123") is None


def test_sbo_term_drives_the_modification_inference():
    sbml = build_sbml(
        "sbo_model",
        [
            ("A", "A", 10.0, None),
            ("AP", "A-P", 0.0, "SBO:0000216"),
        ],
        [_reaction("phos", ["A"], ["AP"], "kcat", ["A"])],
        [("kcat", 0.1)],
    )

    record = _inference(sbml, "AP")

    assert record["confidence"] == "sbo-term"
    assert record["molecules"] == ["A"]
    assert record["sites"] == ["phosphorylation"]
    assert record["states"] == {"phosphorylation": "P"}
    assert "SBO:0000216" in record["reason"]


def test_sbo_term_inference_survives_an_opaque_species_name():
    """The SBO term is the signal; the name need not spell the state."""

    sbml = build_sbml(
        "sbo_opaque_model",
        [
            ("A", "A", 10.0, None),
            ("AP", "activated kinase", 0.0, "SBO:0000216"),
        ],
        [_reaction("phos", ["A"], ["AP"], "kcat", ["A"])],
        [("kcat", 0.1)],
    )

    record = _inference(sbml, "AP")

    assert record["confidence"] == "sbo-term"
    assert record["states"] == {"phosphorylation": "P"}


def test_sbo_term_without_a_single_reactant_reaction_stays_elemental():
    sbml = build_sbml(
        "sbo_untopology_model",
        [
            ("A", "A", 10.0, None),
            ("B", "B", 4.0, None),
            ("AP", "A-P", 0.0, "SBO:0000216"),
        ],
        [_reaction("mix", ["A", "B"], ["AP"], "kon", ["A", "B"])],
        [("kon", 0.5)],
    )

    record = _inference(sbml, "AP")

    assert record["confidence"] == "reaction-topology"
    assert record["molecules"] == ["A", "B"]


# ---------------------------------------------------------------------------
# Reaction-topology complex inference
# ---------------------------------------------------------------------------


def test_reaction_topology_makes_a_complex():
    sbml = build_sbml(
        "topology_model",
        [
            ("A", "A", 10.0, None),
            ("B", "B", 5.0, None),
            ("AB", "assembled", 0.0, None),
        ],
        [_reaction("bind", ["A", "B"], ["AB"], "kon", ["A", "B"])],
        [("kon", 0.5)],
    )

    record = _inference(sbml, "AB")

    assert record["confidence"] == "reaction-topology"
    assert record["molecules"] == ["A", "B"]
    assert record["bonds"]


def test_reaction_topology_infers_a_complex_from_an_unbinding():
    sbml = build_sbml(
        "unbinding_model",
        [
            ("A", "A", 4.0, None),
            ("B", "B", 4.0, None),
            ("CPLX", "assembled entity", 2.0, None),
        ],
        [
            _reaction("assemble", ["A", "B"], ["CPLX"], "kon", ["A", "B"]),
            _reaction("disassemble", ["CPLX"], ["A", "B"], "koff", ["CPLX"]),
        ],
        [("kon", 0.4), ("koff", 0.2)],
    )

    record = _inference(sbml, "CPLX")

    assert record["confidence"] == "reaction-topology"
    assert record["molecules"] == ["A", "B"]


def test_stoichiometry_above_one_is_reflected_in_the_complex_composition():
    """The composition of an inferred complex follows the stoichiometry."""

    sbml = build_sbml(
        "stoichiometry_model",
        [
            ("A", "A", 10.0, None),
            ("B", "B", 5.0, None),
            ("A2B", "dimer", 0.0, None),
        ],
        [
            _reaction(
                "dimerize",
                ["A", "B"],
                ["A2B"],
                "kon",
                ["A", "B"],
                stoichiometries={"A": 2},
            )
        ],
        [("kon", 0.5)],
    )

    record = _inference(sbml, "A2B")

    assert record["confidence"] == "reaction-topology"
    assert record["molecules"] == ["A", "A", "B"]


def test_topology_analysis_is_reported_separately():
    sbml = build_sbml(
        "topology_report_model",
        [
            ("A", "A", 10.0, None),
            ("B", "B", 5.0, None),
            ("AB", "assembled", 0.0, None),
        ],
        [_reaction("bind", ["A", "B"], ["AB"], "kon", ["A", "B"])],
        [("kon", 0.5)],
    )

    model = SBMLParser().parse(sbml)
    topology = analyze_structural_topology(model)

    assert topology["complexes"]["AB"] == ["A", "B"]
    assert topology["modifications"] == {}
    assert topology["unbindings"] == {}


# ---------------------------------------------------------------------------
# Name-based inference
# ---------------------------------------------------------------------------


def test_name_complex_candidates_require_known_constituents_for_hyphen():
    known = {"A": "A", "B": "B"}

    assert _name_complex_candidates("A-B", known) == [("-", ["A", "B"])]
    assert _name_complex_candidates("A-B", {"A": "A"}) == []
    assert _name_complex_candidates("IL-2", known) == []


def test_name_complex_candidates_accept_the_dot_separator():
    assert _name_complex_candidates("A.B", {}) == [(".", ["A", "B"])]


def test_name_complex_candidates_ignore_organism_names():
    assert _name_complex_candidates("C. elegans", {}) == []


def test_separator_tolerant_modification_suffix():
    assert infer_modification("A-P", ["A"]).modification == "Phosphorylation"
    assert (
        infer_modification("A-PP", ["A"]).modification == "Double-Phosphorylation"
    )
    assert infer_modification("A_act", ["A"]).modification == "Activation"
    assert infer_modification("A-P", ["A"]).base == "A"


def test_modification_inference_is_not_applied_without_a_base():
    assert infer_modification("A-P", ["B"]).modification is None


# ---------------------------------------------------------------------------
# The structural inference record
# ---------------------------------------------------------------------------


def test_flat_translation_has_no_structural_record():
    sbml = build_sbml(
        "flat_model",
        [
            ("A", "A", 10.0, None),
            ("B", "B", 5.0, None),
            ("AB", "A.B", 0.0, None),
        ],
        [_reaction("bind", ["A", "B"], ["AB"], "kon", ["A", "B"])],
        [("kon", 0.5)],
    )

    result = _atomize(sbml, atomize=False)

    assert result.success, result.error
    assert result.structural_inference is None


def test_structural_record_reports_confidence_and_summary():
    sbml = build_sbml(
        "record_model",
        [
            ("A", "A", 10.0, None),
            ("B", "B", 5.0, None),
            ("AB", "A.B", 0.0, None),
            ("AP", "A-P", 0.0, "SBO:0000216"),
        ],
        [
            _reaction("bind", ["A", "B"], ["AB"], "kon", ["A", "B"]),
            _reaction("phos", ["A"], ["AP"], "kcat", ["A"]),
        ],
        [("kon", 0.5), ("kcat", 0.1)],
    )

    result = _atomize(sbml)
    report = result.structural_inference

    assert report is not None
    summary = report["summary"]
    assert summary["species_total"] == 4
    assert summary["structural_species"] == 2
    assert summary["elemental_species"] == 2
    assert summary["confidence"]["sbo-term"] == 1
    assert summary["confidence"]["reaction-topology"] == 1


def test_structural_record_is_available_from_the_atomizer_api():
    sbml = build_sbml(
        "api_model",
        [
            ("A", "A", 10.0, None),
            ("AP", "A-P", 0.0, "SBO:0000216"),
        ],
        [_reaction("phos", ["A"], ["AP"], "kcat", ["A"])],
        [("kcat", 0.1)],
    )

    atomizer = Atomizer({"atomize": True, "quiet_mode": True})
    atomizer.atomize(sbml)
    report = atomizer.structural_report()

    assert report is not None
    assert report["species"]["AP"]["confidence"] == "sbo-term"


def test_structural_record_lists_alternative_readings():
    """A name that admits two readings must report both."""

    sbml = build_sbml(
        "alternative_model",
        [
            ("A", "A", 4.0, None),
            ("B", "B", 4.0, None),
            ("C", "C", 4.0, None),
            ("AB", "A.B", 0.0, None),
        ],
        [_reaction("bind", ["A", "C"], ["AB"], "kon", ["A", "C"])],
        [("kon", 0.5)],
    )

    record = _inference(sbml, "AB")

    assert record["molecules"] == ["A", "B"]
    assert record["confidence"] == "explicit-pattern"
    topology_alternatives = [
        alternative
        for alternative in record["alternatives"]
        if alternative["confidence"] == "reaction-topology"
    ]
    assert topology_alternatives
    assert topology_alternatives[0]["molecules"] == ["A", "C"]


# ---------------------------------------------------------------------------
# Flat-versus-atomized mathematical equivalence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", GROUND_TRUTH_MODELS, ids=lambda m: m.name)
def test_flat_and_atomized_translations_are_mathematically_equivalent(model):
    report = compare_flat_and_atomized(
        model.sbml, t_end=model.t_end, n_steps=model.n_steps
    )

    assert report["flat_success"], report["flat_error"]
    assert report["atomized_success"], report["atomized_error"]
    assert report["problems"] == []
    assert report["equivalent"]


@pytest.mark.parametrize("model", GROUND_TRUTH_MODELS, ids=lambda m: m.name)
def test_inferred_structure_matches_the_ground_truth(model):
    metrics = structural_metrics(model.sbml)

    assert metrics["translated"], metrics["error"]
    for species_id, expected in model.expectations.items():
        record = metrics["species"][species_id]
        assert sorted(record["molecules"]) == sorted(expected["molecules"]), (
            species_id,
            record,
        )
        modification_sites = sorted(
            site for site in record["sites"] if site in record["states"]
        )
        assert modification_sites == sorted(expected["modification_sites"]), (
            species_id,
            record,
        )
        assert record["states"] == expected["states"], (species_id, record)
        assert bool(record["bonds"]) == expected["bonded"], (species_id, record)
        binding_sites = len(record["sites"]) - len(modification_sites)
        assert binding_sites == expected["binding_sites"], (species_id, record)
        assert record["confidence"] == expected["confidence"], (species_id, record)


def _reaction(
    reaction_id,
    reactants,
    products,
    rate,
    rate_factors=(),
    stoichiometries=None,
):
    from atomizer_structural_harness import _reaction_xml

    return _reaction_xml(
        reaction_id,
        reactants,
        products,
        rate,
        rate_factors,
        stoichiometries=stoichiometries,
    )
