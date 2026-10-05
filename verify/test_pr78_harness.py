#!/usr/bin/env python3
"""Regressions for the imported PR78 identity and A/B harnesses."""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from verify import ab_bench, identity_check

ROOT = Path(__file__).resolve().parents[1]
AB_BENCH = ROOT / "verify" / "ab_bench.py"
IDENTITY_CHECK = ROOT / "verify" / "identity_check.py"
COMPARE_IDENTITY = ROOT / "verify" / "compare_identity.py"


def make_binary(path: Path, value: bytes | None) -> Path:
    payload = "None" if value is None else repr(value.decode("ascii"))
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, re, sys, time\n"
        "model = pathlib.Path(sys.argv[1])\n"
        "text = model.read_text()\n"
        "steps = int(re.search(r'max_sim_steps=>(\\d+)', text).group(1))\n"
        "start = time.process_time()\n"
        "while time.process_time() - start < steps * 0.001: pass\n"
        f"payload = {payload}\n"
        "if payload is not None:\n"
        "    pathlib.Path(model.stem + '_bench.gdat').write_bytes(payload.encode())\n"
        "    pathlib.Path(model.stem + '.net').write_bytes(b'network')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def make_once_only_binary(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, re, sys, time\n"
        "model = pathlib.Path(sys.argv[1])\n"
        "text = model.read_text()\n"
        "steps = int(re.search(r'max_sim_steps=>(\\d+)', text).group(1))\n"
        "start = time.process_time()\n"
        "while time.process_time() - start < steps * 0.001: pass\n"
        "if model.stem == 'full':\n"
        "    state = pathlib.Path(__file__).with_suffix('.count')\n"
        "    count = int(state.read_text()) if state.exists() else 0\n"
        "    state.write_text(str(count + 1))\n"
        "    if count == 0:\n"
        "        pathlib.Path('full_bench.gdat').write_bytes(b'old-run')\n"
        "        pathlib.Path('full.net').write_bytes(b'old-network')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def make_net_only_binary(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "Path('model.net').write_text('network only')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def make_trajectory_binary(path: Path) -> Path:
    return make_output_binary(
        path, network=b"network", trajectory=trajectory_table(0, 20, 300)
    )


def make_output_binary(path: Path, *, network: bytes | None,
                       trajectory: bytes | None) -> Path:
    writes = []
    if network is not None:
        writes.append(f"Path('model.net').write_bytes({network!r})")
    if trajectory is not None:
        writes.append(f"Path('model_s.gdat').write_bytes({trajectory!r})")
    path.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        + "\n".join(writes) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def trajectory_table(t_start: float, t_end: float, n_steps: int) -> bytes:
    lines = ["# time Atot"]
    for index in range(n_steps + 1):
        timepoint = t_start + (t_end - t_start) * index / n_steps
        lines.append(f"{timepoint:.12e} 1.000000000000e+00")
    return ("\n".join(lines) + "\n").encode()


def test_sampling_grid(case: str) -> dict[str, int | float]:
    start, end, steps = {
        "edge_dimer": (0.0, 20.0, 300),
        "edge_zero_plateau": (0.0, 50.0, 300),
    }.get(case, (0.0, 20.0, 300))
    return {
        "t_start": start,
        "t_end": end,
        "n_steps": steps,
        "expected_rows": steps + 1,
    }


