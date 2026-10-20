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


@pytest.mark.parametrize(
    "consumer", ["jax_ode_flatten", "jax_ssa_flatten", "simulate_batch_ssa_cpu"]
)
def test_flattening_cannot_drop_events(event_model, consumer):
    with pytest.raises(RuntimeError, match="event"):
        getattr(cpp, consumer)(*event_model)


def test_bngsim_capability_refuses_events(event_model):
    check = cpp.check_bngsim_lowering(*event_model)
    assert not check["supported"]
    assert any("event" in message for message in check["blockers"])


def test_structural_bngir_snapshot_cannot_discard_events(event_model):
    with pytest.raises(RuntimeError, match="event"):
        cpp._compiled_snapshot(event_model[0])
