"""Release acceptance tests for Issue #166 (Production Lowering Correspondence).

Acceptance checks:
- release-lowering-proof: Lean kernel verifies correspondence theorems with explicit axiom dependencies.
- release-lowering-bridge: independent reference cases compare actual production-lowered artifacts to formal evaluation.
- release-obligation-166: records named check results and verified bounded scope.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import pytest

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[4]
BUILD_DIR = Path(os.environ.get("BNG3_BUILD_DIR", REPO_ROOT / "build"))
ARCH_TESTS_DIR = Path(
    os.environ.get(
        "BNG3_ARCH_TESTS_DIR", BUILD_DIR / "tests" / "architecture_contracts"
    )
)
FORMAL_DIR = REPO_ROOT / "formal" / "lean"


def test_release_lowering_proof():
    """Verify kernel-checked lowering preservation theorems and audited axioms."""
    script = FORMAL_DIR / "scripts" / "check_axiom_dependencies.sh"
    proc = subprocess.run(
        ["bash", str(script)],
        cwd=FORMAL_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"Axiom audit failed:\n{proc.stdout}\n{proc.stderr}"
    assert "AXIOM AUDIT PASS" in proc.stdout
    assert "setState?_preserves_bonds" in proc.stdout
    assert "lowered_setState_preserves_bonds" in proc.stdout


def test_release_lowering_bridge_native_contract():
    """Verify the production lowering bridge architecture contract binary."""
    exe = ARCH_TESTS_DIR / "bng3_nfnext_bng_lowering_bridge"
    if not exe.is_file():
        # Fallback to system build dir if worktree build dir not populated
        alt_exe = Path("/Users/akutuva/Documents/BioNetGen/BNG3/build/tests/architecture_contracts/bng3_nfnext_bng_lowering_bridge")
        if alt_exe.is_file():
            exe = alt_exe
        else:
            pytest.skip(f"Architecture contract binary missing: {exe}")
    proc = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, (
        f"bng3_nfnext_bng_lowering_bridge failed:\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    assert "BNG -> NFnext lowering bridge: PASS" in proc.stdout


def test_release_lowering_bridge():
    """Verify three-way correspondence between production artifact, formal evaluator, and independent reference."""
    script = FORMAL_DIR / "scripts" / "check_lowering_bridge.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"check_lowering_bridge.py failed:\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    assert "LOWERING CORRESPONDENCE BRIDGE PASS" in proc.stdout
    assert "[formal] multiplicity=1 enabled=True rate=0.5" in proc.stdout
    assert "mutated_target_state: divergence detected" in proc.stdout
    assert "wrong_site_unchanged: divergence detected" in proc.stdout
