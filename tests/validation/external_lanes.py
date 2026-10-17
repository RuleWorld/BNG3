"""Adapters for existing SBML and benchmark reports; no shared PASS inference."""

from __future__ import annotations

import json
import sys

from .campaign import run_command

STATUS = {
    "passed": "PASS",
    "failed": "FAIL",
    "unsupported": "UNSUPPORTED",
    "unsupported_format": "UNSUPPORTED",
    "timeout": "TIMEOUT",
    "timed-out": "TIMEOUT",
    "timed_out": "TIMEOUT",
    "invalid_source": "INVALID_INPUT",
    "invalid-source": "INVALID_INPUT",
    "not_run": "NOT_TESTED",
    "not-run": "NOT_TESTED",
    "not_tested": "NOT_TESTED",
    "pending": "NOT_TESTED",
    "missing": "NOT_TESTED",
}


def _status(value, *, missing="NOT_TESTED"):
    if value is None:
        return missing
    return STATUS.get(str(value).strip().lower(), "HARNESS_ERROR")


def _detail(value):
    return str(value.get("reason", value.get("error", "")))


def _bool_stage(value, key="passed", *, skipped=False, source=False):
    if not isinstance(value, dict):
        return "HARNESS_ERROR"
    if key in value and type(value[key]) is not bool:
        return "HARNESS_ERROR"
    if "skipped" in value and type(value["skipped"]) is not bool:
        return "HARNESS_ERROR"
    explicit = value.get(key)
    status = _status(value.get("status"))
    if skipped and value.get("skipped") is True:
        return "HARNESS_ERROR" if explicit is True or status == "PASS" else "NOT_TESTED"
    if explicit is not None:
        if "status" in value and (
            (explicit and status != "PASS") or (not explicit and status == "PASS")
        ):
            return "HARNESS_ERROR"
        if explicit:
            return "PASS"
        return status if "status" in value else "INVALID_INPUT" if source else "FAIL"
    return status


def _row(identity, stage, status, detail, capability, question, reference):
    return dict(
        id=identity,
        stage=stage,
        status=status,
        detail=detail,
        capabilities=[capability],
        question=question,
        reference=reference,
    )


def _stage_status(record, key, kind):
    if key not in record:
        return "HARNESS_ERROR" if kind == "official" else "NOT_TESTED"
    value = record[key]
    if kind == "boolean":
        return (
            "PASS" if value is True else "FAIL" if value is False else "HARNESS_ERROR"
        )
    if not isinstance(value, dict):
        return "HARNESS_ERROR"
    if kind == "network":
        return (
            "PASS"
            if all(
                type(value.get(k)) is int and value[k] >= 0
                for k in ("species", "reactions")
            )
            else "HARNESS_ERROR"
        )
    if kind == "official":
        return _status(value.get("status"), missing="HARNESS_ERROR")
    return _bool_stage(
        value,
        key="success" if kind == "native" else "passed",
        skipped=kind == "comparison",
        source=kind == "source",
    )


def _stage_rows(prefix, record, stages):
    rows = []
    for key, stage, kind, capability, question, reference in stages:
        value = record.get(key)
        detail = (
            _detail(value) if isinstance(value, dict) else str(record.get("error", ""))
        )
        rows.append(
            _row(
                prefix + ":" + stage,
                stage,
                _stage_status(record, key, kind),
                detail
                or (f"{key} evidence" if key in record else f"no {key} evidence"),
                capability,
                question,
                reference,
            )
        )
    return rows


CONVERSION = (
    "generated_network",
    "conversion",
    "network",
    "atomizer.core-lowering",
    "SBML-to-BNGL-network-conversion",
    "conversion",
)
COMPARISON = (
    "simulation_comparison",
    "cross-engine-simulation",
    "comparison",
    "simulation.ode",
    "independent-numerical-agreement",
    "libroadrunner-exported-sbml",
)
SOURCE_XML = (
    "source_xml",
    "source-validation",
    "source",
    "sbml.native-import",
    "source-document-validity",
    "libsbml",
)


def _record_status_fallback(rows, prefix, record):
    status = _status(record.get("status"))
    if status in {"PASS", "NOT_TESTED"}:
        return
    if any(
        row["status"] == status and row["id"].startswith(prefix + ":") for row in rows
    ):
        return
    rows.append(
        _row(
            prefix + ":record-outcome",
            "record-outcome",
            status,
            str(
                record.get("error")
                or record.get("unsupported_reason")
                or f"record status: {record.get('status')}"
            ),
            "sbml.native-import",
            "external-report-record-outcome",
            "external-report",
        )
    )


def _records(document, label):
    if not isinstance(document, dict) or not isinstance(document.get("records"), list):
        raise ValueError(f"{label} report must contain a records array")
    records = document["records"]
    identities = []
    for record in records:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("id"), str)
            or not record["id"]
        ):
            raise ValueError(f"{label} records require string identities")
        identities.append((record.get("category"), record["id"]))
    if len(set(identities)) != len(identities):
        raise ValueError(f"duplicate {label} record identities")
    return records


