"""Fault controls for the semantic-identity qualification (#166).

The qualification compares the resolved C++ model, its serialized semantic
identities and its compiled ids against an expectation the generator wrote
before the compiler ran.  These tests inject the faults that would make such
a comparison meaningless: an expectation that does not describe the model, a
reference that dangles, a serialization that loses an identity, and a model
the compiler refuses.
"""

from __future__ import annotations

import copy
import json

import pytest

from tests.validation import semantic_identity


def _snapshot(case_id="single-declaration"):
    """The compiled snapshot of one generated case."""
    import bionetgen
    from bionetgen.model import _cpp

    case = next(case for case in semantic_identity.CASES if case["id"] == case_id)
    source = _write(case)
    model = bionetgen.load(str(source))
    return case, _cpp._compiled_snapshot(model._model)


def _write(case, directory=None):
    import tempfile
    from pathlib import Path

    directory = Path(directory or tempfile.mkdtemp())
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "model.bngl"
    path.write_text(case["text"], encoding="utf-8")
    return path


def test_every_generated_case_declares_its_own_identity_expectation():
    cases = semantic_identity.CASES
    assert cases
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        expected = case["expected"]
        assert expected["namespaces"]["parameters"]
        assert expected["namespaces"]["molecule_types"]
        assert expected["namespaces"]["rules"]
        assert expected["seed_count"] >= 1
        assert len(expected["rule_labels"]) == len(expected["namespaces"]["rules"])
        assert case["text"].startswith("begin model")
        assert case["text"].rstrip().endswith("end model")


def test_the_generated_family_covers_the_declared_declaration_surface():
    namespaces = {
        namespace
        for case in semantic_identity.CASES
        for namespace, names in case["expected"]["namespaces"].items()
        if names
    }
    assert namespaces == {
        "parameters",
        "functions",
        "molecule_types",
        "compartments",
        "observables",
        "rules",
    }
    # The reordered case must really carry another id for the same name.
    shared = next(
        case
        for case in semantic_identity.CASES
        if case["id"] == "shared-component-name"
    )
    reordered = next(
        case
        for case in semantic_identity.CASES
        if case["id"] == "reordered-declarations"
    )
    assert shared["expected"]["namespaces"]["molecule_types"] == ["A", "B"]
    assert reordered["expected"]["namespaces"]["molecule_types"] == ["B", "A"]
    # Two molecule types share a component name, so the component ids are
    # declaration-local: the same component name and the same state index
    # belong to different declarations in the two molecule types.
    components = shared["expected"]["components"]
    assert components["A"]["x"] == components["B"]["x"] == 0
    states = shared["expected"]["states"]
    assert states["A"]["x"] == {"u": 0, "p": 1}
    assert states["B"]["x"] == {"on": 0, "off": 1}


def test_the_named_check_identities_are_unique_and_named():
    ids = semantic_identity.check_ids()
    assert len(ids) == len(set(ids))
    assert "campaign:semantic-identity" not in ids
    assert set(ids) <= set(
        f"semantic-identity:{case['id']}:{name}"
        for case in semantic_identity.CASES
        for name in semantic_identity.CHECKS
    )


def test_the_packing_check_accepts_the_generated_expectation():
    case, snapshot = _snapshot()
    assert semantic_identity._packing_differences(snapshot, case["expected"]) == []


def test_the_packing_check_rejects_a_declaration_order_that_does_not_match():
    case, snapshot = _snapshot()
    expected = copy.deepcopy(case["expected"])
    expected["namespaces"]["molecule_types"] = ["B", "A"]
    differences = semantic_identity._packing_differences(snapshot, expected)
    assert differences
    assert differences[0]["field"] == "molecule_types.packing"


def test_the_packing_check_rejects_a_missing_declaration():
    case, snapshot = _snapshot("three-of-each")
    expected = copy.deepcopy(case["expected"])
    expected["namespaces"]["observables"] = ["O1", "O2"]
    differences = semantic_identity._packing_differences(snapshot, expected)
    assert differences
    assert differences[0]["field"] == "observables.packing"


def test_the_packing_check_rejects_an_id_that_denotes_another_declaration():
    case, snapshot = _snapshot("shared-component-name")
    broken = copy.deepcopy(snapshot)
    broken["molecule_types"][1]["id"] = broken["molecule_types"][0]["id"]
    differences = semantic_identity._packing_differences(snapshot, case["expected"])
    assert differences == []
    differences = semantic_identity._packing_differences(broken, case["expected"])
    assert differences
    assert differences[0]["field"] == "molecule_types.packing"


def test_the_reference_check_rejects_an_id_that_denotes_another_declaration():
    case, snapshot = _snapshot("shared-component-name")
    broken = copy.deepcopy(snapshot)
    # The seed names molecule type A but points at the id of B.
    broken["seeds"][0]["pattern"]["molecules"][0]["type_id"] = 1
    differences = semantic_identity._reference_differences(broken, case["expected"])
    assert differences
    assert differences[0]["field"].endswith("type_id")


