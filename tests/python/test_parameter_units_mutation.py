"""Parameter updates retain physical unit metadata used by compilation."""

import bionetgen
import pytest
from bionetgen.model import _cpp


def _physical_rate_model(rate):
    return f"""
begin model
begin units
    timeunits second
    substanceUnits item
end units
begin parameters
    k = {rate} [minute^-1]
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10 [item]
end seed species
begin reaction rules
    A() -> 0 k
end reaction rules
end model
"""


def test_set_parameter_preserves_physical_rate_unit_in_snapshot(tmp_path):
    bngl = tmp_path / "physical_rate.bngl"
    bngl.write_text(_physical_rate_model("0.02"))
    model = bionetgen.load(str(bngl))

    initial = _cpp._compiled_snapshot(model._model)
    initial_parameter = next(p for p in initial["parameters"] if p["name"] == "k")
    assert initial_parameter["unit"] == "minute^-1"
    assert initial_parameter["normalized_value"] == pytest.approx(0.02 / 60.0)

    model.set_parameter("k", 0.04)

    assert model.get_parameter("k").unit == "minute^-1"
    updated = _cpp._compiled_snapshot(model._model)
    updated_parameter = next(p for p in updated["parameters"] if p["name"] == "k")
    assert updated_parameter["unit"] == "minute^-1"
    assert updated_parameter["constant_value"] == pytest.approx(0.04)
    assert updated_parameter["normalized_value"] == pytest.approx(0.04 / 60.0)

    fresh_bngl = tmp_path / "fresh_physical_rate.bngl"
    fresh_bngl.write_text(_physical_rate_model("0.04"))
    fresh = _cpp._compiled_snapshot(bionetgen.load(str(fresh_bngl))._model)
    fresh_parameter = next(p for p in fresh["parameters"] if p["name"] == "k")
    assert updated_parameter["normalized_value"] == pytest.approx(
        fresh_parameter["normalized_value"]
    )
    assert updated["seeds"] == fresh["seeds"]
