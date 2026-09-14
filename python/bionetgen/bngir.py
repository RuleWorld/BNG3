"""Versioned, source-free BNGIR serialization.

The wire object contains semantic model entities and a separate protocol. It
does not contain generated networks, solver state, caches, or source text.
Deserializer support is intentionally strict: unknown required features and
unsupported population-map reconstruction fail closed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

FORMAT = "BNGIR"
VERSION = "0.1"
STRUCTURAL_VERSION = "0.2"
SUPPORTED_VERSIONS = frozenset({VERSION, STRUCTURAL_VERSION})

_FEATURES = frozenset(
    {
        "compartments",
        "energy_patterns",
        "functions",
        "observables",
        "population_maps",
        "protocol",
        "rules",
        "seeds",
    }
)


def _expression(value: Any) -> str:
    if hasattr(value, "to_string"):
        return value.to_string()
    return str(value)


def _action(action: Any, scope: str) -> dict[str, Any]:
    return {"scope": scope, "name": action.name, "arguments": dict(action.arguments)}


def _model_of(model: Any) -> Any:
    native = getattr(model, "_model", None)
    if native is None:
        raise TypeError("BNGIR requires a modern BioNetGenModel")
    return native


def _payload_v01(model: Any, provenance: Mapping[str, Any] | None) -> dict[str, Any]:
    native = _model_of(model)

    parameters = [
        {"name": p.name, "expression": _expression(p.expression)}
        for p in native.parameters
    ]
    molecule_types = []
    for molecule_type in native.molecule_types:
        molecule_types.append(
            {
                "name": molecule_type.name,
                "population": bool(molecule_type.is_population),
                "components": [
                    {"name": c.name, "allowed_states": list(c.allowed_states)}
                    for c in molecule_type.components
                ],
            }
        )
    seeds = [
        {
            "pattern": seed.pattern,
            "amount": _expression(seed.amount),
            "constant": bool(seed.is_constant),
            "compartment": seed.compartment,
        }
        for seed in native.seed_species
    ]
    observables = [
        {
            "name": observable.name,
            "type": observable.type,
            "patterns": list(observable.patterns),
        }
        for observable in native.observables
    ]
    functions = [
        {
            "name": function.name,
            "args": list(function.args),
            "expression": _expression(function.expression),
        }
        for function in native.functions
    ]
    rules = [
        {
            "name": rule.rule_name,
            "label": rule.label,
            "reactants": list(rule.reactant_patterns),
            "products": list(rule.product_patterns),
            "rates": list(rule.rates),
            "modifiers": list(rule.modifiers),
            "bidirectional": bool(rule.is_bidirectional),
        }
        for rule in native.reaction_rules
    ]
    compartments = [
        {
            "name": compartment.name,
            "volume": float(compartment.volume),
            "dimension": int(compartment.dimension),
            "parent": compartment.parent,
        }
        for compartment in native.compartments
    ]
    energy_patterns = [
        {
            "label": pattern.label,
            "pattern": pattern.pattern,
            "expression": _expression(pattern.expression),
        }
        for pattern in native.energy_patterns
    ]
    population_maps = [
        {
            "label": mapping.label,
            "pattern": mapping.pattern,
            "function": mapping.function,
            "args": list(mapping.args),
        }
        for mapping in native.population_maps
    ]

    features = {"required": [], "used": []}
    if compartments:
        features["used"].append("compartments")
    if energy_patterns:
        features["used"].append("energy_patterns")
    if functions:
        features["used"].append("functions")
    if observables:
        features["used"].append("observables")
    if population_maps:
        features["used"].append("population_maps")
    if native.actions or native.protocol_actions:
        features["used"].append("protocol")
    if rules:
        features["used"].append("rules")
    if seeds:
        features["used"].append("seeds")
    features["used"].sort()

    result = {
        "format": FORMAT,
        "version": VERSION,
        "features": features,
        "model": {
            "name": native.model_name,
            "version": native.version,
            "substance_units": native.substance_units,
            "options": dict(native.options),
            "parameters": parameters,
            "molecule_types": molecule_types,
            "compartments": compartments,
            "seeds": seeds,
            "observables": observables,
            "functions": functions,
            "energy_patterns": energy_patterns,
            "population_maps": population_maps,
            "rules": rules,
        },
        "protocol": {
            "actions": [
                *[_action(action, "model") for action in native.actions],
                *[
                    _action(action, "simulation_protocol")
                    for action in native.protocol_actions
                ],
            ],
        },
    }
    if provenance is not None:
        result["provenance"] = dict(provenance)
    return result


def _features_v02(snapshot: Mapping[str, Any]) -> dict[str, list[str]]:
    used: list[str] = []
    for key, feature in (
        ("compartments", "compartments"),
        ("energy_patterns", "energy_patterns"),
        ("functions", "functions"),
        ("observables", "observables"),
        ("population_maps", "population_maps"),
        ("rules", "rules"),
        ("seeds", "seeds"),
    ):
        if snapshot.get(key):
            used.append(feature)
    if snapshot.get("actions"):
        used.append("protocol")
    return {
        "required": ["structured_patterns", "structured_expressions"],
        "used": sorted(used + ["structured_patterns", "structured_expressions"]),
    }


def _payload_v02(model: Any, provenance: Mapping[str, Any] | None) -> dict[str, Any]:
    native = _model_of(model)
    try:
        from .model import _cpp

        snapshot = _cpp._compiled_snapshot(native)
    except (AttributeError, ImportError) as exc:
        raise RuntimeError(
            "BNGIR v0.2 requires the structural compile snapshot support in this BNG3 build"
        ) from exc
    snapshot = dict(snapshot)
    actions = list(snapshot.pop("actions", []))
    metadata = dict(snapshot.pop("metadata", {}))
    result = {
        "format": FORMAT,
        "version": STRUCTURAL_VERSION,
        "features": _features_v02({**snapshot, "actions": actions}),
        "model": {"metadata": metadata, **snapshot},
        "protocol": {"actions": actions},
    }
    if provenance is not None:
        result["provenance"] = dict(provenance)
    return result


def to_bngir(
    model: Any, *, provenance: Mapping[str, Any] | None = None, version: str = VERSION
) -> str:
    """Return deterministic BNGIR JSON.

    ``version="0.1"`` retains the original string-oriented interchange format.
    ``version="0.2"`` serializes the resolved compile model with structural
    patterns, expression trees, rule mappings, and transformation programs.
    """

    if version == VERSION:
        payload = _payload_v01(model, provenance)
    elif version == STRUCTURAL_VERSION:
        payload = _payload_v02(model, provenance)
    else:
        raise ValueError(f"unsupported BNGIR version: {version}")
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"BNGIR {where} must be an object")
    return value


def _load_document_v01(document: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(document, str):
        try:
            value = json.loads(document)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid BNGIR JSON: {exc}") from exc
    else:
        value = document
    root = _require_mapping(value, "document")
    if root.get("format") != FORMAT or root.get("version") != VERSION:
        raise ValueError("unsupported BNGIR format or version")
    features = _require_mapping(root.get("features"), "features")
    for feature_kind in ("required", "used"):
        values = features.get(feature_kind, [])
        if not isinstance(values, list) or not all(
            isinstance(item, str) for item in values
        ):
            raise ValueError(f"BNGIR features.{feature_kind} must be a string array")
        unknown = sorted(set(values) - _FEATURES)
        if unknown:
            raise ValueError(
                f"unsupported required BNGIR features: {', '.join(unknown)}"
            )
    _require_mapping(root.get("model"), "model")
    protocol = _require_mapping(root.get("protocol", {}), "protocol")
    actions = protocol.get("actions", [])
    if not isinstance(actions, list):
        raise ValueError("BNGIR protocol.actions must be an array")
    for index, action in enumerate(actions):
        action = _require_mapping(action, f"protocol.actions[{index}]")
        scope = action.get("scope")
        if scope not in {"model", "simulation_protocol"}:
            raise ValueError(f"unsupported BNGIR action scope: {scope!r}")
        if not isinstance(action.get("name"), str):
            raise ValueError(f"BNGIR protocol.actions[{index}].name must be a string")
        arguments = action.get("arguments", {})
        if not isinstance(arguments, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in arguments.items()
        ):
            raise ValueError(
                f"BNGIR protocol.actions[{index}].arguments must map strings to strings"
            )
    return root


def _quote_action_value(value: Any) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _action_value(value: Any) -> str:
    raw = str(value)
    if (len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"') or re.fullmatch(
        r"[A-Za-z0-9_+./:-]+", raw
    ):
        return raw
    return _quote_action_value(raw)


def _quote_string(value: Any) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _action_lines(action: Mapping[str, Any]) -> str:
    arguments = action.get("arguments", {})
    if not arguments:
        return f"  {action['name']}()"
    pairs = ", ".join(
        f"{key}=>{_action_value(value)}" for key, value in arguments.items()
    )
    return f"  {action['name']}({{{pairs}}})"


def _as_bngl_v01(root: Mapping[str, Any]) -> str:
    model = _require_mapping(root["model"], "model")
    if model.get("population_maps"):
        raise ValueError("BNGIR population_maps deserialization is not yet supported")

    lines: list[str] = []
    if model.get("version"):
        lines.append(f"version({_quote_string(model['version'])})")
    if model.get("substance_units"):
        lines.append(f"substanceUnits({_quote_string(model['substance_units'])})")
    if model.get("name"):
        lines.append(f"setModelName({_quote_string(model['name'])})")
    for key, value in model.get("options", {}).items():
        lines.append(f"setOption({_quote_string(key)}, {_quote_action_value(value)})")
    lines.append("begin model")
    parameters = model.get("parameters", [])
    if parameters:
        lines += ["begin parameters"]
        lines += [f"  {item['name']} {item['expression']}" for item in parameters]
        lines += ["end parameters"]
    compartments = model.get("compartments", [])
    if compartments:
        lines += ["begin compartments"]
        for item in compartments:
            suffix = f" {item.get('parent', '')}" if item.get("parent") else ""
            lines.append(
                f"  {item['name']} {int(item['dimension'])} {item['volume']}{suffix}"
            )
        lines += ["end compartments"]
    molecule_types = model.get("molecule_types", [])
    if molecule_types:
        lines += ["begin molecule types"]
        for item in molecule_types:
            components = []
            for component in item.get("components", []):
                states = "".join(
                    f"~{state}" for state in component.get("allowed_states", [])
                )
                components.append(f"{component['name']}{states}")
            suffix = f"({','.join(components)})" if components else "()"
            population = " population" if item.get("population") else ""
            lines.append(f"  {item['name']}{suffix}{population}")
        lines += ["end molecule types"]
    seeds = model.get("seeds", [])
    if seeds:
        lines += ["begin seed species"]
        for item in seeds:
            pattern = item["pattern"]
            compartment = item.get("compartment", "")
            if compartment and "@" not in pattern:
                pattern = f"@{compartment}:{pattern}"
            if item.get("constant") and not pattern.startswith("$"):
                pattern = "$" + pattern
            lines.append(f"  {pattern} {item['amount']}")
        lines += ["end seed species"]
    observables = model.get("observables", [])
    if observables:
        lines += ["begin observables"]
        for item in observables:
            lines.append(
                f"  {item['type']} {item['name']} {','.join(item['patterns'])}"
            )
        lines += ["end observables"]
    functions = model.get("functions", [])
    if functions:
        lines += ["begin functions"]
        for item in functions:
            args = ",".join(item.get("args", []))
            lines.append(f"  {item['name']}({args}) = {item['expression']}")
        lines += ["end functions"]
    energy_patterns = model.get("energy_patterns", [])
    if energy_patterns:
        lines += ["begin energy patterns"]
        for item in energy_patterns:
            label = f"{item['label']}: " if item.get("label") else ""
            lines.append(f"  {label}{item['pattern']} {item['expression']}")
        lines += ["end energy patterns"]
    rules = model.get("rules", [])
    if rules:
        lines += ["begin reaction rules"]
        for item in rules:
            source_label = str(item.get("label", "")).rstrip(":")
            name = f"{source_label}: " if source_label else ""
            arrow = "<->" if item.get("bidirectional") else "->"
            rate = ", ".join(item.get("rates", []))
            reactants = " + ".join(item["reactants"]) or "0"
            products = " + ".join(item["products"]) or "0"
            line = f"  {name}{reactants} {arrow} {products}"
            if rate:
                line += f" {rate}"
            if item.get("modifiers"):
                line += " " + " ".join(item["modifiers"])
            lines.append(line)
        lines += ["end reaction rules"]
    actions = list(
        _require_mapping(root.get("protocol", {}), "protocol").get("actions", [])
    )
    model_actions = [
        action for action in actions if action.get("scope", "model") == "model"
    ]
    protocol_actions = [
        action for action in actions if action.get("scope") == "simulation_protocol"
    ]
    if protocol_actions:
        lines += ["begin protocol"]
        lines += [_action_lines(action) for action in protocol_actions]
        lines += ["end protocol"]
    lines += ["end model"]
    if model_actions:
        lines += ["begin actions"]
        lines += [_action_lines(action) for action in model_actions]
        lines += ["end actions"]
    return "\n".join(lines) + "\n"


def _parse_document(document: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(document, str):
        try:
            value = json.loads(document)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid BNGIR JSON: {exc}") from exc
    else:
        value = document
    root = _require_mapping(value, "document")
    if root.get("format") != FORMAT or root.get("version") not in SUPPORTED_VERSIONS:
        raise ValueError("unsupported BNGIR format or version")
    return root


def _validate_actions(root: Mapping[str, Any]) -> None:
    protocol = _require_mapping(root.get("protocol", {}), "protocol")
    actions = protocol.get("actions", [])
    if not isinstance(actions, list):
        raise ValueError("BNGIR protocol.actions must be an array")
    for index, raw in enumerate(actions):
        action = _require_mapping(raw, f"protocol.actions[{index}]")
        if action.get("scope") not in {"model", "simulation_protocol"}:
            raise ValueError(f"unsupported BNGIR action scope: {action.get('scope')!r}")
        if not isinstance(action.get("name"), str):
            raise ValueError(f"BNGIR protocol.actions[{index}].name must be a string")
        arguments = action.get("arguments", {})
        if not isinstance(arguments, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in arguments.items()
        ):
            raise ValueError(
                f"BNGIR protocol.actions[{index}].arguments must map strings to strings"
            )


def _validate_expression_v02(
    expression: Mapping[str, Any],
    model: Mapping[str, Any],
    *,
    local_names: set[str] | None = None,
    reactant_count: int | None = None,
    where: str = "expression",
) -> None:
    expression = _require_mapping(expression, where)
    kind = expression.get("kind")
    args = expression.get("arguments", [])
    if not isinstance(args, list):
        raise ValueError(f"BNGIR {where}.arguments must be an array")
    if kind in {"parameter_ref", "observable_ref", "function_ref"}:
        symbol = _require_mapping(expression.get("symbol"), f"{where}.symbol")
        symbol_kind = symbol.get("kind")
        symbol_id = symbol.get("index")
        if not isinstance(symbol_kind, str) or not isinstance(symbol_id, int):
            raise ValueError(f"BNGIR {where}.symbol is malformed")
        _name_for_symbol(model, symbol_kind, symbol_id)
    elif kind == "local_ref":
        name = expression.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"BNGIR {where} local_ref is missing a name")
        if local_names is not None and name not in local_names:
            raise ValueError(f"BNGIR {where} references unknown local scope {name!r}")
    elif kind == "reactant_count_ref":
        value = expression.get("reactant_index")
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"BNGIR {where} has invalid reactant_index")
        if reactant_count is not None and value >= reactant_count:
            raise ValueError(f"BNGIR {where} reactant_index is out of range: {value}")
    elif kind in {
        "number",
        "time_ref",
        "unary",
        "binary",
        "builtin_call",
        "table_function",
    }:
        pass
    elif kind == "unresolved":
        raise ValueError(f"BNGIR {where} is unresolved")
    else:
        raise ValueError(f"unsupported BNGIR {where} kind: {kind!r}")
    for i, arg in enumerate(args):
        _validate_expression_v02(
            _require_mapping(arg, f"{where}.arguments[{i}]"),
            model,
            local_names=local_names,
            reactant_count=reactant_count,
            where=f"{where}.arguments[{i}]",
        )


def _validate_pattern_v02(
    pattern: Mapping[str, Any], model: Mapping[str, Any], where: str
) -> None:
    pattern = _require_mapping(pattern, where)
    molecule_types = _section_id_map(model, "molecule_types")
    compartments = _section_id_map(model, "compartments")
    molecules = pattern.get("molecules", [])
    if not isinstance(molecules, list):
        raise ValueError(f"BNGIR {where}.molecules must be an array")
    seen_occurrences: set[int] = set()
    for mi, raw_molecule in enumerate(molecules):
        molecule = _require_mapping(raw_molecule, f"{where}.molecules[{mi}]")
        occurrence = molecule.get("occurrence", mi)
        if (
            not isinstance(occurrence, int)
            or occurrence < 0
            or occurrence in seen_occurrences
        ):
            raise ValueError(f"BNGIR {where} has invalid/duplicate molecule occurrence")
        seen_occurrences.add(occurrence)
        type_id = molecule.get("type_id")
        declaration = None
        if type_id is not None:
            if not isinstance(type_id, int) or type_id not in molecule_types:
                raise ValueError(
                    f"BNGIR {where} references unknown molecule type id: {type_id}"
                )
            declaration = molecule_types[type_id]
            if molecule.get("type") != declaration.get("name"):
                raise ValueError(f"BNGIR {where} molecule type name/id disagree")
        compartment_id = molecule.get("compartment_id")
        if compartment_id is not None and (
            not isinstance(compartment_id, int) or compartment_id not in compartments
        ):
            raise ValueError(
                f"BNGIR {where} references unknown compartment id: {compartment_id}"
            )
        components = declaration.get("components", []) if declaration else []
        for si, raw_site in enumerate(molecule.get("sites", [])):
            site = _require_mapping(raw_site, f"{where}.molecules[{mi}].sites[{si}]")
            component_index = site.get("component_index")
            component_decl = None
            if component_index is not None and declaration is not None:
                if not isinstance(component_index, int) or component_index < 0:
                    raise ValueError(f"BNGIR {where} has invalid component index")
                component_decl = next(
                    (
                        c
                        for c in components
                        if int(c.get("index", -1)) == component_index
                    ),
                    None,
                )
                if component_decl is None:
                    raise ValueError(
                        f"BNGIR {where} references unknown component index"
                    )
                if site.get("component") != component_decl.get("name"):
                    raise ValueError(f"BNGIR {where} component name/index disagree")
            state = _require_mapping(site.get("state", {}), f"{where}.state")
            state_kind = state.get("kind", "any")
            if (
                state_kind == "exact"
                and component_decl is not None
                and "index" in state
            ):
                state_index = state["index"]
                states = component_decl.get("states", [])
                if (
                    not isinstance(state_index, int)
                    or state_index < 0
                    or state_index >= len(states)
                ):
                    raise ValueError(f"BNGIR {where} references unknown state index")
                if state.get("value") != states[state_index]:
                    raise ValueError(f"BNGIR {where} state value/index disagree")
            elif state_kind == "set" and component_decl is not None:
                indices = state.get("indices", [])
                values = state.get("values", [])
                if len(indices) != len(values):
                    raise ValueError(
                        f"BNGIR {where} state set value/index lengths differ"
                    )
                states = component_decl.get("states", [])
                for state_index, state_value in zip(indices, values):
                    if (
                        not isinstance(state_index, int)
                        or state_index < 0
                        or state_index >= len(states)
                    ):
                        raise ValueError(
                            f"BNGIR {where} references unknown state index"
                        )
                    if state_value != states[state_index]:
                        raise ValueError(f"BNGIR {where} state value/index disagree")
            elif state_kind not in {"any", "exact", "set"}:
                raise ValueError(f"BNGIR {where} has invalid state constraint")
    pattern_compartment_id = pattern.get("compartment_id")
    if pattern_compartment_id is not None and (
        not isinstance(pattern_compartment_id, int)
        or pattern_compartment_id not in compartments
    ):
        raise ValueError(f"BNGIR {where} references unknown graph compartment id")


def _validate_pattern_ref_v02(
    ref: Mapping[str, Any], direction: Mapping[str, Any], where: str, *, site: bool
) -> None:
    ref = _require_mapping(ref, where)
    side = ref.get("side")
    section = (
        "reactants" if side == "reactant" else "products" if side == "product" else None
    )
    if section is None:
        raise ValueError(f"BNGIR {where}.side must be reactant or product")
    patterns = direction.get(section, [])
    pi = ref.get("pattern")
    mi = ref.get("molecule")
    if not isinstance(pi, int) or pi < 0 or pi >= len(patterns):
        raise ValueError(f"BNGIR {where} pattern reference is out of range")
    molecules = _require_mapping(patterns[pi], f"{where}.pattern").get("molecules", [])
    if not isinstance(mi, int) or mi < 0 or mi >= len(molecules):
        raise ValueError(f"BNGIR {where} molecule reference is out of range")
    if site:
        si = ref.get("site")
        sites = _require_mapping(molecules[mi], f"{where}.molecule").get("sites", [])
        if not isinstance(si, int) or si < 0 or si >= len(sites):
            raise ValueError(f"BNGIR {where} site reference is out of range")


def _validate_direction_v02(
    direction: Mapping[str, Any], model: Mapping[str, Any], where: str
) -> None:
    direction = _require_mapping(direction, where)
    for side in ("reactants", "products"):
        patterns = direction.get(side, [])
        if not isinstance(patterns, list):
            raise ValueError(f"BNGIR {where}.{side} must be an array")
        for i, pattern in enumerate(patterns):
            _validate_pattern_v02(
                _require_mapping(pattern, f"{where}.{side}[{i}]"),
                model,
                f"{where}.{side}[{i}]",
            )
    scopes = direction.get("local_scopes", [])
    if not isinstance(scopes, list):
        raise ValueError(f"BNGIR {where}.local_scopes must be an array")
    local_names: set[str] = set()
    reactants = direction.get("reactants", [])
    for i, raw_scope in enumerate(scopes):
        scope = _require_mapping(raw_scope, f"{where}.local_scopes[{i}]")
        name = scope.get("name")
        kind = scope.get("kind")
        pi = scope.get("reactant_pattern")
        if not isinstance(name, str) or not name or name in local_names:
            raise ValueError(f"BNGIR {where} has invalid/duplicate local scope name")
        local_names.add(name)
        if kind not in {"molecule", "species"}:
            raise ValueError(f"BNGIR {where} has invalid local scope kind")
        if not isinstance(pi, int) or pi < 0 or pi >= len(reactants):
            raise ValueError(
                f"BNGIR {where} local scope reactant pattern is out of range"
            )
        occurrence = scope.get("molecule_occurrence")
        if kind == "molecule":
            molecules = _require_mapping(reactants[pi], f"{where}.reactants[{pi}]").get(
                "molecules", []
            )
            if (
                not isinstance(occurrence, int)
                or occurrence < 0
                or occurrence >= len(molecules)
            ):
                raise ValueError(
                    f"BNGIR {where} local scope molecule occurrence is out of range"
                )
        elif occurrence is not None:
            raise ValueError(
                f"BNGIR {where} species scope must not have a molecule occurrence"
            )
    if direction.get("rate"):
        rate = _require_mapping(direction["rate"], f"{where}.rate")
        _validate_expression_v02(
            _require_mapping(rate.get("expression"), f"{where}.rate.expression"),
            model,
            local_names=local_names,
            reactant_count=len(reactants),
            where=f"{where}.rate.expression",
        )
    for i, raw_filter in enumerate(direction.get("filters", [])):
        filter_ = _require_mapping(raw_filter, f"{where}.filters[{i}]")
        side = filter_.get("side")
        patterns = (
            reactants
            if side == "reactant"
            else direction.get("products", []) if side == "product" else None
        )
        pi = filter_.get("pattern_index")
        if patterns is None or not isinstance(pi, int) or pi < 0 or pi >= len(patterns):
            raise ValueError(f"BNGIR {where} filter target is out of range")
        for j, pattern in enumerate(filter_.get("patterns", [])):
            _validate_pattern_v02(
                _require_mapping(pattern, f"{where}.filters[{i}].patterns[{j}]"),
                model,
                f"{where}.filters[{i}].patterns[{j}]",
            )
    for i, raw_mutation in enumerate(direction.get("mutations", [])):
        mutation = _require_mapping(raw_mutation, f"{where}.mutations[{i}]")
        kind = mutation.get("kind")
        if kind in {"add_molecule", "delete_molecule"}:
            _validate_pattern_ref_v02(
                mutation.get("molecule"),
                direction,
                f"{where}.mutations[{i}].molecule",
                site=False,
            )
        elif kind in {"add_bond", "delete_bond", "change_state"}:
            _validate_pattern_ref_v02(
                mutation.get("source"),
                direction,
                f"{where}.mutations[{i}].source",
                site=True,
            )
            if kind in {"add_bond", "delete_bond"}:
                _validate_pattern_ref_v02(
                    mutation.get("partner"),
                    direction,
                    f"{where}.mutations[{i}].partner",
                    site=True,
                )
        else:
            raise ValueError(f"BNGIR {where} has unsupported mutation kind: {kind!r}")


def _validate_model_v02(model: Mapping[str, Any]) -> None:
    # Construct ID maps up front to catch duplicate IDs even when unreferenced.
    for section in (
        "parameters",
        "molecule_types",
        "compartments",
        "observables",
        "functions",
        "energy_patterns",
        "population_types",
        "rules",
    ):
        _section_id_map(model, section)
    for i, parameter in enumerate(model.get("parameters", [])):
        parameter = _require_mapping(parameter, f"model.parameters[{i}]")
        _validate_expression_v02(
            _require_mapping(parameter.get("expression"), "parameter expression"),
            model,
            local_names=set(),
            where=f"model.parameters[{i}].expression",
        )
    for i, seed in enumerate(model.get("seeds", [])):
        seed = _require_mapping(seed, f"model.seeds[{i}]")
        _validate_pattern_v02(
            _require_mapping(seed.get("pattern"), "seed pattern"),
            model,
            f"model.seeds[{i}].pattern",
        )
        _validate_expression_v02(
            _require_mapping(seed.get("amount"), "seed amount"),
            model,
            local_names=set(),
            where=f"model.seeds[{i}].amount",
        )
    for i, observable in enumerate(model.get("observables", [])):
        observable = _require_mapping(observable, f"model.observables[{i}]")
        for j, term in enumerate(observable.get("terms", [])):
            term = _require_mapping(term, f"model.observables[{i}].terms[{j}]")
            _validate_pattern_v02(
                _require_mapping(term.get("pattern"), "observable pattern"),
                model,
                f"model.observables[{i}].terms[{j}].pattern",
            )
    for i, function in enumerate(model.get("functions", [])):
        function = _require_mapping(function, f"model.functions[{i}]")
        args = function.get("arguments", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError(f"BNGIR model.functions[{i}].arguments must be strings")
        _validate_expression_v02(
            _require_mapping(function.get("expression"), "function expression"),
            model,
            local_names=set(args),
            where=f"model.functions[{i}].expression",
        )
    for i, factor in enumerate(model.get("energy_patterns", [])):
        factor = _require_mapping(factor, f"model.energy_patterns[{i}]")
        _validate_pattern_v02(
            _require_mapping(factor.get("pattern"), "energy pattern"),
            model,
            f"model.energy_patterns[{i}].pattern",
        )
        _validate_expression_v02(
            _require_mapping(factor.get("expression"), "energy expression"),
            model,
            local_names=set(),
            where=f"model.energy_patterns[{i}].expression",
        )
    population_types = _section_id_map(model, "population_types")
    for i, mapping in enumerate(model.get("population_maps", [])):
        mapping = _require_mapping(mapping, f"model.population_maps[{i}]")
        _validate_pattern_v02(
            _require_mapping(mapping.get("pattern"), "population-map pattern"),
            model,
            f"model.population_maps[{i}].pattern",
        )
        population_id = mapping.get("population_id")
        if not isinstance(population_id, int) or population_id not in population_types:
            raise ValueError(
                f"BNGIR model.population_maps[{i}] references unknown population type"
            )
        if mapping.get("population") != population_types[population_id].get("name"):
            raise ValueError(
                f"BNGIR model.population_maps[{i}] population name/id disagree"
            )
        _validate_expression_v02(
            _require_mapping(mapping.get("rate"), "population-map rate"),
            model,
            local_names=set(),
            where=f"model.population_maps[{i}].rate",
        )

    for i, rule in enumerate(model.get("rules", [])):
        rule = _require_mapping(rule, f"model.rules[{i}]")
        _validate_direction_v02(
            _require_mapping(rule.get("forward"), "rule.forward"),
            model,
            f"model.rules[{i}].forward",
        )
        if rule.get("reverse") is not None:
            _validate_direction_v02(
                _require_mapping(rule.get("reverse"), "rule.reverse"),
                model,
                f"model.rules[{i}].reverse",
            )


def _load_document_v02(document: str | Mapping[str, Any]) -> Mapping[str, Any]:
    root = _parse_document(document)
    if root.get("version") != STRUCTURAL_VERSION:
        raise ValueError("expected BNGIR v0.2")
    features = _require_mapping(root.get("features"), "features")
    supported = _FEATURES | {"structured_patterns", "structured_expressions"}
    validated: dict[str, list[str]] = {}
    for feature_kind in ("required", "used"):
        values = features.get(feature_kind, [])
        if not isinstance(values, list) or not all(
            isinstance(item, str) for item in values
        ):
            raise ValueError(f"BNGIR features.{feature_kind} must be a string array")
        unknown = sorted(set(values) - supported)
        if unknown:
            raise ValueError(
                f"unsupported {feature_kind} BNGIR features: {', '.join(unknown)}"
            )
        validated[feature_kind] = values
    required = validated["required"]
    if not {"structured_patterns", "structured_expressions"}.issubset(set(required)):
        raise ValueError("BNGIR v0.2 must require structured patterns and expressions")
    model = _require_mapping(root.get("model"), "model")
    _validate_model_v02(model)
    _validate_actions(root)
    return root


def _section_id_map(
    model: Mapping[str, Any], section: str
) -> dict[int, Mapping[str, Any]]:
    values = model.get(section, [])
    if not isinstance(values, list):
        raise ValueError(f"BNGIR model.{section} must be an array")
    result: dict[int, Mapping[str, Any]] = {}
    for position, raw in enumerate(values):
        item = _require_mapping(raw, f"model.{section}[{position}]")
        semantic_id = item.get("id", position)
        if not isinstance(semantic_id, int) or semantic_id < 0:
            raise ValueError(
                f"BNGIR model.{section}[{position}].id must be a non-negative integer"
            )
        if semantic_id in result:
            raise ValueError(f"duplicate BNGIR {section} id: {semantic_id}")
        result[semantic_id] = item
    return result


def _name_for_symbol(model: Mapping[str, Any], kind: str, index: int) -> str:
    sections = {
        "parameter": "parameters",
        "function": "functions",
        "observable": "observables",
        "molecule_type": "molecule_types",
        "compartment": "compartments",
        "reaction_rule": "rules",
        "energy_pattern": "energy_patterns",
        "population_type": "population_types",
    }
    section = sections.get(kind)
    if section is None:
        raise ValueError(f"unsupported BNGIR symbol kind: {kind}")
    values = _section_id_map(model, section)
    if not isinstance(index, int) or index < 0 or index not in values:
        raise ValueError(f"BNGIR {kind} symbol id is unknown: {index}")
    item = values[index]
    name = item.get("name")
    if section == "energy_patterns":
        name = item.get("label")
    if not isinstance(name, str) or not name:
        raise ValueError(f"BNGIR {kind} symbol has no reconstructable name")
    return name


_BINARY_TOKENS = {
    "add": "+",
    "subtract": "-",
    "multiply": "*",
    "divide": "/",
    "power": "^",
    "less": "<",
    "less_equal": "<=",
    "greater": ">",
    "greater_equal": ">=",
    "equal": "==",
    "not_equal": "!=",
    "and": "&&",
    "or": "||",
}
_UNARY_TOKENS = {"plus": "+", "negate": "-", "not": "!"}
_BUILTIN_NAMES = {
    "michaelis_menten": "MM",
    "function_product": "FunctionProduct",
    "table_function": "tfun",
}


def _expression_v02(expression: Mapping[str, Any], model: Mapping[str, Any]) -> str:
    expression = _require_mapping(expression, "expression")
    kind = expression.get("kind")
    args = [
        _expression_v02(_require_mapping(arg, "expression argument"), model)
        for arg in expression.get("arguments", [])
    ]
    if kind == "number":
        return repr(float(expression["value"]))
    if kind in {"parameter_ref", "observable_ref", "function_ref"}:
        symbol = _require_mapping(expression.get("symbol"), "expression symbol")
        name = _name_for_symbol(
            model, str(symbol.get("kind")), int(symbol.get("index"))
        )
        if expression.get("call") or args:
            return f"{name}({','.join(args)})"
        return name
    if kind == "local_ref":
        name = expression.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("BNGIR local_ref expression is missing a name")
        return name
    if kind == "reactant_count_ref":
        index = int(expression.get("reactant_index", -1))
        if index < 0:
            raise ValueError("BNGIR reactant_count_ref has an invalid index")
        return f"reactant_{index + 1}"
    if kind == "time_ref":
        return "time"
    if kind == "unary":
        if len(args) != 1 or expression.get("operator") not in _UNARY_TOKENS:
            raise ValueError("invalid BNGIR unary expression")
        return f"({_UNARY_TOKENS[expression['operator']]}{args[0]})"
    if kind == "binary":
        if len(args) != 2 or expression.get("operator") not in _BINARY_TOKENS:
            raise ValueError("invalid BNGIR binary expression")
        return f"({args[0]} {_BINARY_TOKENS[expression['operator']]} {args[1]})"
    if kind == "builtin_call":
        builtin = str(expression.get("builtin", "unknown"))
        if builtin == "unknown":
            raise ValueError("unresolved builtin in BNGIR expression")
        if builtin == "pi" and not args:
            return "_PI"
        if builtin == "e" and not args:
            return "_e"
        name = _BUILTIN_NAMES.get(builtin, builtin)
        return f"{name}({','.join(args)})"
    if kind == "table_function":
        if expression.get("file"):
            head = _quote_string(expression["file"])
            counter = args[0] if args else "time"
            pieces = [head, counter]
        else:
            xs = ",".join(repr(float(value)) for value in expression.get("x", []))
            ys = ",".join(repr(float(value)) for value in expression.get("y", []))
            counter = args[0] if args else "time"
            pieces = [f"[{xs}]", f"[{ys}]", counter]
        method = expression.get("method")
        if method and method != "linear":
            pieces.append(f"method=>{_quote_string(method)}")
        return f"tfun({','.join(pieces)})"
    if kind == "unresolved":
        raise ValueError("cannot deserialize unresolved BNGIR v0.2 expression")
    raise ValueError(f"unsupported BNGIR expression kind: {kind!r}")


def _pattern_v02(
    pattern: Mapping[str, Any],
    *,
    molecule_scopes: Mapping[int, list[str]] | None = None,
    species_scopes: list[str] | None = None,
) -> str:
    pattern = _require_mapping(pattern, "pattern")
    molecules = []
    for raw_molecule in pattern.get("molecules", []):
        molecule = _require_mapping(raw_molecule, "pattern molecule")
        name = molecule.get("type")
        if not isinstance(name, str) or not name:
            raise ValueError("BNGIR pattern molecule is missing type")
        sites = []
        for raw_site in molecule.get("sites", []):
            site = _require_mapping(raw_site, "pattern site")
            component = site.get("component")
            if not isinstance(component, str) or not component:
                raise ValueError("BNGIR pattern site is missing component")
            text = component
            state = _require_mapping(site.get("state", {}), "pattern state")
            state_kind = state.get("kind", "any")
            if state_kind == "exact":
                text += f"~{state['value']}"
            elif state_kind == "set":
                text += "".join(f"~{value}" for value in state.get("values", []))
            elif state_kind != "any":
                raise ValueError(f"unsupported BNGIR state constraint: {state_kind}")
            if site.get("label"):
                text += f"%{site['label']}"
            bond = _require_mapping(site.get("bond", {}), "pattern bond")
            alternatives = bond.get("alternatives")
            bonds = alternatives if alternatives else [bond]
            for raw_bond in bonds:
                current = _require_mapping(raw_bond, "pattern bond alternative")
                bond_kind = current.get("kind", "unspecified")
                if bond_kind == "unspecified":
                    continue
                if bond_kind == "unbound":
                    text += "."
                elif bond_kind == "bound":
                    text += "!+"
                elif bond_kind == "any":
                    text += "!?"
                elif bond_kind == "exact":
                    text += f"!{int(current['group'])}"
                else:
                    raise ValueError(f"unsupported BNGIR bond constraint: {bond_kind}")
            sites.append(text)
        labels = ""
        if molecule_scopes:
            labels = "".join(
                f"%{scope}"
                for scope in molecule_scopes.get(
                    int(molecule.get("occurrence", len(molecules))), []
                )
            )
        mol = f"{name}{labels}({','.join(sites)})"
        if molecule.get("compartment"):
            mol += f"@{molecule['compartment']}"
        molecules.append(mol)
    body = ".".join(molecules) if molecules else "0"
    if pattern.get("compartment"):
        # Preserve whether the graph-level compartment came from the prefix
        # form. Molecule-local compartments are serialized on each molecule.
        if pattern.get("compartment_prefix", True):
            body = f"@{pattern['compartment']}:{body}"
        else:
            body = f"{body}@{pattern['compartment']}"
    if species_scopes:
        for scope in reversed(species_scopes):
            body = f"%{scope}::{body}"
    return body


def _direction_pattern_strings_v02(
    direction: Mapping[str, Any], side: str
) -> list[str]:
    patterns = direction.get(side, [])
    if side != "reactants":
        return [_pattern_v02(pattern) for pattern in patterns]
    molecule_scopes: dict[int, dict[int, list[str]]] = {}
    species_scopes: dict[int, list[str]] = {}
    for raw in direction.get("local_scopes", []):
        scope = _require_mapping(raw, "rule local scope")
        pi = int(scope["reactant_pattern"])
        if scope["kind"] == "species":
            species_scopes.setdefault(pi, []).append(str(scope["name"]))
        else:
            occurrence = int(scope["molecule_occurrence"])
            molecule_scopes.setdefault(pi, {}).setdefault(occurrence, []).append(
                str(scope["name"])
            )
    return [
        _pattern_v02(
            pattern,
            molecule_scopes=molecule_scopes.get(i),
            species_scopes=species_scopes.get(i),
        )
        for i, pattern in enumerate(patterns)
    ]


def _modifier_v02(modifier: Mapping[str, Any]) -> str:
    kind = modifier.get("kind")
    plain = {
        "delete_molecules": "DeleteMolecules",
        "move_connected": "MoveConnected",
        "match_once": "MatchOnce",
        "total_rate": "TotalRate",
    }
    if kind in plain:
        return plain[kind]
    if kind == "unknown":
        raise ValueError("cannot deserialize unresolved BNGIR v0.2 rule modifier")
    # include/exclude semantics are serialized in direction.filters and emitted there.
    return ""


def _filter_v02(filter_: Mapping[str, Any]) -> str:
    side = filter_.get("side")
    include = bool(filter_.get("include"))
    if side not in {"reactant", "product"}:
        raise ValueError("invalid BNGIR filter side")
    name = ("include_" if include else "exclude_") + (
        "products" if side == "product" else "reactants"
    )
    index = int(filter_.get("pattern_index", 0)) + 1
    patterns = [_pattern_v02(item) for item in filter_.get("patterns", [])]
    return f"{name}({index},{','.join(patterns)})"


def _as_bngl_v02(root: Mapping[str, Any]) -> str:
    model = _require_mapping(root["model"], "model")
    metadata = _require_mapping(model.get("metadata", {}), "model.metadata")
    lines: list[str] = []
    if metadata.get("version"):
        lines.append(f"version({_quote_string(metadata['version'])})")
    if metadata.get("substance_units"):
        lines.append(f"substanceUnits({_quote_string(metadata['substance_units'])})")
    if metadata.get("name"):
        lines.append(f"setModelName({_quote_string(metadata['name'])})")
    for key, value in metadata.get("options", {}).items():
        lines.append(f"setOption({_quote_string(key)}, {_quote_action_value(value)})")
    lines.append("begin model")

    parameters = model.get("parameters", [])
    if parameters:
        lines.append("begin parameters")
        for item in parameters:
            lines.append(
                f"  {item['name']} {_expression_v02(item['expression'], model)}"
            )
        lines.append("end parameters")

    compartments = model.get("compartments", [])
    if compartments:
        lines.append("begin compartments")
        for item in compartments:
            suffix = f" {item['parent']}" if item.get("parent") else ""
            lines.append(
                f"  {item['name']} {int(item['dimension'])} {item['volume']}{suffix}"
            )
        lines.append("end compartments")

    molecule_types = model.get("molecule_types", [])
    if molecule_types:
        lines.append("begin molecule types")
        for item in molecule_types:
            components = [
                component["name"]
                + "".join(f"~{state}" for state in component.get("states", []))
                for component in item.get("components", [])
            ]
            population = " population" if item.get("population") else ""
            lines.append(f"  {item['name']}({','.join(components)}){population}")
        lines.append("end molecule types")

    seeds = model.get("seeds", [])
    if seeds:
        lines.append("begin seed species")
        for item in seeds:
            pattern = _pattern_v02(item["pattern"])
            if item.get("constant") and not pattern.startswith("$"):
                pattern = "$" + pattern
            lines.append(f"  {pattern} {_expression_v02(item['amount'], model)}")
        lines.append("end seed species")

    observables = model.get("observables", [])
    if observables:
        lines.append("begin observables")
        for item in observables:
            kind = "Molecules" if item.get("kind") == "molecules" else "Species"
            rendered_terms = []
            for term in item.get("terms", []):
                pattern = _pattern_v02(term["pattern"])
                relation = str(term.get("relation", ""))
                quantity = int(term.get("quantity", 0))
                rendered_terms.append(
                    f"{pattern}{relation}{quantity}" if relation else pattern
                )
            lines.append(f"  {kind} {item['name']} {','.join(rendered_terms)}")
        lines.append("end observables")

    functions = model.get("functions", [])
    if functions:
        lines.append("begin functions")
        for item in functions:
            args = ",".join(item.get("arguments", []))
            lines.append(
                f"  {item['name']}({args}) = {_expression_v02(item['expression'], model)}"
            )
        lines.append("end functions")

    energy_patterns = model.get("energy_patterns", [])
    if energy_patterns:
        lines.append("begin energy patterns")
        for item in energy_patterns:
            label = f"{item['label']}: " if item.get("label") else ""
            lines.append(
                f"  {label}{_pattern_v02(item['pattern'])} {_expression_v02(item['expression'], model)}"
            )
        lines.append("end energy patterns")

    population_maps = model.get("population_maps", [])
    if population_maps:
        lines.append("begin population maps")
        for item in population_maps:
            label = f"{item['label']}: " if item.get("label") else ""
            args = ",".join(item.get("arguments", []))
            rate = _expression_v02(item["rate"], model)
            lines.append(
                f"  {label}{_pattern_v02(item['pattern'])} -> "
                f"{item['population']}({args}) {rate}"
            )
        lines.append("end population maps")

    rules = model.get("rules", [])
    if rules:
        lines.append("begin reaction rules")
        for item in rules:
            forward = _require_mapping(item["forward"], "rule.forward")
            reactants = (
                " + ".join(_direction_pattern_strings_v02(forward, "reactants")) or "0"
            )
            products = (
                " + ".join(_direction_pattern_strings_v02(forward, "products")) or "0"
            )
            arrow = "<->" if item.get("bidirectional") else "->"
            rates = []
            if forward.get("rate"):
                rates.append(_expression_v02(forward["rate"]["expression"], model))
            reverse = item.get("reverse")
            if item.get("bidirectional"):
                if not reverse or not reverse.get("rate"):
                    raise ValueError("bidirectional BNGIR rule is missing reverse rate")
                rates.append(_expression_v02(reverse["rate"]["expression"], model))
            label = str(item.get("label", "")).rstrip(":")
            prefix = f"{label}: " if label else ""
            line = f"  {prefix}{reactants} {arrow} {products} {', '.join(rates)}"
            modifiers = [
                value
                for value in (_modifier_v02(m) for m in item.get("modifiers", []))
                if value
            ]
            modifiers.extend(_filter_v02(f) for f in forward.get("filters", []))
            if modifiers:
                line += " " + " ".join(modifiers)
            lines.append(line)
        lines.append("end reaction rules")

    actions = list(
        _require_mapping(root.get("protocol", {}), "protocol").get("actions", [])
    )
    protocol_actions = [a for a in actions if a.get("scope") == "simulation_protocol"]
    model_actions = [a for a in actions if a.get("scope") == "model"]
    if protocol_actions:
        lines.append("begin protocol")
        lines += [_action_lines(action) for action in protocol_actions]
        lines.append("end protocol")
    lines.append("end model")
    if model_actions:
        lines.append("begin actions")
        lines += [_action_lines(action) for action in model_actions]
        lines.append("end actions")
    return "\n".join(lines) + "\n"


def from_bngir(document: str | Mapping[str, Any]):
    """Reconstruct a modern ``BioNetGenModel`` from supported BNGIR versions."""
    root = _parse_document(document)
    from .model import BioNetGenModel, _cpp

    if root["version"] == VERSION:
        root = _load_document_v01(root)
        source = _as_bngl_v01(root)
        model_data = _require_mapping(root["model"], "model")
        name = model_data.get("name")
    else:
        root = _load_document_v02(root)
        source = _as_bngl_v02(root)
        model_data = _require_mapping(root["model"], "model")
        name = _require_mapping(model_data.get("metadata", {}), "model.metadata").get(
            "name"
        )

    native = _cpp.parse_string(source)
    result = BioNetGenModel(native)
    if name:
        result._model.set_model_name(name)
    return result


def semantic_equal(left: Any, right: Any, *, version: str = VERSION) -> bool:
    """Compare canonical BNGIR documents, ignoring JSON formatting."""
    left_doc = _parse_document(to_bngir(left, version=version))
    right_doc = _parse_document(to_bngir(right, version=version))
    return left_doc == right_doc
