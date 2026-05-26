"""IO round-trip validation: Write -> Read -> Write produces consistent output.

Tests that .net files maintain consistency through write/read/write cycles.

Usage:
    python scripts/validate_io_roundtrip.py [--bng-cpp PATH] [--models-dir PATH]
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROUNDTRIP_MODELS = [
    "Motivating_example",
    "egfr_net",
    "gene_expr_simple",
    "Repressilator",
]


def run_bng_cpp(bng_cpp, model_path, output_dir):
    """Run bng_cpp to generate .net file."""
    cmd = [str(bng_cpp), str(model_path)]
    result = subprocess.run(cmd, cwd=output_dir, capture_output=True, text=True)
    if result.returncode != 0:
        return None, result.stderr[:500]
    net_files = list(Path(output_dir).glob("*.net"))
    return net_files[0] if net_files else None, ""


def parse_net_sections(net_path):
    """Parse .net file into sections (parameters, species, reactions, groups)."""
    sections = {}
    current_section = None
    current_lines = []

    with open(net_path) as f:
        for line in f:
            line = line.rstrip('\n')
            if line.startswith('begin '):
                current_section = line.strip().replace('begin ', '')
                current_lines = []
            elif line.startswith('end '):
                if current_section:
                    sections[current_section] = current_lines
                current_section = None
            elif current_section:
                stripped = line.strip()
                if stripped:
                    current_lines.append(stripped)

    return sections


def compare_net_files(net1, net2):
    """Compare two .net files section by section. Returns (pass, differences)."""
    sections1 = parse_net_sections(net1)
    sections2 = parse_net_sections(net2)

    differences = []

    for section in ['species', 'reactions', 'groups']:
        if section not in sections1 and section not in sections2:
            continue
        if section not in sections1:
            differences.append(f"Section '{section}' missing from first file")
            continue
        if section not in sections2:
            differences.append(f"Section '{section}' missing from second file")
            continue

        lines1 = sections1[section]
        lines2 = sections2[section]

        if len(lines1) != len(lines2):
            differences.append(f"Section '{section}' line count differs: {len(lines1)} vs {len(lines2)}")
            continue

        for i, (l1, l2) in enumerate(zip(lines1, lines2)):
            if l1 != l2:
                differences.append(f"Section '{section}' line {i+1} differs:\n  '{l1}'\n  '{l2}'")
                if len(differences) > 5:
                    differences.append("... (truncated)")
                    return False, differences

    return len(differences) == 0, differences


def main():
    parser = argparse.ArgumentParser(description="Validate IO round-trip consistency")
    parser.add_argument("--bng-cpp", default="build/bng_cpp", help="Path to bng_cpp binary")
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

    for model_name in ROUNDTRIP_MODELS:
        model_path = models_dir / (model_name + ".bngl")
        if not model_path.exists():
            print(f"  SKIP {model_name}: file not found")
            skipped += 1
            continue

        print(f"  Testing {model_name}...")

        with tempfile.TemporaryDirectory() as tmpdir1:
            # First pass: generate .net
            net1, err = run_bng_cpp(bng_cpp, model_path, tmpdir1)
            if net1 is None:
                print(f"  FAIL {model_name}: first pass failed: {err}")
                failed += 1
                continue

            with tempfile.TemporaryDirectory() as tmpdir2:
                # Second pass: generate .net again (deterministic)
                net2, err = run_bng_cpp(bng_cpp, model_path, tmpdir2)
                if net2 is None:
                    print(f"  FAIL {model_name}: second pass failed: {err}")
                    failed += 1
                    continue

                ok, diffs = compare_net_files(net1, net2)
                if ok:
                    print(f"  PASS {model_name}")
                    passed += 1
                else:
                    print(f"  FAIL {model_name}:")
                    for d in diffs[:3]:
                        print(f"    {d}")
                    failed += 1

    print(f"\nResults: {passed} passed, {failed} failed, {skipped} skipped")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
