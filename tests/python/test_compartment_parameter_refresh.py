"""Parameter and action mutations must refresh parameter-backed volumes."""

import bionetgen
import pytest
from bionetgen import _bionetgen_cpp as _cpp


def _volume_model(vbase="1", vcell="2 * Vbase", *, actions=""):
    return f"""begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin parameters
    Vbase = {vbase} [fL]
    Vcell = {vcell} [fL]
    k = 1e-9 [M/second]
  end parameters
  begin compartments
    cell 3 Vcell [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell 0
  end seed species
  begin observables
    Molecules A_count A()@cell
  end observables
  begin reaction rules
    source: 0 -> A()@cell k
  end reaction rules
{actions}end model
"""


def _compartment_snapshot(model):
    return _cpp._compiled_snapshot(model._model)["compartments"][0]


def _assert_volume_matches(actual_model, expected_model, value):
    actual = _compartment_snapshot(actual_model)
    expected = _compartment_snapshot(expected_model)
    assert actual["volume"] == pytest.approx(value)
    assert actual["normalized_volume"] == pytest.approx(expected["normalized_volume"])
    assert actual["unit"] == expected["unit"] == "fL"


def test_parameter_updates_refresh_direct_and_transitive_volume_expressions(
    tmp_path,
):
    source = tmp_path / "parameter_volume.bngl"
    source.write_text(_volume_model())
    model = bionetgen.load(str(source))

    model.set_parameter("Vbase", 1.5)
    fresh_transitive_path = tmp_path / "fresh_transitive.bngl"
    fresh_transitive_path.write_text(_volume_model(vbase="1.5"))
    fresh_transitive = bionetgen.load(str(fresh_transitive_path))
    _assert_volume_matches(model, fresh_transitive, 3.0)

    # Keep the source expression in BNGL output so a later parameter update
    # still changes the volume after serialization. (This fixture's separate
    # zero-order rule has an unrelated current writer formatting limitation.)
    assert "cell 3 Vcell [fL]" in model.to_bngl()

    model.set_parameter("Vcell", 4.0)
    fresh_direct_path = tmp_path / "fresh_direct.bngl"
    fresh_direct_path.write_text(_volume_model(vbase="1.5", vcell="4"))
    fresh_direct = bionetgen.load(str(fresh_direct_path))
    _assert_volume_matches(model, fresh_direct, 4.0)


def test_physical_zero_order_nfsim_rate_matches_fresh_volume_after_override(
    tmp_path,
):
    source = tmp_path / "mutable_physical_volume.bngl"
    source.write_text(_volume_model(vcell="1"))
    model = bionetgen.load(str(source))
    model.set_parameter("Vcell", 2.0)

    fresh_path = tmp_path / "fresh_physical_volume.bngl"
    fresh_path.write_text(_volume_model(vcell="2"))
    fresh = bionetgen.load(str(fresh_path))

    mutated_result = model.simulate(method="nf", t_end=100.0, n_steps=1, seed=7)
    fresh_result = fresh.simulate(method="nf", t_end=100.0, n_steps=1, seed=7)

    assert mutated_result.construction_path == "direct"
    assert mutated_result.time.tolist() == fresh_result.time.tolist() == [0.0, 100.0]
    assert mutated_result.observables["A_count"].tolist() == (
        fresh_result.observables["A_count"].tolist()
    )


def test_nonfinite_parameter_backed_volume_is_refused_by_physical_nfsim(tmp_path):
    source = tmp_path / "nonfinite_parameter_volume.bngl"
    source.write_text("""begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin parameters
    divisor = 1
    k = 1e-9 [M/second]
  end parameters
  begin compartments
    cell 3 1 / divisor [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell 0
  end seed species
  begin reaction rules
    source: 0 -> A()@cell k
  end reaction rules
end model
""")
    model = bionetgen.load(str(source))

    model.set_parameter("divisor", 0.0)

    with pytest.raises(RuntimeError, match="positive static declared 3D volume"):
        model.simulate(method="nf", t_end=100.0, n_steps=1, seed=7)


def test_failed_volume_refresh_keeps_parameter_and_compartment_consistent(tmp_path):
    source = tmp_path / "invalid_factorial_volume.bngl"
    source.write_text("""begin model
  begin parameters
    n = 2
  end parameters
  begin compartments
    cell 3 factorial(n) [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell 0
  end seed species
end model
""")
    model = bionetgen.load(str(source))
    assert model._model.compartments[0].volume == pytest.approx(2.0)

    with pytest.raises(ValueError, match="factorial.*non-negative integer"):
        model.set_parameter("n", -1.0)

    assert model.get_parameter("n").value == pytest.approx(2.0)
    assert model._model.compartments[0].volume == pytest.approx(2.0)


def test_failed_setparameter_action_keeps_parameter_and_compartment_consistent(
    tmp_path,
):
    source = tmp_path / "invalid_factorial_action.bngl"
    source.write_text("""begin model
  begin parameters
    n = 2
  end parameters
  begin compartments
    cell 3 factorial(n) [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell 0
  end seed species
  begin actions
    setParameter("n", -1)
  end actions
end model
""")
    model = bionetgen.load(str(source))

    with pytest.raises(ValueError, match="factorial.*non-negative integer"):
        model.execute()

    assert model.get_parameter("n").value == pytest.approx(2.0)
    assert model._model.compartments[0].volume == pytest.approx(2.0)


@pytest.mark.parametrize("action", ["include_model", "readFile"])
def test_failed_include_merge_keeps_parameter_and_compartment_consistent(
    tmp_path, action
):
    included = tmp_path / "invalid_override.bngl"
    included.write_text("""begin model
  begin parameters
    n = -1
  end parameters
end model
""")
    source = tmp_path / "invalid_include.bngl"
    read_action = (
        f'include_model({{file=>"{included}"}})'
        if action == "include_model"
        else f'readFile({{file=>"{included}",atomize=>0}})'
    )
    source.write_text(f"""begin model
  begin parameters
    n = 2
  end parameters
  begin compartments
    cell 3 factorial(n) [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell 0
  end seed species
  begin actions
    {read_action}
  end actions
end model
""")
    model = bionetgen.load(str(source))

    with pytest.raises(ValueError, match="factorial.*non-negative integer"):
        model.execute()

    assert model.get_parameter("n").value == pytest.approx(2.0)
    assert model._model.compartments[0].volume == pytest.approx(2.0)


def test_setvolume_action_overrides_dynamic_expression_for_later_parameter_updates(
    tmp_path,
):
    actions = """  begin actions
    setVolume({target=>"cell",value=>2})
    setParameter("Vbase",10)
  end actions
"""
    source = tmp_path / "manual_volume_override.bngl"
    source.write_text(
        _volume_model(
            vbase="1",
            vcell="Vbase + 0.1 * time()",
            actions=actions,
        )
    )
    model = bionetgen.load(str(source))
    model.execute()
    assert model._model.compartments[0].volume == pytest.approx(2.0)
    assert "cell 3 2 [fL]" in model.to_bngl()

    fresh_path = tmp_path / "fresh_manual_volume.bngl"
    fresh_path.write_text(_volume_model(vbase="10", vcell="2"))
    fresh = bionetgen.load(str(fresh_path))

    manual_result = model.simulate(method="nf", t_end=100.0, n_steps=1, seed=7)
    fresh_result = fresh.simulate(method="nf", t_end=100.0, n_steps=1, seed=7)
    assert manual_result.construction_path == "direct"
    assert manual_result.observables["A_count"].tolist() == (
        fresh_result.observables["A_count"].tolist()
    )
