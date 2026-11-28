"""Static flattening for SBML Level 3 ``arrays`` Version 1 models.

SBML Level 3 ``arrays`` v1 (``http://www.sbml.org/sbml/level3/version1/arrays/version1``)
adds finite rectangular arrays to Core SBML elements via ``listOfDimensions``,
``listOfIndices``, and MathML ``<vector>`` / ``<selector>`` expressions (plus
bounded ``<sum>`` / ``<product>`` reductions).

Any valid ``arrays`` model with finite, non-negative constant integer dimensions
and statically resolvable indices has an exact Core SBML equivalent obtained by
unrolling arrayed compartments, species, parameters, initial assignments, rules,
reactions (including species references, modifiers, and local parameters),
events (including event assignments), and constraints.

This module performs that static expansion before the standard Atomizer parser
and fails closed on every invalid, ambiguous, or non-static construct.
"""

from __future__ import annotations

import copy
import itertools
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

ARRAYS_NAMESPACE_V1 = "http://www.sbml.org/sbml/level3/version1/arrays/version1"
MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML"

_ARRAYS_NAMESPACE_RE = re.compile(
    r"^https?://www\.sbml\.org/sbml/level3/version\d+/arrays/version(\d+)$",
    re.IGNORECASE,
)
_CORE_NAMESPACE_RE = re.compile(
    r"^https?://www\.sbml\.org/sbml/level3/version\d+/core$",
    re.IGNORECASE,
)

# Safety cap preventing accidental memory blow-up on absurdly large dimensions.
MAX_FLATTENED_ELEMENTS = 100_000

# SBML L3 arrays v1 elements permitted to carry <arrays:listOfDimensions>.
_DIMENSIONABLE_ELEMENTS = frozenset(
    {
        "compartment",
        "species",
        "parameter",
        "initialAssignment",
        "assignmentRule",
        "rateRule",
        "algebraicRule",
        "reaction",
        "speciesReference",
        "modifierSpeciesReference",
        "localParameter",
        "event",
        "eventAssignment",
        "constraint",
    }
)

# Valid SIdRef attributes that <arrays:index arrays:referencedAttribute="...">
# may index on each Core SBML element.
_INDEXABLE_ATTRIBUTES: Dict[str, frozenset[str]] = {
    "species": frozenset({"compartment", "conversionFactor"}),
    "initialAssignment": frozenset({"symbol"}),
    "assignmentRule": frozenset({"variable"}),
    "rateRule": frozenset({"variable"}),
    "reaction": frozenset({"compartment"}),
    "speciesReference": frozenset({"species"}),
    "modifierSpeciesReference": frozenset({"species"}),
    "eventAssignment": frozenset({"variable"}),
}

_ALLOWED_DIMENSION_ATTRS = frozenset({"id", "name", "size", "arrayDimension"})
_ALLOWED_INDEX_ATTRS = frozenset({"referencedAttribute", "arrayDimension"})


class ArraysFlatteningError(ValueError):
    """Raised when an SBML ``arrays`` document cannot be statically flattened."""


@dataclass(frozen=True)
class DimensionSpec:
    """Validated ``<arrays:dimension>`` declaration."""

    id: Optional[str]
    size_ref: str
    array_dimension: int
    size: int


@dataclass(frozen=True)
class IndexSpec:
    """Validated ``<arrays:index>`` declaration."""

    referenced_attribute: str
    array_dimension: int
    math: ET.Element


@dataclass(frozen=True)
class FunctionDefSpec:
    """Pure Core ``<functionDefinition>`` usable in static index expressions."""

    params: Tuple[str, ...]
    body: ET.Element


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return ""


def _is_arrays_namespace(uri: str) -> bool:
    return bool(uri and _ARRAYS_NAMESPACE_RE.match(uri))


def _arrays_version(uri: str) -> Optional[int]:
    match = _ARRAYS_NAMESPACE_RE.match(uri or "")
    return int(match.group(1)) if match else None


def _build_parent_map(root: ET.Element) -> Dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def _inside_opaque_core_container(
    element: ET.Element, parent_map: Mapping[ET.Element, ET.Element]
) -> bool:
    parent = parent_map.get(element)
    while parent is not None:
        ns = _namespace(str(parent.tag))
        local = _local_name(str(parent.tag))
        if local in {"annotation", "notes"} and _CORE_NAMESPACE_RE.match(ns):
            return True
        parent = parent_map.get(parent)
    return False


def _is_selector_operator(node: ET.Element) -> bool:
    local = _local_name(str(node.tag)).lower()
    if local == "selector":
        return True
    if local == "csymbol":
        text = "".join(node.itertext()).strip().lower()
        definition_url = str(node.get("definitionURL", "") or "").strip().lower()
        tail = definition_url.rstrip("/").rsplit("/", 1)[-1] if definition_url else ""
        return text == "selector" or tail == "selector"
    return False


def _sum_or_product_kind(node: ET.Element) -> Optional[str]:
    local = _local_name(str(node.tag)).lower()
    if local in {"sum", "product"}:
        return local
    if local == "csymbol":
        text = "".join(node.itertext()).strip().lower()
        definition_url = str(node.get("definitionURL", "") or "").strip().lower()
        tail = definition_url.rstrip("/").rsplit("/", 1)[-1] if definition_url else ""
        if text in {"sum", "product"}:
            return text
        if tail in {"sum", "product"}:
            return tail
    return None


def _math_tag(local: str) -> str:
    return f"{{{MATHML_NAMESPACE}}}{local}"


def _make_cn_int(value: int) -> ET.Element:
    elem = ET.Element(_math_tag("cn"), {"type": "integer"})
    elem.text = str(int(value))
    return elem


def _make_ci(name: str) -> ET.Element:
    elem = ET.Element(_math_tag("ci"))
    elem.text = name
    return elem


def _flat_id(base_id: str, coords: Sequence[int]) -> str:
    if not coords:
        return base_id
    return f"{base_id}_{'_'.join(str(c) for c in coords)}"


def _element_array_children(
    element: ET.Element, arrays_ns: Optional[str]
) -> Tuple[Optional[ET.Element], Optional[ET.Element]]:
    """Return ``(listOfDimensions, listOfIndices)`` direct children, validating tags."""

    dims_list: Optional[ET.Element] = None
    indices_list: Optional[ET.Element] = None
    for child in list(element):
        ns = _namespace(str(child.tag))
        if not _is_arrays_namespace(ns):
            continue
        if arrays_ns is not None and ns != arrays_ns:
            raise ArraysFlatteningError(
                f"Mixed or unexpected arrays namespace {ns!r} (expected {arrays_ns!r})."
            )
        local = _local_name(str(child.tag))
        if local == "listOfDimensions":
            if dims_list is not None:
                raise ArraysFlatteningError(
                    f"Element <{_local_name(str(element.tag))}> has multiple "
                    "arrays:listOfDimensions children."
                )
            dims_list = child
        elif local == "listOfIndices":
            if indices_list is not None:
                raise ArraysFlatteningError(
                    f"Element <{_local_name(str(element.tag))}> has multiple "
                    "arrays:listOfIndices children."
                )
            indices_list = child
        else:
            raise ArraysFlatteningError(
                f"Unsupported SBML arrays element <{local}> under "
                f"<{_local_name(str(element.tag))}>."
            )
    return dims_list, indices_list


def _arrays_attr(element: ET.Element, arrays_ns: str, name: str) -> Optional[str]:
    key = f"{{{arrays_ns}}}{name}"
    if key in element.attrib:
        return element.attrib[key]
    return None


def _parse_nonneg_int(raw: Optional[str], context: str) -> int:
    if raw is None or not str(raw).strip():
        raise ArraysFlatteningError(f"Missing integer attribute for {context}.")
    text = str(raw).strip()
    if not re.fullmatch(r"[+-]?\d+", text):
        raise ArraysFlatteningError(
            f"Attribute for {context} must be a non-negative integer, got {raw!r}."
        )
    value = int(text)
    if value < 0:
        raise ArraysFlatteningError(
            f"Attribute for {context} must be non-negative, got {value}."
        )
    return value


def _parse_dimensions_raw(
    element: ET.Element,
    arrays_ns: Optional[str],
    size_values: Mapping[str, int],
) -> List[DimensionSpec]:
    """Parse and validate ``listOfDimensions`` on ``element``."""

    dims_list, _ = _element_array_children(element, arrays_ns)
    if dims_list is None:
        return []
    elem_local = _local_name(str(element.tag))
    if elem_local not in _DIMENSIONABLE_ELEMENTS:
        raise ArraysFlatteningError(
            f"SBML arrays:listOfDimensions is not supported on <{elem_local}>."
        )
    assert arrays_ns is not None
    raw_dims: List[DimensionSpec] = []
    seen_ids: Set[str] = set()
    for child in list(dims_list):
        child_ns = _namespace(str(child.tag))
        child_local = _local_name(str(child.tag))
        if child_local in {"notes", "annotation"} and _CORE_NAMESPACE_RE.match(
            child_ns
        ):
            continue
        if child_ns != arrays_ns or child_local != "dimension":
            raise ArraysFlatteningError(
                f"Unexpected child <{child_local}> inside arrays:listOfDimensions."
            )
        for grand in list(child):
            g_ns = _namespace(str(grand.tag))
            g_local = _local_name(str(grand.tag))
            if not (
                g_local in {"notes", "annotation"} and _CORE_NAMESPACE_RE.match(g_ns)
            ):
                raise ArraysFlatteningError(
                    f"arrays:dimension cannot contain child element <{g_local}>."
                )
        for attr_key in child.attrib:
            attr_ns = _namespace(attr_key)
            attr_local = _local_name(attr_key)
            if _is_arrays_namespace(attr_ns):
                if attr_local not in _ALLOWED_DIMENSION_ATTRS:
                    raise ArraysFlatteningError(
                        f"Unsupported attribute arrays:{attr_local} on arrays:dimension."
                    )
            elif attr_ns == "" and attr_local not in {"metaid", "sboTerm"}:
                raise ArraysFlatteningError(
                    f"Unqualified or unsupported attribute {attr_local!r} on "
                    "arrays:dimension (expected arrays-namespaced attributes)."
                )
        size_ref = _arrays_attr(child, arrays_ns, "size")
        if not size_ref or not size_ref.strip():
            raise ArraysFlatteningError(
                f"arrays:dimension on <{elem_local}> is missing required arrays:size."
            )
        size_ref = size_ref.strip()
        if size_ref not in size_values:
            raise ArraysFlatteningError(
                f"arrays:dimension size={size_ref!r} on <{elem_local}> does not "
                "reference a valid constant non-negative integer scalar parameter."
            )
        dim_idx = _parse_nonneg_int(
            _arrays_attr(child, arrays_ns, "arrayDimension"),
            f"arrays:arrayDimension on <{elem_local}>",
        )
        dim_id = _arrays_attr(child, arrays_ns, "id")
        if dim_id is not None:
            dim_id = dim_id.strip()
            if not dim_id:
                raise ArraysFlatteningError(
                    f"arrays:dimension on <{elem_local}> has empty arrays:id."
                )
            if dim_id in seen_ids:
                raise ArraysFlatteningError(
                    f"Duplicate arrays:dimension id={dim_id!r} on <{elem_local}>."
                )
            seen_ids.add(dim_id)
        raw_dims.append(
            DimensionSpec(
                id=dim_id,
                size_ref=size_ref,
                array_dimension=dim_idx,
                size=size_values[size_ref],
            )
        )
    raw_dims.sort(key=lambda d: d.array_dimension)
    expected = list(range(len(raw_dims)))
    actual = [d.array_dimension for d in raw_dims]
    if actual != expected:
        raise ArraysFlatteningError(
            f"arrays:listOfDimensions on <{elem_local}> must have contiguous "
            f"arrayDimension values {expected}, got {actual}."
        )
    return raw_dims


