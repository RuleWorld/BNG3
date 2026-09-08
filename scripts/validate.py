"""Validation script: run bng_cpp and compare typed .net output.

Compares the C++ engine's network generation against reference .net files
produced by the Perl BNG2.pl engine.  Network equality is structural: species
strings and reaction multisets (including resolved rate expressions) are
compared through ``tests.validation.compare`` rather than by section counts.

Usage:
    python scripts/validate.py [--bng-cpp PATH] [--verbose]
    python scripts/validate.py [--bng-cpp PATH] --skip-file PATH --skip-profile NAME
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Union

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.validation.compare import compare_net, parse_net  # noqa: E402

_FILE_ARGUMENT = re.compile(r"\b(?:file|argfile)\s*=>\s*(['\"])([^'\"]+)\1")


def load_skip_models(skip_file: Union[Path, str], profile: str) -> list[str]:
    """Load one validated reference-exclusion profile from a JSON manifest."""

    path = Path(skip_file)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"cannot read reference exclusion manifest {path}: {exc}"
        ) from exc

    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError(
            f"reference exclusion manifest {path} must use schema_version 1"
        )

    profiles = manifest.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError(f"reference exclusion manifest {path} must contain profiles")

    models = profiles.get(profile)
    if not isinstance(models, list) or any(
        not isinstance(model, str) or not model.strip() for model in models
    ):
        raise ValueError(
            f"reference exclusion profile {profile!r} must be a list of names"
        )
    if len(models) != len(set(models)):
        raise ValueError(f"reference exclusion profile {profile!r} contains duplicates")

    return list(models)


def copy_referenced_support_files(
    bngl: Path, validate_dir: Path, dat_dir: Path, work_dir: Path
) -> list[Path]:
    """Stage files named by model file arguments into a validation work tree.

    Validation runs in an isolated directory.  Besides the BNGL input and the
    explicit ``INPUT_FILES`` directory, legacy models may reference a sibling
    ``.net`` or another artifact from the BNG2 reference directory.  Copy the
    referenced relative path, preserving subdirectories, so actions observe
    the same file layout as the source model.
    """

    copied: list[Path] = []
    text = bngl.read_text(encoding="utf-8")
    for match in _FILE_ARGUMENT.finditer(text):
        relative = Path(match.group(2))
        if relative.is_absolute() or ".." in relative.parts:
            continue

        candidates = [
            validate_dir / relative,
            dat_dir / relative,
            dat_dir / relative.name,
            validate_dir / relative.name,
        ]
        source = next(
            (candidate for candidate in candidates if candidate.is_file()), None
        )
        if source is None:
            continue

        destination = work_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(destination)

    return copied


def run_validation(
    bng_cpp, validate_dir, verbose=False, skip_models=None, strict_references=False
):
    """Run bng_cpp on all .bngl files and compare against reference .net.

    Args:
        bng_cpp: Path to bng_cpp executable
        validate_dir: Path to validation directory
        verbose: Whether to print detailed output
        skip_models: List of model names (without .bngl) to skip
        strict_references: Treat an unskipped missing reference .net as an error
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
            if strict_references:
                results["error"] += 1
                details.append(f"ERROR {model_name} (no reference .net)")
            else:
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
            copy_referenced_support_files(bngl, validate_dir, dat_dir, Path(tmpdir))

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
    parser.add_argument(
        "--skip-file",
        type=Path,
        default=None,
        help="JSON manifest containing named reference-exclusion profiles",
    )
    parser.add_argument(
        "--skip-profile",
        default=None,
        help="Profile to load from --skip-file",
    )
    parser.add_argument(
        "--strict-references",
        action="store_true",
        help="Treat an unskipped model without a reference .net as an error",
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

    if bool(args.skip_file) != bool(args.skip_profile):
        parser.error("--skip-file and --skip-profile must be provided together")

    # Parse skip list
    skip_models = [m.strip() for m in args.skip.split(",") if m.strip()]
    if args.skip_file:
        try:
            skip_models.extend(load_skip_models(args.skip_file, args.skip_profile))
        except ValueError as exc:
            parser.error(str(exc))

    print(f"BNG C++:    {bng_cpp}")
    print(f"Validation: {validate_dir}")
    print(f"Reference:  {validate_dir / 'DAT_validate'}")
    if skip_models:
        print(f"Skipping:   {', '.join(skip_models)}")
    print()

    results, details = run_validation(
        bng_cpp,
        validate_dir,
        verbose=args.verbose,
        skip_models=skip_models,
        strict_references=args.strict_references,
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
    skip_note = (
        "explicit exclusions only"
        if args.strict_references
        else "explicit exclusions or no reference .net"
    )
    print(f"  SKIP:  {results['skip']} ({skip_note})")
    print("=" * 60)

    if results["fail"] > 0 or results["error"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
