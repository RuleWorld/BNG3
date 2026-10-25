"""Focused regression tests for the structural SBML atomization path.

The tests cover the widened structural trigger, the ``sboTerm``-driven
modification inference, the stoichiometry-aware reaction-topology complex
inference, the machine-readable structural inference record, and the
flat-versus-atomized mathematical equivalence on synthetic models whose
molecular structure is known by construction.
"""

from __future__ import annotations

import os
import re
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
    assert [component.name for component in structure.molecules[0].components] == ["b1"]
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
    assert normalize_sbo_term("http://identifiers.org/SBO:0000216") == "SBO:0000216"
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


def test_removal_sbo_term_yields_the_unmodified_form():
    """A removal term names the species as the unmodified form."""

    sbml = build_sbml(
        "removal_model",
        [
            ("A", "A", 10.0, None),
            ("AP", "A-P", 4.0, "SBO:0000216"),
            ("A2", "A", 1.0, "SBO:0000330"),
        ],
        [
            _reaction("phos", ["A"], ["AP"], "kcat", ["A"]),
            _reaction("dephos", ["AP"], ["A2"], "kdp", ["AP"]),
        ],
        [("kcat", 0.1), ("kdp", 0.05)],
    )

    modified = _inference(sbml, "AP")
    unmodified = _inference(sbml, "A2")

    assert modified["confidence"] == "sbo-term"
    assert modified["states"] == {"phosphorylation": "P"}
    assert unmodified["confidence"] == "sbo-term"
    assert unmodified["states"] == {"phosphorylation": "0"}


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


def _compartment_topology_model(
    *,
    compartments,
    species_compartments,
    product_name="assembled",
    reactions=None,
    extra_species=(),
    prefix_species=(),
):
    """Build a topology case with explicit source compartment geometry."""

    sbml = build_sbml(
        "compartment_topology",
        [
            *prefix_species,
            ("A", "A", 4.0, None),
            ("B", "B", 4.0, None),
            ("AB", product_name, 0.0, None),
            *extra_species,
        ],
        (
            [_reaction("bind", ["A", "B"], ["AB"], "kon", ["A", "B"])]
            if reactions is None
            else reactions
        ),
        [("kon", 0.5), ("koff", 0.2)],
    )
    compartment_entries = []
    for name, dimensions, outside in compartments:
        outside_attribute = f' outside="{outside}"' if outside else ""
        compartment_entries.append(
            f'<compartment id="{name}" size="1" spatialDimensions="{dimensions}" '
            f'constant="true"{outside_attribute}/>'
        )
    compartment_xml = "\n".join(compartment_entries)
    sbml = re.sub(r'<compartment id="c"[^>]*/>', compartment_xml, sbml, count=1)
    for species_id, compartment in species_compartments.items():
        sbml = re.sub(
            rf'(<species id="{re.escape(species_id)}"[^>]* compartment=")[^"]+',
            rf"\g<1>{compartment}",
            sbml,
            count=1,
        )
    return sbml


def test_nonadjacent_compartment_topology_falls_back_with_machine_reason():
    sbml = _compartment_topology_model(
        compartments=[("pm", 3, None), ("cyt", 3, None)],
        species_compartments={"A": "pm", "B": "cyt", "AB": "pm"},
    )

    record = _inference(sbml, "AB")

    assert record["confidence"] == "elemental"
    assert record["molecules"] == ["AB"]
    fallback = next(
        alternative
        for alternative in record["alternatives"]
        if alternative.get("code") == "cross-compartment-inference"
    )
    assert fallback["components"] == ["A", "B"]
    assert fallback["component_compartments"] == ["pm", "cyt"]
    assert fallback["product_compartment"] == "pm"