def _parse_indices(
    element: ET.Element, arrays_ns: Optional[str]
) -> Dict[str, List[IndexSpec]]:
    """Parse and validate ``listOfIndices`` on ``element``, grouped by attribute."""

    _, indices_list = _element_array_children(element, arrays_ns)
    if indices_list is None:
        return {}
    elem_local = _local_name(str(element.tag))
    allowed_attrs = _INDEXABLE_ATTRIBUTES.get(elem_local, frozenset())
    assert arrays_ns is not None
    grouped: Dict[str, List[IndexSpec]] = {}
    for child in list(indices_list):
        child_ns = _namespace(str(child.tag))
        child_local = _local_name(str(child.tag))
        if child_local in {"notes", "annotation"} and _CORE_NAMESPACE_RE.match(
            child_ns
        ):
            continue
        if child_ns != arrays_ns or child_local != "index":
            raise ArraysFlatteningError(
                f"Unexpected child <{child_local}> inside arrays:listOfIndices."
            )
        for attr_key in child.attrib:
            attr_ns = _namespace(attr_key)
            attr_local = _local_name(attr_key)
            if _is_arrays_namespace(attr_ns):
                if attr_local not in _ALLOWED_INDEX_ATTRS:
                    raise ArraysFlatteningError(
                        f"Unsupported attribute arrays:{attr_local} on arrays:index."
                    )
            elif attr_ns == "" and attr_local not in {"metaid", "sboTerm"}:
                raise ArraysFlatteningError(
                    f"Unqualified or unsupported attribute {attr_local!r} on "
                    "arrays:index (expected arrays-namespaced attributes)."
                )
        ref_attr = _arrays_attr(child, arrays_ns, "referencedAttribute")
        if not ref_attr or not ref_attr.strip():
            raise ArraysFlatteningError(
                f"arrays:index on <{elem_local}> is missing required "
                "arrays:referencedAttribute."
            )
        ref_attr = ref_attr.strip()
        if ref_attr not in allowed_attrs:
            raise ArraysFlatteningError(
                f"arrays:index referencedAttribute={ref_attr!r} is not allowed on "
                f"<{elem_local}>."
            )
        if element.get(ref_attr) is None:
            raise ArraysFlatteningError(
                f"arrays:index references attribute {ref_attr!r} which is absent "
                f"on <{elem_local}>."
            )
        dim_idx = _parse_nonneg_int(
            _arrays_attr(child, arrays_ns, "arrayDimension"),
            f"arrays:index arrayDimension on <{elem_local}>.{ref_attr}",
        )
        math_children = [
            grand for grand in list(child) if _local_name(str(grand.tag)) == "math"
        ]
        if len(math_children) != 1 or len(list(math_children[0])) != 1:
            raise ArraysFlatteningError(
                f"arrays:index on <{elem_local}>.{ref_attr} must contain a single "
                "MathML <math> expression."
            )
        grouped.setdefault(ref_attr, []).append(
            IndexSpec(
                referenced_attribute=ref_attr,
                array_dimension=dim_idx,
                math=list(math_children[0])[0],
            )
        )
    for ref_attr, specs in grouped.items():
        specs.sort(key=lambda s: s.array_dimension)
        expected = list(range(len(specs)))
        actual = [s.array_dimension for s in specs]
        if actual != expected:
            raise ArraysFlatteningError(
                f"arrays:listOfIndices for <{elem_local}>.{ref_attr} must have "
                f"contiguous arrayDimension values {expected}, got {actual}."
            )
    return grouped


def _parse_cn_fraction(node: ET.Element) -> Fraction:
    """Parse a MathML ``<cn>`` into an exact finite ``Fraction``."""

    num_type = str(node.get("type", "real") or "real").strip().lower()
    children = list(node)
    try:
        if num_type == "rational":
            if len(children) != 1 or _local_name(str(children[0].tag)) != "sep":
                raise ArraysFlatteningError("Malformed rational <cn> in array math.")
            num_text = (node.text or "").strip()
            den_text = (children[0].tail or "").strip()
            return Fraction(int(num_text), int(den_text))
        if num_type in {"e-notation", "enotation"}:
            if len(children) != 1 or _local_name(str(children[0].tag)) != "sep":
                raise ArraysFlatteningError("Malformed e-notation <cn> in array math.")
            mantissa = Fraction((node.text or "").strip())
            exponent = int((children[0].tail or "").strip())
            if abs(exponent) > 308:
                raise ArraysFlatteningError(
                    "e-notation exponent overflow in array math."
                )
            scale = (
                Fraction(10**exponent)
                if exponent >= 0
                else Fraction(1, 10 ** (-exponent))
            )
            return mantissa * scale
        if num_type not in {"integer", "real"} or children:
            raise ArraysFlatteningError(
                f"Unsupported <cn type={num_type!r}> in static array expression."
            )
        text = (node.text or "").strip()
        if not text:
            raise ArraysFlatteningError("Empty <cn> in static array expression.")
        # Reject NaN / Inf before Fraction conversion.
        parsed_float = float(text)
        if not math.isfinite(parsed_float):
            raise ArraysFlatteningError(
                f"Non-finite numeric literal {text!r} in static array expression."
            )
        return Fraction(text)
    except ArraysFlatteningError:
        raise
    except (ValueError, ZeroDivisionError) as exc:
        raise ArraysFlatteningError(
            f"Invalid numeric literal in static array expression: {exc}"
        ) from exc


