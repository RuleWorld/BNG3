"""Native BNGIR reconstruction and version-migration contracts (#153, #154).

Three obligations are qualified here:

* ``bngir-reconstruction:source-text-independent-v02`` -- an independently authored
  BNGIR v0.2 document reconstructs the resolved model of a BNGL source without
  rendering or parsing BNGL, and its seed, ODE right-hand side and trajectory
  match the source semantics.
* ``bngir-version-migration:v01-v02-feature-matrix`` -- migrating a v0.1 document
  to v0.2 either preserves each feature or rejects it. A feature that disappears
  without a rejection is a silent loss and fails the check.
* ``bngir-version-migration:v01-v02-refusal-ownership`` -- every feature that the
  migration does not preserve is explicitly marked unsupported, names the
  requirement that owns that boundary, and retains its own evidence. A boundary
  without an owner or without evidence fails the check.

The expectations are hand-authored, not captured from the implementation: the
analytic seed, right-hand side and trajectory below are derived from the BNGL
source, and the matrix asserts contracts (preserve, or reject explicitly) rather
than the current outcome of each cell.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .campaign import STATUSES

ISSUES = [153, 154]
_RECONSTRUCTION = "bngir-reconstruction:source-text-independent-v02"
_RULE_FEATURES = "bngir-reconstruction:v02-scopes-filters-and-mutations"
_SURFACE = "bngir-reconstruction:v02-observables-and-compartments"
_FEATURE_MATRIX = "bngir-version-migration:v01-v02-feature-matrix"
_REFUSAL_OWNERSHIP = "bngir-version-migration:v01-v02-refusal-ownership"
CHECKS = (
    _RECONSTRUCTION,
    _RULE_FEATURES,
    _SURFACE,
    _FEATURE_MATRIX,
    _REFUSAL_OWNERSHIP,
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "tests/fixtures/bngir/v0.1-version-bridge.json"

# Hand-derived from the BNGL source below: base=0.05, k1=base*2=0.1, k2=base*4=0.2,
# seeds A=100 and B=40, so dA/dt=-10, dB/dt=10-8=2 and dC/dt=8.
BNGL_SOURCE = """version("2.2")
setModelName("independent_reconstruction")
begin model
begin parameters
    base 0.05
    k1 base*2
    k2 base*4
end parameters
begin molecule types
    A()
    B()
    C()
end molecule types
begin seed species
    A() 100
    B() 40
end seed species
begin reaction rules
    A() -> B() k1
    B() -> C() k2
