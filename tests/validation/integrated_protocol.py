"""Generated public-API protocol checks for isolated BNG3 model instances."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import re
from pathlib import Path

# These names are the required output contract. Keep every generated case
# accountable for every check, including when a prerequisite is unavailable.
expected_check_names = (
    "modern-run-equivalence",
    "invalid-option-rejection",
    "independent-ssa-state",
    "exception-recovery",
)

_ISSUES = {
    "modern-run-equivalence": [138, 139, 140, 171, 172],
    "invalid-option-rejection": [139, 140, 171, 172],
    "independent-ssa-state": [141, 143],
    "exception-recovery": [138, 141, 143],
}


def _row(case_id, name, status, detail, first_difference=None):
    return {
        "check": f"{case_id}:protocol:{name}",
        "status": status,
        "detail": str(detail),
        "first_difference": first_difference,
        "related_issues": list(_ISSUES[name]),
    }


def _result_difference(left, right, *, atol=1e-10, rtol=1e-9):
    """Return the first public result difference, including exact grid identity."""
    import numpy as np

    left_time = np.asarray(left.time, dtype=float)
    right_time = np.asarray(right.time, dtype=float)
    for label, values in (("left", left_time), ("right", right_time)):
        if values.ndim != 1 or values.size == 0:
            return {"field": label + ".time.shape", "shape": list(values.shape)}
        invalid = np.flatnonzero(~np.isfinite(values))
        if invalid.size:
            index = int(invalid[0])
            return {
                "field": label + ".time.finite",
                "row": index,
                "value": float(values[index]),
            }
    if left_time.shape != right_time.shape:
        return {
            "field": "time.shape",
            "left": list(left_time.shape),
            "right": list(right_time.shape),
        }
    if not np.array_equal(left_time, right_time):
        index = int(np.flatnonzero(left_time != right_time)[0])
        return {
            "field": "time",
            "row": index,
            "left": float(left_time[index]),
            "right": float(right_time[index]),
        }

    left_names, right_names = set(left.observables), set(right.observables)
    if not left_names or not right_names:
        return {
            "field": "observables.empty",
            "left": sorted(left_names),
            "right": sorted(right_names),
        }
    if left_names != right_names:
        return {
            "field": "observable_names",
            "left": sorted(left_names),
            "right": sorted(right_names),
        }
    for name in sorted(left_names):
        a = np.asarray(left.observables[name], dtype=float)
        b = np.asarray(right.observables[name], dtype=float)
        for label, values in (("left", a), ("right", b)):
            if values.ndim != 1 or values.size == 0:
                return {
                    "field": label + "." + name + ".shape",
                    "shape": list(values.shape),
                }
            expected_shape = left_time.shape if label == "left" else right_time.shape
            if values.shape != expected_shape:
                return {
                    "field": label + "." + name + ".time_shape",
                    "time_shape": list(expected_shape),
                    "value_shape": list(values.shape),
                }
            invalid = np.flatnonzero(~np.isfinite(values))
            if invalid.size:
                index = int(invalid[0])
                return {
                    "field": label + "." + name + ".finite",
                    "row": index,
                    "time": float(left_time[index]) if index < left_time.size else None,
                    "value": float(values[index]),
                }
        if a.shape != b.shape:
            return {
                "field": name + ".shape",
                "left": list(a.shape),
                "right": list(b.shape),
            }
        unequal = ~np.isclose(a, b, atol=atol, rtol=rtol, equal_nan=False)
        if unequal.any():
            index = int(np.flatnonzero(unequal)[0])
            return {
                "field": name,
                "row": index,
                "time": float(left_time[index]),
                "left": float(a[index]),
                "right": float(b[index]),
            }
    return None


def _requested_grid_difference(result, requested):
    """Require a public result to preserve the requested grid exactly."""
    import numpy as np

    actual = np.asarray(result.time, dtype=float)
    expected = np.asarray(requested, dtype=float)
    if actual.ndim != 1 or actual.size == 0:
        return {"field": "time.shape", "actual": list(actual.shape)}
    if not np.isfinite(actual).all():
        index = int(np.flatnonzero(~np.isfinite(actual))[0])
        return {"field": "time.finite", "row": index, "actual": float(actual[index])}
    if actual.shape != expected.shape:
        return {
            "field": "requested_time_grid.shape",
            "expected": list(expected.shape),
            "actual": list(actual.shape),
        }
    if not np.array_equal(actual, expected):
        index = int(np.flatnonzero(actual != expected)[0])
        return {
            "field": "requested_time_grid",
            "row": index,
            "expected": float(expected[index]),
            "actual": float(actual[index]),
        }
    return None


def _copy_result(result):
    import numpy as np

    return (
        np.asarray(result.time).copy(),
        {
            name: np.asarray(values).copy()
            for name, values in result.observables.items()
        },
        np.asarray(result.concentrations).copy(),
    )


def _snapshot_difference(before, after, label):
    import numpy as np

    before_time, before_observables, before_concentrations = before
    after_time, after_observables, after_concentrations = after
    if not np.array_equal(before_time, after_time):
        return {"field": label + ".time"}
    if before_observables.keys() != after_observables.keys():
        return {"field": label + ".observable_names"}
    for name in before_observables:
        if not np.array_equal(before_observables[name], after_observables[name]):
            return {"field": label + "." + name}
    if not np.array_equal(before_concentrations, after_concentrations):
        return {"field": label + ".concentrations"}
    return None


def _rate_parameter(model):
    names = {parameter.name for parameter in model.parameters}
    for rule in model.reaction_rules:
        for rate in rule.rates:
            for identifier in re.findall(r"\b[A-Za-z_]\w*\b", str(rate)):
                if identifier in names:
                    return identifier
    return None


def run(source: Path, case_id: str, directory: Path) -> list[dict]:
    """Run public protocol checks against a translated, action-free BNGL file."""
    source = Path(source).resolve()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)

    try:
        import bionetgen
    except Exception as exc:
        return [
            _row(
                case_id,
                name,
                "NOT_TESTED",
                f"could not import installed bionetgen: {exc}",
            )
            for name in expected_check_names
        ]

    rows = []

    # Compare both public modern dispatch paths on a genuinely nonuniform
    # absolute grid. The model method result is the API relation under test.
    try:
        times = [0.25, 0.6, 1.7, 3.0]
        options = dict(
            method="ode", t_start=0.25, t_end=3.0, n_steps=0, sample_times=times
        )
        public = bionetgen.run(source, **options)
        model_result = bionetgen.load(source).simulate(**options)
        difference = _requested_grid_difference(public, times)
        if difference is None:
            difference = _requested_grid_difference(model_result, times)
        if difference is None:
            difference = _result_difference(public, model_result)
        rows.append(
            _row(
                case_id,
                "modern-run-equivalence",
                "FAIL" if difference else "PASS",
                "public run and model.simulate compared on exact absolute sample grid",
                difference,
            )
        )
    except Exception as exc:
        rows.append(
            _row(
                case_id,
                "modern-run-equivalence",
                "FAIL",
                f"public simulation comparison raised {type(exc).__name__}: {exc}",
            )
        )

    # Invalid method/option combinations must fail before creating output. A
    # valid public run in the same installed worker proves the engine is usable.
    try:
        before = {path.name for path in directory.iterdir()}
        try:
            bionetgen.run(source, method="ssa", t_end=1.0, n_steps=2, sparse=True)
        except ValueError as exc:
            if "only for method='ode'" not in str(exc):
                raise AssertionError(f"unexpected rejection reason: {exc}") from exc
        else:
            raise AssertionError("SSA with ODE-only sparse option was accepted")
        after = {path.name for path in directory.iterdir()}
        if after != before:
            raise AssertionError(
                f"rejected call created output entries: {sorted(after - before)}"
            )
        control = bionetgen.run(source, method="ode", t_end=1.0, n_steps=2)
        if len(control.time) != 3:
            raise AssertionError(
                "valid positive-control simulation returned an unexpected grid"
            )
        rows.append(
            _row(
                case_id,
                "invalid-option-rejection",
                "PASS",
                "ODE-only option rejected for SSA without output; valid ODE control ran",
            )
        )
    except Exception as exc:
        rows.append(
            _row(
                case_id,
                "invalid-option-rejection",
                "FAIL",
                f"protocol check raised {type(exc).__name__}: {exc}",
            )
        )

    # Isolate two SSA models with distinct rates and seeds. Replay one seed
    # after mutating its sibling, and verify the original model and saved arrays
    # retain their pre-mutation values.
    try:
        baseline = bionetgen.load(source)
        rate_name = _rate_parameter(baseline)
        if rate_name is None:
            rows.append(
                _row(
                    case_id,
                    "independent-ssa-state",
                    "NOT_TESTED",
                    "no parameter referenced by a reaction rate was available",
                )
            )
        else:
            baseline_rate = float(baseline.get_parameter(rate_name).value)
            if not (baseline_rate > 0.0):
                rows.append(
                    _row(
                        case_id,
                        "independent-ssa-state",
                        "NOT_TESTED",
                        f"rate parameter {rate_name!r} is not positive",
                    )
                )
            else:
                left, right = bionetgen.load(source), bionetgen.load(source)
                left.set_parameter(rate_name, baseline_rate * 0.73)
                right.set_parameter(rate_name, baseline_rate * 1.31)
                options = dict(method="ssa", t_end=2.0, n_steps=20)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    left_result, right_result = list(
                        pool.map(
                            lambda pair: pair[0].simulate(seed=pair[1], **options),
                            [(left, 1729), (right, 8123)],
                        )
                    )
                left_saved, right_saved = _copy_result(left_result), _copy_result(
                    right_result
                )
                fresh_left, fresh_right = bionetgen.load(source), bionetgen.load(source)
                fresh_left.set_parameter(rate_name, baseline_rate * 0.73)
                fresh_right.set_parameter(rate_name, baseline_rate * 1.31)
                left_reference = fresh_left.simulate(seed=1729, **options)
                right_reference = fresh_right.simulate(seed=8123, **options)
                right.set_parameter(rate_name, baseline_rate * 1.77)
                left_replay = left.simulate(seed=1729, **options)
                difference = _snapshot_difference(
                    left_saved, _copy_result(left_result), "left_saved"
                )
                if difference is None:
                    difference = _snapshot_difference(
                        right_saved, _copy_result(right_result), "right_saved"
                    )
                if difference is None:
                    difference = _result_difference(
                        left_result, left_reference, atol=0.0, rtol=0.0
                    )
                if difference is None:
                    difference = _result_difference(
                        right_result, right_reference, atol=0.0, rtol=0.0
                    )
                if difference is None:
                    difference = _result_difference(
                        left_result, left_replay, atol=0.0, rtol=0.0
                    )
                if (
                    difference is None
                    and float(baseline.get_parameter(rate_name).value) != baseline_rate
                ):
                    difference = {
                        "field": "baseline_rate",
                        "expected": baseline_rate,
                        "observed": float(baseline.get_parameter(rate_name).value),
                    }
                rows.append(
                    _row(
                        case_id,
                        "independent-ssa-state",
                        "FAIL" if difference else "PASS",
                        "independent seeded models replayed after sibling rate mutation; source model and saved results checked",
                        difference,
                    )
                )
    except Exception as exc:
        rows.append(
            _row(
                case_id,
                "independent-ssa-state",
                "FAIL",
                f"independence check raised {type(exc).__name__}: {exc}",
            )
        )

    # Exercise an evaluation-time failure, then compare the recovered instance
    # against a fresh model on the same valid protocol.
    try:
        recovered = bionetgen.load(source)
        options = dict(method="ode", t_end=1.0, n_steps=2)
        try:
            recovered.simulate(
                stop_if="__integrated_protocol_missing_name__ > 0", **options
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError(
                "invalid stop_if expression did not raise RuntimeError"
            )
        actual = recovered.simulate(**options)
        expected = bionetgen.load(source).simulate(**options)
        difference = _result_difference(actual, expected)
        rows.append(
            _row(
                case_id,
                "exception-recovery",
                "FAIL" if difference else "PASS",
                "valid simulation after evaluation exception matched a fresh model",
                difference,
            )
        )
    except Exception as exc:
        rows.append(
            _row(
                case_id,
                "exception-recovery",
                "FAIL",
                f"recovery check raised {type(exc).__name__}: {exc}",
            )
        )

    return rows
