"""NFsim must not freeze named time-dependent parameters in reaction rates."""

import pytest

import bionetgen
from bionetgen import _bionetgen_cpp as _cpp


def _write_model(path, rate_expression, include_action=False):
    actions = (
        "begin actions\n"
        "    simulate_nf({t_end=>2,n_steps=>2,seed=>17})\n"
        "end actions\n"
        if include_action
        else ""
    )
    path.write_text(f"""
begin model
begin parameters
    clock_rate time()+1
    k 2*clock_rate
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1000
    B() 0
end seed species
begin observables
    Molecules A_count A()
    Molecules B_count B()
end observables
begin functions
    rate() = k
end functions
begin reaction rules
    R: A() -> B() {rate_expression}
end reaction rules
{actions}
end model
""")


@pytest.mark.parametrize("rate_expression", ["k", "rate()"])
def test_nf_rejects_time_dependent_named_rate_parameters_even_with_xml_fallback(
    tmp_path, monkeypatch, rate_expression
):
    bngl = tmp_path / "time_parameter_rate.bngl"
    _write_model(bngl, rate_expression)
    model = _cpp.parse_file(str(bngl))
    monkeypatch.delenv("BNG_NFSIM_FORCE_XML", raising=False)

    with pytest.raises(RuntimeError, match="time-dependent"):
        _cpp.simulate_nf(model, t_end=2.0, n_steps=2, seed=17, require_direct=True)

    # The compatibility XML path must not turn the same unsupported model
    # into a nominally successful run after direct lowering rejects it.
    monkeypatch.setenv("BNG_NFSIM_ALLOW_XML_FALLBACK", "1")
    with pytest.raises(RuntimeError, match="time-dependent"):
        _cpp.simulate_nf(model, t_end=2.0, n_steps=2, seed=17)

    # An explicit XML-path request must apply the same semantic veto.
    monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
    with pytest.raises(RuntimeError, match="time-dependent"):
        _cpp.simulate_nf(model, t_end=2.0, n_steps=2, seed=17)


@pytest.mark.parametrize("force_xml", [False, True])
def test_nf_action_rejects_timed_named_rate_before_xml_fallback(
    tmp_path, monkeypatch, force_xml
):
    bngl = tmp_path / "time_parameter_rate_action.bngl"
    _write_model(bngl, "k", include_action=True)
    monkeypatch.setenv("BNG_NFSIM_ALLOW_XML_FALLBACK", "1")
    if force_xml:
        monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
    else:
        monkeypatch.delenv("BNG_NFSIM_FORCE_XML", raising=False)

    with pytest.raises(RuntimeError, match="time-dependent"):
        bionetgen.load(str(bngl)).execute()


def test_nf_keeps_direct_time_expression_dynamic(tmp_path):
    bngl = tmp_path / "direct_time_rate.bngl"
    _write_model(bngl, "time()+1")
    model = _cpp.parse_file(str(bngl))

    result = _cpp.simulate_nf(model, t_end=2.0, n_steps=2, seed=17, require_direct=True)

    assert result["construction_path"] == "direct"
    assert result["time"].tolist() == pytest.approx([0.0, 1.0, 2.0])
    # With the increasing direct time() rate, this seeded trajectory is far
    # below the result from freezing its t=0 value at a constant rate.
    assert result["observables"]["A_count"][-1] < 100
