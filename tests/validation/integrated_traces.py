"""Source-to-compiled rate and unit evidence for generated SBML cases."""

from __future__ import annotations

import math
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def _tag(element):
    return element.tag.rsplit("}", 1)[-1]


def _children(element):
    return list(element)


def _mathml_text(node):
    """Render the small MathML subset used by the generated source models."""
    tag = _tag(node)
    if tag in ("ci", "cn"):
        return (node.text or "").strip()
    if tag == "apply":
        parts = _children(node)
        operator = _tag(parts[0])
        values = [_mathml_text(part) for part in parts[1:]]
        if operator == "times":
            return "(" + " * ".join(values) + ")"
        if operator == "divide" and len(values) == 2:
            return f"({values[0]} / {values[1]})"
        if operator == "plus":
            return "(" + " + ".join(values) + ")"
        if operator == "minus" and len(values) == 1:
            return "(-" + values[0] + ")"
        if operator == "minus" and len(values) == 2:
            return f"({values[0]} - {values[1]})"
        if operator == "ci":
            return f"{(parts[0].text or '').strip()}({', '.join(values)})"
    raise ValueError(f"unsupported generated MathML element: {tag}")


def _evaluate(node, env, functions):
    tag = _tag(node)
    if tag == "cn":
        return float((node.text or "").strip())
    if tag == "ci":
        name = (node.text or "").strip()
        if name not in env:
            raise ValueError(f"source symbol has no observed value: {name}")
        return float(env[name])
    if tag != "apply":
        raise ValueError(f"unsupported generated MathML value: {tag}")
    parts = _children(node)
    op = _tag(parts[0])
    args = parts[1:]
    if op == "ci":
        name = (parts[0].text or "").strip()
        if name not in functions:
            raise ValueError(f"unavailable source function: {name}")
        formals, body = functions[name]
        if len(args) != len(formals):
            raise ValueError(f"source function arity mismatch: {name}")
        local = dict(env)
        local.update(
            {
                formal: _evaluate(arg, env, functions)
                for formal, arg in zip(formals, args)
            }
        )
        return _evaluate(body, local, functions)
    values = [_evaluate(arg, env, functions) for arg in args]
    if op == "times":
        return math.prod(values)
    if op == "divide" and len(values) == 2:
        return values[0] / values[1]
    if op == "plus":
        return sum(values)
    if op == "minus" and len(values) == 1:
        return -values[0]
    if op == "minus" and len(values) == 2:
        return values[0] - values[1]
    raise ValueError(f"unsupported generated MathML operator: {op}")


