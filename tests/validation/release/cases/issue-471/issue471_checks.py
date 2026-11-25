"""Fail-closed consumers for issue #471 release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[5]
SUPPORTED_COMPARATORS = (
    "release-oracle-byte-equality-v1",
    "release-oracle-net-canonical-v1",
    "release-oracle-gdat-numeric-v1",
    "release-oracle-numeric-json-v1",
    "release-oracle-crn-bng2-v1",
    "release-oracle-bngl-hybrid-v1",
    "release-oracle-bngl-xml-v1",
)


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _artifact_bytes(
    artifact_root: Path, relative_path: Any
) -> tuple[bytes | None, str | None]:
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        return None, "artifact path must be a nonempty POSIX relative path"
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        return (
            None,
            "artifact path must not be absolute or contain traversal components",
        )
    root = artifact_root.resolve()
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return None, "artifact path must not traverse symlinks"
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root):
            return None, "artifact path escapes the artifact root"
        if not resolved.is_file():
            return None, "artifact path is not a regular file"
        return resolved.read_bytes(), None
    except OSError as exc:
        return None, f"artifact cannot be read: {exc}"


def _compare_net_bytes(oracle_bytes: bytes, consumer_bytes: bytes) -> tuple[bool, str]:
    """Compare raw pinned-oracle and consumer .net files via canonical structure."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tests.validation import compare

    try:
        oracle_text = oracle_bytes.decode("utf-8")
        consumer_text = consumer_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return False, f"invalid UTF-8 in .net output: {exc}"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        oracle_path = tmp / "oracle.net"
        consumer_path = tmp / "consumer.net"
        oracle_path.write_text(oracle_text, encoding="utf-8")
        consumer_path.write_text(consumer_text, encoding="utf-8")
        ref = compare.parse_net(oracle_path)
        sub = compare.parse_net(consumer_path)
    if ref is None or sub is None:
        return False, "could not parse .net output"
    diff = compare.compare_net(ref, sub)
    return diff.ok, ("" if diff.ok else diff.summary())


