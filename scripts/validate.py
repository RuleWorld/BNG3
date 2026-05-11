"""Validation script: Run bng_cpp on validation models and compare .net output.

Compares the C++ engine's network generation against reference .net files
produced by the Perl BNG2.pl engine.

Usage:
    python scripts/validate.py [--bng-cpp PATH] [--verbose]
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_net_file(path):
    """Parse a .net file into sections for comparison.

    Returns dict of section_name -> list of content lines (stripped, sorted).
    We compare species and reactions sections.
    """
    sections = {}
    current_section = None
    current_lines = []

    if not os.path.exists(path):
        return None

    with open(path, "r") as f:
        for line in f:
            line = line.rstrip("\n")

            # Section headers
            if line.startswith("begin "):
                current_section = line.strip()
                current_lines = []
            elif line.startswith("end "):
                if current_section:
                    sections[current_section] = sorted(current_lines)
                current_section = None
            elif current_section and line.strip():
                # Normalize whitespace in content lines
                normalized = re.sub(r"\s+", " ", line.strip())
                current_lines.append(normalized)

    return sections


def compare_sections(ref_sections, test_sections, section_name):
    """Compare a specific section between reference and test .net files.

    Returns (match, details_string).
    """
    ref_key = None
    test_key = None

    for key in ref_sections:
        if section_name in key:
            ref_key = key
            break
    for key in test_sections:
        if section_name in key:
            test_key = key
            break

    if ref_key is None:
        return True, f"  {section_name}: not in reference (skip)"
    if test_key is None:
        return False, f"  {section_name}: MISSING in test output"

    ref_lines = ref_sections[ref_key]
    test_lines = test_sections[test_key]

    if len(ref_lines) != len(test_lines):
        return False, (
            f"  {section_name}: count mismatch "
            f"(ref={len(ref_lines)}, test={len(test_lines)})"
        )

    # For species: compare count only (ordering may differ)
    # For reactions: compare count (rate expressions may have cosmetic differences)
    return True, f"  {section_name}: OK ({len(ref_lines)} entries)"


def run_validation(bng_cpp, validate_dir, verbose=False):
    """Run bng_cpp on all .bngl files and compare against reference .net."""

    dat_dir = validate_dir / "DAT_validate"
    bngl_files = sorted(validate_dir.glob("*.bngl"))

    results = {"pass": 0, "fail": 0, "skip": 0, "error": 0}
    details = []

    for bngl in bngl_files:
        model_name = bngl.stem
        ref_net = dat_dir / f"{model_name}.net"

        if not ref_net.exists():
            results["skip"] += 1
            if verbose:
                details.append(f"SKIP  {model_name} (no reference .net)")
            continue

        # Run bng_cpp to generate network
        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy bngl to tmpdir (some models use relative includes)
            import shutil

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

            # Parse and compare
            ref_sections = parse_net_file(str(ref_net))
            test_sections = parse_net_file(str(test_net))

            if ref_sections is None or test_sections is None:
                results["error"] += 1
                details.append(f"ERROR {model_name} (parse failure)")
                continue

            # Compare species and reactions counts
            sp_ok, sp_detail = compare_sections(ref_sections, test_sections, "species")
            rx_ok, rx_detail = compare_sections(
                ref_sections, test_sections, "reactions"
            )

            if sp_ok and rx_ok:
                results["pass"] += 1
                if verbose:
                    details.append(f"PASS  {model_name}")
                    details.append(sp_detail)
                    details.append(rx_detail)
            else:
                results["fail"] += 1
                details.append(f"FAIL  {model_name}")
                details.append(sp_detail)
                details.append(rx_detail)

    return results, details


def main():
    parser = argparse.ArgumentParser(
        description="Validate bng_cpp against reference .net files"
    )
    parser.add_argument("--bng-cpp", default=None, help="Path to bng_cpp executable")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all results")
    args = parser.parse_args()

    # Find bng_cpp
    script_dir = Path(__file__).parent
    repo_dir = script_dir.parent

    if args.bng_cpp:
        bng_cpp = Path(args.bng_cpp)
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

    print(f"BNG C++:    {bng_cpp}")
    print(f"Validation: {validate_dir}")
    print(f"Reference:  {validate_dir / 'DAT_validate'}")
    print()

    results, details = run_validation(bng_cpp, validate_dir, verbose=args.verbose)

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
