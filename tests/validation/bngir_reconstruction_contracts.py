"""Native BNGIR reconstruction and version-migration contracts (#153, #154).

Two obligations are qualified here:

* ``bngir-reconstruction:source-text-independent-v02`` -- an independently authored
  BNGIR v0.2 document reconstructs the resolved model of a BNGL source without
  rendering or parsing BNGL, and its seed and ODE right-hand side match the
  source semantics.
* ``bngir-version-migration:v01-v02-feature-matrix`` -- migrating a v0.1 document
  to v0.2 either preserves each feature or refuses it explicitly. A feature that
  disappears without a refusal is a silent loss and fails the check.

The expectations are hand-authored, not captured from the implementation: the
analytic seed and right-hand side below are derived from the BNGL source by
hand, and every matrix cell asserts a contract (preserve or refuse) rather than
the current outcome.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .campaign import STATUSES

ISSUES = [153, 154]
OPERATION = "bngir-reconstruction"
CHECKS = (
    "bngir-reconstruction:source-text-independent-v02",
    "bngir-version-migration:v01-v02-feature-matrix",
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
            "required": [],
            "used": ["parameters", "molecule_types", "seeds", "rules"],
        },
        "protocol": {"actions": []},
        "model": {
            "metadata": {
                "name": "independent_reconstruction",
                "version": "2.2",
                "substance_units": "item",
                "options": {},
            },
            "parameters": [
                {"id": 0, "name": "base", "expression": _number(0.05)},
                {
                    "id": 1,
                    "name": "k1",
                    "expression": {
                        "kind": "binary",
                        "operator": "multiply",
                        "arguments": [_number(2.0), _parameter(0)],
                    },
                },
                {
                    "id": 2,
                    "name": "k2",
                    "expression": {
                        "kind": "binary",
                        "operator": "multiply",
                        "arguments": [_number(4.0), _parameter(0)],
                    },
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
            "population_maps": [],
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


# Each cell names a feature of the v0.1 document and how to observe it in the
# migrated v0.2 document. ``present`` receives the migrated model and returns
# True when the feature survived the migration.
def _has_compartments(model):
    return bool(model["compartments"])


def _has_functions(model):
    return bool(model["functions"])


def _has_components(model):
    return any(item["components"] for item in model["molecule_types"])


def _has_rules(model):
    return bool(model["rules"])


def _has_seeds(model):
    return bool(model["seeds"])


def _has_parameters(model):
    return bool(model["parameters"])


def _has_molecule_types(model):
    return bool(model["molecule_types"])


def _has_site_free_molecule_types(model):
    return bool(model["molecule_types"]) and not any(
        item["components"] for item in model["molecule_types"]
    )


MATRIX = (
    {
        "id": "parameters",
        "mutate": lambda document: None,
        "present": _has_parameters,
        "site_free": True,
    },
    {
        "id": "molecule-types",
        "mutate": lambda document: None,
        "present": _has_molecule_types,
        "site_free": True,
    },
    {
        "id": "seeds",
        "mutate": lambda document: None,
        "present": _has_seeds,
        "site_free": True,
    },
    {
        "id": "rules",
        "mutate": lambda document: None,
        "present": _has_rules,
        "site_free": True,
    },
    {
        "id": "molecule-components",
        "mutate": lambda document: None,
        "present": _has_components,
        "site_free": False,
    },
    {
        "id": "site-free-molecule-types",
        "mutate": lambda document: None,
        "present": _has_site_free_molecule_types,
        "site_free": True,
    },
    {
        "id": "compartments",
        "mutate": lambda document: document["model"].__setitem__(
            "compartments",
            [{"name": "cell", "volume": 1.0, "dimension": 3, "parent": ""}],
        ),
        "present": _has_compartments,
        "site_free": True,
    },
    {
        "id": "functions",
        "mutate": lambda document: document["model"].__setitem__(
            "functions", [{"name": "f", "expression": "1.0"}]
        ),
        "present": _has_functions,
        "site_free": True,
    },
    {
        "id": "protocol-actions",
        "mutate": lambda document: document.__setitem__(
            "protocol", {"actions": [{"kind": "add", "target": "A"}]}
        ),
        "present": None,
        "site_free": True,
    },
    {
        "id": "population-types",
        "mutate": lambda document: document["model"].__setitem__(
            "population_types", [{"name": "P"}]
        ),
        "present": None,
        "site_free": True,
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


def _observation(model):
    """Return the resolved seed and ODE right-hand side of a model."""
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
            CHECKS[0],
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
            CHECKS[0],
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
            CHECKS[0],
            "PASS",
            "independently authored v0.2 document reproduces the BNGL source seed and ODE right-hand side",
            artifact,
        )
    return _row(
        CHECKS[0],
        "FAIL",
        "reconstructed seed or right-hand side differs from the BNGL source",
        artifact,
        difference,
    )


def _migration_row(directory):
    import bionetgen

    artifact = directory / "v01-v02-feature-matrix.v01.json"
    artifact.write_text(
        json.dumps(_v01_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    outcomes = []
    for cell in MATRIX:
        document = _v01_document()
        cell["mutate"](document)
        if cell["site_free"]:
            for molecule in document["model"]["molecule_types"]:
                molecule["components"] = []
        record = {"id": cell["id"]}
        try:
            model = bionetgen.from_bngir(document)
        except ValueError as exc:
            record.update(
                outcome="UNSUPPORTED",
                detail=f"v0.1 read refused the feature explicitly: {exc}",
            )
            outcomes.append(record)
            continue
        except Exception as exc:
            record.update(
                outcome="HARNESS_ERROR",
                detail=f"v0.1 read failed unexpectedly: {type(exc).__name__}: {exc}",
            )
            outcomes.append(record)
            continue
        try:
            migrated = json.loads(bionetgen.to_bngir(model, version="0.2"))
        except Exception as exc:
            record.update(
                outcome="UNSUPPORTED",
                detail=f"v0.2 migration refused the feature explicitly: {type(exc).__name__}: {exc}",
            )
            outcomes.append(record)
            continue
        if not cell["present"](migrated["model"]):
            record.update(
                outcome="FAIL",
                detail="the feature was silently dropped during v0.1 to v0.2 migration",
            )
            outcomes.append(record)
            continue
        record["outcome"] = "PRESERVED"
        try:
            bionetgen.from_bngir(migrated, native=True)
        except ValueError as exc:
            record.update(
                outcome="UNSUPPORTED",
                detail=f"native v0.2 import refused the migrated feature explicitly: {exc}",
            )
        except Exception as exc:
            record.update(
                outcome="HARNESS_ERROR",
                detail=f"native v0.2 import failed unexpectedly: {type(exc).__name__}: {exc}",
            )
        else:
            record.update(
                outcome="PASS",
                detail="the feature survived v0.1 to v0.2 migration and imports natively",
            )
        outcomes.append(record)
    receipt = directory / "v01-v02-feature-matrix.outcomes.json"
    receipt.write_text(json.dumps(outcomes, indent=2) + "\n", encoding="utf-8")

    failures = [
        item for item in outcomes if item["outcome"] in {"FAIL", "HARNESS_ERROR"}
    ]
    if failures:
        return _row(
            CHECKS[1],
            (
                "FAIL"
                if any(item["outcome"] == "FAIL" for item in failures)
                else "HARNESS_ERROR"
            ),
            "one or more v0.1 to v0.2 migration cells lost a feature or failed unexpectedly",
            artifact,
            {"field": "matrix", "cells": failures},
        )
    unsupported = [item["id"] for item in outcomes if item["outcome"] == "UNSUPPORTED"]
    executed = [item["id"] for item in outcomes if item["outcome"] == "PASS"]
    detail = "every v0.1 to v0.2 feature cell was preserved or refused explicitly" + (
        f"; explicit unsupported boundaries: {', '.join(unsupported)}"
        if unsupported
        else ""
    )
    if not executed:
        return _row(
            CHECKS[1],
            "UNSUPPORTED",
            "no matrix cell executed; every feature was refused explicitly",
            artifact,
        )
    return _row(CHECKS[1], "PASS", detail, artifact)


def run_worker(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    rows = [_reconstruction_row(directory), _migration_row(directory)]
    for row in rows:
        if row["status"] not in STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="worker produced an unknown status",
                supported_execution=False,
            )
    return rows
