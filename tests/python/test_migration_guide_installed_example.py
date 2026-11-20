"""Execute the migration guide's examples against the installed BNG3 package.

The guide is the source of truth: this test extracts the BNGL fixture and the
Python example from the ``### Parameter Scans`` section of
``docs/migration_guide.md`` and executes them verbatim.  Editing the published
example therefore changes what this test runs.  The two requested rates are
checked against the unimolecular-decay law ``A(t) = A0 exp(-k t)``, including
which endpoint belongs to which rate.

The wheel CI job runs this file against the installed package, so it also
records the resolved Python/native module locations when
``BNG3_MIGRATION_ARTIFACT_DIR`` is set.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig

import numpy as np
import pytest

import bionetgen

_ROOT = Path(__file__).resolve().parents[2]
_GUIDE = _ROOT / "docs" / "migration_guide.md"


def _guide_section(heading: str) -> str:
    text = _GUIDE.read_text(encoding="utf-8")
    section = re.search(
        rf"^### {re.escape(heading)}\n(.*?)(?=^##(?:#)? |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert section is not None, f"{_GUIDE.name} has no section {heading!r}"
    return section.group(1)


def _fenced_code(section: str, language: str) -> str:
    matches = re.findall(rf"```{re.escape(language)}\n(.*?)```", section, re.DOTALL)
    assert matches, f"{_GUIDE.name} section has no {language!r} fenced block"
    return matches[-1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _record_artifact(
    scan, rates: np.ndarray, endpoints: np.ndarray, expected: np.ndarray
) -> None:
    destination = os.environ.get("BNG3_MIGRATION_ARTIFACT_DIR")
    if not destination:
        return
    import bionetgen._bionetgen_cpp as native

    out_dir = Path(destination)
    out_dir.mkdir(parents=True, exist_ok=True)
    package_file = Path(bionetgen.__file__).resolve()
    native_file = Path(native.__file__).resolve()
    payload = {
        "guide": str(_GUIDE.relative_to(_ROOT)),
        "python_executable": sys.executable,
        "distribution_version": importlib.metadata.version("bionetgen"),
        "package_file": str(package_file),
        "package_sha256": _sha256(package_file),
        "native_module": str(native_file),
        "native_sha256": _sha256(native_file),
        "parameter_name": scan.parameter_name,
        "parameter_values": rates.tolist(),
        "endpoints": endpoints.tolist(),
        "expected_endpoints": expected.tolist(),
        "expected_law": "A0 * exp(-k * t_end), A0=100, t_end=2.0",
        "rtol": 1e-6,
    }
    (out_dir / "migration_installed_example.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def test_migration_guide_parameter_scan_example(tmp_path: Path, monkeypatch):
    """The guide's two-rate decay scan must run and keep values with rates."""
    section = _guide_section("Parameter Scans")
    model_text = _fenced_code(section, "bngl")
    example_text = _fenced_code(section, "python")

    model_path = tmp_path / "model.bngl"
    model_path.write_text(model_text, encoding="utf-8")

    # The example uses the guide's literal ``model.bngl`` file name.
    monkeypatch.chdir(tmp_path)
    namespace: dict[str, object] = {"__name__": "__migration_guide_example__"}
    exec(compile(example_text, str(_GUIDE), "exec"), namespace)
    scan = namespace["scan"]

    # Public API contract: ScanResult, named parameter, values in request order.
    assert isinstance(scan, bionetgen.ScanResult)
    assert scan.parameter_name == "k"
    rates = np.asarray(scan.parameter_values, dtype=float)
    expected_rates = np.array([0.1, 1.0])
    assert rates.shape == expected_rates.shape
    assert np.allclose(rates, expected_rates, rtol=1e-12, atol=0.0)
    assert len(scan.results) == len(expected_rates)

    # Independent source law: dA/dt = -k A, A(0)=100 -> A(t)=100 exp(-k t).
    # Assert each endpoint against the rate at the same scan index, not just
    # against the unordered pair of expected values.
    initial = 100.0
    t_end = 2.0
    endpoints = np.asarray(scan.final("A_total"), dtype=float)
    expected = initial * np.exp(-expected_rates * t_end)
    assert endpoints.shape == expected.shape
    assert np.allclose(endpoints, expected, rtol=1e-6, atol=1e-9)
    assert endpoints[0] == pytest.approx(100.0 * np.exp(-0.2), rel=1e-6)
    assert endpoints[1] == pytest.approx(100.0 * np.exp(-2.0), rel=1e-6)
    assert endpoints[0] > endpoints[1]

    # Same law away from the endpoint, interpolating each scan result at t=1.
    midpoints = np.asarray(scan.at_time(1.0, "A_total"), dtype=float)
    assert np.allclose(
        midpoints, initial * np.exp(-expected_rates * 1.0), rtol=1e-6, atol=1e-9
    )

    _record_artifact(scan, rates, endpoints, expected)


