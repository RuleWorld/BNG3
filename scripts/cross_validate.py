"""Run structural C++ versus Perl network cross-validation.

The Perl engine is the independent BNG2 oracle for this gate.  Both engines
run in isolated temporary directories and their generated ``.net`` files are
compared through the typed graph-aware comparator used by the other validation
tiers.  A species-count match is not sufficient evidence of parity.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Optional, Union

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.validate import copy_referenced_support_files  # noqa: E402
from tests.validation.compare import NetDiff, compare_net, parse_net  # noqa: E402


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_ACTION_LINE = re.compile(r"^\s*([A-Za-z_]\w*)\s*\(")
_SKIP_ACTIONS = {
    "generate_network",
    "saveConcentrations",
    "saveParameters",
    "simulate",
    "simulate_ode",
    "simulate_nf",
    "simulate_pla",
    "simulate_psa",
    "simulate_ssa",
    "visualize",
    "writeMfile",
    "writeMexfile",
    "writeNetwork",
    "writeSBML",
    "writeSBMLMulti",
    "writeXML",
}


def _network_only_text(source: str) -> str:
    """Keep model construction actions and append one deterministic net build."""

    kept_lines: list[str] = []
    kept_actions: list[str] = []
    section: Optional[str] = None
    for line in source.splitlines():
        stripped = line.strip()
        begin = re.match(r"^begin\s+(.+?)\s*$", stripped, re.IGNORECASE)
        end = re.match(r"^end\s+(.+?)\s*$", stripped, re.IGNORECASE)
        if begin:
            section = begin.group(1).strip().lower()
            if section in {"actions", "protocol"}:
                continue
            kept_lines.append(line)
            continue
        if end:
            if section in {"actions", "protocol"}:
                section = None
                continue
            kept_lines.append(line)
            section = None
            continue

        match = _ACTION_LINE.match(line)
        if section == "protocol":
            continue
        if section == "actions" or (section is None and match):
            if match and match.group(1) not in _SKIP_ACTIONS:
                kept_actions.append(line)
            continue
        kept_lines.append(line)

    while kept_lines and not kept_lines[-1].strip():
        kept_lines.pop()
    kept_lines.extend(("", "begin actions"))
    kept_lines.extend(f"  {line.strip()}" for line in kept_actions)
    kept_lines.append("  generate_network({overwrite=>1})")
    kept_lines.append("end actions")
    return "\n".join(kept_lines) + "\n"


def _stage_model(model: Path, models_dir: Path, work_dir: Path) -> Path:
    """Copy one network-only model and its explicitly referenced support files."""

    work_dir.mkdir(parents=True, exist_ok=True)
    staged_model = work_dir / model.name
    staged_model.write_text(
        _network_only_text(model.read_text(encoding="utf-8")), encoding="utf-8"
    )

    input_dir = models_dir / "INPUT_FILES"
    if input_dir.is_dir():
        shutil.copytree(input_dir, work_dir / "INPUT_FILES", dirs_exist_ok=True)

    copy_referenced_support_files(
        model,
        models_dir,
        models_dir / "DAT_validate",
        work_dir,
    )
    return staged_model


def compare_network_files(
    reference_net: Union[Path, str], test_net: Union[Path, str]
) -> Optional[NetDiff]:
    """Compare two generated ``.net`` files, or return ``None`` on parse failure."""

    reference = parse_net(reference_net)
    test = parse_net(test_net)
    if reference is None or test is None:
        return None
    return compare_net(reference, test)


def _short_process_error(result: subprocess.CompletedProcess) -> str:
    output = (result.stderr or result.stdout or "").strip().splitlines()
    return output[0][:240] if output else f"exit {result.returncode}"


def _run_engine(
    command: list[str],
    work_dir: Path,
    timeout: float,
    environment: Optional[dict[str, str]] = None,
) -> tuple[Optional[subprocess.CompletedProcess], Optional[str]]:
    """Run one engine and turn timeout/launch failures into audit text."""

    try:
        env = os.environ.copy()
        if environment:
            env.update(environment)
        return (
            subprocess.run(
                command,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            ),
            None,
        )
    except subprocess.TimeoutExpired:
        return None, f"timeout after {timeout:g}s"
    except OSError as exc:
        return None, f"could not launch engine: {exc}"


def run_cross_validation(
    bng_cpp: Union[Path, str],
    bng_perl: Union[Path, str],
    models_dir: Union[Path, str],
    *,
    perl_executable: str = "perl",
    timeout: float = 60,
    model_names: Optional[Iterable[str]] = None,
    verbose: bool = False,
) -> tuple[dict[str, int], list[str]]:
    """Generate and structurally compare C++/Perl networks for each model."""

    cpp_path = Path(bng_cpp).resolve()
    perl_path = Path(bng_perl).resolve()
    corpus = Path(models_dir).resolve()
    requested = set(model_names or ())
    models = sorted(corpus.glob("*.bngl"))
    if requested:
        models = [model for model in models if model.stem in requested]

    results = {"pass": 0, "fail": 0, "error": 0}
    details: list[str] = []
    if not models:
        return results, ["ERROR cross-validation (no BNGL models selected)"]

    for model in models:
        model_name = model.stem
        with tempfile.TemporaryDirectory(prefix=f"bng3-cross-{model_name}-") as root:
            root_path = Path(root)
            cpp_dir = root_path / "cpp"
            perl_dir = root_path / "perl"
            cpp_model = _stage_model(model, corpus, cpp_dir)
            perl_model = _stage_model(model, corpus, perl_dir)

            cpp_result, cpp_error = _run_engine(
                [str(cpp_path), str(cpp_model)], cpp_dir, timeout
            )
            if cpp_error:
                results["error"] += 1
                details.append(f"ERROR {model_name} (C++ {cpp_error})")
                continue
            if cpp_result is None or cpp_result.returncode != 0:
                results["error"] += 1
                message = (
                    "C++ did not generate a network"
                    if cpp_result is None
                    else f"C++ {_short_process_error(cpp_result)}"
                )
                details.append(f"ERROR {model_name} ({message})")
                continue
            cpp_net = cpp_dir / f"{model_name}.net"
            if not cpp_net.is_file():
                results["error"] += 1
                details.append(f"ERROR {model_name} (missing C++ .net)")
                continue

            perl_result, perl_error = _run_engine(
                [
                    perl_executable,
                    str(perl_path),
                    "--outdir",
                    str(perl_dir),
                    str(perl_model),
                ],
                perl_dir,
                timeout,
                environment={"BNGPATH": str(perl_path.parent)},
            )
            if perl_error:
                results["error"] += 1
                details.append(f"ERROR {model_name} (Perl {perl_error})")
                continue
            if perl_result is None or perl_result.returncode != 0:
                results["error"] += 1
                message = (
                    "Perl did not generate a network"
                    if perl_result is None
                    else f"Perl {_short_process_error(perl_result)}"
                )
                details.append(f"ERROR {model_name} ({message})")
                continue

            perl_net = perl_dir / f"{model_name}.net"
            if not perl_net.is_file():
                results["error"] += 1
                details.append(f"ERROR {model_name} (missing Perl .net)")
                continue

            diff = compare_network_files(perl_net, cpp_net)
            if diff is None:
                results["error"] += 1
                details.append(f"ERROR {model_name} (network parse failure)")
                continue
            if diff.ok:
                results["pass"] += 1
                details.append(f"PASS  {model_name}")
                if verbose:
                    details.append(diff.summary())
            else:
                results["fail"] += 1
                details.append(f"FAIL  {model_name}")
                details.append(diff.summary())

    return results, details


def write_cross_validation_summary(
    summary_file: Union[Path, str],
    results: dict[str, int],
    bng_cpp: Union[Path, str],
    bng_perl: Union[Path, str],
    models_dir: Union[Path, str],
) -> None:
    """Append a provenance-bearing structural cross-validation summary."""

    summary_path = Path(summary_file)
    cpp_path = Path(bng_cpp)
    perl_path = Path(bng_perl)
    total = sum(results.values())
    source_revision = (
        os.environ.get("BNG3_SOURCE_REVISION")
        or os.environ.get("GITHUB_SHA")
        or "unavailable"
    )
    lines = [
        "### C++ vs Perl structural cross-validation",
        "",
        f"- BNG3 source revision: `{source_revision}`",
        f"- Validation corpus: `{Path(models_dir)}`",
        f"- bng_cpp: `{cpp_path}`",
        f"- bng_cpp SHA-256: `{_sha256_file(cpp_path)}`",
        f"- BNG2 oracle: `{perl_path}`",
        f"- BNG2 oracle SHA-256: `{_sha256_file(perl_path)}`",
        "- Comparison: graph-aware species, reaction, rate, and observable-group semantics",
        "",
        "| Total | Pass | Fail | Error |",
        "| ---: | ---: | ---: | ---: |",
        f"| {total} | {results['pass']} | {results['fail']} | {results['error']} |",
        "",
    ]
    with summary_path.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare bng_cpp and BNG2.pl generated networks structurally"
    )
    parser.add_argument("--bng-cpp", required=True, type=Path)
    parser.add_argument("--bng-perl", required=True, type=Path)
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=REPO / "tests" / "validation" / "Validate",
    )
    parser.add_argument("--perl-executable", default="perl")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--model", action="append", dest="model_names")
    parser.add_argument("--summary-file", type=Path)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    for label, path in (
        ("bng_cpp", args.bng_cpp),
        ("BNG2.pl", args.bng_perl),
    ):
        if not path.is_file():
            parser.error(f"{label} not found: {path}")
    if not args.models_dir.is_dir():
        parser.error(f"model directory not found: {args.models_dir}")

    results, details = run_cross_validation(
        args.bng_cpp,
        args.bng_perl,
        args.models_dir,
        perl_executable=args.perl_executable,
        timeout=args.timeout,
        model_names=args.model_names,
        verbose=args.verbose,
    )
    for detail in details:
        print(detail)

    total = sum(results.values())
    print()
    print("=" * 60)
    print("CROSS-VALIDATION SUMMARY")
    print(f"  Total models: {total}")
    print(f"  PASS:  {results['pass']}")
    print(f"  FAIL:  {results['fail']}")
    print(f"  ERROR: {results['error']}")
    print("=" * 60)

    if args.summary_file:
        write_cross_validation_summary(
            args.summary_file,
            results,
            args.bng_cpp,
            args.bng_perl,
            args.models_dir,
        )

    if total == 0 or results["fail"] or results["error"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
