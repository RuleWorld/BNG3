"""Contracts for the official SBML Test Suite reference comparison.

These tests cover the comparison stages that were previously skipped by the
harness: the native action dispatcher path for models with scheduled actions
and the DSMTS ensemble statistics for stochastic cases.
"""

import importlib.util
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


def _load_validator(name: str):
    path = Path(__file__).parents[2] / "scripts" / "ci" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_actions():
    path = Path(__file__).parents[2] / "scripts" / "ci" / "sbml_reference_actions.py"
    spec = importlib.util.spec_from_file_location("sbml_reference_actions", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ACTION_MODEL = """begin model
begin parameters
  k1 1
end parameters
begin compartments
  compartment 3 1
end compartments
begin molecule types
  M_S1()
end molecule types
begin seed species
  @compartment:M_S1() 1
end seed species
begin observables
  Species S1_amt @compartment:M_S1()
end observables
begin functions
  SSTSREF_TEST_0000() = S1_amt
end functions
begin reaction rules
  reaction1: @compartment:M_S1() -> @compartment:M_S1() 0
end reaction rules
end model

begin actions
  generate_network({overwrite=>1})
  simulate({method=>"ode", t_start=>0, t_end=>2.5, n_steps=>25})
  setConcentration("@compartment:M_S1()", "1")
  simulate({continue=>1, method=>"ode", t_start=>2.5, t_end=>5, n_steps=>25})
end actions
"""


def test_action_rewrite_only_changes_the_output_grid():
    actions = _load_actions()
    times = [0.0, 0.5, 1.0, 2.5, 3.0, 5.0]
    rewritten, block = actions.rewrite_action_output_grid(ACTION_MODEL, times)

    # The event semantics are untouched: the same actions in the same order.
    assert "setConcentration" in rewritten
    assert rewritten.count("setConcentration") == ACTION_MODEL.count("setConcentration")
    assert "generate_network({overwrite=>1})" in rewritten
    # The phase boundaries are untouched.
    assert [(phase.t_start, phase.t_end) for phase in block.phases] == [
        (0.0, 2.5),
        (2.5, 5.0),
    ]
    # Only the output grid changed: n_steps is replaced by the official grid.
    assert "n_steps=>25" not in rewritten
    assert "sample_times=>[0.0, 0.5, 1.0, 2.5]" in rewritten
    assert "sample_times=>[2.5, 3.0, 5.0]" in rewritten
    # The solver tolerances match the in-memory reference runner.
    assert "rtol=>1e-09" in rewritten
    assert "atol=>1e-14" in rewritten


def test_action_rewrite_rejects_an_unknown_action():
    actions = _load_actions()
    model = ACTION_MODEL.replace(
        "generate_network({overwrite=>1})", "launchMissiles({overwrite=>1})"
    )
    with pytest.raises(actions.ActionGridError):
        actions.parse_action_block(model)


def test_action_execution_reports_the_official_grid():
    actions = _load_actions()
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    times = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    alias = "SSTSREF_TEST_0000"
    rewritten, _ = actions.rewrite_action_output_grid(ACTION_MODEL, times)

    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        run = actions.execute_action_block(
            cpp,
            rewritten,
            Path(raw),
            times=times,
            aliases={"S1": alias},
        )

    assert run.times == times
    assert len(run.values["S1"]) == len(times)
    # The scheduled action resets the species at t=2.5; the dispatcher reports
    # the phase-boundary sample before the assignment is applied.
    assert run.values["S1"][2] == pytest.approx(1.0)
    assert run.values["S1"][3] == pytest.approx(1.0)


def test_phase_boundary_on_the_official_grid_is_unsupported():
    validator = _load_validator("validate_sbml_test_suite")
    actions = _load_actions()
    block = actions.parse_action_block(ACTION_MODEL)

    reason = validator._phase_boundary_ambiguity(
        block,
        [0.0, 1.0, 2.5, 5.0],
        requested_ids=["S1"],
        target_symbols={"S1_amt"},
    )
    assert reason is not None
    assert "2.5" in reason

    # A boundary that does not move a requested quantity is not ambiguous.
    assert (
        validator._phase_boundary_ambiguity(
            block,
            [0.0, 1.0, 3.0, 5.0],
            requested_ids=["S1"],
            target_symbols={"S1_amt"},
        )
        is None
    )


def _write_stochastic_case(tmp_path: Path, *, columns: str = "X-mean,X-sd") -> dict:
    (tmp_path / "00001-settings.txt").write_text(
        "start: 0\n"
        "duration: 2\n"
        "steps: 2\n"
        "variables: X\n"
        "absolute: \n"
        "relative: \n"
        "amount: X\n"
        "concentration: \n"
        f"output: {columns}\n"
        "meanRange: (-3, 3)\n"
        "sdRange: (-5, 5)\n",
        encoding="utf-8",
    )
    (tmp_path / "00001-results.csv").write_text(
        "time,X-mean,X-sd\n0,100.00000,0.00000\n1,90.00000,4.00000\n2,80.00000,5.00000\n",
        encoding="utf-8",
    )
    source = tmp_path / "00001-sbml-l3v2.xml"
    source.write_text("<sbml/>", encoding="utf-8")
    return {"category": "stochastic", "id": "00001", "path": source}


def test_stochastic_reference_reader_reads_the_official_statistics(tmp_path):
    validator = _load_validator("validate_sbml_test_suite")
    case = _write_stochastic_case(tmp_path)

    reference = validator._read_stochastic_reference_case(case)

    assert reference["times"].tolist() == [0.0, 1.0, 2.0]
    assert reference["outputs"] == [("X", "mean"), ("X", "sd")]
    assert reference["mean_range"] == (-3.0, 3.0)
    assert reference["sd_range"] == (-5.0, 5.0)
    assert reference["expected"]["X-mean"].tolist() == [100.0, 90.0, 80.0]
    assert reference["expected"]["X-sd"].tolist() == [0.0, 4.0, 5.0]


def test_stochastic_reference_reader_rejects_a_missing_statistic(tmp_path):
    validator = _load_validator("validate_sbml_test_suite")
    case = _write_stochastic_case(tmp_path)
    (tmp_path / "00001-settings.txt").write_text(
        (tmp_path / "00001-settings.txt")
        .read_text(encoding="utf-8")
        .replace("output: X-mean,X-sd", "output: X-mean,X-sd,y-mean"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        validator._read_stochastic_reference_case(case)


def _statistics(samples, expected_mean, expected_sd, **kwargs):
    validator = _load_validator("validate_sbml_test_suite")
    array = np.asarray(samples, dtype=float)
    mean = array.mean(axis=0)
    # The DSMTS estimator: the 1/n sum of squared deviations.
    deviation = np.sqrt(np.mean((array - mean) ** 2, axis=0))
    options = {
        "statistic": "mean",
        "mean_range": (-3.0, 3.0),
        "sd_range": (-5.0, 5.0),
        "mean_resolution": 0.0,
    }
    options.update(kwargs)
    return validator._stochastic_statistics(
        mean,
        deviation,
        np.asarray(expected_mean, dtype=float),
        np.asarray(expected_sd, dtype=float),
        runs=int(array.shape[0]),
        **options,
    )


def test_stochastic_statistics_accepts_an_ensemble_that_matches_the_reference():
    rng = np.random.default_rng(7)
    expected_mean = [100.0, 90.0, 80.0]
    expected_sd = [4.0, 4.0, 4.0]
    samples = np.asarray(
        [
            rng.normal(expected_mean[index], expected_sd[index], 4000)
            for index in range(3)
        ]
    ).T

    mean_result = _statistics(samples, expected_mean, expected_sd)
    sd_result = _statistics(samples, expected_mean, expected_sd, statistic="sd")

    # Under a correct simulator the standardised statistics are standard
    # normal, so they stay inside the official acceptance ranges.
    assert mean_result["mean_violations"] == []
    assert sd_result["sd_violations"] == []
    assert max(abs(value) for value in mean_result["mean_statistics"]) < 4.0
    assert max(abs(value) for value in sd_result["sd_statistics"]) < 5.0


def test_stochastic_statistics_rejects_a_biased_ensemble():
    expected_mean = [100.0, 90.0, 80.0]
    expected_sd = [4.0, 4.0, 4.0]
    # A 10 % bias in the mean is far outside the official acceptance range.
    samples = np.tile(np.asarray(expected_mean) + 10.0, (4000, 1))

    result = _statistics(samples, expected_mean, expected_sd)

    assert len(result["mean_violations"]) == 3
    assert all(abs(entry["statistic"]) > 3.0 for entry in result["mean_violations"])


def test_stochastic_statistics_use_the_ensemble_size():
    """The DSMTS statistics are standardised by the number of repetitions."""

    expected_mean = [100.0]
    expected_sd = [4.0]
    # The same sample statistics with a larger ensemble give a larger
    # standardised deviation, because the statistic carries sqrt(n).
    samples = np.tile(np.asarray([110.0]), (100, 1))
    small = _statistics(samples, expected_mean, expected_sd)
    large = _statistics(
        np.tile(np.asarray([110.0]), (10_000, 1)), expected_mean, expected_sd
    )

    assert small["mean_statistics"][0] == pytest.approx(10.0 * math.sqrt(100) / 4.0)
    assert large["mean_statistics"][0] == pytest.approx(10.0 * math.sqrt(10_000) / 4.0)


def test_stochastic_statistics_flags_a_deterministic_reference_mismatch():
    expected_mean = [100.0, 90.0]
    expected_sd = [0.0, 4.0]
    # The reference reports a deterministic quantity, so the ensemble has to be
    # degenerate and has to reproduce the reference mean.
    samples = np.asarray([[99.0] * 100, list(np.linspace(88.0, 92.0, 100))]).T

    result = _statistics(samples, expected_mean, expected_sd)

    assert result["deterministic_failures"]
    assert result["deterministic_failures"][0]["index"] == 0

    # A spread ensemble at a deterministic reference point is a failure too.
    spread_samples = np.asarray(
        [list(np.linspace(99.5, 100.5, 100)), list(np.linspace(88.0, 92.0, 100))]
    ).T
    spread_result = _statistics(spread_samples, expected_mean, expected_sd)
    assert spread_result["deterministic_failures"]
    assert spread_result["deterministic_failures"][0]["index"] == 0


def test_stochastic_violation_criterion_follows_the_official_ranges():
    validator = _load_validator("validate_sbml_test_suite")
    # The official ranges imply the null violation probability.
    assert validator._standard_normal_outside((-3.0, 3.0)) == pytest.approx(
        0.0026998, rel=1e-3
    )
    assert validator._standard_normal_outside((-5.0, 5.0)) < 1e-5
    # A single violation among 100 tests is expected under the null.
    assert (
        validator._binomial_upper_tail(100, 0.0026998, 1)
        > validator.STOCHASTIC_CASE_ERROR_RATE
    )
    # A large violation count is not expected under the null.
    assert (
        validator._binomial_upper_tail(100, 0.0026998, 10)
        < validator.STOCHASTIC_CASE_ERROR_RATE
    )


def test_stochastic_run_budget_and_seeds_are_documented():
    validator = _load_validator("validate_sbml_test_suite")
    assert validator.STOCHASTIC_DEFAULT_RUNS >= 1000
    assert validator.STOCHASTIC_ACTION_RUNS >= 1000
    assert validator.STOCHASTIC_SEED_BASE > 0
    assert validator.STOCHASTIC_CASE_ERROR_RATE > 0
    assert validator.STOCHASTIC_CASE_ERROR_RATE < 0.01


def test_batched_ensemble_is_used_only_for_single_phase_action_blocks():
    validator = _load_validator("validate_sbml_test_suite")
    actions = _load_actions()
    block = actions.parse_action_block(ACTION_MODEL)

    # Two phases with an assignment: the batched sampler cannot execute the
    # scheduled action, so the harness has to use the action ensemble.
    assert not validator._stochastic_batch_applicable(
        block, {"S1": "S1_amt"}, {"S1_amt"}
    )

    single = actions.ActionBlock(
        phases=(block.phases[0],),
        assignments=((0, ()),),
        start_line=block.start_line,
        end_line=block.end_line,
    )
    assert validator._stochastic_batch_applicable(single, {"S1": "S1_amt"}, {"S1_amt"})
    # A target that is not a plain observable is not available either.
    assert not validator._stochastic_batch_applicable(
        single, {"S1": "S1_amt / C_amt"}, {"S1_amt"}
    )


def test_batched_ssa_ensemble_reports_the_official_statistics():
    """The batched sampler returns the mean/sd the official reference holds."""

    validator = _load_validator("validate_sbml_test_suite")
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    model_text = """begin model
begin compartments
  compartment 3 1
end compartments
begin molecule types
  M_X()
end molecule types
begin seed species
  @compartment:M_X() 100
end seed species
begin observables
  Species X_amt @compartment:M_X()
end observables
begin reaction rules
  birth: @compartment:M_X() -> @compartment:M_X() + @compartment:M_X() 0.1
  death: @compartment:M_X() -> 0 0.11
end reaction rules
end model
"""
    model = cpp.parse_string(model_text)
    network = cpp.generate_network(model, max_iter=100)
    assert network.num_reactions == 2

    reference = {
        "start": 0.0,
        "duration": 50.0,
        "steps": 50,
        "times": np.linspace(0.0, 50.0, 51),
    }
    ensemble = validator._stochastic_batch_ensemble(
        cpp,
        model,
        network,
        reference,
        {"X": "X_amt"},
        runs=2000,
        seed=validator.STOCHASTIC_SEED_BASE,
        backend=None,
    )

    assert ensemble["engine"] == "cpu:batch"
    mean = ensemble["values"]["X"]["mean"]
    deviation = ensemble["values"]["X"]["sd"]
    assert mean.shape == (51,)
    assert mean[0] == pytest.approx(100.0)
    # The analytic birth-death mean at t=50 is 100*exp(-0.01*50).
    assert mean[50] == pytest.approx(100.0 * math.exp(-0.5), rel=0.05)
    # The batched sampler reports single-precision statistics, so the
    # deterministic initial point carries a rounding-sized spread.
    assert deviation[0] <= 1e-3 * max(1.0, abs(float(mean[0])))
    assert deviation[50] > 0.0
    assert ensemble["metrics"]["batch_size"] == 2000


def test_gpu_backend_selection_is_explicit():
    validator = _load_validator("validate_sbml_test_suite")
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    backends = validator._gpu_backend_names(cpp)
    assert isinstance(backends, list)
    for name in backends:
        assert name in {"metal", "cuda"}


def test_stochastic_ensemble_is_reproducible_for_a_fixed_seed():
    """A conformance verdict must be reproducible from its recorded seed."""

    validator = _load_validator("validate_sbml_test_suite")
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    model_text = """begin model
begin compartments
  compartment 3 1
end compartments
begin molecule types
  M_X()
end molecule types
begin seed species
  @compartment:M_X() 100
end seed species
begin observables
  Species X_amt @compartment:M_X()
end observables
begin reaction rules
  birth: @compartment:M_X() -> @compartment:M_X() + @compartment:M_X() 0.1
  death: @compartment:M_X() -> 0 0.11
end reaction rules
end model
"""
    model = cpp.parse_string(model_text)
    network = cpp.generate_network(model, max_iter=100)
    reference = {
        "start": 0.0,
        "duration": 10.0,
        "steps": 10,
        "times": np.linspace(0.0, 10.0, 11),
    }
    runs = []
    for _ in range(2):
        ensemble = validator._stochastic_batch_ensemble(
            cpp,
            model,
            network,
            reference,
            {"X": "X_amt"},
            runs=200,
            seed=validator.STOCHASTIC_SEED_BASE,
            backend=None,
        )
        runs.append(ensemble["values"]["X"]["mean"].tolist())
    assert runs[0] == runs[1]
    # The harness uses a single CPU worker so the ensemble stays reproducible.
    assert validator.STOCHASTIC_CPU_THREADS == 1


def test_harness_side_gaps_name_the_harness_limitation():
    """A gap the harness cannot close must say so in a classifiable way.

    The campaign's expectation manifest classifies a gap by the harness's own
    reason text, so a harness-side gap has to name the harness limitation
    rather than read like a model-level refusal.
    """

    validator = _load_validator("validate_sbml_test_suite")
    actions = _load_actions()
    block = actions.parse_action_block(ACTION_MODEL)

    boundary = validator._phase_boundary_ambiguity(
        block,
        [0.0, 1.0, 2.5, 5.0],
        requested_ids=["S1"],
        target_symbols={"S1_amt"},
    )
    assert boundary is not None
    assert "scheduled actions" in boundary

    # The manifest's harness-side needles.
    assert "repeated-run mean" in (
        "the official stochastic reference requests the repeated-run mean of X "
        "without its standard deviation"
    )


def test_a_degenerate_generated_network_is_never_reported_as_agreement():
    """A flat trajectory over a model with no reaction is not a pass."""

    validator = _load_validator("validate_sbml_test_suite")
    empty_network = SimpleNamespace(num_reactions=0)
    source_with_reaction = SimpleNamespace(reactions={"J0": object()})

    reason = validator._degenerate_network_reason(empty_network, source_with_reaction)
    assert reason is not None
    assert "no reaction" in reason
    assert "not comparable" in reason

    # A network with reactions is not degenerate, and a source model without
    # reactions has nothing to lose.
    assert (
        validator._degenerate_network_reason(
            SimpleNamespace(num_reactions=2), source_with_reaction
        )
        is None
    )
    assert (
        validator._degenerate_network_reason(
            empty_network, SimpleNamespace(reactions={})
        )
        is None
    )


def test_official_parameter_mapping_uses_the_standardized_identifier():
    validator = _load_validator("validate_sbml_test_suite")
    parsed = type(
        "Parsed",
        (),
        {
            "species": {},
            "compartments": {},
            "parameters": {"param_id": object()},
            "rules": [],
        },
    )()

    target = validator._reference_output_target(
        "param",
        {"amount": [], "concentration": []},
        parsed,
        {},
        lambda name: name + "_id" if name == "param" else name,
    )

    assert target == "param_id"


def test_official_reaction_output_has_no_bngl_mapping():
    """BNGL has no reaction-rate observable, so reaction ids stay unmapped."""

    validator = _load_validator("validate_sbml_test_suite")
    parsed = type(
        "Parsed",
        (),
        {
            "species": {},
            "compartments": {},
            "parameters": {},
            "rules": [],
        },
    )()

    target = validator._reference_output_target(
        "J1",
        {"amount": [], "concentration": []},
        parsed,
        {},
        lambda name: name,
    )

    assert target is None


def test_bngl_observable_grammar_has_no_reaction_observable():
    """The BNGL observable grammar cannot express a reaction extent."""

    grammar = (Path(__file__).parents[2] / "cpp" / "parser" / "BNGParser.g4").read_text(
        encoding="utf-8"
    )
    rule = grammar.split("observable_type\n", 1)[1].split(";", 1)[0]
    assert "MOLECULES" in rule
    assert "SPECIES" in rule
    assert "COUNTER" in rule
    assert "REACTION" not in rule
    assert "RATE" not in rule
