"""Executed only against the installed candidate in CI."""

import copy
import json

import pytest

import bionetgen
import bionetgen.bngir as bngir_module
from bionetgen.model import _cpp

from tests.validation import bngir_adversarial as adversarial


def test_native_worker_consumes_independent_documents_and_analytic_controls(tmp_path):
    rows = adversarial.run_worker(tmp_path)
    assert [row["id"] for row in rows] == adversarial.check_ids()
    for case, row in zip(adversarial.CASES, rows):
        assert row["related_issues"] == adversarial.ISSUES
        if case["oracle"] == "unsupported":
            assert row["status"] == "UNSUPPORTED", row
        elif case["oracle"] == "accept-or-unsupported":
            assert row["status"] in {"PASS", "UNSUPPORTED"}, row
        else:
            assert row["status"] == "PASS", row
        if row["supported_execution"]:
            assert (tmp_path / f"{case['id']}.execution.json").is_file()


def test_native_import_roundtrips_and_executes_hand_authored_function_document(
    monkeypatch,
):
    case = next(case for case in adversarial.CASES if case["id"] == "function-rate-law")
    document = copy.deepcopy(case["document"])
    expected = case["expected_semantics"]

    def forbidden(*_args, **_kwargs):
        pytest.fail("native BNGIR import rendered or parsed BNGL source")

    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    monkeypatch.setattr(bngir_module, "_as_bngl_v02", forbidden)

    restored = bionetgen.from_bngir(document, native=True)
    assert json.loads(restored.to_bngir(version="0.2")) == document

    network = restored.generate_network()
    state = [expected["seed"][name] for name in network.species_names]
    derivative = _cpp._validation_ode_rhs(restored._model, network, 0.0, state)
    assert dict(zip(network.species_names, derivative)) == pytest.approx(
        expected["rhs"]
    )

    result = restored.simulate(
        method="ode", t_end=2.0, n_steps=10, atol=1e-12, rtol=1e-10
    )
    assert result.time.tolist() == pytest.approx(
        [point["time"] for point in expected["trajectory"]]
    )
    for observed, reference in zip(result.concentrations, expected["trajectory"]):
        assert dict(zip(network.species_names, observed)) == pytest.approx(
            reference["amounts"], abs=1e-7, rel=1e-7
        )


def test_compartment_and_bonded_cases_execute_against_independent_laws(tmp_path):
    """The known native gaps must not be discharged as UNSUPPORTED."""
    rows = {row["check"]: row for row in adversarial.run_worker(tmp_path)}
    for case in adversarial.CASES:
        if case["id"] in {
            "compartment-suffix",
            "compartment-prefix",
            "molecule-compartment",
            "bonded-complex-boundary",
            "wrong-bond-changes-reconstructed-complex",
        }:
            assert case["oracle"] == "accept"
            row = rows[case["id"]]
            assert row["status"] == "PASS", row
            assert row["supported_execution"] is True
            assert (tmp_path / f"{case['id']}.execution.json").is_file()


def test_wrong_bond_control_detects_reconstructed_behaviour_change():
    base = next(c for c in adversarial.CASES if c["id"] == "bonded-complex-boundary")
    changed = next(
        c
        for c in adversarial.CASES
        if c["id"] == "wrong-bond-changes-reconstructed-complex"
    )
    base_model = bionetgen.BioNetGenModel(
        _cpp._model_from_bngir_v02(copy.deepcopy(base["document"]["model"]))
    )
    changed_model = bionetgen.BioNetGenModel(
        _cpp._model_from_bngir_v02(copy.deepcopy(changed["document"]["model"]))
    )
    base_species = set(base_model.generate_network().species_names)
    changed_species = set(changed_model.generate_network().species_names)
    assert base_species != changed_species
    assert "A(b!1).A(b!1)" in base_species
    assert "A(b!1).B(b!1)" in changed_species


def test_malformed_bond_fails_before_a_model_is_returned():
    case = next(c for c in adversarial.CASES if c["id"] == "unpaired-exact-bond-group")
    document = copy.deepcopy(case["document"])
    before = json.dumps(document, sort_keys=True)
    with pytest.raises(Exception, match="exact bond group"):
        _cpp._model_from_bngir_v02(document["model"])
    # Refusal is atomic: the input document is untouched and a subsequent
    # valid import still constructs a fresh model.
    assert json.dumps(document, sort_keys=True) == before
    valid = next(c for c in adversarial.CASES if c["id"] == "baseline-native-control")
    assert isinstance(
        _cpp._model_from_bngir_v02(copy.deepcopy(valid["document"]["model"])),
        _cpp.Model,
    )