def source_rate_trace(sbml_text: str) -> dict:
    """Evaluate each SBML kinetic law at unit species-amount state.

    Species symbols follow SBML's amount/concentration convention. This gives
    an independent source-side rate against which BNG3's native compiled
    per-reaction coefficients can be checked.
    """
    root = ET.fromstring(sbml_text)
    model = next((node for node in root.iter() if _tag(node) == "model"), None)
    if model is None:
        raise ValueError("SBML source has no model")
    compartments = {
        node.get("id"): float(node.get("size", "1"))
        for node in model.iter()
        if _tag(node) == "compartment"
    }
    species = {}
    for node in model.iter():
        if _tag(node) != "species":
            continue
        compartment = node.get("compartment")
        volume = compartments.get(compartment)
        if volume is None or not math.isfinite(volume) or volume <= 0:
            raise ValueError(
                f"source species has unavailable compartment volume: {node.get('id')}"
            )
        species[node.get("id")] = dict(
            compartment=compartment,
            amount_at_probe=1.0,
            symbol_at_probe=(
                1.0
                if node.get("hasOnlySubstanceUnits", "false").lower() == "true"
                else 1.0 / volume
            ),
            substance_units=node.get("substanceUnits"),
            has_only_substance_units=node.get("hasOnlySubstanceUnits", "false").lower()
            == "true",
        )
    parameters = {}
    parameter_units = {}
    for node in model.iter():
        if _tag(node) == "parameter":
            parameters[node.get("id")] = float(node.get("value", "0"))
            parameter_units[node.get("id")] = node.get("units")
    units = {}
    for definition in model.iter():
        if _tag(definition) != "unitDefinition":
            continue
        units[definition.get("id")] = [
            dict(
                kind=item.get("kind"),
                exponent=float(item.get("exponent", "1")),
                scale=int(item.get("scale", "0")),
                multiplier=float(item.get("multiplier", "1")),
            )
            for item in definition.iter()
            if _tag(item) == "unit"
        ]
    functions = {}
    for definition in model.iter():
        if _tag(definition) != "functionDefinition":
            continue
        math_node = next((n for n in definition if _tag(n) == "math"), None)
        lam = (
            next((n for n in math_node if _tag(n) == "lambda"), None)
            if math_node is not None
            else None
        )
        if lam is None:
            continue
        formals = [
            (child.text or "").strip()
            for n in lam
            if _tag(n) == "bvar"
            for child in n
            if _tag(child) == "ci"
        ]
        body = next((n for n in lam if _tag(n) != "bvar"), None)
        if body is not None:
            functions[definition.get("id")] = (formals, body)
    env = dict(
        parameters,
        **{key: value["symbol_at_probe"] for key, value in species.items()},
        **compartments,
    )
    reactions = []
    for reaction in (node for node in model.iter() if _tag(node) == "reaction"):
        law = next((node for node in reaction if _tag(node) == "kineticLaw"), None)
        math_node = (
            next((node for node in law if _tag(node) == "math"), None)
            if law is not None
            else None
        )
        if math_node is None or not list(math_node):
            continue
        expression = list(math_node)[0]
        value = _evaluate(expression, env, functions)
        participants = {}
        for parent in reaction:
            role = _tag(parent)
            if role not in ("listOfReactants", "listOfProducts"):
                continue
            participants["reactants" if role == "listOfReactants" else "products"] = [
                dict(
                    species=n.get("species"),
                    stoichiometry=float(n.get("stoichiometry", "1")),
                )
                for n in parent
                if _tag(n) == "speciesReference"
            ]
        reactions.append(
            dict(
                id=reaction.get("id"),
                source_expression=_mathml_text(expression),
                unit_state_rate=value,
                parameter_units={
                    key: parameter_units[key]
                    for key in _symbol_names(expression)
                    if key in parameter_units
                },
                **participants,
            )
        )
    return dict(
        source="SBML kineticLaw MathML",
        probe=dict(
            species_amounts={key: 1.0 for key in species},
            species_symbol_values={
                key: value["symbol_at_probe"] for key, value in species.items()
            },
        ),
        species=species,
        compartments=compartments,
        parameters=parameters,
        unit_definitions=units,
        reactions=reactions,
    )


def _symbol_names(node):
    return {(n.text or "").strip() for n in node.iter() if _tag(n) == "ci"}


