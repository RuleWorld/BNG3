"""NFsim validation: Compare BNG3 in-process NFsim output against upstream NFsim binary.

Runs the same XML model through both BNG3's in-process NFsim and the upstream
NFsim binary (if available), comparing .gdat output within tolerance.

Usage:
    python scripts/validate_nfsim.py [--bng-cpp PATH] [--nfsim PATH] [--tolerance TOL] [--seed SEED]
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np


NFSIM_MODELS = [
    "simple_system",
    "tlbr/tlbr",
]


def parse_gdat(path):
    """Parse a .gdat file into column names and numpy array."""
    with open(path) as f:
        header = f.readline().strip()
    col_names = header.lstrip('#').split()
    data = np.loadtxt(path, comments='#')
    return col_names, data


def run_bng3_nfsim(bng_cpp, model_bngl, seed, output_dir):
    """Run model through BNG3 in-process NFsim."""
    cmd = [bng_cpp, str(model_bngl)]
    env = os.environ.copy()
    result = subprocess.run(cmd, cwd=output_dir, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        print(f"  BNG3 failed: {result.stderr[:500]}", file=sys.stderr)
        return None
    gdat_files = list(Path(output_dir).glob("*.gdat"))
    return gdat_files[0] if gdat_files else None


def run_upstream_nfsim(nfsim_bin, model_xml, seed, sim_time, output_dir):
    """Run model through upstream NFsim binary."""
    output_gdat = Path(output_dir) / "nfsim_output.gdat"
    cmd = [
        nfsim_bin,
        "-xml", str(model_xml),
        "-seed", str(seed),
        "-sim", str(sim_time),
        "-oSteps", "50",
        "-o", str(output_gdat),
    ]
    result = subprocess.run(cmd, cwd=output_dir, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Upstream NFsim failed: {result.stderr[:500]}", file=sys.stderr)
        return None
    return output_gdat if output_gdat.exists() else None


def compare_gdat(file1, file2, tolerance):
    """Compare two .gdat files within tolerance. Returns (pass, message)."""
    try:
        names1, data1 = parse_gdat(file1)
        names2, data2 = parse_gdat(file2)
    except Exception as e:
        return False, f"Parse error: {e}"

    if data1.shape != data2.shape:
        return False, f"Shape mismatch: {data1.shape} vs {data2.shape}"

    # Compare time columns
    time_diff = np.max(np.abs(data1[:, 0] - data2[:, 0]))
    if time_diff > tolerance:
        return False, f"Time column mismatch (max diff={time_diff})"

    # Compare observable columns
    for col in range(1, data1.shape[1]):
        col_diff = np.max(np.abs(data1[:, col] - data2[:, col]))
        rel_scale = max(np.max(np.abs(data1[:, col])), 1.0)
        rel_diff = col_diff / rel_scale
        if rel_diff > tolerance:
            col_name = names1[col] if col < len(names1) else f"col{col}"
            return False, f"Column '{col_name}' mismatch (relative diff={rel_diff:.6f})"

    return True, "OK"


def main():
    parser = argparse.ArgumentParser(description="Validate NFsim output between BNG3 and upstream")
    parser.add_argument("--bng-cpp", default="build/bng_cpp", help="Path to bng_cpp binary")
    parser.add_argument("--nfsim", default="", help="Path to upstream NFsim binary (optional)")
    parser.add_argument("--tolerance", type=float, default=0.1, help="Relative tolerance for comparison")
    parser.add_argument("--seed", type=int, default=12345, help="Random seed")
    parser.add_argument("--models-dir", default="models", help="Directory containing .bngl models")
    args = parser.parse_args()

    models_dir = Path(args.models_dir)
    bng_cpp = Path(args.bng_cpp)

    if not bng_cpp.exists():
        print(f"ERROR: bng_cpp not found at {bng_cpp}", file=sys.stderr)
        sys.exit(1)

    passed = 0
    failed = 0
    skipped = 0

    for model_name in NFSIM_MODELS:
        model_path = models_dir / (model_name + ".bngl")
        if not model_path.exists():
            print(f"  SKIP {model_name}: file not found")
            skipped += 1
            continue

        print(f"  Testing {model_name}...")

        with tempfile.TemporaryDirectory() as tmpdir:
            bng3_gdat = run_bng3_nfsim(str(bng_cpp), model_path, args.seed, tmpdir)
            if bng3_gdat is None:
                print(f"  FAIL {model_name}: BNG3 produced no output")
                failed += 1
                continue

            if args.nfsim and Path(args.nfsim).exists():
                # Compare against upstream
                nfsim_gdat = run_upstream_nfsim(args.nfsim, model_path, args.seed, 100, tmpdir)
                if nfsim_gdat is None:
                    print(f"  SKIP {model_name}: upstream NFsim failed")
                    skipped += 1
                    continue

                ok, msg = compare_gdat(bng3_gdat, nfsim_gdat, args.tolerance)
                if ok:
                    print(f"  PASS {model_name}")
                    passed += 1
                else:
                    print(f"  FAIL {model_name}: {msg}")
                    failed += 1
            else:
                # Just verify BNG3 produces valid output
                try:
                    _, data = parse_gdat(bng3_gdat)
                    if data.size > 0:
                        print(f"  PASS {model_name} (BNG3 only, no upstream comparison)")
                        passed += 1
                    else:
                        print(f"  FAIL {model_name}: empty output")
                        failed += 1
                except Exception as e:
                    print(f"  FAIL {model_name}: {e}")
                    failed += 1

    print(f"\nResults: {passed} passed, {failed} failed, {skipped} skipped")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
