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
    "parameter-source-controls",
    "lifecycle-construction-isolation",
    "lifecycle-mutation-baseline",
    "lifecycle-public-routes",
    "lifecycle-topology-unavailable",
    "lifecycle-repeated-instantiation",
    "lifecycle-concurrent-instantiation",
    "lifecycle-independent-rng",
    "lifecycle-independent-caches",
    "lifecycle-independent-solver-state",
    "lifecycle-exception-cleanup",
    "lifecycle-parameter-only-reuse",
    "lifecycle-topology-invalidation",
    "lifecycle-compartment-invalidation",
)

# Lifecycle work is deliberately bounded to a stable four-case slice. The
# construction check creates two concurrent models and runs each at most three
# times; mutation and route budgets are declared separately below.
lifecycle_budget = {
    "max_cases": 4,
    "construction_runs_per_model": 3,
    "concurrent_models_per_case": 2,
    "mutation_parameters": ("V", "N", "k"),
    "mutation_methods": ("ode", "ssa"),
    "public_routes_per_case": 2,
    "topology_probes": (
        "add_compartment",
        "add_molecule_type",
        "add_seed_species",
        "remove_seed_species",
        "move_species_to_compartment",
    ),
    # Compile-once / instantiate-many budgets. Every instance-level check
    # compares against a fresh compilation or a closed-form law, never against
    # the instance under test.
    "repeated_runs_per_model": 3,
    "concurrent_instances_per_case": 4,
    "concurrent_seeds": (1729, 8123),
    "rng_sample_steps": 100,
    "solver_state_runs_per_model": 4,
    "exception_recovery_iterations": 3,
    "parameter_only_overrides": ("k",),
    "volume_override_factor": 3.0,
}

_ISSUES = {
    "modern-run-equivalence": [138, 139, 140, 171, 172],
    "invalid-option-rejection": [139, 140, 171, 172],
    "independent-ssa-state": [141, 143],
    "exception-recovery": [138, 141, 143],
    "parameter-source-controls": [141, 143],
    "lifecycle-construction-isolation": [141, 143],
    "lifecycle-mutation-baseline": [141, 143],
    "lifecycle-public-routes": [138, 139, 140],
    "lifecycle-topology-unavailable": [141, 143],
    "lifecycle-repeated-instantiation": [141, 143],
    "lifecycle-concurrent-instantiation": [141, 143],
    "lifecycle-independent-rng": [141, 143],
    "lifecycle-independent-caches": [141, 143],
    "lifecycle-independent-solver-state": [141, 143],
    "lifecycle-exception-cleanup": [141, 143],
    "lifecycle-parameter-only-reuse": [141, 143],
    "lifecycle-topology-invalidation": [141, 143],
    "lifecycle-compartment-invalidation": [141, 143],
}


def _row(case_id, name, status, detail, first_difference=None):
    return {
        "check": f"{case_id}:protocol:{name}",
        "status": status,
        "detail": str(detail),
        "first_difference": first_difference,
        "related_issues": list(_ISSUES[name]),
    }


def _topology_unavailable_row(case_id):
    return _row(
        case_id,
        "lifecycle-topology-unavailable",
        "UNSUPPORTED",
        "runtime topology mutation is unsupported by the public Model API: no in-place edits for compartments, molecule types, seed species, or species compartment assignment; absent methods: "
        + ", ".join(lifecycle_budget["topology_probes"]),
    )


def _lifecycle_case_ids():
    """Choose a stable four-case slice spanning dynamics and compartment size."""
    from .integrated_cases import generated_cases

    available = {case["id"] for case in generated_cases(full=True)}
    selected = (
        "v1-n20-r0-a0",
        "reversible-v3-n80-r0-a0",
        "dimerization-v1-n20-r0-a0",
        "dimerization-v3-n80-r0-a0",
    )
    if not set(selected).issubset(available):
        raise RuntimeError(
            "declared lifecycle case slice is absent from generated corpus"
        )
    return selected


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

    concentrations = getattr(result, "concentrations", None)
    return (
        np.asarray(result.time).copy(),
        {
            name: np.asarray(values).copy()
            for name, values in result.observables.items()
        },
        None if concentrations is None else np.asarray(concentrations).copy(),
    )


def _result_receipt(result, **context):
    time, observables, concentrations = _copy_result(result)
    return {
        **context,
        "time": time.astype(float).tolist(),
        "observables": {
            name: values.astype(float).tolist() for name, values in observables.items()
        },
        "concentrations": (
            None if concentrations is None else concentrations.astype(float).tolist()
        ),
    }


def _write_lifecycle_receipt(directory, check, runs):
    import json

    path = directory / "lifecycle-results.json"
    existing = json.loads(path.read_text()) if path.is_file() else {}
    existing[check] = runs
    path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")


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
    if before_concentrations is None or after_concentrations is None:
        if before_concentrations is not after_concentrations:
            return {"field": label + ".concentrations"}
    elif not np.array_equal(before_concentrations, after_concentrations):
        return {"field": label + ".concentrations"}
    return None


def _rate_parameter(model):
    """Find a rate dependency, including calls; never pick an unused declaration."""
    names = {parameter.name for parameter in model.parameters}
    functions = {function.name: function for function in model.functions}

    def search(expression, seen):
        for identifier in re.findall(r"\b[A-Za-z_]\w*\b", str(expression)):
            if identifier in seen:
                continue
            if identifier in names:
                return identifier
            if identifier in functions:
                function = functions[identifier]
                # Formal arguments shadow global names inside a function.
                found = search(function.expression, seen | {identifier, *function.args})
                if found is not None:
                    return found
        return None

    for rule in model.reaction_rules:
        for rate in rule.rates:
            found = search(rate, set())
            if found is not None:
                return found
    return None


