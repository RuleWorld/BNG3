"""Specification-derived oracle for SBML Test Suite semantic/00966.

The official reference trajectory is not a pointwise oracle: Rinc and Qinc
have equal priority, and firing either one resets the shared nonpersistent
trigger of the other. The source contract below is read and verified with
libSBML; the expected tie law follows from the two symmetric event choices.
"""

from __future__ import annotations

import hashlib
import ast
import math
from pathlib import Path
from typing import Any

import libsbml
import numpy as np
from scipy.stats import binomtest

BLOCK_SIZE = 16
FLIPS_PER_RUN = 100_000
BLOCKS_PER_RUN = FLIPS_PER_RUN // BLOCK_SIZE
SEEDS = tuple(range(1, 17))
ALPHA_FAMILYWISE = 1e-6
HYPOTHESES_PER_SEED = 18  # total Q plus the 17 source-defined histogram bins
FAMILY_SIZE = len(SEEDS) * HYPOTHESES_PER_SEED
PER_TEST_ALPHA = ALPHA_FAMILYWISE / FAMILY_SIZE
INCREMENT = 0.01
SOURCE_RELATIVE_PATH = Path(__file__).with_name("semantic-00966-source.xml")
SETTINGS_RELATIVE_PATH = Path(__file__).with_name("semantic-00966-settings.txt")
SOURCE_SHA256 = "ca548837a5bd90def8861db03cc287849ce2b46084de438938d80e431bd28262"
SETTINGS_SHA256 = "1004504c1034c3d0141221ff9cd8b4c2e57f2932a7515840222c87f6c1a13053"


class SourceContractError(ValueError):
    """The supplied official SBML source does not have the checked semantics."""


def _formula(sbase: Any) -> str:
    return libsbml.formulaToL3String(sbase.getMath())


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceContractError(message)


def _assignments(event: Any) -> dict[str, str]:
    return {
        event.getEventAssignment(index).getVariable(): _formula(
            event.getEventAssignment(index)
        )
        for index in range(event.getNumEventAssignments())
    }


