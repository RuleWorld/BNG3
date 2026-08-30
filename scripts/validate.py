"""Validation script: run bng_cpp and compare typed .net output.

Compares the C++ engine's network generation against reference .net files
produced by the Perl BNG2.pl engine.  Network equality is structural: species
strings and reaction multisets (including resolved rate expressions) are
compared through ``tests.validation.compare`` rather than by section counts.

Usage:
    python scripts/validate.py [--bng-cpp PATH] [--verbose]
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.validation.compare import compare_net, parse_net  # noqa: E402


def run_validation(bng_cpp, validate_dir, verbose=False, skip_models=None):
    """Run bng_cpp on all .bngl files and compare against reference .net.

    Args:
        bng_cpp: Path to bng_cpp executable
        validate_dir: Path to validation directory
        verbose: Whether to print detailed output
        skip_models: List of model names (without .bngl) to skip
    """
    if skip_models is None:
        skip_models = []

    dat_dir = validate_dir / "DAT_validate"
    bngl_files = sorted(validate_dir.glob("*.bngl"))

    results = {"pass": 0, "fail": 0, "skip": 0, "error": 0}
    details = []

    for bngl in bngl_files:
        model_name = bngl.stem

        if model_name in skip_models:
            results["skip"] += 1
            if verbose:
                details.append(f"SKIP  {model_name} (excluded)")
            continue

        ref_net = dat_dir / f"{model_name}.net"

        if not ref_net.exists():
            results["skip"] += 1
            if verbose:
                details.append(f"SKIP  {model_name} (no reference .net)")
            continue

        # Run bng_cpp to generate network
        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy bngl to tmpdir (some models use relative includes)
            tmp_bngl = Path(tmpdir) / bngl.name
            shutil.copy(bngl, tmp_bngl)

            # Also copy any INPUT_FILES if they exist
            input_dir = validate_dir / "INPUT_FILES"
            if input_dir.exists():
                for f in input_dir.iterdir():
                    shutil.copy(f, Path(tmpdir) / f.name)

            try:
                result = subprocess.run(
                    [str(bng_cpp), str(tmp_bngl)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=tmpdir,
                )
            except subprocess.TimeoutExpired:
                results["error"] += 1
                details.append(f"ERROR {model_name} (timeout)")
                continue
            except FileNotFoundError:
                print(f"ERROR: bng_cpp not found at {bng_cpp}")
                sys.exit(1)

            # Find generated .net file
            test_net = Path(tmpdir) / f"{model_name}.net"

            if not test_net.exists():
                # Check if it errored
                if result.returncode != 0:
                    results["error"] += 1
                    err_msg = (
                        result.stderr[:200] if result.stderr else result.stdout[:200]
                    )
                    details.append(
                        f"ERROR {model_name} (exit {result.returncode}): {err_msg}"
                    )
                else:
                    results["error"] += 1
                    details.append(f"ERROR {model_name} (no .net generated)")
                continue

            # Parse and compare through the typed validation comparator.  This
            # catches changed species identity and reaction topology even when
            # section counts happen to be unchanged.
            ref_network = parse_net(ref_net)
            test_network = parse_net(test_net)

            if ref_network is None or test_network is None:
                results["error"] += 1
                details.append(f"ERROR {model_name} (parse failure)")
                continue

            diff = compare_net(ref_network, test_network)
            if diff.ok:
                results["pass"] += 1
                if verbose:
                    details.append(f"PASS  {model_name}")
                    details.append(diff.summary())
            else:
                results["fail"] += 1
                details.append(f"FAIL  {model_name}")
                details.append(diff.summary())

    return results, details


def main():
    parser = argparse.ArgumentParser(
        description="Validate bng_cpp against reference .net files"
    )
    parser.add_argument("--bng-cpp", default=None, help="Path to bng_cpp executable")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all results")
    parser.add_argument(
        "--skip",
        default="",
        help="Comma-separated list of model names to skip (without .bngl extension)",
    )
    args = parser.parse_args()

    # Find bng_cpp
    repo_dir = REPO

    if args.bng_cpp:
        bng_cpp = Path(args.bng_cpp).resolve()
        if not bng_cpp.exists():
            print(f"ERROR: bng_cpp not found at {bng_cpp}")
            sys.exit(1)
    else:
        # Try common build locations
        candidates = [
            repo_dir / "build" / "cpp" / "bng_cpp.exe",
            repo_dir / "build" / "cpp" / "bng_cpp",
            repo_dir / "build" / "Release" / "bng_cpp.exe",
        ]
        bng_cpp = None
        for c in candidates:
            if c.exists():
                bng_cpp = c
                break
        if bng_cpp is None:
            print("ERROR: Cannot find bng_cpp executable. Build first or use --bng-cpp")
            sys.exit(1)

    # Find validation directory
    validate_dir = repo_dir / "tests" / "validation" / "Validate"
    if not validate_dir.exists():
        print(f"ERROR: Validation directory not found: {validate_dir}")
        sys.exit(1)

    # Parse skip list
    skip_models = [m.strip() for m in args.skip.split(",") if m.strip()]

    print(f"BNG C++:    {bng_cpp}")
    print(f"Validation: {validate_dir}")
    print(f"Reference:  {validate_dir / 'DAT_validate'}")
    if skip_models:
        print(f"Skipping:   {', '.join(skip_models)}")
    print()

    results, details = run_validation(
        bng_cpp, validate_dir, verbose=args.verbose, skip_models=skip_models
    )

    # Print details
    for line in details:
        print(line)

    # Summary
    total = sum(results.values())
    print()
    print("=" * 60)
    print(f"VALIDATION SUMMARY")
    print(f"  Total models: {total}")
    print(f"  PASS:  {results['pass']}")
    print(f"  FAIL:  {results['fail']}")
    print(f"  ERROR: {results['error']}")
    print(f"  SKIP:  {results['skip']} (no reference .net)")
    print("=" * 60)

    if results["fail"] > 0 or results["error"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