def test_same_compartment_topology_stays_structural_and_adjacent_falls_back():
    same = _compartment_topology_model(
        compartments=[("cell", 3, None)],
        species_compartments={"A": "cell", "B": "cell", "AB": "cell"},
    )
    adjacent = _compartment_topology_model(
        compartments=[("outside", 3, None), ("membrane", 2, "outside")],
        species_compartments={"A": "membrane", "B": "outside", "AB": "membrane"},
    )

    assert _inference(same, "AB")["confidence"] == "reaction-topology"
    adjacent_record = _inference(adjacent, "AB")
    assert adjacent_record["confidence"] == "elemental"
    assert any(
        alternative.get("code") == "cross-compartment-inference"
        for alternative in adjacent_record["alternatives"]
    )
    assert compare_flat_and_atomized(adjacent)["problems"] == []


def test_cross_compartment_fallback_covers_unbinding_and_name_inference():
    unbinding = _compartment_topology_model(
        compartments=[("pm", 3, None), ("cyt", 3, None)],
        species_compartments={"A": "pm", "B": "cyt", "AB": "pm"},
        reactions=[_reaction("unbind", ["AB"], ["A", "B"], "koff", ["AB"])],
    )
    name_only = _compartment_topology_model(
        compartments=[("pm", 3, None), ("cyt", 3, None)],
        species_compartments={"A": "pm", "B": "cyt", "AB": "pm"},
        product_name="A-B",
        reactions=[],
    )
    explicit = _compartment_topology_model(
        compartments=[("pm", 3, None), ("cyt", 3, None)],
        species_compartments={"A": "pm", "B": "cyt", "AB": "pm"},
        product_name="A(b!1).B(b!1)",
    )

    for sbml in (unbinding, name_only, explicit):
        record = _inference(sbml, "AB")
        assert record["confidence"] == "elemental"
        assert any(
            alternative.get("code") == "cross-compartment-inference"
            for alternative in record["alternatives"]
        )


def test_cross_compartment_use_flattens_complex_even_with_same_compartment_path():
    sbml = _compartment_topology_model(
        compartments=[("pm", 3, None), ("cyt", 3, None)],
        species_compartments={
            "A": "pm",
            "B": "pm",
            "AB": "pm",
            "C": "pm",
            "D": "cyt",
            "ABC": "pm",
            "ABD": "pm",
        },
        extra_species=[
            ("C", "C", 4.0, None),
            ("D", "D", 4.0, None),
            ("ABC", "final", 0.0, None),
            ("ABD", "cross-compartment product", 0.0, None),
        ],
        reactions=[
            _reaction("bind", ["A", "B"], ["AB"], "kon", ["A", "B"]),
            _reaction("extend", ["AB", "C"], ["ABC"], "kon", ["AB", "C"]),
            _reaction("capture", ["AB", "D"], ["ABD"], "kon", ["AB", "D"]),
        ],
    )

    ab = _inference(sbml, "AB")
    abc = _inference(sbml, "ABC")

    assert ab["confidence"] == "elemental"
    assert any(
        alternative.get("code") == "cross-compartment-inference"
        and "capture" in alternative.get("source_reactions", [])
        for alternative in ab["alternatives"]
    )
    assert abc["confidence"] == "reaction-topology"
    assert abc["molecules"] == ["AB", "C"]
    assert compare_flat_and_atomized(sbml)["problems"] == []


def test_unresolved_explicit_molecules_do_not_trigger_false_fallback_structure():
    sbml = build_sbml(
        "unresolved_explicit_pattern",
        [("X", "A(b!1).B(b!1)", 1.0, None)],
        [],
    )

    record = _inference(sbml, "X")

    assert record["confidence"] == "explicit-pattern"
    assert record["molecules"] == ["A", "B"]
    assert not any(
        alternative.get("code") == "cross-compartment-inference"
        for alternative in record["alternatives"]
    )