def _eval_static_value(
    node: ET.Element,
    dim_env: Mapping[str, int],
    const_scalars: Mapping[str, Fraction],
    const_arrays: Mapping[str, Any],
    func_defs: Mapping[str, FunctionDefSpec],
    depth: int = 0,
) -> Any:
    """Evaluate a MathML node statically to ``Fraction``, ``bool``, or nested ``list``."""

    if depth > 32:
        raise ArraysFlatteningError(
            "Static array expression exceeded maximum evaluation depth."
        )
    local = _local_name(str(node.tag)).lower()
    children = list(node)

    if local in {"math", "semantics", "condition"}:
        if len(children) != 1:
            raise ArraysFlatteningError(
                f"Expected single expression inside <{local}> in static array math."
            )
        return _eval_static_value(
            children[0], dim_env, const_scalars, const_arrays, func_defs, depth + 1
        )
    if local == "cn":
        return _parse_cn_fraction(node)
    if local == "true":
        return True
    if local == "false":
        return False
    if local == "ci":
        name = "".join(node.itertext()).strip()
        if name in dim_env:
            return Fraction(dim_env[name])
        if name in const_scalars:
            return const_scalars[name]
        if name in const_arrays:
            return const_arrays[name]
        raise ArraysFlatteningError(
            f"Non-constant or unknown symbol {name!r} in static array expression."
        )
    if local == "vector":
        values = [
            _eval_static_value(
                child, dim_env, const_scalars, const_arrays, func_defs, depth + 1
            )
            for child in children
        ]
        _check_rectangular_list(values)
        return values
    if local == "piecewise":
        otherwise_node: Optional[ET.Element] = None
        for part in children:
            part_local = _local_name(str(part.tag)).lower()
            part_children = list(part)
            if part_local == "piece":
                if len(part_children) != 2:
                    raise ArraysFlatteningError("Malformed <piece> in array math.")
                val_node, cond_node = part_children
                cond_val = _eval_static_value(
                    cond_node,
                    dim_env,
                    const_scalars,
                    const_arrays,
                    func_defs,
                    depth + 1,
                )
                if not isinstance(cond_val, bool):
                    raise ArraysFlatteningError(
                        "<piece> condition must evaluate to a boolean in static array math."
                    )
                if cond_val:
                    return _eval_static_value(
                        val_node,
                        dim_env,
                        const_scalars,
                        const_arrays,
                        func_defs,
                        depth + 1,
                    )
            elif part_local == "otherwise":
                if len(part_children) != 1:
                    raise ArraysFlatteningError("Malformed <otherwise> in array math.")
                otherwise_node = part_children[0]
            else:
                raise ArraysFlatteningError(
                    f"Unexpected child <{part_local}> in <piecewise>."
                )
        if otherwise_node is None:
            raise ArraysFlatteningError(
                "No <piece> matched and no <otherwise> in static array expression."
            )
        return _eval_static_value(
            otherwise_node, dim_env, const_scalars, const_arrays, func_defs, depth + 1
        )
    if local != "apply" or not children:
        raise ArraysFlatteningError(
            f"Unsupported MathML construct <{local}> in static array expression."
        )

    op = children[0]
    op_local = _local_name(str(op.tag)).lower()
    args = children[1:]

    if _is_selector_operator(op):
        if len(args) < 2:
            raise ArraysFlatteningError(
                "MathML selector requires a target array and at least one index."
            )
        target = _eval_static_value(
            args[0], dim_env, const_scalars, const_arrays, func_defs, depth + 1
        )
        current = target
        for idx_node in args[1:]:
            if not isinstance(current, list):
                raise ArraysFlatteningError(
                    "selector applied to scalar or given too many indices."
                )
            idx_val = _eval_static_int(
                idx_node, dim_env, const_scalars, const_arrays, func_defs, depth + 1
            )
            if idx_val < 0 or idx_val >= len(current):
                raise ArraysFlatteningError(
                    f"Array selector index {idx_val} out of bounds for size {len(current)}."
                )
            current = current[idx_val]
        return current

    if op_local == "ci":
        fn_name = "".join(op.itertext()).strip()
        fn_spec = func_defs.get(fn_name)
        if fn_spec is None:
            raise ArraysFlatteningError(
                f"Unknown or unsupported function {fn_name!r} in static array expression."
            )
        if len(args) != len(fn_spec.params):
            raise ArraysFlatteningError(
                f"Function {fn_name!r} expected {len(fn_spec.params)} argument(s), "
                f"got {len(args)}."
            )
        eval_args = [
            _eval_static_value(
                arg, dim_env, const_scalars, const_arrays, func_defs, depth + 1
            )
            for arg in args
        ]
        # Bind function arguments as local scalar/array symbols.
        sub_scalars = dict(const_scalars)
        sub_arrays = dict(const_arrays)
        sub_dims = {k: v for k, v in dim_env.items() if k not in fn_spec.params}
        for param_name, val in zip(fn_spec.params, eval_args):
            if isinstance(val, list):
                sub_arrays[param_name] = val
                sub_scalars.pop(param_name, None)
            elif isinstance(val, Fraction):
                sub_scalars[param_name] = val
                sub_arrays.pop(param_name, None)
            else:
                raise ArraysFlatteningError(
                    f"Unsupported argument type passed to {fn_name!r} in static array math."
                )
        return _eval_static_value(
            fn_spec.body, sub_dims, sub_scalars, sub_arrays, func_defs, depth + 1
        )

    eval_args = [
        _eval_static_value(
            arg, dim_env, const_scalars, const_arrays, func_defs, depth + 1
        )
        for arg in args
    ]

    def _require_nums(vals: Sequence[Any]) -> List[Fraction]:
        nums: List[Fraction] = []
        for v in vals:
            if not isinstance(v, Fraction):
                raise ArraysFlatteningError(
                    f"Operator <{op_local}> requires numeric scalar operands."
                )
            nums.append(v)
        return nums

    def _require_bools(vals: Sequence[Any]) -> List[bool]:
        bools: List[bool] = []
        for v in vals:
            if not isinstance(v, bool):
                raise ArraysFlatteningError(
                    f"Operator <{op_local}> requires boolean operands."
                )
            bools.append(v)
        return bools

    if op_local == "plus":
        return sum(_require_nums(eval_args), Fraction(0))
    if op_local == "times":
        acc = Fraction(1)
        for num in _require_nums(eval_args):
            acc *= num
        return acc
    if op_local == "minus":
        nums = _require_nums(eval_args)
        if len(nums) == 1:
            return -nums[0]
        if len(nums) == 2:
            return nums[0] - nums[1]
        raise ArraysFlatteningError("<minus> expects 1 or 2 operands.")
    if op_local == "divide":
        nums = _require_nums(eval_args)
        if len(nums) != 2:
            raise ArraysFlatteningError("<divide> expects 2 operands.")
        if nums[1] == 0:
            raise ArraysFlatteningError("Division by zero in static array expression.")
        return nums[0] / nums[1]
    if op_local == "quotient":
        nums = _require_nums(eval_args)
        if len(nums) != 2 or nums[1] == 0:
            raise ArraysFlatteningError(
                "Invalid <quotient> operands in static array expression."
            )
        return Fraction(math.trunc(nums[0] / nums[1]))
    if op_local == "rem":
        nums = _require_nums(eval_args)
        if len(nums) != 2 or nums[1] == 0:
            raise ArraysFlatteningError(
                "Invalid <rem> operands in static array expression."
            )
        return nums[0] - nums[1] * math.trunc(nums[0] / nums[1])
    if op_local == "power":
        nums = _require_nums(eval_args)
        if len(nums) != 2:
            raise ArraysFlatteningError("<power> expects 2 operands.")
        base, exp = nums
        if exp.denominator != 1:
            raise ArraysFlatteningError(
                "Non-integer exponent in static array expression."
            )
        exp_int = int(exp)
        if abs(exp_int) > 1000:
            raise ArraysFlatteningError(
                "Exponent too large in static array expression."
            )
        if exp_int < 0 and base == 0:
            raise ArraysFlatteningError("Zero to negative power in static array math.")
        return base**exp_int
    if op_local == "abs":
        nums = _require_nums(eval_args)
        if len(nums) != 1:
            raise ArraysFlatteningError("<abs> expects 1 operand.")
        return abs(nums[0])
    if op_local == "floor":
        nums = _require_nums(eval_args)
        if len(nums) != 1:
            raise ArraysFlatteningError("<floor> expects 1 operand.")
        return Fraction(math.floor(nums[0]))
    if op_local == "ceiling":
        nums = _require_nums(eval_args)
        if len(nums) != 1:
            raise ArraysFlatteningError("<ceiling> expects 1 operand.")
        return Fraction(math.ceil(nums[0]))
    if op_local == "min":
        nums = _require_nums(eval_args)
        if not nums:
            raise ArraysFlatteningError("<min> expects at least 1 operand.")
        return min(nums)
    if op_local == "max":
        nums = _require_nums(eval_args)
        if not nums:
            raise ArraysFlatteningError("<max> expects at least 1 operand.")
        return max(nums)
    if op_local == "not":
        bools = _require_bools(eval_args)
        if len(bools) != 1:
            raise ArraysFlatteningError("<not> expects 1 operand.")
        return not bools[0]
    if op_local == "and":
        return all(_require_bools(eval_args))
    if op_local == "or":
        return any(_require_bools(eval_args))
    if op_local == "xor":
        return sum(_require_bools(eval_args)) % 2 == 1
    if op_local == "implies":
        bools = _require_bools(eval_args)
        if len(bools) != 2:
            raise ArraysFlatteningError("<implies> expects 2 operands.")
        return (not bools[0]) or bools[1]
    if op_local in {"eq", "neq", "lt", "leq", "gt", "geq"}:
        if len(eval_args) < 2:
            raise ArraysFlatteningError(f"<{op_local}> expects at least 2 operands.")
        if op_local in {"eq", "neq"}:
            if all(isinstance(v, bool) for v in eval_args):
                if op_local == "neq" and len(eval_args) != 2:
                    raise ArraysFlatteningError("<neq> expects 2 operands.")
                return (
                    all(a == b for a, b in zip(eval_args, eval_args[1:]))
                    if op_local == "eq"
                    else eval_args[0] != eval_args[1]
                )
        nums = _require_nums(eval_args)
        if op_local == "neq":
            if len(nums) != 2:
                raise ArraysFlatteningError("<neq> expects 2 operands.")
            return nums[0] != nums[1]
        comparators = {
            "eq": lambda a, b: a == b,
            "lt": lambda a, b: a < b,
            "leq": lambda a, b: a <= b,
            "gt": lambda a, b: a > b,
            "geq": lambda a, b: a >= b,
        }
        cmp_fn = comparators[op_local]
        return all(cmp_fn(a, b) for a, b in zip(nums, nums[1:]))

    raise ArraysFlatteningError(
        f"Unsupported MathML operator <{op_local}> in static array expression."
    )


def _eval_static_int(
    node: ET.Element,
    dim_env: Mapping[str, int],
    const_scalars: Mapping[str, Fraction],
    const_arrays: Mapping[str, Any],
    func_defs: Mapping[str, FunctionDefSpec],
    depth: int = 0,
) -> int:
    value = _eval_static_value(
        node, dim_env, const_scalars, const_arrays, func_defs, depth
    )
    if not isinstance(value, Fraction):
        raise ArraysFlatteningError(
            "Static array index expression did not evaluate to an integer."
        )
    if value.denominator != 1:
        raise ArraysFlatteningError(
            f"Static array index expression evaluated to non-integer {float(value):g}."
        )
    return int(value.numerator)


def _check_rectangular_list(value: Any) -> Tuple[int, ...]:
    """Return rectangular shape of nested lists, raising if jagged."""

    if not isinstance(value, list):
        return ()
    if not value:
        return (0,)
    first_shape = _check_rectangular_list(value[0])
    for item in value[1:]:
        item_shape = _check_rectangular_list(item)
        if item_shape != first_shape:
            raise ArraysFlatteningError(
                f"Jagged (non-rectangular) <vector>: shapes {first_shape} vs {item_shape}."
            )
    return (len(value),) + first_shape


def _nested_ci_array(
    base_id: str, shape: Tuple[int, ...], prefix: Tuple[int, ...] = ()
) -> Any:
    if not shape:
        return _make_ci(_flat_id(base_id, prefix))
    return [
        _nested_ci_array(base_id, shape[1:], prefix + (idx,)) for idx in range(shape[0])
    ]


def _flatten_nested_leaves(value: Any) -> List[ET.Element]:
    if isinstance(value, ET.Element):
        return [value]
    result: List[ET.Element] = []
    for item in value:
        result.extend(_flatten_nested_leaves(item))
    return result


def _index_nested(value: Any, coords: Sequence[int]) -> ET.Element:
    current = value
    for idx in coords:
        current = current[idx]
    assert isinstance(current, ET.Element)
    return current


def _push_piecewise_over_arrays(
    branches: Sequence[Tuple[Any, ET.Element]],
    otherwise: Optional[Any],
    shape: Tuple[int, ...],
) -> Any:
    """Distribute ``<piecewise>`` elementwise over matching-shape array branches."""

    if not shape:
        pw = ET.Element(_math_tag("piecewise"))
        for val_elem, cond_elem in branches:
            piece = ET.SubElement(pw, _math_tag("piece"))
            piece.append(copy.deepcopy(val_elem))
            piece.append(copy.deepcopy(cond_elem))
        if otherwise is not None:
            ow = ET.SubElement(pw, _math_tag("otherwise"))
            ow.append(copy.deepcopy(otherwise))
        return pw
    return [
        _push_piecewise_over_arrays(
            [(val[i], cond) for val, cond in branches],
            otherwise[i] if otherwise is not None else None,
            shape[1:],
        )
        for i in range(shape[0])
    ]


