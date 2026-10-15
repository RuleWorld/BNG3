"""Simulation orchestration must preserve stage boundaries and oracle identity."""

from argparse import Namespace
from pathlib import Path

from tests.validation.simulation_contract import net_reload_text, run_simulation


def arguments():
    return Namespace(
        bng_cpp=Path("/missing/subject"),
        case_timeout=1,
        simulation_end=1.0,
        simulation_steps=10,
    )


def test_network_failure_blocks_simulation_without_relabeling_it_as_a_solver_bug(
    tmp_path,
):
    rows = run_simulation(
        "x",
        tmp_path,
        None,
        arguments(),
        {},
        [{"id": "x:network:initial-amounts", "status": "FAIL"}],
    )
    assert {r["check"] for r in rows} == {"cdat", "gdat"}
    assert all(r["status"] == "NOT_TESTED" for r in rows)
    assert all(r["blocked_by"] == ["x:network:initial-amounts"] for r in rows)
    assert not (tmp_path / "simulation").exists()


def test_missing_verified_numeric_oracle_cannot_fallback_to_subject(tmp_path):
    rows = run_simulation("x", tmp_path, {"script": "fake"}, arguments(), {}, [])
    assert rows[0]["status"] == "HARNESS_ERROR"
    assert rows[0]["stage"] == "simulation-preflight"
    assert "independently built run_network" in rows[0]["detail"]


def test_diagnostic_action_is_inside_existing_action_block():
    from tests.validation.simulation_contract import simulation_text

    text = simulation_text(
        "begin model\nend model\nbegin actions\n generate_network()\nend actions\n",
        arguments(),
    )
    assert (
        text.index("generate_network()")
        < text.index("simulate_ode(")
        < text.index("end actions")
    )
    assert text.count("end actions") == 1


def test_net_reload_protocol_preloads_only_parameters_and_compartments():
    source = """
begin model
begin parameters
    k 0.1
end parameters
begin compartments
    cell 3 1
end compartments
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin reaction rules
    A() -> 0 k
end reaction rules
end model
begin actions
    generate_network({overwrite=>1})
end actions
"""

    text = net_reload_text(source, arguments())

    assert "begin parameters\n    k 0.1\nend parameters" in text
    assert "begin compartments\n    cell 3 1\nend compartments" in text
    assert "begin molecule types" not in text
    assert "begin seed species" not in text
    assert "begin reaction rules" not in text
    assert "generate_network" not in text
    assert 'readFile({file=>"input.net"})' in text
    assert 'simulate_ode({netfile=>"input.net"' in text
    assert text.index('readFile({file=>"input.net"})') < text.index("simulate_ode(")


def test_blocked_routes_have_distinct_case_ids(tmp_path):
    blocker = [{"id": "x:network:rates", "status": "FAIL"}]
    a = run_simulation("x", tmp_path, None, arguments(), {}, blocker, route="bngl")
    b = run_simulation(
        "x", tmp_path, None, arguments(), {}, blocker, route="net-reload"
    )
    assert not {r["id"] for r in a} & {r["id"] for r in b}
