"""Independent BNG2 contracts for constant local and live conditional rates."""

from pathlib import Path

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
    ],
    ids=[
        "local-zero",
        "local-A",
        "local-B",
        "local-C",
        "scope-alias",
        "global-observable",
        "time",
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
