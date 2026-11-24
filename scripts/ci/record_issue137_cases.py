"""Execute and record grounded #137 capability-row case receipts.

Each mode executes the real mapped selector(s) against the named independent
oracle or structural/analytic contract and emits ``release-capability[ID]``
results bound to the exact source revision.  A failing or unexecuted selector
is recorded as ``FAIL`` with ``supported_execution=False``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "provenance/upstreams.lock.yml"


def _git_head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()


def _git_dirty(repo: Path) -> bool:
    return bool(
        subprocess.check_output(
            ["git", "-C", str(repo), "status", "--porcelain"], text=True
        ).strip()
    )


def _run(
    command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _row_result(
    row_id: str, passed: bool, selector: str, detail: str
) -> dict[str, Any]:
    return {
        "id": f"release-capability[{row_id}]",
        "status": "PASS" if passed else "FAIL",
        "evidence_kind": "supported-execution" if passed else "observed-failure",
        "supported_execution": passed,
        "related_issues": [137],
        "selector": selector,
        "detail": detail,
    }


def run_structural(root: Path = ROOT) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    nauty = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--noconftest",
            str(root / "tests/python/test_single_nauty_contract.py"),
        ],
        cwd=root,
    )
    prov = _run(
        [sys.executable, str(root / "scripts/validate_provenance.py")],
        cwd=root,
    )
    manifests = sorted((root / "provenance/golden").rglob("manifest.json"))
    golden_ok = (
        prov.returncode == 0 and (root / "provenance/golden/README.md").is_file()
    )
    golden_detail = prov.stdout.strip() or prov.stderr.strip()
    for manifest in manifests:
        check = _run(
            [
                sys.executable,
                str(root / "scripts/validate_golden_manifest.py"),
                "--manifest",
                str(manifest),
            ],
            cwd=root,
        )
        if check.returncode != 0:
            golden_ok = False
            golden_detail = check.stderr.strip() or check.stdout.strip()
            break
    references = {
        "structural-contract": {
            "contract": (
                "provenance/golden/README.md manifest + "
                "tests/python/test_single_nauty_contract.py"
            )
        }
    }
    results = [
        _row_result(
            "core.graph.canonicalization.single-nauty",
            nauty.returncode == 0,
            "tests/python/test_single_nauty_contract.py",
            nauty.stdout.strip() or nauty.stderr.strip(),
        ),
        _row_result(
            "validation.oracles-goldens-release",
            golden_ok,
            "scripts/regen_golden.py",
            golden_detail or "provenance and golden manifest contract satisfied",
        ),
    ]
    return references, results


def _verify_pin(root: Path, name: str, checkout: Path) -> str:
    lock = json.loads((root / "provenance/upstreams.lock.yml").read_text())
    expected = lock["sources"][name]["revision"]
    actual = _git_head(checkout)
    if actual != expected:
        raise ValueError(
            f"pinned {name} checkout {actual} does not match accepted lock {expected}"
        )
    return actual


def run_bng2(
    root: Path, *, bng_cpp: Path, bng2_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pin = _verify_pin(root, "bionetgen", bng2_root)
    env = os.environ.copy()
    env["BNG2_PERL"] = str((bng2_root / "bng2/BNG2.pl").resolve())
    env["BNGPATH"] = str((bng2_root / "bng2").resolve())
    env["BNG3_CI_STRICT_ORACLES"] = "1"

    net = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(root / "tests/validation/pytest.ini"),
            str(root / "tests/validation/test_parity_net.py"),
            "-m",
            "smoke",
            "--bng-cpp",
            str(bng_cpp),
            "-q",
        ],
        cwd=root,
        env=env,
    )
    expr = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(root / "tests/validation/pytest.ini"),
            str(root / "tests/validation/test_parity_expressions.py"),
            "--bng-cpp",
            str(bng_cpp),
            "-q",
        ],
        cwd=root,
        env=env,
    )
    references = {"bionetgen": {"revision": pin}}
    net_ok = net.returncode == 0
    expr_ok = expr.returncode == 0
    net_detail = (
        (net.stdout + "\n" + net.stderr).strip().splitlines()[-1]
        if (net.stdout or net.stderr).strip()
        else ""
    )
    expr_detail = (
        (expr.stdout + "\n" + expr.stderr).strip().splitlines()[-1]
        if (expr.stdout or expr.stderr).strip()
        else ""
    )
    results = [
        _row_result(
            "bngl.ast.model",
            net_ok,
            "tests/validation/test_parity_net.py",
            net_detail,
        ),
        _row_result(
            "bngl.observables.counting-modes",
            net_ok,
            "tests/validation/test_parity_net.py",
            net_detail,
        ),
        _row_result(
            "expression.builtins.shared-table",
            expr_ok,
            "tests/validation/test_parity_expressions.py",
            expr_detail,
        ),
    ]
    return references, results


def run_nfsim(
    root: Path, *, nfsim_root: Path, nfsim_bin: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pin = _verify_pin(root, "nfsim", nfsim_root)
    env = os.environ.copy()
    env["NFSIM_BIN"] = str(nfsim_bin.resolve())
    env["BNG3_RECONCILIATION_NFSIM_SOURCE"] = str(nfsim_root.resolve())

    recon = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(root / "tests/validation/pytest.ini"),
            str(root / "tests/validation/test_reconciliation_nfsim.py"),
            "-q",
        ],
        cwd=root,
        env=env,
    )
    energy = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            f"--confcutdir={root / 'tests/validation/release/cases/issue-177'}",
            "-q",
            str(root / "tests/validation/release/cases/issue-177"),
        ],
        cwd=root,
        env=env,
    )
    recon_ok = recon.returncode == 0
    energy_ok = energy.returncode == 0
    recon_detail = (
        (recon.stdout + "\n" + recon.stderr).strip().splitlines()[-1]
        if (recon.stdout or recon.stderr).strip()
        else ""
    )
    energy_detail = (
        (energy.stdout + "\n" + energy.stderr).strip().splitlines()[-1]
        if (energy.stdout or energy.stderr).strip()
        else ""
    )
    references = {
        "nfsim": {"revision": pin},
        "analytic": {
            "law": "Arrhenius barrier cancellation, detailed balance, and King-Altman NESS derivations in docs/nonequilibrium_energy.md"
        },
    }
    results = [
        _row_result(
            "nfsim.molecule-types",
            recon_ok,
            "tests/validation/test_reconciliation_nfsim.py",
            recon_detail,
        ),
        _row_result(
            "nfsim.seed-species",
            recon_ok,
            "tests/validation/test_reconciliation_nfsim.py",
            recon_detail,
        ),
        _row_result(
            "nfsim.observables",
            recon_ok,
            "tests/validation/test_reconciliation_nfsim.py",
            recon_detail,
        ),
        _row_result(
            "nfsim.energy-and-time-functions",
            energy_ok,
            "tests/validation/release/cases/issue-177/contract.json",
            energy_detail,
        ),
    ]
    return references, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", required=True, choices=("structural", "bng2", "nfsim")
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--bng-cpp", type=Path)
    parser.add_argument("--bng2-root", type=Path)
    parser.add_argument("--nfsim-root", type=Path)
    parser.add_argument("--nfsim-bin", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    head = _git_head(root)
    dirty = _git_dirty(root)
    if head != args.revision or (dirty and not args.allow_dirty):
        parser.error("issue-137 case execution requires the requested clean revision")

    if args.mode == "structural":
        references, results = run_structural(root)
    elif args.mode == "bng2":
        if not args.bng_cpp or not args.bng2_root:
            parser.error("--mode bng2 requires --bng-cpp and --bng2-root")
        references, results = run_bng2(
            root, bng_cpp=args.bng_cpp, bng2_root=args.bng2_root
        )
    else:
        if not args.nfsim_root or not args.nfsim_bin:
            parser.error("--mode nfsim requires --nfsim-root and --nfsim-bin")
        references, results = run_nfsim(
            root, nfsim_root=args.nfsim_root, nfsim_bin=args.nfsim_bin
        )

    payload = {
        "schema_version": 1,
        "source": {"revision": args.revision, "dirty": bool(dirty)},
        "check_id": f"issue-137-cases-{args.mode}",
        "references": references,
        "results": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for row in results:
        print(f"{row['id']}: {row['status']}")
    return int(any(row["status"] != "PASS" for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
