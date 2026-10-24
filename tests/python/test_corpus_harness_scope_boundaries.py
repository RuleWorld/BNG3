"""The curated BioModels gate must say when it cannot measure a record.

Two boundaries of the measurement are pinned here.

*An observable that has no value.*  A model may define an observable
that is undefined at the initial point -- the logarithm of a quantity that is
zero there, a ratio of two quantities that are both zero.  Both engines then
report the *same* undefined value for the model being compared, so the record
cannot be compared pointwise at that value.  This does not establish that a
translated model reproduces its original SBML source.  The gate records a *not
comparable* verdict that names the undefined point.

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

CUSTOM_UNIT_SPECIES = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="unit_oracle" substanceUnits="millimole" volumeUnits="microliter"
    timeUnits="second">
    <listOfUnitDefinitions>
      <unitDefinition id="millimole"><listOfUnits>
        <unit kind="mole" scale="-3"/>
      </listOfUnits></unitDefinition>
      <unitDefinition id="microliter"><listOfUnits>
        <unit kind="liter" scale="-6"/>
      </listOfUnits></unitDefinition>
    </listOfUnitDefinitions>
    <listOfCompartments>
      <compartment id="cell" size="2" units="microliter"
        spatialDimensions="3" constant="true"/>
      <compartment id="point" size="1" spatialDimensions="0" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialAmount="2"
        hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="cell" initialConcentration="1"
        hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
      <species id="C" compartment="point" initialAmount="0.5"
        hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
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


def test_source_comparison_uses_original_sbml_and_species_quantity_units(monkeypatch):
    """The source oracle receives source SBML and amount/concentration selections."""

    import numpy as np
    from types import SimpleNamespace

    harness = _harness()
    source_sbml = "<sbml id='original'/>"
    rr_calls = []

    class FakeRoadRunner:
        integrator = SimpleNamespace(hasValue=lambda _name: False)

        def __init__(self, model_source):
            assert model_source == source_sbml
            self.timeCourseSelections = []

        def simulate(self, start, end, points):
            rr_calls.append((self.timeCourseSelections, start, end, points))
            return np.array([[0.0, 2.0, 1.0], [60.0, 4.0, 2.0]])

    monkeypatch.setitem(
        sys.modules,
        "roadrunner",
        SimpleNamespace(RoadRunner=FakeRoadRunner, __version__="test"),
    )

    class FakeCpp:
        def parse_string(self, bngl):
            import re

            aliases = re.findall(r"^\s*(SSTSREF_[A-Za-z0-9_]+)\(\) =", bngl, re.M)
            return SimpleNamespace(aliases=aliases)

    class FakeModel:
        def __init__(self, model):
            self.model = model

        def simulate(self, **_kwargs):
            values = [[2.0, 4.0], [1.0, 2.0]]
            return SimpleNamespace(
                time=np.array([0.0, 60.0]),
                observables={},
                functions=dict(zip(self.model.aliases, values)),
            )

    source_model = SimpleNamespace(
        species={
            "amount_species": SimpleNamespace(
                has_only_substance_units=True,
                compartment="cell",
                substance_units="",
            ),
            "concentration_species": SimpleNamespace(
                has_only_substance_units=False,
                compartment="cell",
                substance_units="",
            ),
        },
        compartments={
            "cell": SimpleNamespace(spatial_dimensions=3, units="tiny_liter")
        },
        parameters={},
        reactions={},
        rules=[],
        events=[],
        initial_assignments=[],
        function_definitions={},
        time_units="minute",
        substance_units="millimole",
        volume_units="tiny_liter",
        area_units="",
        length_units="",
        unit_definitions={
            "millimole": [{"scale": -3}],
            "tiny_liter": [{"scale": -15}],
        },
    )
    result = harness._simulate_source_and_compare(
        FakeCpp(),
        "begin model\nend model\n",
        FakeModel,
        source_sbml,
        source_model,
        {
            "amount_species": "amount_species",
            "concentration_species": "concentration_species",
        },
        t_end=60.0,
        n_steps=1,
        rtol=1e-7,
        atol=1e-12,
        model_id="source_units",
    )

    assert result["passed"] is True
    assert result["comparison_scope"] == (
        "original_source_sbml_species_output_fidelity"
    )
    assert result["source_time_units"] == "minute"
    assert result["source_species_targets"]["amount_species"] == (
        "(amount_species_amt) * 1000"
    )
    assert result["source_species_targets"]["concentration_species"] == (
        "(concentration_species_amt / __compartment_cell__) * 0.000000000001"
    )
    assert result["source_species_normalization"]["amount_species"] == {
        "quantity_kind": "amount",
        "substance_factor": 0.001,
        "compartment_factor": 1e-15,
        "normalized_to_source_factor": 1000.0,
    }
    assert result["source_species_normalization"]["concentration_species"] == {
        "quantity_kind": "concentration",
        "substance_factor": 0.001,
        "compartment_factor": 1e-15,
        "normalized_to_source_factor": 1e-12,
    }
    assert rr_calls == [
        (
            ["time", "amount_species", "[concentration_species]"],
            0.0,
            60.0,
            2,
        )
    ]


def test_source_comparison_executes_normalized_amount_and_concentration_targets():
    """Exercise generated aliases against real RoadRunner and native BNG3."""

    pytest.importorskip("roadrunner")
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    from bionetgen import BioNetGenModel
    from bionetgen.atomizer.modern import Atomizer, SBMLParser

    harness = _harness()
    parsed = SBMLParser().parse(CUSTOM_UNIT_SPECIES)
    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=10, n_steps=10).atomize(
        CUSTOM_UNIT_SPECIES
    )
    assert atomized.success, atomized.error

    result = harness._simulate_source_and_compare(
        cpp,
        atomized.bngl,
        BioNetGenModel,
        CUSTOM_UNIT_SPECIES,
        parsed,
        dict(atomized.observable_map),
        t_end=10.0,
        n_steps=10,
        rtol=1e-7,
        atol=1e-12,
        model_id="unit_oracle",
    )

    assert result["passed"] is True, result.get("error")
    assert result["source_species_roadrunner_selections"] == {
        "A": "A",
        "B": "[B]",
        "C": "C",
    }
    assert (
        result["source_species_normalization"]["A"]["normalized_to_source_factor"]
        == 1000.0
    )
    assert (
        result["source_species_normalization"]["B"]["normalized_to_source_factor"]
        == 0.001
    )
    assert result["source_species_normalization"]["C"]["quantity_kind"] == "amount"
    assert all(
        item["max_abs_difference"] < 1e-12 for item in result["observables"].values()
    )


def test_source_comparison_fails_on_original_species_mismatch():
    """A source initial amount change remains visible after normalization."""

    pytest.importorskip("roadrunner")
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    from bionetgen import BioNetGenModel
    from bionetgen.atomizer.modern import Atomizer, SBMLParser

    harness = _harness()
    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=10, n_steps=10).atomize(
        CUSTOM_UNIT_SPECIES
    )
    assert atomized.success, atomized.error
    altered_source = CUSTOM_UNIT_SPECIES.replace(
        'initialAmount="2"', 'initialAmount="2.2"'
    )
    altered_model = SBMLParser().parse(altered_source)

    result = harness._simulate_source_and_compare(
        cpp,
        atomized.bngl,
        BioNetGenModel,
        altered_source,
        altered_model,
        dict(atomized.observable_map),
        t_end=10.0,
        n_steps=10,
        rtol=1e-7,
        atol=1e-12,
        model_id="source_mismatch",
    )

    assert result["passed"] is False
    assert result["failed_observables"] == ["A"]


def test_source_unit_factors_follow_atomizer_normalization_boundaries():
    """Use the parser's scaling routine for defaults and spatial dimensions."""

    from types import SimpleNamespace

    harness = _harness()

    def model(*, defaults, dimension, substance_units=""):
        compartment = SimpleNamespace(size=1.0, spatial_dimensions=dimension, units="")
        species = SimpleNamespace(compartment="cell", substance_units=substance_units)
        return SimpleNamespace(
            species={"S": species},
            compartments={"cell": compartment},
            parameters={},
            reactions={},
            rules=[],
            events=[],
            initial_assignments=[],
            function_definitions={},
            unit_definitions={
                "substance": [{"scale": -3}],
                "volume": [{"scale": -6}],
                "area": [{"scale": -4}],
                "length": [{"scale": -2}],
            },
            substance_units="substance" if defaults else "",
            volume_units="volume" if defaults else "",
            area_units="area" if defaults else "",
            length_units="length" if defaults else "",
        )

    # apply_unit_scaling intentionally leaves all source numeric values intact
    # when both model defaults are absent, including explicit local units.
    assert harness._source_species_unit_factors(
        model(defaults=False, dimension=2, substance_units="substance")
    ) == {"S": (1.0, 1.0)}

    expected_compartment_factors = {
        0: 1e-6,  # The Atomizer treats spatialDimensions=0 as its 3D default.
        1: 1e-2,
        2: 1e-4,
        3: 1e-6,
    }
    for dimension, compartment_factor in expected_compartment_factors.items():
        assert harness._source_species_unit_factors(
            model(defaults=True, dimension=dimension)
        ) == {"S": (1e-3, compartment_factor)}


@pytest.mark.parametrize(
    ("written", "source", "expected"),
    [
        (None, {"failed_observables": ["S"]}, "failed"),
        (
            {"not_comparable": {"oracle": "load"}},
            {"failed_observables": ["S"]},
            "failed",
        ),
        (
            {"not_comparable": {"undefined": "at zero"}},
            {"failed_observables": ["S"]},
            "failed",
        ),
        (
            {"failed_observables": ["written"]},
            {"not_comparable": {"mapping": "missing"}},
            "failed",
        ),
        (
            {"passed": False, "not_comparable": {"oracle": "load"}},
            {"harness_error": "bad alias"},
            "harness_error",
        ),
        (
            {"passed": True},
            {"not_comparable": {"mapping": "missing"}},
            "not_comparable",
        ),
        ({"passed": True}, {"passed": True}, "passed"),
    ],
)
def test_source_and_written_comparison_verdict_priority(written, source, expected):
    """A measured semantic mismatch outranks written or source measurement gaps."""

    harness = _harness()
    verdict, _reason = harness._comparison_verdict(written, source)
    assert verdict == expected


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
