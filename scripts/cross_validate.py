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
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Union

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.validate import copy_referenced_support_files  # noqa: E402
from tests.validation.compare import (
    NetDiff,
    _canon_expr,
    compare_net,
    parse_net,
)  # noqa: E402


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
_XML_LABEL_ATTRIBUTES = (
    "name",
    "id",
    "variable",
    "symbol",
    "species",
    "speciesType",
    "component",
    "reactant",
    "product",
    "sourceID",
    "targetID",
)
_XML_COMPONENT_MAPPING_TAGS = {
    "map",
    "mapitem",
    "listofspeciestypecomponentindexes",
    "speciestypecomponentindex",
    "speciestypecomponentmapinproduct",
    "speciestypeinstance",
    "listofspeciestypeinstances",
    "listofoutwardbindingsites",
    "outwardbindingsite",
    "listofspeciesfeatures",
    "speciesfeature",
}
_XML_RATE_LAW_TAGS = {
    "ratelaw",
    "listofrateconstants",
    "rateconstant",
    "kineticlaw",
    "rate",
    "listoflocalparameters",
    "localparameter",
}


@dataclass(frozen=True)
class XmlDifference:
    """One canonical XML difference with an element path and both values."""

    path: str
    reference: object
    test: object
    category: str
    kind: str
    semantic: bool = True


@dataclass(frozen=True)
class StructuralXmlComparison:
    """Semantic XML differences plus sections that differ only in representation."""

    sections: tuple[str, ...]
    differences: tuple[XmlDifference, ...]
    representation_only: tuple[str, ...]

    @property
    def equal(self) -> bool:
        return not self.sections

    def counts(self) -> dict[str, dict[str, int]]:
        counts: dict[str, Counter[str]] = {}
        for difference in self.differences:
            counts.setdefault(difference.category, Counter())[difference.kind] += 1
        return {category: dict(counter) for category, counter in counts.items()}

    def summary(self) -> str:
        if self.equal:
            return "canonical XML equal"
        parts = [
            f"{category} ({', '.join(f'{count} {kind}' for kind, count in sorted(kinds.items()))})"
            for category, kinds in self.counts().items()
        ]
        text = "; ".join(parts)
        if self.representation_only:
            text += (
                "; representation-only differences in "
                + ", ".join(self.representation_only)
            )
        return text


@dataclass(frozen=True)
class _XmlNode:
    tag: str
    attributes: tuple[tuple[str, str], ...]
    text: Optional[str]
    children: tuple["_XmlNode", ...]
    label: str

    @property
    def signature(self) -> tuple:
        return (
            self.tag,
            self.attributes,
            self.text,
            tuple(child.signature for child in self.children),
        )


def _xml_node_label(tag: str, attributes: tuple[tuple[str, str], ...]) -> str:
    values = dict(attributes)
    for name in _XML_LABEL_ATTRIBUTES:
        if values.get(name):
            return f"{tag}[{name}={values[name]!r}]"
    return tag


_XML_IDENTITY_ATTRIBUTES = ("name", "id")


def _xml_node_key(node: _XmlNode) -> tuple:
    """Group elements that name the same entity across the two exports.

    Only ``name``/``id`` identify an element. Positional lists such as
    ``Map``/``MapItem`` or ``ListOfRateConstants`` carry no identity, so their
    members pair by position and surface as value differences instead of a
    spurious missing/extra pair.
    """

    values = dict(node.attributes)
    for name in _XML_IDENTITY_ATTRIBUTES:
        if values.get(name):
            return node.tag, name, values[name]
    return node.tag, "", ""


def _xml_node_summary(node: _XmlNode, limit: int = 160) -> str:
    attributes = ", ".join(
        f"{name}={value!r}"
        for name, value in node.attributes
        if name in _XML_LABEL_ATTRIBUTES
        or name in {"value", "type", "population", "bindingStatus"}
    )
    text = f" text={node.text!r}" if node.text else ""
    summary = f"{node.tag}({attributes}){text}" if attributes or text else node.tag
    return summary if len(summary) <= limit else summary[: limit - 3] + "..."


def _format_xml_value(value: object, limit: int = 160) -> str:
    if value is None:
        return "<missing>"
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _classify_xml_difference(path: str, section: str) -> str:
    tags = {part.split("[", 1)[0].lower() for part in path.split("/")}
    if tags & _XML_COMPONENT_MAPPING_TAGS:
        return "component mapping"
    if tags & _XML_RATE_LAW_TAGS:
        return "rate law"
    if section == "ListOfSpecies" or section == "listOfSpecies":
        return "species"
    if section == "ListOfReactionRules" or section == "listOfReactions":
        return "reaction rule"
    if section == "ListOfMoleculeTypes":
        return "molecule type"
    if section == "listOfSpeciesTypes":
        return "species type"
    if section == "ListOfObservables":
        return "observable"
    if section == "ListOfFunctions":
        return "function"
    return "other"