def validate_source(source_path: str | Path = SOURCE_RELATIVE_PATH) -> dict[str, Any]:
    """Validate source syntax and the exact event structures used by the oracle."""
    path = Path(source_path)
    document = libsbml.readSBMLFromFile(str(path))
    _require(document is not None and document.getModel() is not None, "SBML parse failed")
    document.checkConsistency()
    errors = [
        document.getError(index).getMessage()
        for index in range(document.getNumErrors())
        if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    _require(not errors, "libSBML reports source errors: " + " | ".join(errors))
    model = document.getModel()

    parameters = {model.getParameter(i).getId(): model.getParameter(i) for i in range(model.getNumParameters())}
    for name in ("Q", "R"):
        _require(name in parameters, f"missing parameter {name}")
        _require(parameters[name].getValue() == 0.0, f"{name} must start at zero")
        _require(not parameters[name].getConstant(), f"{name} must be mutable")
    _require(model.getNumRules() == 1, "expected one source assignment rule")
    rule = model.getRule(0)
    _require(rule.isAssignment() and rule.getVariable() == "S", "expected assignment rule S")
    _require(_formula(rule) == "Q + R", "source invariant must be S = Q + R")

    events = {model.getEvent(i).getId(): model.getEvent(i) for i in range(model.getNumEvents())}
    _require(model.getNumEvents() == 23, "expected 23 source events")
    tie_names = ("Rinc", "Qinc")
    tie = [events.get(name) for name in tie_names]
    _require(all(tie), "missing one of the equal-priority increment events")
    tie_trigger = "(time - reset) >= 0.01"
    for event, amount in zip(tie, ("R", "Q")):
        _require(event.isSetTrigger() and _formula(event.getTrigger()) == tie_trigger,
                 f"{event.getId()} trigger differs from the source contract")
        _require(not event.getTrigger().getPersistent(), f"{event.getId()} must be nonpersistent")
        _require(event.getTrigger().getInitialValue(), f"{event.getId()} trigger initial value changed")
        _require(event.getUseValuesFromTriggerTime(), f"{event.getId()} must use trigger-time values")
        _require(event.isSetPriority() and _formula(event.getPriority()) == "10",
                 f"{event.getId()} priority differs from the tie")
        assignments = _assignments(event)
        expected = {"reset": "time", "chicount": "chicount + 1", amount: f"{amount} + 0.01"}
        if amount == "Q":
            expected["chitest"] = "chitest + 1"
        _require(assignments == expected, f"{event.getId()} assignments differ from source contract")

    repeat = events.get("repeat")
    _require(repeat is not None, "missing repeat event")
    _require(_formula(repeat.getTrigger()) == "floor(chicount / 16) >= 1",
             "repeat trigger differs from the 16-event source block")
    _require(repeat.isSetPriority() and _formula(repeat.getPriority()) == "5",
             "repeat priority differs from source")
    _require(_assignments(repeat) == {"assemble": "1.5", "chicount": "0"},
             "repeat assignments differ from source")

    for count in range(BLOCK_SIZE + 1):
        event = events.get(f"_E{count}")
        _require(event is not None, f"missing histogram event _E{count}")
        expected_trigger = f"(assemble >= 1) && (chitest == {count})"
        _require(_formula(event.getTrigger()) == expected_trigger,
                 f"histogram event _E{count} has changed trigger")
        _require(_assignments(event) == {f"chi{count}": f"chi{count} + 1"},
                 f"histogram event _E{count} has changed counter")

    classify = events.get("_E17")
    _require(classify is not None and _formula(classify.getTrigger()) == "assemble >= 1",
             "missing source histogram-classification event")
    _require(classify.isSetPriority() and _formula(classify.getPriority()) == "1",
             "classification priority differs from source")
    _require(_assignments(classify) == {
        "tests": "tests + 1", "chitest": "0", "assemble": "0"
    }, "classification assignments differ from source")

    evaluate = events.get("_E18")
    expected_call = "calculateerror(" + ", ".join(f"chi{i}" for i in range(17)) + ")"
    _require(evaluate is not None and _formula(evaluate.getTrigger()) == "(tests >= 6240) && (finalchi == 0)",
             "final chi-square trigger differs from source")
    _require(evaluate.isSetPriority() and _formula(evaluate.getPriority()) == "0",
             "final chi-square priority differs from source")
    _require(_assignments(evaluate) == {"finalchi": expected_call},
             "final chi-square calculation differs from source")

    error_event = events.get("error_check")
    _require(error_event is not None and _formula(error_event.getTrigger()) == "finalchi > 50",
             "source error trigger differs from finalchi > 50")
    _require(error_event.isSetPriority() and _formula(error_event.getPriority()) == "-1",
             "source error-event priority differs")
    _require(_assignments(error_event) == {"error": "1"},
             "source error-event assignment differs")

    calculation = model.getFunctionDefinition("calculateerror")
    _require(calculation is not None, "missing source calculateerror function")
    function_math = calculation.getMath()
    _require(function_math.getNumChildren() == BLOCK_SIZE + 2,
             "calculateerror must accept 17 histogram counters")
    _require(
        [function_math.getChild(i).getName() for i in range(BLOCK_SIZE + 1)]
        == [f"x{i}" for i in range(BLOCK_SIZE + 1)],
        "calculateerror argument order differs from source histogram order",
    )

    _require("S" in parameters, "missing derived S parameter")
    unit_roundoff = np.finfo(float).eps / 2
    gamma_n = (FLIPS_PER_RUN * unit_roundoff) / (1 - FLIPS_PER_RUN * unit_roundoff)
    # Standard floating-point summation bound for at most 100000 additions of
    # 0.01, plus one final Q+R addition at a magnitude no greater than 1000.
    s_bound = gamma_n * FLIPS_PER_RUN * INCREMENT + unit_roundoff * FLIPS_PER_RUN * INCREMENT
    return {
        "event_count": model.getNumEvents(),
        "tie_pair": list(tie_names),
        "initial_Q": parameters["Q"].getValue(),
        "initial_R": parameters["R"].getValue(),
        "source_variables": sorted(parameters),
        "block_size": BLOCK_SIZE,
        "blocks_per_run": BLOCKS_PER_RUN,
        "flips_per_run": FLIPS_PER_RUN,
        "seeds": list(SEEDS),
        "alpha_familywise": ALPHA_FAMILYWISE,
        "hypotheses": FAMILY_SIZE,
        "per_test_alpha": PER_TEST_ALPHA,
        "s_roundoff_bound": float(s_bound),
        "source_path": str(path.resolve()),
    }


def source_calculateerror(histogram: list[int], source_path: str | Path = SOURCE_RELATIVE_PATH) -> float:
    """Evaluate the official SBML `calculateerror` MathML without `eval`."""
    if len(histogram) != BLOCK_SIZE + 1:
        raise ValueError("calculateerror requires all 17 source histogram bins")
    document = libsbml.readSBMLFromFile(str(source_path))
    calculation = document.getModel().getFunctionDefinition("calculateerror")
    function_math = calculation.getMath()
    formula = libsbml.formulaToL3String(function_math.getChild(function_math.getNumChildren() - 1))
    values = {f"x{i}": float(histogram[i]) for i in range(BLOCK_SIZE + 1)}
    tree = ast.parse(formula.replace("^", "**"), mode="eval").body

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = evaluate(node.operand)
            return operand if isinstance(node.op, ast.UAdd) else -operand
        if isinstance(node, ast.BinOp):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                return left**right
        raise SourceContractError("calculateerror contains unsupported MathML")

    return evaluate(tree)


def validate_settings(settings_path: str | Path = SETTINGS_RELATIVE_PATH) -> dict[str, Any]:
    """Verify the official case's predeclared duration and output budget."""
    path = Path(settings_path)
    content = path.read_text(encoding="utf-8")
    if hashlib.sha256(content.encode("utf-8")).hexdigest() != SETTINGS_SHA256:
        raise SourceContractError("settings do not match the pinned official semantic/00966 case")
    values = {}
    for line in content.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    _require(values.get("start") == "0", "official start time differs from zero")
    _require(values.get("duration") == "1000", "official duration differs from 1000")
    _require(values.get("steps") == "1000", "official output steps differ from 1000")
    _require(values.get("variables") == "S, error", "official output variables changed")
    return {"settings_path": str(path.resolve()), "sha256": SETTINGS_SHA256,
            "start": 0, "duration": 1000, "steps": 1000, "variables": ["S", "error"]}


def _series(result: dict[str, Any], key: str) -> np.ndarray:
    value = result.get(key)
    if value is None:
        raise ValueError(f"missing output series {key}")
    data = np.asarray(value, dtype=float).reshape(-1)
    if not len(data) or not np.all(np.isfinite(data)):
        raise ValueError(f"output series {key} is empty or nonfinite")
    return data


def exact_binomial_pvalue(observed: int, trials: int, probability: float = 0.5) -> float:
    """Two-sided exact binomial p-value (no normal approximation)."""
    return float(binomtest(observed, trials, probability, alternative="two-sided").pvalue)


def check_trajectory(result: dict[str, Any], seed: int) -> dict[str, Any]:
    """Check invariants and the predeclared per-seed tie-order statistics."""
    failures: list[str] = []
    tested: list[dict[str, Any]] = []
    times = _series(result, "time")
    s_values = _series(result, "S")
    q_values = _series(result, "Q")
    r_values = _series(result, "R")
    if not (len(times) == len(s_values) == len(q_values) == len(r_values)):
        raise ValueError("time/S/Q/R output lengths differ")
    if len(times) != 1001 or abs(times[0]) > 1e-12 or abs(times[-1] - 1000) > 1e-9:
        failures.append("full_horizon_and_1001_samples")
    if np.any(np.diff(times) <= 0):
        failures.append("strictly_increasing_time")
    if len(times) == 1001 and not np.allclose(times, np.arange(1001), rtol=0, atol=1e-12):
        failures.append("unit_spaced_sample_schedule")

    contract = validate_source()
    roundoff_bound = contract["s_roundoff_bound"]
    if np.any(np.abs(s_values - q_values - r_values) > roundoff_bound):
        failures.append("S_equals_Q_plus_R")
    if len(times) == len(s_values) and np.any(np.abs(s_values - times) > roundoff_bound):
        failures.append("periodic_clock_sum_invariant")
    lattice_tolerance = roundoff_bound / INCREMENT
    if np.any(np.abs(q_values / INCREMENT - np.rint(q_values / INCREMENT)) > lattice_tolerance):
        failures.append("Q_increment_lattice_samples")
    if np.any(np.abs(r_values / INCREMENT - np.rint(r_values / INCREMENT)) > lattice_tolerance):
        failures.append("R_increment_lattice_samples")
    if abs(s_values[-1] - 1000.0) > roundoff_bound:
        failures.append("100000_tick_sum_invariant")

    q_tick_value = q_values[-1] / INCREMENT
    q_ticks = int(round(q_tick_value))
    if abs(q_tick_value - q_ticks) > roundoff_bound / INCREMENT:
        failures.append("Q_increment_lattice")
    q_p = exact_binomial_pvalue(q_ticks, FLIPS_PER_RUN)
    tested.append({"name": "Q_total", "observed": q_ticks, "trials": FLIPS_PER_RUN, "p_value": q_p})

    histogram: list[int] = []
    for count in range(BLOCK_SIZE + 1):
        values = _series(result, f"chi{count}")
        observed_value = values[-1]
        observed = int(round(observed_value))
        if abs(observed_value - observed) > 1e-9 or observed < 0:
            failures.append(f"chi{count}_integer_counter")
        histogram.append(observed)
        probability = math.comb(BLOCK_SIZE, count) / (2**BLOCK_SIZE)
        p_value = exact_binomial_pvalue(observed, BLOCKS_PER_RUN, probability)
        tested.append({
            "name": f"chi{count}", "observed": observed, "trials": BLOCKS_PER_RUN,
            "probability": probability, "p_value": p_value,
        })
    if sum(histogram) != BLOCKS_PER_RUN:
        failures.append("histogram_accounts_for_all_blocks")
    if any(item["p_value"] < PER_TEST_ALPHA for item in tested):
        failures.append("familywise_binomial")

    return {
        "seed": seed,
        "passed": not failures,
        "failures": sorted(set(failures)),
        "S_roundoff_bound": roundoff_bound,
        "Q_ticks": q_ticks,
        "Q_plus_R": float(q_values[-1] + r_values[-1]),
        "histogram": histogram,
        "tests": tested,
        "familywise_alpha": ALPHA_FAMILYWISE,
        "family_size": FAMILY_SIZE,
        "per_test_alpha": PER_TEST_ALPHA,
        "limits": (
            "The binomial checks qualify randomized equal-priority tie resolution "
            "for the checked seeds and horizon; they do not establish pathwise parity "
            "or prescribe random tie resolution as an SBML requirement."
        ),
    }
