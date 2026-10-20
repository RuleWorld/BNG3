"""Isolated public-API legs for the integration matrix; no oracle substitution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path


def write_result(result, path):
    import numpy as np

    names = list(result.observables)
    values = np.column_stack([result.time] + [result.observables[n] for n in names])
    np.savetxt(path, values, header="time " + " ".join(names), fmt="%.17g")


class HarnessError(RuntimeError):
    pass


def _same_results(left, right, *, atol=1e-10, rtol=1e-9):
    """Return a compact first difference between public simulation results."""
    import numpy as np

    left_names, right_names = list(left.observables), list(right.observables)
    if left_names != right_names:
        return {"field": "columns", "left": left_names, "right": right_names}
    left_time = np.asarray(left.time, dtype=float)
    right_time = np.asarray(right.time, dtype=float)
    if left_time.shape != right_time.shape:
        return {
            "field": "time.shape",
            "left": list(left_time.shape),
            "right": list(right_time.shape),
        }
    for row, (a, b) in enumerate(zip(left_time, right_time)):
        if not np.isfinite(a) or not np.isfinite(b):
            return {
                "field": "time.finite",
                "row": row,
                "left": float(a),
                "right": float(b),
            }
        if not np.isclose(a, b, atol=atol, rtol=rtol):
            return {"field": "time", "row": row, "left": float(a), "right": float(b)}
    for name in left_names:
        a_values = np.asarray(left.observables[name], dtype=float)
        b_values = np.asarray(right.observables[name], dtype=float)
        if a_values.shape != b_values.shape:
            return {
                "field": name + ".shape",
                "left": list(a_values.shape),
                "right": list(b_values.shape),
            }
        for row, (a, b) in enumerate(zip(a_values, b_values)):
            if not np.isfinite(a) or not np.isfinite(b):
                return {
                    "field": name + ".finite",
                    "row": row,
                    "time": float(left_time[row]),
                    "left": float(a),
                    "right": float(b),
                }
            if not np.isclose(a, b, atol=atol, rtol=rtol):
                return {
                    "field": name,
                    "row": row,
                    "time": float(left_time[row]),
                    "left": float(a),
                    "right": float(b),
                }
    return None


def _document_difference(left, right, path=""):
    """First deterministic JSON pointer difference; retain missing-vs-null."""
    if type(left) is not type(right):
        return dict(field=path or "/", left=left, right=right)
    if isinstance(left, dict):
        for key in sorted(left.keys() | right.keys()):
            pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in left:
                return dict(field=pointer, left_missing=True, right=right[key])
            if key not in right:
                return dict(field=pointer, left=left[key], right_missing=True)
            difference = _document_difference(left[key], right[key], pointer)
            if difference is not None:
                return difference
    elif isinstance(left, list):
        if len(left) != len(right):
            return dict(field=path + "/length", left=len(left), right=len(right))
        for index, (a, b) in enumerate(zip(left, right)):
            difference = _document_difference(a, b, path + "/" + str(index))
            if difference is not None:
                return difference
    elif left != right:
        return dict(field=path or "/", left=left, right=right)
    return None


def _semantic_difference(bionetgen, source, restored, version):
    left = json.loads(bionetgen.to_bngir(source, version=version))
    right = json.loads(bionetgen.to_bngir(restored, version=version))
    Path("source-semantic.json").write_text(json.dumps(left, indent=2) + "\n")
    Path("restored-semantic.json").write_text(json.dumps(right, indent=2) + "\n")
    return _document_difference(left, right)


def _new_check(case_id, operation, name, status, detail, first_difference=None):
    from tests.validation.integrated_consumers import ISSUES

    return {
        "id": f"{case_id}:{operation}:{name}",
        "name": name,
        "status": status,
        "detail": str(detail),
        "first_difference": first_difference,
        "issue_ids": list(ISSUES[operation]),
    }


def _write_checks(checks):
    Path("checks.json").write_text(json.dumps(checks, indent=2) + "\n")


def _save_comparison(checks, case_id, operation, name, detail, difference=None):
    checks.append(
        _new_check(
            case_id,
            operation,
            name,
            "FAIL" if difference else "PASS",
            detail,
            difference,
        )
    )


def _complete_checks(case_id, operation, checks, detail):
    from tests.validation.integrated_consumers import CHECKS

    present = {row.get("name") for row in checks}
    for row in checks:
        if row.get("status") == "NOT_TESTED" and row.get("detail") == (
            "consumer operation did not reach this check"
        ):
            row["detail"] = detail
    for name in CHECKS[operation]:
        if name not in present:
            checks.append(_new_check(case_id, operation, name, "NOT_TESTED", detail))
    _write_checks(checks)


def _rate_parameter(model):
    from tests.validation.integrated_protocol import _rate_parameter as find_dependency

    return find_dependency(model)


def _network_snapshot(network, model=None):
    """Capture generated graph data exposed by the public Python binding."""
    snapshot = {
        "num_species": int(network.num_species),
        "num_reactions": int(network.num_reactions),
        "species": list(network.species_names),
        "reaction_labels_diagnostic_only": list(network.reaction_strings),
    }
    if model is not None:
        from bionetgen import _bionetgen_cpp as cpp

        state = [1.0] * network.num_species
        snapshot["unit_state_probe"] = {
            "state": state,
            "reaction_rate_coefficients": list(
                cpp._validation_ode_rate_coefficients(model._model, network, 0.0, state)
            ),
            "ode_rhs": list(cpp._validation_ode_rhs(model._model, network, 0.0, state)),
        }
    return snapshot


def _network_difference(left, right):
    import numpy as np
    from tests.validation.compare import species_isomorphic

    for field in ("num_species", "num_reactions"):
        if left[field] != right[field]:
            return {"field": field, "left": left[field], "right": right[field]}
    unmatched = list(range(len(right["species"])))
    species_mapping = []
    for source_species in left["species"]:
        match = next(
            (
                index
                for index in unmatched
                if species_isomorphic(source_species, right["species"][index])
            ),
            None,
        )
        if match is None:
            return {
                "field": "species_identity",
                "left": source_species,
                "right": unmatched,
            }
        species_mapping.append(match)
        unmatched.remove(match)
    if unmatched:
        return {"field": "species_identity", "left": [], "right": unmatched}

    for field in ("state", "ode_rhs"):
        a = np.asarray(left["unit_state_probe"][field], dtype=float)
        b = np.asarray(right["unit_state_probe"][field], dtype=float)
        if b.ndim == 1 and len(b) == len(species_mapping):
            b = b[species_mapping]
        if a.shape != b.shape:
            return {
                "field": f"unit_state_probe.{field}.shape",
                "left": list(a.shape),
                "right": list(b.shape),
            }
        delta = np.flatnonzero(~np.isclose(a, b, rtol=1e-12, atol=1e-14))
        if len(delta):
            index = int(delta[0])
            return {
                "field": f"unit_state_probe.{field}",
                "index": index,
                "left": float(a[index]),
                "right": float(b[index]),
            }
    return None


def _sbml_observable_ids(path, observable_names):
    """Map source observables to assigned parameter IDs in exported SBML."""
    import xml.etree.ElementTree as ET

    root = ET.parse(path).getroot()
    elements = lambda name: [
        item for item in root.iter() if item.tag.rsplit("}", 1)[-1] == name
    ]
    assigned = {rule.get("variable") for rule in elements("assignmentRule")}
    parameters = elements("parameter")
    result = {}
    for name in observable_names:
        matches = [
            parameter
            for parameter in parameters
            if parameter.get("name") == name
            and parameter.get("constant", "true").lower() == "false"
            and parameter.get("id") in assigned
        ]
        if len(matches) != 1:
            return None
        result[name] = matches[0].get("id")
    return result


def _run_consumer(operation, source_path, case_id, bionetgen):
    import numpy as np
    from tests.validation.integrated_consumers import status_from_checks

    checks = []
    source = bionetgen.load(str(source_path))
    source_network = source.generate_network()
    source_network_snapshot = _network_snapshot(source_network, source)
    if operation != "bngir-v02":
        source.write_net("model.net")

    if operation in ("bngir-v01", "bngir-v02"):
        version = "0.1" if operation == "bngir-v01" else "0.2"
        try:
            document = source.to_bngir(version=version)
        except ValueError as exc:
            if (
                version != "0.1"
                or "cannot represent physical-unit metadata" not in str(exc)
            ):
                raise
            checks.extend(
                [
                    _new_check(
                        case_id, operation, "semantic-equality", "UNSUPPORTED", str(exc)
                    ),
                    _new_check(
                        case_id,
                        operation,
                        "network",
                        "NOT_TESTED",
                        "v0.1 serialization prerequisite is unsupported",
                    ),
                    _new_check(
                        case_id,
                        operation,
                        "simulation",
                        "NOT_TESTED",
                        "v0.1 serialization prerequisite is unsupported",
                    ),
                ]
            )
            _write_checks(checks)
            return "UNSUPPORTED"
        Path("model.bngir.json").write_text(document, encoding="utf-8")
        native_unsupported = None
        if version == "0.2":
            import bionetgen.bngir as bngir_module
            from bionetgen.model import _cpp

            def forbidden(*_args, **_kwargs):
                raise HarnessError("BNGIR v0.2 reconstruction attempted BNGL fallback")

            original_renderer = bngir_module._as_bngl_v02
            original_parser = _cpp.parse_string
            try:
                bngir_module._as_bngl_v02 = forbidden
                try:
                    _cpp.parse_string = forbidden
                    try:
                        restored = bionetgen.from_bngir(
                            json.loads(document), native=True
                        )
                    except ValueError as exc:
                        # The native v0.2 gate is fail-closed: a section outside
                        # its slice is explicitly unsupported, not a silent BNGL
                        # fallback and not a harness crash. Other native gate
                        # violations (dense ids, required fields) stay failures.
                        if not str(exc).startswith("native BNGIR does not support"):
                            raise
                        native_unsupported = str(exc)
                finally:
                    _cpp.parse_string = original_parser
            finally:
                bngir_module._as_bngl_v02 = original_renderer
        else:
            restored = bionetgen.from_bngir(json.loads(document))
        if native_unsupported is not None:
            checks.extend(
                [
                    _new_check(
                        case_id,
                        operation,
                        "semantic-equality",
                        "UNSUPPORTED",
                        native_unsupported,
                    ),
                    _new_check(
                        case_id,
                        operation,
                        "network",
                        "NOT_TESTED",
                        "native v0.2 reconstruction prerequisite is unsupported",
                    ),
                    _new_check(
                        case_id,
                        operation,
                        "simulation",
                        "NOT_TESTED",
                        "native v0.2 reconstruction prerequisite is unsupported",
                    ),
                ]
            )
            _write_checks(checks)
            return "UNSUPPORTED"
        equal = bionetgen.semantic_equal(source, restored, version=version)
        _save_comparison(
            checks,
            case_id,
            operation,
            "semantic-equality",
            f"BNGIR v{version} reconstructed model semantic equality",
            (
                None
                if equal
                else _semantic_difference(bionetgen, source, restored, version)
            ),
        )
        restored_network = restored.generate_network()
        if version == "0.2":
            native_snapshot = _network_snapshot(restored_network, restored)
            Path("source-network.json").write_text(
                json.dumps(source_network_snapshot, indent=2) + "\n", encoding="utf-8"
            )
            Path("native-network.json").write_text(
                json.dumps(native_snapshot, indent=2) + "\n", encoding="utf-8"
            )
            difference = _network_difference(source_network_snapshot, native_snapshot)
            _save_comparison(
                checks,
                case_id,
                operation,
                "network",
                "compared species graph multiset, counts, and aggregate unit-state ODE RHS; reaction labels/rate coefficients are retained as diagnostics because bindings expose labels and order-dependent coefficients rather than per-reaction stoichiometry",
                difference,
            )
        else:
            restored.write_net("model.net")
            _save_comparison(
                checks,
                case_id,
                operation,
                "network",
                "reconstructed model generated model.net",
            )
        result = restored.simulate(
            method="ode", t_end=2, n_steps=10, rtol=1e-10, atol=1e-12
        )
        write_result(result, "api.gdat")
        _save_comparison(
            checks,
            case_id,
            operation,
            "simulation",
            "reconstructed model wrote api.gdat",
        )

    elif operation == "bngl-reload":
        source.write_bngl("roundtrip.bngl")
        restored = bionetgen.load("roundtrip.bngl")
        equal = bionetgen.semantic_equal(source, restored, version="0.2")
        _save_comparison(
            checks,
            case_id,
            operation,
            "semantic-equality",
            "write_bngl then reload semantic equality",
            (
                None
                if equal
                else _semantic_difference(bionetgen, source, restored, "0.2")
            ),
        )
        restored.generate_network()
        restored.write_net("model.net")
        _save_comparison(
            checks, case_id, operation, "network", "reloaded model generated model.net"
        )
        write_result(
            restored.simulate(
                method="ode", t_end=2, n_steps=10, rtol=1e-10, atol=1e-12
            ),
            "api.gdat",
        )
        _save_comparison(
            checks, case_id, operation, "simulation", "reloaded model wrote api.gdat"
        )

    elif operation == "sbml-reload":
        source.write_sbml("model.xml")
        _save_comparison(checks, case_id, operation, "export", "BNG3 wrote model.xml")
        _write_checks(checks)
        try:
            import roadrunner
        except ImportError as exc:
            checks.append(
                _new_check(
                    case_id,
                    operation,
                    "rr-consumer",
                    "HARNESS_ERROR",
                    f"required libRoadRunner dependency unavailable: {exc}",
                )
            )
            checks.append(
                _new_check(
                    case_id,
                    operation,
                    "trajectory",
                    "NOT_TESTED",
                    "observable mapping prerequisite unavailable",
                )
            )
            _write_checks(checks)
            return "HARNESS_ERROR"
        names = [observable.name for observable in source.observables]
        selection_ids = _sbml_observable_ids("model.xml", names)
        if len(names) != len(set(names)) or not names or selection_ids is None:
            checks.append(
                _new_check(
                    case_id,
                    operation,
                    "rr-consumer",
                    "UNSUPPORTED",
                    "original BNG3 observable names are empty, duplicated, or do not map uniquely to SBML assignment rules",
                )
            )
            checks.append(
                _new_check(
                    case_id,
                    operation,
                    "trajectory",
                    "NOT_TESTED",
                    "observable mapping prerequisite unavailable",
                )
            )
            _write_checks(checks)
            return "UNSUPPORTED"
        try:
            rr = roadrunner.RoadRunner(str(Path("model.xml").resolve()))
            global_parameter_ids = set(rr.model.getGlobalParameterIds())
        except Exception as exc:
            _save_comparison(
                checks,
                case_id,
                operation,
                "rr-consumer",
                f"libRoadRunner could not load exported SBML: {type(exc).__name__}: {exc}",
                {"exception_type": type(exc).__name__, "detail": str(exc)},
            )
            _complete_checks(case_id, operation, checks, "RoadRunner loading failed")
            return "FAIL"
        if not set(selection_ids.values()).issubset(global_parameter_ids):
            checks.append(
                _new_check(
                    case_id,
                    operation,
                    "rr-consumer",
                    "UNSUPPORTED",
                    "mapped observable assignment IDs are absent from RoadRunner global parameters",
                )
            )
            checks.append(
                _new_check(
                    case_id,
                    operation,
                    "trajectory",
                    "NOT_TESTED",
                    "observable mapping prerequisite unavailable",
                )
            )
            _write_checks(checks)
            return "UNSUPPORTED"
        selections = ["time", *(selection_ids[name] for name in names)]
        checks.append(
            _new_check(
                case_id,
                operation,
                "rr-consumer",
                "PASS",
                f"libRoadRunner consumed exported SBML through observable IDs mapped from original BNG3 names {names}: {selection_ids}",
            )
        )
        _write_checks(checks)
        try:
            rr.integrator.relative_tolerance = 1e-10
            rr.integrator.absolute_tolerance = 1e-12
            reference = source.simulate(
                method="ode", t_end=2, n_steps=10, rtol=1e-10, atol=1e-12
            )
            rr_result = rr.simulate(
                times=np.asarray(reference.time, dtype=float), selections=selections
            )
            rr_public_result = type(
                "Result",
                (),
                {
                    "time": rr_result[:, 0],
                    "observables": {
                        name: rr_result[:, i + 1] for i, name in enumerate(names)
                    },
                },
            )()
            write_result(rr_public_result, "api.gdat")
            first = _same_results(reference, rr_public_result, atol=1e-8, rtol=1e-7)
        except Exception as exc:
            _save_comparison(
                checks,
                case_id,
                operation,
                "trajectory",
                f"SBML trajectory execution failed: {type(exc).__name__}: {exc}",
                {"exception_type": type(exc).__name__, "detail": str(exc)},
            )
            _complete_checks(case_id, operation, checks, "trajectory execution failed")
            return "FAIL"
        _save_comparison(
            checks,
            case_id,
            operation,
            "trajectory",
            "libRoadRunner SBML result compared against original BNG3 observable mapping",
            first,
        )

    elif operation == "reuse":
        baseline = source.simulate(
            method="ode", t_end=2, n_steps=10, rtol=1e-10, atol=1e-12
        )
        write_result(baseline, "api.gdat")
        checks.append(
            _new_check(
                case_id,
                operation,
                "original",
                "PASS",
                "original model result persisted as api.gdat",
            )
        )
        rate_name = _rate_parameter(source)
        if rate_name is None:
            checks.append(
                _new_check(
                    case_id,
                    operation,
                    "mutation-fresh",
                    "NOT_TESTED",
                    "no parameter dependency in translated reaction rates; numeric folding is allowed",
                )
                | {"applicability": "no-rate-parameter-dependency"}
            )
        else:
            old_rate = source.get_parameter(rate_name).value
            if old_rate is None or not np.isfinite(old_rate):
                raise HarnessError(
                    f"source rate parameter {rate_name!r} is not a finite scalar"
                )
            old_rate = float(old_rate)
            changed_rate = old_rate * 1.5
            mutation_source = Path(source_path).resolve()
            (Path.cwd() / "mutation.json").write_text(
                json.dumps(
                    {
                        "parameter": rate_name,
                        "original_value": old_rate,
                        "mutated_value": changed_rate,
                        "factor": 1.5,
                        "source_path": str(mutation_source),
                        "source_sha256": hashlib.sha256(
                            mutation_source.read_bytes()
                        ).hexdigest(),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            source.set_parameter(rate_name, changed_rate)
            mutated = source.simulate(
                method="ode", t_end=2, n_steps=10, rtol=1e-10, atol=1e-12
            )
            write_result(mutated, "reuse-mutated.gdat")
            fresh = bionetgen.load(str(source_path))
            fresh.set_parameter(rate_name, changed_rate)
            fresh_result = fresh.simulate(
                method="ode", t_end=2, n_steps=10, rtol=1e-10, atol=1e-12
            )
            write_result(fresh_result, "reuse-fresh.gdat")
            mutation_difference = _same_results(mutated, fresh_result)
            if mutation_difference is None and _same_results(baseline, mutated) is None:
                mutation_difference = {
                    "field": "parameter-mutation-effect",
                    "parameter": rate_name,
                    "value": changed_rate,
                    "detail": "mutated trajectory is identical to original trajectory",
                }
            _save_comparison(
                checks,
                case_id,
                operation,
                "mutation-fresh",
                f"mutated native model parameter {rate_name!r} compared with fresh parse and compilation",
                mutation_difference,
            )
            source.set_parameter(rate_name, old_rate)
        reset = source.simulate(
            method="ode", t_end=2, n_steps=10, rtol=1e-10, atol=1e-12
        )
        write_result(reset, "reuse-reset.gdat")
        _save_comparison(
            checks,
            case_id,
            operation,
            "reset",
            "reset model compared with the preserved original result",
            _same_results(baseline, reset),
        )
        repeat_a = bionetgen.load(str(source_path)).simulate(
            method="ssa", t_end=2, n_steps=10, seed=17
        )
        repeat_b = bionetgen.load(str(source_path)).simulate(
            method="ssa", t_end=2, n_steps=10, seed=17
        )
        write_result(repeat_a, "reuse-ssa-a.gdat")
        write_result(repeat_b, "reuse-ssa-b.gdat")
        _save_comparison(
            checks,
            case_id,
            operation,
            "seeded-repeat",
            "independent fresh SSA models with the same seed",
            _same_results(repeat_a, repeat_b, atol=0, rtol=0),
        )

    _write_checks(checks)
    return status_from_checks(case_id, operation, checks)


def write_legacy_result(result):
    import numpy as np

    if set(result.gdats) != {"model"}:
        raise RuntimeError(
            f"returned result lost/duplicated model output: {list(result.gdats)}"
        )
    data = result.gdats["model"]
    np.savetxt(
        "api.gdat",
        np.column_stack([data[n] for n in data.dtype.names]),
        header=" ".join(data.dtype.names),
        fmt="%.17g",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "atomizer",
            "rate-trace",
            "api",
            "nf",
            "pybng",
            "compat",
            "bngir-v01",
            "bngir-v02",
            "bngl-reload",
            "sbml-reload",
            "reuse",
            "boundaries",
            "protocol",
            "nf-marginals",
            "graph-identity",
            "graph-identity-contract",
            "bngir-adversarial",
            "quantity-laws",
            "export-format-tier",
            "netrule-execution",
        ),
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--atomize", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--case-id", default="case")
    parser.add_argument("--case-json")
    parser.add_argument("--native-nfsim", type=Path)
    parser.add_argument("--native-xml", type=Path)
    parser.add_argument("--ensemble-runs", type=int, default=32)
    parser.add_argument("--ensemble-cases", type=int, default=48)
    parser.add_argument("--xml-out", type=Path)
    parser.add_argument("--bng-cpp", type=Path)
    args = parser.parse_args()
    consumer_operations = (
        "bngir-v01",
        "bngir-v02",
        "bngl-reload",
        "sbml-reload",
        "reuse",
    )
    if args.operation == "pybng":
        # -I excludes inherited PYTHONPATH and user site paths. The dedicated interpreter has dependencies, not a second BNG3.
        root = args.upstream.resolve()
        sys.path.insert(0, str(root))
        import bionetgen
        from bionetgen.modelapi import runner
        from bionetgen.main import get_conf

        get_conf()["bngpath"] = os.environ["BNGPATH"]

        package = Path(bionetgen.__file__).resolve()
        runner_path = Path(runner.__file__).resolve()
        if package.parent != root / "bionetgen" or not runner_path.is_relative_to(root):
            raise HarnessError("upstream worker imported a different bionetgen package")
        identity = {
            "package_file": str(package),
            "runner_file": str(runner_path),
            "runner_sha256": hashlib.sha256(runner_path.read_bytes()).hexdigest(),
            "python_executable": sys.executable,
            "python_prefix": sys.prefix,
            "bngpath": os.environ["BNGPATH"],
            "simulator": "subprocess",
        }
        Path("identity.json").write_text(json.dumps(identity, indent=2) + "\n")
        # Exercise the public upstream API, force the independently built BNG2
        # rather than an optional BNGsim or a downloaded bundled executable.
        result = bionetgen.run(
            str(args.input),
            str(Path.cwd()),
            suppress=True,
            timeout=30,
            simulator="subprocess",
        )
        write_legacy_result(result)
        return

    if args.operation in consumer_operations:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from tests.validation.integrated_consumers import CHECKS

        _write_checks(
            [
                _new_check(
                    args.case_id,
                    args.operation,
                    name,
                    "NOT_TESTED",
                    "consumer operation did not reach this check",
                )
                for name in CHECKS[args.operation]
            ]
        )

    # Only expose the repository's identity helper, never its python/ package.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.ci.check_python_package_identity import inspect_installed_package

    try:
        identity = inspect_installed_package()
    except RuntimeError as exc:
        raise HarnessError(str(exc)) from exc
    Path("identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    import bionetgen

    if args.operation in (
        "boundaries",
        "protocol",
        "nf-marginals",
        "graph-identity",
        "graph-identity-contract",
        "bngir-adversarial",
        "quantity-laws",
        "export-format-tier",
        "netrule-execution",
    ):
        from tests.validation.integrated_extensions import run_worker

        checks = run_worker(args.operation, args)
        _write_checks(checks)
        statuses = {row["status"] for row in checks}
        status = next(
            (
                value
                for value in (
                    "HARNESS_ERROR",
                    "FAIL",
                    "TIMEOUT",
                    "INVALID_INPUT",
                    "UNSUPPORTED",
                    "NOT_TESTED",
                )
                if value in statuses
            ),
            "PASS",
        )
        Path("worker-status.json").write_text(json.dumps({"status": status}) + "\n")
        raise SystemExit(0 if checks and status == "PASS" else 1)

    if args.operation in consumer_operations:
        try:
            status = _run_consumer(args.operation, args.input, args.case_id, bionetgen)
        except Exception as exc:
            existing = []
            check_path = Path("checks.json")
            if check_path.is_file():
                try:
                    existing = json.loads(check_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    existing = []
            _complete_checks(
                args.case_id,
                args.operation,
                existing,
                f"not reached after {type(exc).__name__}: {exc}",
            )
            raise
        Path("worker-status.json").write_text(
            json.dumps({"status": status}, indent=2) + "\n"
        )
        if status in ("UNSUPPORTED", "NOT_TESTED"):
            raise SystemExit(1)
        if status in ("FAIL", "HARNESS_ERROR"):
            exception = HarnessError if status == "HARNESS_ERROR" else RuntimeError
            raise exception("integrated consumer check failed; see checks.json")
        return

    if args.operation == "atomizer":
        text = bionetgen.sbml_to_bngl(
            str(args.input),
            atomize=args.atomize,
            use_id=True,
            actions="",
        )
        Path("model.bngl").write_text(text)
        if args.xml_out is not None:
            # BNG3's own NFsim XML export; native routes must consume this,
            # not BNG2's XML, to observe BNG3 conversion semantics.
            args.xml_out.parent.mkdir(parents=True, exist_ok=True)
            bionetgen.load("model.bngl").write_xml(str(args.xml_out))
    elif args.operation == "rate-trace":
        model = bionetgen.load(str(args.input))
        network = model.generate_network()
        from bionetgen import _bionetgen_cpp as cpp

        state = [1.0] * network.num_species
        observation = {
            "observer": "BNG3 native compiled ODE rate coefficients and RHS",
            "species": list(network.species_names),
            "reaction_labels_diagnostic_only": list(network.reaction_strings),
            "state": state,
            "reaction_rate_coefficients": list(
                cpp._validation_ode_rate_coefficients(model._model, network, 0.0, state)
            ),
            "ode_rhs": list(cpp._validation_ode_rhs(model._model, network, 0.0, state)),
        }
        model.write_net("model.net")
        try:
            model.write_xml("model.xml")
            observation["bng_xml_export"] = {"status": "OBSERVED", "path": "model.xml"}
        except (RuntimeError, ValueError) as exc:
            observation["bng_xml_export"] = {
                "status": "UNSUPPORTED",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        Path("rate-trace.json").write_text(json.dumps(observation, indent=2) + "\n")
    elif args.operation == "api":
        model = bionetgen.load(str(args.input))
        model.generate_network()
        model.write_net("model.net")
        write_result(
            model.simulate(method="ode", t_end=2, n_steps=10, rtol=1e-10, atol=1e-12),
            "api.gdat",
        )
    elif args.operation == "compat":
        result = bionetgen.run(str(args.input), str(Path.cwd()), suppress=True)
        write_legacy_result(result)
    else:
        model = bionetgen.load(str(args.input))
        result = model.simulate(method="nf", t_end=2, n_steps=10, seed=7)
        if result.construction_path != "direct":
            raise RuntimeError(f"NFsim path changed: {result.construction_path}")
        write_result(result, "nf.gdat")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        Path("worker-status.json").write_text(
            json.dumps(
                {
                    "status": (
                        "HARNESS_ERROR"
                        if isinstance(exc, (HarnessError, ImportError))
                        else "FAIL"
                    ),
                    "exception_type": type(exc).__name__,
                    "detail": str(exc),
                },
                indent=2,
            )
            + "\n"
        )
        raise
