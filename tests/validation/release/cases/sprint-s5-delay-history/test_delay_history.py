"""Independent regression contracts for state-dependent SBML delay history."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "s5_case_contract", HERE / "case_contract.py"
)
CONTRACT = importlib.util.module_from_spec(_CONTRACT_SPEC)
assert _CONTRACT_SPEC.loader is not None
_CONTRACT_SPEC.loader.exec_module(CONTRACT)
CASE_IDS = CONTRACT.CASE_IDS
continuation_segments = CONTRACT.continuation_segments
expected = CONTRACT.expected
sample_times = CONTRACT.sample_times
self_check = CONTRACT.self_check
source_path = CONTRACT.source_path
source_text = CONTRACT.source_text

_SPEC = importlib.util.spec_from_file_location("s5_replay", HERE / "replay.py")
REPLAY = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(REPLAY)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_raw_sbml_is_valid_and_matches_the_reviewed_contract(case_id):
    """libSBML validates the checked-in raw source before scientific scoring."""
    import libsbml

    path = source_path(case_id)
    assert path.read_text(encoding="utf-8") == source_text(case_id)
    doc = libsbml.readSBMLFromFile(str(path))
    doc.checkConsistency()
    errors = [
        doc.getError(i).getMessage()
        for i in range(doc.getNumErrors())
        if doc.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors, errors
    model = doc.getModel()
    rules = {
        model.getRule(i).getVariable(): libsbml.formulaToL3String(
            model.getRule(i).getMath()
        )
        for i in range(model.getNumRules())
        if model.getRule(i).isSetVariable()
    }
    assert "delay(" in rules["y"]
    assert "z" in rules["y"] and "x" in rules["y"]
    assert "time" not in rules["y"]
    assert any(
        model.getRule(i).getVariable() == "x" and model.getRule(i).isRate()
        for i in range(model.getNumRules())
    )
    assert any(
        model.getRule(i).getVariable() == "z" and model.getRule(i).isRate()
        for i in range(model.getNumRules())
    )
    assert model.getNumEvents() == (0 if case_id == "ordinary" else 1)


def test_analytic_reference_has_zero_lag_and_event_boundary_values():
    self_check()
    assert expected("ordinary", 0.0)["y"] == 1.0
    assert expected("interaction", 0.4)["x"] == pytest.approx(1.4)
    assert expected("interaction", 0.8)["x"] == pytest.approx(2.4)
    assert expected("interaction", 1.2)["x"] == pytest.approx(3.6)
    assert expected("interaction", 2.0)["x"] == pytest.approx(6.0)
    assert expected("boundary", 0.999999)["q"] == 1.0
    assert expected("boundary", 1.0)["q"] == 3.0
    assert expected("boundary", 1.000001)["q"] == 3.0


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_atomizer_retains_the_nonconstant_delayed_read(case_id):
    """A valid dynamic delay must not be silently constant-folded."""
    from bionetgen.atomizer.modern import Atomizer

    atomizer = Atomizer(atomize=False, quiet_mode=True, t_end=2.0)
    result = atomizer.atomize(source_path(case_id).read_text(encoding="utf-8"))
    assert result.success, result.error
    assert "delay(" in result.bngl.lower()
    if case_id != "ordinary":
        assert "t_end=>2" in result.bngl
        assert "t_end=>10" not in result.bngl
    warnings = getattr(atomizer.model, "import_warnings", ())
    assert any("delay" in warning.message.lower() for warning in warnings)


def test_raw_roadrunner_limitation_is_not_a_bng3_result(tmp_path):
    """Oracle DDE limitations remain separate from the BNG3 product verdict."""
    pytest.importorskip("roadrunner")
    for case_id in CASE_IDS:
        row = REPLAY._road_runner_oracle(case_id, source_path(case_id), tmp_path)
        assert row["status"] in {"PASS", "FAIL", "ORACLE_UNAVAILABLE"}
        if row["status"] == "ORACLE_UNAVAILABLE":
            assert "cannot execute" in row["detail"]


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_replay_classifies_each_scientific_stage_separately(case_id, tmp_path):
    report = REPLAY.replay_case(case_id, tmp_path / case_id)
    stages = {row["id"]: row for row in report["stages"]}
    assert stages["source-validation"]["status"] == "PASS"
    assert stages["analytic-reference"]["status"] == "PASS"
    assert stages["atomizer-lowering"]["status"] in {
        "PASS",
        "REQUIRED_BUT_UNSUPPORTED",
        "FAIL",
        "HARNESS_ERROR",
    }
    assert stages["raw-source-libroadrunner"]["status"] in {
        "PASS",
        "FAIL",
        "ORACLE_UNAVAILABLE",
    }
    assert stages["public-bng3-execution"]["status"] in {
        "PASS",
        "FAIL",
        "REQUIRED_BUT_UNSUPPORTED",
        "NOT_TESTED",
    }
    assert stages["public-bng3-continuation"]["status"] in {
        "PASS",
        "FAIL",
        "NOT_REQUIRED",
        "NOT_TESTED",
    }
    assert stages["public-bng3-output-comparison"]["status"] in {
        "PASS",
        "FAIL",
        "NOT_TESTED",
    }
    if case_id == "interaction":
        assert report["continuation_segments"] == [
            [0.0, 0.4],
            [0.4, 0.8],
            [0.8, 1.2],
            [1.2, 2.0],
        ]
        assert np.allclose(
            np.asarray(sample_times(case_id)), [0.0, 0.4, 0.5, 0.8, 1.0, 1.2, 2.0]
        )