def make_identity_output(root: Path, cases: list[str], *,
                         trajectory: bool = True, valid: bool = True) -> None:
    case_records = {}
    for name in cases:
        case = root / name
        case.mkdir(parents=True)
        (case / "model.net").write_bytes(b"network")
        trajectory_files = []
        usable_trajectory_files = []
        sampling = test_sampling_grid(name)
        if trajectory:
            trajectory_path = case / "model_s.gdat"
            trajectory_path.write_bytes(
                trajectory_table(sampling["t_start"], sampling["t_end"],
                                 sampling["n_steps"])
            )
            trajectory_files.append(trajectory_path.name)
            usable_trajectory_files.append(trajectory_path.name)
        artifacts = sorted(case.glob("*.gdat")) + sorted(case.glob("*.net"))
        sums = [
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
            for path in artifacts
        ]
        (case / "SHA256SUMS").write_text("\n".join(sums) + "\n")
        case_records[name] = {
            "status": "pass" if valid and trajectory_files else "missing_trajectory",
            "valid": valid and bool(trajectory_files),
            "exit_code": 0,
            "fresh_output_directory": True,
            "expected_sampling": sampling,
            "network_files": ["model.net"],
            "trajectory_files": trajectory_files,
            "usable_trajectory_files": usable_trajectory_files,
            "artifact_files": [path.name for path in artifacts],
        }
    manifest = {
        "schema_version": 1,
        "selected_cases": cases,
        "valid": valid and bool(cases) and all(
            record["valid"] for record in case_records.values()
        ),
        "cases": case_records,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "identity_manifest.json").write_text(json.dumps(manifest))


def refresh_case_hashes(case: Path) -> None:
    artifacts = sorted(
        path for pattern in ("*.gdat", "*.cdat", "*.net")
        for path in case.glob(pattern)
    )
    sums = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in artifacts
    ]
    (case / "SHA256SUMS").write_text("\n".join(sums) + "\n")