def _flatten_math_node(
    node: ET.Element,
    dim_env: Mapping[str, int],
    symbol_shapes: Mapping[str, Tuple[int, ...]],
    local_shapes: Mapping[str, Tuple[int, ...]],
    const_scalars: Mapping[str, Fraction],
    const_arrays: Mapping[str, Any],
    func_defs: Mapping[str, FunctionDefSpec],
) -> Any:
    """Rewrite MathML node, returning a scalar ``ET.Element`` or nested ``list``."""

    local = _local_name(str(node.tag)).lower()
    children = list(node)

    if local == "vector":
        items = [
            _flatten_math_node(
                child,
                dim_env,
                symbol_shapes,
                local_shapes,
                const_scalars,
                const_arrays,
                func_defs,
            )
            for child in children
        ]
        _check_rectangular_list(items)
        return items

    if local == "ci":
        name = "".join(node.itertext()).strip()
        if name in dim_env:
            return _make_cn_int(dim_env[name])
        if name in local_shapes:
            shape = local_shapes[name]
            if shape:
                return _nested_ci_array(name, shape)
            return copy.deepcopy(node)
        if name in symbol_shapes and symbol_shapes[name]:
            return _nested_ci_array(name, symbol_shapes[name])
        return copy.deepcopy(node)

    if local == "lambda":
        bound: Set[str] = set()
        new_lambda = ET.Element(node.tag, dict(node.attrib))
        for child in children:
            if _local_name(str(child.tag)).lower() == "bvar":
                for ci in child.iter():
                    if _local_name(str(ci.tag)).lower() == "ci":
                        text = "".join(ci.itertext()).strip()
                        if text:
                            bound.add(text)
                new_lambda.append(copy.deepcopy(child))
            else:
                sub_dims = {k: v for k, v in dim_env.items() if k not in bound}
                sub_syms = {k: v for k, v in symbol_shapes.items() if k not in bound}
                sub_locs = {k: v for k, v in local_shapes.items() if k not in bound}
                res = _flatten_math_node(
                    child,
                    sub_dims,
                    sub_syms,
                    sub_locs,
                    const_scalars,
                    const_arrays,
                    func_defs,
                )
                if not isinstance(res, ET.Element):
                    raise ArraysFlatteningError(
                        "Array value inside <lambda> body is not supported."
                    )
                new_lambda.append(res)
        return new_lambda

    if local == "piecewise":
        branches: List[Tuple[Any, ET.Element]] = []
        otherwise_val: Any = None
        has_otherwise = False
        for part in children:
            part_local = _local_name(str(part.tag)).lower()
            part_children = list(part)
            if part_local == "piece":
                if len(part_children) != 2:
                    raise ArraysFlatteningError("Malformed <piece> in MathML.")
                val = _flatten_math_node(
                    part_children[0],
                    dim_env,
                    symbol_shapes,
                    local_shapes,
                    const_scalars,
                    const_arrays,
                    func_defs,
                )
                cond = _flatten_math_node(
                    part_children[1],
                    dim_env,
                    symbol_shapes,
                    local_shapes,
                    const_scalars,
                    const_arrays,
                    func_defs,
                )
                if not isinstance(cond, ET.Element):
                    raise ArraysFlatteningError(
                        "Array value cannot be used as a <piece> condition."
                    )
                branches.append((val, cond))
            elif part_local == "otherwise":
                if len(part_children) != 1:
                    raise ArraysFlatteningError("Malformed <otherwise> in MathML.")
                otherwise_val = _flatten_math_node(
                    part_children[0],
                    dim_env,
                    symbol_shapes,
                    local_shapes,
                    const_scalars,
                    const_arrays,
                    func_defs,
                )
                has_otherwise = True
            else:
                raise ArraysFlatteningError(
                    f"Unexpected child <{part_local}> inside <piecewise>."
                )
        shapes = [_check_rectangular_list(val) for val, _ in branches]
        if has_otherwise:
            shapes.append(_check_rectangular_list(otherwise_val))
        if not shapes:
            return copy.deepcopy(node)
        target_shape = shapes[0]
        if any(s != target_shape for s in shapes[1:]):
            raise ArraysFlatteningError(
                f"<piecewise> branches have mismatched array shapes: {shapes}."
            )
        return _push_piecewise_over_arrays(
            branches, otherwise_val if has_otherwise else None, target_shape
        )

    if local == "apply":
        if not children:
            return copy.deepcopy(node)
        op = children[0]
        op_local = _local_name(str(op.tag)).lower()
        args = children[1:]

        if _is_selector_operator(op):
            if len(args) < 2:
                raise ArraysFlatteningError(
                    "MathML selector requires a target array and at least one index."
                )
            target = _flatten_math_node(
                args[0],
                dim_env,
                symbol_shapes,
                local_shapes,
                const_scalars,
                const_arrays,
                func_defs,
            )
            current = target
            for idx_node in args[1:]:
                if not isinstance(current, list):
                    raise ArraysFlatteningError(
                        "MathML selector applied to scalar or given too many indices."
                    )
                idx_val = _eval_static_int(
                    idx_node, dim_env, const_scalars, const_arrays, func_defs
                )
                if idx_val < 0 or idx_val >= len(current):
                    raise ArraysFlatteningError(
                        f"MathML selector index {idx_val} out of bounds for "
                        f"dimension of size {len(current)}."
                    )
                current = current[idx_val]
            return copy.deepcopy(current)

        sum_prod = _sum_or_product_kind(op)
        if sum_prod is not None:
            return _flatten_sum_or_product(
                sum_prod,
                args,
                dim_env,
                symbol_shapes,
                local_shapes,
                const_scalars,
                const_arrays,
                func_defs,
            )

        new_apply = ET.Element(node.tag, dict(node.attrib))
        if op_local == "ci":
            fn_name = "".join(op.itertext()).strip()
            if fn_name in symbol_shapes and symbol_shapes[fn_name]:
                raise ArraysFlatteningError(
                    f"Array symbol {fn_name!r} cannot be called as a function."
                )
            new_apply.append(copy.deepcopy(op))
        else:
            op_res = _flatten_math_node(
                op,
                dim_env,
                symbol_shapes,
                local_shapes,
                const_scalars,
                const_arrays,
                func_defs,
            )
            if not isinstance(op_res, ET.Element):
                raise ArraysFlatteningError(
                    "Array value cannot be used as a MathML <apply> operator."
                )
            new_apply.append(op_res)

        for arg in args:
            arg_res = _flatten_math_node(
                arg,
                dim_env,
                symbol_shapes,
                local_shapes,
                const_scalars,
                const_arrays,
                func_defs,
            )
            if not isinstance(arg_res, ET.Element):
                raise ArraysFlatteningError(
                    f"Unindexed array value used in scalar MathML operator <{op_local}>."
                )
            new_apply.append(arg_res)
        return new_apply

    # Generic MathML wrapper/leaf (cn, csymbol, true, false, pi, degree, logbase, etc.).
    clone = ET.Element(node.tag, dict(node.attrib))
    clone.text = node.text
    clone.tail = node.tail
    for child in children:
        child_res = _flatten_math_node(
            child,
            dim_env,
            symbol_shapes,
            local_shapes,
            const_scalars,
            const_arrays,
            func_defs,
        )
        if not isinstance(child_res, ET.Element):
            raise ArraysFlatteningError(
                f"Unindexed array value inside scalar MathML element <{local}>."
            )
        clone.append(child_res)
    return clone


def _flatten_sum_or_product(
    kind: str,
    args: Sequence[ET.Element],
    dim_env: Mapping[str, int],
    symbol_shapes: Mapping[str, Tuple[int, ...]],
    local_shapes: Mapping[str, Tuple[int, ...]],
    const_scalars: Mapping[str, Fraction],
    const_arrays: Mapping[str, Any],
    func_defs: Mapping[str, FunctionDefSpec],
) -> ET.Element:
    """Unroll bounded ``<sum>``/``<product>`` or vector reduction into ``<plus>``/``<times>``."""

    identity = 0 if kind == "sum" else 1
    combine_tag = _math_tag("plus" if kind == "sum" else "times")

    def _combine(terms: Sequence[ET.Element]) -> ET.Element:
        if not terms:
            return _make_cn_int(identity)
        if len(terms) == 1:
            return terms[0]
        apply_elem = ET.Element(_math_tag("apply"))
        apply_elem.append(ET.Element(combine_tag))
        for term in terms:
            apply_elem.append(term)
        return apply_elem

    # Form 1: Single vector/array argument: <apply><sum/><ci>X</ci></apply>
    if len(args) == 1 and _local_name(str(args[0].tag)).lower() not in {
        "bvar",
        "lowlimit",
        "uplimit",
        "condition",
        "domainofapplication",
    }:
        target = _flatten_math_node(
            args[0],
            dim_env,
            symbol_shapes,
            local_shapes,
            const_scalars,
            const_arrays,
            func_defs,
        )
        if not isinstance(target, list):
            raise ArraysFlatteningError(
                f"Single-argument <{kind}> requires a vector or arrayed symbol."
            )
        return _combine(_flatten_nested_leaves(target))

    # Form 2: Bounded <bvar> + <lowlimit> + <uplimit> + body
    bvars: List[str] = []
    low_node: Optional[ET.Element] = None
    up_node: Optional[ET.Element] = None
    body_nodes: List[ET.Element] = []
    for arg in args:
        arg_local = _local_name(str(arg.tag)).lower()
        if arg_local == "bvar":
            cis = [
                "".join(el.itertext()).strip()
                for el in arg.iter()
                if _local_name(str(el.tag)).lower() == "ci"
            ]
            if len(cis) != 1 or not cis[0]:
                raise ArraysFlatteningError(f"Malformed <bvar> in <{kind}> expression.")
            bvars.append(cis[0])
        elif arg_local == "lowlimit":
            if low_node is not None or len(list(arg)) != 1:
                raise ArraysFlatteningError(
                    f"Malformed <lowlimit> in <{kind}> expression."
                )
            low_node = list(arg)[0]
        elif arg_local == "uplimit":
            if up_node is not None or len(list(arg)) != 1:
                raise ArraysFlatteningError(
                    f"Malformed <uplimit> in <{kind}> expression."
                )
            up_node = list(arg)[0]
        elif arg_local in {"condition", "domainofapplication"}:
            raise ArraysFlatteningError(
                f"<{kind}> with <{arg_local}> is not supported for static flattening."
            )
        else:
            body_nodes.append(arg)

    if len(bvars) != 1 or low_node is None or up_node is None or len(body_nodes) != 1:
        raise ArraysFlatteningError(
            f"<{kind}> requires a single <bvar>, <lowlimit>, <uplimit>, and body expression."
        )
    low = _eval_static_int(low_node, dim_env, const_scalars, const_arrays, func_defs)
    high = _eval_static_int(up_node, dim_env, const_scalars, const_arrays, func_defs)
    if high - low + 1 > MAX_FLATTENED_ELEMENTS:
        raise ArraysFlatteningError(
            f"<{kind}> range [{low}, {high}] exceeds static flattening limit."
        )
    bvar = bvars[0]
    terms: List[ET.Element] = []
    for val in range(low, high + 1):
        inner_env = dict(dim_env)
        inner_env[bvar] = val
        term = _flatten_math_node(
            body_nodes[0],
            inner_env,
            symbol_shapes,
            local_shapes,
            const_scalars,
            const_arrays,
            func_defs,
        )
        if not isinstance(term, ET.Element):
            raise ArraysFlatteningError(
                f"<{kind}> body must evaluate to a scalar expression."
            )
        terms.append(term)
    return _combine(terms)


def _strip_arrays_from_element(element: ET.Element, arrays_ns: Optional[str]) -> None:
    """Remove direct ``arrays:*`` child containers and ``arrays:*`` attributes."""

    if arrays_ns is None:
        return
    for child in list(element):
        if _is_arrays_namespace(_namespace(str(child.tag))):
            element.remove(child)
    for attr_key in list(element.attrib):
        if _is_arrays_namespace(_namespace(attr_key)):
            del element.attrib[attr_key]


def _rename_cloned_element(element: ET.Element, coords: Sequence[int]) -> None:
    if not coords:
        return
    suffix = "_".join(str(c) for c in coords)
    for attr in ("id", "metaid", "name"):
        val = element.get(attr)
        if val:
            element.set(attr, f"{val}_{suffix}")


def _extract_math_child(element: ET.Element) -> Optional[ET.Element]:
    for child in list(element):
        if _local_name(str(child.tag)) == "math":
            return child
    return None


def _replace_math_child(element: ET.Element, scalar_expr: ET.Element) -> None:
    math_elem = _extract_math_child(element)
    if math_elem is None:
        return
    for child in list(math_elem):
        math_elem.remove(child)
    math_elem.append(scalar_expr)


def _first_core_child(element: ET.Element, local_name: str) -> Optional[ET.Element]:
    for child in list(element):
        if _local_name(str(child.tag)) == local_name:
            return child
    return None


