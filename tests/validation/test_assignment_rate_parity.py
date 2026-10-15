"""Independent BNG2 contracts for constant local and live conditional rates."""

import math
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from scripts.cross_validate import _stage_model
from tests.validation import compare, oracle_perl, runner
from tests.validation.strict import require_oracle


@pytest.mark.parametrize(
    ("reactant", "function", "rate", "expected"),
    [
        ("X()%x", None, "func(x)", "0.0"),
        ("A()%x", None, "func(x)", "1.0"),
        ("B()%x", None, "func(x)", "2.0"),
        ("C()%x", None, "func(x)", "3.0"),
        ("A()%y", None, "func(y)", "1.0"),
        ("X()", "func() if(Obs1==1,param1,param2)", "func()", None),
        ("X()", "func() if(time()>1,param1,param2)", "func()", None),
        (
            "A()%x",
            "func(x) if(Obs1(x)==1,time(),param2)",
            "func(x)",
            None,
        ),
        (
            "X()%x",
            "func(x) if(Obs1(x)==1,time(),param2)",
            "func(x)",
            None,
        ),
    ],
    ids=[
        "local-zero",
        "local-A",
        "local-B",
        "local-C",
        "scope-alias",
        "global-observable",
        "time",
        "scoped-time-true-branch",
        "scoped-time-false-branch",
    ],
)
def test_assignment_conditional_rate_parity(
    tmp_path, bng_cpp, reactant, function, rate, expected
):
    source = Path(__file__).parent / "Validate" / "test_assignment.bngl"
    text = source.read_text(encoding="utf-8")
    text = text.replace("B() 0", "B() 1").replace("C() 0", "C() 1")
    text = text.replace("X()%x -> 0  func(x)", f"{reactant} -> 0  {rate}")
    if function:
        text = text.replace(
            "func(x) if(Obs1(x)==1,param1,if(Obs2(x)>0,param2,if(Obs3(x)>0,param3,0)))",
            function,
        )
    reference, generated = _assignment_networks(text, tmp_path, bng_cpp)
    assert reference.n_reactions == generated.n_reactions == 1
    for network in (reference, generated):
        key = next(iter(network.reaction_multiset))[2]
        if expected is None:
            assert key.startswith("expr:"), "live rate was frozen to a number"
        else:
            assert key == expected


def _assignment_networks(text, tmp_path, bng_cpp):
    model = tmp_path / "assignment.bngl"
    model.write_text(text, encoding="utf-8")
    perl_model = _stage_model(model, tmp_path, tmp_path / "perl")
    cpp_model = _stage_model(model, tmp_path, tmp_path / "cpp")
    assert perl_model.read_bytes() == cpp_model.read_bytes()

    ref_path, ref_source = oracle_perl.net(
        model.stem, tmp_path / "perl", source_path=perl_model
    )
    require_oracle(ref_path is not None, f"live BNG2 oracle unavailable: {ref_source}")
    test_path, _, error = runner.run_cli_path(bng_cpp, cpp_model, tmp_path / "cpp")
    assert test_path is not None, error
    reference = compare.parse_net(ref_path)
    generated = compare.parse_net(test_path)
    assert reference is not None and generated is not None
    diff = compare.compare_net(reference, generated)
    assert diff.ok, diff.summary()
    return reference, generated