def _xml_child_path(parent: str, node: _XmlNode, index: int, total: int) -> str:
    suffix = f"#{index}" if total > 1 else ""
    return f"{parent}/{node.label}{suffix}"


def _diff_xml_node_lists(
    reference: tuple[_XmlNode, ...],
    test: tuple[_XmlNode, ...],
    path: str,
    section: str,
) -> list[XmlDifference]:
    reference_by_key: dict[tuple, list[_XmlNode]] = {}
    test_by_key: dict[tuple, list[_XmlNode]] = {}
    for node in reference:
        reference_by_key.setdefault(_xml_node_key(node), []).append(node)
    for node in test:
        test_by_key.setdefault(_xml_node_key(node), []).append(node)

    differences: list[XmlDifference] = []
    for key in sorted(set(reference_by_key) | set(test_by_key), key=repr):
        reference_nodes = reference_by_key.get(key, [])
        test_nodes = test_by_key.get(key, [])
        total = max(len(reference_nodes), len(test_nodes))
        for index in range(total):
            reference_node = (
                reference_nodes[index] if index < len(reference_nodes) else None
            )
            test_node = test_nodes[index] if index < len(test_nodes) else None
            if reference_node is None:
                child_path = _xml_child_path(path, test_node, index, total)
                differences.append(
                    XmlDifference(
                        child_path,
                        None,
                        _xml_node_summary(test_node),
                        _classify_xml_difference(child_path, section),
                        "extra",
                    )
                )
            elif test_node is None:
                child_path = _xml_child_path(path, reference_node, index, total)
                differences.append(
                    XmlDifference(
                        child_path,
                        _xml_node_summary(reference_node),
                        None,
                        _classify_xml_difference(child_path, section),
                        "missing",
                    )
                )
            else:
                child_path = _xml_child_path(path, reference_node, index, total)
                differences.extend(
                    _diff_xml_nodes(reference_node, test_node, child_path, section)
                )
    return differences


def _diff_xml_nodes(
    reference: _XmlNode,
    test: _XmlNode,
    path: str,
    section: str,
) -> list[XmlDifference]:
    if reference.signature == test.signature:
        return []
    if reference.tag != test.tag:
        return [
            XmlDifference(
                path,
                reference.tag,
                test.tag,
                _classify_xml_difference(path, section),
                "value",
            )
        ]

    differences: list[XmlDifference] = []
    reference_attributes = dict(reference.attributes)
    test_attributes = dict(test.attributes)
    for name in sorted(set(reference_attributes) | set(test_attributes)):
        if reference_attributes.get(name) != test_attributes.get(name):
            attribute_path = f"{path}/@{name}"
            differences.append(
                XmlDifference(
                    attribute_path,
                    reference_attributes.get(name),
                    test_attributes.get(name),
                    _classify_xml_difference(attribute_path, section),
                    "value",
                )
            )
    if reference.text != test.text:
        text_path = f"{path}/text()"
        differences.append(
            XmlDifference(
                text_path,
                reference.text,
                test.text,
                _classify_xml_difference(text_path, section),
                "value",
            )
        )
    differences.extend(
        _diff_xml_node_lists(reference.children, test.children, path, section)
    )
    return differences


def format_structural_xml_differences(
    comparison: StructuralXmlComparison, *, limit: int = 20
) -> list[str]:
    """Format the first element-level differences with paths and both values."""

    lines = [
        f"{difference.path}: BNG2={_format_xml_value(difference.reference)} "
        f"C++={_format_xml_value(difference.test)} "
        f"[{difference.category}, {'semantic' if difference.semantic else 'representation-only'}]"
        for difference in comparison.differences[:limit]
    ]
    remaining = len(comparison.differences) - limit
    if remaining > 0:
        lines.append(f"... {remaining} more element-level difference(s) omitted")
    return lines


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
    # Generated rate helper names are local export IDs. Tie each helper to
    # the rule that references it, retaining the helper's complete definition.
    for rule in model.iter():
        if rule.tag.rsplit("}", 1)[-1] != "ReactionRule":
            continue
        for rate in rule:
            if rate.tag.rsplit("}", 1)[-1] != "RateLaw":
                continue
            name = rate.attrib.get("name", "")
            if rate.attrib.get("type") == "Function" and re.fullmatch(
                r"(?:_rateLaw\d+|__bng3_reaction_rate_\w+)", name
            ):
                owner = aliases.get(
                    rule.attrib.get("id", ""), rule.attrib.get("id", "")
                )
                aliases[name] = f"generated-rate:{owner}"
    # Bonds are undirected. Their enumeration does not identify the bond;
    # the endpoints do, including when an ID is referenced elsewhere.
    for bond in model.iter():
        if bond.tag.rsplit("}", 1)[-1] == "Bond" and "id" in bond.attrib:
            ends = sorted(bond.attrib.get(key, "") for key in ("site1", "site2"))
            aliases[bond.attrib["id"]] = f"bond:{ends!r}"
    return aliases