def _compare_gdat_bytes(
    oracle_bytes: bytes,
    consumer_bytes: bytes,
    *,
    rtol: float = 1e-6,
    atol: float = 1e-10,
) -> tuple[bool, str]:
    """Compare raw pinned-oracle and consumer .gdat tables numerically."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import numpy as np
    from tests.validation import compare

    try:
        oracle_text = oracle_bytes.decode("utf-8")
        consumer_text = consumer_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return False, f"invalid UTF-8 in .gdat output: {exc}"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        oracle_path = tmp / "oracle.gdat"
        consumer_path = tmp / "consumer.gdat"
        oracle_path.write_text(oracle_text, encoding="utf-8")
        consumer_path.write_text(consumer_text, encoding="utf-8")
        ref_vals, ref_cols = compare.parse_gdat(oracle_path)
        sub_vals, sub_cols = compare.parse_gdat(consumer_path)
    if ref_vals is None or sub_vals is None or ref_cols is None or sub_cols is None:
        return False, "could not parse .gdat output"
    if ref_cols != sub_cols:
        return False, f"column mismatch: oracle={ref_cols} consumer={sub_cols}"
    if ref_vals.shape != sub_vals.shape or ref_vals.shape[0] == 0:
        return (
            False,
            f"shape mismatch: oracle={ref_vals.shape} consumer={sub_vals.shape}",
        )
    if not (np.isfinite(ref_vals).all() and np.isfinite(sub_vals).all()):
        return False, "non-finite values in .gdat trajectory"
    if not np.allclose(ref_vals, sub_vals, rtol=rtol, atol=atol, equal_nan=False):
        max_abs = float(np.max(np.abs(ref_vals - sub_vals)))
        return False, f"numeric trajectory mismatch (max_abs={max_abs:.3e})"
    return True, ""


def _compare_numeric_json_bytes(
    oracle_bytes: bytes,
    consumer_bytes: bytes,
    *,
    rtol: float = 1e-9,
    atol: float = 1e-12,
) -> tuple[bool, str]:
    """Compare flat numeric JSON dictionaries within strict tolerance."""
    try:
        oracle_data = json.loads(oracle_bytes.decode("utf-8"))
        consumer_data = json.loads(consumer_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return False, f"invalid numeric JSON output: {exc}"
    if (
        not isinstance(oracle_data, dict)
        or not isinstance(consumer_data, dict)
        or not oracle_data
    ):
        return False, "numeric JSON payload must be a non-empty object"
    if set(oracle_data) != set(consumer_data):
        return (
            False,
            f"numeric JSON key mismatch: oracle={sorted(oracle_data)} consumer={sorted(consumer_data)}",
        )
    for key in sorted(oracle_data):
        ref_val = oracle_data[key]
        sub_val = consumer_data[key]
        if (
            isinstance(ref_val, bool)
            or isinstance(sub_val, bool)
            or not isinstance(ref_val, (int, float))
            or not isinstance(sub_val, (int, float))
        ):
            return False, f"non-numeric value for key {key!r}"
        ref_f = float(ref_val)
        sub_f = float(sub_val)
        if not (math.isfinite(ref_f) and math.isfinite(sub_f)):
            return False, f"non-finite value for key {key!r}"
        if not math.isclose(ref_f, sub_f, rel_tol=rtol, abs_tol=atol):
            return (
                False,
                f"numeric mismatch at {key!r}: oracle={ref_f!r} consumer={sub_f!r}",
            )
    return True, ""


def _parse_bng2_net_crn(
    net_text: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    section = None
    species: list[str] = []
    reactions: list[dict[str, Any]] = []
    for line in net_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("begin "):
            section = stripped.removeprefix("begin ")
            continue
        if stripped.startswith("end "):
            section = None
            continue
        if section == "species" and stripped and not stripped.startswith("#"):
            species.append(stripped.split()[1])
        elif section == "reactions" and stripped and not stripped.startswith("#"):
            body, _, comment = stripped.partition("#")
            fields = body.split()
            if len(fields) < 4:
                raise ValueError(f"unexpected BNG2 .net reaction row: {line!r}")
            reactants = (
                ()
                if fields[1] == "0"
                else tuple(int(value) - 1 for value in fields[1].split(","))
            )
            products = (
                ()
                if fields[2] == "0"
                else tuple(int(value) - 1 for value in fields[2].split(","))
            )
            reactions.append(
                {
                    "reactants": reactants,
                    "products": products,
                    "rate": fields[3],
                    "rule": comment.strip(),
                }
            )
    return species, reactions


def _compare_crn_bng2_bytes(
    oracle_bytes: bytes, consumer_bytes: bytes
) -> tuple[bool, str]:
    """Compare BNG2 .net CRN structure against model.to_crn() JSON."""
    try:
        bng2_species, bng2_reactions = _parse_bng2_net_crn(oracle_bytes.decode("utf-8"))
        crn = json.loads(consumer_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return False, f"invalid CRN/NET payload: {exc}"
    if not isinstance(crn, dict):
        return False, "consumer CRN payload must be an object"
    crn_species = [item.get("name") for item in crn.get("species", [])]
    if not bng2_species or crn_species != bng2_species:
        return False, f"CRN species mismatch: bng2={bng2_species} crn={crn_species}"
    bng2_complexes: list[tuple[int, ...]] = []
    for reaction in bng2_reactions:
        for side in (reaction["reactants"], reaction["products"]):
            if side not in bng2_complexes:
                bng2_complexes.append(side)
    crn_complexes = [
        tuple(item.get("species", [])) for item in crn.get("complexes", [])
    ]
    if crn_complexes != bng2_complexes:
        return False, "CRN complexes mismatch"
    bng2_matrix = [[0] * len(bng2_reactions) for _ in bng2_species]
    for col, reaction in enumerate(bng2_reactions):
        for sp in reaction["reactants"]:
            bng2_matrix[sp][col] -= 1
        for sp in reaction["products"]:
            bng2_matrix[sp][col] += 1
    if crn.get("stoichiometric_matrix") != bng2_matrix:
        return False, "CRN stoichiometric matrix mismatch"
    crn_reactions = crn.get("reactions", [])
    if len(crn_reactions) != len(bng2_reactions):
        return False, "CRN reaction count mismatch"
    for sub_rxn, ref_rxn in zip(crn_reactions, bng2_reactions):
        if (
            tuple(sub_rxn.get("reactants", ())) != ref_rxn["reactants"]
            or tuple(sub_rxn.get("products", ())) != ref_rxn["products"]
        ):
            return False, "CRN reaction topology mismatch"
        rate_law = sub_rxn.get("rate_law", {})
        if rate_law.get("rule_name") != ref_rxn["rule"]:
            return False, "CRN reaction rule label mismatch"
        sub_rate = re.sub(r"\s+", "", str(rate_law.get("expression", ""))).replace(
            "()", ""
        )
        ref_rate = re.sub(r"\s+", "", ref_rxn["rate"])
        if sub_rate != ref_rate:
            return False, f"CRN rate mismatch: {sub_rate!r} != {ref_rate!r}"
    return True, ""


def _split_top_level_patterns(text: str) -> list[str]:
    """Split space- or comma-separated BNGL observable patterns cleanly."""
    tokens: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in text:
        if ch in "({[":
            depth += 1
        elif ch in ")}]" and depth > 0:
            depth -= 1
        if depth == 0 and (ch.isspace() or ch == ","):
            if cur:
                tokens.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        tokens.append("".join(cur))
    return sorted(tokens)


def _float_or_expr(raw: str) -> float | str:
    cleaned = re.sub(r"\s+", "", raw)
    try:
        val = float(cleaned)
    except ValueError:
        return cleaned
    if not math.isfinite(val):
        raise ValueError(f"non-finite scalar value: {raw!r}")
    return val


def _scalar_matches(ref: float | str, sub: float | str) -> bool:
    if isinstance(ref, float) and isinstance(sub, float):
        return math.isclose(ref, sub, rel_tol=1e-12, abs_tol=1e-15)
    return ref == sub


def _parse_hybrid_bngl(payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8")
    sections: dict[str, list[str]] = {}
    actions: list[str] = []
    in_model = False
    saw_end_model = False
    current_section: str | None = None
    for raw_line in text.splitlines():
        line = re.sub(r"#.*$", "", raw_line).strip()
        if not line:
            continue
        low = line.lower()
        if low == "begin model":
            in_model = True
            continue
        if low == "end model":
            in_model = False
            saw_end_model = True
            current_section = None
            continue
        if not in_model:
            if saw_end_model:
                actions.append(re.sub(r"\s+", "", line))
            continue
        if low.startswith("begin "):
            sec = low[len("begin ") :].strip()
            sec = "species" if sec == "seed species" else sec
            current_section = sec
            sections.setdefault(sec, [])
            continue
        if low.startswith("end "):
            current_section = None
            continue
        if current_section is not None:
            sections[current_section].append(" ".join(line.split()))
    if not saw_end_model:
        raise ValueError("hybrid BNGL missing end model block")
    params = []
    for item in sections.get("parameters", []):
        parts = item.split(None, 1)
        if len(parts) != 2:
            raise ValueError(f"invalid parameter line: {item!r}")
        params.append((parts[0], _float_or_expr(parts[1])))
    mol_types = sorted(
        " ".join(
            [re.sub(r"^([A-Za-z_]\w*)\(\)$", r"\1", item.split()[0]), *item.split()[1:]]
        )
        for item in sections.get("molecule types", [])
    )
    species = []
    for item in sections.get("species", []):
        parts = item.rsplit(None, 1)
        if len(parts) != 2:
            raise ValueError(f"invalid seed species line: {item!r}")
        species.append((re.sub(r"\s+", "", parts[0]), _float_or_expr(parts[1])))
    species.sort(key=lambda pair: pair[0])
    observables = []
    for item in sections.get("observables", []):
        parts = item.split(None, 2)
        if len(parts) != 3:
            raise ValueError(f"invalid observable line: {item!r}")
        observables.append((parts[0], parts[1], _split_top_level_patterns(parts[2])))
    observables.sort(key=lambda row: (row[0], row[1]))
    rules = []
    for item in sections.get("reaction rules", []):
        label = ""
        body = item
        if ":" in item and item.index(":") < min(
            (item.find(op) for op in ("<->", "->") if op in item),
            default=len(item),
        ):
            label, body = item.split(":", 1)
            label = label.strip()
            body = body.strip()
        op = "<->" if "<->" in body else "->" if "->" in body else ""
        if not op:
            raise ValueError(f"invalid reaction rule line: {item!r}")
        lhs, rhs_and_rate = body.split(op, 1)
        tokens = rhs_and_rate.strip().rsplit(None, 1)
        if len(tokens) != 2:
            raise ValueError(f"missing rate in reaction rule: {item!r}")
        rhs, rate = tokens
        rules.append(
            (
                label,
                re.sub(r"\s+", "", lhs),
                op,
                re.sub(r"\s+", "", rhs),
                _float_or_expr(rate),
            )
        )
    return {
        "parameters": sorted(params, key=lambda row: row[0]),
        "molecule_types": mol_types,
        "species": species,
        "observables": observables,
        "reaction_rules": rules,
        "actions": actions,
    }


def _compare_hybrid_bngl_bytes(
    oracle_bytes: bytes, consumer_bytes: bytes
) -> tuple[bool, str]:
    try:
        ref = _parse_hybrid_bngl(oracle_bytes)
        sub = _parse_hybrid_bngl(consumer_bytes)
    except (UnicodeDecodeError, ValueError) as exc:
        return False, f"hybrid BNGL parse failed: {exc}"
    for key in (
        "parameters",
        "molecule_types",
        "species",
        "observables",
        "reaction_rules",
        "actions",
    ):
        if not ref[key] or not sub[key]:
            return False, f"hybrid BNGL missing required {key}"
    for key in ("molecule_types", "observables", "actions"):
        if ref[key] != sub[key]:
            return False, f"hybrid BNGL {key} mismatch: {sub[key]!r} != {ref[key]!r}"
    for key in ("parameters", "species"):
        if len(ref[key]) != len(sub[key]):
            return False, f"hybrid BNGL {key} count mismatch"
        for (ref_k, ref_v), (sub_k, sub_v) in zip(ref[key], sub[key]):
            if ref_k != sub_k or not _scalar_matches(ref_v, sub_v):
                return (
                    False,
                    f"hybrid BNGL {key} mismatch for {ref_k!r}: {sub_v!r} != {ref_v!r}",
                )
    if len(ref["reaction_rules"]) != len(sub["reaction_rules"]):
        return False, "hybrid BNGL reaction_rules count mismatch"
    for ref_r, sub_r in zip(ref["reaction_rules"], sub["reaction_rules"]):
        if ref_r[:4] != sub_r[:4] or not _scalar_matches(ref_r[4], sub_r[4]):
            return False, f"hybrid BNGL reaction rule mismatch: {sub_r!r} != {ref_r!r}"
    return True, ""


def _parse_bngl_xml(payload: bytes) -> dict[str, Any]:
    root = ET.fromstring(payload.decode("utf-8"))
    if root.tag not in ("sbml", "{http://www.sbml.org/sbml/level3}sbml"):
        raise ValueError(f"unexpected BNG XML root tag: {root.tag!r}")
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    model = root.find("model")
    if model is None:
        raise ValueError("missing <model> element")
    params = sorted(
        (
            el.attrib.get("id", ""),
            el.attrib.get("type", ""),
            _float_or_expr(el.attrib.get("value", "")),
        )
        for el in model.findall("./ListOfParameters/Parameter")
    )
    mol_types = sorted(
        (
            el.attrib.get("id", ""),
            el.attrib.get("population", "0"),
            tuple(
                (
                    comp.attrib.get("id", ""),
                    tuple(
                        st.attrib.get("id", "")
                        for st in comp.findall("./ListOfAllowedStates/AllowedState")
                    ),
                )
                for comp in el.findall("./ListOfComponentTypes/ComponentType")
            ),
        )
        for el in model.findall("./ListOfMoleculeTypes/MoleculeType")
    )
    species = sorted(
        (
            re.sub(
                r"^([A-Za-z_]\w*)\(\)$",
                r"\1",
                re.sub(r"\s+", "", el.attrib.get("name", "")),
            ),
            _float_or_expr(el.attrib.get("concentration", "")),
            tuple(
                m.attrib.get("name", "")
                for m in el.findall("./ListOfMolecules/Molecule")
            ),
        )
        for el in model.findall("./ListOfSpecies/Species")
    )
    observables = sorted(
        (
            el.attrib.get("name", ""),
            el.attrib.get("type", ""),
            sorted(
                tuple(
                    m.attrib.get("name", "")
                    for m in pat.findall("./ListOfMolecules/Molecule")
                )
                for pat in el.findall("./ListOfPatterns/Pattern")
            ),
        )
        for el in model.findall("./ListOfObservables/Observable")
    )
    rules = []
    for rr in model.findall("./ListOfReactionRules/ReactionRule"):
        rate_el = rr.find("RateLaw")
        rate_consts = tuple(
            (rc.attrib.get("value", ""), rc.attrib.get("type", ""))
            for rc in (
                rate_el.findall("./ListOfRateConstants/RateConstant")
                if rate_el is not None
                else []
            )
        )
        ops = tuple(
            (op.tag, op.attrib.get("DeleteMolecules", ""))
            for op in rr.findall("./ListOfOperations/*")
        )
        rules.append(
            (
                rr.attrib.get("name", ""),
                tuple(
                    tuple(
                        m.attrib.get("name", "")
                        for m in rp.findall("./ListOfMolecules/Molecule")
                    )
                    for rp in rr.findall("./ListOfReactantPatterns/ReactantPattern")
                ),
                tuple(
                    tuple(
                        m.attrib.get("name", "")
                        for m in pp.findall("./ListOfMolecules/Molecule")
                    )
                    for pp in rr.findall("./ListOfProductPatterns/ProductPattern")
                ),
                rate_el.attrib.get("type", "") if rate_el is not None else "",
                rate_el.attrib.get("totalrate", "0") if rate_el is not None else "",
                rate_consts,
                ops,
            )
        )
    return {
        "parameters": params,
        "molecule_types": mol_types,
        "species": species,
        "observables": observables,
        "reaction_rules": rules,
    }


def _compare_bngl_xml_bytes(
    oracle_bytes: bytes, consumer_bytes: bytes
) -> tuple[bool, str]:
    try:
        ref = _parse_bngl_xml(oracle_bytes)
        sub = _parse_bngl_xml(consumer_bytes)
    except (UnicodeDecodeError, ET.ParseError, ValueError) as exc:
        return False, f"BNG XML parse failed: {exc}"
    for key in (
        "parameters",
        "molecule_types",
        "species",
        "observables",
        "reaction_rules",
    ):
        if not ref[key] or not sub[key]:
            return False, f"BNG XML missing required {key}"
    if len(ref["parameters"]) != len(sub["parameters"]):
        return False, "BNG XML parameters count mismatch"
    for (rk, rt, rv), (sk, st, sv) in zip(ref["parameters"], sub["parameters"]):
        if rk != sk or rt != st or not _scalar_matches(rv, sv):
            return False, f"BNG XML parameter mismatch for {rk!r}: {sv!r} != {rv!r}"
    if len(ref["species"]) != len(sub["species"]):
        return False, "BNG XML species count mismatch"
    for (rn, rc, rm), (sn, sc, sm) in zip(ref["species"], sub["species"]):
        if rn != sn or rm != sm or not _scalar_matches(rc, sc):
            return False, f"BNG XML species mismatch for {rn!r}"
    for key in ("molecule_types", "observables", "reaction_rules"):
        if ref[key] != sub[key]:
            return False, f"BNG XML {key} mismatch: {sub[key]!r} != {ref[key]!r}"
    return True, ""


def _oracle_receipt_errors(
    row: dict[str, Any],
    receipt: dict[str, Any],
    revision: str,
    artifact_root: Path | None,
    root: Path,
) -> tuple[list[str], dict[str, Any] | None]:
    errors: list[str] = []
    row_id = row.get("id", "<missing-id>")
    expected_check = f"release-capability[{row_id}]"
    if receipt.get("schema_version") != 2:
        errors.append(f"{row_id}: receipt schema_version must be 2")
    if receipt.get("kind") != "release-oracle-consumer-receipt":
        errors.append(f"{row_id}: consumer receipt kind is missing")
    if (
        receipt.get("capability_id") != row_id
        or receipt.get("check_id") != expected_check
    ):
        errors.append(f"{row_id}: receipt does not name its exact capability check")
    if (
        receipt.get("source_revision") != revision
        or receipt.get("product_revision") != revision
    ):
        errors.append(f"{row_id}: source and product revisions must equal {revision}")
    oracle = receipt.get("oracle")
    if not isinstance(oracle, dict):
        errors.append(f"{row_id}: named oracle identity is missing")
        oracle = {}
    for key in ("name", "revision", "command"):
        if not isinstance(oracle.get(key), str) or not oracle[key].strip():
            errors.append(f"{row_id}: oracle {key} is missing")
    oracle_execution = oracle.get("execution")
    if not isinstance(oracle_execution, dict):
        errors.append(f"{row_id}: pinned oracle execution record is missing")
        oracle_execution = {}
    for key in ("executable", "version", "command"):
        if (
            not isinstance(oracle_execution.get(key), str)
            or not oracle_execution[key].strip()
        ):
            errors.append(f"{row_id}: oracle execution {key} is missing")
    if (
        type(oracle_execution.get("exit_code")) is not int
        or oracle_execution.get("exit_code") != 0
    ):
        errors.append(f"{row_id}: pinned oracle did not exit successfully")
    if not _sha256(oracle.get("artifact_sha256")):
        errors.append(f"{row_id}: oracle artifact SHA-256 is invalid")
    origin = oracle.get("expected_origin")
    if origin not in {
        "external-source",
        "analytic-derivation",
        "official-expected-data",
    }:
        errors.append(f"{row_id}: expected answer origin is not independently grounded")
    identity_text = " ".join(
        str(oracle.get(key, "")) for key in ("name", "command", "expected_origin")
    ).casefold()
    if any(
        term in identity_text
        for term in ("bng3-generated", "sut-generated", "self-oracle")
    ):
        errors.append(f"{row_id}: expected answer is identified as SUT-generated")
    if origin == "analytic-derivation":
        errors.extend(_analytic_oracle_errors(root, row, oracle))
    else:
        errors.extend(_locked_oracle_errors(root, row, oracle))

    producer = receipt.get("producer")
    consumer = receipt.get("consumer")
    if not isinstance(producer, dict) or not isinstance(consumer, dict):
        errors.append(
            f"{row_id}: separate producer and downstream consumer records are required"
        )
        producer, consumer = {}, {}
    for obj, label in ((producer, "producer"), (consumer, "consumer")):
        if not isinstance(obj.get("path"), str) or not obj["path"]:
            errors.append(f"{row_id}: {label} artifact path is missing")
        if not _sha256(obj.get("output_sha256")):
            errors.append(f"{row_id}: {label} output SHA-256 is invalid")
    execution = consumer.get("execution")
    if not isinstance(execution, dict):
        errors.append(f"{row_id}: downstream consumer execution record is missing")
        execution = {}
    for key in ("executable", "version", "command"):
        if not isinstance(execution.get(key), str) or not execution[key].strip():
            errors.append(f"{row_id}: consumer execution {key} is missing")
    if type(execution.get("exit_code")) is not int or execution.get("exit_code") != 0:
        errors.append(f"{row_id}: downstream consumer did not exit successfully")
    if artifact_root is None:
        errors.append(
            f"{row_id}: byte artifacts unavailable; receipt is declaration-only"
        )
        return errors, None

    computed: dict[str, tuple[bytes | None, str | None]] = {}
    for obj, label in (
        (producer, "producer"),
        (oracle, "oracle"),
        (consumer, "consumer"),
    ):
        content, path_error = _artifact_bytes(artifact_root, obj.get("path"))
        computed[label] = (content, path_error)
        if path_error:
            errors.append(f"{row_id}: {label} {path_error}")
            continue
        actual_digest = hashlib.sha256(content).hexdigest()
        expected_digest = (
            oracle.get("artifact_sha256")
            if label == "oracle"
            else obj.get("output_sha256")
        )
        if actual_digest != expected_digest:
            errors.append(
                f"{row_id}: {label} artifact bytes do not match the receipt digest"
            )
    producer_bytes = computed["producer"][0]
    oracle_bytes = computed["oracle"][0]
    consumer_bytes = computed["consumer"][0]
    if producer_bytes is None or oracle_bytes is None or consumer_bytes is None:
        return errors, None
    producer_digest = hashlib.sha256(producer_bytes).hexdigest()
    oracle_digest = hashlib.sha256(oracle_bytes).hexdigest()
    consumer_digest = hashlib.sha256(consumer_bytes).hexdigest()
    if consumer.get("consumed_producer_sha256") != producer_digest:
        errors.append(
            f"{row_id}: consumer execution is not bound to the producer bytes"
        )
    # The owned comparator compares bytes read from the bounded artifact root;
    # the receipt's comparison/result fields are intentionally ignored.
    comparator_id = receipt.get("comparator", "release-oracle-byte-equality-v1")
    common = {
        "implementation_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "producer_sha256": producer_digest,
        "oracle_sha256": oracle_digest,
        "consumer_sha256": consumer_digest,
    }
    if comparator_id == "release-oracle-byte-equality-v1":
        diff_detail = ""
        comparator = {
            "id": "release-oracle-byte-equality-v1",
            **common,
            "consumer_equals_oracle": consumer_bytes == oracle_bytes,
        }
    elif comparator_id == "release-oracle-net-canonical-v1":
        matched, diff_detail = _compare_net_bytes(oracle_bytes, consumer_bytes)
        comparator = {
            "id": "release-oracle-net-canonical-v1",
            **common,
            "consumer_equals_oracle": matched,
        }
    elif comparator_id == "release-oracle-gdat-numeric-v1":
        matched, diff_detail = _compare_gdat_bytes(oracle_bytes, consumer_bytes)
        comparator = {
            "id": "release-oracle-gdat-numeric-v1",
            **common,
            "consumer_equals_oracle": matched,
        }
    elif comparator_id == "release-oracle-numeric-json-v1":
        matched, diff_detail = _compare_numeric_json_bytes(oracle_bytes, consumer_bytes)
        comparator = {
            "id": "release-oracle-numeric-json-v1",
            **common,
            "consumer_equals_oracle": matched,
        }
    elif comparator_id == "release-oracle-crn-bng2-v1":
        matched, diff_detail = _compare_crn_bng2_bytes(oracle_bytes, consumer_bytes)
        comparator = {
            "id": "release-oracle-crn-bng2-v1",
            **common,
            "consumer_equals_oracle": matched,
        }
    elif comparator_id == "release-oracle-bngl-hybrid-v1":
        matched, diff_detail = _compare_hybrid_bngl_bytes(oracle_bytes, consumer_bytes)
        comparator = {
            "id": "release-oracle-bngl-hybrid-v1",
            **common,
            "consumer_equals_oracle": matched,
        }
    elif comparator_id == "release-oracle-bngl-xml-v1":
        matched, diff_detail = _compare_bngl_xml_bytes(oracle_bytes, consumer_bytes)
        comparator = {
            "id": "release-oracle-bngl-xml-v1",
            **common,
            "consumer_equals_oracle": matched,
        }
    else:
        errors.append(f"{row_id}: unsupported owned comparator {comparator_id!r}")
        return errors, None
    if not comparator["consumer_equals_oracle"]:
        suffix = f" ({diff_detail})" if diff_detail else ""
        errors.append(
            f"{row_id}: owned byte comparator found consumer output differs from oracle{suffix}"
        )
    return errors, comparator


def _analytic_oracle_errors(
    root: Path, row: dict[str, Any], oracle: dict[str, Any]
) -> list[str]:
    row_id = row.get("id", "<missing-id>")
    declaration = str(row.get("oracle", "")).casefold()
    oracle_name = str(oracle.get("name", "")).casefold()
    analytic_terms = ("analytic", "hand-derived")
    if not any(term in declaration for term in analytic_terms) or not any(
        term in oracle_name for term in analytic_terms
    ):
        return [
            f"{row_id}: analytic receipt does not match an analytic matrix declaration"
        ]
    law = oracle.get("law")
    if not isinstance(law, str) or not law.strip():
        return [f"{row_id}: analytic oracle law description is missing"]
    if not _sha256(oracle.get("executable_sha256")):
        return [f"{row_id}: analytic oracle script SHA-256 is invalid"]
    spec_path = oracle.get("spec_path")
    spec_bytes, path_error = _artifact_bytes(root, spec_path)
    if path_error or spec_bytes is None:
        return [f"{row_id}: analytic specification path invalid: {path_error}"]
    spec_digest = hashlib.sha256(spec_bytes).hexdigest()
    if (
        oracle.get("spec_sha256") != spec_digest
        or oracle.get("revision") != spec_digest
    ):
        return [
            f"{row_id}: analytic oracle revision/digest does not match specification bytes"
        ]
    return []


def _locked_oracle_errors(
    root: Path, row: dict[str, Any], oracle: dict[str, Any]
) -> list[str]:
    row_id = row.get("id", "<missing-id>")
    try:
        lock = yaml.safe_load(
            (root / "provenance/upstreams.lock.yml").read_text(encoding="utf-8")
        )
    except (OSError, yaml.YAMLError) as exc:
        return [f"{row_id}: pinned upstream lock unavailable: {exc}"]
    if not isinstance(lock, dict) or not isinstance(lock.get("sources"), dict):
        return [f"{row_id}: pinned upstream lock has no sources mapping"]
    source_id = oracle.get("source_id")
    aliases = {
        "bng2": ("bng2",),
        "nfsim": ("nfsim",),
        "pybionetgen": ("pybionetgen",),
        "sbml-test-suite": ("ssts", "sbml test suite"),
        "bngsim": ("bngsim",),
        "bngplayground": ("playground",),
        "rulehub": ("rulehub",),
    }
    if source_id not in aliases:
        return [f"{row_id}: oracle source_id is not a supported pinned source"]
    declaration = str(row.get("oracle", "")).casefold()
    oracle_name = str(oracle.get("name", "")).casefold()
    matching_alias = next(
        (alias for alias in aliases[source_id] if alias in declaration), None
    )
    if matching_alias is None or matching_alias not in oracle_name:
        return [
            f"{row_id}: receipt oracle does not match the matrix source declaration"
        ]

    oracle_lock = lock.get("oracles", {}).get(source_id)
    source_key = (
        oracle_lock.get("source") if isinstance(oracle_lock, dict) else source_id
    )
    source = lock["sources"].get(source_key)
    expected_revision = source.get("revision") if isinstance(source, dict) else None
    source_status = source.get("status") if isinstance(source, dict) else None
    if not isinstance(expected_revision, str) or not re.fullmatch(
        r"[0-9a-f]{40}", expected_revision
    ):
        return [f"{row_id}: pinned source {source_key} has no full revision"]
    if source_status != "accepted":
        return [f"{row_id}: pinned source {source_key} is not accepted"]
    if oracle.get("revision") != expected_revision:
        return [f"{row_id}: oracle revision does not match pinned source {source_key}"]
    if isinstance(oracle_lock, dict):
        if oracle_lock.get("status") != "locked":
            return [f"{row_id}: oracle {source_id} is not locked"]
        artifact_digest = str(oracle_lock.get("artifact_digest", ""))
        expected_executable = artifact_digest.removeprefix("sha256:")
        build_platform = oracle.get("build_platform")
        recipe = str(oracle_lock.get("build_recipe", "")).casefold()
        cross_platform = (
            isinstance(build_platform, str)
            and bool(build_platform.strip())
            and build_platform != "macos-arm64"
            and "macos arm64" in recipe
        )
        if cross_platform:
            if not _sha256(oracle.get("executable_sha256")):
                return [
                    f"{row_id}: oracle executable digest does not match the pinned lock"
                ]
            if oracle.get("source_clean") is not True:
                return [
                    f"{row_id}: cross-platform oracle source checkout is not verified clean"
                ]
            if "script_sha256" in oracle and not _sha256(oracle.get("script_sha256")):
                return [f"{row_id}: oracle script SHA-256 is invalid"]
        elif (
            not _sha256(expected_executable)
            or oracle.get("executable_sha256") != expected_executable
        ):
            return [
                f"{row_id}: oracle executable digest does not match the pinned lock"
            ]
    return []


def _has_named_oracle(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    lowered = value.casefold()
    if "as appropriate" in lowered or re.search(
        r"\b(?:tbd|unknown|none|n/a|oracle needed)\b", lowered
    ):
        return False
    if any(
        term in lowered for term in ("bng3-generated", "sut-generated", "self-oracle")
    ):
        return False
    names = (
        "bng2",
        "nfsim",
        "pybionetgen",
        "ssts",
        "roadrunner",
        "libsbml",
        "jsbml",
        "bngsim",
        "multi specification",
        "analytic",
        "hand-derived",
        "independently authored",
        "independent exact network enumerator",
    )
    return any(name in lowered for name in names)


def _inventory_ids(root: Path) -> list[str]:
    path = root / "docs/CAPABILITY_UNION_INVENTORY.md"
    if not path.is_file():
        raise ValueError("independent capability inventory is missing")
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*([A-Za-z][A-Za-z0-9_.-]*)\s*\|", line)
        if match and match.group(1) != "ID":
            ids.append(match.group(1))
    if not ids:
        raise ValueError("independent capability inventory contains no row IDs")
    return ids


def oracle_independence_report(
    root: Path, receipt_dir: Path, revision: str, artifact_root: Path | None = None
) -> dict[str, Any]:
    """Report declaration coverage separately from exact-revision execution evidence."""
    matrix_path = root / "provenance/capability-matrix.yml"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    rows = matrix.get("rows")
    if not isinstance(rows, list):
        raise ValueError("capability matrix rows must be a list")
    if not rows:
        raise ValueError("capability matrix rows must not be empty")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision must be a full 40-character commit SHA")
    duplicate_ids: set[str] = set()
    seen: set[str] = set()
    findings: list[str] = []
    comparisons: list[dict[str, Any]] = []
    named = 0
    grounded = 0
    status_counts: dict[str, int] = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("id"), str)
            or not row.get("id", "").strip()
        ):
            findings.append("matrix contains a row without a stable ID")
            continue
        row_id = row["id"]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", row_id):
            findings.append(f"matrix row ID is unsafe for receipt lookup: {row_id!r}")
            continue
        if row_id in seen:
            duplicate_ids.add(row_id)
        seen.add(row_id)
        status = str(row.get("status", "<missing>"))
        status_counts[status] = status_counts.get(status, 0) + 1
        oracle_decl = row.get("oracle")
        if _has_named_oracle(oracle_decl):
            named += 1
        else:
            findings.append(
                f"{row_id}: oracle declaration does not name an external or analytic source"
            )
        receipt_path = receipt_dir / f"{row_id}.json"
        if not receipt_path.is_file():
            findings.append(f"{row_id}: no exact-revision downstream consumer receipt")
            continue
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(f"{row_id}: consumer receipt cannot be read: {exc}")
            continue
        row_errors, comparator = _oracle_receipt_errors(
            row, receipt, revision, artifact_root, root
        )
        receipt_valid = not row_errors
        if status != "implemented":
            row_errors.append(
                f"{row_id}: matrix status is {status}; implementation is not qualified"
            )
        if comparator:
            comparisons.append(
                {
                    "capability_id": row_id,
                    "receipt_valid": receipt_valid,
                    "check_result": "pass" if not row_errors else "fail",
                    **comparator,
                }
            )
        if row_errors:
            findings.extend(row_errors)
        else:
            grounded += 1
    findings.extend(
        f"duplicate matrix row ID: {row_id}" for row_id in sorted(duplicate_ids)
    )
    try:
        inventory_id_list = _inventory_ids(root)
    except (OSError, ValueError) as exc:
        inventory_id_list = []
        findings.append(f"independent capability inventory invalid: {exc}")
    inventory_ids = set(inventory_id_list)
    inventory_duplicates = sorted(
        value for value in inventory_ids if inventory_id_list.count(value) > 1
    )
    findings.extend(
        f"duplicate independent inventory row ID: {row_id}"
        for row_id in inventory_duplicates
    )
    matrix_ids = seen
    if matrix_ids != inventory_ids:
        findings.append(
            "matrix/inventory ID coverage mismatch: "
            f"matrix-only={sorted(matrix_ids - inventory_ids)[:10]} "
            f"inventory-only={sorted(inventory_ids - matrix_ids)[:10]}"
        )
    return {
        "schema_version": 1,
        "check_id": "release-oracle-independence",
        "revision": revision,
        "row_count": len(rows),
        "evidence_scope": (
            "ARTIFACT_CHECKS_ENABLED" if artifact_root else "DECLARATION_ONLY"
        ),
        "named_oracle_rows": named,
        "grounded_execution_rows": grounded,
        "owned_comparisons": comparisons,
        "source_status_counts": status_counts,
        "findings": findings,
        "result": "pass" if not findings and grounded == len(rows) else "fail",
    }


def topology_errors(
    workflow: dict[str, Any], independent_groups: list[list[str]] | None = None
) -> list[str]:
    """Check declared parallel job groups and unconditional partial-artifact uploads."""
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return ["workflow has no jobs"]
    errors: list[str] = []
    for group in independent_groups or []:
        for job_name in group:
            if job_name not in jobs:
                errors.append(f"independent job is missing: {job_name}")
        for left_index, left in enumerate(group):
            if left not in jobs:
                continue
            for right in group[left_index + 1 :]:
                if right not in jobs:
                    continue
                for dependent, other in ((left, right), (right, left)):
                    needs = jobs[dependent].get("needs", [])
                    needs = [needs] if isinstance(needs, str) else needs
                    if other in needs:
                        errors.append(
                            f"independent jobs are serialized: {other} -> {dependent}"
                        )
    for job_name, job in jobs.items():
        for step in job.get("steps", []) if isinstance(job, dict) else []:
            if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                condition = str(step.get("if", ""))
                if "always()" not in condition and "!cancelled()" not in condition:
                    errors.append(
                        f"{job_name}: artifact upload does not run after failure"
                    )
    return errors


def check_workflow_topology(path: Path) -> dict[str, Any]:
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    groups = [["bng2-parity", "nfsim-parity", "pybionetgen-compat"]]
    errors = topology_errors(workflow, groups)
    # These jobs share source-lock validation but their scientific checks are independent.
    if path.name == "parity.yml":
        expected_needs = {name: ["oracle-lock"] for name in groups[0]}
        for name, expected in expected_needs.items():
            needs = workflow["jobs"].get(name, {}).get("needs", [])
            observed = [needs] if isinstance(needs, str) else needs
            if observed != expected:
                errors.append(f"{name}: needs must be {expected}, observed {observed}")
    required_workflows = [
        "ci.yml",
        "parity.yml",
        "sbml-conformance.yml",
        "weekly.yml",
        "formal.yml",
        "codeql.yml",
        "autofix.yml",
        "release.yml",
        "issue-acceptance.yml",
        "issue-472-docs-acceptance.yml",
        "regenerate-bng2-ensembles.yml",
        "release-policy.yml",
    ]
    return {
        "schema_version": 1,
        "check_id": "release-ci-topology",
        "workflow": str(path),
        "independent_jobs": groups[0] if path.name == "parity.yml" else [],
        "static_result": "pass" if not errors else "fail",
        "acceptance_result": "fail",
        "coverage": [path.name],
        "required_workflow_coverage": required_workflows,
        "acceptance_gaps": [
            "all maintained workflows and every job have not been audited",
            "no interrupted-run replay receipt was consumed",
        ],
        "errors": errors,
        "result": "fail",
    }


REQUIRED_WORKFLOWS = (
    "ci.yml",
    "parity.yml",
    "sbml-conformance.yml",
    "weekly.yml",
    "formal.yml",
    "codeql.yml",
    "autofix.yml",
    "release.yml",
    "issue-acceptance.yml",
    "issue-472-docs-acceptance.yml",
    "regenerate-bng2-ensembles.yml",
    "release-policy.yml",
)
TOPOLOGY_CONTRACT = Path(__file__).resolve().parent / "topology-contract.json"


def _transitive_needs(jobs: dict[str, Any], name: str) -> set[str]:
    seen: set[str] = set()
    stack = [name]
    while stack:
        current = stack.pop()
        spec = jobs.get(current, {})
        needs = spec.get("needs", []) if isinstance(spec, dict) else []
        needs = [needs] if isinstance(needs, str) else needs
        for need in needs:
            if need not in seen:
                seen.add(need)
                stack.append(need)
    return seen


def replay_errors(receipts: list[dict[str, Any]], revision: str | None) -> list[str]:
    """Require a bounded, revision-bound receipt that partial cases survived interruption."""
    errors: list[str] = []
    if not revision:
        return ["no exact revision was supplied for the interrupted-run replay receipt"]
    if not receipts:
        return ["no interrupted-run replay receipt was consumed"]
    for receipt in receipts:
        if receipt.get("schema_version") != 1:
            errors.append("replay receipt schema_version is not 1")
            continue
        if receipt.get("source_revision") != revision:
            errors.append(
                f"replay receipt revision {receipt.get('source_revision')} != {revision}"
            )
            continue
        phases = receipt.get("phases", {})
        actions = phases.get("resume", {}).get("actions", {})
        if not isinstance(actions, dict) or "reused" not in actions.values():
            errors.append("resume did not reuse an already completed per-case artifact")
        if (
            phases.get("stale_control", {}).get("action")
            != "stale-discarded-and-executed"
        ):
            errors.append("stale partial artifact was not identified and discarded")
        cases = receipt.get("cases", {})
        if not cases or not all(
            isinstance(case, dict) and case.get("verdicts_match_clean") is True
            for case in cases.values()
        ):
            errors.append("resumed per-case verdicts do not match the clean run")
    return errors


def check_workflows_topology(
    workflows_dir: Path,
    *,
    revision: str | None = None,
    replay_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    workflow_paths = sorted(workflows_dir.glob("*.yml"))
    present = {path.name for path in workflow_paths}
    missing = [name for name in REQUIRED_WORKFLOWS if name not in present]
    per_workflow: list[dict[str, Any]] = []
    static_errors: list[str] = [
        f"maintained workflow missing: {name}" for name in missing
    ]
    contract = json.loads(TOPOLOGY_CONTRACT.read_text())["groups"]
    audited_groups: list[str] = []
    for path in workflow_paths:
        workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        errs = topology_errors(workflow)
        jobs = workflow.get("jobs", {})
        for group in contract.get(path.name, []):
            audited_groups.append(f"{path.name}:{','.join(group)}")
            for name in group:
                if name not in jobs:
                    errs.append(f"{path.name}: independent job is missing: {name}")
            for index, name in enumerate(group):
                if name not in jobs:
                    continue
                required = _transitive_needs(jobs, name)
                for other in group[index + 1 :]:
                    if other in required or name in _transitive_needs(jobs, other):
                        errs.append(
                            f"{path.name}: independent jobs are serialized: {name} -> {other}"
                        )
        per_workflow.append(
            {
                "workflow": path.name,
                "static_result": "pass" if not errs else "fail",
                "errors": errs,
            }
        )
        static_errors.extend(f"{path.name}: {error}" for error in errs)
    parity = workflows_dir / "parity.yml"
    parity_report = (
        check_workflow_topology(parity)
        if parity.is_file()
        else {"static_result": "fail", "errors": ["parity.yml missing"]}
    )
    replay = replay_errors(replay_receipts or [], revision)
    static_ok = not static_errors and parity_report.get("static_result") == "pass"
    gaps = list(replay)
    if static_errors:
        gaps.append("workflow topology has static errors")
    return {
        "schema_version": 3,
        "check_id": "release-ci-topology",
        "evaluated_revision": revision,
        "working_tree_dirty": False,
        "workflows_dir": str(workflows_dir),
        "audited_workflows": sorted(present),
        "audited_independent_groups": audited_groups,
        "per_workflow": per_workflow,
        "parity": parity_report,
        "static_result": "pass" if static_ok else "fail",
        "acceptance_gaps": gaps,
        "errors": static_errors + list(parity_report.get("errors", [])),
        "acceptance_result": "pass" if static_ok and not gaps else "fail",
        "result": "pass" if static_ok and not gaps else "fail",
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="check", required=True)
    oracle = sub.add_parser("oracle")
    oracle.add_argument("--root", type=Path, default=Path.cwd())
    oracle.add_argument("--receipts", type=Path, required=True)
    oracle.add_argument("--artifacts", type=Path)
    oracle.add_argument("--revision", required=True)
    oracle.add_argument("--report", type=Path, required=True)
    topology = sub.add_parser("topology")
    topology.add_argument(
        "--workflow", type=Path, default=Path(".github/workflows/parity.yml")
    )
    topology.add_argument("--workflows-dir", type=Path)
    topology.add_argument("--all-workflows", action="store_true")
    topology.add_argument("--revision")
    topology.add_argument("--replay-receipt", type=Path, action="append", default=[])
    topology.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.check == "oracle":
        report = oracle_independence_report(
            args.root, args.receipts, args.revision, args.artifacts
        )
    else:
        workflows_dir = args.workflows_dir
        if args.all_workflows and workflows_dir is None:
            workflows_dir = Path(".github/workflows")
        if workflows_dir is not None:
            receipts = [json.loads(p.read_bytes()) for p in args.replay_receipt]
            report = check_workflows_topology(
                workflows_dir, revision=args.revision, replay_receipts=receipts
            )
        else:
            report = check_workflow_topology(args.workflow)
    write_report(report, args.report)
    print(
        json.dumps(
            {
                key: report[key]
                for key in report
                if key
                in {
                    "check_id",
                    "result",
                    "row_count",
                    "grounded_execution_rows",
                    "static_result",
                    "acceptance_result",
                    "errors",
                }
            },
            sort_keys=True,
        )
    )
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
