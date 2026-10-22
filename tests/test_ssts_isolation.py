"""Per-case isolation in the official SBML Test Suite gate must not change verdicts.

The gate isolates every case in its own process so a case cannot corrupt the
next one.  The fork isolation mode reaches the same guarantee without paying
an interpreter start per case.  These tests pin the two properties a reviewer
of validation infrastructure has to be able to check: the isolation modes
agree on every verdict, and the shared verification slot serializes full-suite
runs without changing any verdict.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import validate_sbml_test_suite as runner

REPO = Path(__file__).resolve().parents[1]
GATE = REPO / "scripts" / "ci" / "validate_sbml_test_suite.py"

VALID_SBML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model metaid="_case00001" id="case00001" name="case00001" timeUnits="time">
    <listOfCompartments>
      <compartment id="compartment" name="compartment" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" name="S1" compartment="compartment" initialAmount="0.00015" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
      <species id="S2" name="S2" compartment="compartment" initialAmount="0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" name="k1" value="1" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="reaction1" name="reaction1" reversible="false">
        <listOfReactants>
          <speciesReference species="S1" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="S2" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <times/>
              <ci> compartment </ci>
              <ci> k1 </ci>
              <ci> S1 </ci>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""

INVALID_SBML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="case00002" name="case00002">
    <listOfReactions>
      <reaction id="reaction1" reversible="false">
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><plus/><ci> undefined_parameter </ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""


def _locked_ssts_checkout(tmp_path: Path) -> tuple[Path, Path]:
    """Build a clean locked suite checkout with two semantic cases."""

    suite = tmp_path / "suite"
    suite.mkdir()
    subprocess.run(["git", "-C", str(suite), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(suite), "config", "user.name", "SSTS test"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(suite), "config", "user.email", "ssts@example.invalid"],
        check=True,
        capture_output=True,
    )
    (suite / "README.md").write_text("locked suite\n", encoding="utf-8")
    for case_id, body in (("00001", VALID_SBML), ("00002", INVALID_SBML)):
        case_dir = suite / "cases" / "semantic" / case_id
        case_dir.mkdir(parents=True)
        (case_dir / f"{case_id}-sbml-l3v2.xml").write_text(body, encoding="utf-8")
    stochastic_dir = suite / "cases" / "stochastic" / "00001"
    stochastic_dir.mkdir(parents=True)
    (stochastic_dir / "00001-sbml-l3v2.xml").write_text(VALID_SBML, encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(suite), "add", "README.md", "cases"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(suite), "commit", "-m", "initial"],
        check=True,
        capture_output=True,
    )
    revision = subprocess.check_output(
        ["git", "-C", str(suite), "rev-parse", "HEAD"], text=True
    ).strip()
    repository = "https://github.com/sbmlteam/sbml-test-suite.git"
    subprocess.run(
        ["git", "-C", str(suite), "remote", "add", "origin", repository],
        check=True,
        capture_output=True,
    )
    lock = tmp_path / "upstreams.lock.yml"
    lock.write_text(
        json.dumps(
            {
                "sources": {
                    "sbml-test-suite": {
                        "repository": repository,
                        "branch": "3.5.0",
                        "revision": revision,
                        "role": "official-validation-corpus-not-oracle",
                        "status": "observed",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return suite, lock


def _gate_environment() -> dict[str, str]:
    """Return an environment in which the gate measures this checkout.

    The gate refuses to measure a package it cannot trace to the checkout
    that owns it, so a test that runs the gate has to hand it one: the
    checkout's own source tree and its built extension when they exist, and
    otherwise the installed distribution.
    """

    environment = dict(os.environ)
    build_cpp = REPO / "build" / "cpp"
    if any(build_cpp.glob("_bionetgen_cpp*")):
        entries = [str(REPO / "python"), str(build_cpp)]
        existing = environment.get("PYTHONPATH")
        if existing:
            entries.append(existing)
        environment["PYTHONPATH"] = os.pathsep.join(entries)
    return environment


def _run_gate(
    suite: Path,
    lock: Path,
    report: Path,
    mode: str,
    extra: list[str] | None = None,
    categories: list[str] | None = None,
) -> subprocess.CompletedProcess:
    command = [
        sys.executable,
        str(GATE),
        "--suite-dir",
        str(suite),
        "--lock",
        str(lock),
        "--json",
        str(report),
        "--categories",
        *(categories or ["semantic"]),
        "--isolate-cases",
        "--isolation-mode",
        mode,
        "--jobs",
        "2",
        "--case-timeout",
        "60",
        *(extra or []),
    ]
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        env=_gate_environment(),
    )


def _verdicts(report: Path) -> dict[str, dict]:
    document = json.loads(report.read_text(encoding="utf-8"))
    return {
        f"{record['category']}/{record['id']}": record for record in document["records"]
    }


@pytest.mark.skipif(
    not hasattr(os, "fork"), reason="fork isolation requires POSIX fork"
)
def test_fork_and_process_isolation_agree_on_every_verdict(tmp_path):
    """The cheap isolation mode must not change a single verdict."""

    pytest.importorskip("bionetgen._bionetgen_cpp")
    suite, lock = _locked_ssts_checkout(tmp_path)
    fork_report = tmp_path / "fork.json"
    process_report = tmp_path / "process.json"

    fork = _run_gate(suite, lock, fork_report, "fork", ["--no-lock"])
    process = _run_gate(suite, lock, process_report, "process", ["--no-lock"])

    assert fork.returncode == process.returncode, fork.stderr + process.stderr
    assert fork_report.is_file() and process_report.is_file()
    fork_verdicts = _verdicts(fork_report)
    process_verdicts = _verdicts(process_report)
    assert set(fork_verdicts) == set(process_verdicts)
    assert fork_verdicts
    for key, fork_record in fork_verdicts.items():
        process_record = process_verdicts[key]
        assert fork_record["status"] == process_record["status"], key
        assert (
            fork_record["official_conformance"]["status"]
            == process_record["official_conformance"]["status"]
        ), key
        assert fork_record.get("roundtrip_passed") == process_record.get(
            "roundtrip_passed"
        ), key
        assert fork_record.get("simulation_comparison") == process_record.get(
            "simulation_comparison"
        ), key
        assert fork_record.get("generated_network") == process_record.get(
            "generated_network"
        ), key
        assert fork_record.get("reimport_network") == process_record.get(
            "reimport_network"
        ), key
        assert fork_record.get("native_reader") == process_record.get(
            "native_reader"
        ), key
        assert fork_record.get("unsupported_reason") == process_record.get(
            "unsupported_reason"
        ), key
        assert fork_record.get("error") == process_record.get("error"), key


@pytest.mark.skipif(
    not hasattr(os, "fork"), reason="fork isolation requires POSIX fork"
)
def test_fork_isolation_reports_a_timeout_like_the_process_mode(tmp_path, monkeypatch):
    """A hanging case must be bounded and reported identically in both modes."""

    def _hang(*_args, **_kwargs):
        import time

        time.sleep(30)

    monkeypatch.setattr(runner, "_validate_case", _hang)
    case = {
        "category": "semantic",
        "id": "00001",
        "version": "l3v2",
        "path": str(tmp_path / "source.xml"),
    }
    args = _namespace(tmp_path, case_timeout=1)
    records = runner._run_forked_cases([case], args, None, {}, 1)

    assert len(records) == 1
    assert records[0]["status"] == "timeout"
    assert records[0]["official_conformance"]["status"] == "timed-out"
    assert records[0]["error"] == "per-case timeout after 1s"


@pytest.mark.skipif(
    not hasattr(os, "fork"), reason="fork isolation requires POSIX fork"
)
def test_fork_isolation_keeps_a_failing_case_from_reaching_its_neighbour(
    tmp_path, monkeypatch
):
    """A case that fails must not change the verdict of the next case."""

    def _selective(case, *_args, **_kwargs):
        if case["id"] == "00001":
            raise RuntimeError("deliberate failure")
        return {
            "category": case["category"],
            "id": case["id"],
            "version": case["version"],
            "source": str(case["path"]),
            "status": "passed",
            "core_passed": True,
            "official_conformance": {"status": "passed"},
        }

    monkeypatch.setattr(runner, "_validate_case", _selective)
    cases = [
        {
            "category": "semantic",
            "id": "00001",
            "version": "l3v2",
            "path": str(tmp_path / "a.xml"),
        },
        {
            "category": "semantic",
            "id": "00002",
            "version": "l3v2",
            "path": str(tmp_path / "b.xml"),
        },
    ]
    args = _namespace(tmp_path, case_timeout=60)
    records = runner._run_forked_cases(cases, args, None, {}, 2)

    assert [record["status"] for record in records] == ["failed", "passed"]
    assert "deliberate failure" in records[0]["error"]


@pytest.mark.skipif(
    not hasattr(os, "fork"), reason="fork isolation requires POSIX fork"
)
def test_fork_isolation_does_not_leak_case_state_into_the_next_case(
    tmp_path, monkeypatch
):
    """Module state written by one case must not be visible to the next.

    This is the property that a batched, same-process implementation would
    lose.  Every forked child starts from the parent's pristine state, so a
    case that writes a module global cannot be observed by its neighbour.
    """

    monkeypatch.setattr(runner, "_LEAK_PROBE", None, raising=False)

    def _leaky(case, *_args, **_kwargs):
        if case["id"] == "00001":
            runner._LEAK_PROBE = "leaked"
        return {
            "category": case["category"],
            "id": case["id"],
            "version": case["version"],
            "source": str(case["path"]),
            "status": "passed",
            "core_passed": True,
            "observed_probe": runner._LEAK_PROBE,
            "official_conformance": {"status": "passed"},
        }

    monkeypatch.setattr(runner, "_validate_case", _leaky)
    cases = [
        {
            "category": "semantic",
            "id": "00001",
            "version": "l3v2",
            "path": str(tmp_path / "a.xml"),
        },
        {
            "category": "semantic",
            "id": "00002",
            "version": "l3v2",
            "path": str(tmp_path / "b.xml"),
        },
    ]
    args = _namespace(tmp_path, case_timeout=60)
    records = runner._run_forked_cases(cases, args, None, {}, 1)

    assert records[0]["observed_probe"] == "leaked"
    assert records[1]["observed_probe"] is None


def test_busy_verification_slot_never_blocks_or_fails_a_run(tmp_path):
    """A busy slot must be reported and must not fail the run."""

    pytest.importorskip("bionetgen._bionetgen_cpp")
    suite, lock = _locked_ssts_checkout(tmp_path)
    slot = tmp_path / "verification.lock"
    report = tmp_path / "report.json"

    with runner._verification_slot(slot, 0.0):
        result = _run_gate(
            suite,
            lock,
            report,
            "fork",
            ["--lock-file", str(slot), "--lock-wait", "0"],
            categories=["semantic", "stochastic"],
        )
        assert "verification slot" in result.stderr
        assert report.is_file()

        document = json.loads(report.read_text(encoding="utf-8"))
        assert document["case_isolation"]["verification_slot"] is None
        assert document["records"]


def test_verification_slot_is_held_for_the_run_and_released_after(tmp_path):
    """The slot must not survive the run that took it."""

    slot = tmp_path / "verification.lock"
    with runner._verification_slot(slot, 0.0) as handle:
        assert handle is not None
    with runner._verification_slot(slot, 0.0) as handle:
        assert handle is not None


def test_stale_verification_slot_file_does_not_block_a_run(tmp_path):
    """A leftover lock file must not stop a run from taking the slot.

    The slot is an advisory lock, not a marker file: only a live holder
    keeps it, so a file left behind by a killed run cannot deadlock CI.
    """

    slot = tmp_path / "verification.lock"
    slot.write_text("pid=1 since=long ago\n", encoding="utf-8")
    with runner._verification_slot(slot, 0.0) as handle:
        assert handle is not None


def test_unusable_verification_slot_fails_open(tmp_path):
    """A lock file that cannot be created must not fail the run."""

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("occupied\n", encoding="utf-8")
    with runner._verification_slot(blocker / "verification.lock", 0.0) as handle:
        assert handle is None


def test_jobs_advisory_warns_when_the_run_oversubscribes_the_machine():
    cpu_count = os.cpu_count() or 1
    assert runner._jobs_advisory(cpu_count + 1, cpu_count) is not None
    assert "CPUs" in runner._jobs_advisory(cpu_count + 1, cpu_count)
    assert runner._jobs_advisory(1, cpu_count) is None
    assert runner._jobs_advisory(max(1, cpu_count // 2), cpu_count) is None
    # Every CPU is more than half of them, so the softer advisory still fires.
    assert runner._jobs_advisory(cpu_count, cpu_count) is not None


def test_jobs_is_rejected_when_it_is_not_positive():
    """A nonsensical worker count is refused in every mode, not only isolated."""

    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--suite-dir",
            str(Path(__file__).parent),
            "--json",
            "/dev/null",
            "--jobs",
            "0",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--jobs must be at least one" in result.stderr


def _namespace(tmp_path: Path, case_timeout: int):
    import argparse

    return argparse.Namespace(
        json=tmp_path / "report.json",
        suite_dir=tmp_path,
        lock=tmp_path / "lock.json",
        simulation_t_end=1.0,
        simulation_n_steps=10,
        simulation_rtol=1e-7,
        simulation_atol=1e-12,
        stochastic_runs=runner.STOCHASTIC_DEFAULT_RUNS,
        case_timeout=case_timeout,
        artifacts_dir=None,
    )
