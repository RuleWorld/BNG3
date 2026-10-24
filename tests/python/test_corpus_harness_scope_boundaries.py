"""The curated BioModels gate must say when it cannot measure a record.

Two boundaries of the measurement are pinned here.

*An observable that has no value.*  A source model may define an observable
that is undefined at the initial point -- the logarithm of a quantity that is
zero there, a ratio of two quantities that are both zero.  Both engines then
report the *same* undefined value, so the record reproduces its source
exactly; what the record cannot do is be compared pointwise.  The gate used
to record such a record as a failure, which claimed a disagreement that does
not exist.  It now records a *not comparable* verdict that names the
undefined point.

*An explicit refusal.*  The Atomizer refuses some constructs on purpose, with
a message that names the construct.  The gate has to recognise such a
refusal as a gap rather than as a failure of the gate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
HARNESS_PATH = REPO / "scripts" / "ci" / "validate_published_biomodels.py"
INVENTORY_PATH = REPO / "scripts" / "ci" / "curated_biomodels_corpus_inventory.py"

# A species that grows from zero, so the logarithm of its amount is undefined
# at t = 0 and defined everywhere else.
UNDEFINED_AT_THE_INITIAL_POINT = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="undefined_at_zero">
    <listOfCompartments>
      <compartment id="c" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true"
        boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfRules>
      <rateRule variable="S">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn> 1 </cn></math>
      </rateRule>
      <assignmentRule variable="obs">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><log/><ci> S </ci></apply>
        </math>
      </assignmentRule>
    </listOfRules>
  </model>
</sbml>
"""

# A compartment whose size an event changes, with a rate rule on a
# concentration-valued species: the Atomizer refuses this on purpose.
EVENT_DRIVEN_COMPARTMENT = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="event_driven_compartment">
    <listOfCompartments>
      <compartment id="c" spatialDimensions="3" size="1" constant="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="c" initialAmount="1" hasOnlySubstanceUnits="false"
        boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfRules>
      <rateRule variable="S">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn> 1 </cn></math>
      </rateRule>
    </listOfRules>
    <listOfEvents>
      <event id="E">
        <trigger>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <gt/>
              <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time"/>
              <cn> 0 </cn>
            </apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="c">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><ci> c </ci><cn> 3 </cn></apply>
            </math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>
"""


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _harness() -> ModuleType:
    return _load(HARNESS_PATH, "bng3_corpus_harness_under_test")


def _inventory() -> ModuleType:
    return _load(INVENTORY_PATH, "bng3_corpus_inventory_under_test")


def test_an_observable_without_a_value_is_not_a_disagreement(tmp_path):
    """A record whose own observable is undefined at t=0 is not comparable."""

    harness = _harness()
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    from bionetgen import BioNetGenModel

    result = harness._validate_mode(
        UNDEFINED_AT_THE_INITIAL_POINT,
        "BIOMD0000000001",
        False,
        cpp,
        BioNetGenModel,
        tmp_path,
        False,
        1.0,
        10,
        1e-7,
        1e-12,
    )

    assert result["status"] == "not_comparable", result.get("error")
    reason = str(result["not_comparable_reason"])
    assert "undefined at t=0" in reason, reason
    comparison = result["simulation_comparison"]
    assert comparison["passed"] is False
    assert comparison["failed_observables"] == []
    assert "obs" in comparison["not_comparable"]
    # The two engines agree at every point where the observable has a value.
    entry = comparison["observables"]["obs"]
    assert entry["undefined"] is True
    assert entry["undefined_at"][0] == 0.0
    assert entry["max_abs_difference"] <= entry["tolerance"]


def test_a_non_finite_observable_does_not_widen_the_comparison_tolerance():
    """An undefined value must not turn every tolerance into infinity."""

    harness = _harness()
    import numpy as np

    assert harness._finite_max_abs(np.array([1.0, 2.0, 3.0])) == 3.0
    assert harness._finite_max_abs(np.array([1.0, -np.inf])) == 1.0
    assert harness._finite_max_abs(np.array([np.nan, np.inf])) == 0.0


def test_unrelated_large_observable_cannot_mask_small_series_mismatch(monkeypatch):
    """Each observable's numerical floor must use its own magnitude."""

    import numpy as np
    from types import SimpleNamespace

    harness = _harness()

    class FakeRoadRunner:
        integrator = SimpleNamespace(hasValue=lambda _name: False)

        def __init__(self, _path):
            self.timeCourseSelections = []

        def getAssignmentRuleIds(self):
            return {"large", "small"}

        def simulate(self, _start, _end, _points):
            return np.array([[0.0, 1e18, 100.0], [1.0, 1e18, 106.0]])

    monkeypatch.setitem(
        sys.modules,
        "roadrunner",
        SimpleNamespace(RoadRunner=FakeRoadRunner, __version__="test"),
    )

    class FakeModel:
        def simulate(self, **_kwargs):
            return SimpleNamespace(
                time=np.array([0.0, 1.0]),
                observables={"large": [1e18, 1e18], "small": [100.0, 100.0]},
                functions={},
            )

    result = harness._simulate_and_compare(
        object(),
        lambda _model: FakeModel(),
        Path("written.xml"),
        t_end=1.0,
        n_steps=1,
        rtol=1e-7,
        atol=1e-12,
    )

    assert result["passed"] is False
    assert result["failed_observables"] == ["small"]
    assert result["observables"]["large"]["passed"] is True
    assert result["observables"]["small"]["tolerance"] < 1.0


def test_the_gate_records_the_atomizers_refusal_as_a_gap():
    """An explicit refusal names its construct and is not a failure."""

    harness = _harness()
    inventory = _inventory()
    from bionetgen.atomizer.modern import Atomizer

    result = Atomizer(atomize=False, quiet_mode=True).atomize(EVENT_DRIVEN_COMPARTMENT)
    assert result.success is False
    message = str(result.error)
    assert "compartment derivative" in message, message

    assert harness._known_unsupported_error(message) is True
    construct = inventory.corpus_construct(message)
    assert construct == "rules:species-rate-rule-needs-compartment"
    assert inventory.corpus_gap_side(construct) == "atomizer"


def test_the_gate_names_the_construct_of_a_record_it_cannot_measure():
    """A record the gate cannot measure names the construct that stopped it."""

    inventory = _inventory()

    undefined = (
        "the source observable is undefined at t=0: BNG3 and libRoadRunner "
        "report the same undefined value, so a pointwise comparison cannot "
        "measure the record (log_Treg)"
    )
    construct = inventory.corpus_construct(undefined)
    assert construct == "source:undefined-observable"
    assert inventory.corpus_gap_side(construct) == "source"

    oracle = (
        "the independent oracle (libRoadRunner) could not integrate the "
        "written SBML: RuntimeError: CVODE Error: CV_CONV_FAILURE"
    )
    construct = inventory.corpus_construct(oracle)
    assert construct == "harness:oracle-solver-failure"
    assert inventory.corpus_gap_side(construct) == "harness"

    assert "not_comparable" in inventory.CORPUS_EXPECTATION_STATUSES
    assert "source" in inventory.CORPUS_GAP_SIDES
