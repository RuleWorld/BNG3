"""Independent BNGIR export, determinism, and equality contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .campaign import STATUSES

ISSUES = [155, 156]
CHECKS = (
    "bngir-export:v02-independent-roundtrip",
    "bngir-export:v02-site-bearing-unsupported",
    "bngir-export:canonical-bytes-determinism",
    "bngir-equality:v01-v02-identity-provenance",
    "bngir-equality:approved-default-v01-explicit-v02",
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = {
    "v0.1-version-bridge.json": "v01-version-bridge.json",
    "v0.2-version-bridge.json": "v02-version-bridge.json",
    "v0.2-site-free-version-bridge.json": "v02-site-free-version-bridge.json",
}


def check_ids():
    return list(CHECKS)


def _fixture(name):
    """Load a hand-reviewed fixture, independent of the writer under test."""
    return json.loads(
        (_ROOT / "tests/fixtures/bngir" / name).read_text(encoding="utf-8")
    )


def _retain(directory, name):
    """Copy a fixture into the artifact directory and describe it."""
    source = _ROOT / "tests/fixtures/bngir" / name
    target = directory / _FIXTURES[name]
    target.write_bytes(source.read_bytes())
    return target


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


def _native_roundtrip(directory, artifact, document, check):
    import bionetgen

    try:
        restored = bionetgen.from_bngir(document, native=True)
        observed = json.loads(bionetgen.to_bngir(restored, version="0.2"))
    except (NotImplementedError, RuntimeError) as exc:
        return _row(
            check,
            "UNSUPPORTED",
            f"native v0.2 import/export unavailable: {type(exc).__name__}: {exc}",
            artifact,
            {"field": "native-export", "exception": type(exc).__name__},
        )
    except ValueError as exc:
        if "ordinary site-free type" in str(exc):
            return _row(
                check,
                "UNSUPPORTED",
                f"native reader explicitly refuses this fixture's site-bearing molecule type: {exc}",
                artifact,
                {"field": "native-export", "exception": type(exc).__name__},
            )
        return _row(
            check,
            "HARNESS_ERROR",
            f"native import/export failed unexpectedly: {type(exc).__name__}: {exc}",
            artifact,
            {"field": "native-export", "exception": type(exc).__name__},
        )
    except Exception as exc:
        return _row(
            check,
            "HARNESS_ERROR",
            f"native import/export could not be evaluated: {type(exc).__name__}: {exc}",
            artifact,
            {"field": "native-export", "exception": type(exc).__name__},
        )
    if observed == document:
        return _row(
            check,
            "PASS",
            "native import/export reproduces the frozen hand-reviewed v0.2 document",
            artifact,
        )
    return _row(
        check,
        "FAIL",
        "native export differs from the frozen v0.2 document",
        artifact,
        {"field": "document", "expected": document, "actual": observed},
    )


def run_worker(directory: Path):
    import bionetgen

    directory.mkdir(parents=True, exist_ok=True)
    site_free_artifact = _retain(directory, "v0.2-site-free-version-bridge.json")
    site_bearing_artifact = _retain(directory, "v0.2-version-bridge.json")
    legacy_artifact = _retain(directory, "v0.1-version-bridge.json")

    rows = [
        _native_roundtrip(
            directory,
            site_free_artifact,
            _fixture("v0.2-site-free-version-bridge.json"),
            CHECKS[0],
        ),
        _native_roundtrip(
            directory,
            site_bearing_artifact,
            _fixture("v0.2-version-bridge.json"),
            CHECKS[1],
        ),
    ]

    try:
        fixture = _fixture("v0.2-version-bridge.json")
        legacy = _fixture("v0.1-version-bridge.json")
        model = bionetgen.from_bngir(legacy)
        expected_wire = json.dumps(
            fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        first = bionetgen.to_bngir(model, version="0.2")
        second = bionetgen.to_bngir(model, version="0.2")
        ok = first == second == expected_wire
        rows.append(
            _row(
                CHECKS[2],
                "PASS" if ok else "FAIL",
                (
                    "repeated serialization is byte-identical to the frozen canonical v0.2 wire fixture"
                    if ok
                    else "serialization differs from repeatability or frozen canonical bytes"
                ),
                legacy_artifact,
                None if ok else {"field": "serialized-bytes"},
            )
        )
        restored = bionetgen.from_bngir(first)
        changed = json.loads(first)
        changed["model"]["metadata"]["name"] = "different_identity"
        renamed = bionetgen.from_bngir(changed)
        equal_roundtrip = bionetgen.semantic_equal(model, restored, version="0.2")
        unequal_identity = not bionetgen.semantic_equal(model, renamed, version="0.2")
        ok = equal_roundtrip and unequal_identity
        detail = "formatting-insensitive round-trip equality preserves serialized identity; provenance is outside semantic_equal's model API"
        rows.append(
            _row(
                CHECKS[3],
                "PASS" if ok else "FAIL",
                (
                    detail
                    if ok
                    else "round-trip equality or identity sensitivity violated"
                ),
                legacy_artifact,
                (
                    None
                    if ok
                    else {
                        "field": "semantic_equal",
                        "equal_roundtrip": equal_roundtrip,
                        "unequal_identity": unequal_identity,
                    }
                ),
            )
        )
        default_wire = bionetgen.to_bngir(model)
        v01_wire = bionetgen.to_bngir(model, version="0.1")
        v02_wire = bionetgen.to_bngir(model, version="0.2")
        try:
            bionetgen.to_bngir(model, version="future")
            invalid_refused = False
        except ValueError:
            invalid_refused = True
        ok = (
            json.loads(default_wire)["version"] == "0.1"
            and default_wire == v01_wire
            and json.loads(v02_wire)["version"] == "0.2"
            and invalid_refused
        )
        rows.append(
            _row(
                CHECKS[4],
                "PASS" if ok else "FAIL",
                (
                    "approved contract: v0.1 default, explicit v0.2 opt-in, unknown versions refused"
                    if ok
                    else "version default/opt-in/refusal contract differs"
                ),
                legacy_artifact,
                None if ok else {"field": "version-policy"},
            )
        )
    except Exception as exc:
        for check in CHECKS[2:]:
            rows.append(
                _row(
                    check,
                    "HARNESS_ERROR",
                    f"serialization/equality could not be evaluated: {type(exc).__name__}: {exc}",
                    legacy_artifact,
                    {"field": check, "exception": type(exc).__name__},
                )
            )

    for row in rows:
        if row["status"] not in STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="worker produced an unknown status",
                supported_execution=False,
            )
    return rows
