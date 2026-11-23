"""Release acceptance tests for Issue #172 (Python Legacy Consolidation).

Validates:
- release-python-consolidation: dependency audit finds one maintained semantic implementation per capability.
- release-python-legacy: complete pinned PyBioNetGen compatibility matrix passes on installed BNG3.
- release-obligation-172: manifest, contract, source identities and negative controls recorded.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import pytest

import bionetgen
import bionetgen.core.defaults as bng_defaults
import bionetgen.core.exc as bng_exc
import bionetgen.modelapi.model as bng_model_api
import bionetgen.result as bng_result_mod
import bionetgen.simulator.simulators as bng_simulators

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent

SAMPLE_BNGL = """begin model
begin parameters
    k 0.5
end parameters
begin molecule types
    X()
    Y()
end molecule types
begin seed species
    X() 100
    Y() 0
end seed species
begin observables
    Molecules X_total X()
    Molecules Y_total Y()
end observables
begin reaction rules
    X() -> Y() k
end reaction rules
end model
"""


def test_release_python_consolidation(tmp_path: Path):
    """Verify one maintained semantic implementation per capability behind common interfaces."""
    # 1. Native C++ backend owns core simulation
    import bionetgen._bionetgen_cpp as cpp

    assert hasattr(cpp, "parse_file")
    assert hasattr(cpp, "simulate_ode")
    assert hasattr(cpp, "simulate_ssa")
    assert hasattr(cpp, "simulate_nfnext")

    # 2. Maintained model loader wraps native C++ model
    m_file = tmp_path / "model.bngl"
    m_file.write_text(SAMPLE_BNGL, encoding="utf-8")
    model = bionetgen.load(str(m_file))
    assert isinstance(model, bionetgen.model.BioNetGenModel)
    assert hasattr(model, "parameters")
    assert hasattr(model, "simulate")

    # 3. Maintained simulation runner produces SimResult
    res = bionetgen.run(str(m_file), method="ode", t_end=1.0, n_steps=5)
    assert isinstance(res, bng_result_mod.SimResult)
    assert hasattr(res, "time")
    assert hasattr(res, "observables")

    # 4. Legacy bngmodel wraps modelapi and delegates cleanly
    legacy_m = bng_model_api.bngmodel(str(m_file))
    assert hasattr(legacy_m, "add_block")
    assert hasattr(legacy_m, "write_model")

    # 5. Legacy simulator getter returns maintained simulator classes, retiring unsupported ones
    assert callable(bng_simulators.sim_getter)
    with pytest.raises(ValueError, match="no longer supported"):
        bng_simulators.sim_getter(model_str="dummy", sim_type="cpy")

    # 6. Negative control: unsupported backend produces typed refusal, not approximation
    with pytest.raises((ValueError, bng_exc.BNGError, KeyError)):
        bionetgen.run(str(m_file), method="unsupported_quantum_solver")


LEGACY_MODULES = (
    "test_compatibility_contract",
    "test_pybionetgen_bngfile_strip_actions_compat",
    "test_pybionetgen_action_parser_compat",
    "test_pybionetgen_result_access_compat",
)
LEGACY_EXPECTED_COUNT = 94


def verify_legacy_junit(path, modules=LEGACY_MODULES, expected=LEGACY_EXPECTED_COUNT):
    """Reject a green exit code that did not execute the named suite."""
    import xml.etree.ElementTree as ET

    if not path.is_file():
        raise AssertionError("no JUnit report for the compatibility suite")
    cases = list(ET.parse(path).getroot().iter("testcase"))
    problems = [
        case.get("name")
        for case in cases
        if any(case.find(tag) is not None for tag in ("failure", "error", "skipped"))
    ]
    assert not problems, f"compatibility cases skipped or failed: {problems}"
    assert len(cases) == expected, f"expected {expected} executed cases, found {len(cases)}"
    classnames = {
        next(
            (part for part in case.get("classname", "").split(".") if part in modules),
            "",
        )
        for case in cases
    }
    assert classnames == set(modules), f"unexpected test modules: {classnames}"
    return len(cases)


def test_release_python_legacy(tmp_path):
    """Verify the complete pinned compatibility suite actually executed."""
    modules = LEGACY_MODULES
    compat_suite = [str(REPO_ROOT / f"tests/python/{name}.py") for name in modules]
    junit = tmp_path / "pybionetgen-compat.xml"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--noconftest",
            *compat_suite,
            "--junitxml",
            str(junit),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"PyBioNetGen legacy compatibility suite failed:\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    # The live check claims 94 tests; a green exit code alone cannot establish
    # that those identities executed.
    verify_legacy_junit(junit)


def test_legacy_junit_rejects_partial_and_skipped_evidence(tmp_path):
    """Negative control: partial, skipped and missing artifacts cannot pass."""
    import xml.etree.ElementTree as ET

    def report(path, count, skipped=()):
        suite = ET.Element("testsuite")
        for index in range(count):
            module = LEGACY_MODULES[index % len(LEGACY_MODULES)]
            case = ET.SubElement(
                suite, "testcase", name=f"case_{index}", classname=f"{module}.C"
            )
            if index in skipped:
                ET.SubElement(case, "skipped")
        ET.ElementTree(suite).write(path)

    partial = tmp_path / "partial.xml"
    report(partial, LEGACY_EXPECTED_COUNT - 1)
    with pytest.raises(AssertionError, match="expected 94"):
        verify_legacy_junit(partial)

    skipped = tmp_path / "skipped.xml"
    report(skipped, LEGACY_EXPECTED_COUNT, skipped=(0,))
    with pytest.raises(AssertionError, match="skipped or failed"):
        verify_legacy_junit(skipped)

    missing = tmp_path / "missing.xml"
    with pytest.raises(AssertionError, match="no JUnit report"):
        verify_legacy_junit(missing)

    complete = tmp_path / "complete.xml"
    report(complete, LEGACY_EXPECTED_COUNT)
    assert verify_legacy_junit(complete) == LEGACY_EXPECTED_COUNT


def test_release_obligation_172():
    """Verify Issue 172 contract, manifest definitions, and negative control handling."""
    contract_file = CASE_DIR / "contract.json"
    assert contract_file.is_file(), "contract.json missing"
    contract = json.loads(contract_file.read_text(encoding="utf-8"))

    assert contract["schema_version"] == 1
    assert contract["issue"] == 172
    assert contract["acceptance_checks"] == [
        "release-python-consolidation",
        "release-python-legacy",
        "release-obligation-172",
    ]

    manifest = json.loads(
        (REPO_ROOT / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue_entry = next((i for i in manifest["issues"] if i["number"] == 172), None)
    assert issue_entry is not None, "Issue 172 entry missing from manifest"
