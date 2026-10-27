"""Simulation orchestration must preserve stage boundaries and oracle identity."""

from argparse import Namespace
from pathlib import Path
import shutil

import numpy as np
import pytest

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
    (source_dir / "test_data.tfun").write_text("0 1\n1 2\n", encoding="utf-8")
    source_dir.joinpath("x.bngl").write_text(
        """begin model
begin parameters
    volume 2
end parameters
begin compartments
    cell 3 volume
end compartments
begin functions
    rate() = tfun('test_data.tfun', time)
end functions
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
        assert (Path(cwd) / "test_data.tfun").read_text(encoding="utf-8") == (
            "0 1\n1 2\n"
        )
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
    assert "begin functions" not in context
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


def test_net_reload_ssa_rejects_time_through_nested_user_function_argument(
    bng_cpp, tmp_path
):
    from tests.validation import runner

    (tmp_path / "input.net").write_text(
        """begin functions
    1 rate_adjust(x) (x * 2)
    2 nested_adjust(x) rate_adjust(x)
    3 rate_at_time() time
end functions
begin species
    1 X() 100
    2 Y() 100
end species
begin reactions
    1 1 0 nested_adjust(rate_at_time())
    2 2 0 rate_at_time()
end reactions
begin groups
    1 X_total 1
    2 Y_total 2
end groups
""",
        encoding="utf-8",
    )
    (tmp_path / "ode.bngl").write_text(
        'readFile({file=>"input.net"})\n'
        'simulate_ode({prefix=>"ode",netfile=>"input.net",t_start=>0,'
        "t_end=>1,n_steps=>10,rtol=>1e-8,atol=>1e-12,print_CDAT=>1})\n",
        encoding="utf-8",
    )
    _, _, ode_error = runner.run_cli_path(bng_cpp, tmp_path / "ode.bngl", tmp_path)
    assert not ode_error, f"time-dependent NET ODE failed: {ode_error}"
    ode_cdat = np.loadtxt(tmp_path / "ode.cdat", comments="#")
    np.testing.assert_allclose(
        ode_cdat[-1, 1:],
        [100.0 * np.exp(-1.0), 100.0 * np.exp(-0.5)],
        rtol=1e-6,
    )

    (tmp_path / "ssa.bngl").write_text(
        'readFile({file=>"input.net"})\n'
        'simulate_ssa({prefix=>"ssa",netfile=>"input.net",t_start=>0,'
        "t_end=>1,n_steps=>2,seed=>42,print_CDAT=>1})\n",
        encoding="utf-8",
    )
    _, _, ssa_error = runner.run_cli_path(bng_cpp, tmp_path / "ssa.bngl", tmp_path)
    assert "SSA does not support explicitly time-dependent rate laws" in ssa_error


def _assert_compartment_net_reload_matches_source(
    bng_cpp, tmp_path, method, rate_expression, function_block=""
):
    from tests.validation import runner
    from tests.validation.simulation_contract import net_reload_context

    if method == "ode":
        source_action = 'simulate_ode({prefix=>"trajectory",t_start=>0,t_end=>1.0,n_steps=>10,rtol=>1e-8,atol=>1e-12,print_CDAT=>1})'
        reload_action = 'simulate_ode({prefix=>"trajectory",netfile=>"input.net",t_start=>0,t_end=>1.0,n_steps=>10,rtol=>1e-8,atol=>1e-12,print_CDAT=>1})'
    elif method == "ssa":
        source_action = 'simulate_ssa({prefix=>"trajectory",t_start=>0,t_end=>1.0,n_steps=>10,seed=>31415,print_CDAT=>1})'
        reload_action = 'simulate_ssa({prefix=>"trajectory",netfile=>"input.net",t_start=>0,t_end=>1.0,n_steps=>10,seed=>31415,print_CDAT=>1})'
    else:
        source_action = 'simulate_psa({prefix=>"trajectory",t_start=>0,t_end=>1.0,n_steps=>10,seed=>31415,poplevel=>0})'
        reload_action = source_action

    source = tmp_path / "source.bngl"
    source.write_text(
        """begin model
begin parameters
    cell_volume 20
    k_bind 0.1
    A0 100
    B0 20
end parameters
"""
        + function_block
        + """begin compartments
    cell 3 cell_volume
end compartments
begin molecule types
    A(x)
    B(y)
end molecule types
begin seed species
    A(x)@cell A0
    B(y)@cell B0
end seed species
begin observables
    Molecules A_total A()
    Molecules B_total B()
    Species AB_total @cell:A(x!1).B(y!1)
end observables
begin reaction rules
"""
        + "    A(x)@cell + B(y)@cell -> A(x!1)@cell.B(y!1)@cell "
        + rate_expression
        + "\nend reaction rules\n"
        + """end model
begin actions
    generate_network({overwrite=>1})
"""
        + "    "
        + source_action
        + "\nend actions\n",
        encoding="utf-8",
    )

    source_run = tmp_path / "source-run"
    source_net, _, source_error = runner.run_cli_path(bng_cpp, source, source_run)
    assert source_net is not None, f"source network generation failed: {source_error}"
    if function_block:
        from tests.validation import compare

        # Static nested calls may be folded during export. Check their value,
        # including the bimolecular compartment factor, rather than spelling.
        network = compare.parse_net(source_net)
        assert network is not None and network.n_reactions == 1
        rate = network._raw[0][2]
        assert float(
            compare._resolve_rate(
                rate,
                network.rate_defs,
                "value",
                network.rate_functions,
                network.rate_observables,
            )
        ) == pytest.approx(0.1 * 2 / 20)
    source_traces = {
        kind: np.loadtxt(source_run / f"trajectory.{kind}", comments="#")
        for kind in ("cdat", "gdat")
    }

    reload_run = tmp_path / "net-reload"
    reload_run.mkdir()
    shutil.copy2(source_net, reload_run / "input.net")
    (reload_run / "context.bngl").write_text(
        net_reload_context(source), encoding="utf-8"
    )
    reload_source = reload_run / "reload.bngl"
    reload_source.write_text(
        'readFile({file=>"context.bngl"})\n'
        'readFile({file=>"input.net"})\n' + reload_action + "\n",
        encoding="utf-8",
    )
    _, _, reload_error = runner.run_cli_path(bng_cpp, reload_source, reload_run)
    assert not reload_error, f"NET reload simulation failed: {reload_error}"

    for kind, expected in source_traces.items():
        actual = np.loadtxt(reload_run / f"trajectory.{kind}", comments="#")
        np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-10)


@pytest.mark.parametrize("method", ["ode", "ssa", "psa"])
def test_compartment_net_reload_matches_source_network(bng_cpp, tmp_path, method):
    _assert_compartment_net_reload_matches_source(bng_cpp, tmp_path, method, "k_bind")


@pytest.mark.parametrize("method", ["ode", "ssa", "psa"])
def test_compartment_net_reload_preserves_nested_numeric_function_arguments(
    bng_cpp, tmp_path, method
):
    functions = """begin functions
    bind_multiplier(x) x * (1 + x)
    nested_multiplier(x) max(bind_multiplier(x), 1)
end functions
"""
    _assert_compartment_net_reload_matches_source(
        bng_cpp, tmp_path, method, "k_bind * nested_multiplier(1)", functions
    )


def test_compartment_net_reload_preserves_psa_indexed_observables(bng_cpp, tmp_path):
    _assert_compartment_net_reload_matches_source(bng_cpp, tmp_path, "psa", "k_bind")


@pytest.mark.parametrize("method", ["ode", "ssa", "psa"])
def test_net_reload_preserves_mixed_scope_and_numeric_function_arguments(
    bng_cpp, tmp_path, method
):
    from tests.validation import runner
    from tests.validation.simulation_contract import net_reload_context

    if method == "ode":
        source_action = 'simulate_ode({prefix=>"trajectory",t_start=>0,t_end=>1,n_steps=>10,rtol=>1e-8,atol=>1e-12,print_CDAT=>1})'
        reload_action = 'simulate_ode({prefix=>"trajectory",netfile=>"input.net",t_start=>0,t_end=>1,n_steps=>10,rtol=>1e-8,atol=>1e-12,print_CDAT=>1})'
    elif method == "ssa":
        source_action = 'simulate_ssa({prefix=>"trajectory",t_start=>0,t_end=>1,n_steps=>10,seed=>31415,print_CDAT=>1})'
        reload_action = 'simulate_ssa({prefix=>"trajectory",netfile=>"input.net",t_start=>0,t_end=>1,n_steps=>10,seed=>31415,print_CDAT=>1})'
    else:
        source_action = 'simulate_psa({prefix=>"trajectory",t_start=>0,t_end=>1,n_steps=>10,seed=>31415,poplevel=>0})'
        reload_action = source_action

    source = tmp_path / "source.bngl"
    source.write_text(
        """begin model
begin parameters
    k 2
end parameters
begin molecule types
    A(s~u~p)
    I(i)
end molecule types
begin seed species
    A(s~u!1).I(i!1) 1
    A(s~p!1).I(i!1) 1
end seed species
begin observables
    Molecules A_total A()
end observables
begin functions
    gate(x,k) = if(A_total(x)>0,0,k)
    scale_value(n) = n*2
    rate_adjust(n) = scale_value(n)
end functions
begin reaction rules
    A%x(s~u!1).I(i!1) -> A%x(s~p!1).I(i!1) gate(x,k)
    A%x(s~p!1).I(i!1) -> A%x(s~u!1).I(i!1) rate_adjust(A_total(x))
end reaction rules
end model
begin actions
    generate_network({overwrite=>1})
""" + "    " + source_action + "\nend actions\n",
        encoding="utf-8",
    )

    source_run = tmp_path / "source-run"
    source_net, _, source_error = runner.run_cli_path(bng_cpp, source, source_run)
    assert source_net is not None, f"source network generation failed: {source_error}"
    net_text = source_net.read_text(encoding="utf-8")
    assert "__R1_local1 0  # ConstantExpression" in net_text
    assert "__R2_local1 2  # ConstantExpression" in net_text
    source_traces = {
        kind: np.loadtxt(source_run / f"trajectory.{kind}", comments="#")
        for kind in ("cdat", "gdat")
    }

    reload_run = tmp_path / "net-reload"
    reload_run.mkdir()
    shutil.copy2(source_net, reload_run / "input.net")
    (reload_run / "context.bngl").write_text(
        net_reload_context(source), encoding="utf-8"
    )
    reload_source = reload_run / "reload.bngl"
    reload_source.write_text(
        'readFile({file=>"context.bngl"})\n'
        'readFile({file=>"input.net"})\n' + reload_action + "\n",
        encoding="utf-8",
    )
    _, _, reload_error = runner.run_cli_path(bng_cpp, reload_source, reload_run)
    assert not reload_error, f"NET reload simulation failed: {reload_error}"

    for kind, expected in source_traces.items():
        actual = np.loadtxt(reload_run / f"trajectory.{kind}", comments="#")
        np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-10)
