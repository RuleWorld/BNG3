"""Independent BNGIR v0.2 fixture contracts (valid/invalid JSON cases)."""

import json
from pathlib import Path

import jsonschema
import pytest

import bionetgen

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "bngir" / "adversarial"
SCHEMA = json.loads(
    (ROOT / "provenance" / "schemas" / "bngir-0.2.schema.json").read_text(
        encoding="utf-8"
    )
)


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_adversarial_valid_fixture_roundtrips_and_executes_native():
    doc = _load("valid_decay.json")
    jsonschema.validate(doc, SCHEMA)
    restored = bionetgen.from_bngir(doc)
    native = bionetgen.from_bngir(doc, native=True)
    assert bionetgen.semantic_equal(restored, native, version="0.2")
    # Independent analytic control for A -> B, k=0.1, A(0)=10.
    result = native.simulate(method="ode", t_end=2.0, n_steps=10)
    assert abs(float(result.concentrations[0][0]) - 10.0) < 1e-9
    assert abs(float(result.concentrations[0][1]) - 0.0) < 1e-9
    assert abs(float(result.concentrations[-1][0]) - 10.0 * 0.8187307530779818) < 1e-6
    assert abs(float(result.concentrations[-1][1]) - 10.0 * (1 - 0.8187307530779818)) < 1e-6


@pytest.mark.parametrize(
    "name,expect_schema_failure",
    [
        ("invalid_duplicate_parameter_id.json", False),
        ("invalid_parameter_ref.json", False),
        ("invalid_seed_type_ref.json", False),
        ("invalid_observable_relation.json", True),
    ],
)
def test_adversarial_invalid_fixtures_rejected(name, expect_schema_failure):
    doc = _load(name)
    if expect_schema_failure:
        with pytest.raises(Exception):
            jsonschema.validate(doc, SCHEMA)
    else:
        jsonschema.validate(doc, SCHEMA)
    # Invalid documents must not be accepted as valid reconstructions.
    with pytest.raises(Exception):
        bionetgen.from_bngir(doc)
    with pytest.raises(Exception):
        bionetgen.from_bngir(doc, native=True)