@pytest.mark.parametrize(
    (
        "reactant",
        "observable",
        "branch",
        "parameter_definitions",
        "offset",
        "parameter_slope",
    ),
    [
        (
            "A()%x",
            "A_total",
            "true",
            "kbase 2\n    k kbase",
            0.0,
            0.0,
        ),
        (
            "X()%x",
            "X_total",
            "false",
            "kbase 2\n    k kbase",
            0.0,
            0.0,
        ),
        (
            "A()%x",
            "A_total",
            "true",
            "kbase 2\n    k kbase + time()",
            0.0,
            1.0,
        ),
        (
            "X()%x",
            "X_total",
            "false",
            "kbase 2\n    k kbase + time()",
            0.0,
            1.0,
        ),
        (
            "A()%x",
            "A_total",
            "true",
            "kbase 2\n    kIntermediate kbase + time()\n    k kIntermediate + 1",
            1.0,
            1.0,
        ),
        (
            "X()%x",
            "X_total",
            "false",
            "kbase 2\n    kIntermediate kbase + time()\n    k kIntermediate + 1",
            1.0,
            1.0,
        ),
    ],
    ids=[
        "static-parameter-true-branch",
        "static-parameter-false-branch",
        "direct-time-parameter-true-branch",
        "direct-time-parameter-false-branch",
        "transitive-time-parameter-true-branch",
        "transitive-time-parameter-false-branch",
    ],
)
def test_scoped_time_rate_ode_matches_analytic_solution(
    tmp_path,
    bng_cpp,
    reactant,
    observable,
    branch,
    parameter_definitions,
    offset,
    parameter_slope,
):
    source = tmp_path / f"scoped-time-{branch}.bngl"
    source.write_text(
        f"""begin model
begin parameters
    {parameter_definitions}
end parameters
begin molecule types
    A()
    X()
end molecule types
begin seed species
    A() 1
    X() 1
end seed species
begin observables
    Molecules Obs1 A()
    Molecules A_total A()
    Molecules X_total X()
end observables
begin functions
    func(x) if(Obs1(x)==1,time()+k,k)
end functions
begin reaction rules
    {reactant} -> 0 func(x)
end reaction rules
end model
begin actions
    generate_network({{overwrite=>1}})
    simulate({{method=>"ode",t_end=>2,n_steps=>4,atol=>1e-10,rtol=>1e-10}})
end actions
""",
        encoding="utf-8",
    )
    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "cli")
    assert gdat is not None, error
    data, columns = compare.parse_gdat(gdat)
    assert data is not None and columns is not None
    times = data[:, columns.index("time")]
    actual = data[:, columns.index(observable)]
    rate_slope = parameter_slope + (1.0 if branch == "true" else 0.0)
    expected = [
        math.exp(-(2.0 + offset) * time - 0.5 * rate_slope * time * time)
        for time in times
    ]
    assert actual == pytest.approx(expected, rel=1e-5, abs=5e-9)


def test_scoped_time_rate_preserves_dynamic_parameter_through_nested_function(
    tmp_path, bng_cpp
):
    source = tmp_path / "scoped-time-nested-parameter.bngl"
    source.write_text(
        """begin model
begin parameters
    kbase 2
    k kbase + time()
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules Obs1 A()
    Molecules A_total A()
end observables
begin functions
    pass(q) q
    func(x) if(Obs1(x)==1,pass(k)+time(),pass(k)+time())
end functions
begin reaction rules
    A()%x -> 0 func(x)
end reaction rules
end model
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode",t_end=>2,n_steps=>4,atol=>1e-10,rtol=>1e-10})
end actions
""",
        encoding="utf-8",
    )
    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "cli")
    assert gdat is not None, error
    data, columns = compare.parse_gdat(gdat)
    assert data is not None and columns is not None
    times = data[:, columns.index("time")]
    actual = data[:, columns.index("A_total")]
    expected = [math.exp(-2.0 * time - time * time) for time in times]
    assert actual == pytest.approx(expected, rel=1e-5, abs=5e-9)


def test_scoped_time_rate_prefers_declared_pi_and_e_parameters_in_nested_calls(
    tmp_path, bng_cpp
):
    source = tmp_path / "scoped-time-declared-pi-e-parameters.bngl"
    source.write_text(
        """begin model
begin parameters
    pi 2
    e 3
end parameters
begin molecule types
    A()
    X()
end molecule types
begin seed species
    A() 1
    X() 1
end seed species
begin observables
    Molecules Obs1 A()
    Molecules A_total A()
    Molecules X_total X()
end observables
begin functions
    pass(q) q
    func(x) if(Obs1(x)==1,pass(pi)+time(),pass(e)+time())
end functions
begin reaction rules
    A()%x -> 0 func(x)
    X()%x -> 0 func(x)
end reaction rules
end model
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode",t_end=>2,n_steps=>4,atol=>1e-10,rtol=>1e-10})
end actions
""",
        encoding="utf-8",
    )
    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "cli")
    assert gdat is not None, error
    data, columns = compare.parse_gdat(gdat)
    assert data is not None and columns is not None
    times = data[:, columns.index("time")]
    actual_a = data[:, columns.index("A_total")]
    actual_x = data[:, columns.index("X_total")]
    expected_a = [math.exp(-2.0 * time - 0.5 * time * time) for time in times]
    expected_x = [math.exp(-3.0 * time - 0.5 * time * time) for time in times]
    assert actual_a == pytest.approx(expected_a, rel=1e-5, abs=5e-9)
    assert actual_x == pytest.approx(expected_x, rel=1e-5, abs=5e-9)


