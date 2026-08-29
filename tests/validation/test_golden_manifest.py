"""Contract tests for provenance-complete golden bundle manifests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import validate_golden_manifest as validator

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "validate_golden_manifest.py"


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, dict]:
    (tmp_path / "provenance" / "corpus").mkdir(parents=True)
    (tmp_path / "models").mkdir()
    (tmp_path / "golden").mkdir()
    model_path = tmp_path / "models" / "simple.bngl"
    model_path.write_text("begin model\nend model\n", encoding="utf-8")
    output_path = tmp_path / "golden" / "simple.net"
    output_path.write_text("golden network\n", encoding="utf-8")

    lock = {
        "schema_version": 1,
        "baseline": {
            "date": "2026-08-28",
            "status": "pending-maintainer-approval",
            "approved_by": None,
            "approved_at": None,
            "notes": [],
        },
        "sources": {
            "bionetgen": {
                "repository": "https://github.com/RuleWorld/bionetgen.git",
                "branch": "master",
                "revision": "a" * 40,
                "role": "oracle",
                "status": "observed",
                "evidence": {"kind": "planning-snapshot", "checked_at": "2026-08-28"},
            },
            "nfsim": {
                "repository": "https://github.com/RuleWorld/NFsim.git",
                "branch": "master",
                "revision": "b" * 40,
                "role": "oracle",
                "status": "observed",
                "evidence": {"kind": "planning-snapshot", "checked_at": "2026-08-28"},
            },
            "rulehub": {
                "repository": "https://github.com/RuleWorld/RuleHub.git",
                "branch": "master",
                "revision": "c" * 40,
                "role": "corpus",
                "status": "observed",
                "evidence": {"kind": "planning-snapshot", "checked_at": "2026-08-28"},
            },
        },
        "oracles": {
            "bng2": {
                "source": "bionetgen",
                "status": "pending",
                "build_recipe": None,
                "artifact_digest": None,
            },
            "nfsim": {
                "source": "nfsim",
                "status": "pending",
                "build_recipe": None,
                "artifact_digest": None,
            },
        },
        "dependencies": {
            "compiler_images": {"status": "pending", "images": []},
            "python_lock": {"status": "pending", "path": None, "digest": None},
        },
    }
    lock_path = tmp_path / "provenance" / "upstreams.lock.yml"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    selection = {
        "schema_version": 1,
        "selection_status": "pending-maintainer-approval",
        "source_lock": {
            "path": "provenance/upstreams.lock.yml",
            "sha256": _sha(lock_path),
        },
        "rulehub": {
            "repository": "https://github.com/RuleWorld/RuleHub.git",
            "revision": "c" * 40,
            "status": "observed",
            "policy": "fixture",
        },
        "tiers": {
            tier: ["simple"] if tier == "s" else []
            for tier in ("s", "p", "nf", "expr", "x", "b")
        },
        "records": [
            {
                "id": "simple",
                "path": "models/simple.bngl",
                "sha256": _sha(model_path),
                "origin": "repository-fixture",
                "tiers": ["s"],
            }
        ],
        "notes": [],
    }
    selection_path = tmp_path / "provenance" / "corpus" / "selection.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")

    manifest = {
        "$schema": "schemas/golden-manifest.schema.json",
        "schema_version": 1,
        "bundle_id": "sha256:" + "1" * 64,
        "status": "candidate",
        "generated_at": "2026-08-28T12:00:00Z",
        "source_lock": {
            "path": "provenance/upstreams.lock.yml",
            "sha256": _sha(lock_path),
        },
        "models": [
            {"id": "simple", "path": "models/simple.bngl", "sha256": _sha(model_path)}
        ],
        "corpus": {
            "selection_manifest": {
                "path": "provenance/corpus/selection.json",
                "sha256": _sha(selection_path),
            },
            "rulehub": {
                "repository": "https://github.com/RuleWorld/RuleHub.git",
                "revision": "c" * 40,
            },
        },
        "oracle": {
            "name": "bng2",
            "source": "bionetgen",
            "repository": "https://github.com/RuleWorld/bionetgen.git",
            "revision": "a" * 40,
            "build_recipe": "perl legacy/perl/BNG2.pl",
            "artifact_digest": "sha256:" + "2" * 64,
        },
        "build": {
            "compiler": "clang",
            "compiler_version": "18.1.8",
            "flags": ["-O2"],
            "dependencies": ["n/a"],
            "platform": "darwin-arm64",
            "container_image": "ghcr.io/example/bng3@sha256:" + "3" * 64,
        },
        "execution": {
            "command": ["perl", "legacy/perl/BNG2.pl", "models/simple.bngl"],
            "method": "network",
            "seeds": [],
            "time_grid": [0.0, 1.0],
            "tolerances": {"absolute": 1e-12, "relative": 1e-9},
            "comparator_version": "bng3-compare-v1",
        },
        "outputs": [
            {
                "path": "golden/simple.net",
                "model_id": "simple",
                "kind": "net",
                "sha256": _sha(output_path),
            }
        ],
        "notes": [],
    }
    return tmp_path / "manifest.json", manifest


def _write_fixture(tmp_path: Path) -> Path:
    path, manifest = _fixture(tmp_path)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


@pytest.mark.smoke
def test_candidate_manifest_validates_all_bytes(tmp_path):
    manifest_path = _write_fixture(tmp_path)
    document = validator.load(manifest_path)
    assert validator.validate(document, repo_root=tmp_path) == []


def test_output_digest_and_path_traversal_are_rejected(tmp_path):
    manifest_path = _write_fixture(tmp_path)
    document = validator.load(manifest_path)
    document["outputs"][0]["sha256"] = "sha256:" + "0" * 64
    document["models"][0]["path"] = "../outside.bngl"
    errors = validator.validate(document, repo_root=tmp_path)
    assert "outputs[0].sha256 does not match the output" in errors
    assert "models[0].path must name a repository-relative file" in errors


def test_approved_manifest_requires_locked_source_and_oracle(tmp_path):
    manifest_path = _write_fixture(tmp_path)
    document = validator.load(manifest_path)
    document["status"] = "approved"
    errors = validator.validate(document, repo_root=tmp_path)
    assert "approved bundle requires a locked oracle" in errors
    assert "approved bundle requires an approved source-lock baseline" in errors
    assert "approved bundle requires locked compiler images" in errors


def test_stochastic_manifest_requires_seed(tmp_path):
    manifest_path = _write_fixture(tmp_path)
    document = validator.load(manifest_path)
    document["execution"]["method"] = "ssa"
    errors = validator.validate(document, repo_root=tmp_path)
    assert "stochastic execution requires at least one seed" in errors


def test_malformed_nested_types_return_diagnostics_not_tracebacks(tmp_path):
    manifest_path = _write_fixture(tmp_path)
    document = validator.load(manifest_path)
    document["execution"]["seeds"] = [{}]
    document["outputs"][0]["model_id"] = []
    errors = validator.validate(document, repo_root=tmp_path)
    assert "execution.seeds must be a unique array of non-negative integers" in errors
    assert "outputs[0].model_id references an unknown model" in errors


def test_cli_reports_malformed_manifest_without_traceback(tmp_path):
    manifest_path = _write_fixture(tmp_path)
    document = validator.load(manifest_path)
    document["outputs"][0]["sha256"] = "not-a-digest"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "outputs[0].sha256 must be a sha256 digest" in result.stderr
    assert "Traceback" not in result.stderr
