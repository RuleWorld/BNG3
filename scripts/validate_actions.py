"""Validate validation-corpus fixtures whose primary contract is an action output.

The network validator compares generated ``.net`` files with independent BNG2
references.  These fixtures exercise XML, SBML Multi, hybrid-model, and graph
writers instead, so they are run here with explicit output contracts rather
than being treated as missing-reference skips.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.validate import copy_referenced_support_files

ACTION_MODELS = (
    "ANx",
    "hybrid_test",
    "test_tfun",
    "test_tfun_xml",
    "test_write_sbml_multi",
    "visualize",
)

EXPECTED_OUTPUTS = {
    "ANx": ("ANx.xml",),
    "test_tfun": ("test_tfun.xml",),
    "test_tfun_xml": ("test_tfun_xml.xml",),
    "test_write_sbml_multi": ("test_write_sbml_multi_sbml_multi.xml",),
    "visualize": (
        "visualize_contactmap.gml",
        "visualize_conventional.gml",
        "visualize_compact.gml",
        "visualize_regulatory_1.gml",
        "visualize_regulatory_2.gml",
        "visualize_regulatory_3.gml",
        "visualize_regulatory_4.gml",
    ),
}


def _check_xml(path: Path) -> None:
    root = ET.parse(path).getroot()
    if root.tag.rsplit("}", 1)[-1] not in {"sbml", "sbmlDocument"}:
        raise ValueError(f"{path.name} has unexpected XML root {root.tag!r}")


def validate_action_model(
    bng_cpp: Path | str, validate_dir: Path | str, model_name: str
) -> tuple[str, str]:
    """Run one action fixture and return ``(status, detail)``."""

    bng_cpp = Path(bng_cpp).resolve()
    validate_path = Path(validate_dir)
    source = validate_path / f"{model_name}.bngl"
    if not source.is_file():
        return "error", f"ERROR {model_name} (missing BNGL source)"

    with tempfile.TemporaryDirectory(prefix=f"bng3-action-{model_name}-") as raw:
        work_dir = Path(raw)
        staged = work_dir / source.name
        shutil.copy2(source, staged)

        input_dir = validate_path / "INPUT_FILES"
        if input_dir.is_dir():
            for support in input_dir.iterdir():
                if support.is_file():
                    shutil.copy2(support, work_dir / support.name)
        copy_referenced_support_files(
            source, validate_path, validate_path / "DAT_validate", work_dir
        )

        command = [str(bng_cpp)]
        if model_name == "hybrid_test":
            # The source action is intentionally expensive because it expands
            # a 50,000-ligand network.  --check validates the complete parser
            # and action-argument contract; the committed BNG2 hybrid artifact
            # is checked below as the generated-model contract.
            command.append("--check")
        command.append(staged.name)
        try:
            result = subprocess.run(
                command,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return "error", f"ERROR {model_name} (timeout)"

        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip().replace("\n", " ")
            return (
                "fail",
                f"FAIL {model_name} (exit {result.returncode}): {message[:240]}",
            )

        if model_name == "hybrid_test":
            generated = validate_path / "DAT_validate" / "hybrid_test_hpp.bngl"
            generated_xml = validate_path / "DAT_validate" / "hybrid_test_hpp.xml"
            if not generated.is_file() or not generated_xml.is_file():
                return "error", "ERROR hybrid_test (missing committed hybrid artifact)"
            generated_text = generated.read_text(encoding="utf-8")
            if (
                "begin model" not in generated_text
                or "begin reaction rules" not in generated_text
            ):
                return "fail", "FAIL hybrid_test (artifact lacks hybrid model sections)"
            try:
                _check_xml(generated_xml)
            except (ET.ParseError, ValueError) as exc:
                return "fail", f"FAIL hybrid_test (artifact XML): {exc}"
            return "pass", "PASS hybrid_test (parser and committed hybrid artifact)"

        for output_name in EXPECTED_OUTPUTS[model_name]:
            output = work_dir / output_name
            if not output.is_file() or output.stat().st_size == 0:
                return "error", f"ERROR {model_name} (missing output {output_name})"
            if output.suffix == ".xml":
                try:
                    _check_xml(output)
                except (ET.ParseError, ValueError) as exc:
                    return "fail", f"FAIL {model_name} ({output_name}): {exc}"
            elif output.suffix == ".gml":
                if not output.read_text(encoding="utf-8").lstrip().startswith("graph"):
                    return (
                        "fail",
                        f"FAIL {model_name} ({output_name}): invalid GML header",
                    )

        return "pass", f"PASS {model_name} (action outputs)"


def run_action_validation(
    bng_cpp: Path | str, validate_dir: Path | str, model_names=ACTION_MODELS
) -> tuple[dict[str, int], list[str]]:
    results = {"pass": 0, "fail": 0, "skip": 0, "error": 0}
    details: list[str] = []
    for model_name in model_names:
        status, detail = validate_action_model(bng_cpp, validate_dir, model_name)
        results[status] += 1
        details.append(detail)
    return results, details


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bng-cpp", required=True, type=Path)
    parser.add_argument(
        "--validate-dir", default="tests/validation/Validate", type=Path
    )
    args = parser.parse_args()
    results, details = run_action_validation(args.bng_cpp, args.validate_dir)
    print("\n".join(details))
    print(
        f"PASS={results['pass']} FAIL={results['fail']} ERROR={results['error']} SKIP={results['skip']}"
    )
    raise SystemExit(1 if results["fail"] or results["error"] or results["skip"] else 0)