def test_static_scoped_rate_prefers_declared_pi_and_e_parameters_in_nested_calls(
    tmp_path, bng_cpp
):
    source = tmp_path / "static-scoped-declared-pi-e-parameters.bngl"
    source.write_text(
        """begin model
begin parameters
    pi 2
    e 3
end parameters
begin molecule types
    A()
    X()
end molecule types
begin seed species
    A() 1
    X() 1
end seed species
begin observables
    Molecules Obs1 A()
    Molecules A_total A()
    Molecules X_total X()
end observables
begin functions
    pass(q) q
    func(x) if(Obs1(x)==1,pass(pi),pass(e))
end functions
begin reaction rules
    A()%x -> 0 func(x)
    X()%x -> 0 func(x)
end reaction rules
end model
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode",t_end=>2,n_steps=>4,atol=>1e-10,rtol=>1e-10})
end actions
""",
        encoding="utf-8",
    )
    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "cli")
    assert gdat is not None, error
    data, columns = compare.parse_gdat(gdat)
    assert data is not None and columns is not None
    times = data[:, columns.index("time")]
    actual_a = data[:, columns.index("A_total")]
    actual_x = data[:, columns.index("X_total")]
    expected_a = [math.exp(-2.0 * time) for time in times]
    expected_x = [math.exp(-3.0 * time) for time in times]
    assert actual_a == pytest.approx(expected_a, rel=1e-5, abs=5e-9)
    assert actual_x == pytest.approx(expected_x, rel=1e-5, abs=5e-9)


def test_scoped_time_rate_does_not_fold_dynamic_parameter_nested_condition(
    tmp_path, bng_cpp
):
    source = tmp_path / "scoped-time-dynamic-nested-condition.bngl"
    source.write_text(
        """begin model
begin parameters
    kbase 2
    k kbase + time()
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules Obs1 A()
    Molecules A_total A()
end observables
begin functions
    pass(q) q
    func(x) if(Obs1(x)==1 && pass(k)<3,1,2)
end functions
begin reaction rules
    A()%x -> 0 func(x)
end reaction rules
end model
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode",t_end=>2,n_steps=>4,atol=>1e-10,rtol=>1e-10})
end actions
""",
        encoding="utf-8",
    )
    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "cli")
    assert gdat is not None, error
    data, columns = compare.parse_gdat(gdat)
    assert data is not None and columns is not None
    times = data[:, columns.index("time")]
    actual = data[:, columns.index("A_total")]
    expected = [
        math.exp(-time if time <= 1.0 else -(1.0 + 2.0 * (time - 1.0)))
        for time in times
    ]
    assert actual == pytest.approx(expected, rel=1e-5, abs=5e-9)


@pytest.mark.parametrize(
    ("constant", "value"),
    [("_pi", math.pi), ("_e", math.e)],
)
def test_scoped_time_rate_preserves_math_constant_through_nested_function(
    tmp_path, bng_cpp, constant, value
):
    source = tmp_path / f"scoped-time-nested-{constant}.bngl"
    source.write_text(
        f"""begin model
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules Obs1 A()
    Molecules A_total A()
end observables
begin functions
    pass(q) q
    func(x) if(Obs1(x)==1,pass({constant})+time(),pass({constant})+time())
end functions
begin reaction rules
    A()%x -> 0 func(x)
end reaction rules
end model
begin actions
    generate_network({{overwrite=>1}})
    simulate({{method=>"ode",t_end=>2,n_steps=>4,atol=>1e-10,rtol=>1e-10}})
end actions
""",
        encoding="utf-8",
    )
    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "cli")
    assert gdat is not None, error
    data, columns = compare.parse_gdat(gdat)
    assert data is not None and columns is not None
    times = data[:, columns.index("time")]
    actual = data[:, columns.index("A_total")]
    expected = [math.exp(-value * time - 0.5 * time * time) for time in times]
    assert actual == pytest.approx(expected, rel=1e-5, abs=5e-9)


