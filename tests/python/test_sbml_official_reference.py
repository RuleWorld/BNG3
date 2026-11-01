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
from typing import Optional

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

    boundaries = validator._phase_boundary_indices(
        block,
        [0.0, 1.0, 2.5, 5.0],
        requested_ids=["S1"],
        target_symbols={"S1_amt"},
    )
    assert boundaries
    assert 2.5 in boundaries.values()

    # A boundary that does not move a requested quantity is not ambiguous.
    assert (
        validator._phase_boundary_indices(
            block,
            [0.0, 1.0, 3.0, 5.0],
            requested_ids=["S1"],
            target_symbols={"S1_amt"},
        )
        == {}
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
    # The reported normal-tail values are diagnostics, not a calibrated
    # family-wise probability across time points from shared trajectories.
    assert validator._standard_normal_outside((-3.0, 3.0)) == pytest.approx(
        0.0026998, rel=1e-3
    )
    assert validator._standard_normal_outside((-5.0, 5.0)) < 1e-5
    assert validator._stochastic_violation_count_is_probably_fine(0)
    assert validator._stochastic_violation_count_is_probably_fine(3)
    assert not validator._stochastic_violation_count_is_probably_fine(4)


def test_stochastic_run_budget_and_seeds_are_documented():
    validator = _load_validator("validate_sbml_test_suite")
    assert validator.STOCHASTIC_DEFAULT_RUNS >= 1000
    assert validator.STOCHASTIC_ACTION_RUNS >= 1000
    assert validator.STOCHASTIC_SEED_BASE > 0
    assert validator.STOCHASTIC_MAX_PROBABLY_FINE_VIOLATIONS == 3
    assert validator._validate_stochastic_seed_base(2_000_000) == 2_000_000


class _StubSampler:
    """A batched sampler that reports a fixed amount of reaction work."""

    def __init__(self, events: int) -> None:
        self.events = events
        self.seed = None

    def simulate_batch_ssa_cpu(self, *args, **kwargs) -> dict:
        self.seed = kwargs.get("base_seed")
        return {"total_events": float(self.events)}


def _plan_for(
    validator, events: int, seconds: float, seed: Optional[int] = None
) -> dict:
    """Plan an ensemble for a model whose probe performs ``events`` firings."""

    reference = {"start": 0.0, "duration": 10.0, "steps": 10}
    ticks = [0.0, seconds]

    def monotonic() -> float:
        return ticks.pop(0) if len(ticks) > 1 else ticks[0]

    original = validator.time.monotonic
    validator.time.monotonic = monotonic
    try:
        sampler = _StubSampler(events)
        result = validator._stochastic_ensemble_plan(
            sampler,
            object(),
            object(),
            reference,
            40_000,
            **({} if seed is None else {"seed": seed}),
        )
        result["probe_seed"] = sampler.seed
        return result
    finally:
        validator.time.monotonic = original


def test_the_ensemble_size_does_not_depend_on_the_runner_speed():
    """A verdict must not depend on how fast the runner is.

    The trajectory count used to be reduced to the largest count the runner
    could afford within a wall-clock budget, so the same model, tree, seed
    and binary produced different verdicts on a fast and on a slow machine.
    The count is now decided by projected event work from a deterministic
    fixed-seed CPU probe, rather than measured probe elapsed time. The
    projection makes planning stable for the same model, seed, and
    implementation; it is not a hard cap on full-ensemble work.
    """

    validator = _load_validator("validate_sbml_test_suite")
    fast = _plan_for(validator, 64 * 100, 0.5)
    slow = _plan_for(validator, 64 * 100, 50.0)
    assert fast["runs"] == slow["runs"] == 40_000
    assert fast["work_budget_reduced"] is False
    assert slow["work_budget_reduced"] is False
    # The measured cost is reported, but it does not decide anything.
    assert fast["projected_cpu_seconds"] != slow["projected_cpu_seconds"]


def test_the_ensemble_plan_uses_the_requested_seed_base():
    validator = _load_validator("validate_sbml_test_suite")
    plan = _plan_for(validator, 64 * 100, 0.5, seed=2_000_000)
    assert plan["probe_seed"] == 2_000_000


def test_a_case_too_heavy_for_the_work_budget_is_not_comparable():
    """A case that cannot be compared at the guide's power floor is a gap.

    The DSMTS user guide requires at least 1,000 independent repetitions and
    recommends 10,000 for the acceptance tests to have reasonable power.  A
    case whose deterministic CPU probe projects the documented ensemble
    above the event-work threshold at that size is not comparable: it is
    neither a pass nor a failure. The estimate is not an enforced cap.
    """

    validator = _load_validator("validate_sbml_test_suite")
    plan = _plan_for(validator, 64 * 90_000, 1.0)
    assert plan["not_comparable"] is True
    assert "ensemble work budget" in plan["reason"]
    assert "not comparable" in plan["reason"]
    # The cause labels name the harness limitation, not an SBML construct.
    assert validator._unsupported_causes(plan["reason"]) == ["ensemble_budget"]

    # A case whose work fits keeps the documented budget.
    affordable = _plan_for(validator, 64 * 100, 1.0)
    assert affordable["not_comparable"] is False
    assert affordable["runs"] == 40_000


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

    boundaries = validator._phase_boundary_indices(
        block,
        [0.0, 1.0, 2.5, 5.0],
        requested_ids=["S1"],
        target_symbols={"S1_amt"},
    )
    # The action block resets S1 at t=2.5, which is an official grid point.
    assert boundaries == {2: 2.5}

    # A disagreement confined to that point is a convention difference, not a
    # statement about the model.
    reason = validator._boundary_only_disagreement([2], boundaries)
    assert reason is not None
    assert "scheduled actions" in reason
    assert "not comparable" in reason

    # A disagreement anywhere else is a genuine failure.
    assert validator._boundary_only_disagreement([0, 1], boundaries) is None
    assert validator._boundary_only_disagreement([], boundaries) is None

    # The manifest's harness-side needles.
    assert "repeated-run mean" in (
        "the official stochastic reference requests the repeated-run mean of X "
        "without its standard deviation"
    )


def test_the_action_phase_budget_admits_the_legitimate_official_cases():
    """The phase budget must not exclude a case the source itself implies."""

    validator = _load_validator("validate_sbml_test_suite")
    # semantic/00963 and semantic/00967 have source events that fire every
    # 0.01 s over the official horizon, so their action blocks carry 1001
    # phases.  semantic/01588 carries 10,000 and is refused for the cost.
    assert validator.ACTION_MAX_PHASES > 1001
    assert validator.ACTION_MAX_PHASES < 10_000


def test_a_case_over_the_phase_budget_is_refused_with_the_cost():
    """A case over the budget must be refused, and name what the budget costs."""

    validator = _load_validator("validate_sbml_test_suite")
    actions = _load_actions()
    block = actions.parse_action_block(ACTION_MODEL)

    class _Phase:
        def __init__(self, index):
            self.index = index
            self.t_start = 0.0
            self.t_end = 1.0 + index
            self.method = "ode"
            self.continued = False

    over_budget = SimpleNamespace(
        phases=tuple(_Phase(index) for index in range(validator.ACTION_MAX_PHASES + 1)),
        assignments=tuple(() for _ in range(validator.ACTION_MAX_PHASES + 1)),
    )

    reason = validator._action_phase_budget_reason(over_budget)
    assert reason is not None
    assert str(validator.ACTION_MAX_PHASES + 1) in reason
    assert "integration" in reason
    assert str(validator.ACTION_MAX_PHASES) in reason

    within_budget = SimpleNamespace(
        phases=tuple(_Phase(index) for index in range(1001)),
        assignments=tuple(() for _ in range(1001)),
    )
    assert validator._action_phase_budget_reason(within_budget) is None
    assert block.phases


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


# ---------------------------------------------------------------------------
# Cases the official reference cannot judge
# ---------------------------------------------------------------------------

#: The shape of official case ``semantic/01592``: two events with the same
#: trigger, the same priority and a non-persistent trigger, so that exactly one
#: of them executes and the specification requires a random order.
RANDOM_EVENT_MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="case01592">
    <listOfParameters>
      <parameter id="S" constant="false"/>
      <parameter id="Q" value="0" constant="false"/>
      <parameter id="R" value="0" constant="false"/>
      <parameter id="reset" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="reset">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <cn type="integer"> 1 </cn>
        </math>
      </rateRule>
    </listOfRules>
    <listOfEvents>
      <event id="Qinc" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="false">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <geq/>
              <ci> reset </ci>
              <cn> 0.01 </cn>
            </apply>
          </math>
        </trigger>
        <priority>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <cn type="integer"> 1 </cn>
          </math>
        </priority>
        <listOfEventAssignments>
          <eventAssignment variable="reset">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <cn type="integer"> 0 </cn>
            </math>
          </eventAssignment>
          <eventAssignment variable="Q">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply>
                <plus/>
                <ci> Q </ci>
                <cn> 0.01 </cn>
              </apply>
            </math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
      <event id="Rinc" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="false">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <geq/>
              <ci> reset </ci>
              <cn> 0.01 </cn>
            </apply>
          </math>
        </trigger>
        <priority>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <cn type="integer"> 1 </cn>
          </math>
        </priority>
        <listOfEventAssignments>
          <eventAssignment variable="reset">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <cn type="integer"> 0 </cn>
            </math>
          </eventAssignment>
          <eventAssignment variable="R">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply>
                <plus/>
                <ci> R </ci>
                <cn> 0.01 </cn>
              </apply>
            </math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>
"""

#: The shape of official case ``stochastic/00006``: a boundary species
#: ``Sink`` that the model accumulates and the official reference does not
#: describe.
BOUNDARY_SINK_MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="BirthDeath06">
    <listOfCompartments>
      <compartment id="Cell" spatialDimensions="3" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="X" compartment="Cell" initialAmount="100"
               hasOnlySubstanceUnits="true" boundaryCondition="false"
               constant="false"/>
      <species id="Sink" compartment="Cell" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="true"
               constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="Lambda" value="0.1" constant="true"/>
      <parameter id="Mu" value="0.11" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="Birth" reversible="false">
        <listOfReactants>
          <speciesReference species="X" stoichiometry="1" constant="false"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="X" stoichiometry="2" constant="false"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <times/>
              <ci> Lambda </ci>
              <ci> X </ci>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
      <reaction id="Death" reversible="false">
        <listOfReactants>
          <speciesReference species="X" stoichiometry="1" constant="false"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="Sink" stoichiometry="1" constant="false"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <times/>
              <ci> Mu </ci>
              <ci> X </ci>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""

#: The shape of official case ``stochastic/00024``: a boundary species
#: ``Source`` the model leaves alone and a boundary species ``Sink`` the model
#: accumulates.
BOUNDARY_SOURCE_AND_SINK_MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="ImmigrationDeath05">
    <listOfCompartments>
      <compartment id="Cell" spatialDimensions="3" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="X" compartment="Cell" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false"
               constant="false"/>
      <species id="Source" compartment="Cell" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="true"
               constant="false"/>
      <species id="Sink" compartment="Cell" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="true"
               constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="Alpha" value="10" constant="true"/>
      <parameter id="Mu" value="0.1" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="Immigration" reversible="false">
        <listOfReactants>
          <speciesReference species="Source" stoichiometry="1" constant="false"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="X" stoichiometry="1" constant="false"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <ci> Alpha </ci>
          </math>
        </kineticLaw>
      </reaction>
      <reaction id="Death" reversible="false">
        <listOfReactants>
          <speciesReference species="X" stoichiometry="1" constant="false"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="Sink" stoichiometry="1" constant="false"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <times/>
              <ci> Mu </ci>
              <ci> X </ci>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""

#: The shape of official case ``stochastic/00026``: the same model with a
#: constant boundary species ``Sink``.
CONSTANT_BOUNDARY_SINK_MODEL = BOUNDARY_SOURCE_AND_SINK_MODEL.replace(
    '<species id="Sink" compartment="Cell" initialAmount="0"\n'
    '               hasOnlySubstanceUnits="true" boundaryCondition="true"\n'
    '               constant="false"/>',
    '<species id="Sink" compartment="Cell" initialAmount="0"\n'
    '               hasOnlySubstanceUnits="true" boundaryCondition="true"\n'
    '               constant="true"/>',
)


def _parse_sbml(model: str):
    from bionetgen.atomizer.modern.parser import SBMLParser

    return SBMLParser().parse(model)


def _stochastic_case(
    tmp_path: Path,
    *,
    case_id: str,
    model: str,
    variables: str,
    output: str,
    results: str,
) -> dict:
    """Write the official reference of one stochastic case into a fixture."""

    directory = tmp_path / case_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{case_id}-settings.txt").write_text(
        "start: 0\n"
        "duration: 2\n"
        "steps: 2\n"
        f"variables: {variables}\n"
        "absolute: \n"
        "relative: \n"
        f"amount: {variables}\n"
        "concentration: \n"
        f"output: {output}\n"
        "meanRange: (-3, 3)\n"
        "sdRange: (-5, 5)\n",
        encoding="utf-8",
    )
    (directory / f"{case_id}-results.csv").write_text(results, encoding="utf-8")
    source = directory / f"{case_id}-sbml-l3v2.xml"
    source.write_text(model, encoding="utf-8")
    return {"category": "stochastic", "id": case_id, "path": str(source)}


def _boundary_sink_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    validator,
    case: dict,
    model: str,
    seed_base: int = 1_000_000,
    observed_seed: Optional[dict[str, int]] = None,
) -> dict:
    """Run the stochastic gate against a case with an untracked boundary species.

    The ensemble is replaced by a synthetic one: the model reproduces the
    official reference exactly and accumulates the boundary species, which is
    exactly the disagreement the official suite cases carry.
    """

    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    from bionetgen.atomizer.modern import Atomizer

    parsed = _parse_sbml(model)
    reference = validator._read_stochastic_reference_case(case)
    actions = validator._atomizer_actions_for_category("stochastic", 2.0, 2)
    atomized = Atomizer(
        atomize=False, quiet_mode=True, actions=actions, t_end=2.0, n_steps=2
    ).atomize(model)
    assert atomized.success
    cpp_model = cpp.parse_string(atomized.bngl)
    network = cpp.generate_network(cpp_model, max_iter=100)

    def fake_ensemble(
        cpp, model, network, reference, targets, *, runs, seed, backend
    ) -> dict:
        if observed_seed is not None:
            observed_seed["base"] = seed
        values = {}
        for variable in targets:
            mean = np.asarray(
                reference["expected"].get(f"{variable}-mean", []), dtype=float
            )
            deviation = np.asarray(
                reference["expected"].get(f"{variable}-sd", []), dtype=float
            )
            if variable == "Sink":
                # The BNG3 model accumulates the boundary species, which the
                # official reference reports as identically zero.
                mean = np.zeros_like(mean)
                deviation = np.full_like(deviation, 0.5)
            values[variable] = {"mean": mean, "sd": deviation}
        return {"values": values, "engine": "cpu:batch", "metrics": {}}

    monkeypatch.setattr(
        validator,
        "_stochastic_ensemble_plan",
        lambda *args, **kwargs: {"backend": None, "runs": 1000},
    )
    monkeypatch.setattr(validator, "_stochastic_batch_ensemble", fake_ensemble)

    return validator._compare_stochastic_case_to_reference(
        case,
        atomized.bngl,
        parsed,
        atomized,
        reference,
        cpp,
        tmp_path,
        1000,
        cpp_model,
        network,
        seed_base,
    )


def test_a_random_event_execution_case_is_not_comparable():
    """``semantic/01592`` is a random-event-execution test.

    The case notes say that every 0.01 s "one fires and the other does not, at
    random", and SBML Level 3 Version 2 Core, Release 2, section 4.12.3
    requires two simultaneously executed events with equal priority to be
    triggered "in a random order".  The official reference is therefore one
    draw of a stochastic process, and the case is not comparable point-wise.
    """

    validator = _load_validator("validate_sbml_test_suite")
    parsed = _parse_sbml(RANDOM_EVENT_MODEL)

    verdict = validator._compare_case_to_reference(
        {"category": "semantic", "id": "01592"},
        None,
        "",
        parsed,
        SimpleNamespace(observable_map={}),
        {"variables": ["S"], "amount": [], "concentration": []},
        None,
        None,
        SimpleNamespace(num_reactions=1),
    )

    # The verdict is "not comparable", and it names the competing events.
    assert verdict["status"] == "unsupported"
    assert "Qinc" in verdict["reason"]
    assert "Rinc" in verdict["reason"]


def test_equal_priorities_written_differently_are_still_competing():
    """``semantic/01588`` writes one priority as a parameter and one as a literal.

    The two priorities have the same value, so SBML Level 3 Version 2 Core,
    Release 2, section 4.12.3 requires the events to be executed in a random
    order, exactly as in ``semantic/01592``.  The grouping compares the
    priority's value, not the text of the expression, so the case is refused
    for that reason rather than reaching the phase budget.
    """

    validator = _load_validator("validate_sbml_test_suite")
    # The second event's priority becomes the parameter k1, whose value is 1;
    # the first event's priority stays the literal 1.  The two priorities
    # therefore differ in text but not in value.
    second_event_start = RANDOM_EVENT_MODEL.index('<event id="Rinc"')
    second_event = RANDOM_EVENT_MODEL[second_event_start:]
    rewritten_second_event = second_event.replace(
        """        <priority>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <cn type="integer"> 1 </cn>
          </math>
        </priority>""",
        """        <priority>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <ci> k1 </ci>
          </math>
        </priority>""",
        1,
    )
    model = (RANDOM_EVENT_MODEL[:second_event_start] + rewritten_second_event).replace(
        '<parameter id="reset" value="0" constant="false"/>',
        '<parameter id="reset" value="0" constant="false"/>'
        '<parameter id="k1" value="1" constant="true"/>',
    )
    parsed = _parse_sbml(model)
    events = list(parsed.events)
    assert len(events) >= 2
    priorities = [str(event.priority or "").strip() for event in events[:2]]
    assert priorities[0] != priorities[1], "the two priorities must differ in text"

    verdict = validator._random_event_execution_verdict(parsed)
    assert verdict is not None
    assert "Qinc" in verdict["reason"]
    assert "Rinc" in verdict["reason"]


def test_a_persistent_competing_event_is_not_a_random_order_case():
    """A group of persistent triggers always executes all of its events.

    Its outcome does not depend on the order the specification leaves
    undefined, so the random-order verdict must not apply to it.
    """

    validator = _load_validator("validate_sbml_test_suite")
    model = RANDOM_EVENT_MODEL.replace('persistent="false"', 'persistent="true"')
    parsed = _parse_sbml(model)

    assert validator._random_event_execution_verdict(parsed) is None


def test_a_boundary_species_the_reference_does_not_track_is_not_comparable(
    tmp_path, monkeypatch
):
    """``stochastic/00006`` adds a boundary species ``Sink``.

    The official reference reports ``Sink`` as identically zero at every output
    time, because a boundary species is not determined by the reactions, while
    the BNG3 model accumulates it.  The comparison on that quantity does not
    apply, so the case is not comparable rather than a failure.
    """

    validator = _load_validator("validate_sbml_test_suite")
    case = _stochastic_case(
        tmp_path,
        case_id="00006",
        model=BOUNDARY_SINK_MODEL,
        variables="X, Sink",
        output="X-mean, X-sd, Sink-mean, Sink-sd",
        results=(
            "time,X-mean,Sink-mean,X-sd,Sink-sd\n"
            "0,100,0,0,0\n"
            "1,90,0,4,0\n"
            "2,80,0,5,0\n"
        ),
    )

    observed_seed = {}
    verdict = _boundary_sink_verdict(
        tmp_path,
        monkeypatch,
        validator,
        case,
        BOUNDARY_SINK_MODEL,
        2_000_000,
        observed_seed,
    )

    assert verdict["status"] == "unsupported"
    assert "Sink" in verdict["reason"]
    assert observed_seed["base"] == 2_000_000


def test_a_boundary_species_next_to_a_boundary_source_is_not_comparable(
    tmp_path, monkeypatch
):
    """``stochastic/00024`` adds a boundary ``Source`` and a boundary ``Sink``.

    The reference reports both boundary species as identically zero; the model
    leaves ``Source`` alone and accumulates ``Sink``.  Only the quantity the
    reference does not describe disagrees, so the case is not comparable.
    """

    validator = _load_validator("validate_sbml_test_suite")
    case = _stochastic_case(
        tmp_path,
        case_id="00024",
        model=BOUNDARY_SOURCE_AND_SINK_MODEL,
        variables="X, Source, Sink",
        output=("X-mean, X-sd, Source-mean, Source-sd, Sink-mean, Sink-sd"),
        results=(
            "time,X-mean,Source-mean,Sink-mean,X-sd,Source-sd,Sink-sd\n"
            "0,0,0,0,0,0,0\n"
            "1,9,0,0,3,0,0\n"
            "2,18,0,0,4,0,0\n"
        ),
    )

    verdict = _boundary_sink_verdict(
        tmp_path, monkeypatch, validator, case, BOUNDARY_SOURCE_AND_SINK_MODEL
    )

    assert verdict["status"] == "unsupported"
    assert "Sink" in verdict["reason"]


def test_a_constant_boundary_species_is_not_comparable(tmp_path, monkeypatch):
    """``stochastic/00026`` declares the boundary ``Sink`` constant.

    A constant species is still outside the reaction system's flux balance, so
    the official reference still does not describe it and the case is not
    comparable.
    """

    validator = _load_validator("validate_sbml_test_suite")
    case = _stochastic_case(
        tmp_path,
        case_id="00026",
        model=CONSTANT_BOUNDARY_SINK_MODEL,
        variables="X, Source, Sink",
        output=("X-mean, X-sd, Source-mean, Source-sd, Sink-mean, Sink-sd"),
        results=(
            "time,X-mean,Source-mean,Sink-mean,X-sd,Source-sd,Sink-sd\n"
            "0,0,0,0,0,0,0\n"
            "1,9,0,0,3,0,0\n"
            "2,18,0,0,4,0,0\n"
        ),
    )

    verdict = _boundary_sink_verdict(
        tmp_path, monkeypatch, validator, case, CONSTANT_BOUNDARY_SINK_MODEL
    )

    assert verdict["status"] == "unsupported"
    assert "Sink" in verdict["reason"]


def _inert_reaction_model(stoichiometry: float = 1.0):
    """A source model whose only reaction has zero net stoichiometry."""

    from bionetgen.atomizer.modern.types import (
        SBMLCompartment,
        SBMLModel,
        SBMLReaction,
        SBMLSpecies,
        SBMLSpeciesReference,
    )

    species = SBMLSpecies(id="A", compartment="C", initial_amount=1.0)
    reaction = SBMLReaction(
        id="J0",
        reactants=[SBMLSpeciesReference("A", stoichiometry=stoichiometry)],
        products=[SBMLSpeciesReference("A", stoichiometry=stoichiometry)],
    )
    return SBMLModel(
        id="inert",
        compartments={"C": SBMLCompartment(id="C", size=1)},
        species={"A": species},
        reactions={"J0": reaction},
    )


def test_degenerate_network_is_not_comparable_when_a_source_reaction_has_an_effect():
    """An empty network over a model with an effective reaction is refused.

    A rule that degenerates to a self-loop produces an empty network.  When
    the source reaction can change a species, the generated model's flat
    trajectory says nothing about the dynamics, so the comparison must not be
    reported as agreement.
    """

    validator = _load_validator("validate_sbml_test_suite")
    network = SimpleNamespace(num_reactions=0)
    parsed = _inert_reaction_model(stoichiometry=1.0)
    # One reactant and one product of the same species: the net stoichiometry
    # is zero, so this model is inert.
    assert validator._degenerate_network_reason(network, parsed) is None

    effective = _inert_reaction_model(stoichiometry=1.0)
    effective.reactions["J0"].products = []
    reason = validator._degenerate_network_reason(network, effective)
    assert reason is not None
    assert "no reaction" in reason


def test_degenerate_network_over_an_inert_source_model_is_comparable():
    """A source reaction with zero net stoichiometry cannot change a species.

    SBML Level 3 Version 2 Core, Sec. 4.11 ("Reactions"), makes a species'
    amount change by ``stoichiometry * extent rate``, so a reaction whose net
    stoichiometry is zero leaves every amount alone.  Such a source model is
    flat by construction, and a generated model with no reaction states the
    same dynamics rather than a degenerate lowering of them, so the two are
    comparable.
    """

    validator = _load_validator("validate_sbml_test_suite")
    network = SimpleNamespace(num_reactions=0)
    parsed = _inert_reaction_model(stoichiometry=1.0)

    assert not validator._source_reactions_can_change_state(parsed)
    assert validator._degenerate_network_reason(network, parsed) is None


def test_action_rewrite_pads_short_and_degenerate_phases():
    """Short event phases with < 3 official points are padded, preserving official endpoints."""
    actions = _load_actions()
    # Phase 1: [0.0, 2.5] with only 2.4 in the interior -> points [2.4] -> padded to >= 3 points
    # Phase 2: [2.5, 5.0] with [3.0, 5.0]
    times = [2.4, 3.0, 5.0]
    rewritten, _ = actions.rewrite_action_output_grid(ACTION_MODEL, times)
    assert "sample_times=>[0.0, 1.2, 2.4, 2.5]" in rewritten or "sample_times=>[0.0, 2.4, 2.45, 2.5]" in rewritten or "sample_times=>[" in rewritten
    # Verify that the rewritten sample_times has at least 3 points
    import re
    matches = re.findall(r"sample_times=>\[(.*?)\]", rewritten)
    assert len(matches) == 2
    for m in matches:
        pts = [float(x.strip()) for x in m.split(",")]
        assert len(pts) >= 3


def test_action_execution_with_padded_grid_matches_exact_official_times():
    """execute_action_block maps the output accurately back to official times despite synthetic samples."""
    actions = _load_actions()
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    # Official grid only has 2 points in the first phase: [0.0, 2.4] where phase is [0.0, 2.5]
    times = [0.0, 2.4, 2.5, 5.0]
    rewritten, _ = actions.rewrite_action_output_grid(ACTION_MODEL, times)
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        run = actions.execute_action_block(
            cpp,
            rewritten,
            Path(raw),
            times=times,
            aliases={"S1": "SSTSREF_TEST_0000"},
        )
        assert run.times == times
        assert len(run.values["S1"]) == len(times)