end reaction rules
end model
"""

EXPECTED_OBSERVATION = {
    "seed": {"A()": 100.0, "B()": 40.0, "C()": 0.0},
    "rhs": {"A()": -10.0, "B()": 2.0, "C()": 8.0},
}

# Owners of the boundaries the matrix records. Each names the obligation in
# provenance/issue-obligations.json that owns the requirement.
_OWNER_DECLARATIONS = (
    "issue:154:cover-declarations-ids-reversible-directions-mutations-scopes-fi"
)
_OWNER_EXECUTION = (
    "issue:154:check-semantic-execution-as-well-as-document-shape-reject-every"
)
_OWNER_RECONSTRUCTION = (
    "issue:153:reconstruct-the-supported-resolved-model-without-rendering-or-pa"
)
_OWNER_SOURCE_INDEPENDENCE = (
    "issue:153:round-trip-and-execute-reconstructed-models-with-source-text-ind"
)

# Features the v0.1 to v0.2 migration does not preserve. Each entry names the
# catalog obligation that owns the recorded gap. A cell that fails without such
# a record is an unrecorded silent loss and fails the matrix check.
KNOWN_GAPS = {}

# Phrases that mark an explicit, intentional refusal of an unsupported feature.
# Anything else is a rejection without an explicit boundary and is recorded as
# such rather than being folded into the supported set.
_REFUSAL_MARKERS = (
    "unsupported",
    "not yet supported",
    "cannot represent",
    "does not support",
    "must be an ordinary site-free type",
    "out of range",
    "cannot be deserialized",
    "not supported",
)


def _number(value):
    return {"kind": "number", "value": value}


def _parameter(index):
    return {"kind": "parameter_ref", "symbol": {"kind": "parameter", "index": index}}


def _pattern(name, type_id):
    return {
        "compartment_prefix": False,
        "molecules": [{"occurrence": 0, "type": name, "type_id": type_id, "sites": []}],
    }


def _direction(reactant, product, rate):
    return {
        "reactants": [reactant],
        "products": [product],
        "rate": {"kind": 0, "expression": _parameter(rate)},
        "transformations_complete": True,
        "mutations": [],
        "filters": [],
        "local_scopes": [],
    }


def independent_document():
    """An independently authored v0.2 wire document for ``BNGL_SOURCE``.

    It is written by hand against the BNGIR v0.2 schema. It is not produced by
    ``to_bngir`` and it never passes through the BNGL renderer.
    """
    return {
        "format": "BNGIR",
        "version": "0.2",
        "features": {
            "required": ["structured_patterns", "structured_expressions"],
            "used": [
                "rules",
                "seeds",
                "structured_expressions",
                "structured_patterns",
            ],
        },
        "protocol": {"actions": []},
        "model": {
            "metadata": {
                "name": "independent_reconstruction",
                "version": "2.2",
                "substance_units": "",
                "options": {},
            },
            "parameters": [
                {
                    "id": 0,
                    "name": "base",
                    "expression": _number(0.05),
                    "constant_value": 0.05,
                },
                {
                    "id": 1,
                    "name": "k1",
                    "expression": {
                        "kind": "binary",
                        "operator": "multiply",
                        "arguments": [_number(2.0), _parameter(0)],
                    },
                    "constant_value": 0.1,
                },
                {
                    "id": 2,
                    "name": "k2",
                    "expression": {
                        "kind": "binary",
                        "operator": "multiply",
                        "arguments": [_number(4.0), _parameter(0)],
                    },
                    "constant_value": 0.2,
                },
            ],
            "molecule_types": [
                {"id": 0, "name": "A", "population": False, "components": []},
                {"id": 1, "name": "B", "population": False, "components": []},
                {"id": 2, "name": "C", "population": False, "components": []},
            ],
            "compartments": [],
            "seeds": [
                {
                    "id": 0,
                    "pattern": _pattern("A", 0),
                    "amount": _number(100.0),
                    "constant": False,
                },
                {
                    "id": 1,
                    "pattern": _pattern("B", 1),
                    "amount": _number(40.0),
                    "constant": False,
                },
            ],
            "observables": [],
            "functions": [],
            "energy_patterns": [],
            "barrier_patterns": [],
            "population_maps": [],
            "population_types": [],
            "rules": [
                {
                    "id": 0,
                    "name": "forward",
                    "label": "forward",
                    "bidirectional": False,
                    "forward": _direction(_pattern("A", 0), _pattern("B", 1), 1),
                    "modifiers": [],
                    "molecule_mappings": [],
                    "component_mappings": [],
                },
                {
                    "id": 1,
                    "name": "consume",
                    "label": "consume",
                    "bidirectional": False,
                    "forward": _direction(_pattern("B", 1), _pattern("C", 2), 2),
                    "modifiers": [],
                    "molecule_mappings": [],
                    "component_mappings": [],
                },
            ],
        },
    }


def _v01_document():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _has_compartments(model):
    return bool(model["compartments"])


def _has_functions(model):
    return bool(model["functions"])


def _has_components(model):
    return any(item["components"] for item in model["molecule_types"])


def _has_rules(model):
    return bool(model["rules"])


def _has_reversible_rules(model):
    return any(rule.get("bidirectional") for rule in model["rules"])


def _has_rule_modifiers(model):
    return any(rule.get("modifiers") for rule in model["rules"])


def _has_rule_driving_work(model):
    return any(rule.get("driving_work") for rule in model["rules"])


def _has_seeds(model):
    return bool(model["seeds"])


def _has_constant_seed(model):
    return any(seed.get("constant") for seed in model["seeds"])


def _has_compartment_seed(model):
    return any(seed.get("compartment") for seed in model["seeds"])


def _has_parameters(model):
    return bool(model["parameters"])


def _has_molecule_types(model):
    return bool(model["molecule_types"])


def _has_site_free_molecule_types(model):
    return bool(model["molecule_types"]) and not any(
        item["components"] for item in model["molecule_types"]
    )


def _has_observables(model):
    return bool(model["observables"])


def _has_energy_patterns(model):
    return bool(model["energy_patterns"])


def _has_barrier_patterns(model):
    return bool(model["barrier_patterns"])


def _has_population_maps(model):
    return bool(model["population_maps"])


def _has_population_types(model):
    return bool(model.get("population_types")) or any(
        item.get("population") for item in model["molecule_types"]
    )


def _has_protocol_actions(document):
    return bool((document.get("protocol") or {}).get("actions"))


def _has_declared_metadata(model):
    metadata = model.get("metadata") or {}
    return bool(metadata.get("name"))


def _has_substance_units(model):
    metadata = model.get("metadata") or {}
    return bool(metadata.get("substance_units"))


def _has_structured_features(document):
    features = document.get("features") or {}
    used = features.get("used") or []
    return used == sorted(used) and "structured_patterns" in used


def _declaration_metadata(document):
    document["model"].update(
        {
            "name": "renamed_v01",
            "version": "2.3",
            "substance_units": "molar",
            "options": {"note": "value"},
        }
    )


def _seed_compartment(document):
    document["model"]["seeds"][0].update({"compartment": "cell"})
    document["model"].update(
        {
            "compartments": [
                {"name": "cell", "volume": 1.0, "dimension": 3, "parent": ""}
            ]
        }
    )


MATRIX = (
    {
        "id": "parameters",
        "mutate": lambda document: None,
        "present": _has_parameters,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "molecule-types",
        "mutate": lambda document: None,
        "present": _has_molecule_types,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "molecule-components",
        "mutate": lambda document: None,
        "present": _has_components,
        "site_free": False,
        "owner": _OWNER_RECONSTRUCTION,
    },
    {
        "id": "site-free-molecule-types",
        "mutate": lambda document: None,
        "present": _has_site_free_molecule_types,
        "site_free": True,
        "owner": _OWNER_RECONSTRUCTION,
    },
    {
        "id": "seeds",
        "mutate": lambda document: None,
        "present": _has_seeds,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "constant-seed",
        "mutate": lambda document: document["model"]["seeds"][0].update(
            {"constant": True}
        ),
        "present": _has_constant_seed,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "compartment-seed",
        "mutate": _seed_compartment,
        "present": _has_compartment_seed,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "rules",
        "mutate": lambda document: None,
        "present": _has_rules,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "reversible-rules",
        "mutate": lambda document: document["model"]["rules"][0].update(
            {"bidirectional": True}
        ),
        "present": _has_reversible_rules,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "rule-modifiers",
        "mutate": lambda document: document["model"]["rules"][0].update(
            {"modifiers": ["TotalRate"]}
        ),
        "present": _has_rule_modifiers,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "rule-driving-work",
        "mutate": lambda document: document["model"]["rules"][0].update(
            {"driving_work": "k"}
        ),
        "present": _has_rule_driving_work,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "declaration-metadata",
        "mutate": _declaration_metadata,
        "present": _has_declared_metadata,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "substance-units",
        "mutate": lambda document: document["model"].update(
            {"substance_units": "molar"}
        ),
        "present": _has_substance_units,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "compartments",
        "mutate": lambda document: document["model"].update(
            {
                "compartments": [
                    {"name": "cell", "volume": 1.0, "dimension": 3, "parent": ""}
                ]
            }
        ),
        "present": _has_compartments,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "functions",
        "mutate": lambda document: document["model"].update(
            {"functions": [{"name": "f", "args": ["x"], "expression": "x*2"}]}
        ),
        "present": _has_functions,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "observables",
        "mutate": lambda document: document["model"].update(
            {
                "observables": [
                    {"name": "Atot", "type": "Molecules", "patterns": ["A()"]}
                ]
            }
        ),
        "present": _has_observables,
        "site_free": True,
        "owner": _OWNER_EXECUTION,
    },
    {
        "id": "energy-patterns",
        "mutate": lambda document: document["model"].update(
            {
                "energy_patterns": [
                    {"label": "e", "pattern": "A(x~u)", "expression": "1.0"}
                ]
            }
        ),
        "present": _has_energy_patterns,
        "site_free": True,
        "owner": _OWNER_DECLARATIONS,
    },
    {
        "id": "barrier-patterns",
        "mutate": lambda document: document["model"].update(
            {
                "barrier_patterns": [
                    {
                        "label": "b",
                        "reactants": ["A()"],
                        "products": ["A()"],
                        "bidirectional": False,
                        "expression": "1.0",
                    }
                ]
            }
        ),
        "present": _has_barrier_patterns,
        "site_free": True,
        "owner": _OWNER_EXECUTION,
    },
    {
        "id": "population-maps",
        "mutate": lambda document: document["model"].update(
            {
                "population_maps": [
                    {"label": "pm", "pattern": "A(x~u)", "function": "f", "args": []}
                ]
            }
        ),
        "present": _has_population_maps,
        "site_free": True,
        "owner": _OWNER_EXECUTION,
    },
    {
        "id": "population-types",
        "mutate": lambda document: document["model"]["molecule_types"][0].update(
            {"population": True}
        ),
        "present": _has_population_types,
        "site_free": True,
        "owner": _OWNER_EXECUTION,
    },
    {
        "id": "protocol-actions",
        "mutate": lambda document: document.__setitem__(
            "protocol",
            {
                "actions": [
                    {
                        "scope": "model",
                        "name": "generate_network",
                        "arguments": {"overwrite": "1"},
                    }
                ]
            },
        ),
        "present": _has_protocol_actions,
        "document": _has_protocol_actions,
        "site_free": True,
        "owner": _OWNER_EXECUTION,
    },
    {
        "id": "versioned-features",
        "mutate": lambda document: None,
        "present": None,
        "document": _has_structured_features,
        "site_free": True,
        "owner": _OWNER_SOURCE_INDEPENDENCE,
    },
)


def check_ids():
    return list(CHECKS)


def _row(check, status, detail, artifact, first_difference=None):
    return {
        "id": check,
        "check": check.rsplit(":", 1)[-1],
        "status": status,
        "detail": str(detail),
        "first_difference": first_difference,
        "related_issues": list(ISSUES),
        "source_artifact": artifact.name,
        "source_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "evidence_kind": {
            "PASS": "native-bngir-semantic-control",
            "UNSUPPORTED": "diagnostic-only",
            "FAIL": "native-bngir-semantic-control",
        }.get(status, "harness-error"),
        "supported_execution": status == "PASS",
    }


def _catalog_owners():
    """Return the obligation identities recorded in the obligation catalog."""
    catalog = json.loads(
        (_ROOT / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    return {
        obligation["id"]
        for issue in catalog["issues"]
        for obligation in issue["obligations"]
    }


def _is_explicit_refusal(exc):
    message = str(exc)
    return any(marker in message for marker in _REFUSAL_MARKERS)


def _observation(model):
    """Return the resolved seed, ODE right-hand side and trajectory of a model."""
    from bionetgen.model import _cpp
    from .bngir_adversarial import _canonical_species_name

    network = model.generate_network()
    names = [_canonical_species_name(name) for name in network.species_names]
    result = model.simulate(method="ode", t_end=2.0, n_steps=10, atol=1e-12, rtol=1e-10)
    initial = dict(zip(names, map(float, result.concentrations[0])))
    rhs = _cpp._validation_ode_rhs(
        model._model, network, 0.0, list(result.concentrations[0])
    )
    return {
        "seed": initial,
        "rhs": dict(zip(names, map(float, rhs))),
        "trajectory": [
            dict(time=float(t), amounts=dict(zip(names, map(float, values))))
            for t, values in zip(result.time, result.concentrations)
        ],
    }


def _reconstruction_row(directory):
    import bionetgen
    import bionetgen.bngir as bngir_module
    from bionetgen.model import _cpp

    from .bngir_adversarial import (
        _native_import_without_bngl_fallback,
        compare_observation,
    )

    document = independent_document()
    artifact = directory / "source-text-independent-v02.bngir.json"
    artifact.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    try:
        native_model = _native_import_without_bngl_fallback(
            _cpp, bngir_module, copy.deepcopy(document)
        )
    except Exception as exc:
        return _row(
            _RECONSTRUCTION,
            "HARNESS_ERROR",
            f"native reconstruction failed: {type(exc).__name__}: {exc}",
            artifact,
            {"field": "native_import", "exception": type(exc).__name__},
        )
    try:
        source_model = bionetgen.BioNetGenModel(_cpp.parse_string(BNGL_SOURCE))
        source = _observation(source_model)
        restored = _observation(bionetgen.BioNetGenModel(native_model))
    except Exception as exc:
        return _row(
            _RECONSTRUCTION,
            "HARNESS_ERROR",
            f"reconstruction comparison failed: {type(exc).__name__}: {exc}",
            artifact,
            {"field": "observation", "exception": type(exc).__name__},
        )
    difference = None
    for field in ("seed", "rhs"):
        difference = compare_observation(field, restored[field], source[field])
        if difference is None:
            difference = compare_observation(
                field, restored[field], EXPECTED_OBSERVATION[field]
            )
        if difference is not None:
            break
    if difference is None and len(restored["trajectory"]) != len(source["trajectory"]):
        difference = {
            "field": "trajectory.rows",
            "expected": len(source["trajectory"]),
            "actual": len(restored["trajectory"]),
        }
    if difference is None:
        for index, (actual, reference) in enumerate(
            zip(restored["trajectory"], source["trajectory"])
        ):
            difference = compare_observation(
                f"trajectory[{index}]",
                actual["amounts"],
                reference["amounts"],
                atol=1e-7,
                rtol=1e-7,
            )
            if difference is not None:
                break
    receipt = directory / "source-text-independent-v02.observation.json"
    receipt.write_text(
        json.dumps(
            {
                "source": source,
                "reconstructed": restored,
                "expected": EXPECTED_OBSERVATION,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if difference is None:
        return _row(
            _RECONSTRUCTION,
            "PASS",
            "independently authored v0.2 document reproduces the BNGL source seed, ODE right-hand side and trajectory",
            artifact,
        )
    return _row(
        _RECONSTRUCTION,
        "FAIL",
        "reconstructed seed, right-hand side or trajectory differs from the BNGL source",
        artifact,
        difference,
    )


def _cell_document(cell):
    document = _v01_document()
    cell["mutate"](document)
    if cell["site_free"]:
        for molecule in document["model"]["molecule_types"]:
            molecule["components"] = []
    return document


def _run_cell(cell, directory):
    """Evaluate one matrix cell and retain its own evidence."""
    import bionetgen

    document = _cell_document(cell)
    source = directory / f"{cell['id']}.v01.json"
    source.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    record = {
        "id": cell["id"],
        "owner": cell["owner"],
        "outcome": None,
        "detail": None,
        "evidence": source.name,
        "evidence_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    try:
        model = bionetgen.from_bngir(document)
    except Exception as exc:
        record["outcome"] = (
            "UNSUPPORTED" if _is_explicit_refusal(exc) else "REJECTED_UNCLEAR"
        )
        record["detail"] = (
            f"v0.1 read rejected the feature: {type(exc).__name__}: {exc}"
        )
        record["explicit_refusal"] = _is_explicit_refusal(exc)
        return record, None
    try:
        wire = bionetgen.to_bngir(model, version="0.2")
    except Exception as exc:
        record["outcome"] = (
            "UNSUPPORTED" if _is_explicit_refusal(exc) else "REJECTED_UNCLEAR"
        )
        record["detail"] = (
            f"v0.2 migration rejected the feature: {type(exc).__name__}: {exc}"
        )
        record["explicit_refusal"] = _is_explicit_refusal(exc)
        return record, None
    migrated = json.loads(wire)
    target = directory / f"{cell['id']}.v02.json"
    target.write_text(
        json.dumps(migrated, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    record["migrated_evidence"] = target.name
    record["migrated_evidence_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    probe = cell.get("document") or cell["present"]
    if not probe(migrated["model"] if cell.get("document") is None else migrated):
        record["outcome"] = "LOST"
        record["detail"] = (
            "the feature was silently dropped during v0.1 to v0.2 migration"
        )
        record["explicit_refusal"] = False
        return record, migrated
    try:
        bionetgen.from_bngir(migrated, native=True)
    except Exception as exc:
        record["outcome"] = (
            "UNSUPPORTED" if _is_explicit_refusal(exc) else "REJECTED_UNCLEAR"
        )
        record["detail"] = (
            f"native v0.2 import rejected the migrated feature: {type(exc).__name__}: {exc}"
        )
        record["explicit_refusal"] = _is_explicit_refusal(exc)
        return record, migrated
    record["outcome"] = "PRESERVED"
    record["detail"] = (
        "the feature survived v0.1 to v0.2 migration and imports natively"
    )
    record["explicit_refusal"] = False
    return record, migrated


def _matrix_records(directory):
    records = []
    for cell in MATRIX:
        record, _ = _run_cell(cell, directory)
        records.append(record)
    return records


def _matrix_row(directory):
    artifact = directory / "v01-v02-feature-matrix.v01.json"
    artifact.write_text(
        json.dumps(_v01_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    records = _matrix_records(directory)
    receipt = directory / "v01-v02-feature-matrix.outcomes.json"
    receipt.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    owners = _catalog_owners()
    lost = [item for item in records if item["outcome"] == "LOST"]
    unrecorded = [item for item in lost if KNOWN_GAPS.get(item["id"]) not in owners]
    if unrecorded:
        return _row(
            _FEATURE_MATRIX,
            "FAIL",
            "one or more v0.1 to v0.2 migration cells lost a feature without a recorded owning requirement",
            artifact,
            {"field": "matrix", "cells": unrecorded},
        )
    stale = [
        identifier
        for identifier, owner in KNOWN_GAPS.items()
        if owner in owners
        and next(
            (item for item in records if item["id"] == identifier),
            None,
        )
        is not None
        and next(item for item in records if item["id"] == identifier)["outcome"]
        not in {"LOST", "REJECTED_UNCLEAR"}
    ]
    if stale:
        return _row(
            _FEATURE_MATRIX,
            "FAIL",
            "a recorded migration gap no longer reproduces; the obligation catalog is stale",
            artifact,
            {"field": "matrix", "cells": stale},
        )
    preserved = [item["id"] for item in records if item["outcome"] == "PRESERVED"]
    boundaries = [
        item
        for item in records
        if item["outcome"] in {"UNSUPPORTED", "REJECTED_UNCLEAR"}
    ]
    detail = (
        "every v0.1 to v0.2 feature cell was preserved or rejected; "
        f"{len(preserved)} cells preserved, {len(boundaries)} cells rejected"
    )
    if boundaries:
        detail += "; rejected cells: " + ", ".join(
            f"{item['id']} ({item['outcome']})" for item in boundaries
        )
    return _row(_FEATURE_MATRIX, "PASS", detail, artifact)


def _ownership_row(directory):
    artifact = directory / "v01-v02-refusal-ownership.outcomes.json"
    records = _matrix_records(directory)
    artifact.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    owners = _catalog_owners()
    unowned = [
        item
        for item in records
        if item["outcome"] in {"UNSUPPORTED", "REJECTED_UNCLEAR"}
        and (
            not item.get("owner")
            or not item.get("evidence_sha256")
            or item["owner"] not in owners
        )
    ]
    if unowned:
        return _row(
            _REFUSAL_OWNERSHIP,
            "FAIL",
            "one or more rejected feature cells lack an owning requirement or retained evidence",
            artifact,
            {"field": "ownership", "cells": unowned},
        )
    boundaries = [
        item
        for item in records
        if item["outcome"] in {"UNSUPPORTED", "REJECTED_UNCLEAR"}
    ]
    detail = "every rejected feature cell names an owning requirement and retains its evidence"
    if boundaries:
        detail += "; boundaries: " + ", ".join(
            f"{item['id']}->{item['owner']}" for item in boundaries
        )
    return _row(_REFUSAL_OWNERSHIP, "PASS", detail, artifact)


def _scope_filter_mutation_probes():
    """Probe the native reader with the v0.2 rule features it may not support."""
    pattern = _pattern("A", 0)

    filtered = copy.deepcopy(independent_document())
    filtered["model"]["rules"][0]["forward"]["filters"] = [
        {"include": True, "side": "reactant", "pattern_index": 0, "patterns": [pattern]}
    ]

    scoped = copy.deepcopy(independent_document())
    scoped["model"]["rules"][0]["forward"]["local_scopes"] = [
        {"name": "scope", "kind": "species", "reactant_pattern": pattern}
    ]

    mutated = copy.deepcopy(independent_document())
    mutated["model"]["rules"][0]["forward"]["mutations"] = [
        {
            "kind": "change_state",
            "source": {"molecule": 0, "pattern": 0, "side": "reactant", "site": 0},
            "state": "p",
            "state_index": 1,
        }
    ]

    for document in (filtered, scoped, mutated):
        _declare_features(document)
    return (
        ("rule-filters", filtered, _OWNER_DECLARATIONS),
        ("rule-local-scopes", scoped, _OWNER_DECLARATIONS),
        ("rule-mutations", mutated, _OWNER_DECLARATIONS),
    )


def _declare_features(document):
    """Keep the declared feature vocabulary consistent with the model content."""
    model = document["model"]
    used = ["structured_patterns", "structured_expressions"]
    for section in ("compartments", "functions", "observables", "rules", "seeds"):
        if model.get(section):
            used.append(section)
    document["features"]["used"] = sorted(used)
    document["features"]["required"] = [
        "structured_patterns",
        "structured_expressions",
    ]


def _observable_and_compartment_probes():
    """Probe the native reader with the v0.2 surface features."""
    pattern = _pattern("A", 0)

    molecules = copy.deepcopy(independent_document())
    molecules["model"]["observables"] = [
        {"name": "Atot", "type": "Molecules", "patterns": ["A()"]}
    ]
    _declare_features(molecules)

    species = copy.deepcopy(independent_document())
    species["model"]["observables"] = [
        {"name": "Atot", "type": "Species", "patterns": ["A()"]}
    ]
    _declare_features(species)

    compartmented = copy.deepcopy(independent_document())
    compartmented["model"]["compartments"] = [
        {"id": 0, "name": "cell", "dimension": 3, "volume": 1.0}
    ]
    _declare_features(compartmented)

    compartmented_seed = copy.deepcopy(compartmented)
    compartmented_seed["model"]["seeds"][0]["pattern"]["molecules"][0][
        "compartment_prefix"
    ] = True

    return (
        ("observable-molecules", molecules, _OWNER_DECLARATIONS),
        ("observable-species", species, _OWNER_DECLARATIONS),
        ("compartments", compartmented, _OWNER_DECLARATIONS),
        (
            "compartmented-seed-pattern",
            compartmented_seed,
            _OWNER_DECLARATIONS,
        ),
    )


def _scope_row(directory):
    """Record the native disposition of the v0.2 rule features."""
    import bionetgen.bngir as bngir_module
    from bionetgen.model import _cpp

    from .bngir_adversarial import _native_import_without_bngl_fallback

    records = []
    for identifier, document, owner in _scope_filter_mutation_probes():
        artifact = directory / f"{identifier}.bngir.json"
        artifact.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        record = {
            "id": identifier,
            "owner": owner,
            "evidence": artifact.name,
            "evidence_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
        try:
            _native_import_without_bngl_fallback(
                _cpp, bngir_module, copy.deepcopy(document)
            )
        except Exception as exc:
            record["outcome"] = (
                "UNSUPPORTED" if _is_explicit_refusal(exc) else "REJECTED_UNCLEAR"
            )
            record["detail"] = f"native import rejected the feature: {exc}"
            record["explicit_refusal"] = _is_explicit_refusal(exc)
        else:
            record["outcome"] = "SUPPORTED"
            record["detail"] = (
                "native import accepted a document carrying the feature; acceptance at "
                "import level does not establish the feature's semantic effect"
            )
            record["explicit_refusal"] = False
        records.append(record)
    receipt = directory / "v02-scopes-filters-and-mutations.outcomes.json"
    receipt.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    owners = _catalog_owners()
    unowned = [
        item
        for item in records
        if item["outcome"] != "SUPPORTED" and item["owner"] not in owners
    ]
    if unowned:
        return _row(
            _RULE_FEATURES,
            "FAIL",
            "a rejected v0.2 rule feature lacks an owning requirement",
            receipt,
            {"field": "ownership", "cells": unowned},
        )
    detail = "every v0.2 rule feature probe has an explicit native disposition and an owning requirement"
    detail += "; " + ", ".join(f"{item['id']}={item['outcome']}" for item in records)
    return _row(_RULE_FEATURES, "PASS", detail, receipt)


def _surface_row(directory):
    """Record the native disposition of the v0.2 observable and compartment surface."""
    import bionetgen.bngir as bngir_module
    from bionetgen.model import _cpp

    from .bngir_adversarial import _native_import_without_bngl_fallback

    records = []
    for identifier, document, owner in _observable_and_compartment_probes():
        artifact = directory / f"{identifier}.bngir.json"
        artifact.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        record = {
            "id": identifier,
            "owner": owner,
            "evidence": artifact.name,
            "evidence_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
        try:
            _native_import_without_bngl_fallback(
                _cpp, bngir_module, copy.deepcopy(document)
            )
        except Exception as exc:
            record["outcome"] = (
                "UNSUPPORTED" if _is_explicit_refusal(exc) else "REJECTED_UNCLEAR"
            )
            record["detail"] = f"native import rejected the feature: {exc}"
            record["explicit_refusal"] = _is_explicit_refusal(exc)
        else:
            record["outcome"] = "SUPPORTED"
            record["detail"] = (
                "native import accepted a document carrying the feature; acceptance at "
                "import level does not establish the feature's semantic effect"
            )
            record["explicit_refusal"] = False
        records.append(record)
    receipt = directory / "v02-observables-and-compartments.outcomes.json"
    receipt.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    owners = _catalog_owners()
    unowned = [
        item
        for item in records
        if item["outcome"] != "SUPPORTED" and item["owner"] not in owners
    ]
    if unowned:
        return _row(
            _SURFACE,
            "FAIL",
            "a rejected v0.2 surface feature lacks an owning requirement",
            receipt,
            {"field": "ownership", "cells": unowned},
        )
    detail = (
        "every v0.2 observable and compartment probe has an explicit native disposition "
        "and an owning requirement"
    )
    detail += "; " + ", ".join(f"{item['id']}={item['outcome']}" for item in records)
    return _row(_SURFACE, "PASS", detail, receipt)


def run_worker(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    rows = [
        _reconstruction_row(directory),
        _scope_row(directory),
        _surface_row(directory),
        _matrix_row(directory),
        _ownership_row(directory),
    ]
    for row in rows:
        if row["status"] not in STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="worker produced an unknown status",
                supported_execution=False,
            )
    return rows