def _collect_function_definitions(
    model: ET.Element, arrays_ns: Optional[str]
) -> Dict[str, FunctionDefSpec]:
    """Validate and collect pure Core ``<functionDefinition>`` elements."""

    func_defs: Dict[str, FunctionDefSpec] = {}
    list_elem = _first_core_child(model, "listOfFunctionDefinitions")
    if list_elem is None:
        return func_defs
    if _element_array_children(list_elem, arrays_ns) != (None, None):
        raise ArraysFlatteningError(
            "arrays constructs are not permitted on <listOfFunctionDefinitions>."
        )
    for fn in list(list_elem):
        if _local_name(str(fn.tag)) != "functionDefinition":
            continue
        if _element_array_children(fn, arrays_ns) != (None, None):
            raise ArraysFlatteningError(
                "SBML arrays dimensions/indices are not supported on <functionDefinition>."
            )
        fn_id = str(fn.get("id", "") or "").strip()
        math_elem = _extract_math_child(fn)
        if math_elem is None:
            continue
        for desc in math_elem.iter():
            desc_local = _local_name(str(desc.tag)).lower()
            if desc_local == "vector" or _is_selector_operator(desc):
                raise ArraysFlatteningError(
                    f"<functionDefinition id={fn_id!r}> contains <vector> or "
                    "<selector>, which is not supported for static flattening."
                )
        if not fn_id or len(list(math_elem)) != 1:
            continue
        lam = list(math_elem)[0]
        if _local_name(str(lam.tag)).lower() != "lambda":
            continue
        params: List[str] = []
        body: Optional[ET.Element] = None
        for child in list(lam):
            if _local_name(str(child.tag)).lower() == "bvar":
                cis = [
                    "".join(el.itertext()).strip()
                    for el in child.iter()
                    if _local_name(str(el.tag)).lower() == "ci"
                ]
                if len(cis) == 1 and cis[0]:
                    params.append(cis[0])
            else:
                body = child
        if body is not None:
            func_defs[fn_id] = FunctionDefSpec(params=tuple(params), body=body)
    return func_defs


def _resolve_constant_scalar_parameters(
    model: ET.Element,
    arrays_ns: Optional[str],
    func_defs: Mapping[str, FunctionDefSpec],
) -> Tuple[Dict[str, Fraction], Dict[str, int]]:
    """Resolve scalar constant parameters for dimension sizes and index math.

    Returns ``(const_scalars, valid_size_params)`` where ``valid_size_params``
    maps scalar constant non-negative integer parameter IDs to ``int`` values.
    """

    # Any symbol written by a rule or eventAssignment cannot be constant.
    mutated_ids: Set[str] = set()
    rules_list = _first_core_child(model, "listOfRules")
    if rules_list is not None:
        for rule in list(rules_list):
            if _local_name(str(rule.tag)) in {"assignmentRule", "rateRule"}:
                var = str(rule.get("variable", "") or "").strip()
                if var:
                    mutated_ids.add(var)
    events_list = _first_core_child(model, "listOfEvents")
    if events_list is not None:
        for event in list(events_list):
            ea_list = _first_core_child(event, "listOfEventAssignments")
            if ea_list is not None:
                for ea in list(ea_list):
                    var = str(ea.get("variable", "") or "").strip()
                    if var:
                        mutated_ids.add(var)

    # Collect scalar initialAssignments so constant parameters initialized by
    # initialAssignment resolve cleanly (and override their `value` attribute).
    scalar_init_assigns: Dict[str, ET.Element] = {}
    ia_list = _first_core_child(model, "listOfInitialAssignments")
    if ia_list is not None:
        for ia in list(ia_list):
            if _local_name(str(ia.tag)) != "initialAssignment":
                continue
            dims_el, idx_el = _element_array_children(ia, arrays_ns)
            if dims_el is not None or idx_el is not None:
                continue
            sym = str(ia.get("symbol", "") or "").strip()
            math_el = _extract_math_child(ia)
            if sym and math_el is not None and len(list(math_el)) == 1:
                scalar_init_assigns[sym] = list(math_el)[0]

    const_scalars: Dict[str, Fraction] = {}
    deferred_const_params: List[str] = []
    params_list = _first_core_child(model, "listOfParameters")
    if params_list is not None:
        for param in list(params_list):
            if _local_name(str(param.tag)) != "parameter":
                continue
            dims_el, _ = _element_array_children(param, arrays_ns)
            if dims_el is not None and len(list(dims_el)) > 0:
                continue
            pid = str(param.get("id", "") or "").strip()
            if not pid or pid in mutated_ids:
                continue
            if str(param.get("constant", "") or "").strip().lower() != "true":
                continue
            if pid in scalar_init_assigns:
                deferred_const_params.append(pid)
                continue
            raw_val = param.get("value")
            if raw_val is None or not str(raw_val).strip():
                continue
            try:
                fval = float(str(raw_val).strip())
                if math.isfinite(fval):
                    const_scalars[pid] = Fraction(str(raw_val).strip())
            except ValueError:
                continue

    # Iteratively resolve constant scalar parameters initialized by initialAssignment.
    for _ in range(len(deferred_const_params) + 1):
        progressed = False
        for pid in deferred_const_params:
            if pid in const_scalars:
                continue
            try:
                val = _eval_static_value(
                    scalar_init_assigns[pid], {}, const_scalars, {}, func_defs
                )
            except ArraysFlatteningError:
                continue
            if isinstance(val, Fraction):
                const_scalars[pid] = val
                progressed = True
        if not progressed:
            break

    valid_size_params: Dict[str, int] = {}
    for pid, frac in const_scalars.items():
        if frac.denominator == 1 and frac.numerator >= 0:
            valid_size_params[pid] = int(frac.numerator)

    return const_scalars, valid_size_params


def _resolve_constant_array_parameters(
    model: ET.Element,
    arrays_ns: Optional[str],
    size_values: Mapping[str, int],
    const_scalars: Mapping[str, Fraction],
    func_defs: Mapping[str, FunctionDefSpec],
) -> Dict[str, Any]:
    """Resolve constant arrayed parameters so static ``selector(const_arr, i)`` works in indices."""

    mutated_ids: Set[str] = set()
    rules_list = _first_core_child(model, "listOfRules")
    if rules_list is not None:
        for rule in list(rules_list):
            if _local_name(str(rule.tag)) in {"assignmentRule", "rateRule"}:
                var = str(rule.get("variable", "") or "").strip()
                if var:
                    mutated_ids.add(var)
    events_list = _first_core_child(model, "listOfEvents")
    if events_list is not None:
        for event in list(events_list):
            ea_list = _first_core_child(event, "listOfEventAssignments")
            if ea_list is not None:
                for ea in list(ea_list):
                    var = str(ea.get("variable", "") or "").strip()
                    if var:
                        mutated_ids.add(var)

    # Identify constant arrayed parameters and their shapes.
    const_array_shapes: Dict[str, Tuple[int, ...]] = {}
    const_arrays: Dict[str, Any] = {}
    params_list = _first_core_child(model, "listOfParameters")
    if params_list is None:
        return const_arrays

    def _fill_nested(shape: Tuple[int, ...], fill_val: Any) -> Any:
        if not shape:
            return fill_val
        return [_fill_nested(shape[1:], fill_val) for _ in range(shape[0])]

    for param in list(params_list):
        if _local_name(str(param.tag)) != "parameter":
            continue
        dims = _parse_dimensions_raw(param, arrays_ns, size_values)
        if not dims:
            continue
        pid = str(param.get("id", "") or "").strip()
        if not pid or pid in mutated_ids:
            continue
        if str(param.get("constant", "") or "").strip().lower() != "true":
            continue
        shape = tuple(d.size for d in dims)
        const_array_shapes[pid] = shape
        raw_val = param.get("value")
        if raw_val is not None and str(raw_val).strip():
            try:
                fval = float(str(raw_val).strip())
                if math.isfinite(fval):
                    const_arrays[pid] = _fill_nested(
                        shape, Fraction(str(raw_val).strip())
                    )
            except ValueError:
                pass

    # Override with static vector/indexed initialAssignments when resolvable.
    ia_list = _first_core_child(model, "listOfInitialAssignments")
    if ia_list is not None and const_array_shapes:
        for ia in list(ia_list):
            if _local_name(str(ia.tag)) != "initialAssignment":
                continue
            sym = str(ia.get("symbol", "") or "").strip()
            if sym not in const_array_shapes:
                continue
            dims = _parse_dimensions_raw(ia, arrays_ns, size_values)
            indices = _parse_indices(ia, arrays_ns)
            math_el = _extract_math_child(ia)
            if math_el is None or len(list(math_el)) != 1:
                continue
            expr = list(math_el)[0]
            shape = const_array_shapes[sym]
            if not dims and not indices:
                try:
                    val = _eval_static_value(
                        expr, {}, const_scalars, const_arrays, func_defs
                    )
                    if isinstance(val, list) and _check_rectangular_list(val) == shape:
                        const_arrays[sym] = val
                except ArraysFlatteningError:
                    const_arrays.pop(sym, None)
            else:
                # Indexed initialAssignment on a constant arrayed parameter:
                # populate element-by-element if all coordinates resolve statically.
                sym_indices = indices.get("symbol", [])
                if len(sym_indices) == len(shape):
                    arr = const_arrays.get(sym)
                    if arr is None:
                        arr = _fill_nested(shape, None)
                    ok = True
                    for coords in itertools.product(*(range(d.size) for d in dims)):
                        dim_env = {
                            d.id: c for d, c in zip(dims, coords) if d.id is not None
                        }
                        try:
                            target_coords = [
                                _eval_static_int(
                                    idx.math,
                                    dim_env,
                                    const_scalars,
                                    const_arrays,
                                    func_defs,
                                )
                                for idx in sym_indices
                            ]
                            if any(
                                tc < 0 or tc >= s for tc, s in zip(target_coords, shape)
                            ):
                                ok = False
                                break
                            val = _eval_static_value(
                                expr, dim_env, const_scalars, const_arrays, func_defs
                            )
                            if not isinstance(val, Fraction):
                                ok = False
                                break
                            cur = arr
                            for tc in target_coords[:-1]:
                                cur = cur[tc]
                            cur[target_coords[-1]] = val
                        except ArraysFlatteningError:
                            ok = False
                            break
                    if ok:
                        const_arrays[sym] = arr
                    else:
                        const_arrays.pop(sym, None)

        # Discard any partially-populated constant arrays (with None holes).
        def _has_none(obj: Any) -> bool:
            if obj is None:
                return True
            if isinstance(obj, list):
                return any(_has_none(x) for x in obj)
            return False

        for pid in list(const_arrays):
            if _has_none(const_arrays[pid]):
                del const_arrays[pid]

    return const_arrays


