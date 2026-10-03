"""ODE trajectory parity: action-aware BNG3 CLI vs Perl/golden ``.gdat``."""

from __future__ import annotations

import pytest

from tests.validation import compare, corpus, oracle_perl, runner
from tests.validation.strict import require_oracle

# Deterministic ODE models suitable for tight numeric comparison.  Models with
# only stochastic actions belong in test_parity_stochastic.py, not here.
ODE_MODELS = [
    "Motivating_example",
    "CaOscillate_Func",
    "Repressilator",
    "egfr_net",
    "michment",
]
ODE_MODELS = [m for m in ODE_MODELS if corpus.resolve(m) is not None]

# In-process package checks are limited to models whose single BNG2 action has
# the same initial state and horizon as Model.simulate. Continuation/action
# protocols remain on the action-aware CLI route above.
API_ODE_CASES = [
    ("localfunc", 10.0, 40, 1e-8, 1e-8, False),
    ("CaOscillate_Func", 50.0, 500, 1e-12, 1e-12, False),
    ("michment", 10.0, 50, 1e-8, 1e-8, True),
]
API_ODE_CASES = [case for case in API_ODE_CASES if corpus.resolve(case[0])]


@pytest.mark.smoke
@pytest.mark.parametrize("model_name", ODE_MODELS)
def test_ode_parity(model_name, bng_cpp, work_dir):
    ref_path, ref_src = oracle_perl.gdat(model_name, work_dir / "perl")
    require_oracle(
        ref_path is not None,
        f"no reference .gdat for {model_name}: {ref_src}",
    )

    ref_data, ref_cols = compare.parse_gdat(ref_path)
    assert ref_data is not None, f"could not parse reference .gdat ({ref_src})"

    # The BNG2 reference is produced by executing the model's action block.
    # Use the action-aware CLI path so setup actions (for example
    # setConcentration, sparse CVODE, and multi-phase continuation) are not
    # silently discarded by the direct API path.
    _, test_path, err = runner.run_cli(bng_cpp, model_name, work_dir / "cpp")
    assert test_path is not None, f"engine produced no trajectory: {err}"
    test_data, test_cols = compare.parse_gdat(test_path)
    assert test_data is not None, "could not parse engine .gdat"

    diff = compare.compare_trajectories(
        ref_data,
        ref_cols,
        test_data,
        test_cols,
        rtol=1e-6,
        columns=compare.COLUMNS_INTERSECT,
    )
    assert diff.ok, f"ODE mismatch [{model_name}] (ref={ref_src}): {diff.summary()}"


@pytest.mark.expressions
@pytest.mark.parametrize(
    "model_name,t_end,n_steps,solver_rtol,solver_atol,sparse", API_ODE_CASES
)
def test_python_api_ode_parity(
    model_name, t_end, n_steps, solver_rtol, solver_atol, sparse, api, work_dir
):
    ref_path, ref_src = oracle_perl.gdat(model_name, work_dir / "perl")
    require_oracle(
        ref_path is not None,
        f"no reference .gdat for {model_name}: {ref_src}",
    )
    ref_data, ref_cols = compare.parse_gdat(ref_path)
    assert ref_data is not None, f"could not parse reference .gdat ({ref_src})"

    test = runner.run_api(
        model_name,
        method="ode",
        t_start=0.0,
        t_end=t_end,
        n_steps=n_steps,
        rtol=solver_rtol,
        atol=solver_atol,
        sparse=sparse,
    )
    diff = compare.compare_trajectories(
        ref_data,
        ref_cols,
        test.data,
        test.columns,
        rtol=1e-6,
        atol=1e-9,
        columns=compare.COLUMNS_EXACT,
    )
    assert diff.ok, f"Python API ODE mismatch [{model_name}] (ref={ref_src}): {diff.summary()}"


@pytest.mark.expressions
def test_action_explicit_ode_tolerances_override_bng2_compatible_default(
    bng_cpp, api, tmp_path
):
    """An explicit action tolerance still overrides the BNG2 action default."""
    source = corpus.resolve("Motivating_example")
    assert source is not None
    source_text = source.read_text(encoding="utf-8")
    default_action = "simulate_ode({t_start=>0,t_end=>40,n_steps=>100})"
    assert source_text.count(default_action) == 1

    explicit_source = tmp_path / "Motivating_example_explicit.bngl"
    explicit_source.write_text(
        source_text.replace(
            default_action,
            "simulate_ode({t_start=>0,t_end=>40,n_steps=>100,"
            "rtol=>1e-12,atol=>1e-12})",
        ),
        encoding="utf-8",
    )
    _, cli_gdat, err = runner.run_cli_path(
        bng_cpp, explicit_source, tmp_path / "cli"
    )
    assert cli_gdat is not None, f"explicit-tolerance action failed: {err}"
    cli_data, cli_columns = compare.parse_gdat(cli_gdat)
    assert cli_data is not None, "could not parse explicit-tolerance action output"

    model = api.load(str(explicit_source))
    result = model.simulate(
        method="ode",
        t_start=0.0,
        t_end=40.0,
        n_steps=100,
        rtol=1e-12,
        atol=1e-12,
        sparse=False,
    )
    direct = runner._result_to_trajectory(result)
    diff = compare.compare_trajectories(
        direct.data,
        direct.columns,
        cli_data,
        cli_columns,
        rtol=1e-10,
        atol=1e-12,
        columns=compare.COLUMNS_EXACT,
    )
    assert diff.ok, (
        "action path did not preserve explicit tight rtol/atol against the direct API: "
        f"{diff.summary()}"
    )


@pytest.mark.expressions
def test_python_api_ode_defaults_remain_independent_of_action_defaults(api):
    source = corpus.resolve("Motivating_example")
    assert source is not None
    model = api.load(str(source))

    default = runner._result_to_trajectory(
        model.simulate(method="ode", t_end=40.0, n_steps=100)
    )
    explicit = runner._result_to_trajectory(
        model.simulate(
            method="ode",
            t_end=40.0,
            n_steps=100,
            rtol=1e-8,
            atol=1e-12,
            sparse=False,
        )
    )
    diff = compare.compare_trajectories(
        default.data,
        default.columns,
        explicit.data,
        explicit.columns,
        rtol=0.0,
        atol=0.0,
        columns=compare.COLUMNS_EXACT,
    )
    assert diff.ok, (
        "direct Python API defaults changed from rtol=1e-8/atol=1e-12: "
        f"{diff.summary()}"
    )