def sbml_results(document):
    rows = []
    for record in _records(document, "SSTS"):
        if record.get("category") not in {"semantic", "stochastic"}:
            raise ValueError("SSTS records require semantic or stochastic category")
        prefix = f"ssts:{record['category']}:{record['id']}"
        stages = [
            CONVERSION,
            (
                "official_conformance",
                "official-conformance",
                "official",
                "sbml.native-import",
                "official-reference-conformance",
                "sbml-test-suite",
            ),
            (
                "roundtrip_passed",
                "roundtrip-structure",
                "boolean",
                "atomizer.core-lowering",
                "SBML-roundtrip-structure",
                "roundtrip",
            ),
            COMPARISON,
        ]
        if "source_xml" in record:
            stages.insert(0, SOURCE_XML)
        rows.extend(_stage_rows(prefix, record, stages))
        _record_status_fallback(rows, prefix, record)
    return rows


def biomodel_results(document):
    rows = []
    for record in _records(document, "published BioModels"):
        identity = f"biomodel:{record['id']}"
        modes = record.get("modes")
        if modes is None or modes == []:
            status = _status(record.get("status"))
            # A record-level success without modes cannot qualify any stage.
            rows.append(
                _row(
                    identity + ":record-outcome",
                    "record-outcome",
                    "HARNESS_ERROR" if status == "PASS" else status,
                    str(
                        record.get("unsupported_reason")
                        or record.get("error")
                        or "no mode execution evidence"
                    ),
                    "sbml.native-import",
                    "published-SBML-record-eligibility",
                    "published-biomodels",
                )
            )
            continue
        if not isinstance(modes, list):
            raise ValueError("BioModels modes must be an array")
        seen = set()
        for mode in modes:
            if (
                not isinstance(mode, dict)
                or mode.get("mode") not in {"flat", "atomized"}
                or mode["mode"] in seen
            ):
                raise ValueError(
                    "BioModels modes require unique flat or atomized identities"
                )
            seen.add(mode["mode"])
            prefix = identity + ":" + mode["mode"]
            rows.append(
                _row(
                    prefix + ":execution",
                    "mode-execution",
                    _status(mode.get("status")),
                    str(
                        mode.get("unsupported_reason")
                        or mode.get("error")
                        or "mode orchestration outcome"
                    ),
                    "atomizer.core-lowering",
                    "published-SBML-mode-execution",
                    "published-biomodels",
                )
            )
            stages = [
                CONVERSION,
                (
                    "written_xml",
                    "roundtrip-write",
                    "validation",
                    "export.sbml",
                    "SBML-writer-validity",
                    "libsbml",
                ),
                (
                    "native_reader",
                    "roundtrip-native-reader",
                    "native",
                    "sbml.native-import",
                    "native-SBML-reader",
                    "bng3-native-reader",
                ),
                (
                    "reimport_network",
                    "reimport-network",
                    "network",
                    "atomizer.core-lowering",
                    "SBML-reimport-network-generation",
                    "roundtrip",
                ),
                COMPARISON,
            ]
            if "source_xml" in mode:
                stages.insert(0, SOURCE_XML)
            if "ode" in mode:
                stages.append(
                    (
                        "ode",
                        "ode-smoke",
                        "validation",
                        "simulation.ode",
                        "ODE-smoke-execution",
                        "BNG3-CVODE",
                    )
                )
            rows.extend(_stage_rows(prefix, mode, stages))
            _record_status_fallback(rows, prefix, mode)
        _record_status_fallback(rows, identity, record)
    return rows


def benchmark_results(document):
    return [
        {
            "id": "benchmark:" + record["model"],
            "stage": "performance",
            "status": "PASS" if record["status"] == "ok" else "FAIL",
            "detail": record.get("error", ""),
            "question": "performance-measurement-only",
            "measurements": record,
        }
        for record in document.get("models", [])
    ]


def run_existing_lane(name, root, directory, env, *, sbml_suite=None, timeout=7200):
    work = directory / "lanes" / name
    output = work / "results.json"
    if name == "performance":
        command = [
            sys.executable,
            str(root / "benchmarks/run_benchmarks.py"),
            "--models",
            "simple_system",
            "blbr",
            "--generation-only",
            "--repeats",
            "5",
            "--json",
            str(output),
            "--markdown",
            str(work / "results.md"),
        ]
        adapter = benchmark_results
    else:
        if sbml_suite is None:
            return [
                {
                    "id": name,
                    "stage": "reference-preflight",
                    "status": "HARNESS_ERROR",
                    "detail": "full tier requires --sbml-suite (locked official suite checkout)",
                }
            ]
        command = [
            sys.executable,
            str(root / "scripts/ci/validate_sbml_test_suite.py"),
            "--suite-dir",
            str(sbml_suite.resolve()),
            "--json",
            str(output),
            "--isolate-cases",
            "--jobs",
            "4",
            "--case-timeout",
            "60",
        ]
        adapter = sbml_results
    receipt = run_command(
        command, work, timeout, required=["results.json"], env=env, cwd=root
    )
    rows = []
    try:
        rows = adapter(json.loads(output.read_text()))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        receipt.update(status="HARNESS_ERROR", detail=str(exc))
    if not rows or receipt["status"] != "PASS":
        rows.append(
            {
                "id": name + ":process",
                "stage": "lane-execution",
                "status": (
                    receipt["status"]
                    if receipt["status"] != "PASS"
                    else "HARNESS_ERROR"
                ),
                "detail": receipt["detail"] or "empty report",
            }
        )
    return rows
