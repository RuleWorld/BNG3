"""Versioned, source-free BNGIR JSON v0.1 serialization.

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


def _payload(model: Any, provenance: Mapping[str, Any] | None) -> dict[str, Any]:
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


def to_bngir(model: Any, *, provenance: Mapping[str, Any] | None = None) -> str:
    """Return deterministic BNGIR JSON v0.1 for ``model``."""

    return json.dumps(
        _payload(model, provenance),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"BNGIR {where} must be an object")
    return value


def _load_document(document: str | Mapping[str, Any]) -> Mapping[str, Any]:
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


def _as_bngl(root: Mapping[str, Any]) -> str:
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


def from_bngir(document: str | Mapping[str, Any]):
    """Reconstruct a modern ``BioNetGenModel`` from BNGIR v0.1."""

    root = _load_document(document)
    from .model import BioNetGenModel, _cpp

    native = _cpp.parse_string(_as_bngl(root))
    result = BioNetGenModel(native)
    model = _require_mapping(root["model"], "model")
    if model.get("name"):
        result._model.set_model_name(model["name"])
    return result


def semantic_equal(left: Any, right: Any) -> bool:
    """Compare canonical BNGIR documents, ignoring JSON formatting."""

    return _load_document(to_bngir(left)) == _load_document(to_bngir(right))
