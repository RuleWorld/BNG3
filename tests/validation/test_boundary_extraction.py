"""The extracted-capability boundary qualification (#164).

The family has to be able to refuse the two regressions it exists for: a
consumer that stops asking the named seam, and a writer that reports a
different total-rate decision than the model source declares.  These tests
therefore mutate a copy of the tree and a copy of the artefacts instead of
asserting only that the current tree passes.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.validation import boundary_extraction as boundary

ROOT = Path(__file__).resolve().parents[2]


def test_the_check_identities_are_declared_independently_of_execution():
    ids = boundary.check_ids()

    assert ids == [
        "boundary-extraction:seam-ownership",
        "boundary-extraction:caller-agreement",
        "boundary-extraction:semantics-unchanged",
        "qualification:issue:164:extract-cohesive-boundaries-incrementally-without-changing-suppo",
    ]
    assert len(ids) == len(set(ids))


def test_the_generated_family_states_the_total_rate_outcome_of_every_reaction():
    assert boundary.CASES
    for case in boundary.CASES:
        assert case["reactions"], case["id"]
        for reaction in case["reactions"]:
            assert isinstance(reaction["total_rate"], bool)
            assert reaction["factor"] > 0.0
            assert reaction["reactants"] or reaction["products"]


def test_the_seam_owns_the_capability_in_the_current_tree():
    assert boundary.seam_differences() == []


def _tree_copy(tmp_path: Path) -> Path:
    """A copy of the C++ tree that the seam-ownership scan can read."""
    root = tmp_path / "tree"
    for directory in ("compile", "engine", "io", "parser"):
        (root / "cpp" / directory).mkdir(parents=True)
    for relative in (
        "cpp/compile/TotalRate.hpp",
        "cpp/compile/TotalRate.cpp",
        "cpp/compile/CompiledRule.cpp",
        "cpp/engine/OdeIntegrator.cpp",
        "cpp/engine/PsaSimulator.cpp",
        "cpp/io/NetWriter.cpp",
        "cpp/io/SbmlReader.cpp",
        "cpp/io/SbmlWriter.cpp",
        "cpp/io/XmlWriter.cpp",
    ):
        shutil.copy2(ROOT / relative, root / relative)
    return root


def test_a_consumer_that_stops_asking_the_seam_is_refused(tmp_path):
    root = _tree_copy(tmp_path)
    writer = root / "cpp" / "io" / "SbmlWriter.cpp"
    text = writer.read_text(encoding="utf-8")
    text = text.replace(
        "bng::compile::isTotalRateReaction(model, rxn.getOriginRuleName())",
        "hasTotalRateModifier(model, rxn.getOriginRuleName())",
    )
    writer.write_text(text, encoding="utf-8")

    differences = boundary.seam_differences(root)

    assert any(
        item["field"] == "consumer.does-not-call-the-seam" for item in differences
    )


def test_a_second_owner_of_the_modifier_spelling_is_refused(tmp_path):
    root = _tree_copy(tmp_path)
    writer = root / "cpp" / "io" / "SbmlWriter.cpp"
    writer.write_text(
        writer.read_text(encoding="utf-8")
        + "\nbool hasTotalRateModifier(const ast::Model&, const std::string& origin) {\n"
        + '    return lower(origin) == "totalrate";\n}\n',
        encoding="utf-8",
    )

    differences = boundary.seam_differences(root)

    assert any(
        item["field"] == "spelling.decided-outside-the-seam" for item in differences
    )


def test_a_missing_seam_is_refused(tmp_path):
    root = _tree_copy(tmp_path)
    (root / "cpp" / "compile" / "TotalRate.hpp").unlink()

    differences = boundary.seam_differences(root)

    assert any(item["field"] == "seam.header" for item in differences)


def test_a_writer_that_drops_the_total_rate_marker_is_refused():
    """The pre-extraction SBML writer did not mark the reverse direction."""
    case = next(item for item in boundary.CASES if item["id"] == "total-reversible-2a")
    net = [
        dict(
            index=1, reactants=[1, 1], products=[2, 2], rate="kf", factor=1.0, rule="R1"
        ),
        dict(
            index=2, reactants=[2, 2], products=[1, 1], rate="kr", factor=1.0, rule="R2"
        ),
    ]
    sbml = [
        dict(annotated=True, factor=1.0, identifiers=["kf"], species=[]),
        dict(annotated=False, factor=1.0, identifiers=["kr"], species=[]),
    ]

    differences = boundary.caller_differences(case, net, sbml)

    assert any(
        item["field"] == "reaction[1].sbml.total-rate-marker" for item in differences
    )


def test_a_network_writer_that_applies_the_symmetry_factor_to_a_total_rate_is_refused():
    case = next(item for item in boundary.CASES if item["id"] == "total-forward-3a")
    net = [
        dict(
            index=1,
            reactants=[1, 1, 1],
            products=[],
            rate="k",
            factor=1.0 / 6.0,
            rule="R1",
        )
    ]
    sbml = [dict(annotated=True, factor=1.0, identifiers=["k"], species=[])]

    differences = boundary.caller_differences(case, net, sbml)

    assert any(item["field"] == "reaction[0].net.factor" for item in differences)


def test_the_family_reports_every_named_check(tmp_path):
    rows = boundary.run_worker(tmp_path)

    assert [row["id"] for row in rows] == boundary.check_ids()
    for row in rows:
        assert row["status"] == "PASS", (row["id"], row["detail"])
        assert row["evidence_kind"] == "supported-execution"
        assert row["supported_execution"] is True


def test_the_covering_qualified_checks_are_the_existing_ones(tmp_path):
    outcomes = boundary.covering_outcomes(tmp_path)

    assert set(outcomes) == {"rate-law-contract", "network-rule-execution"}
    for entry in outcomes.values():
        assert entry["not_passed"] == []
        assert entry["passed"] == entry["checks"]


@pytest.mark.parametrize("case", boundary.CASES, ids=lambda case: case["id"])
def test_every_generated_case_agrees_with_both_writers(tmp_path, case):
    import bionetgen

    case_dir = tmp_path / case["id"]
    case_dir.mkdir(parents=True)
    source = case_dir / "model.bngl"
    source.write_text(case["bngl"], encoding="utf-8")
    model = bionetgen.load(str(source))
    model.generate_network()
    model.write_net(str(case_dir / "model.net"))
    model.write_sbml(str(case_dir / "model.xml"))

    net = boundary._net_reactions((case_dir / "model.net").read_text())
    sbml = boundary._sbml_reactions((case_dir / "model.xml").read_text())

    assert boundary.caller_differences(case, net, sbml) == []