def run(source: Path, case_id: str, directory: Path, *, case=None) -> list[dict]:
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
    control_source = None
    if case is not None:
        from .integrated_cases import reuse_bngl

        control_source = directory / "reuse-source-control.bngl"
        control_source.write_text(reuse_bngl(case))

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
        # Numeric folding may leave the translation without mutable rates.
        # Use a separately identified native source control in that case.
        ssa_source = source
        baseline = bionetgen.load(ssa_source)
        rate_name = _rate_parameter(baseline)
        if rate_name is None and control_source is not None:
            ssa_source = control_source
            baseline = bionetgen.load(ssa_source)
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
                left, right = bionetgen.load(ssa_source), bionetgen.load(ssa_source)
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
                left_saved, right_saved = (
                    _copy_result(left_result),
                    _copy_result(right_result),
                )
                fresh_left, fresh_right = (
                    bionetgen.load(ssa_source),
                    bionetgen.load(ssa_source),
                )
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
                        f"independent seeded models replayed after sibling rate mutation; source={ssa_source.name}; model and saved results checked",
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

    # Functional recovery is separate from native allocation cleanup. The late
    # conditional reaches CVODE's output loop; an unknown name alone fails
    # before solver allocation and cannot qualify that exception boundary.
    try:
        recovered = bionetgen.load(source)
        options = dict(method="ode", t_end=1.0, n_steps=2)
        baseline = recovered.simulate(**options)
        saved = _copy_result(baseline)
        network = recovered._network
        receipts = []
        difference = None
        for phase, condition in (
            ("before-allocation", "__integrated_protocol_missing_name__ > 0"),
            (
                "after-allocation",
                "if(time > 0, __integrated_protocol_missing_name__, 0)",
            ),
        ):
            try:
                recovered.simulate(stop_if=condition, **options)
            except RuntimeError as exc:
                if "__integrated_protocol_missing_name__" not in str(exc):
                    raise
            else:
                raise AssertionError("invalid stop_if did not raise RuntimeError")
            if recovered._network is not network:
                raise AssertionError("exception discarded the generated network")
            actual = recovered.simulate(**options)
            expected = bionetgen.load(source).simulate(**options)
            difference = _result_difference(actual, expected)
            if difference is None:
                difference = _snapshot_difference(
                    saved, _copy_result(baseline), "saved"
                )
            receipts.append(
                _result_receipt(
                    actual,
                    phase=phase,
                    generated_network_retained=True,
                    native_resource_cleanup="NOT_TESTED; requires leak sanitizer",
                )
            )
            if difference:
                break
        _write_lifecycle_receipt(directory, "exception-recovery", receipts)
        rows.append(
            _row(
                case_id,
                "exception-recovery",
                "FAIL" if difference else "PASS",
                "functional recovery before/after solver allocation matched fresh model; "
                "network and saved outputs retained; native resource cleanup not qualified",
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

    if case is None or case.get("id") not in _lifecycle_case_ids():
        detail = (
            "generated case is outside the declared four-case lifecycle slice"
            if case is not None
            else "generated source case was not supplied"
        )
        for name in _LIFECYCLE_CHECK_NAMES:
            rows.append(_row(case_id, name, "NOT_TESTED", detail))
    else:
        for name, detail, check in _LIFECYCLE_CHECKS:
            try:
                difference = check(bionetgen, case, directory)
                rows.append(
                    _row(
                        case_id,
                        name,
                        "FAIL" if difference else "PASS",
                        detail,
                        difference,
                    )
                )
            except Exception as exc:
                rows.append(
                    _row(
                        case_id,
                        name,
                        "FAIL",
                        f"protocol raised {type(exc).__name__}: {exc}",
                    )
                )

    try:
        import bionetgen

        topology_model = bionetgen.load(source)
        probes = [
            name
            for name in lifecycle_budget["topology_probes"]
            if hasattr(topology_model, name)
        ]
        if probes:
            rows.append(
                _row(
                    case_id,
                    "lifecycle-topology-unavailable",
                    "FAIL",
                    "runtime topology API appeared without a declared semantic contract: "
                    + ", ".join(probes),
                )
            )
        else:
            rows.append(_topology_unavailable_row(case_id))
    except Exception as exc:
        rows.append(
            _row(
                case_id,
                "lifecycle-topology-unavailable",
                "FAIL",
                f"topology capability probe raised {type(exc).__name__}: {exc}",
            )
        )

    try:
        if case is None:
            rows.append(
                _row(
                    case_id,
                    "parameter-source-controls",
                    "NOT_TESTED",
                    "generated source case was not supplied",
                )
            )
        else:
            _reuse_source_controls(bionetgen, case, directory)
            rows.append(
                _row(
                    case_id,
                    "parameter-source-controls",
                    "PASS",
                    "native named-dependency controls; ODE/SSA overrides and resets matched source-edited fresh compilations",
                )
            )
    except Exception as exc:
        rows.append(_row(case_id, "parameter-source-controls", "FAIL", str(exc)))

    successful_lifecycle = {
        row["check"].rsplit(":", 1)[-1]
        for row in rows
        if row["status"] == "PASS"
        and row["check"].rsplit(":", 1)[-1].startswith("lifecycle-")
        and row["check"].rsplit(":", 1)[-1] != "lifecycle-topology-unavailable"
    }
    if successful_lifecycle:
        receipt_path = directory / "lifecycle-results.json"
        try:
            import json

            receipt = json.loads(receipt_path.read_text())
            if any(not receipt.get(name) for name in successful_lifecycle):
                raise ValueError("successful lifecycle check has no output receipt")
        except (OSError, ValueError, TypeError) as exc:
            for row in rows:
                name = row["check"].rsplit(":", 1)[-1]
                if name in successful_lifecycle:
                    row["status"] = "HARNESS_ERROR"
                    row["detail"] = f"lifecycle output receipt invalid: {exc}"

    return rows


def _reuse_source_controls(bionetgen, case, directory):
    import json
    from .integrated_cases import RATE, reuse_bngl

    source = directory / "reuse-source-control.bngl"
    source.write_text(reuse_bngl(case))
    scenarios = [("k", RATE * 1.5), ("N", case["initial"] * 2)]
    if case["family"] == "dimerization":
        scenarios.append(("V", case["volume"] * 2))
    observations = []
    for method in ("ode", "ssa"):
        options = dict(method=method, t_end=2, n_steps=10, seed=1729)
        if method == "ode":
            options.update(rtol=1e-10, atol=1e-12)
        for parameter, value in scenarios:
            model = bionetgen.load(source)
            baseline = model.simulate(**options)
            snapshot = _copy_result(baseline)
            old = float(model.get_parameter(parameter).value)
            model.set_parameter(parameter, value)
            actual = model.simulate(**options)
            changed_case = dict(case)
            if parameter == "N":
                changed_case["initial"] = value
            if parameter == "V":
                changed_case["volume"] = value
            reference = directory / f"reuse-reference-{parameter}.bngl"
            reference.write_text(
                reuse_bngl(changed_case, rate=value if parameter == "k" else RATE)
            )
            fresh = bionetgen.load(reference).simulate(**options)
            difference = _result_difference(actual, fresh)
            if difference is not None:
                raise AssertionError(f"{method} override {parameter}: {difference}")
            if method == "ode" and _result_difference(baseline, actual) is None:
                raise AssertionError(
                    f"ODE override {parameter} had no observable effect"
                )
            model.set_parameter(parameter, old)
            reset = model.simulate(**options)
            difference = _result_difference(reset, baseline) or _snapshot_difference(
                snapshot, _copy_result(baseline), "saved"
            )
            if difference is not None:
                raise AssertionError(f"{method} reset {parameter}: {difference}")
            observations.append(
                dict(method=method, parameter=parameter, value=value, status="PASS")
            )
    (directory / "reuse-controls.json").write_text(
        json.dumps(observations, indent=2) + "\n"
    )
    return observations


def _analytic_result_difference(result, case, *, atol=1e-8, rtol=1e-8):
    """Compare native control trajectories with the independent closed form."""
    from types import SimpleNamespace
    from .integrated_cases import RATE, REVERSE_RATE
    import numpy as np

    times = np.asarray(result.time, dtype=float)
    initial = float(case["initial"])
    volume = float(case["volume"])
    rate = float(case.get("_lifecycle_rate", RATE))
    if case["family"] == "decay":
        a = initial * np.exp(-rate * times)
        expected_observables = {"A": a, "B": initial - a}
    elif case["family"] == "reversible":
        a0 = 0.0 if case["reverse"] else initial
        equilibrium_a = initial * REVERSE_RATE / (rate + REVERSE_RATE)
        a = equilibrium_a + (a0 - equilibrium_a) * np.exp(
            -(rate + REVERSE_RATE) * times
        )
        expected_observables = {"A": a, "B": initial - a}
    elif case["family"] == "dimerization":
        a = initial / (1 + 2 * rate * initial * times / volume)
        expected_observables = {"A": a, "D": (initial - a) / 2}
    else:
        raise ValueError(f"unknown lifecycle family: {case['family']!r}")
    expected = SimpleNamespace(
        time=times,
        observables=expected_observables,
    )
    return _result_difference(result, expected, atol=atol, rtol=rtol)


def _lifecycle_construction_isolation(bionetgen, case, directory):
    """Interleave distinct model states and compare each with a fresh compile."""
    from .integrated_cases import RATE, reuse_bngl

    source = directory / "lifecycle-isolation.bngl"
    source.write_text(reuse_bngl(case))
    with ThreadPoolExecutor(
        max_workers=lifecycle_budget["concurrent_models_per_case"]
    ) as pool:
        left, right = list(pool.map(lambda _index: bionetgen.load(source), range(2)))
    left.set_parameter("k", RATE * 0.73)
    right.set_parameter("k", RATE * 1.31)
    left.set_parameter("N", case["initial"] + 3)
    right.set_parameter("N", case["initial"] + 11)
    options = dict(method="ssa", t_end=2.0, n_steps=10)
    settings = (
        (left, RATE * 0.73, case["initial"] + 3, 1729, "left"),
        (right, RATE * 1.31, case["initial"] + 11, 8123, "right"),
    )
    receipts = []
    networks = {}

    def replay(model, rate, initial, seed, model_name, suffix):
        actual = model.simulate(seed=seed, **options)
        previous = networks.setdefault(model_name, model._network)
        retained = previous is model._network and previous is not None
        expected_case = dict(case, initial=initial)
        reference = directory / f"lifecycle-isolation-{model_name}-{suffix}.bngl"
        reference.write_text(reuse_bngl(expected_case, rate=rate))
        expected = bionetgen.load(reference).simulate(seed=seed, **options)
        receipts.append(
            _result_receipt(
                actual,
                model=model_name,
                reference=reference.name,
                rate=rate,
                initial=initial,
                seed=seed,
                phase=suffix,
                generated_network_retained=retained,
                reuse_scope="generated-network identity only; compilation count unmeasured",
            )
        )
        if not retained:
            return {"field": "network_cache_rebuilt", "model": model_name}
        return _result_difference(actual, expected, atol=0.0, rtol=0.0)

    # Two independent native instances run concurrently, then are interleaved
    # twice more. This is the declared maximum of three runs per instance.
    with ThreadPoolExecutor(
        max_workers=lifecycle_budget["concurrent_models_per_case"]
    ) as pool:
        initial_differences = list(
            pool.map(lambda item: replay(*item, "parallel"), settings)
        )
    if initial_differences[0] or initial_differences[1]:
        _write_lifecycle_receipt(
            directory, "lifecycle-construction-isolation", receipts
        )
        return initial_differences[0] or initial_differences[1]
    if networks["left"] is networks["right"]:
        return {"field": "independent_models_share_network_cache"}
    for index in range(2):
        difference = replay(*settings[index], f"interleave-{index}")
        if difference:
            _write_lifecycle_receipt(
                directory, "lifecycle-construction-isolation", receipts
            )
            return difference
        difference = replay(*settings[1 - index], f"interleave-{1 - index}")
        if difference:
            _write_lifecycle_receipt(
                directory, "lifecycle-construction-isolation", receipts
            )
            return difference
    _write_lifecycle_receipt(directory, "lifecycle-construction-isolation", receipts)
    return None


def _lifecycle_mutation_baseline(bionetgen, case, directory):
    """Mutate volume, seed and rate, then restore and check analytic baseline."""
    from .integrated_cases import RATE, reuse_bngl

    source = directory / "lifecycle-mutations.bngl"
    source.write_text(reuse_bngl(case))
    parameters = (
        ("V", case["volume"] * 1.7),
        ("N", case["initial"] + 9),
        ("k", RATE * 1.4),
    )
    receipts = []
    for method in lifecycle_budget["mutation_methods"]:
        options = dict(method=method, t_start=0.0, t_end=2.0, n_steps=10, seed=1729)
        if method == "ode":
            options.update(rtol=1e-10, atol=1e-12)
        model = bionetgen.load(source)
        baseline = model.simulate(**options)
        receipts.append(
            _result_receipt(
                baseline, method=method, phase="baseline", seed=options["seed"]
            )
        )
        if method == "ode":
            difference = _analytic_result_difference(baseline, case)
            if difference:
                _write_lifecycle_receipt(
                    directory, "lifecycle-mutation-baseline", receipts
                )
                return difference
        for parameter, changed_value in parameters:
            old_value = float(model.get_parameter(parameter).value)
            previous_network = model._network
            model.set_parameter(parameter, changed_value)
            invalidated = model._network is None
            actual = model.simulate(**options)
            regenerated = model._network is not previous_network
            changed_case = dict(case)
            if parameter == "N":
                changed_case["initial"] = int(changed_value)
            if parameter == "V":
                changed_case["volume"] = changed_value
            if parameter == "k":
                changed_case["_lifecycle_rate"] = changed_value
            if method == "ode":
                difference = _analytic_result_difference(actual, changed_case)
                if difference:
                    receipts.append(
                        _result_receipt(
                            actual,
                            method=method,
                            phase="mutated",
                            parameter=parameter,
                            value=changed_value,
                        )
                    )
                    _write_lifecycle_receipt(
                        directory, "lifecycle-mutation-baseline", receipts
                    )
                    return {
                        "field": f"analytic_mutation.{parameter}.{difference['field']}"
                    }
            fresh_source = directory / f"lifecycle-fresh-{method}-{parameter}.bngl"
            fresh_source.write_text(
                reuse_bngl(
                    changed_case, rate=changed_value if parameter == "k" else RATE
                )
            )
            expected = bionetgen.load(fresh_source).simulate(**options)
            receipts.append(
                _result_receipt(
                    actual,
                    method=method,
                    phase="mutated",
                    parameter=parameter,
                    value=changed_value,
                    generated_network_invalidated=invalidated,
                    generated_network_regenerated=regenerated,
                    seed=options["seed"],
                )
            )
            difference = _result_difference(actual, expected, atol=0.0, rtol=0.0)
            if difference:
                _write_lifecycle_receipt(
                    directory, "lifecycle-mutation-baseline", receipts
                )
                return {"field": f"mutation.{parameter}.{difference['field']}"}
            model.set_parameter(parameter, old_value)
            restored = model.simulate(**options)
            receipts.append(
                _result_receipt(
                    restored,
                    method=method,
                    phase="restored",
                    parameter=parameter,
                    value=old_value,
                    seed=options["seed"],
                )
            )
            difference = _result_difference(restored, baseline, atol=0.0, rtol=0.0)
            if difference:
                _write_lifecycle_receipt(
                    directory, "lifecycle-mutation-baseline", receipts
                )
                return {"field": f"restore.{parameter}.{difference['field']}"}
    _write_lifecycle_receipt(directory, "lifecycle-mutation-baseline", receipts)
    return None


def _lifecycle_public_routes(bionetgen, case, directory):
    """Compare the public CLI run route and a CLI action route with the API."""
    import hashlib
    import importlib.metadata
    import shutil
    import subprocess
    from bionetgen.cli import main
    from .integrated_cases import reuse_bngl
    import numpy as np

    route_dir = directory / "lifecycle-public-routes"
    route_dir.mkdir(exist_ok=True)
    run_command = main.commands.get("run")
    execute_command = main.commands.get("execute")
    run_options = (
        {
            option
            for parameter in run_command.params
            for option in getattr(parameter, "opts", ())
        }
        if run_command is not None
        else set()
    )
    if (
        run_command is None
        or execute_command is None
        or not {"--method", "--t-end", "--n-steps", "--output"}.issubset(run_options)
    ):
        return {"field": "cli.public_commands", "commands": sorted(main.commands)}
    source = route_dir / "route.bngl"
    source.write_text(reuse_bngl(case))
    output = route_dir / "route.tsv"
    options = [
        "run",
        str(source),
        "--method",
        "ode",
        "--t-end",
        "2",
        "--n-steps",
        "10",
        "--output",
        str(output),
    ]
    executable = shutil.which("bionetgen")
    distribution = importlib.metadata.distribution("bionetgen")
    owned = {
        Path(distribution.locate_file(file)).resolve()
        for file in distribution.files or ()
    }
    if executable is None or Path(executable).resolve() not in owned:
        return {"field": "cli.installed_identity", "executable": executable}
    identity = dict(
        executable=executable,
        sha256=hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
        package_file=bionetgen.__file__,
        entry_point="bionetgen.cli:main",
    )
    (route_dir / "cli-identity.json").write_text(
        __import__("json").dumps(identity, indent=2) + "\n"
    )
    cli = subprocess.run(
        [executable, *options],
        cwd=route_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    (route_dir / "cli-run.log").write_text(cli.stdout + cli.stderr)
    if cli.returncode != 0 or not output.is_file():
        return {
            "field": "cli.run",
            "exit_code": cli.returncode,
            "output": (cli.stdout + cli.stderr)[-500:],
        }
    table = np.loadtxt(output)
    api = bionetgen.run(source, method="ode", t_end=2.0, n_steps=10)
    if table.shape[0] != api.time.size or not np.array_equal(table[:, 0], api.time):
        return {"field": "cli.run.time_grid"}
    if table.shape[1] != len(api.observables) + 1:
        return {"field": "cli.run.columns"}
    if not np.allclose(
        table[:, 1:],
        np.column_stack(list(api.observables.values())),
        atol=1e-10,
        rtol=1e-9,
    ):
        return {"field": "cli.run.values"}

    action_source = route_dir / "route-actions.bngl"
    action_source.write_text(
        reuse_bngl(case)
        + "\ngenerate_network({overwrite=>1})\nwriteNetwork({overwrite=>1})\n"
        'simulate({method=>"ode",t_end=>2,n_steps=>10,rtol=>1e-10,atol=>1e-12})\n'
    )
    action = subprocess.run(
        [executable, "execute", str(action_source)],
        cwd=route_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    (route_dir / "cli-action.log").write_text(action.stdout + action.stderr)
    if action.returncode != 0:
        return {
            "field": "cli.execute",
            "exit_code": action.returncode,
            "output": (action.stdout + action.stderr)[-500:],
        }
    if not action_source.with_suffix(".net").is_file():
        return {
            "field": "cli.execute.writeNetwork",
            "path": str(action_source.with_suffix(".net")),
        }
    from types import SimpleNamespace
    from .contracts import _trajectory

    data, columns = _trajectory(action_source.with_suffix(".gdat"))
    action_result = SimpleNamespace(
        time=data[:, 0],
        observables={
            name: data[:, index] for index, name in enumerate(columns) if index
        },
    )
    difference = _analytic_result_difference(action_result, case)
    if difference:
        return dict(difference, route="cli.execute.simulate")
    _write_lifecycle_receipt(
        directory,
        "lifecycle-public-routes",
        [
            _result_receipt(api, route="python-api.run", source=source.name),
            _result_receipt(
                action_result, route="cli.execute.simulate", source=action_source.name
            ),
            {
                "route": "cli.run",
                "output": output.name,
                "time": table[:, 0].astype(float).tolist(),
                "values": table[:, 1:].astype(float).tolist(),
            },
            {
                "route": "cli.execute/writeNetwork",
                "source": action_source.name,
                "artifact": action_source.with_suffix(".net").name,
                "artifact_bytes": action_source.with_suffix(".net").stat().st_size,
            },
        ],
    )
    return None


def _lifecycle_control_source(case, directory, name):
    """Write the native lifecycle control for a case and return its path."""
    from .integrated_cases import reuse_bngl

    path = directory / name
    path.write_text(reuse_bngl(case))
    return path


def _lifecycle_deterministic_options():
    return dict(method="ode", t_end=2.0, n_steps=10, rtol=1e-10, atol=1e-12)


def _compiled_topology(cpp, model):
    """Return the compiled structure a parameter-only override must preserve."""
    snapshot = cpp._compiled_snapshot(model._model)
    return {
        key: snapshot.get(key)
        for key in (
            "molecule_types",
            "rules",
            "seeds",
            "observables",
            "functions",
            "compartments",
        )
    }


def _topology_result_difference(result, case, *, rate=None, atol=1e-8, rtol=1e-8):
    """Compare the merged-topology trajectory with the closed-form chain law."""
    from types import SimpleNamespace

    from .integrated_cases import RATE

    import numpy as np

    rate = RATE if rate is None else rate
    times = np.asarray(result.time, dtype=float)
    initial = float(case["initial"])
    converted = initial * np.exp(-rate * times)
    expected = SimpleNamespace(
        time=times,
        observables={
            "A": converted,
            "B": initial - converted,
            "D": np.full(times.shape, float(max(1, int(initial) // 4))),
        },
    )
    return _result_difference(result, expected, atol=atol, rtol=rtol)


def _lifecycle_repeated_instantiation(bionetgen, case, directory):
    """Repeated instantiation over one compiled model keeps independent results."""
    source = _lifecycle_control_source(case, directory, "lifecycle-repeated.bngl")
    deterministic = _lifecycle_deterministic_options()
    stochastic = dict(method="ssa", t_end=2.0, n_steps=10, seed=1729)
    model = bionetgen.load(str(source))
    expected_ode = bionetgen.load(str(source)).simulate(**deterministic)
    expected_ssa = bionetgen.load(str(source)).simulate(**stochastic)
    receipts = []
    for index in range(lifecycle_budget["repeated_runs_per_model"]):
        actual = model.simulate(**deterministic)
        sampled = model.simulate(**stochastic)
        receipts.append(
            _result_receipt(actual, instance="reused", run=index, source=source.name)
        )
        receipts.append(
            _result_receipt(sampled, instance="reused", run=index, source=source.name)
        )
        difference = _result_difference(actual, expected_ode)
        if difference is None:
            difference = _result_difference(sampled, expected_ssa, atol=0.0, rtol=0.0)
        if difference is not None:
            _write_lifecycle_receipt(
                directory, "lifecycle-repeated-instantiation", receipts
            )
            return {"field": f"repeat[{index}].{difference['field']}"}
    _write_lifecycle_receipt(directory, "lifecycle-repeated-instantiation", receipts)
    return None


def _lifecycle_concurrent_instantiation(bionetgen, case, directory):
    """Concurrent instantiation keeps RNG streams, caches and solver apart."""
    source = _lifecycle_control_source(case, directory, "lifecycle-concurrent.bngl")
    seeds = lifecycle_budget["concurrent_seeds"]
    count = lifecycle_budget["concurrent_instances_per_case"]
    assignment = tuple(seeds[index % len(seeds)] for index in range(count))
    options = dict(
        method="ssa", t_end=2.0, n_steps=lifecycle_budget["rng_sample_steps"]
    )
    with ThreadPoolExecutor(max_workers=count) as pool:
        models = list(
            pool.map(lambda _index: bionetgen.load(str(source)), range(count))
        )
    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(
            pool.map(
                lambda item: item[0].simulate(seed=item[1], **options),
                list(zip(models, assignment)),
            )
        )
    receipts = []
    for index, (model, result, seed) in enumerate(zip(models, results, assignment)):
        expected = bionetgen.load(str(source)).simulate(seed=seed, **options)
        difference = _result_difference(result, expected, atol=0.0, rtol=0.0)
        if difference is not None:
            _write_lifecycle_receipt(
                directory, "lifecycle-concurrent-instantiation", receipts
            )
            return {"field": f"instance[{index}].{difference['field']}"}
        receipts.append(_result_receipt(result, instance=index, seed=seed))
    networks = [model._network for model in models]
    if len({id(network) for network in networks}) != count:
        _write_lifecycle_receipt(
            directory, "lifecycle-concurrent-instantiation", receipts
        )
        return {"field": "concurrent.network_cache_shared"}
    by_seed = {}
    for index, seed in enumerate(assignment):
        by_seed.setdefault(seed, []).append(results[index])
    for seed, group in sorted(by_seed.items()):
        for other in group[1:]:
            difference = _result_difference(group[0], other, atol=0.0, rtol=0.0)
            if difference is not None:
                _write_lifecycle_receipt(
                    directory, "lifecycle-concurrent-instantiation", receipts
                )
                return {"field": "concurrent.same_seed_diverged", "seed": seed}
    distinct = sorted(by_seed)
    if len(distinct) > 1:
        difference = _result_difference(
            by_seed[distinct[0]][0], by_seed[distinct[1]][0], atol=0.0, rtol=0.0
        )
        if difference is None:
            _write_lifecycle_receipt(
                directory, "lifecycle-concurrent-instantiation", receipts
            )
            return {"field": "concurrent.seed_not_honored", "seeds": distinct}
    _write_lifecycle_receipt(directory, "lifecycle-concurrent-instantiation", receipts)
    return None


def _lifecycle_independent_rng(bionetgen, case, directory):
    """Each trajectory owns an independent RNG stream."""
    source = _lifecycle_control_source(case, directory, "lifecycle-rng.bngl")
    options = dict(
        method="ssa", t_end=2.0, n_steps=lifecycle_budget["rng_sample_steps"]
    )
    first_seed, second_seed = lifecycle_budget["concurrent_seeds"]
    model = bionetgen.load(str(source))
    first = model.simulate(seed=first_seed, **options)
    other = model.simulate(seed=second_seed, **options)
    repeated = model.simulate(seed=first_seed, **options)
    receipts = [
        _result_receipt(first, phase="first", seed=first_seed),
        _result_receipt(other, phase="other-seed", seed=second_seed),
        _result_receipt(repeated, phase="repeated", seed=first_seed),
    ]
    difference = _result_difference(repeated, first, atol=0.0, rtol=0.0)
    if difference is not None:
        _write_lifecycle_receipt(directory, "lifecycle-independent-rng", receipts)
        return {"field": f"rng.replay.{difference['field']}"}
    difference = _result_difference(other, first, atol=0.0, rtol=0.0)
    if difference is None:
        _write_lifecycle_receipt(directory, "lifecycle-independent-rng", receipts)
        return {"field": "rng.seed_not_honored"}
    twin = bionetgen.load(str(source)).simulate(seed=first_seed, **options)
    difference = _result_difference(twin, first, atol=0.0, rtol=0.0)
    if difference is not None:
        _write_lifecycle_receipt(directory, "lifecycle-independent-rng", receipts)
        return {"field": f"rng.twin.{difference['field']}"}
    _write_lifecycle_receipt(directory, "lifecycle-independent-rng", receipts)
    return None


def _lifecycle_independent_caches(bionetgen, case, directory):
    """Each instance owns its mutable caches."""
    from .integrated_cases import RATE, reuse_bngl

    source = _lifecycle_control_source(case, directory, "lifecycle-caches.bngl")
    options = _lifecycle_deterministic_options()
    left = bionetgen.load(str(source))
    right = bionetgen.load(str(source))
    left_network = left.generate_network()
    right_network = right.generate_network()
    receipts = []
    if left_network is right_network:
        return {"field": "caches.network_shared"}
    changed = RATE * 0.73
    left.set_parameter("k", changed)
    if left._network is not None:
        _write_lifecycle_receipt(directory, "lifecycle-independent-caches", receipts)
        return {"field": "caches.mutation_kept_stale_network"}
    if right._network is not right_network:
        _write_lifecycle_receipt(directory, "lifecycle-independent-caches", receipts)
        return {"field": "caches.sibling_cache_invalidated"}
    if float(right.get_parameter("k").value) != RATE:
        _write_lifecycle_receipt(directory, "lifecycle-independent-caches", receipts)
        return {
            "field": "caches.parameter_leaked_to_sibling",
            "observed": float(right.get_parameter("k").value),
        }
    left_reference = directory / "lifecycle-caches-left.bngl"
    left_reference.write_text(reuse_bngl(case, rate=changed))
    left_result = left.simulate(**options)
    right_result = right.simulate(**options)
    receipts.append(_result_receipt(left_result, instance="left"))
    receipts.append(_result_receipt(right_result, instance="right"))
    difference = _result_difference(
        left_result, bionetgen.load(str(left_reference)).simulate(**options)
    )
    if difference is None:
        difference = _result_difference(
            right_result, bionetgen.load(str(source)).simulate(**options)
        )
    if difference is not None:
        _write_lifecycle_receipt(directory, "lifecycle-independent-caches", receipts)
        return {"field": f"caches.{difference['field']}"}
    if left._network is left_network or left._network is right_network:
        _write_lifecycle_receipt(directory, "lifecycle-independent-caches", receipts)
        return {"field": "caches.rebuilt_network_shared"}
    _write_lifecycle_receipt(directory, "lifecycle-independent-caches", receipts)
    return None


def _lifecycle_independent_solver_state(bionetgen, case, directory):
    """Each trajectory owns its solver state."""
    source = _lifecycle_control_source(case, directory, "lifecycle-solver-state.bngl")
    options = _lifecycle_deterministic_options()
    model = bionetgen.load(str(source))
    expected = bionetgen.load(str(source)).simulate(**options)
    receipts = []
    difference = None
    for phase in ("first", "repeat"):
        actual = model.simulate(**options)
        receipts.append(_result_receipt(actual, phase=phase))
        difference = _result_difference(actual, expected)
        if difference is not None:
            break
    if difference is None:
        stopped = model.simulate(stop_if="time > 1.0", **options)
        receipts.append(_result_receipt(stopped, phase="stopped"))
        actual = model.simulate(**options)
        receipts.append(_result_receipt(actual, phase="after-stop"))
        difference = _result_difference(actual, expected)
    if difference is None:
        sampled = model.simulate(method="ssa", t_end=2.0, n_steps=10, seed=99)
        receipts.append(_result_receipt(sampled, phase="stochastic"))
        actual = model.simulate(**options)
        receipts.append(_result_receipt(actual, phase="after-stochastic"))
        difference = _result_difference(actual, expected)
    _write_lifecycle_receipt(directory, "lifecycle-independent-solver-state", receipts)
    return difference


def _lifecycle_exception_cleanup(bionetgen, case, directory):
    """Exception paths release the trajectory-owned state."""
    source = _lifecycle_control_source(case, directory, "lifecycle-exception.bngl")
    options = _lifecycle_deterministic_options()
    model = bionetgen.load(str(source))
    expected = bionetgen.load(str(source)).simulate(**options)
    expected_network = bionetgen.load(str(source)).generate_network()
    receipts = []
    difference = None
    for index in range(lifecycle_budget["exception_recovery_iterations"]):
        try:
            model.simulate(
                stop_if="if(time > 0, __lifecycle_missing_name__, 0)", **options
            )
        except RuntimeError as exc:
            if "__lifecycle_missing_name__" not in str(exc):
                difference = {"field": "exception.message", "detail": str(exc)}
                break
        else:
            difference = {"field": "exception.not_raised"}
            break
        actual = model.simulate(**options)
        receipts.append(
            _result_receipt(
                actual,
                phase="recovered",
                iteration=index,
                native_resource_cleanup=(
                    "NOT_TESTED; the ASan job's 'OdeIntegrator recovers after late "
                    "stop condition failure' test owns the native release proof"
                ),
            )
        )
        difference = _result_difference(actual, expected)
        if difference is not None:
            break
        if model._network is None or int(model._network.num_species) != int(
            expected_network.num_species
        ):
            difference = {"field": "exception.network_cache_damaged"}
            break
    _write_lifecycle_receipt(directory, "lifecycle-exception-cleanup", receipts)
    return difference


def _lifecycle_parameter_only_reuse(bionetgen, case, directory):
    """Parameter-only overrides reuse the compiled structure and match a compile."""
    from bionetgen import _bionetgen_cpp as cpp

    from .integrated_cases import RATE, reuse_bngl

    source = _lifecycle_control_source(case, directory, "lifecycle-parameter-only.bngl")
    options = _lifecycle_deterministic_options()
    model = bionetgen.load(str(source))
    expected = bionetgen.load(str(source)).simulate(**options)
    receipts = []
    difference = _analytic_result_difference(expected, case)
    if difference is not None:
        _write_lifecycle_receipt(directory, "lifecycle-parameter-only-reuse", receipts)
        return {"field": f"baseline.{difference['field']}"}
    compiled = model._model
    topology = _compiled_topology(cpp, model)
    for parameter in lifecycle_budget["parameter_only_overrides"]:
        value = RATE * 1.4
        model.set_parameter(parameter, value)
        actual = model.simulate(**options)
        reference_source = directory / f"lifecycle-parameter-only-{parameter}.bngl"
        reference_source.write_text(reuse_bngl(case, rate=value))
        fresh = bionetgen.load(str(reference_source)).simulate(**options)
        difference = _result_difference(actual, fresh)
        if difference is None:
            difference = _analytic_result_difference(
                actual, dict(case, _lifecycle_rate=value)
            )
        if difference is None and model._model is not compiled:
            difference = {"field": "parameter.compiled_model_replaced"}
        if difference is None and _compiled_topology(cpp, model) != topology:
            difference = {"field": "parameter.compiled_structure_changed"}
        receipts.append(_result_receipt(actual, parameter=parameter, value=value))
        if difference is not None:
            _write_lifecycle_receipt(
                directory, "lifecycle-parameter-only-reuse", receipts
            )
            return {"field": f"parameter.{parameter}.{difference['field']}"}
        model.set_parameter(parameter, RATE)
        restored = model.simulate(**options)
        difference = _result_difference(restored, expected)
        if difference is not None:
            _write_lifecycle_receipt(
                directory, "lifecycle-parameter-only-reuse", receipts
            )
            return {"field": f"restore.{parameter}.{difference['field']}"}
    _write_lifecycle_receipt(directory, "lifecycle-parameter-only-reuse", receipts)
    return None


def _lifecycle_topology_invalidation(bionetgen, case, directory):
    """A topology change invalidates the cached network and matches a compile."""
    from .integrated_cases import lifecycle_topology_sources

    base_source, fragment_source, merged_source = lifecycle_topology_sources(case)
    fragment_path = directory / "lifecycle-topology-fragment.bngl"
    fragment_path.write_text(fragment_source)
    base_path = directory / "lifecycle-topology-control.bngl"
    base_path.write_text(base_source)
    merged_path = directory / "lifecycle-topology-merged.bngl"
    merged_path.write_text(merged_source)
    options = _lifecycle_deterministic_options()
    model = bionetgen.load(str(base_path))
    before = list(model.generate_network().species_names)
    model.execute()
    receipts = []
    if model._network is not None:
        _write_lifecycle_receipt(directory, "lifecycle-topology-invalidation", receipts)
        return {
            "field": "topology.network_cache_not_invalidated",
            "cached_species": list(model._network.species_names),
            "species_before_action": before,
        }
    actual = model.simulate(**options)
    receipts.append(_result_receipt(actual, phase="merged"))
    fresh = bionetgen.load(str(merged_path)).simulate(**options)
    difference = _result_difference(actual, fresh)
    if difference is None:
        difference = _topology_result_difference(actual, case)
    if difference is None and list(model._network.species_names) == before:
        difference = {"field": "topology.species_not_added", "before": before}
    if difference is None:
        baseline = bionetgen.load(str(base_path)).simulate(**options)
        if _result_difference(actual, baseline) is None:
            difference = {"field": "topology.change_not_observable"}
    if difference is not None:
        _write_lifecycle_receipt(directory, "lifecycle-topology-invalidation", receipts)
        return difference
    _write_lifecycle_receipt(directory, "lifecycle-topology-invalidation", receipts)
    return None


def _lifecycle_compartment_invalidation(bionetgen, case, directory):
    """A compartment/volume change invalidates reuse and matches a compile."""
    from .integrated_cases import lifecycle_volume_bngl

    volume_case = dict(case, family="dimerization")
    new_volume = float(case["volume"]) * lifecycle_budget["volume_override_factor"]
    control = directory / "lifecycle-compartment.bngl"
    control.write_text(
        lifecycle_volume_bngl(
            volume_case,
            actions=f'  setVolume({{target=>"cell",value=>{new_volume:.17g}}})\n',
        )
    )
    reference = directory / "lifecycle-compartment-fresh.bngl"
    reference.write_text(lifecycle_volume_bngl(volume_case, volume=new_volume))
    options = _lifecycle_deterministic_options()
    model = bionetgen.load(str(control))
    baseline = model.simulate(**options)
    model.execute()
    receipts = []
    if model._network is not None:
        _write_lifecycle_receipt(
            directory, "lifecycle-compartment-invalidation", receipts
        )
        return {"field": "compartment.network_cache_not_invalidated"}
    actual = model.simulate(**options)
    receipts.append(_result_receipt(actual, phase="new-volume"))
    fresh = bionetgen.load(str(reference)).simulate(**options)
    difference = _result_difference(actual, fresh)
    if difference is None:
        difference = _analytic_result_difference(
            actual, dict(volume_case, volume=new_volume)
        )
    if difference is None and _result_difference(actual, baseline) is None:
        difference = {"field": "compartment.volume_change_not_observable"}
    if difference is not None:
        _write_lifecycle_receipt(
            directory, "lifecycle-compartment-invalidation", receipts
        )
        return difference
    _write_lifecycle_receipt(directory, "lifecycle-compartment-invalidation", receipts)
    return None


_LIFECYCLE_CHECKS = (
    (
        "lifecycle-construction-isolation",
        "two concurrently constructed models with distinct seeds and parameters, "
        "three interleaved SSA runs each, compared with fresh construction",
        _lifecycle_construction_isolation,
    ),
    (
        "lifecycle-mutation-baseline",
        "volume, population and rate mutations compared with fresh compilations "
        "and the closed-form law, then restored",
        _lifecycle_mutation_baseline,
    ),
    (
        "lifecycle-public-routes",
        "the public CLI run route and a CLI action route compared with the API "
        "and the closed-form law",
        _lifecycle_public_routes,
    ),
    (
        "lifecycle-repeated-instantiation",
        "one compiled model instantiated repeatedly; every run compared with a "
        "fresh compilation",
        _lifecycle_repeated_instantiation,
    ),
    (
        "lifecycle-concurrent-instantiation",
        "concurrently constructed and simulated instances; every trajectory "
        "compared with a fresh compilation and the caches kept distinct",
        _lifecycle_concurrent_instantiation,
    ),
    (
        "lifecycle-independent-rng",
        "seeded trajectories replayed and interleaved on one instance and on an "
        "independent instance",
        _lifecycle_independent_rng,
    ),
    (
        "lifecycle-independent-caches",
        "one instance mutated while its sibling keeps its own parameters and its "
        "own generated network",
        _lifecycle_independent_caches,
    ),
    (
        "lifecycle-independent-solver-state",
        "repeated, early-stopped and interleaved stochastic runs on one instance "
        "compared with a fresh compilation",
        _lifecycle_independent_solver_state,
    ),
    (
        "lifecycle-exception-cleanup",
        "a late stop-condition failure followed by repeated recoveries compared "
        "with a fresh compilation",
        _lifecycle_exception_cleanup,
    ),
    (
        "lifecycle-parameter-only-reuse",
        "a parameter-only override compared with a fresh compilation and the "
        "closed-form law, with the compiled structure preserved",
        _lifecycle_parameter_only_reuse,
    ),
    (
        "lifecycle-topology-invalidation",
        "a topology-changing action invalidates the cached network; the rebuilt "
        "trajectory compared with a fresh compilation and the closed-form law",
        _lifecycle_topology_invalidation,
    ),
    (
        "lifecycle-compartment-invalidation",
        "a compartment-volume change invalidates reuse; the rebuilt trajectory "
        "compared with a fresh compilation and the closed-form law",
        _lifecycle_compartment_invalidation,
    ),
)

_LIFECYCLE_CHECK_NAMES = tuple(name for name, _detail, _check in _LIFECYCLE_CHECKS)
