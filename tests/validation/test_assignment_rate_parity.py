"""Independent BNG2 contracts for constant local and live conditional rates."""

from pathlib import Path
import math

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
