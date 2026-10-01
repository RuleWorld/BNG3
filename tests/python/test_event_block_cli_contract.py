"""CLI/engine contract for the BNG3 ``bng3_events`` extension block.

ADR 0004 action item 5 requires that a model carrying a versioned
``bng3_events`` block round-trips through the BNGL parser/writer *and* that
attempting to execute such a model through the normal CLI/engine path fails
with an explicit rejection diagnostic rather than a silent approximation.

These tests drive the real in-process C++ engine (``bionetgen._bionetgen_cpp``),
the same module ``bionetgen.load(...).execute()`` and the ``bng3`` CLI use.
"""

import pytest

from _extdep import require_extension

_cpp = require_extension()

import bionetgen

# Verbatim from cpp/ast/Model.hpp: kUnsupportedEventExecutionMessage.
UNSUPPORTED_EVENT_EXECUTION_MESSAGE = (
    "BNG3 event execution is not implemented; bng3_events models cannot be simulated"
)

_EVENT_BLOCK = """begin bng3_events version 1
  event "reset_x"
    trigger: X > 5
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: X = 0
  end event
end bng3_events
"""

_MODEL_BODY = """begin model
begin parameters
    k 0.2
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
{rules}\
{events}
end model
"""

_RULES = """begin reaction rules
    X() -> 0 k
end reaction rules
"""


def _write_model(path, events, rules=_RULES):
    # The rules block is optional: BnglWriter drops the rate of a pure
    # degradation rule, so round-trip assertions use a rules-free model and
    # only the execution tests carry rules.
    path.write_text(_MODEL_BODY.format(events=events, rules=rules))
    return str(path)


def test_event_block_survives_bngl_round_trip(tmp_path):
    source = _write_model(tmp_path / "roundtrip.bngl", _EVENT_BLOCK, rules="")

    model = bionetgen.load(source)
    written = tmp_path / "written.bngl"
    model.write_bngl(str(written))

    text = written.read_text()
    assert "begin bng3_events version 1" in text
    assert "end bng3_events" in text

    # Re-reading the written file must preserve the event system rather than
    # silently drop it, and writing it again must be a fixed point.
    reparsed = bionetgen.load(str(written))
    assert reparsed.to_bngl() == model.to_bngl()


def test_event_model_is_rejected_by_execute_before_any_output(tmp_path):
    source = tmp_path / "rejected.bngl"
    _write_model(
        source,
        _EVENT_BLOCK + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>10, n_steps=>10})
end actions
""",
    )

    model = bionetgen.load(str(source))

    with pytest.raises(RuntimeError) as excinfo:
        model.execute()

    message = str(excinfo.value)
    assert "bng3_events" in message
    assert "event execution is not implemented" in message
    # Fail closed before writing any simulation output.
    assert not list(tmp_path.glob("*.gdat"))
    assert not list(tmp_path.glob("*.cdat"))
    assert not list(tmp_path.glob("*.net"))


def test_event_model_simulation_action_rejects_with_the_declared_message(tmp_path):
    # generate_network() also refuses a bng3_events model, so pre-build the
    # network from the same model without the event block and read it back.
    # This isolates the simulation path, which is the one the ADR names.
    base = _write_model(
        tmp_path / "base.bngl",
        """
begin actions
    generate_network({overwrite=>1})
end actions
""",
    )
    bionetgen.load(base).execute()
    assert (tmp_path / "base.net").exists()

    source = tmp_path / "simulate_rejected.bngl"
    _write_model(
        source,
        _EVENT_BLOCK + """
begin actions
    readNetwork({file=>"base.net"})
    simulate({method=>"ode", t_end=>10, n_steps=>10})
end actions
""",
    )

    model = bionetgen.load(str(source))

    with pytest.raises(RuntimeError) as excinfo:
        model.execute()

    assert str(excinfo.value) == UNSUPPORTED_EVENT_EXECUTION_MESSAGE


@pytest.mark.parametrize(
    "method", ["simulate_ode", "simulate_ssa", "simulate_pla", "simulate_psa"]
)
def test_every_engine_binding_rejects_event_models(tmp_path, method):
    base = _cpp.parse_file(_write_model(tmp_path / "net_source.bngl", ""))
    network = _cpp.generate_network(base, 100)

    event_path = _write_model(tmp_path / "event.bngl", _EVENT_BLOCK)
    event_model = _cpp.parse_file(event_path)

    with pytest.raises(RuntimeError) as excinfo:
        getattr(_cpp, method)(event_model, network, 10.0, 10)

    assert str(excinfo.value) == UNSUPPORTED_EVENT_EXECUTION_MESSAGE


def _cli_text(result):
    """All text a CLI user can see, whether or not Click captured the stream."""
    parts = [result.output or ""]
    if result.exception is not None:
        parts.append(f"{type(result.exception).__name__}: {result.exception}")
    return "\n".join(parts)


def test_cli_execute_command_rejects_an_event_model(tmp_path):
    from click.testing import CliRunner

    from bionetgen import cli

    source = _write_model(
        tmp_path / "cli_execute.bngl",
        _EVENT_BLOCK + """
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>10, n_steps=>10})
end actions
""",
    )
    result = CliRunner().invoke(cli.execute, [source])

    # The CLI must fail loudly rather than report a successful run.
    assert result.exit_code != 0
    assert "bng3_events" in _cli_text(result)
    assert "event execution is not implemented" in _cli_text(result)


def test_cli_run_command_rejects_an_event_model(tmp_path):
    from click.testing import CliRunner

    from bionetgen import cli

    source = _write_model(tmp_path / "cli_run.bngl", _EVENT_BLOCK)
    result = CliRunner().invoke(cli.run, [source, "--t-end", "10", "--n-steps", "10"])

    assert result.exit_code != 0
    assert "event execution is not implemented" in _cli_text(result)
