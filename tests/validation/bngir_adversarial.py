"""Independent native BNGIR v0.2 controls for cross-reference integrity."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

from .campaign import STATUSES

ISSUES = [153, 154, 155, 156, 163]
OPERATION = "bngir-adversarial"


class NativeRefusal(RuntimeError):
    """An explicit refusal returned by the native BNGIR importer."""


class HarnessError(RuntimeError):
    """The adapter could not establish a native semantic outcome."""


def _number(value):
    return {"kind": "number", "value": value}


def _parameter(index):
    return {"kind": "parameter_ref", "symbol": {"kind": "parameter", "index": index}}


def _pattern(name, type_id):
    return {
        "compartment_prefix": False,
        "molecules": [{"occurrence": 0, "type": name, "type_id": type_id, "sites": []}],
    }


def _direction(reactant, product):
    return {
        "reactants": [reactant],
        "products": [product],
        "rate": {"kind": 0, "expression": _parameter(1)},
        "transformations_complete": True,
        "mutations": [],
        "filters": [],
        "local_scopes": [],
    }


def _document():
    """An independent wire document; it is not generated from BNGL or BNG3."""
    return {
        "format": "BNGIR",
        "version": "0.2",
        "features": {
            "required": [],
            "used": ["parameters", "molecule_types", "seeds", "rules"],
        },
        "protocol": {"actions": []},
        "model": {
            "metadata": {
                "name": "independent_decay",
                "version": "2.2",
                "substance_units": "item",
                "options": {},
            },
            "parameters": [
                {"id": 0, "name": "base", "expression": _number(0.05)},
                {
                    "id": 1,
                    "name": "k",
                    "expression": {
                        "kind": "binary",
                        "operator": "multiply",
                        "arguments": [_number(2.0), _parameter(0)],
                    },
                },
            ],
            "molecule_types": [
                {"id": 0, "name": "A", "population": False, "components": []},
                {"id": 1, "name": "B", "population": False, "components": []},
            ],
            "compartments": [],
            "seeds": [
                {
                    "id": 0,
                    "pattern": _pattern("A", 0),
                    "amount": _number(100.0),
                    "constant": False,
                }
            ],
            "observables": [],
            "functions": [],
            "energy_patterns": [],
            "population_maps": [],
            "rules": [
                {
                    "id": 0,
                    "name": "convert",
                    "label": "convert",
                    "bidirectional": False,
                    "forward": _direction(_pattern("A", 0), _pattern("B", 1)),
                    "modifiers": [],
                    "molecule_mappings": [],
                    "component_mappings": [],
                }
            ],
        },
    }


def _remap_parameter_ids(model, order):
    parameters = {item["name"]: item for item in model["parameters"]}
    old_to_new = {parameters[name]["id"]: new for new, name in enumerate(order)}
    model["parameters"] = [parameters[name] for name in order]
    for new, item in enumerate(model["parameters"]):
        item["id"] = new

    def visit(value):
        if isinstance(value, dict):
            symbol = value.get("symbol")
            if isinstance(symbol, dict) and symbol.get("kind") == "parameter":
                symbol["index"] = old_to_new[symbol["index"]]
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(model)


def generated_cases():
    """Return supported positive controls and schema-valid adversarial inputs."""
    baseline = _document()
    cases = [
        {
            "id": "baseline-native-control",
            "document": baseline,
            "oracle": "accept",
            "expected_semantics": {
                "seed": {"A()": 100.0, "B()": 0.0},
                "rhs": {"A()": -10.0, "B()": 10.0},
            },
        }
    ]

    alpha = copy.deepcopy(baseline)
    alpha["model"]["metadata"]["name"] = "renamed_decay"
    alpha["model"]["parameters"][0]["name"] = "scale"
    alpha["model"]["parameters"][1]["name"] = "rate"
    alpha["model"]["molecule_types"][0]["name"] = "X"
    alpha["model"]["molecule_types"][1]["name"] = "Y"
    alpha["model"]["seeds"][0]["pattern"] = _pattern("X", 0)
    alpha["model"]["rules"][0]["forward"] = _direction(
        _pattern("X", 0), _pattern("Y", 1)
    )
    cases.append(
        {
            "id": "alpha-renamed-symbols",
            "document": alpha,
            "oracle": "accept",
            "expected_semantics": {
                "seed": {"X()": 100.0, "Y()": 0.0},
                "rhs": {"X()": -10.0, "Y()": 10.0},
            },
        }
    )

    ordered = copy.deepcopy(baseline)
    _remap_parameter_ids(ordered["model"], ("k", "base"))
    cases.append(
        {
            "id": "parameter-declaration-order",
            "document": ordered,
            "oracle": "accept",
            "expected_semantics": {
                "seed": {"A()": 100.0, "B()": 0.0},
                "rhs": {"A()": -10.0, "B()": 10.0},
            },
        }
    )

    nested = copy.deepcopy(baseline)
    nested["model"]["rules"][0]["forward"]["rate"]["expression"] = {
        "kind": "binary",
        "operator": "multiply",
        "arguments": [_parameter(1), _number(1.0)],
    }
    cases.append(
        {
            "id": "nested-rate-expression",
            "document": nested,
            "oracle": "accept",
            "expected_semantics": {
                "seed": {"A()": 100.0, "B()": 0.0},
                "rhs": {"A()": -10.0, "B()": 10.0},
            },
        }
    )

    # A rate law that runs through a model function. The function binds its own
    # argument and the rule calls it with a parameter, so the rate stays the
    # declared 0.1 and the closed-form trajectory is unchanged.
    functions = copy.deepcopy(baseline)
    functions["features"]["used"] = sorted(
        [*functions["features"]["used"], "functions"]
    )
    functions["model"]["functions"] = [
        {
            "id": 0,
            "name": "doubled",
            "arguments": ["x"],
            "expression": {
                "kind": "binary",
                "operator": "add",
                "arguments": [
                    {"kind": "local_ref", "name": "x"},
                    {"kind": "local_ref", "name": "x"},
                ],
            },
        }
    ]
    functions["model"]["rules"][0]["forward"]["rate"]["expression"] = {
        "kind": "function_ref",
        "symbol": {"kind": "function", "index": 0},
        "call": True,
        "arguments": [_parameter(0)],
    }
    cases.append(
        {
            "id": "function-rate-law",
            "document": functions,
            "oracle": "accept",
            "expected_semantics": {
                "seed": {"A()": 100.0, "B()": 0.0},
                "rhs": {"A()": -10.0, "B()": 10.0},
            },
        }
    )

    permuted = copy.deepcopy(baseline)
    permuted["model"]["molecule_types"].reverse()
    for index, item in enumerate(permuted["model"]["molecule_types"]):
        item["id"] = index
    for pattern in (
        permuted["model"]["seeds"][0]["pattern"],
        *permuted["model"]["rules"][0]["forward"]["reactants"],
        *permuted["model"]["rules"][0]["forward"]["products"],
    ):
        pattern["molecules"][0]["type_id"] = 1 - pattern["molecules"][0]["type_id"]
    cases.append(
        dict(
            id="molecule-id-permutation",
            document=permuted,
            oracle="accept",
            expected_semantics=copy.deepcopy(cases[0]["expected_semantics"]),
        )
    )

    # Pending #300 owns compartment support. Until it lands, explicit native
    # refusal remains UNSUPPORTED; acceptance must execute all analytic checks.
    for spelling in ("suffix", "prefix", "molecule"):
        document = copy.deepcopy(baseline)
        model = document["model"]
        model["compartments"] = [dict(id=0, name="cell", dimension=3, volume=2.0)]
        model["seeds"][0]["compartment"] = "cell"
        patterns = [
            model["seeds"][0]["pattern"],
            *model["rules"][0]["forward"]["reactants"],
            *model["rules"][0]["forward"]["products"],
        ]
        for pattern in patterns:
            if spelling == "molecule":
                pattern["molecules"][0].update(compartment="cell", compartment_id=0)
            else:
                pattern.update(
                    compartment="cell", compartment_prefix=spelling == "prefix"
                )
        cases.append(
            dict(
                id=(
                    "molecule-compartment"
                    if spelling == "molecule"
                    else "compartment-" + spelling
                ),
                document=document,
                oracle="accept-or-unsupported",
                expected_semantics=dict(
                    seed={"A()@cell": 100.0, "B()@cell": 0.0},
                    rhs={"A()@cell": -10.0, "B()@cell": 10.0},
                ),
            )
        )

    bonded = copy.deepcopy(baseline)
    bonded["model"]["molecule_types"][0]["components"] = [
        dict(index=0, name="b", states=[])
    ]
    molecule = bonded["model"]["seeds"][0]["pattern"]["molecules"][0]
    molecule["sites"] = [
        dict(
            occurrence=0,
            component="b",
            component_index=0,
            state=dict(kind="any"),
            bond=dict(kind="exact", group=1),
        )
    ]
    second = copy.deepcopy(molecule)
    second["occurrence"] = 1
    bonded["model"]["seeds"][0]["pattern"]["molecules"].append(second)
    cases.append(
        dict(
            id="bonded-complex-boundary",
            document=bonded,
            oracle="unsupported",
            expected_semantics=dict(
                reason="native multi-molecule/site reconstruction unavailable"
            ),
        )
    )

    # Fixed grid and closed-form conversion law declared before execution.
    for case in cases:
        if "seed" in case["expected_semantics"]:
            seed = case["expected_semantics"]["seed"]
            names = list(seed)
            case["expected_semantics"]["trajectory"] = [
                dict(
                    time=t,
                    amounts={
                        names[0]: 100 * math.exp(-0.1 * t),
                        names[1]: 100 * (1 - math.exp(-0.1 * t)),
                    },
                )
                for t in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0)
            ]

    mutations = []
    invalid_parameter = copy.deepcopy(baseline)
    invalid_parameter["model"]["rules"][0]["forward"]["rate"]["expression"] = {
        "kind": "binary",
        "operator": "multiply",
        "arguments": [_number(2.0), _parameter(99)],
    }
    mutations.append(("nested-parameter-reference-out-of-range", invalid_parameter))

    wrong_kind = copy.deepcopy(baseline)
    wrong_kind["model"]["rules"][0]["forward"]["rate"]["expression"]["symbol"] = {
        "kind": "observable",
        "index": 0,
    }
    mutations.append(("parameter-reference-kind-mismatch", wrong_kind))

    bad_type = copy.deepcopy(baseline)
    bad_type["model"]["seeds"][0]["pattern"]["molecules"][0]["type_id"] = 99
    mutations.append(("seed-molecule-type-reference-out-of-range", bad_type))

    bad_identity = copy.deepcopy(baseline)
    bad_identity["model"]["seeds"][0]["pattern"]["molecules"][0]["type"] = "B"
    mutations.append(("seed-type-name-id-disagreement", bad_identity))

    # Seed references were covered, but rule-side reactant/product patterns
    # are separate native import paths. Exercise both paths with the same
    # schema-valid out-of-range and name/id mismatch controls.
    for side in ("reactants", "products"):
        pattern_name = side.removesuffix("s")
        out_of_range = copy.deepcopy(baseline)
        molecule = out_of_range["model"]["rules"][0]["forward"][side][0]["molecules"][0]
        molecule["type_id"] = 99
        mutations.append(
            (f"rule-{pattern_name}-type-reference-out-of-range", out_of_range)
        )

        name_id_mismatch = copy.deepcopy(baseline)
        molecule = name_id_mismatch["model"]["rules"][0]["forward"][side][0][
            "molecules"
        ][0]
        molecule_types = name_id_mismatch["model"]["molecule_types"]
        molecule["type"] = next(
            item["name"] for item in molecule_types if item["id"] != molecule["type_id"]
        )
        mutations.append(
            (f"rule-{pattern_name}-type-name-id-disagreement", name_id_mismatch)
        )

    duplicate_id = copy.deepcopy(baseline)
    duplicate_id["model"]["molecule_types"][1]["id"] = 0
    mutations.append(("duplicate-molecule-type-id", duplicate_id))

    duplicate_name = copy.deepcopy(baseline)
    duplicate_name["model"]["parameters"][1]["name"] = "base"
    mutations.append(("duplicate-parameter-name", duplicate_name))

    bad_compartment = copy.deepcopy(baseline)
    bad_compartment["model"]["compartments"] = [
        {
            "id": 0,
            "name": "cell",
            "dimension": 3,
            "volume": 1.0,
            "parent": "missing",
            "parent_id": 7,
        }
    ]
    bad_compartment["model"]["seeds"][0]["compartment"] = "cell"
    bad_compartment["model"]["seeds"][0]["pattern"]["compartment"] = "cell"
    bad_compartment["model"]["seeds"][0]["pattern"]["molecules"][0][
        "compartment"
    ] = "cell"
    mutations.append(("compartment-parent-reference-out-of-range", bad_compartment))
    unknown = copy.deepcopy(baseline)
    unknown["model"]["seeds"][0]["pattern"]["compartment"] = "missing"
    mutations.append(("unknown-pattern-compartment", unknown))

    cases.extend(
        {
            "id": case_id,
            "document": document,
            "oracle": "refuse",
            "expected_semantics": {
                "reason": "schema-valid structural corruption must be explicitly refused"
            },
        }
        for case_id, document in mutations
    )
    return tuple(cases)


CASES = generated_cases()


def check_ids():
    return [f"{OPERATION}:{case['id']}" for case in CASES]


def _schema_path():
    return (
        Path(__file__).resolve().parents[2] / "provenance/schemas/bngir-0.2.schema.json"
    )


def compare_observation(field, observed, expected, *, atol=1e-12, rtol=1e-12):
    if set(observed) != set(expected):
        return dict(
            field=field + ".species", expected=sorted(expected), actual=sorted(observed)
        )
    for name, value in expected.items():
        actual = observed[name]
        if not math.isfinite(actual) or not math.isclose(
            actual, value, abs_tol=atol, rel_tol=rtol
        ):
            return dict(field=field + "." + name, expected=value, actual=actual)
    return None


def _canonical_species_name(name):
    """Normalize a network species name to a spelling-independent identity.

    A compartmented species is named ``@compartment::Pattern``; the analytic
    control states the compartment as a ``Pattern@compartment`` suffix, so the
    pattern-level, species-level and molecule-level spellings of one
    compartmented species compare equal.
    """
    for separator in ("::", ":"):
        if name.startswith("@") and separator in name:
            head, _, body = name.partition(separator)
            return body + "@" + head[1:]
    return name


def _analytic_observation(model, expected, output=None):
    from bionetgen.model import _cpp

    network = model.generate_network()
    # Prefix/suffix spelling is not structural identity; retain compartment name.
    names = [_canonical_species_name(name) for name in network.species_names]
    result = model.simulate(method="ode", t_end=2.0, n_steps=10, atol=1e-12, rtol=1e-10)
    initial = dict(zip(names, map(float, result.concentrations[0])))
    rhs = _cpp._validation_ode_rhs(
        model._model, network, 0.0, list(result.concentrations[0])
    )
    receipt = dict(
        seed=initial,
        rhs=dict(zip(names, map(float, rhs))),
        trajectory=[
            dict(time=float(t), amounts=dict(zip(names, map(float, values))))
            for t, values in zip(result.time, result.concentrations)
        ],
    )
    if output is not None:
        output.write_text(json.dumps(receipt, indent=2) + "\n")
    for field in ("seed", "rhs"):
        difference = compare_observation(field, receipt[field], expected[field])
        if difference:
            return difference
    if len(receipt["trajectory"]) != len(expected["trajectory"]):
        return dict(
            field="trajectory.rows",
            expected=len(expected["trajectory"]),
            actual=len(receipt["trajectory"]),
        )
    for actual, reference in zip(receipt["trajectory"], expected["trajectory"]):
        if not math.isclose(actual["time"], reference["time"], abs_tol=1e-12):
            return dict(
                field="trajectory.time",
                expected=reference["time"],
                actual=actual["time"],
            )
        difference = compare_observation(
            "trajectory", actual["amounts"], reference["amounts"], atol=1e-7, rtol=1e-7
        )
        if difference:
            return dict(difference, time=reference["time"])
    return None


def evaluate_case(case, *, native_import, wrap_model, output=None):
    """Classify one case; expected refusals remain diagnostic-only evidence."""
    identity = f"{OPERATION}:{case['id']}"
    row = {
        "id": identity,
        "check": case["id"],
        "related_issues": list(ISSUES),
        "supported_execution": case["oracle"] in {"accept", "accept-or-unsupported"},
        "evidence_kind": (
            "native-bngir-semantic-control"
            if case["oracle"] in {"accept", "accept-or-unsupported"}
            else "diagnostic-only"
        ),
        "first_difference": None,
    }
    try:
        restored = wrap_model(native_import(copy.deepcopy(case["document"])))
    except NativeRefusal as exc:
        if case["oracle"] in {"unsupported", "accept-or-unsupported"} and (
            str(exc) == "native BNGIR model.compartments is not supported"
            or str(exc) == "native BNGIR does not support compartments"
            or str(exc) == "native BNGIR pattern requires exactly one molecule"
        ):
            row.update(
                status="UNSUPPORTED",
                detail=str(exc),
                supported_execution=False,
                evidence_kind="unsupported-boundary",
            )
        elif case["oracle"] == "refuse":
            row.update(
                status="PASS",
                detail=f"native import explicitly refused schema-valid corruption: {type(exc).__name__}: {exc}",
                supported_execution=False,
            )
        else:
            row.update(
                status="FAIL",
                detail=f"native import rejected positive control: {type(exc).__name__}: {exc}",
                first_difference={
                    "field": "native_import",
                    "exception": type(exc).__name__,
                    "detail": str(exc),
                },
            )
        return row
    except Exception as exc:
        row.update(
            status="HARNESS_ERROR",
            evidence_kind="harness-error",
            detail=f"native BNGIR outcome unavailable: {type(exc).__name__}: {exc}",
            first_difference={
                "field": "harness",
                "exception": type(exc).__name__,
                "detail": str(exc),
            },
            supported_execution=False,
        )
        return row
    if case["oracle"] in {"refuse", "unsupported"}:
        row.update(
            status="FAIL",
            detail="native import accepted a schema-valid structural corruption",
            first_difference={
                "field": "native_refusal",
                "expected": "explicit refusal",
                "actual": "accepted",
            },
        )
        return row
    difference = _analytic_observation(restored, case["expected_semantics"], output)
    if difference is None:
        row.update(
            status="PASS",
            detail="independently authored BNGIR produced the declared seed, analytic ODE RHS and closed-form trajectory",
        )
    else:
        row.update(
            status="FAIL",
            detail="native BNGIR result differs from independent seed/RHS expectation",
            first_difference=difference,
        )
    return row


def _native_import_without_bngl_fallback(cpp, bngir_module, document):
    """Call the native importer directly; distinguish refusal from adapter failure."""
    original_parser = cpp.parse_string
    original_renderer = bngir_module._as_bngl_v02

    def forbidden(*_args, **_kwargs):
        raise HarnessError(
            "BNGIR adversarial worker attempted BNGL render/parse fallback"
        )

    cpp.parse_string = forbidden
    bngir_module._as_bngl_v02 = forbidden
    try:
        try:
            return cpp._model_from_bngir_v02(document["model"])
        except HarnessError:
            raise
        except RuntimeError as exc:
            # Current native structural refusals identify the BNGIR boundary.
            # Other RuntimeErrors can be adapter/runtime faults and are not a
            # semantic result for this schema-valid generated control.
            if str(exc).startswith("native BNGIR "):
                raise NativeRefusal(str(exc)) from exc
            raise HarnessError(
                f"unexpected native importer RuntimeError: {exc}"
            ) from exc
    finally:
        cpp.parse_string = original_parser
        bngir_module._as_bngl_v02 = original_renderer


def run_worker(directory: Path):
    """Validate and exercise the native import route without parser rendering."""
    import jsonschema
    import bionetgen
    import bionetgen.bngir as bngir_module
    from bionetgen.model import _cpp

    schema = json.loads(_schema_path().read_text(encoding="utf-8"))
    directory.mkdir(parents=True, exist_ok=True)
    rows = []

    def native_import(document):
        return _native_import_without_bngl_fallback(_cpp, bngir_module, document)

    for case in CASES:
        path = directory / f"{case['id']}.bngir.json"
        path.write_text(
            json.dumps(case["document"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            jsonschema.validate(case["document"], schema)
        except Exception as exc:
            rows.append(
                {
                    "id": f"{OPERATION}:{case['id']}",
                    "check": case["id"],
                    "status": "HARNESS_ERROR",
                    "detail": f"generated BNGIR is not schema-valid: {type(exc).__name__}: {exc}",
                    "first_difference": {
                        "field": "schema",
                        "exception": type(exc).__name__,
                    },
                    "related_issues": list(ISSUES),
                    "evidence_kind": "diagnostic-only",
                    "supported_execution": False,
                }
            )
            continue
        try:
            row = evaluate_case(
                case,
                native_import=native_import,
                wrap_model=lambda native_model: bionetgen.BioNetGenModel(native_model),
                output=directory / f"{case['id']}.execution.json",
            )
            row["source_artifact"] = path.name
            row["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append(row)
        except Exception as exc:
            rows.append(
                {
                    "id": f"{OPERATION}:{case['id']}",
                    "check": case["id"],
                    "status": "HARNESS_ERROR",
                    "detail": f"adversarial case harness failed: {type(exc).__name__}: {exc}",
                    "first_difference": {
                        "field": "harness",
                        "exception": type(exc).__name__,
                    },
                    "related_issues": list(ISSUES),
                    "evidence_kind": "diagnostic-only",
                    "supported_execution": False,
                }
            )
    for row in rows:
        if row.get("status") not in STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="invalid status emitted by BNGIR adversarial adapter",
            )
    return rows