def _detect_arrays_namespace(
    root: ET.Element, parent_map: Mapping[ET.Element, ET.Element]
) -> Optional[str]:
    """Return the active ``arrays`` v1 namespace URI if present, validating version."""

    found: Set[str] = set()
    for elem in root.iter():
        if _inside_opaque_core_container(elem, parent_map):
            continue
        ns = _namespace(str(elem.tag))
        if _is_arrays_namespace(ns):
            found.add(ns)
        for attr_key in elem.attrib:
            attr_ns = _namespace(attr_key)
            if _is_arrays_namespace(attr_ns):
                found.add(attr_ns)
    if not found:
        return None
    if len(found) > 1:
        raise ArraysFlatteningError(
            f"Multiple SBML arrays namespaces declared in one document: {sorted(found)}."
        )
    uri = next(iter(found))
    version = _arrays_version(uri)
    if version != 1:
        raise ArraysFlatteningError(
            f"Unsupported SBML arrays package version {version} ({uri}); "
            "only Level 3 arrays version 1 is supported."
        )
    return uri


def has_arrays_constructs(sbml_string: str) -> bool:
    """Return whether an SBML document contains active ``arrays`` elements or math.

    Empty ``xmlns:arrays`` declarations (or markup solely inside Core
    ``<annotation>``/``<notes>``) return ``False``.
    """

    try:
        root = ET.fromstring(sbml_string)
    except ET.ParseError:
        return False
    parent_map = _build_parent_map(root)
    for elem in root.iter():
        if _inside_opaque_core_container(elem, parent_map):
            continue
        ns = _namespace(str(elem.tag))
        if _is_arrays_namespace(ns):
            return True
        if elem is not root:
            for attr_key in elem.attrib:
                if _is_arrays_namespace(_namespace(attr_key)):
                    return True
        local = _local_name(str(elem.tag)).lower()
        if local == "vector" or _is_selector_operator(elem):
            return True
    return False


def _iter_coords(
    dims: Sequence[DimensionSpec],
    outer_env: Mapping[str, int],
    budget: List[int],
) -> Iterable[Tuple[Tuple[int, ...], Dict[str, int]]]:
    """Yield ``(coords, merged_dim_env)`` for every coordinate of ``dims``."""

    for dim in dims:
        if dim.id is not None and dim.id in outer_env:
            raise ArraysFlatteningError(
                f"Nested arrays:dimension id={dim.id!r} shadows an enclosing dimension."
            )
    if not dims:
        yield (), dict(outer_env)
        return
    product_size = 1
    for dim in dims:
        product_size *= dim.size
        if product_size > MAX_FLATTENED_ELEMENTS:
            raise ArraysFlatteningError(
                f"Static array expansion size ({product_size}) exceeds limit "
                f"({MAX_FLATTENED_ELEMENTS})."
            )
    budget[0] += product_size
    if budget[0] > MAX_FLATTENED_ELEMENTS:
        raise ArraysFlatteningError(
            f"Total flattened array element count exceeds limit ({MAX_FLATTENED_ELEMENTS})."
        )
    for coords in itertools.product(*(range(d.size) for d in dims)):
        env = dict(outer_env)
        for dim, val in zip(dims, coords):
            if dim.id is not None:
                env[dim.id] = val
        yield coords, env


def _resolve_indexed_attribute(
    element: ET.Element,
    attr_name: str,
    indices_by_attr: Mapping[str, List[IndexSpec]],
    dim_env: Mapping[str, int],
    symbol_shapes: Mapping[str, Tuple[int, ...]],
    const_scalars: Mapping[str, Fraction],
    const_arrays: Mapping[str, Any],
    func_defs: Mapping[str, FunctionDefSpec],
    allow_partial: bool = False,
) -> Tuple[str, Tuple[int, ...], Tuple[int, ...]]:
    """Resolve an SIdRef attribute using ``listOfIndices``.

    Returns ``(resolved_or_base_id, resolved_indices, remaining_shape)``.
    """

    base_target = str(element.get(attr_name, "") or "").strip()
    attr_indices = indices_by_attr.get(attr_name, [])
    target_shape = symbol_shapes.get(base_target, ())
    elem_local = _local_name(str(element.tag))

    if not target_shape:
        if attr_indices:
            raise ArraysFlatteningError(
                f"arrays:index provided for scalar attribute "
                f"<{elem_local} {attr_name}={base_target!r}>."
            )
        return base_target, (), ()

    if len(attr_indices) > len(target_shape):
        raise ArraysFlatteningError(
            f"Too many arrays:index entries ({len(attr_indices)}) for "
            f"{len(target_shape)}D target {base_target!r} on <{elem_local}>."
        )

    idx_vals: List[int] = []
    for k, spec in enumerate(attr_indices):
        val = _eval_static_int(
            spec.math, dim_env, const_scalars, const_arrays, func_defs
        )
        if val < 0 or val >= target_shape[k]:
            raise ArraysFlatteningError(
                f"arrays:index {val} out of bounds for dimension {k} "
                f"(size {target_shape[k]}) of {base_target!r} on <{elem_local}>."
            )
        idx_vals.append(val)

    remaining_shape = target_shape[len(idx_vals) :]
    if remaining_shape and not allow_partial:
        raise ArraysFlatteningError(
            f"<{elem_local} {attr_name}={base_target!r}> references a "
            f"{len(target_shape)}D array, but only {len(idx_vals)} index(es) "
            "were provided."
        )
    if not remaining_shape:
        return _flat_id(base_target, idx_vals), tuple(idx_vals), ()
    return base_target, tuple(idx_vals), remaining_shape


def _flatten_assignment_like(
    element: ET.Element,
    attr_name: str,
    outer_env: Mapping[str, int],
    arrays_ns: Optional[str],
    size_values: Mapping[str, int],
    symbol_shapes: Mapping[str, Tuple[int, ...]],
    const_scalars: Mapping[str, Fraction],
    const_arrays: Mapping[str, Any],
    func_defs: Mapping[str, FunctionDefSpec],
    seen_targets: Set[str],
    budget: List[int],
) -> List[ET.Element]:
    """Flatten ``initialAssignment``, ``assignmentRule``, ``rateRule``, or ``eventAssignment``."""

    elem_local = _local_name(str(element.tag))
    dims = _parse_dimensions_raw(element, arrays_ns, size_values)
    indices = _parse_indices(element, arrays_ns)
    math_el = _extract_math_child(element)

    emitted: List[ET.Element] = []
    for coords, dim_env in _iter_coords(dims, outer_env, budget):
        base_or_flat, idx_vals, remaining_shape = _resolve_indexed_attribute(
            element,
            attr_name,
            indices,
            dim_env,
            symbol_shapes,
            const_scalars,
            const_arrays,
            func_defs,
            allow_partial=True,
        )

        if math_el is None or len(list(math_el)) == 0:
            if remaining_shape:
                raise ArraysFlatteningError(
                    f"<{elem_local} {attr_name}={base_or_flat!r}> targeting an "
                    "unindexed array has empty <math>."
                )
            if base_or_flat in seen_targets:
                raise ArraysFlatteningError(
                    f"Duplicate <{elem_local}> target {base_or_flat!r} after "
                    "array flattening."
                )
            seen_targets.add(base_or_flat)
            clone = copy.deepcopy(element)
            _strip_arrays_from_element(clone, arrays_ns)
            _rename_cloned_element(clone, coords)
            clone.set(attr_name, base_or_flat)
            emitted.append(clone)
            continue

        if len(list(math_el)) != 1:
            raise ArraysFlatteningError(
                f"Malformed <math> inside <{elem_local} {attr_name}={base_or_flat!r}>."
            )
        rhs = _flatten_math_node(
            list(math_el)[0],
            dim_env,
            symbol_shapes,
            {},
            const_scalars,
            const_arrays,
            func_defs,
        )
        rhs_shape = _check_rectangular_list(rhs)
        if rhs_shape != remaining_shape:
            raise ArraysFlatteningError(
                f"Shape mismatch on <{elem_local} {attr_name}={base_or_flat!r}>: "
                f"target expects shape {remaining_shape}, math produced {rhs_shape}."
            )

        if not remaining_shape:
            assert isinstance(rhs, ET.Element)
            if base_or_flat in seen_targets:
                raise ArraysFlatteningError(
                    f"Duplicate <{elem_local}> target {base_or_flat!r} after "
                    "array flattening."
                )
            seen_targets.add(base_or_flat)
            clone = copy.deepcopy(element)
            _strip_arrays_from_element(clone, arrays_ns)
            _rename_cloned_element(clone, coords)
            clone.set(attr_name, base_or_flat)
            _replace_math_child(clone, rhs)
            emitted.append(clone)
        else:
            for sub_coords in itertools.product(*(range(d) for d in remaining_shape)):
                full_target = _flat_id(base_or_flat, idx_vals + sub_coords)
                if full_target in seen_targets:
                    raise ArraysFlatteningError(
                        f"Duplicate <{elem_local}> target {full_target!r} after "
                        "array flattening."
                    )
                seen_targets.add(full_target)
                budget[0] += 1
                if budget[0] > MAX_FLATTENED_ELEMENTS:
                    raise ArraysFlatteningError(
                        f"Total flattened array element count exceeds limit "
                        f"({MAX_FLATTENED_ELEMENTS})."
                    )
                clone = copy.deepcopy(element)
                _strip_arrays_from_element(clone, arrays_ns)
                _rename_cloned_element(clone, coords + sub_coords)
                clone.set(attr_name, full_target)
                _replace_math_child(
                    clone, copy.deepcopy(_index_nested(rhs, sub_coords))
                )
                emitted.append(clone)

    return emitted


def _flatten_scalar_math_container(
    container: ET.Element,
    dim_env: Mapping[str, int],
    arrays_ns: Optional[str],
    symbol_shapes: Mapping[str, Tuple[int, ...]],
    local_shapes: Mapping[str, Tuple[int, ...]],
    const_scalars: Mapping[str, Fraction],
    const_arrays: Mapping[str, Any],
    func_defs: Mapping[str, FunctionDefSpec],
) -> None:
    """Validate and flatten a scalar ``<math>`` child of ``container`` in place."""

    if _element_array_children(container, arrays_ns) != (None, None):
        raise ArraysFlatteningError(
            f"SBML arrays dimensions/indices are not permitted on "
            f"<{_local_name(str(container.tag))}>."
        )
    math_el = _extract_math_child(container)
    if math_el is None or len(list(math_el)) == 0:
        return
    if len(list(math_el)) != 1:
        raise ArraysFlatteningError(
            f"Malformed <math> inside <{_local_name(str(container.tag))}>."
        )
    flattened = _flatten_math_node(
        list(math_el)[0],
        dim_env,
        symbol_shapes,
        local_shapes,
        const_scalars,
        const_arrays,
        func_defs,
    )
    if not isinstance(flattened, ET.Element):
        raise ArraysFlatteningError(
            f"Array value is not allowed in scalar <{_local_name(str(container.tag))}> math."
        )
    _replace_math_child(container, flattened)