def _normalize_expression_text(expression: str) -> str:
    """Remove insignificant whitespace and redundant outer grouping only."""

    return _canon_expr(expression)


def _xml_element_node(
    element: ET.Element,
    aliases: dict[str, str],
    parameter_values: dict[str, str],
) -> _XmlNode:
    """Return a whitespace- and namespace-prefix-independent XML node."""

    tag = element.tag.rsplit("}", 1)[-1]
    normalized_attributes = dict(element.attrib)
    if tag == "ReactionRule" and re.fullmatch(
        r"_R\d+", normalized_attributes.get("name", "")
    ):
        normalized_attributes["name"] = normalized_attributes["name"][1:]
    if tag == "ReactionRule":
        normalized_attributes.setdefault("symmetry_factor", "1")
    if tag == "Observable":
        normalized_attributes.setdefault("output", "1")
    if tag == "Pattern":
        normalized_attributes.setdefault("automorphisms", "1")
    if tag in {"Bond", "AddBond", "DeleteBond"}:
        if "site1" in normalized_attributes and "site2" in normalized_attributes:
            ends = sorted(normalized_attributes[key] for key in ("site1", "site2"))
            normalized_attributes.update(zip(("site1", "site2"), ends))
    attributes = tuple(
        sorted(
            (
                name.rsplit("}", 1)[-1],
                (
                    aliases.get(value, " ".join(value.split()))
                    if name.rsplit("}", 1)[-1] == "id"
                    or name.rsplit("}", 1)[-1] in _XML_IDREF_ATTRIBUTES
                    or (tag == "RateLaw" and name == "name")
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
                or (
                    tag == "RateConstant"
                    and name == "value"
                    and re.fullmatch(r"_rateLaw\d+", value)
                )
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
        _xml_element_node(child, aliases, parameter_values) for child in element
    )
    if (tag.startswith("ListOf") and tag != "ListOfArguments") or tag == "Map":
        children = tuple(sorted(children, key=lambda child: repr(child.signature)))
    return _XmlNode(tag, attributes, text, children, _xml_node_label(tag, attributes))


def _xml_element_signature(
    element: ET.Element,
    aliases: dict[str, str],
    parameter_values: dict[str, str],
) -> tuple:
    """Return a whitespace- and namespace-prefix-independent XML signature."""

    return _xml_element_node(element, aliases, parameter_values).signature


def _model_element(path: Path) -> ET.Element:
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
    return model


def _parameter_values(model: ET.Element) -> dict[str, str]:
    return {
        element.attrib["id"]: element.attrib["value"]
        for element in model.iter()
        if element.tag.rsplit("}", 1)[-1] == "Parameter"
        and "id" in element.attrib
        and "value" in element.attrib
        and element.attrib.get("type") == "Constant"
    }


def _structural_xml_nodes(
    path: Path, sections: Iterable[str]
) -> dict[str, tuple[_XmlNode, ...]]:
    """Extract selected model XML sections as canonical nodes."""

    model = _model_element(path)
    requested = set(sections)
    aliases = _semantic_xml_ids(model)
    parameter_values = _parameter_values(model)
    observed: dict[str, tuple[_XmlNode, ...]] = {}
    for child in model:
        name = child.tag.rsplit("}", 1)[-1]
        if name in requested:
            observed[name] = tuple(
                sorted(
                    (
                        _xml_element_node(item, aliases, parameter_values)
                        for item in child
                    ),
                    key=lambda node: repr(node.signature),
                )
            )

    for name in requested - set(observed):
        observed[name] = ()
    return observed


def _structural_xml_signature(path: Path, sections: Iterable[str]) -> dict[str, tuple]:
    """Extract selected model XML sections for BNG2/BNG3 structural checks."""

    return {
        name: tuple(node.signature for node in nodes)
        for name, nodes in _structural_xml_nodes(path, sections).items()
    }


def _raw_structural_xml_signature(
    path: Path, sections: Iterable[str]
) -> dict[str, tuple[str, ...]]:
    """Extract selected sections without canonicalization to identify representation."""

    model = _model_element(path)
    requested = set(sections)
    observed: dict[str, tuple[str, ...]] = {}
    for child in model:
        name = child.tag.rsplit("}", 1)[-1]
        if name in requested:
            observed[name] = tuple(
                " ".join(ET.tostring(item, encoding="unicode").split())
                for item in child
            )
    for name in requested - set(observed):
        observed[name] = ()
    return observed


def diff_structural_xml(
    reference_xml: Union[Path, str],
    test_xml: Union[Path, str],
    *,
    sections: Iterable[str],
) -> StructuralXmlComparison:
    """Return categorized, element-level differences between two XML exports."""

    selected_sections = tuple(sections)
    reference_path = Path(reference_xml)
    test_path = Path(test_xml)
    reference = _structural_xml_nodes(reference_path, selected_sections)
    test = _structural_xml_nodes(test_path, selected_sections)
    reference_raw = _raw_structural_xml_signature(reference_path, selected_sections)
    test_raw = _raw_structural_xml_signature(test_path, selected_sections)

    differing_sections: list[str] = []
    representation_only: list[str] = []
    differences: list[XmlDifference] = []
    for section in selected_sections:
        reference_nodes = reference.get(section, ())
        test_nodes = test.get(section, ())
        reference_signatures = tuple(node.signature for node in reference_nodes)
        test_signatures = tuple(node.signature for node in test_nodes)
        if reference_signatures != test_signatures:
            differing_sections.append(section)
            differences.extend(
                _diff_xml_node_lists(
                    reference_nodes, test_nodes, section, section
                )
            )
        elif reference_raw.get(section, ()) != test_raw.get(section, ()):
            representation_only.append(section)

    return StructuralXmlComparison(
        sections=tuple(differing_sections),
        differences=tuple(differences),
        representation_only=tuple(representation_only),
    )


def compare_structural_xml(
    reference_xml: Union[Path, str],
    test_xml: Union[Path, str],
    *,
    sections: Iterable[str],
) -> tuple[bool, list[str]]:
    """Compare declared species/rule/function or SBML-Multi XML sections."""

    comparison = diff_structural_xml(
        reference_xml, test_xml, sections=sections
    )
    return comparison.equal, list(comparison.sections)


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


def _preserve_xml_artifacts(
    artifact_dir: Optional[Path],
    model_name: str,
    cpp_xml: Path,
    perl_xml: Path,
) -> list[Path]:
    """Copy both generated XML exports aside for CI inspection on failure."""

    if artifact_dir is None:
        return []
    artifact_dir.mkdir(parents=True, exist_ok=True)
    preserved: list[Path] = []
    for engine, source in (("cpp", cpp_xml), ("bng2", perl_xml)):
        if source.is_file():
            destination = artifact_dir / f"{model_name}.{engine}.xml"
            shutil.copy2(source, destination)
            preserved.append(destination)
    return preserved


def _run_authored_export_comparison(
    model: Path,
    cpp_path: Path,
    perl_path: Path,
    models_dir: Path,
    perl_executable: str,
    timeout: float,
    *,
    artifact_dir: Optional[Path] = None,
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
            preserved = _preserve_xml_artifacts(
                artifact_dir, model.stem, cpp_xml, perl_xml
            )
            detail = (
                f"ERROR {model.stem} (missing authored output: {', '.join(missing)})"
            )
            if preserved:
                detail += "\n  preserved artifacts: " + ", ".join(
                    str(path) for path in preserved
                )
            return "error", detail

        try:
            comparison = diff_structural_xml(
                perl_xml, cpp_xml, sections=sections
            )
        except (ET.ParseError, OSError, ValueError) as exc:
            preserved = _preserve_xml_artifacts(
                artifact_dir, model.stem, cpp_xml, perl_xml
            )
            detail = f"FAIL {model.stem} (invalid structural XML: {exc})"
            if preserved:
                detail += "\n  preserved artifacts: " + ", ".join(
                    str(path) for path in preserved
                )
            return "fail", detail
        if not comparison.equal:
            preserved = _preserve_xml_artifacts(
                artifact_dir, model.stem, cpp_xml, perl_xml
            )
            lines = [
                f"FAIL {model.stem} (C++/BNG2 structural XML differs: {', '.join(comparison.sections)})",
                f"  semantic differences: {comparison.summary()}",
            ]
            lines.extend(
                f"  {line}"
                for line in format_structural_xml_differences(comparison)
            )
            if preserved:
                lines.append(
                    "  preserved artifacts: "
                    + ", ".join(str(path) for path in preserved)
                )
            return "fail", "\n".join(lines)
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
    artifact_dir: Optional[Path] = None,
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
                artifact_dir=artifact_dir,
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
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        help="Preserve generated XML exports here when an authored export differs",
    )
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
        artifact_dir=args.artifact_dir,
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
