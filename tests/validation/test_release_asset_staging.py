"""Release staging must fail closed on duplicate asset basenames.

These tests execute the ``run:`` bodies taken directly from
``.github/workflows/release.yml``. They deliberately do not reimplement the
guards in Python: if a guard is removed from the workflow, or the PyPI download
is changed back to ``merge-multiple: true``, these tests fail without edits.

Two staging paths are covered:

* ``release`` / "Organize release assets" -> files uploaded to the GitHub Release.
* ``publish-pypi`` / "Flatten dist directory" -> files uploaded to PyPI.

The PyPI path additionally requires the download step to keep every artifact in
its own directory; otherwise a duplicate basename is overwritten *during*
download, before the flattening guard can observe both files.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.workflow_yaml import parse_workflow

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

WHEEL = "bionetgen-3.0.0a1-py3-none-any.whl"
SDIST = "bionetgen-3.0.0a1.tar.gz"
CLI = "bionetgen-linux-x86_64.tar.gz"


def _step(name: str) -> dict:
    workflow = parse_workflow(WORKFLOW)
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if step.get("name") == name:
                return step
    raise AssertionError(f"{WORKFLOW.name} has no step named {name!r}")


def _run_step(tmp_path: Path, name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", _step(name)["run"]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def _write(root: Path, relative: str, payload: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return path


def _release_artifacts(root: Path, *, collision: bool) -> None:
    """Lay out what ``actions/download-artifact@v4`` produces in ``artifacts/``."""
    _write(root, f"artifacts/bionetgen-linux-x86_64/{CLI}", "linux-cli-bytes")
    _write(root, f"artifacts/sdist/{SDIST}", "sdist-bytes")
    _write(root, f"artifacts/wheels-ubuntu-22.04/{WHEEL}", "ubuntu-wheel-bytes")
    _write(
        root,
        f"artifacts/wheels-macos-15/{WHEEL}",
        "other-wheel-bytes" if collision else "ubuntu-wheel-bytes",
    )


def _pypi_artifacts(root: Path, *, collision: bool) -> None:
    """Lay out the per-artifact directories the download step must preserve."""
    _write(root, f"dist/wheels-ubuntu-22.04/{WHEEL}", "ubuntu-wheel-bytes")
    _write(
        root,
        f"dist/wheels-macos-15/{WHEEL}",
        "other-wheel-bytes" if collision else "ubuntu-wheel-bytes",
    )
    _write(root, f"dist/sdist/{SDIST}", "sdist-bytes")


def test_pypi_download_keeps_artifacts_separate_until_guard_runs():
    step = next(
        s
        for s in parse_workflow(WORKFLOW)["jobs"]["publish-pypi"]["steps"]
        if s.get("uses", "").startswith("actions/download-artifact@")
    )
    assert step["with"]["path"] == "dist/"
    assert "wheels" in step["with"]["pattern"] and "sdist" in step["with"]["pattern"]
    # merge-multiple: true collapses every artifact into dist/ at download time,
    # so a colliding basename is gone before the flattening guard can see it.
    assert step["with"].get("merge-multiple", False) is False


def test_github_release_staging_accepts_distinct_basenames(tmp_path):
    _release_artifacts(tmp_path, collision=False)
    result = _run_step(tmp_path, "Organize release assets")
    assert result.returncode == 0, result.stderr
    staged = sorted(p.name for p in (tmp_path / "release-assets").iterdir())
    assert staged == sorted([CLI, SDIST, WHEEL])


def test_github_release_staging_rejects_collision_before_copy(tmp_path):
    _release_artifacts(tmp_path, collision=True)
    result = _run_step(tmp_path, "Organize release assets")
    assert result.returncode != 0
    assert "release asset basename collision" in result.stderr
    assert WHEEL in result.stderr
    assert list((tmp_path / "release-assets").iterdir()) == []


def test_pypi_staging_accepts_distinct_basenames(tmp_path):
    _pypi_artifacts(tmp_path, collision=False)
    result = _run_step(tmp_path, "Flatten dist directory")
    assert result.returncode == 0, result.stderr
    staged = sorted(p.name for p in (tmp_path / "flat-dist").iterdir())
    assert staged == sorted([SDIST, WHEEL])


def test_pypi_staging_rejects_collision_before_flatten(tmp_path):
    _pypi_artifacts(tmp_path, collision=True)
    result = _run_step(tmp_path, "Flatten dist directory")
    assert result.returncode != 0
    assert "PyPI dist basename collision" in result.stderr
    assert WHEEL in result.stderr
    assert not (tmp_path / "flat-dist").exists()


def test_github_release_staging_rejects_missing_cli_archive(tmp_path):
    _release_artifacts(tmp_path, collision=False)
    (tmp_path / f"artifacts/bionetgen-linux-x86_64/{CLI}").unlink()

    result = _run_step(tmp_path, "Organize release assets")

    assert result.returncode != 0
    assert "missing release assets" in result.stderr
    assert list((tmp_path / "release-assets").iterdir()) == []


def test_release_and_pypi_staging_preserve_linux_aarch64_assets(tmp_path):
    cli_arm64 = "bionetgen-linux-aarch64.tar.gz"
    wheel_x64 = "bionetgen-3.0.0a1-cp312-cp312-manylinux_2_28_x86_64.whl"
    wheel_arm64 = "bionetgen-3.0.0a1-cp312-cp312-manylinux_2_28_aarch64.whl"

    _write(tmp_path, f"artifacts/bionetgen-linux-x86_64/{CLI}", "linux-x64-cli")
    _write(tmp_path, f"artifacts/bionetgen-linux-aarch64/{cli_arm64}", "linux-arm-cli")
    _write(tmp_path, f"artifacts/wheels-ubuntu-22.04/{wheel_x64}", "linux-x64-wheel")
    _write(
        tmp_path, f"artifacts/wheels-ubuntu-24.04-arm/{wheel_arm64}", "linux-arm-wheel"
    )
    _write(tmp_path, f"artifacts/sdist/{SDIST}", "sdist-bytes")

    release_result = _run_step(tmp_path, "Organize release assets")
    assert release_result.returncode == 0, release_result.stderr
    staged = sorted(p.name for p in (tmp_path / "release-assets").iterdir())
    assert staged == sorted([CLI, cli_arm64, SDIST, wheel_x64, wheel_arm64])

    _write(tmp_path, f"dist/wheels-ubuntu-22.04/{wheel_x64}", "linux-x64-wheel")
    _write(tmp_path, f"dist/wheels-ubuntu-24.04-arm/{wheel_arm64}", "linux-arm-wheel")
    _write(tmp_path, f"dist/sdist/{SDIST}", "sdist-bytes")

    pypi_result = _run_step(tmp_path, "Flatten dist directory")
    assert pypi_result.returncode == 0, pypi_result.stderr
    flattened = sorted(p.name for p in (tmp_path / "flat-dist").iterdir())
    assert flattened == sorted([SDIST, wheel_x64, wheel_arm64])
