#!/usr/bin/env python3
"""Regressions for the imported PR78 identity and A/B harnesses."""
from __future__ import annotations

import json
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


class PR78HarnessTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