@pytest.fixture
def guide_model(tmp_path: Path, monkeypatch):
    source = _fenced_code(_guide_section("Parameter Scans"), "bngl")
    (tmp_path / "model.bngl").write_text(source, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run_example(heading: str) -> dict:
    example = _fenced_code(_guide_section(heading), "python")
    namespace = {"__name__": "__migration_guide_example__"}
    exec(compile(example, str(_GUIDE), "exec"), namespace)
    return namespace


def test_guide_loading_simulation_and_results(guide_model):
    assert _run_example("Load A Model")["model"].parameters[0].name == "k"
    for heading in ("Run A Simulation", "Inspect Results"):
        result = _run_example(heading)["result"]
        assert result.time[-1] == 2.0
        expected = 100.0 * np.exp(-0.1 * result.time)
        np.testing.assert_allclose(result.observables["A_total"], expected, rtol=1e-6)
    assert list(result.to_dataframe().columns) == ["time", "A_total"]


def test_guide_sensitivity_and_parameter_access(guide_model):
    values = _run_example("Access Parameters")["values"]
    assert values == {"k": 0.1}
    sensitivity = _run_example("Sensitivity Analysis")["sensitivity"]
    assert sensitivity.parameter_names == ["k"]
    assert sensitivity.observable_names == ["A_total"]
    # d(log A(2))/d(log k) = -k * 2 for the documented decay.
    assert sensitivity.matrix[0, 0] == pytest.approx(-0.2, rel=1e-4)


def test_guide_network_free_and_builder(guide_model):
    result = _run_example("Run Network-Free")["result"]
    trajectory = np.asarray(result.observables["A_total"])
    assert result.time[-1] == 2.0
    assert trajectory[0] == 100 and 0 <= trajectory[-1] < 100
    assert np.all(np.diff(trajectory) <= 0)
    model = _run_example("Programmatic Model Building")["model"]
    assert len(model.reaction_rules) == 2
    result = model.simulate(method="ode", t_end=2.0, n_steps=2)
    assert result.observables["AB"][0] == 0
    assert 0 < result.observables["AB"][-1] < 100


def test_guide_sbml_export_and_import(guide_model):
    import libsbml

    _run_example("SBML Export")
    document = libsbml.readSBML(str(guide_model / "model.xml"))
    assert document.getNumErrors(libsbml.LIBSBML_SEV_ERROR) == 0
    assert document.getModel().getNumReactions() == 1
    result = _run_example("SBML Import")["result"]
    assert result.time[-1] == 2.0
    concentration = result.concentrations[:, 0]
    np.testing.assert_allclose(
        concentration, 100 * np.exp(-0.1 * result.time), rtol=1e-6
    )


def test_guide_command_line_examples(guide_model):
    executable = shutil.which("bionetgen", path=sysconfig.get_path("scripts"))
    assert executable is not None, "expected installed bionetgen console entry"
    commands = _fenced_code(_guide_section("Command Line"), "bash").splitlines()
    result = None
    for command in commands:
        if not command.strip():
            continue
        program, *args = shlex.split(command)
        assert program == "bionetgen"
        result = subprocess.run(
            [executable, *args], check=True, capture_output=True, text=True
        )
    assert result is not None and "Exported" in result.stdout
    table = np.genfromtxt(guide_model / "decay.tsv", names=True, delimiter="\t")
    assert table["time"][-1] == 2.0
    np.testing.assert_allclose(
        table["A_total"], 100 * np.exp(-0.1 * table["time"]), rtol=1e-6
    )
    assert (guide_model / "decay.net").is_file()
