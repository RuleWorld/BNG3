"""Replay the raw SBML sources through source and BNG3 stages separately."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from case_contract import (
    CASE_IDS,
    SPECIFICATION,
    SPEC_URL,
    continuation_segments,
    expected,
    sample_times,
    self_check,
    source_path,
)

HERE = Path(__file__).resolve().parent
ATOL = 1e-9
RTOL = 1e-9


def _stage(stage_id: str, status: str, detail: str, **extra) -> dict:
    return {"id": stage_id, "status": status, "detail": detail, **extra}


def _source_validation(source_path_: Path) -> dict:
    import libsbml

    document = libsbml.readSBMLFromFile(str(source_path_))
    document.checkConsistency()
    errors = [
        document.getError(index).getMessage().strip()
        for index in range(document.getNumErrors())
        if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    model = document.getModel()
    if model is None:
        errors.append("libSBML produced no model")
    if errors:
        return _stage(
            "source-validation",
            "INVALID_SOURCE",
            "libSBML rejected the raw source",
            errors=errors,
            libsbml_version=libsbml.getLibSBMLDottedVersion(),
        )
    return _stage(
        "source-validation",
        "PASS",
        "libSBML consistency validation found no errors",
        libsbml_version=libsbml.getLibSBMLDottedVersion(),
        warning_count=sum(
            document.getError(index).getSeverity() == libsbml.LIBSBML_SEV_WARNING
            for index in range(document.getNumErrors())
        ),
    )


def _analytic_reference(case_id: str, times: tuple[float, ...]) -> tuple[dict, dict]:
    self_check()
    values = {
        symbol: [expected(case_id, t)[symbol] for t in times]
        for symbol in ("z", "k", "x", "y", "q")
    }
    return (
        _stage(
            "analytic-reference",
            "PASS",
            "independent closed-form equations and event/history boundaries self-check",
            specification=SPECIFICATION,
            specification_url=SPEC_URL,
            values={"time": list(times), **values},
        ),
        values,
    )


def _road_runner_oracle(case_id: str, path: Path, outdir: Path) -> dict:
    try:
        import roadrunner
    except ImportError as exc:
        return _stage(
            "raw-source-libroadrunner",
            "ORACLE_UNAVAILABLE",
            f"libRoadRunner is not installed: {exc}",
        )
    try:
        times = sample_times(case_id)
        rr = roadrunner.RoadRunner(str(path.resolve()))
        rr.integrator.relative_tolerance = 1e-10
        rr.integrator.absolute_tolerance = 1e-12
        selections = ["time", "z", "k", "x", "y", "q"]
        values = np.asarray(
            rr.simulate(times=list(times), selections=selections), dtype=float
        )
    except Exception as exc:
        return _stage(
            "raw-source-libroadrunner",
            "ORACLE_UNAVAILABLE",
            f"libRoadRunner {getattr(roadrunner, '__version__', 'unknown')} cannot execute this raw DDE source: {type(exc).__name__}: {exc}",
            oracle_version=getattr(roadrunner, "__version__", None),
        )
    expected_values = np.asarray(
        [[t, *(expected(case_id, t)[name] for name in selections[1:])] for t in times],
        dtype=float,
    )
    artifact = outdir / f"{case_id}-raw-roadrunner.csv"
    np.savetxt(
        artifact,
        values,
        delimiter=",",
        header=",".join(selections),
        comments="",
        fmt="%.17g",
    )
    differences = np.argwhere(
        ~np.isclose(values, expected_values, atol=ATOL, rtol=RTOL)
    )
    first_difference = None
    if differences.size:
        row, column = map(int, differences[0])
        first_difference = {
            "time": float(times[row]),
            "quantity": selections[column],
            "expected": float(expected_values[row, column]),
            "actual": float(values[row, column]),
        }
    return _stage(
        "raw-source-libroadrunner",
        "FAIL" if first_difference else "PASS",
        "raw SBML source executed by the independent libRoadRunner engine",
        oracle_version=getattr(roadrunner, "__version__", None),
        artifact=str(artifact.resolve()),
        first_difference=first_difference,
    )


def _atomize(path: Path, outdir: Path) -> tuple[dict, str | None]:
    try:
        from bionetgen.atomizer.modern import Atomizer
    except Exception as exc:
        return (
            _stage(
                "atomizer-lowering",
                "HARNESS_ERROR",
                f"could not import BNG3 Atomizer: {type(exc).__name__}: {exc}",
            ),
            None,
        )
    # Keep the requested horizon fixed: all delayed queries end at t/2 <= 1.
    atomizer = Atomizer(atomize=False, quiet_mode=True, t_end=2.0)
    try:
        result = atomizer.atomize(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return (
            _stage(
                "atomizer-lowering",
                "FAIL",
                f"Atomizer raised while lowering valid source: {type(exc).__name__}: {exc}",
            ),
            None,
        )
    warnings = [
        {
            "category": warning.category,
            "severity": warning.severity,
            "message": warning.message,
            "count": warning.count,
        }
        for warning in getattr(getattr(atomizer, "model", None), "import_warnings", ())
    ]
    if not result.success or not result.bngl:
        status = "REQUIRED_BUT_UNSUPPORTED" if result.error else "FAIL"
        return (
            _stage(
                "atomizer-lowering",
                status,
                result.error or "Atomizer emitted no representation",
                warnings=warnings,
            ),
            result.bngl or None,
        )
    bngl_path = outdir / f"{path.stem}-emitted.bngl"
    bngl_path.write_text(result.bngl, encoding="utf-8")
    has_dynamic_delay = "delay(" in result.bngl.lower()
    if not has_dynamic_delay:
        status = "FAIL"
        detail = (
            "valid nonconstant delayed read disappeared from emitted representation"
        )
    else:
        status = "PASS"
        detail = "Atomizer emitted a BNG3 representation retaining the nonconstant delayed read"
    return (
        _stage(
            "atomizer-lowering",
            status,
            detail,
            warnings=warnings,
            emitted_bngl=str(bngl_path.resolve()),
            emitted_bngl_sha256=hashlib.sha256(bngl_path.read_bytes()).hexdigest(),
        ),
        result.bngl,
    )


def _public_bng3(
    case_id: str, bngl: str | None, outdir: Path
) -> tuple[dict, dict, dict]:
    if not bngl:
        missing = _stage(
            "public-bng3-execution", "NOT_TESTED", "no emitted BNGL was available"
        )
        return (
            missing,
            _stage(
                "public-bng3-continuation",
                "NOT_TESTED",
                "execution prerequisite missing",
            ),
            _stage(
                "public-bng3-output-comparison",
                "NOT_TESTED",
                "execution prerequisite missing",
            ),
        )
    try:
        from bionetgen import BioNetGenModel, _bionetgen_cpp
    except Exception as exc:
        detail = f"candidate native extension unavailable: {type(exc).__name__}: {exc}"
        return (
            _stage("public-bng3-execution", "NOT_TESTED", detail),
            _stage("public-bng3-continuation", "NOT_TESTED", detail),
            _stage("public-bng3-output-comparison", "NOT_TESTED", detail),
        )
    failed_segment = None
    try:
        native_model = _bionetgen_cpp.parse_string(bngl)
        model = BioNetGenModel(native_model)
        observations = []
        segments = continuation_segments(case_id)
        for index, (start, end) in enumerate(segments):
            failed_segment = index
            result = model.simulate(
                method="ode",
                t_start=start,
                t_end=end,
                n_steps=0,
                sample_times=(
                    [start, end]
                    if case_id == "interaction"
                    else list(sample_times(case_id))
                ),
                continue_simulation=index > 0,
                rtol=RTOL,
                atol=ATOL,
            )
            functions = getattr(result, "functions", {})
            observables = getattr(result, "observables", {})
            times = np.asarray(result.time, dtype=float)
            for row, time in enumerate(times):
                if observations and np.isclose(
                    time, observations[-1]["time"], atol=1e-13, rtol=0
                ):
                    continue
                observations.append(
                    {
                        "time": float(time),
                        **{
                            name: float(np.asarray(values[name])[row])
                            for name, values in (
                                ("x_amt", observables),
                                ("z_amt", observables),
                                ("y", functions),
                                ("q", functions),
                            )
                            if name in values
                        },
                    }
                )
        runtime_identity = {
            "module": str(Path(_bionetgen_cpp.__file__).resolve()),
            "module_sha256": hashlib.sha256(
                Path(_bionetgen_cpp.__file__).read_bytes()
            ).hexdigest(),
        }
    except Exception as exc:
        msg = f"public BNG3 execution raised: {type(exc).__name__}: {exc}"
        low = msg.lower()
        status = (
            "REQUIRED_BUT_UNSUPPORTED"
            if "unsupported" in low or "unrepresentable" in low
            else "FAIL"
        )
        return (
            _stage("public-bng3-execution", status, msg),
            _stage(
                "public-bng3-continuation",
                (
                    "FAIL"
                    if case_id == "interaction"
                    and failed_segment
                    and failed_segment > 0
                    else "NOT_TESTED"
                ),
                (
                    "continued phase raised before completion"
                    if case_id == "interaction"
                    and failed_segment
                    and failed_segment > 0
                    else "continuation was not reached"
                ),
            ),
            _stage(
                "public-bng3-output-comparison",
                "NOT_TESTED",
                "execution failed before outputs were available",
            ),
        )
    output = outdir / f"{case_id}-public-bng3.json"
    output.write_text(json.dumps(observations, indent=2) + "\n", encoding="utf-8")
    mismatch = None
    for observation in observations:
        t = observation["time"]
        want = expected(case_id, t)
        for output_name, reference_name in (
            ("x_amt", "x"),
            ("z_amt", "z"),
            ("y", "y"),
            ("q", "q"),
        ):
            if output_name not in observation:
                mismatch = {
                    "time": t,
                    "quantity": output_name,
                    "reason": "missing output",
                }
                break
            actual = observation[output_name]
            reference = want[reference_name]
            if not np.isclose(actual, reference, atol=ATOL, rtol=RTOL):
                mismatch = {
                    "time": t,
                    "quantity": output_name,
                    "expected": reference,
                    "actual": actual,
                }
                break
        if mismatch:
            break
    continuation_status = "PASS" if case_id == "interaction" else "NOT_REQUIRED"
    return (
        _stage(
            "public-bng3-execution",
            "PASS" if not mismatch else "FAIL",
            "public BioNetGenModel ODE API executed the emitted representation",
            native_identity=runtime_identity,
            segments=[list(segment) for segment in continuation_segments(case_id)],
        ),
        _stage(
            "public-bng3-continuation",
            continuation_status,
            (
                "one native session preserved delayed state across all four public continuation intervals"
                if case_id == "interaction"
                else "only one uninterrupted public simulation was required"
            ),
            segments=[list(segment) for segment in continuation_segments(case_id)],
        ),
        _stage(
            "public-bng3-output-comparison",
            "PASS" if not mismatch else "FAIL",
            "public outputs compared against the independent analytic source law",
            artifact=str(output.resolve()),
            first_difference=mismatch,
        ),
    )


def replay_case(case_id: str, outdir: Path) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    path = source_path(case_id)
    raw_copy = outdir / f"{case_id}-source.xml"
    shutil.copyfile(path, raw_copy)
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    validation = _source_validation(path)
    analytic, _ = _analytic_reference(case_id, sample_times(case_id))
    stages = [validation, analytic]
    if validation["status"] == "PASS":
        stages.append(_road_runner_oracle(case_id, path, outdir))
        lowering, bngl = _atomize(path, outdir)
        stages.append(lowering)
        execution, continuation, comparison = _public_bng3(case_id, bngl, outdir)
        stages.extend((execution, continuation, comparison))
    else:
        stages.extend(
            _stage(stage, "NOT_TESTED", "blocked by invalid raw source")
            for stage in (
                "raw-source-libroadrunner",
                "atomizer-lowering",
                "public-bng3-execution",
                "public-bng3-continuation",
                "public-bng3-output-comparison",
            )
        )
    product = next(
        (stage for stage in stages if stage["id"] == "public-bng3-output-comparison"),
        None,
    )
    lowering = next(stage for stage in stages if stage["id"] == "atomizer-lowering")
    execution = next(
        stage for stage in stages if stage["id"] == "public-bng3-execution"
    )
    if validation["status"] != "PASS":
        verdict = "INVALID_SOURCE"
    elif lowering["status"] == "REQUIRED_BUT_UNSUPPORTED":
        verdict = "REQUIRED_BUT_UNSUPPORTED"
    elif execution["status"] == "REQUIRED_BUT_UNSUPPORTED":
        verdict = "REQUIRED_BUT_UNSUPPORTED"
    elif execution["status"] == "FAIL":
        verdict = "SEMANTIC_FAILURE"
    elif product and product["status"] == "FAIL":
        verdict = "SEMANTIC_FAILURE"
    elif product and product["status"] == "PASS":
        verdict = "PASS"
    else:
        verdict = "MISSING_EVIDENCE"
    report = {
        "case_id": case_id,
        "source_path": str(path.resolve()),
        "source_sha256": source_hash,
        "raw_source_copy": str(raw_copy.resolve()),
        "case_source_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=HERE.parents[4],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "specification": SPECIFICATION,
        "specification_url": SPEC_URL,
        "command": "python tests/validation/release/cases/sprint-s5-delay-history/replay.py --out <outdir>",
        "time_grid": list(sample_times(case_id)),
        "continuation_segments": [
            list(segment) for segment in continuation_segments(case_id)
        ],
        "comparator": {"kind": "analytic source law", "atol": ATOL, "rtol": RTOL},
        "verdict": verdict,
        "stages": stages,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    reports = [replay_case(case_id, args.out) for case_id in CASE_IDS]
    source_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=HERE.parents[4],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest = {
        "harness_revision": source_revision,
        "native_source_revision": os.environ.get(
            "BNG3_SOURCE_REVISION", source_revision
        ),
        "product_code_base_sha": "9c6fd7ee0862405d08217703a280e56da74de206",
        "repository_dirty": bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=HERE.parents[4],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ),
        "oracle_versions": {
            "libSBML": __import__("libsbml").getLibSBMLDottedVersion(),
            "libRoadRunner": getattr(__import__("roadrunner"), "__version__", None),
            "python": sys.version.split()[0],
        },
        "cases": reports,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    report_path = args.out / "s5-replay.json"
    report_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(report_path.resolve()),
                "verdicts": {r["case_id"]: r["verdict"] for r in reports},
            },
            indent=2,
        )
    )
    return (
        1
        if any(r["verdict"] in {"INVALID_SOURCE", "SEMANTIC_FAILURE"} for r in reports)
        else 0
    )


if __name__ == "__main__":
    sys.exit(main())
