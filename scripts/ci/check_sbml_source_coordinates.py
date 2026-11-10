"""Replay two weekly translation fixtures against their original SBML ODEs.

Graph identity is reported independently and is never relaxed by this check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.cross_validate import _stage_model, compare_network_files
from tests.validation.compare import parse_net
from tests.validation.sbml_source_coordinates import (
    InvalidSource,
    UnsupportedSource,
    SemanticMismatch,
    compare_source_rhs,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root, *arguments):
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], text=True
    ).strip()


def locked_source(root, name, lock):
    revision = git(root, "rev-parse", "HEAD")
    if revision != lock["sources"][name]["revision"] or git(
        root, "status", "--porcelain", "--untracked-files=no"
    ):
        raise ValueError(f"{name}: stale or dirty independent source")
    return revision


def run(command, directory, environment, log):
    with log.open("w") as output:
        output.write(json.dumps(command) + "\n")
        output.flush()
        process = subprocess.run(
            command,
            cwd=directory,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=180,
        )
    if process.returncode:
        raise RuntimeError(f"command exited {process.returncode}; see {log}")


def coordinates(network, case, candidate):
    parsed = parse_net(network)
    if case == "flat":
        labels = ["A()", "B()", "C()", "D()", "AA()"]
        lookup = {
            label.removeprefix("@cell::"): index
            for index, label in parsed.species_by_index.items()
        }
        return {f"S{i+1}": lookup[name] for i, name in enumerate(labels)}
    labels = (
        ["MolA_cell", "MolB_cell", "MolA_MolB_cell", "MolA_P_cell", "__MolB__2_cell"]
        if candidate
        else ["MolA", "MolB", "MolA_MolB", "MolA_P", "MolB2"]
    )
    groups = {name: weights for name, weights in parsed.groups.values()}
    mapping = {}
    for i, name in enumerate(labels):
        weights = groups[name]
        if len(weights) != 1 or next(iter(weights.values())) != 1:
            raise ValueError(f"coordinate {name} is not an exact singleton")
        mapping[f"S{i+1}"] = next(iter(weights))
    return mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bng-cpp", type=Path, required=True)
    parser.add_argument("--bng2-root", type=Path, required=True)
    parser.add_argument("--translator-root", type=Path, required=True)
    parser.add_argument("--translator-python", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=False)
    report = {
        "check_id": "weekly-bounded-source-coordinate-ode",
        "result": "HARNESS_ERROR",
        "scope": "two fixtures; initial amounts and deterministic ODE RHS only; graph and stochastic identity remain separate",
        "cases": {},
    }
    report_path = args.artifacts / "report.json"

    def save():
        report_path.write_text(json.dumps(report, indent=2) + "\n")

    save()
    try:
        lock = json.loads((ROOT / "provenance/upstreams.lock.yml").read_text())
        report["source_revision"] = git(ROOT, "rev-parse", "HEAD")
        if git(ROOT, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("product checkout has tracked modifications")
        if not args.bng_cpp.resolve().is_relative_to(ROOT / "build"):
            raise ValueError(
                "product executable must come from this checkout's fresh CI build"
            )
        cache = (ROOT / "build/CMakeCache.txt").read_text()
        if f"CMAKE_HOME_DIRECTORY:INTERNAL={ROOT}" not in cache:
            raise ValueError("product build belongs to another source checkout")
        report["bng2_revision"] = locked_source(args.bng2_root, "bionetgen", lock)
        report["translator_revision"] = locked_source(
            args.translator_root, "pybionetgen", lock
        )
        report["bng_cpp_sha256"] = digest(args.bng_cpp)
        reference_env = dict(
            os.environ,
            PYTHONPATH=str(args.translator_root),
            BNGPATH=str(args.bng2_root / "bng2"),
        )
        # Reject a dedicated oracle interpreter that imports another package.
        imported = subprocess.check_output(
            [
                str(args.translator_python),
                "-c",
                "import bionetgen; print(bionetgen.__file__)",
            ],
            env=reference_env,
            text=True,
        ).strip()
        if not Path(imported).resolve().is_relative_to(args.translator_root.resolve()):
            raise ValueError(
                "independent translator interpreter imports a foreign package"
            )
        corpus = ROOT / "tests/validation/Validate"
        for case in ("flat", "structured"):
            evidence = report["cases"][case] = {"result": "NOT_TESTED"}
            save()
            directory = args.artifacts / case
            directory.mkdir()
            source = corpus / "INPUT_FILES" / f"test_sbml_{case}_SBML.xml"
            model = corpus / f"test_sbml_{case}.bngl"
            staged = _stage_model(model, corpus, directory / "bng3")
            run(
                [str(args.bng_cpp.resolve()), str(staged.resolve())],
                staged.parent,
                dict(os.environ),
                directory / "bng3.log",
            )
            candidate = staged.with_suffix(".net")
            reference_dir = directory / "reference"
            reference_dir.mkdir()
            translated = reference_dir / "model.bngl"
            command = [
                str(args.translator_python),
                str(args.translator_root / "bionetgen/atomizer/sbmlTranslator.py"),
                "-i",
                str(source),
                "-o",
                str(translated.resolve()),
            ]
            if case == "structured":
                command.append("-a")
            run(command, reference_dir, reference_env, directory / "translator.log")
            # The oracle owns translation; only generation actions are added.
            with translated.open("a") as output:
                output.write("\ngenerate_network({overwrite=>1})\n")
            run(
                [
                    "perl",
                    str(args.bng2_root / "bng2/BNG2.pl"),
                    str(translated.resolve()),
                ],
                reference_dir,
                reference_env,
                directory / "bng2.log",
            )
            reference = translated.with_suffix(".net")
            graph = compare_network_files(reference, candidate)
            evidence["strict_graph"] = {
                "result": "PASS" if graph.ok else "FAIL",
                "details": graph.summary(),
            }
            evidence["networks"] = {}
            for label, network, is_candidate in [
                ("bng2", reference, False),
                ("bng3", candidate, True),
            ]:
                evidence["networks"][label] = compare_source_rhs(
                    source, network, coordinates(network, case, is_candidate)
                )
                save()
            evidence["result"] = "PASS"
            save()
        report["result"] = "PASS"
    except Exception as error:
        report["result"] = (
            "INVALID_INPUT"
            if isinstance(error, InvalidSource)
            else (
                "UNSUPPORTED"
                if isinstance(error, UnsupportedSource)
                else "FAIL" if isinstance(error, SemanticMismatch) else "HARNESS_ERROR"
            )
        )
        if report["cases"]:
            list(report["cases"].values())[-1]["result"] = report["result"]
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        save()
    print(json.dumps(report, indent=2))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