def flatten_arrays_sbml(sbml_string: str) -> str:
    """Statically flatten an SBML Level 3 ``arrays`` v1 XML string into Core SBML.

    Returns the original ``sbml_string`` unchanged when no active ``arrays``
    constructs or MathML ``<vector>``/``<selector>`` nodes are present.
    Raises :class:`ArraysFlatteningError` on any invalid or non-static construct.
    """

    try:
        root = ET.fromstring(sbml_string)
    except ET.ParseError as exc:
        raise ArraysFlatteningError(f"Invalid SBML XML: {exc}") from exc

    parent_map = _build_parent_map(root)
    arrays_ns = _detect_arrays_namespace(root, parent_map)
    if not has_arrays_constructs(sbml_string):
        return sbml_string

    core_ns = _namespace(str(root.tag))
    model = next(
        (elem for elem in list(root) if _local_name(str(elem.tag)) == "model"), None
    )
    if model is None:
        raise ArraysFlatteningError("SBML document has no <model> element.")

    # Reject arrays elements on <sbml>, <model>, or any listOf* containers.
    if _element_array_children(root, arrays_ns) != (None, None):
        raise ArraysFlatteningError(
            "SBML arrays dimensions/indices are not permitted on <sbml>."
        )
    if _element_array_children(model, arrays_ns) != (None, None):
        raise ArraysFlatteningError(
            "SBML arrays dimensions/indices are not permitted on <model>."
        )
    for child in list(model):
        if _local_name(str(child.tag)).startswith("listOf"):
            if _element_array_children(child, arrays_ns) != (None, None):
                raise ArraysFlatteningError(
                    f"SBML arrays dimensions/indices are not permitted on "
                    f"<{_local_name(str(child.tag))}>."
                )

    unit_defs = _first_core_child(model, "listOfUnitDefinitions")
    if unit_defs is not None:
        for elem in unit_defs.iter():
            if _is_arrays_namespace(_namespace(str(elem.tag))):
                raise ArraysFlatteningError(
                    "SBML arrays constructs are not permitted inside <listOfUnitDefinitions>."
                )

    func_defs = _collect_function_definitions(model, arrays_ns)
    const_scalars, size_values = _resolve_constant_scalar_parameters(
        model, arrays_ns, func_defs
    )
    const_arrays = _resolve_constant_array_parameters(
        model, arrays_ns, size_values, const_scalars, func_defs
    )

    # Pass 1: Collect array shapes for all model-level SIds and check collisions.
    symbol_shapes: Dict[str, Tuple[int, ...]] = {}
    all_named_shapes: List[Tuple[str, Tuple[int, ...]]] = []

    def _register_named(
        elem: ET.Element, shape: Tuple[int, ...], in_math: bool = True
    ) -> None:
        sid = str(elem.get("id", "") or "").strip()
        if not sid:
            return
        if in_math:
            symbol_shapes[sid] = shape
        all_named_shapes.append((sid, shape))

    for list_name, item_name, in_math in (
        ("listOfCompartments", "compartment", True),
        ("listOfSpecies", "species", True),
        ("listOfParameters", "parameter", True),
        ("listOfEvents", "event", False),
    ):
        container = _first_core_child(model, list_name)
        if container is None:
            continue
        for item in list(container):
            if _local_name(str(item.tag)) != item_name:
                continue
            dims = _parse_dimensions_raw(item, arrays_ns, size_values)
            _register_named(item, tuple(d.size for d in dims), in_math=in_math)

    reactions_container = _first_core_child(model, "listOfReactions")
    if reactions_container is not None:
        for rxn in list(reactions_container):
            if _local_name(str(rxn.tag)) != "reaction":
                continue
            rxn_dims = _parse_dimensions_raw(rxn, arrays_ns, size_values)
            rxn_shape = tuple(d.size for d in rxn_dims)
            _register_named(rxn, rxn_shape, in_math=True)
            for ref_list_name in ("listOfReactants", "listOfProducts"):
                ref_list = _first_core_child(rxn, ref_list_name)
                if ref_list is None:
                    continue
                for sr in list(ref_list):
                    if _local_name(str(sr.tag)) != "speciesReference":
                        continue
                    sr_dims = _parse_dimensions_raw(sr, arrays_ns, size_values)
                    sr_shape = rxn_shape + tuple(d.size for d in sr_dims)
                    _register_named(sr, sr_shape, in_math=True)

    # Include functionDefinition IDs in collision checking.
    for fn_id in func_defs:
        all_named_shapes.append((fn_id, ()))

    # Validate flattened ID uniqueness across the model SId namespace.
    # Register scalar SIds first so any collision with an expanded array ID
    # reports the arrayed source clearly.
    model_base_sids: Set[str] = {base_id for base_id, _ in all_named_shapes}
    seen_sids: Set[str] = set()
    for base_id, shape in all_named_shapes:
        if not shape:
            if base_id in seen_sids:
                raise ArraysFlatteningError(
                    f"Duplicate model SId {base_id!r} encountered during arrays flattening."
                )
            seen_sids.add(base_id)
    for base_id, shape in all_named_shapes:
        if shape:
            prod = 1
            for s in shape:
                prod *= s
                if prod > MAX_FLATTENED_ELEMENTS:
                    raise ArraysFlatteningError(
                        f"Arrayed symbol {base_id!r} with shape {shape} exceeds "
                        f"flattening limit ({MAX_FLATTENED_ELEMENTS})."
                    )
            for coords in itertools.product(*(range(s) for s in shape)):
                fid = _flat_id(base_id, coords)
                if fid in seen_sids:
                    raise ArraysFlatteningError(
                        f"Flattened array ID {fid!r} (from {base_id!r}) collides "
                        "with another model identifier."
                    )
                seen_sids.add(fid)

    # Validate that no arrays:dimension id collides with a model-level SId
    # (SBML L3 arrays v1 rule arrays-20202).
    if arrays_ns is not None:
        for elem in model.iter():
            if _inside_opaque_core_container(elem, parent_map):
                continue
            if (
                _namespace(str(elem.tag)) == arrays_ns
                and _local_name(str(elem.tag)) == "dimension"
            ):
                dim_id = _arrays_attr(elem, arrays_ns, "id")
                if dim_id and dim_id.strip() in model_base_sids:
                    raise ArraysFlatteningError(
                        f"arrays:dimension id={dim_id.strip()!r} collides with an "
                        "existing model SId."
                    )

    budget = [0]

    # Pass 2: Flatten each model list in place.
    # 2a. Compartments
    comp_list = _first_core_child(model, "listOfCompartments")
    if comp_list is not None:
        new_comps: List[ET.Element] = []
        for comp in list(comp_list):
            if _local_name(str(comp.tag)) != "compartment":
                new_comps.append(comp)
                continue
            dims = _parse_dimensions_raw(comp, arrays_ns, size_values)
            _parse_indices(comp, arrays_ns)
            for coords, _env in _iter_coords(dims, {}, budget):
                clone = copy.deepcopy(comp)
                _strip_arrays_from_element(clone, arrays_ns)
                _rename_cloned_element(clone, coords)
                new_comps.append(clone)
        comp_list[:] = new_comps

    # 2b. Species
    species_list = _first_core_child(model, "listOfSpecies")
    if species_list is not None:
        new_species: List[ET.Element] = []
        for sp in list(species_list):
            if _local_name(str(sp.tag)) != "species":
                new_species.append(sp)
                continue
            dims = _parse_dimensions_raw(sp, arrays_ns, size_values)
            indices = _parse_indices(sp, arrays_ns)
            for coords, dim_env in _iter_coords(dims, {}, budget):
                clone = copy.deepcopy(sp)
                _strip_arrays_from_element(clone, arrays_ns)
                _rename_cloned_element(clone, coords)
                if sp.get("compartment") is not None:
                    comp_id, _, _ = _resolve_indexed_attribute(
                        sp,
                        "compartment",
                        indices,
                        dim_env,
                        symbol_shapes,
                        const_scalars,
                        const_arrays,
                        func_defs,
                    )
                    clone.set("compartment", comp_id)
                if sp.get("conversionFactor") is not None:
                    cf_id, _, _ = _resolve_indexed_attribute(
                        sp,
                        "conversionFactor",
                        indices,
                        dim_env,
                        symbol_shapes,
                        const_scalars,
                        const_arrays,
                        func_defs,
                    )
                    clone.set("conversionFactor", cf_id)
                new_species.append(clone)
        species_list[:] = new_species

    # 2c. Parameters
    params_list = _first_core_child(model, "listOfParameters")
    if params_list is not None:
        new_params: List[ET.Element] = []
        for param in list(params_list):
            if _local_name(str(param.tag)) != "parameter":
                new_params.append(param)
                continue
            dims = _parse_dimensions_raw(param, arrays_ns, size_values)
            _parse_indices(param, arrays_ns)
            for coords, _env in _iter_coords(dims, {}, budget):
                clone = copy.deepcopy(param)
                _strip_arrays_from_element(clone, arrays_ns)
                _rename_cloned_element(clone, coords)
                new_params.append(clone)
        params_list[:] = new_params

    # 2d. InitialAssignments
    ia_list = _first_core_child(model, "listOfInitialAssignments")
    if ia_list is not None:
        seen_ia_symbols: Set[str] = set()
        new_ias: List[ET.Element] = []
        for ia in list(ia_list):
            if _local_name(str(ia.tag)) != "initialAssignment":
                new_ias.append(ia)
                continue
            new_ias.extend(
                _flatten_assignment_like(
                    ia,
                    "symbol",
                    {},
                    arrays_ns,
                    size_values,
                    symbol_shapes,
                    const_scalars,
                    const_arrays,
                    func_defs,
                    seen_ia_symbols,
                    budget,
                )
            )
        ia_list[:] = new_ias

    # 2e. Rules (assignmentRule, rateRule, algebraicRule)
    rules_list = _first_core_child(model, "listOfRules")
    if rules_list is not None:
        seen_rule_vars: Set[str] = set()
        new_rules: List[ET.Element] = []
        for rule in list(rules_list):
            rule_local = _local_name(str(rule.tag))
            if rule_local in {"assignmentRule", "rateRule"}:
                new_rules.extend(
                    _flatten_assignment_like(
                        rule,
                        "variable",
                        {},
                        arrays_ns,
                        size_values,
                        symbol_shapes,
                        const_scalars,
                        const_arrays,
                        func_defs,
                        seen_rule_vars,
                        budget,
                    )
                )
            elif rule_local == "algebraicRule":
                dims = _parse_dimensions_raw(rule, arrays_ns, size_values)
                _parse_indices(rule, arrays_ns)
                for coords, dim_env in _iter_coords(dims, {}, budget):
                    clone = copy.deepcopy(rule)
                    _strip_arrays_from_element(clone, arrays_ns)
                    _rename_cloned_element(clone, coords)
                    _flatten_scalar_math_container(
                        clone,
                        dim_env,
                        arrays_ns,
                        symbol_shapes,
                        {},
                        const_scalars,
                        const_arrays,
                        func_defs,
                    )
                    new_rules.append(clone)
            else:
                new_rules.append(rule)
        rules_list[:] = new_rules

    # 2f. Reactions (with speciesReferences, modifiers, localParameters, kineticLaw)
    if reactions_container is not None:
        new_reactions: List[ET.Element] = []
        for rxn in list(reactions_container):
            if _local_name(str(rxn.tag)) != "reaction":
                new_reactions.append(rxn)
                continue
            rxn_dims = _parse_dimensions_raw(rxn, arrays_ns, size_values)
            rxn_indices = _parse_indices(rxn, arrays_ns)
            for rxn_coords, rxn_env in _iter_coords(rxn_dims, {}, budget):
                clone = copy.deepcopy(rxn)
                _strip_arrays_from_element(clone, arrays_ns)
                _rename_cloned_element(clone, rxn_coords)
                if rxn.get("compartment") is not None:
                    comp_id, _, _ = _resolve_indexed_attribute(
                        rxn,
                        "compartment",
                        rxn_indices,
                        rxn_env,
                        symbol_shapes,
                        const_scalars,
                        const_arrays,
                        func_defs,
                    )
                    clone.set("compartment", comp_id)

                for ref_list_name in ("listOfReactants", "listOfProducts"):
                    ref_list = _first_core_child(clone, ref_list_name)
                    if ref_list is None:
                        continue
                    if _element_array_children(ref_list, arrays_ns) != (None, None):
                        raise ArraysFlatteningError(
                            f"arrays constructs are not permitted on <{ref_list_name}>."
                        )
                    new_refs: List[ET.Element] = []
                    for sr in list(ref_list):
                        if _local_name(str(sr.tag)) != "speciesReference":
                            new_refs.append(sr)
                            continue
                        sr_dims = _parse_dimensions_raw(sr, arrays_ns, size_values)
                        sr_indices = _parse_indices(sr, arrays_ns)
                        for sr_coords, sr_env in _iter_coords(sr_dims, rxn_env, budget):
                            sr_clone = copy.deepcopy(sr)
                            _strip_arrays_from_element(sr_clone, arrays_ns)
                            _rename_cloned_element(sr_clone, rxn_coords + sr_coords)
                            sp_id, _, _ = _resolve_indexed_attribute(
                                sr,
                                "species",
                                sr_indices,
                                sr_env,
                                symbol_shapes,
                                const_scalars,
                                const_arrays,
                                func_defs,
                            )
                            sr_clone.set("species", sp_id)
                            stoich_math = _first_core_child(
                                sr_clone, "stoichiometryMath"
                            )
                            if stoich_math is not None:
                                _flatten_scalar_math_container(
                                    stoich_math,
                                    sr_env,
                                    arrays_ns,
                                    symbol_shapes,
                                    {},
                                    const_scalars,
                                    const_arrays,
                                    func_defs,
                                )
                            new_refs.append(sr_clone)
                    ref_list[:] = new_refs

                mod_list = _first_core_child(clone, "listOfModifiers")
                if mod_list is not None:
                    if _element_array_children(mod_list, arrays_ns) != (None, None):
                        raise ArraysFlatteningError(
                            "arrays constructs are not permitted on <listOfModifiers>."
                        )
                    new_mods: List[ET.Element] = []
                    for mod in list(mod_list):
                        if _local_name(str(mod.tag)) != "modifierSpeciesReference":
                            new_mods.append(mod)
                            continue
                        mod_dims = _parse_dimensions_raw(mod, arrays_ns, size_values)
                        mod_indices = _parse_indices(mod, arrays_ns)
                        for mod_coords, mod_env in _iter_coords(
                            mod_dims, rxn_env, budget
                        ):
                            mod_clone = copy.deepcopy(mod)
                            _strip_arrays_from_element(mod_clone, arrays_ns)
                            _rename_cloned_element(mod_clone, rxn_coords + mod_coords)
                            sp_id, _, _ = _resolve_indexed_attribute(
                                mod,
                                "species",
                                mod_indices,
                                mod_env,
                                symbol_shapes,
                                const_scalars,
                                const_arrays,
                                func_defs,
                            )
                            mod_clone.set("species", sp_id)
                            new_mods.append(mod_clone)
                    mod_list[:] = new_mods

                kinetic_law = _first_core_child(clone, "kineticLaw")
                if kinetic_law is not None:
                    local_shapes: Dict[str, Tuple[int, ...]] = {}
                    local_seen: Set[str] = set()
                    lp_list = _first_core_child(kinetic_law, "listOfLocalParameters")
                    if lp_list is not None:
                        if _element_array_children(lp_list, arrays_ns) != (None, None):
                            raise ArraysFlatteningError(
                                "arrays constructs are not permitted on "
                                "<listOfLocalParameters>."
                            )
                        new_lps: List[ET.Element] = []
                        for lp in list(lp_list):
                            if _local_name(str(lp.tag)) != "localParameter":
                                new_lps.append(lp)
                                continue
                            lp_dims = _parse_dimensions_raw(lp, arrays_ns, size_values)
                            _parse_indices(lp, arrays_ns)
                            lp_shape = tuple(d.size for d in lp_dims)
                            lp_id = str(lp.get("id", "") or "").strip()
                            if lp_id:
                                local_shapes[lp_id] = lp_shape
                            for lp_coords, _lp_env in _iter_coords(
                                lp_dims, rxn_env, budget
                            ):
                                lp_clone = copy.deepcopy(lp)
                                _strip_arrays_from_element(lp_clone, arrays_ns)
                                _rename_cloned_element(lp_clone, lp_coords)
                                flat_lp_id = str(lp_clone.get("id", "") or "").strip()
                                if flat_lp_id:
                                    if flat_lp_id in local_seen:
                                        raise ArraysFlatteningError(
                                            f"Flattened localParameter ID {flat_lp_id!r} "
                                            "collides within reaction."
                                        )
                                    local_seen.add(flat_lp_id)
                                new_lps.append(lp_clone)
                        lp_list[:] = new_lps

                    _flatten_scalar_math_container(
                        kinetic_law,
                        rxn_env,
                        arrays_ns,
                        symbol_shapes,
                        local_shapes,
                        const_scalars,
                        const_arrays,
                        func_defs,
                    )

                new_reactions.append(clone)
        reactions_container[:] = new_reactions

    # 2g. Events (with trigger, delay, priority, eventAssignments)
    events_list = _first_core_child(model, "listOfEvents")
    if events_list is not None:
        new_events: List[ET.Element] = []
        for event in list(events_list):
            if _local_name(str(event.tag)) != "event":
                new_events.append(event)
                continue
            ev_dims = _parse_dimensions_raw(event, arrays_ns, size_values)
            _parse_indices(event, arrays_ns)
            for ev_coords, ev_env in _iter_coords(ev_dims, {}, budget):
                clone = copy.deepcopy(event)
                _strip_arrays_from_element(clone, arrays_ns)
                _rename_cloned_element(clone, ev_coords)

                for sub_name in ("trigger", "delay", "priority"):
                    sub = _first_core_child(clone, sub_name)
                    if sub is not None:
                        _flatten_scalar_math_container(
                            sub,
                            ev_env,
                            arrays_ns,
                            symbol_shapes,
                            {},
                            const_scalars,
                            const_arrays,
                            func_defs,
                        )

                ea_list = _first_core_child(clone, "listOfEventAssignments")
                if ea_list is not None:
                    if _element_array_children(ea_list, arrays_ns) != (None, None):
                        raise ArraysFlatteningError(
                            "arrays constructs are not permitted on "
                            "<listOfEventAssignments>."
                        )
                    seen_ea_vars: Set[str] = set()
                    new_eas: List[ET.Element] = []
                    for ea in list(ea_list):
                        if _local_name(str(ea.tag)) != "eventAssignment":
                            new_eas.append(ea)
                            continue
                        new_eas.extend(
                            _flatten_assignment_like(
                                ea,
                                "variable",
                                ev_env,
                                arrays_ns,
                                size_values,
                                symbol_shapes,
                                const_scalars,
                                const_arrays,
                                func_defs,
                                seen_ea_vars,
                                budget,
                            )
                        )
                    ea_list[:] = new_eas

                new_events.append(clone)
        events_list[:] = new_events

    # 2h. Constraints
    constraints_list = _first_core_child(model, "listOfConstraints")
    if constraints_list is not None:
        new_constraints: List[ET.Element] = []
        for constraint in list(constraints_list):
            if _local_name(str(constraint.tag)) != "constraint":
                new_constraints.append(constraint)
                continue
            dims = _parse_dimensions_raw(constraint, arrays_ns, size_values)
            _parse_indices(constraint, arrays_ns)
            for coords, dim_env in _iter_coords(dims, {}, budget):
                clone = copy.deepcopy(constraint)
                _strip_arrays_from_element(clone, arrays_ns)
                _rename_cloned_element(clone, coords)
                _flatten_scalar_math_container(
                    clone,
                    dim_env,
                    arrays_ns,
                    symbol_shapes,
                    {},
                    const_scalars,
                    const_arrays,
                    func_defs,
                )
                new_constraints.append(clone)
        constraints_list[:] = new_constraints

    # Strip root arrays:* attributes (such as arrays:required).
    for attr_key in list(root.attrib):
        if _is_arrays_namespace(_namespace(attr_key)):
            del root.attrib[attr_key]

    # Final safety sweep: fail closed if any arrays element/attribute or
    # <vector>/<selector> survived anywhere outside Core <annotation>/<notes>.
    post_parents = _build_parent_map(root)
    for elem in root.iter():
        if _inside_opaque_core_container(elem, post_parents):
            continue
        if _is_arrays_namespace(_namespace(str(elem.tag))):
            raise ArraysFlatteningError(
                f"Unflattened SBML arrays element <{_local_name(str(elem.tag))}> remained."
            )
        for attr_key in elem.attrib:
            if _is_arrays_namespace(_namespace(attr_key)):
                raise ArraysFlatteningError(
                    f"Unflattened SBML arrays attribute {_local_name(attr_key)!r} remained."
                )
        local = _local_name(str(elem.tag)).lower()
        if local == "vector" or _is_selector_operator(elem):
            raise ArraysFlatteningError(
                f"Unflattened MathML <{local}> remained outside supported contexts."
            )

    if core_ns:
        ET.register_namespace("", core_ns)
    return ET.tostring(root, encoding="unicode")


def flatten_arrays_package(sbml_string: str) -> Tuple[str, Optional[str]]:
    """Flatten SBML Level 3 ``arrays`` constructs, returning ``(xml, failure)``.

    Mirrors ``_flatten_comp_package``: returns ``(flattened_xml, None)`` on
    success (or when no active ``arrays`` constructs exist), and
    ``(original_xml, diagnostic_message)`` when flattening fails closed.
    """

    if not has_arrays_constructs(sbml_string):
        return sbml_string, None
    try:
        return flatten_arrays_sbml(sbml_string), None
    except ArraysFlatteningError as exc:
        return sbml_string, f"SBML arrays flattening failed: {exc}"


__all__ = [
    "ARRAYS_NAMESPACE_V1",
    "ArraysFlatteningError",
    "MAX_FLATTENED_ELEMENTS",
    "flatten_arrays_package",
    "flatten_arrays_sbml",
    "has_arrays_constructs",
]