def trace_identity(case_id: str, source: dict) -> str:
    payload = json.dumps(source, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"{case_id}:rate-units:{digest}"


def first_differing_boundary(boundaries: list[dict]) -> dict:
    """Locate the first observed mismatch without skipping missing links."""
    failures = [
        row["name"]
        for row in boundaries
        if row["status"] in {"FAIL", "TIMEOUT", "HARNESS_ERROR"}
    ]
    missing = next(
        (
            index
            for index, row in enumerate(boundaries)
            if row["status"] in {"NOT_TESTED", "UNSUPPORTED", "INVALID_INPUT"}
        ),
        None,
    )
    first = None
    for index, row in enumerate(boundaries):
        if row["status"] in {"FAIL", "TIMEOUT", "HARNESS_ERROR"}:
            if all(previous["status"] == "PASS" for previous in boundaries[:index]):
                first = dict(
                    name=row["name"], first_difference=row.get("first_difference")
                )
            break
        if row["status"] != "PASS":
            break
    return dict(
        first_divergence=first,
        blocked_at=boundaries[missing]["name"] if missing is not None else None,
        observed_failures=failures,
        boundary_statuses=[
            dict(name=row["name"], status=row["status"]) for row in boundaries
        ],
    )


def compare_rate_trace(source: dict, observation: dict | None) -> dict:
    """Compare source kinetic-law values with observed compiled coefficients."""
    if not isinstance(observation, dict):
        return dict(
            status="NOT_TESTED",
            detail="compiled rate/RHS observation is missing",
            first_difference=None,
        )
    observed = observation.get("reaction_rate_coefficients")
    expected = [row["unit_state_rate"] for row in source.get("reactions", [])]
    if not isinstance(observed, list) or len(observed) != len(expected) or not expected:
        return dict(
            status="NOT_TESTED",
            detail="coverage missing: compiled rate vector does not cover source reactions",
            first_difference=None,
            source_reaction_count=len(expected),
            observed_rate_count=len(observed) if isinstance(observed, list) else None,
            observed_rhs=observation.get("ode_rhs"),
        )
    # Reaction order can change during translation; compare the evaluated rate
    # multiset while retaining both original ordered observations in the receipt.
    left = sorted((float(value), index) for index, value in enumerate(expected))
    right = sorted((float(value), index) for index, value in enumerate(observed))
    for sorted_index, (
        (source_value, source_index),
        (observed_value, observed_index),
    ) in enumerate(zip(left, right)):
        if (
            not math.isfinite(source_value)
            or not math.isfinite(observed_value)
            or not math.isclose(
                source_value, observed_value, rel_tol=1e-12, abs_tol=1e-14
            )
        ):
            return dict(
                status="FAIL",
                detail="source kinetic-law rate differs from compiled BNG3 coefficient multiset at unit amount state",
                first_difference=dict(
                    field="reaction_rate_coefficients",
                    sorted_index=sorted_index,
                    source=source_value,
                    observed=observed_value,
                    observed_reaction_index=observed_index,
                ),
                observed_rhs=observation.get("ode_rhs"),
            )
    return dict(
        status="PASS",
        detail="source kinetic-law values match compiled BNG3 coefficient multiset at unit amount state",
        first_difference=None,
        observed_rhs=observation.get("ode_rhs"),
        comparison_kind="unmapped-reaction-rate-multiset",
    )


def compare_rate_values(
    source: dict | list[float] | None,
    observed: list[float] | None,
    label: str,
    *,
    rtol: float = 1e-12,
) -> dict:
    """Compare a serialization's parsed effective rates when it exposes them."""
    expected = (
        [row["unit_state_rate"] for row in source.get("reactions", [])]
        if isinstance(source, dict)
        else source
    )
    expected = expected if isinstance(expected, list) else []
    if not isinstance(observed, list) or len(observed) != len(expected) or not expected:
        return dict(
            status="NOT_TESTED",
            detail=f"coverage missing: {label} rate vector is unavailable or incomplete",
            first_difference=None,
            source_rate_count=len(expected),
            observed_rate_count=len(observed) if isinstance(observed, list) else None,
        )
    left, right = sorted(expected), sorted(float(value) for value in observed)
    for index, (source_value, observed_value) in enumerate(zip(left, right)):
        if not math.isfinite(observed_value) or not math.isclose(
            source_value, observed_value, rel_tol=rtol, abs_tol=1e-14
        ):
            return dict(
                status="FAIL",
                detail=f"rate values differ from {label} rate multiset",
                first_difference=dict(
                    field="effective_rate_multiset",
                    sorted_index=index,
                    source=source_value,
                    observed=observed_value,
                ),
                comparison_kind="unmapped-reaction-rate-multiset",
            )
    return dict(
        status="PASS",
        detail=f"rate values match {label} rate multiset",
        first_difference=None,
        comparison_kind="unmapped-reaction-rate-multiset",
    )


def exported_net_rates(path) -> dict:
    """Read NET reactions through the campaign parser and resolve their rates."""
    from . import compare

    network = compare.parse_net(path)
    if network is None:
        return dict(
            status="NOT_TESTED",
            detail="exported NET is absent or unparsable",
            effective_rates=None,
        )
    rates = []
    for _reactants, _products, token in network._raw:
        value = compare._resolve_rate(
            token,
            network.rate_defs,
            "value",
            network.rate_functions,
            network.rate_observables,
        )
        try:
            rates.append(float(value))
        except (TypeError, ValueError):
            return dict(
                status="NOT_TESTED",
                detail="NET rate remains state-dependent after existing rate resolution",
                effective_rates=None,
                resolved_rates=[*rates, value],
            )
    return dict(
        status="OBSERVED",
        detail="parsed with tests.validation.compare.parse_net and _resolve_rate",
        effective_rates=rates,
        rate_tokens=[row[2] for row in network._raw],
    )


def _compartment_geometry(root):
    """Map each XML compartment to its dimension and statically known size.

    A compartment whose size is a parameter or expression is reported with a
    ``None`` size: the count-rate conversion then cannot be evaluated here.
    """
    geometry = {}
    for node in root.iter():
        if _tag(node) != "Compartment":
            continue
        dimension = node.get("spatialDimensions") or node.get("dimension") or "3"
        size = node.get("size")
        try:
            size = float(size) if size is not None else None
        except ValueError:
            size = None
        geometry[node.get("id")] = (dimension, size)
    return geometry


def _compartment_unit_conversion(reactant_compartments, product_compartments, geometry):
    """BNG2's intensive-to-extensive count-rate conversion for one rule.

    ``bng2/Perl2/Rxn.pm`` (get_intensive_to_extensive_units_conversion) anchors
    the first surface reactant, else the first volume reactant, and divides by
    the sizes of the remaining reactant compartments.  Zero-order synthesis
    multiplies by the product compartment size instead.  ``None`` means the
    conversion is not statically determinable, so the two serializations
    cannot be compared in one convention.
    """
    reactants = [c for c in reactant_compartments if c]
    if reactants:
        sizes = []
        for name in reactants:
            entry = geometry.get(name)
            if entry is None or entry[1] is None:
                return None
            sizes.append(entry)
        surfaces = [item for item in sizes if item[0] == "2"]
        volumes = [item for item in sizes if item[0] == "3"]
        if len(surfaces) + len(volumes) != len(sizes):
            # BNG2 rejects 1-D/0-D reactant compartments at parse time.
            return None
        anchored = surfaces or volumes
        remaining = anchored[1:] if anchored else []
        remaining += [item for item in sizes if item not in anchored]
        if not remaining:
            return 1.0
        denominator = 1.0
        for _dimension, size in remaining:
            denominator *= size
        if denominator == 0.0:
            return None
        return 1.0 / denominator
    products = [c for c in product_compartments if c]
    if products:
        sizes = set()
        for name in products:
            entry = geometry.get(name)
            if entry is None or entry[1] is None:
                return None
            sizes.add(entry[1])
        if len(sizes) != 1:
            # BNG2 cannot scale synthesis products spread over compartments.
            return None
        return float(next(iter(sizes)))
    return 1.0


def _parameter_values(root):
    """Map each exported parameter id to the constant value it states.

    A parameter whose value is not a plain number is reported as ``None``:
    the count-rate coefficient of a rule that depends on it cannot be
    determined here.
    """
    values = {}
    for node in root.iter():
        if _tag(node) != "Parameter":
            continue
        try:
            values[node.get("id")] = float(node.get("value"))
        except (TypeError, ValueError):
            values[node.get("id")] = None
    return values


def exported_bng_xml(path, source: dict | None = None) -> dict:
    """Capture and evaluate elementary constant BNG-XML coefficients only.

    The coefficient is reported in the same count-rate convention the NET
    export uses, so the two serializations can be compared: the raw rule rate
    constant is combined with the rule's symmetry factor and with BNG2's
    compartment unit conversion.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        return dict(
            status="NOT_TESTED",
            detail=f"BNG-XML export unavailable: {type(exc).__name__}: {exc}",
            rules=[],
        )
    geometry = _compartment_geometry(root)
    parameters = _parameter_values(root)
    rules = []
    effective_rates = []
    complete = True
    for node in root.iter():
        if _tag(node) != "ReactionRule":
            continue
        rates = [
            item.get("value") for item in node.iter() if _tag(item) == "RateConstant"
        ]
        law = next((item for item in node if _tag(item) == "RateLaw"), None)
        law_type = law.get("type") if law is not None else None
        reactant_patterns = [
            item for item in node.iter() if _tag(item) == "ReactantPattern"
        ]
        product_patterns = [
            item for item in node.iter() if _tag(item) == "ProductPattern"
        ]
        conversion = _compartment_unit_conversion(
            [item.get("compartment") for item in reactant_patterns],
            [item.get("compartment") for item in product_patterns],
            geometry,
        )
        value = None
        if rates and rates[0]:
            try:
                value = float(rates[0])
            except ValueError:
                # A parameter-backed constant rate law; the exported
                # parameter list states the value it was given.
                value = parameters.get(rates[0])
        try:
            symmetry = float(node.get("symmetry_factor", "1"))
            if (
                law_type != "Ele"
                or len(rates) != 1
                or value is None
                or not math.isfinite(value)
                or not math.isfinite(symmetry)
                or symmetry <= 0
                or conversion is None
            ):
                raise ValueError("rate law is not one constant elementary coefficient")
            coefficient = value * symmetry * conversion
            effective_rates.append(coefficient)
        except (TypeError, ValueError):
            complete = False
            coefficient = None
        rules.append(
            dict(
                id=node.get("id"),
                name=node.get("name"),
                symmetry_factor=node.get("symmetry_factor"),
                rate_constants=rates,
                rate_constant_value=value,
                rate_law_type=law_type,
                reactant_pattern_count=len(reactant_patterns),
                reactant_compartments=[
                    item.get("compartment") for item in reactant_patterns
                ],
                product_compartments=[
                    item.get("compartment") for item in product_patterns
                ],
                compartment_unit_conversion=conversion,
                observed_elementary_coefficient=coefficient,
            )
        )
    source_molecularities = (
        sorted(
            sum(float(item["stoichiometry"]) for item in reaction.get("reactants", []))
            for reaction in source.get("reactions", [])
        )
        if isinstance(source, dict)
        else None
    )
    xml_molecularities = sorted(rule["reactant_pattern_count"] for rule in rules)
    qualified = (
        source_molecularities is not None
        and source_molecularities == xml_molecularities
    )
    return dict(
        status="OBSERVED" if rules else "NOT_TESTED",
        detail=(
            "elementary constants times explicit symmetry_factor (default 1), with generated reactant molecularity matched"
            if complete and rules and qualified
            else "effective coefficient unsupported: requires matching generated molecularity and scalar elementary laws"
        ),
        rules=rules,
        effective_rates=effective_rates if complete and rules and qualified else None,
        parameters=parameters,
        source_molecularities=source_molecularities,
        xml_molecularities=xml_molecularities,
        compartment_sizes=[
            dict(id=node.get("id"), size=node.get("size"))
            for node in root.iter()
            if _tag(node) == "Compartment"
        ],
    )


def native_count_rate_xml(source_xml, target_xml) -> dict:
    """Rewrite a BNG-XML export into BNG2's count-rate convention.

    BNG2's count-rate convention divides a reactant-bearing rate constant by
    the reaction compartment's size (``bng2/Perl2/Rxn.pm:100-197``).  The
    pinned native NFsim applies a compartment size only to zero-order
    synthesis (``src/NFinput/NFinput.cpp`` sets ``volumeConversion`` for
    ``ts->getNreactants() == 0``), and only when the model states the
    compartment on the molecule.  This export states it on the pattern, so
    the oracle samples every rule at ``rate constant x symmetry factor``
    rather than at the count-rate coefficient the .net export and the
    embedded engine use.

    The rewrite hands the oracle the model the embedded engine executes: the
    compartment unit conversion is folded into the rule's rate constant and
    the now-redundant symmetry factor is dropped.  The conversion is the one
    ``exported_bng_xml`` already computes for this export, so the oracle and
    the embedded engine are stated in the same convention rather than in two
    divergent ones.  An export that does state a molecule compartment is
    refused rather than counted twice.

    The result is ``status`` "NORMALISED" with the written path and the
    per-rule coefficients, "UNSUPPORTED" with the reason the count-rate
    convention cannot be stated for this export, or "UNAVAILABLE" when the
    exported model itself cannot be read.
    """
    target = Path(target_xml)
    try:
        tree = ET.parse(source_xml)
    except (OSError, ET.ParseError) as exc:
        return dict(
            status="UNAVAILABLE",
            detail=(
                "the exported model is unavailable: " f"{type(exc).__name__}: {exc}"
            ),
        )
    root = tree.getroot()
    namespace = root.tag[1:].split("}")[0] if root.tag.startswith("{") else ""
    if namespace:
        # Keep the document's own default namespace.  The pinned oracle reads
        # namespace-insensitive XML, but a prefixed rewrite would still change
        # the artefact it is handed.
        ET.register_namespace("", namespace)
    exported = exported_bng_xml(source_xml)
    rules = exported.get("rules") or []
    if not rules:
        return dict(
            status="UNSUPPORTED",
            detail="the exported model declares no reaction rule to normalise",
        )
    compartments = {
        node.get("id") for node in root.iter() if _tag(node) == "Compartment"
    }
    if len(compartments) > 1:
        return dict(
            status="UNSUPPORTED",
            detail=(
                "the exported model states more than one compartment, which the "
                "pinned oracle does not read from this export, so it would match "
                "reactants across compartments"
            ),
        )
    if any(node.get("compartment") for node in root.iter() if _tag(node) == "Molecule"):
        return dict(
            status="UNSUPPORTED",
            detail=(
                "the exported model states a molecule compartment, which makes "
                "the pinned oracle apply the product compartment's size to a "
                "zero-order rule itself"
            ),
        )
    elements = [node for node in root.iter() if _tag(node) == "ReactionRule"]
    if len(elements) != len(rules):
        return dict(
            status="UNSUPPORTED",
            detail="the exported model's reaction rules could not be matched to their parsed evidence",
        )
    normalised = []
    for element, rule in zip(elements, rules):
        if element.get("id") != rule["id"]:
            return dict(
                status="UNSUPPORTED",
                detail="the exported model's reaction rule identity changed while it was parsed",
            )
        if rule["rate_law_type"] != "Ele" or len(rule["rate_constants"]) != 1:
            return dict(
                status="UNSUPPORTED",
                detail=(
                    f"reaction rule {rule['id']} does not declare one elementary "
                    "constant rate"
                ),
            )
        value = rule.get("rate_constant_value")
        if value is None or not math.isfinite(value):
            return dict(
                status="UNSUPPORTED",
                detail=(
                    f"reaction rule {rule['id']} has no statically determinable "
                    "rate constant"
                ),
            )
        conversion = rule["compartment_unit_conversion"]
        if conversion is None:
            return dict(
                status="UNSUPPORTED",
                detail=(
                    f"reaction rule {rule['id']} has no statically determinable "
                    "compartment unit conversion"
                ),
            )
        symmetry = float(rule["symmetry_factor"] or 1.0)
        coefficient = value * symmetry * conversion
        # The count-rate coefficient goes into the rate constant, and the
        # symmetry factor it already carries becomes redundant.
        rate_constant = next(
            item for item in element.iter() if _tag(item) == "RateConstant"
        )
        rate_constant.set("value", repr(coefficient))
        element.attrib.pop("symmetry_factor", None)
        normalised.append(
            dict(
                id=rule["id"],
                rate_constant=value,
                symmetry_factor=symmetry,
                compartment_unit_conversion=conversion,
                count_rate_coefficient=coefficient,
                reactant_pattern_count=rule["reactant_pattern_count"],
            )
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return dict(status="NORMALISED", path=str(target), rules=normalised)


def boundary_metadata(name: str) -> dict:
    """Keep XML coefficient evidence diagnostic-only in support rollups."""
    if name == "net-bngxml-rate-coefficient":
        return dict(diagnostic_only=True, supported_execution=False)
    return {}
