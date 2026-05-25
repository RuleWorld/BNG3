"""Trajectory validation: Run bng_cpp on validation models and compare .gdat output.

Compares BNG3 simulation trajectories against BNG2 reference .gdat/.cdat files
to verify numerical correctness of the ODE integrator.

Usage:
    python scripts/validate_trajectories.py [--bng-cpp PATH] [--ref-dir PATH] [--verbose] [--tolerance TOL]
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import numpy as np


# Models suitable for ODE trajectory comparison (deterministic, no stochastic)
TRAJECTORY_MODELS = [
    "Motivating_example",
    "CaOscillate_Func",
    "CaOscillate_Sat",
    "Haugh2b",
    "Repressilator",
    "egfr_net",
    "gene_expr_simple",
]


def parse_gdat(path):
    """Parse a .gdat file into a numpy array with column names."""
    if not os.path.exists(path):
        return None, None

    with open(path, "r") as f:
        lines = f.readlines()

    if not lines:
        return None, None

    # First line is header (starts with #)
    header_line = lines[0].strip()
    if header_line.startswith("#"):
        header_line = header_line[1:].strip()
    columns = header_line.split()

    data = []
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        values = [float(x) for x in line.split()]
        data.append(values)

    if not data:
        return None, None

    return np.array(data), columns


def compare_trajectories(ref_data, test_data, ref_cols, test_cols, tolerance=1e-3):
    """Compare two trajectory arrays within relative tolerance.

    Returns (passed, max_relative_error, details).
    """
    if ref_data is None or test_data is None:
        return False, float("inf"), "Missing data"

    # Match columns by name
    common_cols = []
    for i, col in enumerate(ref_cols):
        if col in test_cols:
            common_cols.append((col, i, test_cols.index(col)))

    if not common_cols:
        return False, float("inf"), "No matching columns"

    # Compare time points (may differ in count — interpolate if needed)
    ref_times = ref_data[:, 0]
    test_times = test_data[:, 0]

    max_rel_error = 0.0
    worst_col = ""

    for col_name, ref_idx, test_idx in common_cols:
        if col_name == "time":
            continue

        ref_values = ref_data[:, ref_idx]
        test_values = test_data[:, test_idx]

        # If different number of time points, interpolate test onto ref time grid
        if len(ref_times) != len(test_times) or not np.allclose(ref_times, test_times, rtol=1e-6):
            test_values = np.interp(ref_times, test_times, test_values)

        # Compute relative error (with floor to avoid division by near-zero)
        scale = np.maximum(np.abs(ref_values), 1e-10)
        rel_error = np.abs(ref_values - test_values) / scale
        col_max_error = np.max(rel_error)

        if col_max_error > max_rel_error:
            max_rel_error = col_max_error
            worst_col = col_name

    passed = max_rel_error < tolerance
    details = f"max_rel_error={max_rel_error:.2e} (column: {worst_col})"
    return passed, max_rel_error, details


def run_model(bng_cpp, bngl_path, work_dir):
    """Run bng_cpp on a .bngl file and return path to .gdat output."""
    # Ensure DLLs next to executable and MinGW runtime are findable
    env = os.environ.copy()
    bng_dir = str(Path(bng_cpp).parent)
    extra_paths = [bng_dir]
    # Add common MinGW DLL locations
    for p in [r"C:\Strawberry\c\bin", r"C:\mingw64\bin", r"C:\msys64\mingw64\bin"]:
        if os.path.isdir(p):
            extra_paths.append(p)
    env["PATH"] = os.pathsep.join(extra_paths) + os.pathsep + env.get("PATH", "")

    # Copy bngl to work_dir so output goes there
    import shutil
    local_bngl = Path(work_dir) / Path(bngl_path).name
    shutil.copy2(str(bngl_path), str(local_bngl))

    result = subprocess.run(
        [bng_cpp, str(local_bngl)],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if result.returncode != 0:
        return None, result.stderr

    # Find .gdat file in work directory
    for f in Path(work_dir).glob("*.gdat"):
        return f, None

    return None, "No .gdat file produced"


def main():
    parser = argparse.ArgumentParser(description="Validate BNG3 simulation trajectories")
    parser.add_argument("--bng-cpp", default=None, help="Path to bng_cpp binary")
    parser.add_argument("--ref-dir", default=None, help="Path to reference DAT_validate directory")
    parser.add_argument("--model-dir", default=None, help="Path to validation BNGL models")
    parser.add_argument("--tolerance", type=float, default=1e-3, help="Relative error tolerance")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--models", nargs="*", default=None, help="Specific models to test")
    args = parser.parse_args()

    # Find bng_cpp binary
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    if args.bng_cpp:
        bng_cpp = args.bng_cpp
    else:
        # Search common build locations
        candidates = [
            project_root / "build" / "cpp" / "bng_cpp",
            project_root / "build" / "cpp" / "bng_cpp.exe",
            project_root / "build" / "Release" / "bng_cpp.exe",
        ]
        bng_cpp = None
        for c in candidates:
            if c.exists():
                bng_cpp = str(c)
                break
        if not bng_cpp:
            print("ERROR: Cannot find bng_cpp binary. Use --bng-cpp to specify.")
            sys.exit(1)

    # Find reference data
    if args.ref_dir:
        ref_dir = Path(args.ref_dir)
    else:
        ref_dir = project_root.parent.parent / "temp" / "bionetgen" / "bng2" / "Validate" / "DAT_validate"
        if not ref_dir.exists():
            # Try relative to script
            ref_dir = project_root / "tests" / "reference_data"

    if args.model_dir:
        model_dir = Path(args.model_dir)
    else:
        model_dir = project_root.parent.parent / "temp" / "bionetgen" / "bng2" / "Validate"
        if not model_dir.exists():
            model_dir = project_root / "models" / "validate"

    models = args.models or TRAJECTORY_MODELS

    print(f"BNG3 Trajectory Validation")
    print(f"  bng_cpp:   {bng_cpp}")
    print(f"  ref_dir:   {ref_dir}")
    print(f"  model_dir: {model_dir}")
    print(f"  tolerance: {args.tolerance}")
    print(f"  models:    {len(models)}")
    print()

    passed = 0
    failed = 0
    skipped = 0

    for model_name in models:
        bngl_path = model_dir / f"{model_name}.bngl"
        ref_gdat = ref_dir / f"{model_name}.gdat"

        if not bngl_path.exists():
            if args.verbose:
                print(f"  SKIP {model_name}: .bngl not found")
            skipped += 1
            continue

        if not ref_gdat.exists():
            if args.verbose:
                print(f"  SKIP {model_name}: reference .gdat not found")
            skipped += 1
            continue

        # Run in temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            gdat_path, error = run_model(bng_cpp, bngl_path, tmpdir)

            if gdat_path is None:
                print(f"  FAIL {model_name}: execution failed — {error[:100] if error else 'unknown'}")
                failed += 1
                continue

            # Compare
            ref_data, ref_cols = parse_gdat(ref_gdat)
            test_data, test_cols = parse_gdat(gdat_path)

            ok, max_err, details = compare_trajectories(
                ref_data, test_data, ref_cols, test_cols, args.tolerance
            )

            if ok:
                print(f"  PASS {model_name} ({details})")
                passed += 1
            else:
                print(f"  FAIL {model_name} ({details})")
                failed += 1

    print()
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
