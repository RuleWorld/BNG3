"""Run structural C++ versus Perl network/export cross-validation.

The Perl engine is the independent BNG2 oracle for this gate.  Both engines
run in isolated temporary directories and their generated ``.net`` files are
compared through the typed graph-aware comparator used by the other validation
tiers.  The ANx, hybrid_test, and test_write_sbml_multi fixtures retain their
authored XML-export actions and compare the generated model sections instead.
A species-count match is not sufficient evidence of parity.
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
import xml.etree.ElementTree as ET
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
    "parameter_scan",
    "resetConcentrations",
    "saveConcentrations",
    "saveParameters",
    "simulate",
    "simulate_ode",
    "simulate_nf",
    "simulate_pla",
    "simulate_ps",
    "simulate_psa",
    "simulate_rm",
    "simulate_ssa",
    "visualize",
    "writeMfile",
    "writeMexfile",
    "writeNetwork",
    "writeSBML",
    "writeSBMLMulti",
    "writeXML",
}


_READ_NET_FILE = re.compile(
    r"""\breadFile\s*\(\s*\{[^}]*\bfile\s*=>\s*['"][^'"]+\.net['"]""",
    re.IGNORECASE,
)

_AUTHORED_EXPORTS = {
    "ANx": (
        {"cpp": "ANx.xml", "perl": "ANx.xml"},
        (
            "ListOfMoleculeTypes",
            "ListOfSpecies",
            "ListOfReactionRules",
            "ListOfObservables",
            "ListOfFunctions",
        ),
        "molecule types, species, rules, observables, functions",
    ),
    "hybrid_test": (
        {"cpp": "hybrid_test_hpp.xml", "perl": "hybrid_test_hpp.xml"},
        (
            "ListOfMoleculeTypes",
            "ListOfSpecies",
            "ListOfReactionRules",
            "ListOfObservables",
            "ListOfFunctions",
        ),
        "molecule types, species, rules, observables, functions",
    ),
    "test_write_sbml_multi": (
        {
            "cpp": "test_write_sbml_multi_sbml_multi.xml",
            "perl": "test_write_sbml_multi_sbml_sbmlmulti.xml",
        },
        ("listOfSpeciesTypes", "listOfSpecies", "listOfReactions"),
        "Multi species types, species, reactions",
    ),
}
_XML_IDREF_ATTRIBUTES = {
    "bindingSite1",
    "bindingSite2",
    "component",
    "compartment",
    "parent",
    "parentComponent",
    "productComponent",
    "reactant",
    "reactantComponent",
    "species",
    "speciesReference",
    "speciesType",
    "speciesTypeInstance",
    "site1",
    "site2",
    "sourceID",
    "targetID",
    "variable",
}
_XML_METADATA_ATTRIBUTES = {"args"}
_XML_NAMED_ID_TAGS = {
    "MoleculeType",
    "Observable",
    "ReactionRule",
    "Species",
    "species",
    "speciesType",
}


def _network_only_text(
    source: str,
    *,
    preserve_network_writer: bool = False,
    write_tfun_xml: bool = False,
) -> str:
    """Keep model setup and generation actions; remove simulation/output actions."""

    kept_lines: list[str] = []
    kept_actions: list[str] = []
    has_network_action = False
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
            if match and match.group(1) == "generate_network":
                kept_actions.append(line.strip())
                has_network_action = True
                continue
            if (
                preserve_network_writer
                and match
                and match.group(1) in {"resetConcentrations", "writeNetwork"}
            ):
                kept_actions.append(line.strip())
                continue
            if match and match.group(1) not in _SKIP_ACTIONS:
                # Declarations such as setOption are legal at top level but
                # not inside BNG3's action grammar. Preserve their scope.
                if section is None and match.group(1) in {
                    "setOption",
                    "setModelName",
                    "substanceUnits",
                    "version",
                }:
                    kept_lines.append(line)
                else:
                    kept_actions.append(line)
            continue
        kept_lines.append(line)

    while kept_lines and not kept_lines[-1].strip():
        kept_lines.pop()
    kept_lines.extend(("", "begin actions"))
    kept_lines.extend(f"  {line.strip()}" for line in kept_actions)
    # Network imports already carry a network. SBML/XML imports still need a
    # generation action unless the source provided one explicitly.
    if not has_network_action and not any(
        _READ_NET_FILE.search(action) for action in kept_actions
    ):
        kept_lines.append("  generate_network({overwrite=>1})")
    if write_tfun_xml and re.search(r"\bTFUN\s*\(", source):
        kept_lines.append("  writeXML({overwrite=>1})")
    kept_lines.append("end actions")
    return "\n".join(kept_lines) + "\n"


def _stage_model(
    model: Path,
    models_dir: Path,
    work_dir: Path,
    *,
    support_roots: Iterable[Path] = (),
    preserve_network_writer: bool = False,
    write_tfun_xml: bool = False,
) -> Path:
    """Copy one network-only model and its explicitly referenced support files."""

    work_dir.mkdir(parents=True, exist_ok=True)
    staged_model = work_dir / model.name
    staged_model.write_text(
        _network_only_text(
            model.read_text(encoding="utf-8"),
            preserve_network_writer=preserve_network_writer,
            write_tfun_xml=write_tfun_xml,
        ),
        encoding="utf-8",
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
    for root in support_roots:
        copy_referenced_support_files(
            model,
            root,
            root / "DAT_validate",
            work_dir,
        )
    return staged_model


def _stage_authored_action_model(model: Path, models_dir: Path, work_dir: Path) -> Path:
    """Stage an export fixture unchanged, with only its declared support files."""

    work_dir.mkdir(parents=True, exist_ok=True)
    staged_model = work_dir / model.name
    shutil.copy2(model, staged_model)

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


def _semantic_xml_ids(model: ET.Element) -> dict[str, str]:
    """Map generated XML IDs to stable element labels for reference comparison."""

    aliases: dict[str, str] = {}
    counts: dict[str, int] = {}
    identity_attributes = ("name", "symbol", "variable")
    for element in model.iter():
        identifier = element.attrib.get("id")
        tag = element.tag.rsplit("}", 1)[-1]
        if not identifier or tag not in _XML_NAMED_ID_TAGS:
            continue
        identity = tuple(
            (name, " ".join(element.attrib[name].split()))
            for name in identity_attributes
            if name in element.attrib
        )
        if not identity:
            continue
        if tag == "ReactionRule" and identity:
            name, value = identity[0]
            if name == "name" and re.fullmatch(r"_R\d+", value):
                identity = ((name, value[1:]), *identity[1:])
        label = f"{tag}:{identity!r}"
        occurrence = counts.get(label, 0)
        counts[label] = occurrence + 1
        aliases[identifier] = f"{label}#{occurrence}"
    return aliases


def _xml_element_signature(
    element: ET.Element,
    aliases: dict[str, str],
    parameter_values: dict[str, str],
) -> tuple:
    """Return a whitespace- and namespace-prefix-independent XML signature."""

    tag = element.tag.rsplit("}", 1)[-1]
    tag_name = element.tag.rsplit("}", 1)[-1]
    normalized_attributes = dict(element.attrib)
    if tag_name == "ReactionRule" and re.fullmatch(
        r"_R\d+", normalized_attributes.get("name", "")
    ):
        normalized_attributes["name"] = normalized_attributes["name"][1:]
    if tag_name == "ReactionRule":
        normalized_attributes.setdefault("symmetry_factor", "1")
    attributes = tuple(
        sorted(
            (
                name.rsplit("}", 1)[-1],
                (
                    aliases.get(value, " ".join(value.split()))
                    if name.rsplit("}", 1)[-1] == "id"
                    or name.rsplit("}", 1)[-1] in _XML_IDREF_ATTRIBUTES
                    else " ".join(value.split())
                ),
            )
            for name, value in normalized_attributes.items()
            if name.rsplit("}", 1)[-1] not in _XML_METADATA_ATTRIBUTES
        )
    )
    attributes = tuple(
        (
            name,
            (
                parameter_values.get(value, value)
                if name in {"concentration", "initialAmount", "initialConcentration"}
                else value
            ),
        )
        for name, value in attributes
    )
    raw_text = element.text or ""
    text = (
        _normalize_expression_text(raw_text)
        if tag in {"Expression", "math"}
        else " ".join(raw_text.split())
    ) or None
    children = tuple(
        _xml_element_signature(child, aliases, parameter_values) for child in element
    )
    if tag.startswith("ListOf") and tag != "ListOfArguments":
        children = tuple(sorted(children, key=repr))
    return tag, attributes, text, children


def _normalize_expression_text(expression: str) -> str:
    """Remove insignificant whitespace and redundant outer grouping only."""

    normalized = "".join(expression.split())
    while normalized.startswith("(") and normalized.endswith(")"):
        depth = 0
        wraps_expression = True
        for index, character in enumerate(normalized):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(normalized) - 1:
                    wraps_expression = False
                    break
        if not wraps_expression or depth != 0:
            break
        normalized = normalized[1:-1]
    return normalized


def _structural_xml_signature(path: Path, sections: Iterable[str]) -> dict[str, tuple]:
    """Extract selected model XML sections for BNG2/BNG3 structural checks."""

    root = ET.parse(path).getroot()
    model = next(
        (
            element
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "model"
        ),
        None,
    )
    if model is None:
        raise ValueError(f"{path.name} has no model element")

    requested = set(sections)
    aliases = _semantic_xml_ids(model)
    parameter_values = {
        element.attrib["id"]: element.attrib["value"]
        for element in model.iter()
        if element.tag.rsplit("}", 1)[-1] == "Parameter"
        and "id" in element.attrib
        and "value" in element.attrib
        and element.attrib.get("type") == "Constant"
    }
    observed: dict[str, tuple] = {}
    for child in model:
        name = child.tag.rsplit("}", 1)[-1]
        if name in requested:
            observed[name] = tuple(
                sorted(
                    (
                        _xml_element_signature(item, aliases, parameter_values)
                        for item in child
                    ),
                    key=repr,
                )
            )

    for name in requested - set(observed):
        observed[name] = ()
    return observed


def compare_structural_xml(
    reference_xml: Union[Path, str],
    test_xml: Union[Path, str],
    *,
    sections: Iterable[str],
) -> tuple[bool, list[str]]:
    """Compare declared species/rule/function or SBML-Multi XML sections."""

    selected_sections = tuple(sections)
    reference = _structural_xml_signature(Path(reference_xml), selected_sections)
    test = _structural_xml_signature(Path(test_xml), selected_sections)
    differences = sorted(
        section for section in reference if reference[section] != test.get(section)
    )
    return not differences, differences


_CONTINUATION_BASES = {
    "michment_cont": "michment",
    "test_sat_cont": "test_sat",
}


def _prepare_continuation_input(
    engine: str,
    engine_path: Path,
    perl_executable: str,
    corpus: Path,
    work_dir: Path,
    model_name: str,
    timeout: float,
) -> Optional[str]:
    """Generate the base network needed by a legacy continuation model."""

    base_name = _CONTINUATION_BASES.get(model_name)
    if base_name is None:
        return None
    continuation_net = work_dir / f"{model_name}.net"
    # A staged DAT_validate network is not evidence that the prerequisite ran.
    continuation_net.unlink(missing_ok=True)
    base_source = corpus / f"{base_name}.bngl"
    if not base_source.is_file():
        return f"missing continuation base model {base_source.name}"
    base_model = _stage_model(
        base_source,
        corpus,
        work_dir,
        preserve_network_writer=True,
        write_tfun_xml=(engine == "Perl"),
    )
    # Staging the base may also find a same-named reference support file.
    # Remove it after staging so only writeNetwork from the producer can satisfy
    # the continuation input.
    continuation_net.unlink(missing_ok=True)
    if engine == "Perl":
        command = [
            perl_executable,
            str(engine_path),
            "--outdir",
            str(work_dir),
            str(base_model),
        ]
    else:
        command = [str(engine_path), str(base_model)]
    result, error = _run_engine(
        command,
        work_dir,
        timeout,
        environment=(
            {"BNGPATH": str(engine_path.parent)} if engine == "Perl" else None
        ),
    )
    if error:
        return f"{engine} base {base_name} {error}"
    if result is None or result.returncode != 0:
        detail = (
            "did not generate a network"
            if result is None
            else _short_process_error(result)
        )
        return f"{engine} base {base_name} {detail}"
    if not continuation_net.is_file():
        return f"{engine} base {base_name} did not write {continuation_net.name}"
    return None


def compare_network_files(
    reference_net: Union[Path, str],
    test_net: Union[Path, str],
    *,
    reference_tfun_xml: Optional[Union[Path, str]] = None,
) -> Optional[NetDiff]:
    """Compare two generated ``.net`` files, or return ``None`` on parse failure."""

    reference = parse_net(reference_net)
    test = parse_net(test_net)
    if reference is None or test is None:
        return None
    if reference_tfun_xml is None:
        return compare_net(reference, test)
    return compare_net(reference, test, reference_tfun_xml=reference_tfun_xml)


def _try_compare_network_files(
    reference_net: Path,
    test_net: Path,
    *,
    reference_tfun_xml: Optional[Path] = None,
) -> tuple[Optional[NetDiff], Optional[str]]:
    """Keep malformed or inconsistent oracle sidecars local to one model."""

    try:
        return (
            compare_network_files(
                reference_net, test_net, reference_tfun_xml=reference_tfun_xml
            ),
            None,
        )
    except (OSError, ValueError) as exc:
        return None, str(exc)


def _short_process_error(result: subprocess.CompletedProcess) -> str:
    output = f"{result.stderr or ''}\n{result.stdout or ''}".strip().splitlines()
    failures = [
        line.strip()
        for line in output
        if re.search(
            r"\b(ABORT|ERROR|Exception|Error|failed|Traceback|TypeError)\b", line
        )
    ]
    message = failures[-1] if failures else (output[0].strip() if output else "")
    return message[:240] if message else f"exit {result.returncode}"


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


def _run_authored_export_comparison(
    model: Path,
    cpp_path: Path,
    perl_path: Path,
    models_dir: Path,
    perl_executable: str,
    timeout: float,
) -> tuple[str, str]:
    """Run a fixture's authored export action in both engines and compare XML."""

    output_names, sections, label = _AUTHORED_EXPORTS[model.stem]
    with tempfile.TemporaryDirectory(prefix=f"bng3-export-{model.stem}-") as raw:
        root = Path(raw)
        cpp_dir = root / "cpp"
        perl_dir = root / "perl"
        cpp_model = _stage_authored_action_model(model, models_dir, cpp_dir)
        perl_model = _stage_authored_action_model(model, models_dir, perl_dir)

        cpp_result, cpp_error = _run_engine(
            [str(cpp_path), str(cpp_model)], cpp_dir, timeout
        )
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

        engine_status = []
        engine_errors = []
        for engine, result, error in (
            ("C++", cpp_result, cpp_error),
            ("BNG2", perl_result, perl_error),
        ):
            if error:
                engine_status.append(f"{engine}: {error}")
                engine_errors.append(f"{engine} {error}")
            elif result is None or result.returncode != 0:
                reason = (
                    "process did not return"
                    if result is None
                    else _short_process_error(result)
                )
                engine_status.append(f"{engine}: action failed: {reason}")
                engine_errors.append(f"{engine} action failed: {reason}")
            else:
                engine_status.append(f"{engine}: action completed")
        if engine_errors:
            return "error", f"ERROR {model.stem} ({'; '.join(engine_status)})"

        cpp_xml = cpp_dir / output_names["cpp"]
        perl_xml = perl_dir / output_names["perl"]
        missing = [
            f"{engine} {path.name}"
            for engine, path in (("C++", cpp_xml), ("Perl", perl_xml))
            if not path.is_file() or path.stat().st_size == 0
        ]
        if missing:
            return (
                "error",
                f"ERROR {model.stem} (missing authored output: {', '.join(missing)})",
            )

        try:
            equal, differences = compare_structural_xml(
                perl_xml, cpp_xml, sections=sections
            )
        except (ET.ParseError, OSError, ValueError) as exc:
            return "fail", f"FAIL {model.stem} (invalid structural XML: {exc})"
        if not equal:
            return (
                "fail",
                f"FAIL {model.stem} (C++/BNG2 structural XML differs: {', '.join(differences)})",
            )
        return "pass", f"PASS  {model.stem} (authored export: {label})"


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
        if model_name in _AUTHORED_EXPORTS:
            status, detail = _run_authored_export_comparison(
                model,
                cpp_path,
                perl_path,
                corpus,
                perl_executable,
                timeout,
            )
            results[status] += 1
            details.append(detail)
            continue

        with tempfile.TemporaryDirectory(prefix=f"bng3-cross-{model_name}-") as root:
            root_path = Path(root)
            cpp_dir = root_path / "cpp"
            perl_dir = root_path / "perl"
            cpp_model = _stage_model(model, corpus, cpp_dir)
            perl_model = _stage_model(model, corpus, perl_dir, write_tfun_xml=True)

            prerequisite_error = _prepare_continuation_input(
                "C++", cpp_path, perl_executable, corpus, cpp_dir, model_name, timeout
            )
            if prerequisite_error:
                results["error"] += 1
                details.append(f"ERROR {model_name} ({prerequisite_error})")
                continue
            prerequisite_error = _prepare_continuation_input(
                "Perl",
                perl_path,
                perl_executable,
                corpus,
                perl_dir,
                model_name,
                timeout,
            )
            if prerequisite_error:
                results["error"] += 1
                details.append(f"ERROR {model_name} ({prerequisite_error})")
                continue

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

            source_text = model.read_text(encoding="utf-8")
            tfun_xml = (
                perl_dir / f"{model_name}.xml"
                if re.search(r"\bTFUN\s*\(", source_text)
                else None
            )
            diff, comparison_error = _try_compare_network_files(
                perl_net, cpp_net, reference_tfun_xml=tfun_xml
            )
            if comparison_error:
                results["error"] += 1
                details.append(
                    f"ERROR {model_name} (reference comparison error: {comparison_error})"
                )
                continue
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
    details: Iterable[str] = (),
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
        "- Comparison: graph-aware network semantics plus authored XML export sections",
        "",
        "| Total | Pass | Fail | Error |",
        "| ---: | ---: | ---: | ---: |",
        f"| {total} | {results['pass']} | {results['fail']} | {results['error']} |",
        "",
    ]
    case_details = list(details)
    if case_details:
        lines.extend(["#### Per-model results", ""])
        lines.extend(f"- {detail}" for detail in case_details)
        lines.append("")
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
            details,
        )

    if total == 0 or results["fail"] or results["error"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
