"""The release-candidate qualification of the single-host arms (#184).

The family has to refuse the regressions it exists for: a packaged artefact
that stops carrying the licence or the notices, a notice that is removed from
a bundled source, a shipped artefact that carries sanitizer instrumentation
or an embedded C++ runtime, and a hosted arm that does not say what it has to
produce.  These tests therefore mutate a copy of the tree instead of
asserting only that the current tree passes.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.validation import release_candidate as release

ROOT = Path(__file__).resolve().parents[2]


def _tree_copy(tmp_path: Path) -> Path:
    """A copy of the files the release-candidate checks read."""
    root = tmp_path / "tree"
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "provenance").mkdir(parents=True)
    for relative in (
        "LICENSE",
        "NOTICE",
        "CMakeLists.txt",
        "pyproject.toml",
        "provenance/third-party-notices.json",
        ".github/workflows/release.yml",
        ".github/workflows/ci.yml",
        "cpp/nauty/nauty.h",
        "cpp/nfsim/LICENSE.txt",
    ):
        source = ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return root


def test_the_check_identities_are_declared_independently_of_execution():
    ids = release.check_ids()

    assert ids == [
        "release-candidate:license-inventory",
        "release-candidate:notice-inventory",
        "release-candidate:memory-contract",
        "release-candidate:sanitizer-configuration",
        "release-candidate:platform-matrix-shape",
        "release-candidate:hosted-evidence",
        "qualification:issue:184:verify-final-candidate-platform-sanitizer-memory-licenses-notice",
    ]
    assert len(ids) == len(set(ids))


def test_the_fetched_dependencies_are_derived_from_the_build():
    dependencies = {entry["name"]: entry for entry in release.fetched_dependencies()}

    # The test-only dependency is fetched as well; the check filters it out.
    assert set(dependencies) == {"Catch2", "antlr4_runtime", "sundials", "pybind11"}
    assert dependencies["antlr4_runtime"]["revision"] == "4.13.2"
    assert dependencies["sundials"]["revision"] == "v7.6.0"
    assert dependencies["pybind11"]["revision"] == "v2.13.6"


def test_the_current_tree_satisfies_every_single_host_arm():
    assert release.licence_differences() == []
    assert release.notice_differences() == []
    assert release.memory_contract_differences() == []
    assert release.sanitizer_differences() == []
    assert release.platform_matrix_differences() == []


def test_a_packaged_artefact_that_drops_the_licence_is_refused(tmp_path):
    root = _tree_copy(tmp_path)
    workflow = root / ".github" / "workflows" / "release.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "cp LICENSE NOTICE", "cp README.md"
        ),
        encoding="utf-8",
    )

    differences = release.licence_differences(root)

    assert any(item["field"] == "licence.packaging" for item in differences)


def test_a_packaged_artefact_that_drops_the_notices_is_refused(tmp_path):
    root = _tree_copy(tmp_path)
    workflow = root / ".github" / "workflows" / "release.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace("cp LICENSE NOTICE", "cp LICENSE"),
        encoding="utf-8",
    )

    differences = release.notice_differences(root)

    assert any(item["field"] == "notices.packaging" for item in differences)


def test_a_removed_notice_is_refused(tmp_path):
    root = _tree_copy(tmp_path)
    bundled = root / "cpp" / "nfsim" / "LICENSE.txt"
    bundled.write_text("the notice was removed\n", encoding="utf-8")

    differences = release.notice_differences(root)

    assert any(item["field"] == "notices.removed" for item in differences)


def test_an_uninventoried_fetched_dependency_is_refused(tmp_path):
    root = _tree_copy(tmp_path)
    inventory = json.loads(
        (root / "provenance" / "third-party-notices.json").read_text(encoding="utf-8")
    )
    inventory["components"] = [
        entry for entry in inventory["components"] if entry["id"] != "sundials"
    ]
    (root / "provenance" / "third-party-notices.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )

    differences = release.notice_differences(root)

    assert any(item["field"] == "notices.uninventoried" for item in differences)


def test_a_stale_recorded_revision_is_refused(tmp_path):
    root = _tree_copy(tmp_path)
    inventory = json.loads(
        (root / "provenance" / "third-party-notices.json").read_text(encoding="utf-8")
    )
    for entry in inventory["components"]:
        if entry["id"] == "antlr4-runtime":
            entry["revision"] = "4.0.0"
    (root / "provenance" / "third-party-notices.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )

    differences = release.notice_differences(root)

    assert any(item["field"] == "notices.stale-revision" for item in differences)


def test_a_shipped_artefact_with_sanitizer_instrumentation_is_refused(tmp_path):
    root = _tree_copy(tmp_path)
    workflow = root / ".github" / "workflows" / "release.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "-DCMAKE_BUILD_TYPE=Release",
            '-DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="-fsanitize=address"',
        ),
        encoding="utf-8",
    )

    differences = release.memory_contract_differences(root)

    assert any(item["field"] == "memory.sanitizer-in-release" for item in differences)


def test_a_shipped_extension_with_an_embedded_runtime_is_refused(tmp_path):
    root = _tree_copy(tmp_path)
    workflow = root / ".github" / "workflows" / "release.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "-DBUILD_TESTS=OFF",
            "-DBUILD_TESTS=OFF -DCMAKE_SHARED_LINKER_FLAGS=-static-libstdc++",
        ),
        encoding="utf-8",
    )

    differences = release.memory_contract_differences(root)

    assert any(item["field"] == "memory.static-runtime" for item in differences)


def test_a_ci_lane_without_a_sanitizer_job_is_refused(tmp_path):
    root = _tree_copy(tmp_path)
    workflow = root / ".github" / "workflows" / "ci.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "-fsanitize=address", "-fno-inline"
        ),
        encoding="utf-8",
    )

    differences = release.sanitizer_differences(root)

    assert any(item["field"] == "sanitizer.job" for item in differences)


def test_a_platform_matrix_that_disagrees_is_refused(tmp_path):
    root = _tree_copy(tmp_path)
    workflow = root / ".github" / "workflows" / "release.yml"
    text = workflow.read_text(encoding="utf-8")
    # The wheel matrix declares one platform less than the binary matrix.
    text = text.replace(
        '          - os: windows-2022\n            macos_arch: x86_64\n            macos_deployment_target: "11.0"\n',
        "",
    )
    workflow.write_text(text, encoding="utf-8")

    differences = release.platform_matrix_differences(root)

    assert any(item["field"] == "matrix.agreement" for item in differences)


def test_the_hosted_arms_name_their_command_and_their_artefact():
    arms = release.hosted_arms()

    assert arms
    for arm in arms:
        assert arm["command"].strip()
        assert arm["artifact"].strip()
        assert arm["owner"] == release.HOSTED_OWNER
        # The arms are evidence to collect: nothing here claims that one ran.
        assert arm["status"] == "PENDING"


def test_the_hosted_arms_cover_every_release_platform():
    arms = release.hosted_arms()
    covered = {arm["platform"] for arm in arms}

    assert "ubuntu-22.04" in covered
    assert "macos-14" in covered
    assert "windows-2022" in covered
    assert release.hosted_evidence_differences(arms) == []


def test_an_arm_without_an_artefact_is_refused():
    arms = [
        dict(
            arm="release-binary-ubuntu-22.04",
            platform="ubuntu-22.04",
            command="x",
            artifact="",
            owner="x",
        )
    ]

    differences = release.hosted_evidence_differences(arms)

    assert any(item["field"] == "hosted.arm" for item in differences)


def test_the_family_reports_every_named_check(tmp_path):
    rows = release.run_worker(tmp_path)

    assert [row["id"] for row in rows] == release.check_ids()
    for row in rows:
        assert row["status"] == "PASS", (row["id"], row["detail"])
        assert row["evidence_kind"] == "supported-execution"
        assert row["supported_execution"] is True


def test_the_hosted_evidence_is_written_as_an_artefact(tmp_path):
    release.run_worker(tmp_path)

    document = json.loads(
        (tmp_path / "hosted-evidence.json").read_text(encoding="utf-8")
    )

    assert document["owner"] == release.HOSTED_OWNER
    assert document["arms"]
    for arm in document["arms"]:
        assert arm["status"] == "PENDING"
        assert arm["command"]
        assert arm["artifact"]