def test_the_reference_check_rejects_a_reference_that_dangles():
    case, snapshot = _snapshot()
    broken = copy.deepcopy(snapshot)
    broken["seeds"][0]["pattern"]["molecules"][0]["type_id"] = 99
    differences = semantic_identity._reference_differences(broken, case["expected"])
    assert differences
    assert differences[0]["field"].endswith("type_id")


def test_the_reference_check_rejects_a_component_index_of_another_component():
    case, snapshot = _snapshot("shared-component-name")
    broken = copy.deepcopy(snapshot)
    # The site names component "x" of molecule type A but points at another
    # component index.
    broken["seeds"][0]["pattern"]["molecules"][0]["sites"][0]["component_index"] = 3
    differences = semantic_identity._reference_differences(broken, case["expected"])
    assert differences
    assert differences[0]["field"].endswith("component_index")


def test_the_reference_check_rejects_an_expression_that_names_another_parameter():
    case, snapshot = _snapshot("three-of-each")
    broken = copy.deepcopy(snapshot)
    for parameter in broken["parameters"]:
        expression = parameter.get("expression", {})
        if expression.get("kind") == "binary":
            expression["arguments"][0]["symbol"]["index"] = 2
    differences = semantic_identity._reference_differences(broken, case["expected"])
    assert differences
    assert differences[0]["field"].endswith("expression")


def test_the_refinement_check_rejects_two_declarations_that_share_an_id():
    case, snapshot = _snapshot("shared-component-name")
    broken = copy.deepcopy(snapshot)
    broken["molecule_types"][1]["id"] = broken["molecule_types"][0]["id"]
    differences = semantic_identity._refinement_differences(broken, case["expected"])
    assert differences
    assert any(difference["field"].endswith("ids.unique") for difference in differences)


def test_the_refinement_check_rejects_a_name_that_is_not_unique():
    case, snapshot = _snapshot("shared-component-name")
    broken = copy.deepcopy(snapshot)
    broken["molecule_types"][1]["name"] = broken["molecule_types"][0]["name"]
    differences = semantic_identity._refinement_differences(broken, case["expected"])
    assert differences
    assert any(
        difference["field"].endswith("names.unique") for difference in differences
    )


def test_the_serialization_check_rejects_a_document_that_loses_an_identity():
    case, snapshot = _snapshot("three-of-each")
    resolved = {key: value for key, value in snapshot.items() if key != "actions"}
    document = {"model": resolved}
    assert semantic_identity._serialization_differences(snapshot, document) == []
    document["model"]["molecule_types"] = document["model"]["molecule_types"][:1]
    differences = semantic_identity._serialization_differences(snapshot, document)
    assert differences
    assert differences[0]["field"] == "bngir.model"


def test_a_model_the_compiler_refuses_is_never_scored_as_a_pass(monkeypatch):
    case = dict(semantic_identity.CASES[0])
    case["id"] = "uncompilable"
    case["text"] = (
        "begin model\nbegin molecule types\n  A(\nend molecule types\nend model\n"
    )
    monkeypatch.setattr(semantic_identity, "CASES", (case,))
    rows = semantic_identity.run_worker(_tmp_path())
    assert len(rows) == len(semantic_identity.CHECKS)
    assert {row["status"] for row in rows} == {"HARNESS_ERROR"}
    assert not any(row["status"] == "PASS" for row in rows)


def test_the_lean_reference_is_named_and_stays_distinct_from_the_fixture():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for relative in semantic_identity.LEAN_REFERENCE:
        assert (root / relative).is_file(), relative
    assert "formal/lean" not in semantic_identity.__file__
    assert "does not re-prove" in semantic_identity.__doc__


def test_the_declared_domain_is_stated_and_bounded():
    assert "generated models" in semantic_identity.DOMAIN
    assert "no energy pattern" in semantic_identity.DOMAIN
    assert semantic_identity.CHECKS == (
        "identity-packing",
        "identity-reference",
        "identity-refinement",
    )


def _tmp_path():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp())


def test_the_worker_emits_one_named_row_per_check_and_case():
    rows = semantic_identity.run_worker(_tmp_path())
    expected = semantic_identity.check_ids()
    assert [row["id"] for row in rows] == expected
    for row in rows:
        assert row["status"] in {"PASS", "FAIL", "HARNESS_ERROR", "UNSUPPORTED"}
        assert row["related_issues"] == [166]
        assert row["evidence_kind"] == "supported-execution"
        assert isinstance(row["detail"], str) and row["detail"]
        if row["status"] != "PASS":
            assert row["first_difference"] is not None


@pytest.mark.parametrize("case_id", ["single-declaration", "three-of-each"])
def test_the_generated_cases_resolve_to_the_expected_identities(case_id):
    case, snapshot = _snapshot(case_id)
    assert semantic_identity._reference_differences(snapshot, case["expected"]) == []
    assert semantic_identity._refinement_differences(snapshot, case["expected"]) == []
    assert json.dumps(snapshot, sort_keys=True)
