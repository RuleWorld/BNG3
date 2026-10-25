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
