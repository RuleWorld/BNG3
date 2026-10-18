"""Harness controls for generated #142 graph-identity cases."""

import sys
from types import SimpleNamespace
from pathlib import Path

from tests.validation import graph_identity


def test_generated_ring_permutations_are_oracle_equal_and_nontrivial():
    rings = [
        case
        for case in graph_identity.CASES
        if case["id"].startswith("symmetric-ring-")
    ]
    assert [case["id"] for case in rings] == [
        "symmetric-ring-3",
        "symmetric-ring-4",
        "symmetric-ring-5",
    ]
    for case in rings:
        left, right = case["oracle_seeds"]
        assert left != right
        assert graph_identity.oracle_partition((left, right)) == [left]
        assert case["expected_species"] == 1


def test_negative_controls_keep_state_and_both_compartment_scopes_distinct():
    controls = {
        case["id"]: case
        for case in graph_identity.CASES
        if case["expected_species"] == 2
    }
    assert set(controls) == {
        "state-distinction",
        "species-compartment-distinction",
        "molecule-compartment-distinction",
    }
    for case in controls.values():
        assert len(graph_identity.oracle_partition(case["oracle_seeds"])) == 2


def test_generated_sources_use_valid_compartment_forms_and_preserve_site_names():
    cases = {case["id"]: case for case in graph_identity.CASES}
    ring = graph_identity.model_text(cases["symmetric-ring-3"])
    assert "A(a,b)" in ring
    assert "a!3,b!1" in ring
    species = graph_identity.model_text(cases["species-compartment-distinction"])
    molecule = graph_identity.model_text(cases["molecule-compartment-distinction"])
    assert "@PM:A(x!1).B(y!1)" in species
    assert "@PM:A@CP(x!1).B@PM(y!1)" in molecule


def test_one_native_case_exception_does_not_erase_later_observations(
    tmp_path, monkeypatch
):
    class Model:
        def __init__(self, path):
            self.case_id = path.parent.name

        def generate_network(self):
            if self.case_id == graph_identity.CASES[1]["id"]:
                raise RuntimeError("synthetic case failure")
            return SimpleNamespace(
                num_species=next(
                    case["expected_species"]
                    for case in graph_identity.CASES
                    if case["id"] == self.case_id
                )
            )

        def write_net(self, path):
            if self.case_id == graph_identity.CASES[2]["id"]:
                raise OSError("synthetic artifact failure")
            Path(path).write_text("synthetic network")

    def load(path):
        case_id = Path(path).parent.name
        if case_id == graph_identity.CASES[0]["id"]:
            raise ValueError("synthetic invalid input")
        return Model(Path(path))

    fake_bionetgen = SimpleNamespace(load=load)
    monkeypatch.setitem(sys.modules, "bionetgen", fake_bionetgen)
    monkeypatch.setattr(
        graph_identity,
        "parse_net",
        lambda path: SimpleNamespace(
            species_by_index={
                index + 1: seed
                for index, seed in enumerate(
                    graph_identity.oracle_partition(
                        next(
                            case["oracle_seeds"]
                            for case in graph_identity.CASES
                            if case["id"] == path.parent.name
                        )
                    )
                )
            }
        ),
    )

    rows = graph_identity.run_worker(tmp_path)

    assert len(rows) == len(graph_identity.CASES)
    assert [row["status"] for row in rows] == [
        "INVALID_INPUT",
        "FAIL",
        "HARNESS_ERROR",
        "PASS",
        "PASS",
        "PASS",
    ]
