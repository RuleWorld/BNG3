#!/usr/bin/env python3
"""Consume retained Issue 142 release-check results and record their identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import numpy as np
from scipy.linalg import expm

from scripts.ci.oracle_sources import load_lock
from tests.validation import compare, graph_identity_contract

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_CHECKS = (
    "release-graph-identity",
    "release-graph-observables",
    "release-obligation-142",
)


def _fail(message: str) -> None:
    raise ValueError(message)


def _properties(testcase: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for prop in testcase.findall("./properties/property"):
        name = prop.attrib.get("name", "")
        value = prop.attrib.get("value", "")
        if not name:
            _fail("JUnit property has no name")
        if name in result and result[name] != value:
            _fail(f"conflicting JUnit property {name}: {result[name]} vs {value}")
        result[name] = value
    return result


def read_check_junit(path: Path, testcase_name: str, check_id: str) -> dict[str, str]:
    if not path.is_file():
        _fail(f"missing JUnit result: {path}")
    root = ET.parse(path).getroot()
    testcases = list(root.iter("testcase"))
    if not testcases:
        _fail(f"JUnit result has no test cases: {path}")
    for testcase in testcases:
        if testcase.find("failure") is not None or testcase.find("error") is not None:
            _fail(
                f"JUnit contains failed or errored case: {testcase.attrib.get('name')}"
            )
        if testcase.find("skipped") is not None:
            _fail(f"JUnit contains skipped case: {testcase.attrib.get('name')}")
    matching = [case for case in testcases if case.attrib.get("name") == testcase_name]
    if len(matching) != 1:
        _fail(f"expected exactly one JUnit case {testcase_name}, got {len(matching)}")
    properties = _properties(matching[0])
    if properties.get("acceptance_check") != check_id:
        _fail(f"JUnit case {testcase_name} does not identify {check_id}")
    return properties


def verify_manifest(root: Path = ROOT) -> dict[str, dict]:
    manifest = json.loads((root / "provenance/issue-obligations.json").read_text())
    issue = next((item for item in manifest["issues"] if item["number"] == 142), None)
    if issue is None:
        _fail("Issue 142 is missing from the obligations manifest")
    checks: dict[str, dict] = {}
    for obligation in issue["obligations"]:
        for check in obligation["required_checks"]:
            check_id = check["id"]
            if check_id in checks:
                _fail(f"conflicting manifest definition for {check_id}")
            checks[check_id] = check
    missing = set(EXPECTED_CHECKS) - set(checks)
    if missing:
        _fail(f"manifest is missing required checks: {sorted(missing)}")
    if not all(
        checks[check_id].get("identity_requirements") for check_id in EXPECTED_CHECKS
    ):
        _fail("a required Issue 142 check has no source/oracle identity requirements")
    expected_test_refs = {
        "release-graph-identity": "tests/validation/test_graph_identity_contract.py",
        "release-graph-observables": "tests/validation/test_nfsim_physical_unimolecular.py",
        "release-obligation-142": "scripts/ci/record_issue142_release.py",
    }
    for check_id, reference in expected_test_refs.items():
        if not any(
            reference in item for item in checks[check_id].get("test_references", [])
        ):
            _fail(f"manifest does not map {check_id} to {reference}")
    return checks


def _check_source_identity(report: dict, expected_revision: str, label: str) -> None:
    if report.get("source_revision") != expected_revision:
        _fail(
            f"stale {label} source revision: {report.get('source_revision')} != {expected_revision}"
        )
    if report.get("source_dirty") is not False:
        _fail(f"{label} source was not recorded clean")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_identity_evidence(directory: Path, expected_revision: str) -> dict:
    report_path = directory / "identity-report.json"
    if not report_path.is_file():
        _fail("missing independent graph identity report")
    report = json.loads(report_path.read_text())
    if report.get("acceptance_check") != "release-graph-identity":
        _fail("identity report has a conflicting check ID")
    _check_source_identity(report, expected_revision, "graph identity")
    oracle = (ROOT / "tests/validation/compare.py").read_bytes() + (
        ROOT / "tests/validation/graph_identity_contract.py"
    ).read_bytes()
    oracle_sha = hashlib.sha256(oracle).hexdigest()
    if report.get("independent_isomorphism_oracle_sha256") != oracle_sha:
        _fail("identity report uses a missing or stale isomorphism oracle")
    cases = graph_identity_contract.CASES
    expected_ids = {
        f"graph-identity-contract:{case['id']}:{check}"
        for case in cases
        for check in graph_identity_contract.CHECKS
    }
    rows = report.get("results")
    if not isinstance(rows, list):
        _fail("identity report has no result rows")
    by_id: dict[str, dict] = {}
    for row in rows:
        check_id = row.get("id")
        if check_id in by_id:
            _fail(f"duplicate identity result ID: {check_id}")
        by_id[check_id] = row
    missing = expected_ids - set(by_id)
    unexpected = set(by_id) - expected_ids
    if missing or unexpected:
        _fail(
            f"identity result IDs disagree; missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
    failed = [
        check_id for check_id, row in by_id.items() if row.get("status") != "PASS"
    ]
    if failed:
        _fail(f"identity checks did not pass: {failed[:5]}")
    if report.get("case_count") != len(cases):
        _fail("identity report case count is stale")
    if report.get("exhaustive_case_count") != 116:
        _fail("identity report does not cover all 116 bounded cases")
    subject_sha = hashlib.sha256(
        json.dumps(
            graph_identity_contract.CASES, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    if report.get("subject_sha256") != subject_sha:
        _fail("identity report has a stale generated-case subject hash")
    junit = read_check_junit(
        directory / "release-graph-identity.xml",
        "test_the_native_surfaces_match_the_independent_contract",
        "release-graph-identity",
    )
    if (
        junit.get("bng3_revision") != expected_revision
        or junit.get("bng3_dirty") != "false"
        or junit.get("independent_isomorphism_oracle_sha256") != oracle_sha
        or junit.get("subject_sha256") != subject_sha
    ):
        _fail("identity JUnit properties conflict with the retained report")
    return {
        "status": "PASS",
        "result_count": len(rows),
        "case_count": len(cases),
        "exhaustive_case_count": 116,
        "independent_isomorphism_oracle_sha256": oracle_sha,
        "subject_sha256": subject_sha,
        "report_sha256": _sha256(report_path),
    }


def _verify_observables_artifacts(directory: Path, report: dict) -> list[int]:
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        _fail("observable report has no retained artifact hashes")
    for name, expected_sha in artifacts.items():
        path = directory / name
        if not path.is_file() or _sha256(path) != expected_sha:
            _fail(f"missing, stale, or conflicting observable artifact: {name}")
    expected_trajectories = {
        f"trajectories/seed-{seed}.gdat"
        for seed in range(report["seed_start"], report["seed_end_exclusive"])
    }
    actual_trajectories = {name for name in artifacts if name.endswith(".gdat")}
    if actual_trajectories != expected_trajectories:
        _fail("observable report is missing or has unexpected seeded trajectories")
    endpoints = []
    for name in sorted(expected_trajectories):
        data, columns = compare.parse_gdat(directory / name)
        if data is None or columns is None or not {"Dimer", "Bound"} <= set(columns):
            _fail(f"malformed observable trajectory: {name}")
        dimers = data[:, columns.index("Dimer")]
        bound = data[:, columns.index("Bound")]
        if not np.array_equal(bound, 2 * dimers) or dimers[0] != 0:
            _fail(f"native observable multiplicity mismatch: {name}")
        endpoints.append(int(dimers[-1]))
    if endpoints != report.get("endpoint_dimers"):
        _fail("observable report endpoint counts conflict with retained trajectories")
    return endpoints


def _verify_endpoint_law(endpoints: list[int], report: dict) -> None:
    molecules = 10
    rate = 0.1
    end_time = 1.0
    runs = 200
    states = molecules // 2 + 1
    generator = np.zeros((states, states), dtype=float)
    for dimers in range(states - 1):
        free_molecules = molecules - 2 * dimers
        propensity = rate * free_molecules * (free_molecules - 1) / 2
        generator[dimers, dimers] = -propensity
        generator[dimers, dimers + 1] = propensity
    initial = np.zeros(states, dtype=float)
    initial[0] = 1.0
    expected_cdf = np.cumsum(expm(generator.T * end_time) @ initial)
    if any(count < 0 or count >= states for count in endpoints):
        _fail("native dimer count is outside the independently enumerated state space")
    observed_cdf = np.cumsum(np.bincount(endpoints, minlength=states) / runs)
    epsilon = math.sqrt(math.log(2.0 / 0.005) / (2.0 * runs))
    if len(endpoints) != runs or np.max(np.abs(observed_cdf - expected_cdf)) > epsilon:
        _fail("native endpoint counts fail the independent finite-state CTMC bound")
    if report.get("run_count") != runs or report.get("dkw_alpha") != 0.005:
        _fail("observable ensemble budget or error control is stale")
    if (
        report.get("seed_start") != 7300
        or report.get("seed_end_exclusive") != 7500
        or report.get("seed_end_exclusive") - report.get("seed_start") != runs
        or report.get("end_time") != end_time
    ):
        _fail("observable fixed seed or time budget is inconsistent")


def verify_observables_evidence(directory: Path, expected_revision: str) -> dict:
    report_path = directory / "observables-report.json"
    if not report_path.is_file():
        _fail("missing symmetric observable report")
    report = json.loads(report_path.read_text())
    if report.get("acceptance_check") != "release-graph-observables":
        _fail("observable report has a conflicting check ID")
    _check_source_identity(report, expected_revision, "graph observables")
    lock = load_lock()
    if report.get("bng2_revision") != lock["sources"]["bionetgen"]["revision"]:
        _fail("observable report uses a stale BNG2 source revision")
    if report.get("nfsim_revision") != lock["sources"]["nfsim"]["revision"]:
        _fail("observable report uses a stale NFsim source revision")
    for key in (
        "bng2_script_sha256",
        "nfsim_binary_sha256",
        "model_source_sha256",
        "bng2_net_sha256",
        "bng2_xml_sha256",
        "bng3_net_sha256",
    ):
        value = report.get(key)
        if not isinstance(value, str) or len(value) != 64:
            _fail(f"observable report lacks valid identity field {key}")
    junit = read_check_junit(
        directory / "release-graph-observables.xml",
        "test_release_graph_observables_symmetric_homodimer_multiplicity",
        "release-graph-observables",
    )
    expected_properties = {
        "bng3_revision": expected_revision,
        "bng3_dirty": "false",
        "bng2_revision": report["bng2_revision"],
        "bng2_script_sha256": report["bng2_script_sha256"],
        "nfsim_revision": report["nfsim_revision"],
        "nfsim_binary_sha256": report["nfsim_binary_sha256"],
        "model_source_sha256": report["model_source_sha256"],
        "bng2_net_sha256": report["bng2_net_sha256"],
        "bng2_xml_sha256": report["bng2_xml_sha256"],
        "bng3_net_sha256": report["bng3_net_sha256"],
    }
    if any(junit.get(key) != value for key, value in expected_properties.items()):
        _fail("observable JUnit properties conflict with the retained report")
    endpoints = _verify_observables_artifacts(directory, report)
    _verify_endpoint_law(endpoints, report)

    bng2_net = compare.parse_net(directory / "bng2/symmetric-dimer.net")
    bng3_net = compare.parse_net(directory / "bng3/symmetric-dimer.net")
    if bng2_net is None or bng3_net is None:
        _fail("observable artifacts lack parseable BNG2/BNG3 networks")
    diff = compare.compare_net(bng2_net, bng3_net)
    if not diff.ok:
        _fail(f"BNG2/BNG3 observable network parity failed: {diff.summary()}")
    if len(bng2_net._raw) != 1 or bng2_net._raw[0][2] != "0.5*kon":
        _fail("BNG2 homodimer reaction does not encode its symmetric pair factor")
    dimer = {
        index
        for index, species in bng2_net.species_by_index.items()
        if species == "A(b!1).A(b!1)"
    }
    if len(dimer) != 1:
        _fail("BNG2 network has no unique symmetric dimer species")
    group_weights = {
        name: {
            bng2_net.species_by_index[index]: weight
            for index, weight in weights.items()
        }
        for name, weights in bng2_net.groups.values()
    }
    expected_weights = {
        "Dimer": {"A(b!1).A(b!1)": 1.0},
        "Bound": {"A(b!1).A(b!1)": 2.0},
    }
    if group_weights != expected_weights:
        _fail(f"BNG2 observable group multiplicities differ: {group_weights}")
    if report.get("bng2_net_sha256") != _sha256(directory / "bng2/symmetric-dimer.net"):
        _fail("BNG2 network hash disagrees with report")
    if report.get("bng2_xml_sha256") != _sha256(directory / "bng2/symmetric-dimer.xml"):
        _fail("BNG2 XML hash disagrees with report")
    if report.get("bng3_net_sha256") != _sha256(directory / "bng3/symmetric-dimer.net"):
        _fail("BNG3 network hash disagrees with report")
    if report.get("model_source_sha256") != _sha256(directory / "model.bngl"):
        _fail("model source hash disagrees with report")
    xml_root = ET.parse(directory / "bng2/symmetric-dimer.xml").getroot()
    rules = [
        element for element in xml_root.iter() if element.tag.endswith("ReactionRule")
    ]
    if len(rules) != 1 or float(rules[0].attrib.get("symmetry_factor", "nan")) != 0.5:
        _fail("retained BNG2 XML has no unique symmetric reaction factor")
    dimer_patterns = [
        pattern
        for observable in xml_root.iter()
        if observable.tag.endswith("Observable")
        and observable.attrib.get("name") == "Dimer"
        for pattern in observable.iter()
        if pattern.tag.endswith("Pattern")
        and pattern.attrib.get("automorphisms") == "2"
    ]
    if not dimer_patterns:
        _fail("retained BNG2 XML lost the dimer observable automorphism weight")
    return {
        "status": "PASS",
        "run_count": len(endpoints),
        "seed_start": report["seed_start"],
        "seed_end_exclusive": report["seed_end_exclusive"],
        "dkw_alpha": report["dkw_alpha"],
        "bng2_revision": report["bng2_revision"],
        "bng2_script_sha256": report["bng2_script_sha256"],
        "nfsim_revision": report["nfsim_revision"],
        "nfsim_binary_sha256": report["nfsim_binary_sha256"],
        "subject_sha256": report["model_source_sha256"],
        "report_sha256": _sha256(report_path),
    }


def build_release_record(
    identity_dir: Path,
    observables_dir: Path,
    expected_revision: str,
    root: Path = ROOT,
) -> dict:
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if head != expected_revision:
        _fail(f"stale Issue 142 evidence: checkout HEAD {head} != {expected_revision}")
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if dirty:
        _fail(f"Issue 142 evidence checkout is dirty: {dirty}")
    manifest_checks = verify_manifest(root)
    identity = verify_identity_evidence(identity_dir, expected_revision)
    observables = verify_observables_evidence(observables_dir, expected_revision)
    return {
        "schema_version": 1,
        "acceptance_check": "release-obligation-142",
        "source_revision": head,
        "source_dirty": False,
        "checks": {
            "release-graph-identity": identity,
            "release-graph-observables": observables,
            "release-obligation-142": {"status": "PASS"},
        },
        "manifest_check_ids": sorted(set(EXPECTED_CHECKS) & set(manifest_checks)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity-evidence", type=Path, required=True)
    parser.add_argument("--observables-evidence", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-file", type=Path)
    args = parser.parse_args(argv)
    try:
        report = build_release_record(
            args.identity_evidence,
            args.observables_evidence,
            args.source_revision,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        summary = [
            "## Issue 142 release obligation record",
            "",
            f"- Main/source commit: `{report['source_revision']}`",
            "- release-graph-identity: PASS (independent bounded exhaustive partition; clean source revision and oracle hash recorded)",
            f"- release-graph-observables: PASS ({report['checks']['release-graph-observables']['run_count']} pinned native NFsim runs; BNG2/BNG3 networks, observable weights, source/oracle identities and artifacts checked)",
            "- release-obligation-142: PASS (consumed both named check reports and retained artifacts)",
            f"- BNG2 revision: `{report['checks']['release-graph-observables']['bng2_revision']}`",
            f"- Native NFsim revision: `{report['checks']['release-graph-observables']['nfsim_revision']}`",
            f"- Native NFsim binary SHA-256: `{report['checks']['release-graph-observables']['nfsim_binary_sha256']}`",
            f"- Independent isomorphism oracle SHA-256: `{report['checks']['release-graph-identity']['independent_isomorphism_oracle_sha256']}`",
            "",
            f"Consolidated JSON: `{args.output}`",
            "",
        ]
        if args.summary_file:
            with args.summary_file.open("a", encoding="utf-8") as stream:
                stream.write("\n".join(summary))
        else:
            sys.stdout.write("\n".join(summary))
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        print(f"Issue 142 release record rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
