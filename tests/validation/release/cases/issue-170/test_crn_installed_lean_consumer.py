"""Exercise the installed public CRN artifact through crnt-lean's importer."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess

import bionetgen
from scripts.ci.check_python_package_identity import inspect_installed_package


def _model_source() -> str:
    return """
begin model
begin units
    timeunits second
    substanceUnits item
    volumeUnits litre
    unit per_minute = minute^-1
end units
begin parameters
    k1 = 1 [second^-1]
    k2 = 2 [per_minute]
    k3 = 3 [second^-1]
end parameters
begin molecule types
    A()
    B()
    C()
end molecule types
begin seed species
    A() 10 [item]
end seed species
begin functions
    doubled() = 2*k2
end functions
begin reaction rules
    make: A() -> B() + B() k1
    convert: B() -> C() doubled()
    return: C() -> A() k3
end reaction rules
end model
"""


def _lean_environment(consumer_root: Path) -> dict[str, str]:
    lean_paths = [consumer_root / ".lake" / "build" / "lib" / "lean"]
    package_root = consumer_root / ".lake" / "packages"
    if package_root.is_dir():
        lean_paths.extend(
            package / ".lake" / "build" / "lib" / "lean"
            for package in sorted(package_root.iterdir())
        )
    lean_paths.extend(
        Path(path) for path in os.environ.get("LEAN_PATH", "").split(os.pathsep) if path
    )
    env = os.environ.copy()
    env["LEAN_PATH"] = os.pathsep.join(
        str(path.resolve()) for path in lean_paths if path.is_dir()
    )
    return env


def test_installed_crn_artifact_is_imported_by_crnt_lean(tmp_path):
    consumer_root = Path(os.environ["BNG3_CRNT_LEAN_ROOT"]).resolve()
    consumer_revision = os.environ["BNG3_CRNT_LEAN_REVISION"]
    probe = Path(__file__).with_name("CrntLeanImportProbe.lean").resolve()
    actual_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=consumer_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert actual_revision == consumer_revision
    assert not subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=consumer_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    package_identity = inspect_installed_package(
        source_revision=os.environ["BNG3_SOURCE_REVISION"],
        require_source_head=True,
        product_checkout=Path(__file__).resolve().parents[5],
    )

    model_path = tmp_path / "functional-cycle.bngl"
    model_path.write_text(_model_source(), encoding="utf-8")
    model = bionetgen.load(model_path)
    crn_path = tmp_path / "functional-cycle.crn.json"
    model.write_crn(crn_path)
    crn = json.loads(crn_path.read_text(encoding="utf-8"))

    assert [(s["index"], s["name"]) for s in crn["species"]] == [
        (0, "A()"),
        (1, "B()"),
        (2, "C()"),
    ]
    assert [c["species"] for c in crn["complexes"]] == [[0], [1, 1], [1], [2]]
    assert [
        (r["reactants"], r["products"], r["reactant_complex"], r["product_complex"])
        for r in crn["reactions"]
    ] == [([0], [1, 1], 0, 1), ([1], [2], 2, 3), ([2], [0], 3, 0)]
    assert crn["stoichiometric_matrix"] == [
        [-1, 0, 1],
        [2, -1, 0],
        [0, 1, -1],
    ]
    functional_rate = crn["reactions"][1]["rate_law"]
    assert functional_rate["expression"] == "doubled()"
    assert functional_rate["rule_name"] == "convert"
    assert functional_rate["functions"] == ["doubled"]
    assert functional_rate["parameters"] == ["k2"]
    assert functional_rate["parameter_units"] == {"k2": "per_minute"}
    assert crn["units"]["definitions"] == [
        {"name": "per_minute", "expression": "minute^-1"}
    ]

    reactions = []
    for reaction in crn["reactions"]:
        source = [0] * len(crn["species"])
        target = [0] * len(crn["species"])
        for species in reaction["reactants"]:
            source[species] += 1
        for species in reaction["products"]:
            target[species] += 1
        reactions.append({"source": source, "target": target})
    network_data = {"numSpecies": len(crn["species"]), "reactions": reactions}
    payload_path = tmp_path / "crnt-lean-network-data.json"
    payload_path.write_text(json.dumps(network_data) + "\n", encoding="utf-8")

    consumed = subprocess.run(
        ["lean", "--run", str(probe)],
        cwd=consumer_root,
        input=payload_path.read_text(encoding="utf-8"),
        env=_lean_environment(consumer_root),
        capture_output=True,
        text=True,
    )
    assert consumed.returncode == 0, consumed.stderr
    assert json.loads(consumed.stdout) == {"numSpecies": 3, "numReactions": 3}

    if evidence_dir := os.environ.get("BNG3_CRN_ARTIFACT_DIR"):
        output = Path(evidence_dir).resolve()
        output.mkdir(parents=True, exist_ok=True)
        (output / crn_path.name).write_bytes(crn_path.read_bytes())
        (output / payload_path.name).write_bytes(payload_path.read_bytes())
        identity = {
            "installed_package": package_identity,
            "bng3_distribution_version": importlib.metadata.version("bionetgen"),
            "consumer_revision": actual_revision,
            "bngl_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
            "crn_artifact": str(output / crn_path.name),
            "network_data_artifact": str(output / payload_path.name),
            "consumer_stdout": consumed.stdout.strip(),
        }
        (output / "identity.json").write_text(
            json.dumps(identity, indent=2) + "\n", encoding="utf-8"
        )
