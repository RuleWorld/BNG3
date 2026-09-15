#!/usr/bin/env python3
"""Validate BNG3's SBML/Atomizer path on pinned public BioModels files.

The manifest pins the downloaded bytes, while this runner checks both the
modern Playground-derived flat and atomized Atomizer paths.  ODE simulation is
reported as a diagnostic because some published models are numerically stiff
or singular at their published initial conditions; import and network
generation are the hard acceptance gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_if_needed(path: Path, url: str, expected_sha256: str) -> None:
    if not path.exists():
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "BNG3-published-BioModels-validator/1"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            path.write_bytes(response.read())
    actual = _sha256(path)
    if actual != expected_sha256:
        raise RuntimeError(
            f"sha256 mismatch for {path.name}: expected {expected_sha256}, got {actual}"
        )


def _validate_mode(
    sbml: str, atomize: bool, cpp: Any, model_type: Any
) -> dict[str, Any]:
    from bionetgen.atomizer.modern import Atomizer

    mode = "atomized" if atomize else "flat"
    result: dict[str, Any] = {"mode": mode, "atomizer_success": False}
    atomized = Atomizer(atomize=atomize, quiet_mode=True).atomize(sbml)
    result["atomizer_success"] = atomized.success
    if not atomized.success:
        result["error"] = atomized.error
        result["core_passed"] = False
        return result

    try:
        cpp_model = cpp.parse_string(atomized.bngl)
        network = cpp.generate_network(cpp_model, max_iter=100)
        result["network"] = {
            "species": network.num_species,
            "reactions": network.num_reactions,
        }
        result["core_passed"] = network.num_species > 0 and network.num_reactions > 0
    except Exception as exc:  # pragma: no cover - exercised by external files
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["core_passed"] = False
        return result

    try:
        model = model_type(cpp_model)
        simulation = model.simulate(method="ode", t_end=1.0, n_steps=2)
        result["ode"] = {
            "passed": simulation.n_steps == 3,
            "time_points": simulation.n_steps,
        }
        if not result["ode"]["passed"]:
            result["ode"]["error"] = "unexpected output time-point count"
    except Exception as exc:  # published initial conditions may be singular
        result["ode"] = {
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repo = Path(__file__).resolve().parents[2]
    parser.add_argument(
        "--manifest",
        type=Path,
        default=repo / "provenance" / "published-biomodels.json",
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=repo / "work" / "published-biomodels"
    )
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        import bionetgen._bionetgen_cpp as cpp
        from bionetgen import BioNetGenModel
    except ImportError as exc:
        raise SystemExit(
            "BNG3 C++ extension is unavailable; set PYTHONPATH=python:build/cpp"
        ) from exc

    models = []
    for entry in manifest["models"]:
        path = args.cache_dir / entry["filename"]
        url = manifest["download_url_template"].format(
            id=entry["id"], filename=entry["filename"]
        )
        record: dict[str, Any] = {
            "id": entry["id"],
            "description": entry["description"],
            "filename": entry["filename"],
            "download_url": url,
            "sha256": entry["sha256"],
        }
        try:
            _download_if_needed(path, url, entry["sha256"])
            sbml = path.read_text(encoding="utf-8")
            record["modes"] = [
                _validate_mode(sbml, atomize=False, cpp=cpp, model_type=BioNetGenModel),
                _validate_mode(sbml, atomize=True, cpp=cpp, model_type=BioNetGenModel),
            ]
            record["core_passed"] = all(mode["core_passed"] for mode in record["modes"])
        except Exception as exc:  # download/hash/read failures are hard failures
            record["core_passed"] = False
            record["error"] = f"{type(exc).__name__}: {exc}"
        models.append(record)
        print(
            f"{entry['id']}: {'PASS' if record['core_passed'] else 'FAIL'} "
            f"({entry['description']})"
        )

    report = {
        "schema_version": 1,
        "manifest": str(args.manifest.resolve()),
        "cache_dir": str(args.cache_dir.resolve()),
        "models": models,
        "core_passed": all(record["core_passed"] for record in models),
        "ode_passed": all(
            mode.get("ode", {}).get("passed", False)
            for record in models
            for mode in record.get("modes", [])
        ),
        "ode_is_diagnostic": True,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"core={'PASS' if report['core_passed'] else 'FAIL'} "
        f"ode={'PASS' if report['ode_passed'] else 'DIAGNOSTIC-FAIL'}"
    )
    return 0 if report["core_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