def test_forced_flattening_uses_source_id_and_matches_source_execution():
    sbml = build_sbml(
        "unresolved_explicit_cross_compartment",
        [
            ("X", "A(b!1).B(b!1)", 1.0, None),
            ("C", "C", 1.0, None),
            ("Y", "Y", 0.0, None),
        ],
        [_reaction("capture", ["X", "C"], ["Y"], "kon", ["X", "C"])],
        [("kon", 0.1)],
    )
    sbml = re.sub(
        r'<compartment id="c"[^>]*/>',
        '<compartment id="pm" size="1" spatialDimensions="3" constant="true"/>'
        '<compartment id="cyt" size="1" spatialDimensions="3" constant="true"/>',
        sbml,
        count=1,
    )
    for species_id, compartment in (("X", "pm"), ("Y", "pm"), ("C", "cyt")):
        sbml = re.sub(
            rf'(<species id="{re.escape(species_id)}"[^>]* compartment=")[^\"]+',
            rf"\g<1>{compartment}",
            sbml,
            count=1,
        )

    record = _inference(sbml, "X")

    assert record["confidence"] == "elemental"
    assert record["molecules"] == ["X"]
    assert any(
        alternative.get("code") == "cross-compartment-inference"
        for alternative in record["alternatives"]
    )
    import numpy as np
    import bionetgen._bionetgen_cpp as cpp
    from bionetgen.model import BioNetGenModel

    roadrunner = pytest.importorskip("roadrunner")
    translated = _atomize(sbml)
    assert translated.success, translated.error
    bng = BioNetGenModel(cpp.parse_string(translated.bngl)).simulate(
        method="ode", t_end=1.0, n_steps=10, rtol=1e-9, atol=1e-12
    )
    source = roadrunner.RoadRunner(sbml)
    source.integrator.setValue("relative_tolerance", 1e-9)
    source.integrator.setValue("absolute_tolerance", 1e-12)
    source.timeCourseSelections = ["time", "[X]", "[C]", "[Y]"]
    reference = source.simulate(0.0, 1.0, 11)
    for column, species_id in enumerate(("X", "C", "Y"), start=1):
        np.testing.assert_allclose(
            bng.observables[species_id], reference[:, column], rtol=1e-6, atol=5e-9
        )


def test_cross_compartment_fallback_keeps_source_ids_when_names_collide():
    sbml = _compartment_topology_model(
        compartments=[("pm", 3, None), ("cyt", 3, None)],
        species_compartments={
            "shadow": "cyt",
            "A": "pm",
            "B": "pm",
            "AB": "pm",
            "D": "cyt",
            "ABD": "pm",
        },
        prefix_species=[("shadow", "A", 4.0, None)],
        extra_species=[("D", "D", 4.0, None), ("ABD", "product", 0.0, None)],
        reactions=[
            _reaction("bind", ["A", "B"], ["AB"], "kon", ["A", "B"]),
            _reaction("capture", ["AB", "D"], ["ABD"], "kon", ["AB", "D"]),
        ],
    )

    record = _inference(sbml, "AB")
    fallback = next(
        alternative
        for alternative in record["alternatives"]
        if alternative.get("code") == "cross-compartment-inference"
    )

    assert fallback["components"] == ["A", "B"]
    assert fallback["component_compartments"] == ["pm", "pm"]


def test_nonadjacent_compartment_fallback_preserves_executable_reaction():
    sbml = _compartment_topology_model(
        compartments=[("pm", 3, None), ("cyt", 3, None)],
        species_compartments={"A": "pm", "B": "cyt", "AB": "pm"},
    )

    report = compare_flat_and_atomized(sbml)

    assert report["problems"] == []
    assert report["flat_species"] == report["atomized_species"]
    assert report["flat_reactions"] == report["atomized_reactions"]


@pytest.mark.parametrize(
    ("compartments", "species_compartments"),
    [
        (
            [("pm", 3, None), ("cyt", 3, None)],
            {"A": "pm", "B": "cyt", "AB": "pm"},
        ),
        (
            [("outside", 3, None), ("membrane", 2, "outside")],
            {"A": "membrane", "B": "outside", "AB": "membrane"},
        ),
    ],
)
def test_cross_compartment_fallback_matches_original_sbml_law(
    compartments, species_compartments
):
    import numpy as np

    roadrunner = pytest.importorskip("roadrunner")
    import bionetgen._bionetgen_cpp as cpp
    from bionetgen.model import BioNetGenModel

    sbml = _compartment_topology_model(
        compartments=compartments,
        species_compartments=species_compartments,
    )
    translated = _atomize(sbml)
    assert translated.success, translated.error

    bng = BioNetGenModel(cpp.parse_string(translated.bngl)).simulate(
        method="ode", t_end=1.0, n_steps=10, rtol=1e-9, atol=1e-12
    )
    source = roadrunner.RoadRunner(sbml)
    source.integrator.setValue("relative_tolerance", 1e-9)
    source.integrator.setValue("absolute_tolerance", 1e-12)
    source.timeCourseSelections = ["time", "[A]", "[B]", "[AB]"]
    reference = source.simulate(0.0, 1.0, 11)

    for column, species_id in enumerate(("A", "B", "AB"), start=1):
        np.testing.assert_allclose(
            bng.observables[species_id],
            reference[:, column],
            rtol=1e-6,
            atol=5e-9,
        )


