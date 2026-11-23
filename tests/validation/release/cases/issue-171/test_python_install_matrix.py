"""Installed-artifact evidence for Issue #171 release-python-install.

Builds a wheel and an sdist from this checkout, installs each into a fresh
virtual environment, and exercises the public API and CLI in every installed
environment.  Optional extras are installed and checked in their own isolated
environments; an extra is never allowed to qualify another one.

The generated JSON report is consumed by the #171 recorder.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
DIST_DIR = Path(
    os.environ.get(
        "BNG3_DIST_DIR", "/tmp/bng3-own-issues-154-155-156-171/.release-dist"
    )
)
EXTRAS = ("legacy", "plotting", "jax", "notebook", "full", "dev")
SELECTED_EXTRAS = tuple(
    part for part in os.environ.get("BNG3_INSTALL_EXTRAS", ",".join(EXTRAS)).split(",") if part
)
SMOKE = (
    "import bionetgen, importlib.metadata as m; "
    "assert bionetgen.__version__ == m.version('bionetgen') == '3.0.0a1'; "
    "assert hasattr(bionetgen, 'load') and hasattr(bionetgen, 'run'); "
    "assert hasattr(bionetgen, 'BioNetGenModel')"
)


def _run(cmd, *, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _build(outdir: Path) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    use_isolation = os.environ.get("BNG3_BUILD_ISOLATION", "0") != "0"
    cmd = [sys.executable, "-m", "build", "--outdir", str(outdir)]
    if not use_isolation:
        cmd.append("--no-isolation")
    result = _run(cmd, cwd=REPO_ROOT)
    assert result.returncode == 0, f"distribution build failed:\n{result.stderr[-4000:]}"
    wheel = next(outdir.glob("*.whl"), None)
    sdist = next(outdir.glob("*.tar.gz"), None)
    assert wheel is not None and sdist is not None, "wheel and sdist must both be built"
    return {"wheel": str(wheel), "sdist": str(sdist)}


def _fresh_env(path: Path) -> Path:
    builder = venv.EnvBuilder(with_pip=True)
    builder.create(path)
    binary = path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    assert binary.is_file(), f"venv interpreter missing at {binary}"
    return binary


def _install(binary: Path, target: str) -> None:
    result = _run([str(binary), "-m", "pip", "install", "-q", target])
    assert result.returncode == 0, f"install of {target} failed:\n{result.stderr[-4000:]}"


def _verify(binary: Path, extra: str | None = None) -> dict:
    result = _run([str(binary), "-c", SMOKE])
    assert result.returncode == 0, f"API smoke failed for {extra or 'base'}:\n{result.stderr}"
    cli = _run([str(binary), "-m", "bionetgen.cli", "--version"])
    assert cli.returncode == 0, f"CLI smoke failed for {extra or 'base'}:\n{cli.stderr}"
    version = _run(
        [str(binary), "-c", "import importlib.metadata as m;print(m.version('bionetgen'))"]
    )
    return {
        "extra": extra or "base",
        "api": "PASS",
        "cli": "PASS",
        "version": version.stdout.strip(),
        "python": str(binary),
    }


@pytest.fixture(scope="module")
def install_report(tmp_path_factory):
    root = tmp_path_factory.mktemp("issue171-install")
    artifacts = _build(root / "dist")
    rows = []

    for kind in ("wheel", "sdist"):
        binary = _fresh_env(root / f"venv-{kind}")
        _install(binary, artifacts[kind])
        rows.append(_verify(binary) | {"artifact": kind})

    for extra in SELECTED_EXTRAS:
        binary = _fresh_env(root / f"venv-extra-{extra}")
        _install(binary, f"{artifacts['wheel']}[{extra}]")
        rows.append(_verify(binary, extra=extra) | {"artifact": f"wheel[{extra}]"})

    report = {
        "schema_version": 1,
        "acceptance_check": "release-python-install",
        "artifacts": artifacts,
        "selected_extras": list(SELECTED_EXTRAS),
        "declared_extras": list(EXTRAS),
        "rows": rows,
    }
    out = root / "python-install-report.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    report["report_path"] = str(out)
    return report


def test_wheel_and_sdist_install_in_fresh_environments(install_report):
    kinds = {row["artifact"] for row in install_report["rows"]}
    assert {"wheel", "sdist"} <= kinds
    for row in install_report["rows"]:
        assert row["api"] == "PASS" and row["cli"] == "PASS"
        assert row["version"] == "3.0.0a1"


def test_required_extras_are_tested_separately(install_report):
    extra_rows = {
        row["extra"] for row in install_report["rows"] if row["artifact"].startswith("wheel[")
    }
    assert set(install_report["selected_extras"]) == extra_rows
    assert all(
        row["python"] != other["python"]
        for i, row in enumerate(install_report["rows"])
        for other in install_report["rows"][i + 1 :]
    ), "every distribution/extra must use its own fresh environment"
