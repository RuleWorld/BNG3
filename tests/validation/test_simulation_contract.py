"""Simulation orchestration must preserve stage boundaries and oracle identity."""

from argparse import Namespace
from pathlib import Path

from tests.validation.simulation_contract import net_reload_context, run_simulation


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


def test_net_reload_context_preloads_only_parameters_and_compartments(tmp_path):
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

    source_path = tmp_path / "source.bngl"
    source_path.write_text(source, encoding="utf-8")
    text = net_reload_context(source_path)

    assert "begin parameters\n    k 0.1\nend parameters" in text
    assert "begin compartments\n    cell 3 1\nend compartments" in text
    assert "begin molecule types" not in text
    assert "begin seed species" not in text
    assert "begin reaction rules" not in text
    assert "generate_network" not in text
    assert "simulate_ode(" not in text


def test_blocked_routes_have_distinct_case_ids(tmp_path):
    blocker = [{"id": "x:network:rates", "status": "FAIL"}]
    a = run_simulation("x", tmp_path, None, arguments(), {}, blocker, route="bngl")
    b = run_simulation(
        "x", tmp_path, None, arguments(), {}, blocker, route="net-reload"
    )
    assert not {r["id"] for r in a} & {r["id"] for r in b}


def test_net_reload_loads_source_context_without_replaying_model_actions(
    tmp_path, monkeypatch
):
    from tests.validation import simulation_contract

    work = tmp_path / "model"
    source_dir = work / "input"
    source_dir.mkdir(parents=True)
    source_dir.joinpath("x.bngl").write_text(
        """begin model
begin parameters
    volume 2
end parameters
begin compartments
    cell 3 volume
end compartments
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
end model
begin actions
    generate_network()
end actions
""",
        encoding="utf-8",
    )
    for side in ("reference", "subject"):
        output_dir = work / side
        output_dir.mkdir()
        output_dir.joinpath("x.net").write_text(
            """begin parameters
    1 volume 2
end parameters
begin species
    1 @cell::A() 1
end species
begin reactions
end reactions
""",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        simulation_contract.campaign, "verify_digest", lambda *args: None
    )
    protocols = []

    def stop_after_recording(command, cwd, timeout, **kwargs):
        protocols.append(Path(command[-1]).read_text(encoding="utf-8"))
        return {"status": "FAIL", "detail": "intentional test stop"}

    monkeypatch.setattr(
        simulation_contract.campaign, "run_command", stop_after_recording
    )
    reference = {
        "interpreter": "perl",
        "script": "BNG2.pl",
        "network_binary": str(tmp_path / "run_network"),
        "network_binary_sha256": "verified",
    }
    rows = run_simulation("x", work, reference, arguments(), {}, [], route="net-reload")

    context = (work / "simulation-net-reload" / "reference" / "context.bngl").read_text(
        encoding="utf-8"
    )
    assert "begin parameters" in context
    assert "begin compartments" in context
    assert "begin molecule types" not in context
    assert "begin seed species" not in context
    assert "generate_network" not in context
    assert len(protocols) == 1
    assert protocols[0].index('readFile({file=>"context.bngl"})') < protocols[0].index(
        'readFile({file=>"input.net"})'
    )
    assert "simulate_ode(" in protocols[0]
    assert 'netfile=>"input.net"' in protocols[0]
    assert rows[0]["status"] == "HARNESS_ERROR"