def test_association_that_is_not_one_to_one_keeps_the_flat_representation():
    """A stoichiometry above one is a mass balance, not a composition."""

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

    assert record["confidence"] == "elemental"
    assert record["molecules"] == ["A2B"]
    assert any(
        alternative["confidence"] == "reaction-topology"
        for alternative in record["alternatives"]
    )


def test_flat_and_atomized_networks_match_for_a_non_unit_stoichiometry():
    sbml = build_sbml(
        "non_unit_model",
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

    report = compare_flat_and_atomized(sbml)

    assert report["problems"] == []
    assert report["flat_species"] == report["atomized_species"]
    assert report["flat_reactions"] == report["atomized_reactions"]


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


def test_uncorroborated_name_reading_is_reported_as_an_alternative():
    """A rejected name reading must not disappear silently."""

    sbml = build_sbml(
        "uncorroborated_model",
        [
            ("A", "A", 4.0, None),
            ("AB", "A-B", 2.0, None),
        ],
        [],
        [],
    )

    record = _inference(sbml, "AB")

    assert record["confidence"] == "elemental"
    assert record["molecules"] == ["AB"]
    assert any(
        alternative["molecules"] == ["A", "B"] for alternative in record["alternatives"]
    )


def test_separator_tolerant_modification_suffix():
    assert infer_modification("A-P", ["A"]).modification == "Phosphorylation"
    assert infer_modification("A-PP", ["A"]).modification == "Double-Phosphorylation"
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


def test_complex_of_a_complex_keeps_the_exact_flat_representation():
    """A complex whose component is itself a complex has no exact pattern."""

    sbml = build_sbml(
        "nested_model",
        [
            ("A", "A", 6.0, None),
            ("B", "B", 4.0, None),
            ("C", "C", 2.0, None),
            ("AB", "AB", 1.0, None),
            ("ABC", "ABC", 0.0, None),
        ],
        [
            _reaction("ab", ["A", "B"], ["AB"], "kon", ["A", "B"]),
            _reaction("abc", ["AB", "C"], ["ABC"], "kon", ["AB", "C"]),
        ],
        [("kon", 0.5)],
    )

    complex_record = _inference(sbml, "AB")
    nested_record = _inference(sbml, "ABC")

    assert complex_record["confidence"] == "reaction-topology"
    assert complex_record["molecules"] == ["A", "B"]
    assert nested_record["confidence"] == "elemental"
    assert nested_record["molecules"] == ["ABC"]
    assert any(
        alternative["confidence"] == "reaction-topology"
        for alternative in nested_record["alternatives"]
    )


def test_flat_and_atomized_networks_match_for_a_nested_complex():
    sbml = build_sbml(
        "nested_network_model",
        [
            ("A", "A", 6.0, None),
            ("B", "B", 4.0, None),
            ("C", "C", 2.0, None),
            ("AB", "AB", 1.0, None),
            ("ABC", "ABC", 0.0, None),
        ],
        [
            _reaction("ab", ["A", "B"], ["AB"], "kon", ["A", "B"]),
            _reaction("abc", ["AB", "C"], ["ABC"], "kon", ["AB", "C"]),
        ],
        [("kon", 0.5)],
    )

    report = compare_flat_and_atomized(sbml)

    assert report["problems"] == []
    assert report["flat_species"] == report["atomized_species"]
    assert report["flat_reactions"] == report["atomized_reactions"]


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
