"""Keep conversion, round-trip and numerical evidence independently visible."""

import numpy as np
import pytest
import sys

from scripts.ci import validate_sbml_test_suite as runner


def test_later_numerical_failure_does_not_erase_successful_conversion():
    record = {
        "status": "failed",
        "generated_network": {"species": 2, "reactions": 1},
        "native_reader": {"success": True},
        "roundtrip_passed": True,
        "simulation_comparison": {"passed": False, "error": "mismatch"},
        "official_conformance": {"status": "failed"},
    }
    stages = runner._stage_summary([record])
    assert stages["conversion"] == {"passed": 1}
    assert stages["roundtrip_structure"] == {"passed": 1}
    assert stages["independent_comparison"] == {"failed": 1}
    assert stages["official_reference"] == {"failed": 1}


def test_declined_conversion_does_not_count_downstream_as_executed():
    record = {
        "status": "unsupported",
        "simulation_comparison": {"passed": False, "skipped": True},
        "official_conformance": {"status": "unsupported"},
    }
    stages = runner._stage_summary([record])
    assert stages["conversion"] == {"unsupported": 1}
    assert stages["roundtrip_structure"] == {"not-tested": 1}
    assert stages["independent_comparison"] == {"not-tested": 1}


def test_roundtrip_failure_is_separate_from_passing_official_reference():
    record = {
        "status": "failed",
        "generated_network": {"species": 2, "reactions": 1},
        "native_reader": {"success": False},
        "official_conformance": {"status": "passed"},
    }
    stages = runner._stage_summary([record])
    assert stages["conversion"] == {"passed": 1}
    assert stages["roundtrip_structure"] == {"failed": 1}
    assert stages["independent_comparison"] == {"not-tested": 1}
    assert stages["official_reference"] == {"passed": 1}


def test_mismatch_samples_preserve_times_values_and_bound():
    times = np.arange(20, dtype=float)
    samples = runner._mismatch_samples(times, times + 1, times, tolerance=0.5)
    assert len(samples) == 16
    assert samples[0] == {"index": 0, "time": 0.0, "bng3": 1.0, "libroadrunner": 0.0}
    assert samples[-1]["index"] == 15


def test_mismatch_samples_distinguish_nonfinite_classes():
    samples = runner._mismatch_samples(
        np.array([0.0, 1.0, 2.0]),
        np.array([np.nan, np.inf, -np.inf]),
        np.array([np.nan, -np.inf, 2.0]),
        tolerance=0.0,
    )
    assert samples == [
        {"index": 1, "time": 1.0, "bng3": "+inf", "libroadrunner": "-inf"},
        {"index": 2, "time": 2.0, "bng3": "-inf", "libroadrunner": 2.0},
    ]


@pytest.mark.parametrize("campaign", ["ssts", "biomodels"])
@pytest.mark.parametrize("compartment", ["cell", "missing"])
def test_sbml_validation_checks_species_compartment_references(campaign, compartment):
    from scripts.ci import validate_published_biomodels

    validate = (
        runner._validate_xml
        if campaign == "ssts"
        else validate_published_biomodels._validate_xml
    )
    try:
        import libsbml  # noqa: F401
    except ImportError:
        # The lightweight harness CI intentionally omits this oracle. Verify
        # the unavailable-dependency path there; the installed SSTS lane runs
        # the reference controls below with real libSBML.
        with pytest.raises(RuntimeError, match="libSBML is required"):
            validate("<sbml/>", "unavailable-validator-control")
        return
    xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
      level="3" version="2"><model id="reference_control">
      <listOfCompartments>
        <compartment id="cell" size="2" constant="true"/>
      </listOfCompartments>
      <listOfSpecies>
        <species id="X" compartment="{compartment}" initialAmount="3"
          hasOnlySubstanceUnits="true" constant="false" boundaryCondition="false"/>
      </listOfSpecies>
    </model></sbml>"""
    if compartment == "missing":
        # SBML L3V2 validation rule 20601: a species' compartment must exist.
        with pytest.raises(RuntimeError, match="20601"):
            validate(xml, "dangling-compartment-control")
    else:
        # Omitted unit declarations produce consistency warnings, not errors.
        assert validate(xml, "valid-reference-control")["passed"] is True


@pytest.mark.parametrize("campaign", ["ssts", "biomodels"])
def test_sbml_validation_cannot_pass_without_its_validator(campaign, monkeypatch):
    from scripts.ci import validate_published_biomodels

    validate = (
        runner._validate_xml
        if campaign == "ssts"
        else validate_published_biomodels._validate_xml
    )
    monkeypatch.setitem(sys.modules, "libsbml", None)
    with pytest.raises(RuntimeError, match="libSBML is required"):
        validate("<not-even-an-sbml-model/>", "missing-validator-control")


@pytest.mark.parametrize("campaign", ["ssts", "biomodels"])
def test_missing_sbml_validator_is_a_harness_failure(campaign, monkeypatch, tmp_path):
    from scripts.ci import validate_published_biomodels

    monkeypatch.setitem(sys.modules, "libsbml", None)
    source = tmp_path / "source.xml"
    source.write_text(
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" '
        'level="3" version="2"><model id="valid_empty_model"/></sbml>'
    )
    options = dict(
        work_dir=tmp_path,
        simulation_t_end=1.0,
        simulation_n_steps=10,
        simulation_rtol=1e-6,
        simulation_atol=1e-8,
    )
    if campaign == "ssts":
        # Reference acquisition is independent of the missing XML validator.
        monkeypatch.setattr(runner, "_read_reference_case", lambda _case: None)
        result = runner._validate_case(
            {
                "category": "semantic",
                "id": "control",
                "version": "l3v2",
                "path": source,
            },
            cpp=None,
            **options,
        )
        assert result["official_conformance"]["status"] == "failed"
    else:
        result = validate_published_biomodels._validate_mode(
            source.read_text(),
            model_id="control",
            mode_atomize=False,
            cpp=None,
            model_type=None,
            ode_smoke=False,
            **options,
        )
    assert result["status"] == "failed"
    assert "libSBML is required" in result["harness_error"]
    assert result["core_passed"] is False


def test_random_event_execution_suppresses_pointwise_failure():
    """A case whose official reference is a random draw stays unsupported.

    regression: semantic/00966 has equally-prioritised competing events whose
    triggers are non-persistent. SBML L3V2 Core 4.12.3 leaves their order to a
    random draw, so the harness declared the official comparison unsupported
    but still let the libRoadRunner pointwise comparison mark the case failed.
    """
    reason = "events Qinc, Rinc share one trigger and one priority; random order"
    record = {"status": "passed"}
    comparison = {
        "passed": False,
        "error": "observable mismatch",
        "observables": {"S": {"mismatch_samples": [{"time": 0.1}]}},
    }
    applied = runner._apply_noncomparable_verdict(
        record, comparison, {"status": "unsupported", "reason": reason}
    )
    assert applied is True
    assert record["status"] == "unsupported"
    assert record["unsupported_reason"] == reason
    assert comparison["skipped"] is True
    assert comparison["skip_reason"] == reason
    # Numeric diagnostics are retained, not erased.
    assert comparison["observables"]["S"]["mismatch_samples"]


def test_random_event_verdict_does_not_mask_ordinary_failure():
    record = {"status": "passed"}
    comparison = {"passed": False, "error": "ordinary mismatch"}
    assert runner._apply_noncomparable_verdict(record, comparison, None) is False
    assert record == {"status": "passed"}
    assert "skipped" not in comparison