class PR78HarnessTests(unittest.TestCase):
    def test_sampling_expectations_cover_all_fixed_identity_actions(self) -> None:
        grids = {
            name: identity_check.expected_sampling(name)
            for name, _, _ in identity_check.CASES
        }
        self.assertEqual(
            grids["isomerization"],
            {"t_start": 0.0, "t_end": 20000.0,
             "n_steps": 400, "expected_rows": 401},
        )
        self.assertEqual(grids["gene_expr_simple"]["t_end"], 100000.0)
        self.assertEqual(grids["edge_ring_long"]["t_end"], 200.0)
        for sampling in grids.values():
            self.assertEqual(sampling["expected_rows"], sampling["n_steps"] + 1)

    def test_blbr_identity_case_keeps_its_stoichiometry_bound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr78-blbr-") as tmp:
            case = identity_check.build_case(
                "blbr", "models/blbr.bngl", [
                    'simulate_ssa({suffix=>"s",t_start=>0,t_end=>10,'
                    'n_steps=>300,seed=>31})'
                ], Path(tmp),
            )
            text = (case / "model.bngl").read_text()
            self.assertIn(
                "generate_network({overwrite=>1,max_stoich=>{'R'=>5,'L'=>5}})",
                text,
            )
            self.assertNotIn("generate_network({overwrite=>1})", text)

    def test_rss_normalization_matches_macos_and_linux_wait4_units(self) -> None:
        self.assertEqual(ab_bench.maxrss_to_bytes(2048, "darwin"), 2048)
        self.assertEqual(ab_bench.maxrss_to_bytes(2, "linux"), 2048)

    def test_hash_mismatch_fails_the_ab_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr78-mismatch-") as tmp:
            root = Path(tmp)
            a = make_binary(root / "a", b"trajectory-A")
            b = make_binary(root / "b", b"trajectory-B")
            report = root / "report.json"
            result = subprocess.run(
                [sys.executable, str(AB_BENCH), "--bin", f"A={a}", "--bin",
                 f"B={b}", "--reps", "1", "--species", "2", "--events",
                 "10", "--json", str(report)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rss_json_has_normalized_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr78-rss-") as tmp:
            root = Path(tmp)
            binary = make_binary(root / "binary", b"same-trajectory")
            report = root / "report.json"
            result = subprocess.run(
                [sys.executable, str(AB_BENCH), "--bin", f"A={binary}", "--bin",
                 f"B={binary}", "--reps", "1", "--species", "2", "--events",
                 "10", "--json", str(report)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(report.read_text())
            self.assertIn("max_rss_bytes", data)
            self.assertNotIn("max_rss_kb", data)

    def test_a_previous_gdat_cannot_satisfy_a_later_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr78-stale-") as tmp:
            root = Path(tmp)
            binary = make_once_only_binary(root / "binary")
            result = subprocess.run(
                [sys.executable, str(AB_BENCH), "--bin", f"A={binary}",
                 "--reps", "2", "--species", "2", "--events", "10"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_identity_check_fails_for_nonzero_model_exit_without_slow_cases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr78-exit-") as tmp:
            root = Path(tmp)
            failing = root / "failing-bng-cpp"
            failing.write_text("#!/bin/sh\nexit 17\n", encoding="utf-8")
            failing.chmod(0o755)
            result = subprocess.run(
                [sys.executable, str(IDENTITY_CHECK), str(failing),
                 str(root / "identity"), "--only", "edge_dimer"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_identity_check_records_unlaunchable_simulator(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-launch-error-") as tmp:
            root = Path(tmp)
            out = root / "identity"
            result = subprocess.run(
                [sys.executable, str(IDENTITY_CHECK), str(root / "missing-bng-cpp"),
                 str(out), "--only", "edge_dimer"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((out / "identity_manifest.json").read_text())
            self.assertFalse(manifest["valid"])
            record = manifest["cases"]["edge_dimer"]
            self.assertEqual(record["status"], "launch_error")
            self.assertIsNone(record["exit_code"])
            self.assertIn("No such file", record["error"])

    def test_identity_check_rejects_net_only_success_and_records_invalid_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-net-only-") as tmp:
            root = Path(tmp)
            binary = make_net_only_binary(root / "net-only-bng-cpp")
            out = root / "identity"
            result = subprocess.run(
                [sys.executable, str(IDENTITY_CHECK), str(binary), str(out),
                 "--only", "edge_dimer"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((out / "identity_manifest.json").read_text())
            self.assertFalse(manifest["valid"])
            self.assertEqual(
                manifest["cases"]["edge_dimer"]["status"],
                "missing_trajectory",
            )
            self.assertEqual(
                manifest["cases"]["edge_dimer"]["trajectory_files"], [],
            )

    def test_identity_check_records_valid_fresh_trajectory_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-valid-trajectory-") as tmp:
            root = Path(tmp)
            binary = make_trajectory_binary(root / "trajectory-bng-cpp")
            out = root / "identity"
            result = subprocess.run(
                [sys.executable, str(IDENTITY_CHECK), str(binary), str(out),
                 "--only", "edge_dimer"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((out / "identity_manifest.json").read_text())
            self.assertTrue(manifest["valid"])
            record = manifest["cases"]["edge_dimer"]
            self.assertEqual(record["status"], "pass")
            self.assertTrue(record["fresh_output_directory"])
            self.assertEqual(record["trajectory_files"], ["model_s.gdat"])
            self.assertEqual(record["expected_sampling"], test_sampling_grid("edge_dimer"))
            self.assertEqual(record["network_files"], ["model.net"])
            self.assertEqual(record["usable_trajectory_files"], ["model_s.gdat"])

    def test_identity_check_rejects_empty_trajectory_data(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-empty-trajectory-") as tmp:
            root = Path(tmp)
            binary = make_output_binary(
                root / "empty-trajectory-bng-cpp",
                network=b"network",
                trajectory=b"",
            )
            out = root / "identity"
            result = subprocess.run(
                [sys.executable, str(IDENTITY_CHECK), str(binary), str(out),
                 "--only", "edge_dimer"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads((out / "identity_manifest.json").read_text())[
                "cases"]["edge_dimer"]
            self.assertEqual(record["status"], "invalid_trajectory")
            self.assertEqual(record["usable_trajectory_files"], [])

    def test_identity_check_rejects_header_only_trajectory_data(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-header-only-trajectory-") as tmp:
            root = Path(tmp)
            binary = make_output_binary(
                root / "header-only-trajectory-bng-cpp",
                network=b"network",
                trajectory=b"# time Atot\n",
            )
            out = root / "identity"
            result = subprocess.run(
                [sys.executable, str(IDENTITY_CHECK), str(binary), str(out),
                 "--only", "edge_dimer"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads((out / "identity_manifest.json").read_text())[
                "cases"]["edge_dimer"]
            self.assertEqual(record["status"], "invalid_trajectory")
            self.assertEqual(record["usable_trajectory_files"], [])

    def test_identity_check_rejects_single_row_truncated_trajectory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-truncated-trajectory-") as tmp:
            root = Path(tmp)
            binary = make_output_binary(
                root / "truncated-trajectory-bng-cpp",
                network=b"network",
                trajectory=b"# time Atot\n0.0 1.0\n",
            )
            out = root / "identity"
            result = subprocess.run(
                [sys.executable, str(IDENTITY_CHECK), str(binary), str(out),
                 "--only", "edge_dimer"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads((out / "identity_manifest.json").read_text())[
                "cases"]["edge_dimer"]
            self.assertEqual(record["status"], "invalid_trajectory")
            self.assertEqual(record["expected_sampling"]["expected_rows"], 301)

    def test_identity_check_rejects_wrong_trajectory_endpoint(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-wrong-endpoint-") as tmp:
            root = Path(tmp)
            binary = make_output_binary(
                root / "wrong-endpoint-bng-cpp",
                network=b"network",
                trajectory=trajectory_table(0, 10, 300),
            )
            out = root / "identity"
            result = subprocess.run(
                [sys.executable, str(IDENTITY_CHECK), str(binary), str(out),
                 "--only", "edge_dimer"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads((out / "identity_manifest.json").read_text())[
                "cases"]["edge_dimer"]
            self.assertEqual(record["status"], "invalid_trajectory")

    def test_identity_check_rejects_trajectory_without_network(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-no-network-") as tmp:
            root = Path(tmp)
            binary = make_output_binary(
                root / "trajectory-only-bng-cpp",
                network=None,
                trajectory=b"# time Atot\n0.0 1.0\n",
            )
            out = root / "identity"
            result = subprocess.run(
                [sys.executable, str(IDENTITY_CHECK), str(binary), str(out),
                 "--only", "edge_dimer"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads((out / "identity_manifest.json").read_text())[
                "cases"]["edge_dimer"]
            self.assertEqual(record["status"], "missing_network")
            self.assertEqual(record["network_files"], [])

    def test_identity_check_rejects_empty_network(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-empty-network-") as tmp:
            root = Path(tmp)
            binary = make_output_binary(
                root / "empty-network-bng-cpp",
                network=b"",
                trajectory=b"# time Atot\n0.0 1.0\n",
            )
            out = root / "identity"
            result = subprocess.run(
                [sys.executable, str(IDENTITY_CHECK), str(binary), str(out),
                 "--only", "edge_dimer"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads((out / "identity_manifest.json").read_text())[
                "cases"]["edge_dimer"]
            self.assertEqual(record["status"], "missing_network")
            self.assertEqual(record["network_files"], ["model.net"])

    def test_compare_identity_rejects_matching_hashes_from_invalid_runs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-invalid-run-") as tmp:
            root = Path(tmp)
            base = root / "base"
            changed = root / "changed"
            make_identity_output(base, ["edge_dimer"], trajectory=False, valid=False)
            make_identity_output(changed, ["edge_dimer"], trajectory=False, valid=False)
            result = subprocess.run(
                [sys.executable, str(COMPARE_IDENTITY), str(base), str(changed)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("INVALID", result.stdout + result.stderr)

    def test_compare_identity_accepts_complete_identical_runs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-valid-identical-") as tmp:
            root = Path(tmp)
            base = root / "base"
            changed = root / "changed"
            make_identity_output(base, ["edge_dimer"])
            make_identity_output(changed, ["edge_dimer"])
            result = subprocess.run(
                [sys.executable, str(COMPARE_IDENTITY), str(base), str(changed)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("IDENTICAL", result.stdout)

    def test_compare_identity_rejects_nonfresh_case_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-comparator-stale-output-") as tmp:
            root = Path(tmp)
            base = root / "base"
            changed = root / "changed"
            make_identity_output(base, ["edge_dimer"])
            make_identity_output(changed, ["edge_dimer"])
            manifest_path = changed / "identity_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["cases"]["edge_dimer"]["fresh_output_directory"] = False
            manifest_path.write_text(json.dumps(manifest))
            result = subprocess.run(
                [sys.executable, str(COMPARE_IDENTITY), str(base), str(changed)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("INVALID", result.stdout + result.stderr)

    def test_compare_identity_rejects_manifest_claim_for_wrong_sampling_grid(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-comparator-wrong-grid-") as tmp:
            root = Path(tmp)
            base = root / "base"
            changed = root / "changed"
            make_identity_output(base, ["edge_dimer"])
            make_identity_output(changed, ["edge_dimer"])
            changed_case = changed / "edge_dimer"
            (changed_case / "model_s.gdat").write_bytes(trajectory_table(0, 10, 300))
            refresh_case_hashes(changed_case)
            manifest_path = changed / "identity_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["cases"]["edge_dimer"]["expected_sampling"] = test_sampling_grid(
                "edge_zero_plateau"
            )
            manifest_path.write_text(json.dumps(manifest))
            result = subprocess.run(
                [sys.executable, str(COMPARE_IDENTITY), str(base), str(changed)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("INVALID", result.stdout + result.stderr)

    def test_compare_identity_revalidates_trajectory_contents(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-comparator-invalid-data-") as tmp:
            root = Path(tmp)
            base = root / "base"
            changed = root / "changed"
            make_identity_output(base, ["edge_dimer"])
            make_identity_output(changed, ["edge_dimer"])
            changed_case = changed / "edge_dimer"
            (changed_case / "model_s.gdat").write_text("# time Atot\n")
            refresh_case_hashes(changed_case)
            result = subprocess.run(
                [sys.executable, str(COMPARE_IDENTITY), str(base), str(changed)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("INVALID", result.stdout + result.stderr)

    def test_compare_identity_rejects_manifest_claim_without_network(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-comparator-no-network-") as tmp:
            root = Path(tmp)
            base = root / "base"
            changed = root / "changed"
            make_identity_output(base, ["edge_dimer"])
            make_identity_output(changed, ["edge_dimer"])
            changed_case = changed / "edge_dimer"
            (changed_case / "model.net").unlink()
            refresh_case_hashes(changed_case)
            manifest_path = changed / "identity_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            record = manifest["cases"]["edge_dimer"]
            record["network_files"] = []
            record["artifact_files"] = ["model_s.gdat"]
            manifest_path.write_text(json.dumps(manifest))
            result = subprocess.run(
                [sys.executable, str(COMPARE_IDENTITY), str(base), str(changed)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("INVALID", result.stdout + result.stderr)

    def test_compare_identity_rejects_empty_network(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-comparator-empty-network-") as tmp:
            root = Path(tmp)
            base = root / "base"
            changed = root / "changed"
            make_identity_output(base, ["edge_dimer"])
            make_identity_output(changed, ["edge_dimer"])
            changed_case = changed / "edge_dimer"
            (changed_case / "model.net").write_bytes(b"")
            refresh_case_hashes(changed_case)
            result = subprocess.run(
                [sys.executable, str(COMPARE_IDENTITY), str(base), str(changed)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("INVALID", result.stdout + result.stderr)

    def test_compare_identity_rejects_candidate_extra_case(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-extra-case-") as tmp:
            root = Path(tmp)
            base = root / "base"
            changed = root / "changed"
            make_identity_output(base, ["edge_dimer"])
            make_identity_output(changed, ["edge_dimer", "edge_extra"])
            result = subprocess.run(
                [sys.executable, str(COMPARE_IDENTITY), str(base), str(changed)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("coverage mismatch", result.stdout + result.stderr)

    def test_compare_identity_rejects_candidate_missing_case(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-missing-case-") as tmp:
            root = Path(tmp)
            base = root / "base"
            changed = root / "changed"
            make_identity_output(base, ["edge_dimer", "edge_zero_plateau"])
            make_identity_output(changed, ["edge_dimer"])
            result = subprocess.run(
                [sys.executable, str(COMPARE_IDENTITY), str(base), str(changed)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("coverage mismatch", result.stdout + result.stderr)

    def test_compare_identity_rejects_empty_case_coverage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr92-empty-coverage-") as tmp:
            root = Path(tmp)
            base = root / "base"
            changed = root / "changed"
            base.mkdir()
            changed.mkdir()
            result = subprocess.run(
                [sys.executable, str(COMPARE_IDENTITY), str(base), str(changed)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("empty case set", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