@pytest.mark.parametrize("identifier", ["pi", "e"])
def test_scoped_time_rate_rejects_undeclared_bare_math_aliases(
    tmp_path, bng_cpp, identifier
):
    source = tmp_path / f"scoped-time-undeclared-{identifier}.bngl"
    source.write_text(
        f"""begin model
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules Obs1 A()
end observables
begin functions
    pass(q) q
    func(x) if(Obs1(x)==1,pass({identifier})+time(),pass({identifier})+time())
end functions
begin reaction rules
    A()%x -> 0 func(x)
end reaction rules
end model
begin actions
    generate_network({{overwrite=>1}})
end actions
""",
        encoding="utf-8",
    )
    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "cli")
    assert gdat is None
    assert f"{identifier}: unresolved expression symbol: {identifier}" in error


@pytest.mark.parametrize("clock", ["time", "t"])
def test_scoped_time_rate_preserves_bare_clock_through_nested_function(
    tmp_path, bng_cpp, clock
):
    source = tmp_path / f"scoped-time-nested-{clock}.bngl"
    source.write_text(
        f"""begin model
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules Obs1 A()
    Molecules A_total A()
end observables
begin functions
    pass(q) q
    func(x) if(Obs1(x)==1,pass({clock}),pass({clock}))
end functions
begin reaction rules
    A()%x -> 0 func(x)
end reaction rules
end model
begin actions
    generate_network({{overwrite=>1}})
    simulate({{method=>"ode",t_end=>2,n_steps=>4,atol=>1e-10,rtol=>1e-10}})
end actions
""",
        encoding="utf-8",
    )
    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "cli")
    assert gdat is not None, error
    data, columns = compare.parse_gdat(gdat)
    assert data is not None and columns is not None
    times = data[:, columns.index("time")]
    actual = data[:, columns.index("A_total")]
    expected = [math.exp(-0.5 * time * time) for time in times]
    assert actual == pytest.approx(expected, rel=1e-5, abs=5e-9)


def test_scoped_time_rate_constant_false_branch_remains_supported_by_ssa(
    tmp_path, bng_cpp
):
    source = tmp_path / "scoped-time-false-branch-ssa.bngl"
    source.write_text(
        """begin model
begin molecule types
    A()
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules Obs1 A()
    Molecules X_total X()
end observables
begin functions
    func(x) if(Obs1(x)==1,time(),2)
end functions
begin reaction rules
    X()%x -> 0 func(x)
end reaction rules
end model
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ssa",t_end=>2,n_steps=>4,seed=>1})
end actions
""",
        encoding="utf-8",
    )
    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "cli")
    assert gdat is not None, error


def test_scoped_time_rate_nested_static_condition_remains_supported_by_ssa(
    tmp_path, bng_cpp
):
    source = tmp_path / "scoped-time-nested-condition-ssa.bngl"
    source.write_text(
        """begin model
begin molecule types
    A()
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules Obs2 A()
    Molecules X_total X()
end observables
begin functions
    inner(x) if(Obs2(x)==1,time(),2)
    func(x) if(inner(x)==3,time(),4)
end functions
begin reaction rules
    X()%x -> 0 func(x)
end reaction rules
end model
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ssa",t_end=>2,n_steps=>4,seed=>1})
end actions
""",
        encoding="utf-8",
    )
    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "cli")
    assert gdat is not None, error


def test_scoped_time_rate_dead_branch_expression_remains_supported_by_ssa(
    tmp_path, bng_cpp
):
    source = tmp_path / "scoped-time-dead-branch-expression-ssa.bngl"
    source.write_text(
        """begin model
begin molecule types
    A()
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules Obs1 A()
    Molecules X_total X()
end observables
begin functions
    func(x) if(Obs1(x)==1,time(),2)+1
end functions
begin reaction rules
    X()%x -> 0 func(x)
end reaction rules
end model
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ssa",t_end=>2,n_steps=>4,seed=>1})
end actions
""",
        encoding="utf-8",
    )
    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "cli")
    assert gdat is not None, error


def test_scoped_time_rate_remains_unsupported_by_ssa(tmp_path, bng_cpp):
    source = tmp_path / "scoped-time-ssa.bngl"
    source.write_text(
        """begin model
begin parameters
    k 2
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules Obs1 A()
end observables
begin functions
    func(x) if(Obs1(x)==1,time(),k)
end functions
begin reaction rules
    A()%x -> 0 func(x)
end reaction rules
end model
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ssa",t_end=>2,n_steps=>4,seed=>1})
end actions
""",
        encoding="utf-8",
    )
    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "cli")
    assert gdat is None
    assert "SSA does not support explicitly time-dependent rate laws" in error


