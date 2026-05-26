"""SBML export validation: Check BNG3 SBML output for well-formedness.

Exports SBML from BNG3 for multiple models and validates using libsbml
(if available) or basic XML well-formedness checks.

Usage:
    python scripts/validate_sbml.py [--bng-cpp PATH] [--models-dir PATH]
"""

import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


SBML_TEST_MODELS = [
    "Motivating_example",
    "egfr_net",
    "Repressilator",
    "gene_expr_simple",
    "Haugh2b",
]


def run_bng_sbml(bng_cpp, model_path, output_dir):
    """Run bng_cpp with writeSBML action."""
    # Create a modified model that includes writeSBML
    model_text = model_path.read_text()

    # Check if model already has writeSBML action
    if "writeSBML" not in model_text and "writesbml" not in model_text.lower():
        # Add writeSBML action before end actions or at end
        if "end actions" in model_text:
            model_text = model_text.replace("end actions", "  writeSBML()\nend actions")
        else:
            model_text += "\nwriteSBML()\n"

    modified_path = Path(output_dir) / model_path.name
    modified_path.write_text(model_text)

    cmd = [str(bng_cpp), str(modified_path)]
    result = subprocess.run(cmd, cwd=output_dir, capture_output=True, text=True)
    if result.returncode != 0:
        return None, result.stderr[:500]

    xml_files = list(Path(output_dir).glob("*.xml"))
    return xml_files[0] if xml_files else None, ""


def validate_sbml_xml(xml_path):
    """Validate SBML XML structure."""
    errors = []

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError as e:
        return [f"XML parse error: {e}"]

    # Check namespace
    ns = root.tag.split('}')[0] + '}' if '}' in root.tag else ''
    if 'sbml' not in root.tag.lower():
        errors.append(f"Root element is not 'sbml': {root.tag}")

    # Check for required SBML elements
    model_elem = root.find(f'{ns}model')
    if model_elem is None:
        errors.append("Missing <model> element")
        return errors

    # Check for species
    species_list = model_elem.find(f'{ns}listOfSpecies')
    if species_list is None:
        errors.append("Missing <listOfSpecies>")
    else:
        species = species_list.findall(f'{ns}species')
        if len(species) == 0:
            errors.append("No species defined")

    # Check for reactions
    reactions_list = model_elem.find(f'{ns}listOfReactions')
    if reactions_list is None:
        errors.append("Missing <listOfReactions>")
    else:
        reactions = reactions_list.findall(f'{ns}reaction')
        if len(reactions) == 0:
            errors.append("No reactions defined")

    # Check for parameters
    params_list = model_elem.find(f'{ns}listOfParameters')
    if params_list is not None:
        params = params_list.findall(f'{ns}parameter')
        if len(params) == 0:
            errors.append("listOfParameters exists but is empty")

    return errors


def validate_with_libsbml(xml_path):
    """Validate using libsbml if available."""
    try:
        import libsbml
    except ImportError:
        return None  # libsbml not available

    doc = libsbml.readSBML(str(xml_path))
    num_errors = doc.getNumErrors()
    errors = []
    for i in range(num_errors):
        err = doc.getError(i)
        if err.getSeverity() >= libsbml.LIBSBML_SEV_ERROR:
            errors.append(f"L{err.getLine()}: {err.getMessage()}")
    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate SBML export")
    parser.add_argument("--bng-cpp", default="build/bng_cpp", help="Path to bng_cpp binary")
    parser.add_argument("--models-dir", default="models", help="Directory with .bngl models")
    args = parser.parse_args()

    bng_cpp = Path(args.bng_cpp)
    models_dir = Path(args.models_dir)

    if not bng_cpp.exists():
        print(f"ERROR: bng_cpp not found at {bng_cpp}", file=sys.stderr)
        sys.exit(1)

    passed = 0
    failed = 0
    skipped = 0

    for model_name in SBML_TEST_MODELS:
        model_path = models_dir / (model_name + ".bngl")
        if not model_path.exists():
            print(f"  SKIP {model_name}: file not found")
            skipped += 1
            continue

        print(f"  Testing {model_name}...")

        with tempfile.TemporaryDirectory() as tmpdir:
            xml_path, err = run_bng_sbml(bng_cpp, model_path, tmpdir)
            if xml_path is None:
                print(f"  FAIL {model_name}: export failed: {err}")
                failed += 1
                continue

            # Basic XML validation
            xml_errors = validate_sbml_xml(xml_path)
            if xml_errors:
                print(f"  FAIL {model_name}: {'; '.join(xml_errors[:3])}")
                failed += 1
                continue

            # libsbml validation (if available)
            libsbml_errors = validate_with_libsbml(xml_path)
            if libsbml_errors is not None and len(libsbml_errors) > 0:
                print(f"  FAIL {model_name} (libsbml): {'; '.join(libsbml_errors[:3])}")
                failed += 1
                continue

            print(f"  PASS {model_name}")
            passed += 1

    print(f"\nResults: {passed} passed, {failed} failed, {skipped} skipped")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
