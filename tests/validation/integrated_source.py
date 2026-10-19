"""Independent source-model validation for integrated semantic cases."""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np

from .integrated_cases import TIMES, expected_source_species


def validate_sbml_source(xml):
    """Validate generated input independently before attributing consumer results."""
    import libsbml

    document = libsbml.readSBMLFromString(xml)
    document.checkConsistency()
    errors = [
        document.getError(index).getMessage().strip()
        for index in range(document.getNumErrors())
        if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    if document.getModel() is None:
        errors.append("libSBML did not produce a model")
    if errors:
        return "INVALID_INPUT", "libSBML rejected generated source: " + " | ".join(
            errors
        )
    return "PASS", "libSBML consistency validation accepted generated source"


def source_selection_names(case, species):
    """Return RoadRunner selectors for source-symbol amount/concentration values."""
    if case.get("transform") == "concentration-coordinate":
        return [f"[{name}]" for name in species]
    return list(species)


def source_trajectory_difference(actual, case, species=None):
    """Compare raw SBML states with analytic source-coordinate trajectories."""
    expected, expected_species = expected_source_species(case)
    species = expected_species if species is None else species
    if actual.shape != (len(TIMES), len(species) + 1):
        return {
            "field": "shape",
            "expected": [len(TIMES), len(species) + 1],
            "actual": list(actual.shape),
        }
    if not np.allclose(actual[:, 0], TIMES, rtol=0, atol=1e-9):
        index = int(
            np.flatnonzero(~np.isclose(actual[:, 0], TIMES, rtol=0, atol=1e-9))[0]
        )
        return {
            "field": "time",
            "row": index,
            "expected": float(TIMES[index]),
            "actual": float(actual[index, 0]),
        }
    if not np.allclose(actual[:, 1:], expected, rtol=1e-7, atol=1e-9):
        positions = np.argwhere(
            ~np.isclose(actual[:, 1:], expected, rtol=1e-7, atol=1e-9)
        )
        index, column = map(int, positions[0])
        return {
            "field": species[column],
            "row": index,
            "expected": float(expected[index, column]),
            "actual": float(actual[index, column + 1]),
        }
    return None


def source_sbml_oracle(case, source_path, directory, source_validation):
    """Run raw SBML in RoadRunner and compare fixed source-coordinate laws."""
    row = dict(
        id=f"{case['id']}:source-sbml-oracle",
        stage="source-sbml-oracle",
        integration_case=case["id"],
        status="NOT_TESTED",
        detail="source validation prerequisite did not pass",
        command="libRoadRunner executes raw generated source.xml",
        related_issues=[],
    )
    if source_validation["status"] != "PASS":
        row["blocked_by"] = [source_validation["id"]]
        return row
    try:
        import roadrunner
    except ImportError as exc:
        row.update(
            status="HARNESS_ERROR",
            detail=f"required libRoadRunner dependency unavailable: {exc}",
        )
        return row
    try:
        rr = roadrunner.RoadRunner(str(source_path.resolve()))
        _, species = expected_source_species(case)
        selections = source_selection_names(case, species)
        selections_with_time = ["time", *selections]
        rr.integrator.relative_tolerance = 1e-10
        rr.integrator.absolute_tolerance = 1e-12
        actual = np.asarray(
            rr.simulate(times=TIMES, selections=selections_with_time), dtype=float
        )
    except Exception as exc:
        row.update(
            status="FAIL",
            detail=f"libRoadRunner could not execute valid generated SBML: {type(exc).__name__}: {exc}",
            first_difference={"exception_type": type(exc).__name__, "detail": str(exc)},
        )
        return row

    try:
        metadata = {
            "implementation": "libRoadRunner",
            "version": getattr(roadrunner, "__version__", None),
            "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "model_name": rr.model.getModelName(),
            "selections": selections_with_time,
            "source_coordinate": (
                "concentration"
                if case.get("transform") == "concentration-coordinate"
                else "amount"
            ),
            "relative_tolerance": 1e-10,
            "absolute_tolerance": 1e-12,
            "time_grid": TIMES.tolist(),
        }
        if metadata["version"] is None:
            for distribution in ("libroadrunner", "roadrunner"):
                try:
                    metadata["version"] = version(distribution)
                    break
                except PackageNotFoundError:
                    continue
        if metadata["version"] is None:
            raise RuntimeError("could not identify the installed libRoadRunner version")

        observed_path = directory / "source-roadrunner.gdat"
        np.savetxt(
            observed_path,
            actual,
            header=" ".join(selections_with_time),
            fmt="%.17g",
        )
        metadata_path = directory / "source-roadrunner.json"
        metadata_path.write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as exc:
        row.update(
            status="HARNESS_ERROR",
            detail=f"could not record libRoadRunner identity/artifacts: {type(exc).__name__}: {exc}",
            first_difference={"exception_type": type(exc).__name__, "detail": str(exc)},
        )
        return row
    row["receipt"] = str(observed_path.resolve())
    row["metadata_receipt"] = str(metadata_path.resolve())
    row["oracle"] = metadata
    difference = source_trajectory_difference(actual, case, species)
    row.update(
        status="FAIL" if difference else "PASS",
        detail=(
            "raw SBML source species trajectories match fixed closed-form amount laws"
            " in the declared amount/concentration coordinate"
        ),
        first_difference=difference,
    )
    return row