@pytest.mark.parametrize(
    ("rates", "expected"),
    [
        ("func(x),func(y)", ["0.0", "1.0"]),
        ("global(),func(y)", ["1.0", "2.0"]),
        ("func(x),global()", ["0.0", "2.0"]),
    ],
)
def test_assignment_reversible_conditional_rates(tmp_path, bng_cpp, rates, expected):
    source = Path(__file__).parent / "Validate" / "test_assignment.bngl"
    text = source.read_text(encoding="utf-8")
    text = text.replace("end functions", "global() param2\nend functions")
    text = text.replace("X()%x -> 0  func(x)", f"X()%x <-> A()%y {rates}")
    reference, generated = _assignment_networks(text, tmp_path, bng_cpp)
    for network in (reference, generated):
        assert network.n_reactions == 2
        assert sorted(key[2] for key in network.reaction_multiset) == expected


def test_numeric_function_argument_matches_bng2_inline_rate_and_net_reload(
    tmp_path, bng_cpp
):
    def source_model(rate_expression, method="ode", include_function=True):
        if method == "ode":
            simulation = (
                "simulate_ode({t_start=>0,t_end=>0.1,n_steps=>4,"
                "atol=>1e-12,rtol=>1e-10})"
            )
        else:
            simulation = "simulate_ssa({t_start=>0,t_end=>0.1,n_steps=>4," "seed=>42})"
        function_block = (
            "begin functions\n    rate_adjust(k) = k*2\nend functions\n"
            if include_function
            else ""
        )
        return f"""begin model
begin parameters
    k1 2
    k2 3
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 100
end seed species
begin observables
    Molecules A_total A()
end observables
{function_block}begin reaction rules
    A() -> 0 {rate_expression}
end reaction rules
end model
begin actions
    generate_network({{overwrite=>1}})
    {simulation}
end actions
"""

    function_call_source = source_model("rate_adjust(k1+k2)")
    source_path = tmp_path / "function-call.bngl"
    source_path.write_text(function_call_source, encoding="utf-8")
    _, source_gdat, source_error = runner.run_cli_path(
        bng_cpp, source_path, tmp_path / "bng3-source"
    )
    assert source_gdat is not None, source_error

    source_net = tmp_path / "bng3-source" / "function-call.net"
    assert source_net.is_file()

    reload_dir = tmp_path / "bng3-net-reload"
    reload_dir.mkdir()
    reload_net = reload_dir / "input.net"
    reload_net.write_bytes(source_net.read_bytes())
    reload_source = reload_dir / "reload.bngl"
    reload_source.write_text(
        'readFile({file=>"input.net"})\n'
        'simulate_ode({prefix=>"reload",netfile=>"input.net",t_start=>0,'
        "t_end=>0.1,n_steps=>4,atol=>1e-12,rtol=>1e-10})\n",
        encoding="utf-8",
    )
    _, reload_gdat, reload_error = runner.run_cli_path(
        bng_cpp, reload_source, reload_dir
    )
    assert reload_gdat is not None, reload_error

    # BNG2 does not import argument-taking functions from NET. Generate its
    # reference from the mathematically equivalent inlined rate, 2*(2+3) = 10.
    bng2_source = tmp_path / "bng2-inline-rate.bngl"
    bng2_source.write_text(
        source_model("2*(k1+k2)", include_function=False), encoding="utf-8"
    )
    bng2_work = tmp_path / "bng2-inline-rate"
    bng2_net, bng2_source_kind = oracle_perl.net(
        bng2_source.stem,
        bng2_work,
        network_only=True,
        source_path=bng2_source,
    )
    require_oracle(
        bng2_net is not None,
        f"BNG2 inline-rate network unavailable: {bng2_source_kind}",
    )
    for net_path in (source_net, bng2_net):
        network = compare.parse_net(net_path)
        assert network is not None and network.n_reactions == 1
        assert next(iter(network.reaction_multiset))[2] == "10.0"

    bngpath = os.environ.get("BNGPATH")
    require_oracle(bool(bngpath), "BNG2 inline-rate simulation requires BNGPATH")
    run_network = Path(bngpath) / "bin" / "run_network"
    require_oracle(run_network.is_file(), f"BNG2 run_network not found: {run_network}")
    bng2_prefix = bng2_work / "bng2-inline-rate-output"
    bng2_result = subprocess.run(
        [
            str(run_network),
            "-o",
            str(bng2_prefix),
            "-p",
            "cvode",
            "-a",
            "1e-12",
            "-r",
            "1e-10",
            "--cdat",
            "1",
            "--fdat",
            "0",
            str(bng2_net),
            "0",
            "0.025",
            "0.05",
            "0.075",
            "0.1",
        ],
        cwd=bng2_work,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert bng2_result.returncode == 0, (
        "BNG2 run_network failed on the equivalent inlined rate:\n"
        f"stdout:\n{bng2_result.stdout}\nstderr:\n{bng2_result.stderr}"
    )
    bng2_cdat = bng2_prefix.with_suffix(".cdat")
    assert bng2_cdat.is_file(), f"BNG2 produced no CDAT at {bng2_cdat}"

    bng2_data, bng2_columns = compare.parse_gdat(bng2_cdat)
    assert bng2_data is not None and bng2_columns is not None
    bng2_species_column = next(
        (column for column in bng2_columns if column != "time"), None
    )
    assert bng2_species_column is not None
    bng2_times = bng2_data[:, bng2_columns.index("time")]
    bng2_values = bng2_data[:, bng2_columns.index(bng2_species_column)]

    trajectories = []
    for gdat in (source_gdat, reload_gdat):
        data, columns = compare.parse_gdat(gdat)
        assert data is not None and columns is not None
        assert "A_total" in columns
        trajectories.append(
            (data[:, columns.index("time")], data[:, columns.index("A_total")])
        )

    for times, values in trajectories:
        assert times == pytest.approx(bng2_times, abs=1e-12)
        assert values == pytest.approx(bng2_values, rel=1e-9, abs=1e-10)
        assert values[-1] == pytest.approx(100.0 * math.exp(-1.0), rel=1e-8)

    # The same rate must survive the stochastic source and imported-NET paths.
    ssa_source = tmp_path / "function-call-ssa.bngl"
    ssa_source.write_text(
        source_model("rate_adjust(k1+k2)", method="ssa"), encoding="utf-8"
    )
    ssa_source_dir = tmp_path / "bng3-ssa-source"
    _, ssa_source_gdat, ssa_source_error = runner.run_cli_path(
        bng_cpp, ssa_source, ssa_source_dir
    )
    assert ssa_source_gdat is not None, ssa_source_error
    ssa_reload_dir = tmp_path / "bng3-ssa-net-reload"
    ssa_reload_dir.mkdir()
    ssa_reload_net = ssa_reload_dir / "input.net"
    ssa_reload_net.write_bytes((ssa_source_dir / "function-call-ssa.net").read_bytes())
    ssa_reload_source = ssa_reload_dir / "reload.bngl"
    ssa_reload_source.write_text(
        'readFile({file=>"input.net"})\n'
        'simulate_ssa({prefix=>"ssa-reload",netfile=>"input.net",t_start=>0,'
        "t_end=>0.1,n_steps=>4,seed=>42})\n",
        encoding="utf-8",
    )
    _, ssa_reload_gdat, ssa_reload_error = runner.run_cli_path(
        bng_cpp, ssa_reload_source, ssa_reload_dir
    )
    assert ssa_reload_gdat is not None, ssa_reload_error

    ssa_source_data, ssa_source_columns = compare.parse_gdat(ssa_source_gdat)
    ssa_reload_data, ssa_reload_columns = compare.parse_gdat(ssa_reload_gdat)
    assert ssa_source_data is not None and ssa_source_columns is not None
    assert ssa_reload_data is not None and ssa_reload_columns is not None
    assert "A_total" in ssa_source_columns and "A_total" in ssa_reload_columns
    np.testing.assert_allclose(
        ssa_source_data[
            :, [ssa_source_columns.index("time"), ssa_source_columns.index("A_total")]
        ],
        ssa_reload_data[
            :, [ssa_reload_columns.index("time"), ssa_reload_columns.index("A_total")]
        ],
        rtol=0.0,
        atol=0.0,
    )
