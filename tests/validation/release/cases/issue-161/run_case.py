#!/usr/bin/env python3
"""Run the reduced Issue 161 authored Multi export comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))
from scripts.cross_validate import (  # noqa: E402
    _run_engine,
    _stage_authored_action_model,
    run_cross_validation,
)
from scripts.ci.oracle_sources import load_lock, load_oracle_source  # noqa: E402
from tests.validation.oracle_perl import _is_locked_bng2  # noqa: E402
from bionetgen.atomizer.modern import (  # noqa: E402
    SBMLParser,
    build_species_composition_table,
    generate_bngl,
    get_molecule_types,
    get_seed_species,
)

MODEL_NAME = "test_write_sbml_multi"
CASES = (
    "test_write_sbml_multi.bngl",
    "state_bearing_binding_refusal.bngl",
)
LOCKED_BNG2_REVISION = load_oracle_source(load_lock(), "bionetgen")["revision"]


def _git_identity(path: Path) -> dict:
    git_path = path if path.is_dir() else path.parent
    root = subprocess.run(
        ["git", "-C", str(git_path), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    revision = subprocess.run(
        ["git", "-C", root, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    return {"root": root, "revision": revision, "dirty": dirty}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _consume_and_reimport(
    xml_path: Path, bng_cpp: Path, work_dir: Path, timeout: float
) -> dict:
    """Require the emitted Multi document to reconstruct and execute in BNG3."""

    model = SBMLParser().parse(xml_path.read_text(encoding="utf-8"))
    if not model.multi_executable:
        raise RuntimeError("reimported SBML Multi model is not executable")
    if not model.multi_species_patterns or not model.multi_reaction_mappings:
        raise RuntimeError("reimported SBML Multi structures are empty")

    composition = build_species_composition_table(model)
    molecule_types = get_molecule_types(composition, model.multi_type_patterns.values())
    bngl, _ = generate_bngl(
        model, composition, molecule_types, get_seed_species(composition, model)
    )
    if "not yet fed into the simulated network" in bngl:
        raise RuntimeError(
            "reimported Multi data was dropped during BNGL reconstruction"
        )

    reconstructed = work_dir / "reimported_multi.bngl"
    reconstructed.write_text(
        bngl.rstrip() + "\n\n## actions ##\ngenerate_network({overwrite=>1})\n",
        encoding="utf-8",
    )
    result, error = _run_engine([str(bng_cpp), str(reconstructed)], work_dir, timeout)
    if error:
        raise RuntimeError(f"reimported BNG3 model did not execute: {error}")
    if result is None or result.returncode != 0:
        detail = "process did not return" if result is None else result.stderr.strip()
        raise RuntimeError(f"reimported BNG3 model did not execute: {detail}")
    network = work_dir / "reimported_multi.net"
    if not network.is_file() or network.stat().st_size == 0:
        raise RuntimeError("reimported BNG3 model did not produce a network")
    return {
        "species_patterns": len(model.multi_species_patterns),
        "reaction_mappings": len(model.multi_reaction_mappings),
        "network_bytes": network.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bng-cpp", type=Path, required=True)
    parser.add_argument("--bng2", type=Path, required=True)
    parser.add_argument("--perl", default="perl")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    for name, path in (("bng_cpp", args.bng_cpp), ("BNG2.pl", args.bng2)):
        if not path.is_file():
            parser.error(f"{name} is not a file: {path}")
    product = _git_identity(ROOT)
    oracle = _git_identity(args.bng2)
    provenance = {
        "product": product,
        "bng_cpp": {
            "path": str(args.bng_cpp.resolve()),
            "sha256": _sha256(args.bng_cpp),
        },
        "bng2": {
            **oracle,
            "locked_revision": LOCKED_BNG2_REVISION,
            "revision_matches_lock": oracle["revision"] == LOCKED_BNG2_REVISION,
            "checkout_is_locked": _is_locked_bng2(args.bng2),
            "script": {"path": str(args.bng2.resolve()), "sha256": _sha256(args.bng2)},
        },
    }
    provenance["eligible"] = bool(
        not product["dirty"]
        and oracle["revision"] == LOCKED_BNG2_REVISION
        and not oracle["dirty"]
        and provenance["bng2"]["checkout_is_locked"]
    )
    case_results = []
    for case in CASES:
        source = Path(__file__).with_name(case)
        with tempfile.TemporaryDirectory(
            prefix=f"bng3-issue-161-{source.stem}-"
        ) as raw:
            root = Path(raw)
            models = root / "Validate"
            models.mkdir()
            staged = models / f"{MODEL_NAME}.bngl"
            shutil.copyfile(source, staged)
            counts, details = run_cross_validation(
                args.bng_cpp,
                args.bng2,
                models,
                perl_executable=args.perl,
                timeout=args.timeout,
                model_names=[MODEL_NAME],
            )
            consumer = None
            cpp_dir = root / "consumer-cpp"
            cpp_dir.mkdir()
            cpp_model = _stage_authored_action_model(staged, models, cpp_dir)
            result, error = _run_engine(
                [str(args.bng_cpp.resolve()), str(cpp_model)],
                cpp_dir,
                args.timeout,
            )
            if error:
                consumer_error = error
            elif result is None or result.returncode != 0:
                consumer_error = (
                    "process did not return"
                    if result is None
                    else result.stderr.strip()
                )
            else:
                output = cpp_dir / f"{MODEL_NAME}_sbml_multi.xml"
                if not output.is_file() or not output.stat().st_size:
                    consumer_error = "C++ authored export output is missing or empty"
                else:
                    consumer_error = None
                    try:
                        consumer = _consume_and_reimport(
                            output, args.bng_cpp.resolve(), cpp_dir, args.timeout
                        )
                    except Exception as exc:  # the report preserves the failing stage
                        consumer_error = str(exc)
            case_results.append(
                {
                    "source": case,
                    "source_sha256": _sha256(source),
                    "authored_export": {"counts": counts, "details": details},
                    "reimport_network_smoke": {
                        "status": "pass" if consumer_error is None else "error",
                        "details": consumer,
                        "error": consumer_error,
                    },
                }
            )
    report = {
        "case": "issue-161/authored-multi-and-reimport-network-smoke",
        "provenance": provenance,
        "cases": case_results,
        "classification": (
            "pass"
            if provenance["eligible"]
            and all(
                entry["authored_export"]["counts"] == {"pass": 1, "fail": 0, "error": 0}
                and entry["reimport_network_smoke"]["status"] == "pass"
                for entry in case_results
            )
            else "failed-or-error"
        ),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["classification"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
