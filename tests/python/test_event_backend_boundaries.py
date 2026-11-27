"""Admitting native CVODE events must not silently broaden other consumers."""

import pytest

from _extdep import require_extension

cpp = require_extension()


@pytest.fixture
def event_model(tmp_path):
    source = tmp_path / "event.bngl"
    source.write_text("""begin model
begin parameters
 k 1
end parameters
begin molecule types
 A()
end molecule types
begin seed species
 A() 10
end seed species
begin observables
 Molecules X A()
end observables
begin reaction rules
 A() -> 0 k
end reaction rules
begin bng3_events version 1
 event "reset"
 trigger: X <= 5
 initial_value: false
 persistent: true
 use_values_from_trigger_time: true
 assignment: X = 10
 end event
end bng3_events
end model
""")
    model = cpp.parse_file(str(source))
    return model, cpp.generate_network(model)


@pytest.mark.parametrize(
    "writer", ["write_xml", "write_net", "write_matlab", "write_latex"]
)
def test_export_refuses_before_creating_eventless_file(event_model, tmp_path, writer):
    model, network = event_model
    destination = tmp_path / "output"
    arguments = (
        (model, str(destination))
        if writer == "write_xml"
        else (model, network, str(destination))
    )
    with pytest.raises(RuntimeError, match="event"):
        getattr(cpp.io, writer)(*arguments)
    assert not destination.exists()


def test_sbml_export_preserves_the_native_event(event_model, tmp_path):
    model, network = event_model
    destination = tmp_path / "output.xml"
    cpp.io.write_sbml(model, network, str(destination))
    text = destination.read_text()
    assert "<listOfEvents>" in text
    # The trigger and the assignment name the network species that the
    # observable covers, so a re-imported document keeps the event.
    assert "<ci> S1 </ci>" in text
    assert 'eventAssignment variable="S1"' in text


@pytest.mark.parametrize("consumer", ["jax_ode_flatten", "jax_ssa_flatten"])
def test_flattening_cannot_drop_events(event_model, consumer):
    with pytest.raises(RuntimeError, match="event"):
        getattr(cpp, consumer)(*event_model)


def test_cpu_batch_ssa_executes_native_events(event_model):
    model, network = event_model
    result = cpp.simulate_batch_ssa_cpu(
        model,
        network,
        t_end=3.0,
        n_steps=6,
        batch_size=8,
        base_seed=42,
    )
    # Without the reset event (X <= 5 -> X = 10), A() -> 0 with k=1 decays
    # from 10 toward ~0.5 by t=3. With native event execution, X resets back to
    # 10 whenever it hits 5, so every mean and final trajectory value stays > 5.
    assert all(val > 5.0 for val in result["observable_means"]["X"])
    x_idx = result["observable_names"].index("X")
    assert all(val > 5.0 for val in result["final_observables"][:, x_idx])


def test_bngsim_capability_accepts_supported_and_refuses_unsupported_events(
    event_model, tmp_path
):
    check = cpp.check_bngsim_lowering(*event_model)
    assert check["supported"]
    assert check["blockers"] == []

    distrib_source = tmp_path / "event_distrib.bngl"
    distrib_source.write_text("""begin model
begin parameters
 k 1
end parameters
begin molecule types
 A()
end molecule types
begin seed species
 A() 10
end seed species
begin observables
 Molecules X A()
end observables
begin reaction rules
 A() -> 0 k
end reaction rules
begin bng3_events version 1
 event "draw"
 trigger: time >= 1
 initial_value: false
 persistent: true
 use_values_from_trigger_time: true
 assignment: X = distrib_uniform(1, 5)
 end event
end bng3_events
end model
""")
    distrib_model = cpp.parse_file(str(distrib_source))
    distrib_network = cpp.generate_network(distrib_model)
    distrib_check = cpp.check_bngsim_lowering(distrib_model, distrib_network)
    assert not distrib_check["supported"]
    assert any("distrib" in message for message in distrib_check["blockers"])


def test_structural_bngir_snapshot_cannot_discard_events(event_model):
    with pytest.raises(RuntimeError, match="event"):
        cpp._compiled_snapshot(event_model[0])
