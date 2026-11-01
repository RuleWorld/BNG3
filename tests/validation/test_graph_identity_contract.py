"""Harness controls for the generated #142 identity-contract cases."""

from __future__ import annotations

import pytest

from tests.validation import graph_identity_contract as contract
from tests.validation.compare import species_isomorphic


def _case(case_id: str) -> dict:
    return next(case for case in contract.CASES if case["id"] == case_id)


def test_generated_cases_exercise_both_equality_and_difference():
    rings = [
        case for case in contract.CASES if case["id"].startswith("symmetric-ring-")
    ]
    assert [case["id"] for case in rings] == [
        "symmetric-ring-3",
        "symmetric-ring-4",
        "symmetric-ring-5",
    ]
    for case in rings:
        first, second, chain = case["species"]
        # The permuted spelling differs in node labelling and traversal order.
        assert first != second
        assert species_isomorphic(first, second)
        # The chain is a different graph, so the contract is exercised in both
        # directions rather than assumed.
        assert not species_isomorphic(first, chain)


def test_generated_compartment_controls_separate_the_identity_layers():
    molecule = _case("molecule-compartment-distinction")
    species = _case("species-compartment-distinction")
    for case in (molecule, species):
        texts = tuple(contract.contract_spelling(text) for text in case["species"])
        # The structure layer ignores the compartments.
        assert len(contract.contract_partition(texts, contract.LAYER_STRUCTURE)) == 1
        # The compartment and species layers keep them apart.
        assert len(contract.contract_partition(texts, contract.LAYER_COMPARTMENT)) == 2
        assert len(contract.contract_partition(texts, contract.LAYER_SPECIES)) == 2


def test_bounded_exhaustive_family_covers_two_molecule_equivalent_site_graphs():
    case = _case("exhaustive-small-equivalent-sites")
    assert len(case["species"]) == 116
    assert any("." not in species for species in case["species"])
    assert any("." in species and "!" not in species for species in case["species"])
    assert any(species.count("!") == 2 for species in case["species"])
    assert any(species.count("!") == 4 for species in case["species"])


def test_contract_spelling_keeps_the_compartments_and_the_bonds():
    assert contract.contract_spelling("@PM:A(x!1)@CP.B(y!1)@PM") == (
        "@PM::A(x!1)@CP.B(y!1)@PM"
    )
    assert contract.contract_spelling("A(x!1).B(y!2)") == "A(x!1).B(y!2)"
    structure = contract.relation_text(
        "@PM::A(x!1)@CP.B(y!1)@PM", contract.LAYER_STRUCTURE
    )
    assert structure == "A(x!1).B(y!1)"
    compartment = contract.relation_text(
        "@PM::A(x!1)@CP.B(y!1)@PM", contract.LAYER_COMPARTMENT
    )
    assert compartment == "A(x!1)@CP.B(y!1)@PM"
    inherited = contract.relation_text("@PM::A(x!1).B(y!1)", contract.LAYER_COMPARTMENT)
    assert inherited == "A(x!1)@PM.B(y!1)@PM"


def test_the_native_surfaces_match_the_independent_contract(tmp_path):
    rows = contract.run_worker(tmp_path)

    assert [row["id"] for row in rows] == [
        f"graph-identity-contract:{case['id']}:{check}"
        for case in contract.CASES
        for check in contract.CHECKS
    ]
    assert {row["status"] for row in rows} == {"PASS"}, [
        row for row in rows if row["status"] != "PASS"
    ]
    for row in rows:
        assert row["related_issues"] == [142]
        assert row["identity_relations"] == contract.SURFACE_LAYERS


def _fake_probe(entries: list[dict], layers: dict):
    def probe(model):
        return {"species": entries, "layers": layers}

    return probe


def _observations(tmp_path, case_id: str):
    """Read the native observations of one generated case."""
    from bionetgen import _bionetgen_cpp as cpp

    case = _case(case_id)
    source = tmp_path / "model.bngl"
    source.write_text(contract.model_text(case), encoding="utf-8")
    import bionetgen

    model = bionetgen.load(str(source))
    return list(cpp._validation_species_identity_labels(model._model)["species"]), dict(
        cpp._validation_species_identity_labels(model._model)["layers"]
    )


def test_two_different_graphs_that_share_a_label_are_a_mismatch(tmp_path, monkeypatch):
    from bionetgen import _bionetgen_cpp as cpp

    case = _case("topology-distinction")
    entries, layers = _observations(tmp_path, case["id"])
    assert len({entry["network_label"] for entry in entries}) == 2
    # Give the two different graphs the same label: the check must refuse the
    # merge instead of accepting the shared label as an identity.
    entries[1]["network_label"] = entries[0]["network_label"]
    monkeypatch.setattr(
        cpp,
        "_validation_species_identity_labels",
        _fake_probe(entries, layers),
    )

    rows = contract._run_case(case, tmp_path / "collision")
    row = next(row for row in rows if row["check"] == "network-canonical-label")
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"] == "network-canonical-label"


def test_a_surface_that_decides_another_layer_is_visible(tmp_path, monkeypatch):
    from bionetgen import _bionetgen_cpp as cpp

    case = _case("state-distinction")
    entries, layers = _observations(tmp_path, case["id"])
    layers = dict(layers)
    layers["network-canonical-label"] = contract.LAYER_SPECIES
    monkeypatch.setattr(
        cpp,
        "_validation_species_identity_labels",
        _fake_probe(entries, layers),
    )

    rows = contract._run_case(case, tmp_path / "layer")
    row = next(row for row in rows if row["check"] == "shared-identity-contract")
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"] == "declared-identity-relation"


def test_a_canonicalizer_that_decides_another_relation_is_a_mismatch(
    tmp_path, monkeypatch
):
    """A compartment-blind NFsim label must not pass the compartment layer."""

    from bionetgen import _bionetgen_cpp as cpp

    case = _case("molecule-compartment-distinction")
    entries, layers = _observations(tmp_path, case["id"])
    # The NFsim surface reports the network label, which decides the structure
    # layer instead of the structure+compartment layer.
    for entry in entries:
        entry["nfsim_label"] = entry["network_label"]
    monkeypatch.setattr(
        cpp,
        "_validation_species_identity_labels",
        _fake_probe(entries, layers),
    )

    rows = contract._run_case(case, tmp_path / "relation")
    row = next(row for row in rows if row["check"] == "nfsim-canonical-label")
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"] == "nfsim-canonical-label"
    # The network label still decides the structure layer, so it stays a pass.
    network = next(row for row in rows if row["check"] == "network-canonical-label")
    assert network["status"] == "PASS"


def test_a_native_refusal_is_not_a_pass(tmp_path, monkeypatch):
    from bionetgen import _bionetgen_cpp as cpp

    def refuse(model):
        raise RuntimeError("synthetic native refusal")

    monkeypatch.setattr(cpp, "_validation_species_identity_labels", refuse)

    rows = contract.run_worker(tmp_path)
    assert rows
    assert {row["status"] for row in rows} == {"HARNESS_ERROR"}
    for row in rows:
        assert "synthetic native refusal" in row["detail"]


@pytest.mark.parametrize("relation", ["", "structure+compartment+extra"])
def test_an_unknown_relation_is_refused(relation):
    with pytest.raises(ValueError):
        contract.relation_text("A(x!1)", relation)
