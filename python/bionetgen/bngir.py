"""Versioned, source-free BNGIR serialization.

The wire object contains semantic model entities and a separate protocol. It
does not contain generated networks, solver state, caches, or source text.
Deserializer support is intentionally strict: unknown required features and
unsupported population-map reconstruction fail closed.
"""

from __future__ import annotations

import json
import math
import re
import ast
from collections.abc import Mapping
from fractions import Fraction
from typing import Any

FORMAT = "BNGIR"
VERSION = "0.1"
STRUCTURAL_VERSION = "0.2"
DEFAULT_VERSION = STRUCTURAL_VERSION
SUPPORTED_VERSIONS = frozenset({VERSION, STRUCTURAL_VERSION})

# Bound on network-generation iterations used by exact equality proof search.
# Unbounded models otherwise expand exponentially and never reach the fixed
# point that the certificate requires; truncation is reported as undecided.
_EQUALITY_NETWORK_MAX_ITER = 6

_FEATURES = frozenset(
    {
        "barrier_patterns",
        "compartments",
        "delayed_rules",
        "driven_reservoirs",
        "energy_patterns",
        "functions",
        "observables",
        "population_maps",
        "protocol",
        "rules",
        "seeds",
        "units",
    }
)

# The six unit-default roles normalizeUnitSyntax() accepts on read-back; any
# other role cannot be re-emitted as BNGL.
_UNIT_DEFAULT_ROLES = frozenset(
    {
        "areaUnits",
        "extentUnits",
        "lengthUnits",
        "substanceUnits",
        "timeUnits",
        "volumeUnits",
    }
)

# Builtin function names the compiler can resolve, mirroring builtinName() in
# cpp/bindings/bind_compile_snapshot.cpp. A builtin_call outside this set can
# not be rendered back to BNGL and must be refused rather than lowered to an
# ordinary function call.
_KNOWN_BUILTINS = frozenset(
    {
        "abs",
        "acos",
        "acosh",
        "arrhenius",
        "asin",
        "asinh",
        "atan",
        "atanh",
        "avg",
        "ceil",
        "cos",
        "cosh",
        "e",
        "exp",
        "factorial",
        "floor",
        "function_product",
        "hill",
        "hybrid",
        "if",
        "ln",
        "log10",
        "log2",
        "max",
        "michaelis_menten",
        "min",
        "mratio",
        "pi",
        "rint",
        "saturation",
        "sin",
        "sinh",
        "sqrt",
        "sum",
        "table_function",
        "tan",
        "tanh",
        "time",
    }
)


def _expression(value: Any) -> str:
    rendered = value.to_string() if hasattr(value, "to_string") else str(value)
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", rendered):
        # C++ may print a binary double with 17 digits (0.10000000000000001).
        # Python's repr chooses the shortest decimal that round-trips to the
        # same value, keeping numeric expressions stable and readable.
        return repr(float(rendered))
    return rendered


def _action(action: Any, scope: str) -> dict[str, Any]:
    return {"scope": scope, "name": action.name, "arguments": dict(action.arguments)}


def _model_of(model: Any) -> Any:
    native = getattr(model, "_model", None)
    if native is None:
        raise TypeError("BNGIR requires a modern BioNetGenModel")
    return native


def _payload_v01(model: Any, provenance: Mapping[str, Any] | None) -> dict[str, Any]:
    native = _model_of(model)

    parameters = []
    for p in native.parameters:
        item = {"name": p.name, "expression": _expression(p.expression)}
        if p.unit:
            item["unit"] = p.unit
        parameters.append(item)

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
    seeds = []
    for seed in native.seed_species:
        item = {
            "pattern": seed.pattern,
            "amount": _expression(seed.amount),
            "constant": bool(seed.is_constant),
            "compartment": seed.compartment,
        }
        if seed.unit:
            item["unit"] = seed.unit
        seeds.append(item)

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
    # v0.1 stores patterns as strings. The native rule view drops compartment
    # prefixes, so recover them from the compiled snapshot; otherwise a v0.1
    # round trip silently deletes compartment transport rules.
    snapshot_rules = []
    try:
        from .model import _cpp

        snapshot_rules = _cpp._compiled_snapshot(native).get("rules", [])
    except Exception:
        snapshot_rules = []

    def _v01_patterns(rule_index: int, side: str, patterns: list) -> list:
        if rule_index >= len(snapshot_rules):
            return list(patterns)
        direction = snapshot_rules[rule_index].get("forward", {})
        snapshot_patterns = direction.get(side, [])
        rendered = []
        for index, pattern in enumerate(patterns):
            text = str(pattern)
            if index < len(snapshot_patterns) and not text.startswith("@"):
                compartment = snapshot_patterns[index].get("compartment", "")
                if compartment and f"@{compartment}" not in text:
                    # The suffix spelling keeps the compartment on the molecule,
                    # which BNGL's network generator honours for transport
                    # rules; the prefix spelling is silently dropped.
                    text = f"{text}@{compartment}"
            rendered.append(text)
        return rendered

    rules = []
    for rule_index, rule in enumerate(native.reaction_rules):
        item = {
            "name": rule.rule_name,
            "label": rule.label,
            "reactants": _v01_patterns(rule_index, "reactants", rule.reactant_patterns),
            "products": _v01_patterns(rule_index, "products", rule.product_patterns),
            "rates": list(rule.rates),
            "modifiers": list(rule.modifiers),
            "bidirectional": bool(rule.is_bidirectional),
            "driving_work": rule.driving_work if rule.has_driving_work else "",
        }
        if rule.has_delay:
            item["delay"] = rule.delay_expression
            if rule.is_non_consuming:
                item["non_consuming"] = True
        rules.append(item)

    compartments = []
    for compartment in native.compartments:
        item = {
            "name": compartment.name,
            "volume": float(compartment.volume),
            "dimension": int(compartment.dimension),
            "parent": compartment.parent,
        }
        if compartment.unit:
            item["unit"] = compartment.unit
        compartments.append(item)
    energy_patterns = [
        {
            "label": pattern.label,
            "pattern": pattern.pattern,
            "expression": _expression(pattern.expression),
        }
        for pattern in native.energy_patterns
    ]
    # Barrier patterns are a separate section: a transition-state contribution
    # is not a ground-state energy, so it must not be folded into
    # energy_patterns. The transition is carried as reactant/product pattern
    # strings plus the barrier energy.
    barrier_patterns = [
        {
            "label": barrier.label,
            "reactants": list(barrier.transition.reactant_patterns),
            "products": list(barrier.transition.product_patterns),
            "bidirectional": bool(barrier.transition.is_bidirectional),
            "expression": barrier.expression,
        }
        for barrier in native.barrier_patterns
    ]
    population_maps = []
    if native.population_maps:
        snapshot_population_rates = None
        try:
            from .model import _cpp

            snapshot = _cpp._compiled_snapshot(native)
            snapshot_population_rates = [
                item.get("rate") for item in snapshot.get("population_maps", [])
            ]
            snapshot_model = snapshot
        except Exception:
            snapshot_population_rates = None
            snapshot_model = None
        for index, mapping in enumerate(native.population_maps):
            item = {
                "label": mapping.label,
                "pattern": mapping.pattern,
                "function": mapping.function,
                "args": list(mapping.args),
            }
            rate = None
            if snapshot_population_rates and index < len(snapshot_population_rates):
                rate = snapshot_population_rates[index]
            if isinstance(rate, Mapping) and snapshot_model is not None:
                item["rate"] = _expression_v02(rate, snapshot_model)
            elif hasattr(mapping, "rateText") and getattr(mapping, "rateText"):
                item["rate"] = str(getattr(mapping, "rateText"))
            elif hasattr(mapping, "rate") and isinstance(getattr(mapping, "rate"), str):
                item["rate"] = getattr(mapping, "rate")
            if getattr(mapping, "total_rate", False):
                item["total_rate"] = True
            population_maps.append(item)

    features = {"required": [], "used": []}
    if compartments:
        features["used"].append("compartments")
    if energy_patterns:
        features["used"].append("energy_patterns")
    if barrier_patterns:
        features["used"].append("barrier_patterns")
    if any(rule.get("driving_work") for rule in rules):
        features["used"].append("driven_reservoirs")
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
    if any(rule.get("delay") for rule in rules):
        features["used"].append("delayed_rules")
    if native.unit_defaults or any(
        "unit" in item for item in (*parameters, *seeds, *compartments)
    ):
        features["used"].append("units")
    if seeds:
        features["used"].append("seeds")
    features["used"].sort()

    model_payload = {
        "name": getattr(native, "model" + "_name"),
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
        "barrier_patterns": barrier_patterns,
        "population_maps": population_maps,
        "rules": rules,
    }
    if native.unit_defaults:
        model_payload["unit_defaults"] = dict(native.unit_defaults)
    unit_definitions = list(native.unit_definitions)
    if unit_definitions:
        model_payload["unit_definitions"] = unit_definitions

    result = {
        "format": FORMAT,
        "version": VERSION,
        "features": features,
        "model": model_payload,
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
        ("barrier_patterns", "barrier_patterns"),
        ("functions", "functions"),
        ("observables", "observables"),
        ("population_maps", "population_maps"),
        ("population_types", "population_maps"),
        ("rules", "rules"),
        ("seeds", "seeds"),
    ):
        if snapshot.get(key):
            used.append(feature)
    if any(rule.get("delay") is not None for rule in snapshot.get("rules", [])):
        used.append("delayed_rules")
    if any(
        rule.get("driving_work") not in (None, "", {})
        for rule in snapshot.get("rules", [])
        if isinstance(rule, Mapping)
    ):
        used.append("driven_reservoirs")
    metadata = snapshot.get("metadata") or {}
    has_units = (
        metadata.get("unit_defaults")
        or metadata.get("unit_definitions")
        or metadata.get("substance_units")
        or any(item.get("unit") for item in snapshot.get("parameters", []))
        or any(item.get("unit") for item in snapshot.get("seeds", []))
        or any(item.get("unit") for item in snapshot.get("compartments", []))
        or any(item.get("declared_unit") for item in snapshot.get("parameters", []))
        or any(item.get("inferred_unit") for item in snapshot.get("parameters", []))
        or any(item.get("declared_unit") for item in snapshot.get("seeds", []))
        or any(item.get("declared_unit") for item in snapshot.get("compartments", []))
    )
    if has_units:
        used.append("units")
    if snapshot.get("actions"):
        used.append("protocol")
    return {
        "required": ["structured_patterns", "structured_expressions"],
        "used": sorted(set(used) | {"structured_patterns", "structured_expressions"}),
    }


def _payload_v02(model: Any, provenance: Mapping[str, Any] | None) -> dict[str, Any]:
    native = _model_of(model)
    for observable in native.observables:
        if observable.type not in ("Molecules", "Species", "Counter"):
            raise ValueError(
                f"BNGIR {STRUCTURAL_VERSION} cannot represent "
                f"{observable.type!r} observable kinds; use version {VERSION!r}"
            )
    try:
        from .model import _cpp

        snapshot = _cpp._compiled_snapshot(native)
    except (AttributeError, ImportError) as exc:
        raise RuntimeError(
            "BNGIR v0.2 requires the structural compile snapshot support in this BNG3 build"
        ) from exc
    snapshot = dict(snapshot)
    raw_actions = list(snapshot.pop("actions", []))
    actions = [
        {
            "scope": act.get("scope", "model"),
            "name": act.get("name", ""),
            "arguments": {str(k): str(v) for k, v in act.get("arguments", {}).items()},
        }
        for act in raw_actions
    ]
    metadata = dict(snapshot.pop("metadata", {}))
    model_snapshot = {"metadata": metadata, **snapshot}
    # _cpp._compiled_snapshot may omit rule-level execution metadata that is
    # losslessly available from the native model; enrich so v0.2 round trips
    # preserve driving work and other explicitly serialized rule semantics.
    for barrier in model_snapshot.get("barrier_patterns", []):
        if isinstance(barrier, Mapping) and isinstance(
            barrier.get("expression"), Mapping
        ):
            barrier["expression"] = _expression_v02(
                barrier["expression"], model_snapshot
            )
    native_rules = list(getattr(native, "reaction_rules", []))
    for index, rule in enumerate(model_snapshot.get("rules", [])):
        if not isinstance(rule, Mapping) or index >= len(native_rules):
            continue
        native_rule = native_rules[index]
        if getattr(native_rule, "has_driving_work", False):
            driving_work = getattr(native_rule, "driving_work", "")
            if driving_work:
                rule["driving_work"] = driving_work
        if getattr(native_rule, "is_non_consuming", False):
            rule["non_consuming"] = True
    result = {
        "format": FORMAT,
        "version": STRUCTURAL_VERSION,
        "features": _features_v02({**model_snapshot, "actions": actions}),
        "model": model_snapshot,
        "protocol": {"actions": actions},
    }
    # Writer/reader closure: every 0.2 document must pass the reader's own
    # validation, so to_bngir refuses anything from_bngir would refuse instead
    # of emitting a document that cannot be read back.
    _load_document_v02(result)
    if provenance is not None:
        result["provenance"] = dict(provenance)
    return result


def to_bngir(
    model: Any,
    *,
    provenance: Mapping[str, Any] | None = None,
    version: str = DEFAULT_VERSION,
) -> str:
    """Return deterministic BNGIR JSON.

    ``version="0.1"`` retains the original string-oriented interchange format.
    ``version="0.2"`` serializes the resolved compile model with structural
    patterns, expression trees, rule mappings, and transformation programs.
    """

    if version == VERSION and getattr(model, "_native_bngir_v02_only", False):
        raise ValueError(
            "native BNGIR v0.2 imports cannot be exported as v0.1 because their "
            "source pattern text is intentionally unavailable"
        )
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
    unit_defaults = model.get("unit_defaults") or {}
    unit_definitions = model.get("unit_definitions") or []
    if unit_defaults or unit_definitions:
        lines += ["begin units"]
        for role in sorted(unit_defaults):
            lines.append(f"  {role} = {unit_defaults[role]}")
        for defn in unit_definitions:
            if isinstance(defn, Mapping):
                name = defn.get("name", defn.get("id"))
                expression = defn.get("expression")
                if isinstance(name, str) and name and isinstance(expression, str):
                    lines.append(f"  unit {name} = {expression}")
        lines += ["end units"]
    parameters = model.get("parameters", [])
    if parameters:
        lines += ["begin parameters"]
        lines += [
            f"  {item['name']} {item['expression']}"
            + (f" [{item['unit']}]" if item.get("unit") else "")
            for item in parameters
        ]
        lines += ["end parameters"]
    compartments = model.get("compartments", [])
    if compartments:
        lines += ["begin compartments"]
        for item in compartments:
            suffix = f" {item.get('parent', '')}" if item.get("parent") else ""
            unit_suffix = f" [{item['unit']}]" if item.get("unit") else ""
            lines.append(
                f"  {item['name']} {int(item['dimension'])} {item['volume']}{suffix}{unit_suffix}"
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
            unit_suffix = f" [{item['unit']}]" if item.get("unit") else ""
            lines.append(f"  {pattern} {item['amount']}{unit_suffix}")
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
    barrier_patterns = model.get("barrier_patterns", [])
    if barrier_patterns:
        # Must follow energy patterns: a barrier is only legal in a model that
        # has a dG for it to modify.
        lines += ["begin barrier patterns"]
        for item in barrier_patterns:
            label = f"{item['label']}: " if item.get("label") else ""
            arrow = "<->" if item.get("bidirectional") else "->"
            reactants = " + ".join(item.get("reactants", [])) or "0"
            products = " + ".join(item.get("products", [])) or "0"
            lines.append(
                f"  {label}{reactants} {arrow} {products} {item['expression']}"
            )
        lines += ["end barrier patterns"]
    population_maps = model.get("population_maps", [])
    if population_maps:
        lines += ["begin population maps"]
        for item in population_maps:
            if not item.get("rate"):
                raise ValueError(
                    "BNGIR v0.1 population map is missing rate; "
                    "lossless population map deserialization requires an explicit rate"
                )
            label = f"{item['label']}: " if item.get("label") else ""
            args = ",".join(item.get("args", []))
            rate = item["rate"]
            line = f"  {label}{item['pattern']} -> {item['function']}({args}) {rate}"
            if item.get("total_rate", False):
                line += " TotalRate"
            lines.append(line)
        lines += ["end population maps"]

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
            if item.get("delay"):
                line += f" delay={item['delay']}"
            if item.get("non_consuming"):
                line += " NonConsuming"
            if item.get("modifiers"):
                line += " " + " ".join(item["modifiers"])
            # Reservoir work is kinetics, not annotation: dropping it would
            # silently turn a driven model into an equilibrium one.
            if item.get("driving_work"):
                line += f" driven_by({item['driving_work']})"
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


def _validate_document_properties(root: Mapping[str, Any]) -> None:
    """Reject unknown document and model properties while allowing provenance."""
    allowed = {"format", "version", "features", "model", "protocol", "provenance"}
    unexpected = sorted(str(key) for key in root if key not in allowed)
    if unexpected:
        raise ValueError(
            f"BNGIR document has unsupported properties: {', '.join(unexpected)}"
        )

    features = _require_mapping(root.get("features"), "features")
    unexpected_features = sorted(
        str(key) for key in features if key not in {"required", "used"}
    )
    if unexpected_features:
        raise ValueError(
            "BNGIR features has unsupported properties: "
            f"{', '.join(unexpected_features)}"
        )

    protocol = _require_mapping(root.get("protocol", {}), "protocol")
    unexpected_protocol = sorted(str(key) for key in protocol if key not in {"actions"})
    if unexpected_protocol:
        raise ValueError(
            "BNGIR protocol has unsupported properties: "
            f"{', '.join(unexpected_protocol)}"
        )
    for index, raw_action in enumerate(protocol.get("actions", [])):
        action = _require_mapping(raw_action, f"protocol.actions[{index}]")
        unexpected_action = sorted(
            str(key) for key in action if key not in {"scope", "name", "arguments"}
        )
        if unexpected_action:
            raise ValueError(
                f"BNGIR protocol.actions[{index}] has unsupported properties: "
                f"{', '.join(unexpected_action)}"
            )

    if root["version"] == VERSION:
        model_allowed = {
            "name",
            "version",
            "substance_units",
            "options",
            "parameters",
            "molecule_types",
            "compartments",
            "seeds",
            "observables",
            "functions",
            "energy_patterns",
            "barrier_patterns",
            "population_maps",
            "rules",
            "unit_defaults",
            "unit_definitions",
        }
    else:
        model_allowed = {
            "metadata",
            "parameters",
            "molecule_types",
            "compartments",
            "seeds",
            "observables",
            "functions",
            "energy_patterns",
            "barrier_patterns",
            "population_types",
            "population_maps",
            "rules",
        }
    model = _require_mapping(root.get("model"), "model")
    unexpected_model = sorted(str(key) for key in model if key not in model_allowed)
    if unexpected_model:
        properties = ", ".join(unexpected_model)
        raise ValueError(f"BNGIR model has unsupported properties: {properties}")


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
        if not isinstance(symbol_kind, str) or not _is_json_integer(symbol_id):
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
        if not _is_json_integer(value) or value < 0:
            raise ValueError(f"BNGIR {where} has invalid reactant_index")
        if reactant_count is not None and value >= reactant_count:
            raise ValueError(f"BNGIR {where} reactant_index is out of range: {value}")
    elif kind == "builtin_call":
        builtin = expression.get("builtin")
        if builtin not in _KNOWN_BUILTINS:
            raise ValueError(f"BNGIR {where} has unsupported builtin: {builtin!r}")
    elif kind in {"number", "time_ref", "unary", "binary", "table_function"}:
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


def _is_json_integer(value: Any) -> bool:
    """Accept integer references while excluding JSON booleans."""
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_pattern_v02(
    pattern: Mapping[str, Any], model: Mapping[str, Any], where: str
) -> None:
    pattern = _require_mapping(pattern, where)
    molecule_types = _section_id_map(model, "molecule_types")
    compartments = _section_id_map(model, "compartments")
    compartment_names = {
        str(item.get("name")): cid
        for cid, item in compartments.items()
        if isinstance(item.get("name"), str)
    }
    molecules = pattern.get("molecules", [])
    if not isinstance(molecules, list):
        raise ValueError(f"BNGIR {where}.molecules must be an array")
    pattern_compartment = pattern.get("compartment")
    if pattern_compartment is not None:
        if (
            not isinstance(pattern_compartment, str)
            or pattern_compartment not in compartment_names
        ):
            raise ValueError(
                f"BNGIR {where} references unknown compartment: {pattern_compartment!r}"
            )
    pattern_compartment_id = pattern.get("compartment_id")
    if pattern_compartment_id is not None and (
        not _is_json_integer(pattern_compartment_id)
        or pattern_compartment_id not in compartments
    ):
        raise ValueError(f"BNGIR {where} references unknown graph compartment id")
    if pattern_compartment is not None and pattern_compartment_id is not None:
        if compartment_names[pattern_compartment] != pattern_compartment_id:
            raise ValueError(f"BNGIR {where} compartment name/id disagree")
    seen_occurrences: set[int] = set()
    for mi, raw_molecule in enumerate(molecules):
        molecule = _require_mapping(raw_molecule, f"{where}.molecules[{mi}]")
        occurrence = molecule.get("occurrence", mi)
        if (
            not _is_json_integer(occurrence)
            or occurrence < 0
            or occurrence in seen_occurrences
        ):
            raise ValueError(f"BNGIR {where} has invalid/duplicate molecule occurrence")
        seen_occurrences.add(occurrence)
        type_id = molecule.get("type_id")
        declaration = None
        if type_id is not None:
            if not _is_json_integer(type_id) or type_id not in molecule_types:
                raise ValueError(
                    f"BNGIR {where} references unknown molecule type id: {type_id}"
                )
            declaration = molecule_types[type_id]
            if molecule.get("type") != declaration.get("name"):
                raise ValueError(f"BNGIR {where} molecule type name/id disagree")
        molecule_compartment = molecule.get("compartment")
        if molecule_compartment is not None:
            if (
                not isinstance(molecule_compartment, str)
                or molecule_compartment not in compartment_names
            ):
                raise ValueError(
                    f"BNGIR {where} references unknown compartment: {molecule_compartment!r}"
                )
        compartment_id = molecule.get("compartment_id")
        if compartment_id is not None and (
            not _is_json_integer(compartment_id) or compartment_id not in compartments
        ):
            raise ValueError(
                f"BNGIR {where} references unknown compartment id: {compartment_id}"
            )
        if molecule_compartment is not None and compartment_id is not None:
            if compartment_names[molecule_compartment] != compartment_id:
                raise ValueError(f"BNGIR {where} molecule compartment name/id disagree")
        components = declaration.get("components", []) if declaration else []
        for si, raw_site in enumerate(molecule.get("sites", [])):
            site = _require_mapping(raw_site, f"{where}.molecules[{mi}].sites[{si}]")
            component_index = site.get("component_index")
            component_decl = None
            if component_index is not None and declaration is not None:
                if not _is_json_integer(component_index) or component_index < 0:
                    raise ValueError(f"BNGIR {where} has invalid component index")
                component_decl = next(
                    (
                        c
                        for c in components
                        if _is_json_integer(c.get("index"))
                        and c["index"] == component_index
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
                    not _is_json_integer(state_index)
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
                        not _is_json_integer(state_index)
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
    if not _is_json_integer(pi) or pi < 0 or pi >= len(patterns):
        raise ValueError(f"BNGIR {where} pattern reference is out of range")
    molecules = _require_mapping(patterns[pi], f"{where}.pattern").get("molecules", [])
    if not _is_json_integer(mi) or mi < 0 or mi >= len(molecules):
        raise ValueError(f"BNGIR {where} molecule reference is out of range")
    if site:
        si = ref.get("site")
        sites = _require_mapping(molecules[mi], f"{where}.molecule").get("sites", [])
        if not _is_json_integer(si) or si < 0 or si >= len(sites):
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
        if not _is_json_integer(pi) or pi < 0 or pi >= len(reactants):
            raise ValueError(
                f"BNGIR {where} local scope reactant pattern is out of range"
            )
        occurrence = scope.get("molecule_occurrence")
        if kind == "molecule":
            molecules = _require_mapping(reactants[pi], f"{where}.reactants[{pi}]").get(
                "molecules", []
            )
            if (
                not _is_json_integer(occurrence)
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
        if (
            patterns is None
            or not _is_json_integer(pi)
            or pi < 0
            or pi >= len(patterns)
        ):
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


# Rule modifiers that render verbatim in BNGL rule lines.
_PLAIN_RULE_MODIFIERS = frozenset(
    {"delete_molecules", "move_connected", "match_once", "total_rate"}
)
# Include/exclude modifiers serialize through direction.filters; each kind maps
# to the (include, side) pair of the filter that carries it.
_FILTER_MODIFIER_SIDES = {
    "include_reactants": (True, "reactant"),
    "exclude_reactants": (False, "reactant"),
    "include_products": (True, "product"),
    "exclude_products": (False, "product"),
}


def _require_optional_unit_v02(item: Mapping[str, Any], where: str) -> None:
    unit = item.get("unit")
    if unit is not None and (not isinstance(unit, str) or not unit):
        raise ValueError(f"BNGIR {where}.unit must be a non-empty string")


def _validate_metadata_v02(metadata: Mapping[str, Any]) -> None:
    unit_defaults = metadata.get("unit_defaults", {})
    if not isinstance(unit_defaults, Mapping):
        raise ValueError("BNGIR model.metadata.unit_defaults must be an object")
    for role, unit in unit_defaults.items():
        if (
            not isinstance(role, str)
            or role not in _UNIT_DEFAULT_ROLES
            or not isinstance(unit, str)
            or not unit
        ):
            raise ValueError(
                f"BNGIR model.metadata.unit_defaults has unsupported role: {role!r}"
            )
    unit_definitions = metadata.get("unit_definitions", [])
    if not isinstance(unit_definitions, list):
        raise ValueError("BNGIR model.metadata.unit_definitions must be an array")
    for i, raw_definition in enumerate(unit_definitions):
        definition = _require_mapping(
            raw_definition, f"model.metadata.unit_definitions[{i}]"
        )
        # A builtin definition is provided by the standard unit vocabulary on
        # read-back; the wire form only carries authored definitions, so a
        # builtin entry cannot be reconstructed and must be refused.
        if definition.get("builtin"):
            raise ValueError(
                f"BNGIR model.metadata.unit_definitions[{i}] is a builtin definition"
            )
        identifier = definition.get("id")
        expression_text = definition.get("expression")
        if (
            not isinstance(identifier, str)
            or not identifier
            or not isinstance(expression_text, str)
            or not expression_text
        ):
            raise ValueError(f"BNGIR model.metadata.unit_definitions[{i}] is malformed")


def _validate_model_v02(model: Mapping[str, Any]) -> None:
    # Construct ID maps up front to catch duplicate IDs even when unreferenced.
    for section in (
        "parameters",
        "molecule_types",
        "compartments",
        "observables",
        "functions",
        "energy_patterns",
        "barrier_patterns",
        "population_types",
        "rules",
    ):
        _section_id_map(model, section)
    _validate_metadata_v02(
        _require_mapping(model.get("metadata", {}), "model.metadata")
    )
    for i, parameter in enumerate(model.get("parameters", [])):
        parameter = _require_mapping(parameter, f"model.parameters[{i}]")
        _require_optional_unit_v02(parameter, f"model.parameters[{i}]")
        _validate_expression_v02(
            _require_mapping(parameter.get("expression"), "parameter expression"),
            model,
            local_names=set(),
            where=f"model.parameters[{i}].expression",
        )
    for i, compartment in enumerate(model.get("compartments", [])):
        compartment = _require_mapping(compartment, f"model.compartments[{i}]")
        _require_optional_unit_v02(compartment, f"model.compartments[{i}]")
    for i, seed in enumerate(model.get("seeds", [])):
        seed = _require_mapping(seed, f"model.seeds[{i}]")
        _require_optional_unit_v02(seed, f"model.seeds[{i}]")
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
        kind = observable.get("kind")
        if kind not in {"molecules", "species", "counter"}:
            raise ValueError(
                f"BNGIR model.observables[{i}] has unsupported observable kind: {kind!r}"
            )
        for j, term in enumerate(observable.get("terms", [])):
            term = _require_mapping(term, f"model.observables[{i}].terms[{j}]")
            pattern = _require_mapping(term.get("pattern"), "observable pattern")
            _validate_pattern_v02(
                pattern,
                model,
                f"model.observables[{i}].terms[{j}].pattern",
            )
            relation = term.get("relation")
            if relation is None:
                continue
            if relation not in {"==", "!=", ">", ">=", "<", "<="}:
                raise ValueError(
                    f"BNGIR model.observables[{i}].terms[{j}] has unsupported "
                    f"count relation: {relation!r}"
                )
            if not _is_json_integer(term.get("quantity")):
                raise ValueError(
                    f"BNGIR model.observables[{i}].terms[{j}].quantity must be an integer"
                )
            if relation == ">":
                # species_def '>' count filters accept any pattern shape.
                continue
            # BNGL only spells count restrictions other than '>' after a bare
            # molecule name, so anything richer cannot round-trip.
            molecules = pattern.get("molecules", [])
            if (
                len(molecules) != 1
                or _require_mapping(molecules[0], "observable molecule").get("sites")
                or pattern.get("compartment")
                or molecules[0].get("compartment")
                or not isinstance(molecules[0].get("type"), str)
                or not molecules[0].get("type")
            ):
                raise ValueError(
                    f"BNGIR model.observables[{i}].terms[{j}] count relation "
                    f"{relation!r} requires a bare molecule pattern"
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
    for i, barrier in enumerate(model.get("barrier_patterns", [])):
        barrier = _require_mapping(barrier, f"model.barrier_patterns[{i}]")
        label = barrier.get("label", "")
        if not isinstance(label, str):
            raise ValueError(
                f"BNGIR model.barrier_patterns[{i}].label must be a string"
            )
        # The wire form carries the backing transition as text (its schema
        # shape), not as reactant/product pattern lists.
        transition = barrier.get("transition")
        if not isinstance(transition, str) or "->" not in transition:
            raise ValueError(
                f"BNGIR model.barrier_patterns[{i}].transition must be a reaction transition"
            )
        expression_text = barrier.get("expression")
        if not isinstance(expression_text, str) or not expression_text:
            raise ValueError(
                f"BNGIR model.barrier_patterns[{i}].expression must be a non-empty string"
            )
        if barrier.get("center_resolved") is not True:
            raise ValueError(
                f"BNGIR model.barrier_patterns[{i}] {label!r} does not carry "
                "a resolved reaction center"
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
        if not _is_json_integer(population_id) or population_id not in population_types:
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
        if "total_rate" in mapping and type(mapping["total_rate"]) is not bool:
            raise ValueError(
                f"BNGIR model.population_maps[{i}].total_rate must be boolean"
            )

    for i, rule in enumerate(model.get("rules", [])):
        rule = _require_mapping(rule, f"model.rules[{i}]")
        forward = _require_mapping(rule.get("forward"), "rule.forward")
        _validate_direction_v02(forward, model, f"model.rules[{i}].forward")
        reverse = rule.get("reverse")
        if reverse is not None and not rule.get("bidirectional"):
            raise ValueError(
                f"BNGIR model.rules[{i}] carries a reverse direction on a "
                "non-bidirectional rule"
            )
        if reverse is not None:
            reverse = _require_mapping(reverse, "rule.reverse")
            _validate_direction_v02(reverse, model, f"model.rules[{i}].reverse")
        driving_work = rule.get("driving_work")
        if driving_work is not None:
            if isinstance(driving_work, str):
                if not driving_work.strip():
                    raise ValueError(
                        f"BNGIR model.rules[{i}].driving_work must be a non-empty string"
                    )
            elif isinstance(driving_work, Mapping):
                _validate_expression_v02(
                    driving_work,
                    model,
                    local_names=set(),
                    where=f"model.rules[{i}].driving_work",
                )
            else:
                raise ValueError(
                    f"BNGIR model.rules[{i}].driving_work must be a string or expression object"
                )
        driving_work = rule.get("driving_work")
        if driving_work is not None:
            if isinstance(driving_work, str):
                if not driving_work.strip():
                    raise ValueError(
                        f"BNGIR model.rules[{i}].driving_work must be a non-empty string"
                    )
            elif isinstance(driving_work, Mapping):
                _validate_expression_v02(
                    driving_work,
                    model,
                    local_names=set(),
                    where=f"model.rules[{i}].driving_work",
                )
            else:
                raise ValueError(
                    f"BNGIR model.rules[{i}].driving_work must be a string or expression object"
                )
        # Include/exclude modifiers are rendered from direction.filters; a
        # modifier without its matching filter would be dropped silently.
        filters = list(forward.get("filters", []))
        if reverse is not None:
            filters += list(reverse.get("filters", []))
        for j, raw_modifier in enumerate(rule.get("modifiers", [])):
            modifier = _require_mapping(
                raw_modifier, f"model.rules[{i}].modifiers[{j}]"
            )
            kind = modifier.get("kind")
            if kind in _PLAIN_RULE_MODIFIERS:
                continue
            if kind == "unknown":
                raise ValueError(f"BNGIR model.rules[{i}].modifiers[{j}] is unresolved")
            if kind in _FILTER_MODIFIER_SIDES:
                include, side = _FILTER_MODIFIER_SIDES[kind]
                if not any(
                    isinstance(candidate, Mapping)
                    and bool(candidate.get("include")) is include
                    and candidate.get("side") == side
                    for candidate in filters
                ):
                    raise ValueError(
                        f"BNGIR model.rules[{i}].modifiers[{j}] {kind!r} has no "
                        "matching filter"
                    )
                continue
            raise ValueError(
                f"BNGIR model.rules[{i}] has unsupported modifier kind: {kind!r}"
            )
        if "non_consuming" in rule:
            if not isinstance(rule["non_consuming"], bool):
                raise ValueError(
                    f"BNGIR model.rules[{i}].non_consuming must be boolean"
                )
            if rule["non_consuming"] and "delay" not in rule:
                raise ValueError(
                    f"BNGIR model.rules[{i}] NonConsuming requires delay expression"
                )
        if "delay" in rule:
            _validate_expression_v02(
                _require_mapping(rule["delay"], f"model.rules[{i}].delay"),
                model,
                local_names=set(),
                where=f"model.rules[{i}].delay",
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


def _native_exact_keys(value: Mapping[str, Any], keys: set[str], where: str) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted((str(key) for key in actual - keys))
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unsupported {', '.join(extra)}")
        raise ValueError(f"native BNGIR {where} has {'; '.join(details)}")


def _native_required_optional_keys(
    value: Mapping[str, Any], required: set[str], allowed: set[str], where: str
) -> None:
    actual = set(value)
    missing = sorted(required - actual)
    extra = sorted(str(key) for key in actual - allowed)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unsupported {', '.join(extra)}")
        raise ValueError(f"native BNGIR {where} has {'; '.join(details)}")


def _is_native_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _native_expression_v02(
    expression: Mapping[str, Any],
    parameter_ids: set[int],
    where: str,
    *,
    local_names: frozenset[str] | None = None,
    function_ids: frozenset[int] = frozenset(),
    function_arities: Mapping[int, int] | None = None,
    observable_ids: frozenset[int] = frozenset(),
    allow_function_calls: bool = False,
) -> None:
    """Validate one expression of the native BNGIR v0.2 subset.

    ``local_names`` is ``None`` for a model-level expression and holds the
    arguments of the owning function for a function body. A local or an
    observable reference only has a meaning inside a function body, so the
    two contexts accept different expression kinds. A function call is only
    accepted where a rate law may name a model function.
    """
    expression = _require_mapping(expression, where)
    kind = expression.get("kind")
    if kind == "number":
        _native_exact_keys(expression, {"kind", "value"}, where)
        value = expression["value"]
        if not _is_native_finite_number(value):
            raise ValueError(f"native BNGIR {where}.value must be finite")
        return
    if kind == "parameter_ref":
        _native_exact_keys(expression, {"kind", "symbol"}, where)
        symbol = _require_mapping(expression["symbol"], f"{where}.symbol")
        _native_exact_keys(symbol, {"kind", "index"}, f"{where}.symbol")
        index = symbol["index"]
        if (
            symbol["kind"] != "parameter"
            or isinstance(index, bool)
            or not isinstance(index, int)
            or index not in parameter_ids
        ):
            raise ValueError(f"native BNGIR {where} references an unknown parameter id")
        return
    if kind == "local_ref":
        if local_names is None:
            raise ValueError(
                f"native BNGIR {where} kind 'local_ref' is outside the supported "
                "expression subset"
            )
        _native_exact_keys(expression, {"kind", "name"}, where)
        name = expression["name"]
        if not isinstance(name, str) or name not in local_names:
            raise ValueError(
                f"native BNGIR {where} references an unknown function argument"
            )
        return
    if kind == "function_ref":
        if not allow_function_calls:
            raise ValueError(f"native BNGIR {where} does not support a function call")
        _native_required_optional_keys(
            expression,
            {"kind", "symbol"},
            {"kind", "symbol", "call", "arguments"},
            where,
        )
        symbol = _require_mapping(expression["symbol"], f"{where}.symbol")
        _native_exact_keys(symbol, {"kind", "index"}, f"{where}.symbol")
        index = symbol["index"]
        if (
            symbol["kind"] != "function"
            or isinstance(index, bool)
            or not isinstance(index, int)
            or index not in function_ids
        ):
            raise ValueError(f"native BNGIR {where} references an unknown function id")
        call = expression.get("call", False)
        if not isinstance(call, bool):
            raise ValueError(f"native BNGIR {where}.call must be boolean")
        args = expression.get("arguments", [])
        if not isinstance(args, list):
            raise ValueError(f"native BNGIR {where}.arguments must be an array")
        if call and function_arities is not None:
            if len(args) != function_arities[index]:
                raise ValueError(
                    f"native BNGIR {where} calls a function with a different arity"
                )
        if not call and args:
            raise ValueError(f"native BNGIR {where} arguments require a call")
        for argument_index, argument in enumerate(args):
            _native_expression_v02(
                argument,
                parameter_ids,
                f"{where}.arguments[{argument_index}]",
                local_names=local_names,
                function_ids=function_ids,
                function_arities=function_arities,
                observable_ids=observable_ids,
                allow_function_calls=allow_function_calls,
            )
        return
    if kind == "observable_ref":
        if local_names is None:
            raise ValueError(
                f"native BNGIR {where} kind 'observable_ref' is outside the supported "
                "expression subset"
            )
        _native_required_optional_keys(
            expression,
            {"kind", "symbol"},
            {"kind", "symbol", "call", "arguments"},
            where,
        )
        symbol = _require_mapping(expression["symbol"], f"{where}.symbol")
        _native_exact_keys(symbol, {"kind", "index"}, f"{where}.symbol")
        index = symbol["index"]
        if (
            symbol["kind"] != "observable"
            or isinstance(index, bool)
            or not isinstance(index, int)
            or index not in observable_ids
        ):
            raise ValueError(
                f"native BNGIR {where} references an unknown observable id"
            )
        call = expression.get("call", False)
        if not isinstance(call, bool):
            raise ValueError(f"native BNGIR {where}.call must be boolean")
        args = expression.get("arguments", [])
        if not isinstance(args, list):
            raise ValueError(f"native BNGIR {where}.arguments must be an array")
        if args:
            raise ValueError(
                f"native BNGIR {where} does not support a scoped observable"
            )
        return
    if kind == "unary":
        _native_exact_keys(expression, {"kind", "operator", "arguments"}, where)
        operator = expression["operator"]
        if not isinstance(operator, str) or operator not in {"plus", "negate"}:
            raise ValueError(f"native BNGIR {where} has unsupported unary operator")
        args = expression["arguments"]
        if not isinstance(args, list) or len(args) != 1:
            raise ValueError(f"native BNGIR {where} must have one argument")
        _native_expression_v02(
            args[0],
            parameter_ids,
            f"{where}.arguments[0]",
            local_names=local_names,
            function_ids=function_ids,
            function_arities=function_arities,
            observable_ids=observable_ids,
            allow_function_calls=allow_function_calls,
        )
        return
    if kind == "binary":
        _native_exact_keys(expression, {"kind", "operator", "arguments"}, where)
        operator = expression["operator"]
        if not isinstance(operator, str) or operator not in {
            "add",
            "subtract",
            "multiply",
            "divide",
            "power",
        }:
            raise ValueError(f"native BNGIR {where} has unsupported binary operator")
        args = expression["arguments"]
        if not isinstance(args, list) or len(args) != 2:
            raise ValueError(f"native BNGIR {where} must have two arguments")
        for index, argument in enumerate(args):
            _native_expression_v02(
                argument,
                parameter_ids,
                f"{where}.arguments[{index}]",
                local_names=local_names,
                function_ids=function_ids,
                function_arities=function_arities,
                observable_ids=observable_ids,
                allow_function_calls=allow_function_calls,
            )
        return
    raise ValueError(
        f"native BNGIR {where} kind {kind!r} is outside the supported expression subset"
    )


def _native_pattern_v02(
    pattern: Mapping[str, Any],
    where: str,
    molecule_ids: set[int],
    molecule_types: Mapping[int, Mapping[str, Any]],
    *,
    require_complete: bool = False,
) -> None:
    pattern = _require_mapping(pattern, where)
    _native_required_optional_keys(
        pattern,
        {"compartment_prefix", "molecules"},
        {"compartment", "compartment_prefix", "molecules"},
        where,
    )
    if not isinstance(pattern["compartment_prefix"], bool):
        raise ValueError(f"native BNGIR {where} compartment_prefix must be boolean")
    if (
        pattern["compartment_prefix"] is not False
        and pattern["compartment_prefix"] is not True
    ):
        raise ValueError(f"native BNGIR {where} compartment_prefix must be boolean")
    if "compartment" in pattern:
        if not isinstance(pattern["compartment"], str) or not pattern["compartment"]:
            raise ValueError(
                f"native BNGIR {where} compartment must be a nonempty string"
            )
    molecules = pattern["molecules"]
    if not isinstance(molecules, list) or not molecules:
        raise ValueError(
            f"native BNGIR {where} requires exactly one molecule or a bonded complex"
        )
    exact_bond_groups: dict[int, list[tuple[int, int]]] = {}
    for molecule_index, raw_molecule in enumerate(molecules):
        molecule = _require_mapping(
            raw_molecule, f"{where}.molecules[{molecule_index}]"
        )
        _native_required_optional_keys(
            molecule,
            {"occurrence", "sites", "type", "type_id"},
            {"compartment", "compartment_id", "occurrence", "sites", "type", "type_id"},
            f"{where}.molecules[{molecule_index}]",
        )
        if "compartment" in molecule and (
            not isinstance(molecule["compartment"], str) or not molecule["compartment"]
        ):
            raise ValueError(
                f"native BNGIR {where}.molecules[{molecule_index}].compartment must be a nonempty string"
            )
        if "compartment_id" in molecule:
            compartment_id = molecule["compartment_id"]
            if (
                isinstance(compartment_id, bool)
                or not isinstance(compartment_id, int)
                or compartment_id < 0
            ):
                raise ValueError(
                    f"native BNGIR {where}.molecules[{molecule_index}].compartment_id must be a nonnegative integer"
                )
        if (
            isinstance(molecule["occurrence"], bool)
            or not isinstance(molecule["occurrence"], int)
            or molecule["occurrence"] != molecule_index
        ):
            raise ValueError(f"native BNGIR {where} has an invalid molecule occurrence")
        type_id = molecule["type_id"]
        if (
            isinstance(type_id, bool)
            or not isinstance(type_id, int)
            or type_id not in molecule_ids
        ):
            raise ValueError(
                f"native BNGIR {where} references an unknown molecule type id"
            )
        if not isinstance(molecule["type"], str) or not molecule["type"]:
            raise ValueError(f"native BNGIR {where} has no molecule type name")
        molecule_type = molecule_types[type_id]
        if molecule["type"] != molecule_type["name"]:
            raise ValueError(
                f"native BNGIR {where} molecule type name does not match type_id"
            )
        sites = molecule["sites"]
        components = molecule_type["components"]
        if not isinstance(sites, list) or (
            len(sites) != len(components)
            if require_complete
            else len(sites) > len(components)
        ):
            raise ValueError(
                f"native BNGIR {where} site count does not match its molecule type"
            )
        seen_component_indices = set()
        for site_index, raw_site in enumerate(sites):
            site = _require_mapping(
                raw_site, f"{where}.molecules[{molecule_index}].sites[{site_index}]"
            )
            _native_required_optional_keys(
                site,
                {"occurrence", "component", "component_index", "state", "bond"},
                {
                    "occurrence",
                    "component",
                    "component_index",
                    "state",
                    "bond",
                    "label",
                },
                f"{where}.molecules[{molecule_index}].sites[{site_index}]",
            )
            comp_idx = site["component_index"]
            if (
                isinstance(comp_idx, bool)
                or not isinstance(comp_idx, int)
                or not (0 <= comp_idx < len(components))
                or comp_idx in seen_component_indices
            ):
                raise ValueError(
                    f"native BNGIR {where} has an out-of-slice site reference"
                )
            seen_component_indices.add(comp_idx)
            component = components[comp_idx]
            occ = site["occurrence"]
            if (
                isinstance(occ, bool)
                or not isinstance(occ, int)
                or occ < 0
                or site["component"] != component["name"]
                or site.get("label", "") != ""
            ):
                raise ValueError(
                    f"native BNGIR {where} has an out-of-slice site reference"
                )
            state = _require_mapping(
                site["state"],
                f"{where}.molecules[{molecule_index}].sites[{site_index}].state",
            )
            allowed_states = component["states"]
            if allowed_states:
                _native_exact_keys(
                    state,
                    {"kind", "value", "index"},
                    f"{where}.molecules[{molecule_index}].sites[{site_index}].state",
                )
                state_index = state["index"]
                if (
                    state["kind"] != "exact"
                    or isinstance(state_index, bool)
                    or not isinstance(state_index, int)
                    or not 0 <= state_index < len(allowed_states)
                    or state["value"] != allowed_states[state_index]
                ):
                    raise ValueError(
                        f"native BNGIR {where} has an unknown or inconsistent finite state"
                    )
            elif state != {"kind": "any"}:
                raise ValueError(
                    f"native BNGIR {where} binding-only site must have an any state constraint"
                )
            bond = _require_mapping(
                site["bond"],
                f"{where}.molecules[{molecule_index}].sites[{site_index}].bond",
            )
            if bond == {"kind": "unbound"}:
                continue
            if bond.get("kind") == "exact":
                _native_exact_keys(
                    bond,
                    {"kind", "group"},
                    f"{where}.molecules[{molecule_index}].sites[{site_index}].bond",
                )
                group = bond["group"]
                if isinstance(group, bool) or not isinstance(group, int) or group < 0:
                    raise ValueError(
                        f"native BNGIR {where} has an invalid exact bond group"
                    )
                exact_bond_groups.setdefault(group, []).append(
                    (molecule_index, comp_idx)
                )
                continue
            if bond in (
                {"kind": "bound"},
                {"kind": "any"},
                {"kind": "unspecified"},
            ):
                continue
            raise ValueError(f"native BNGIR {where} has an unsupported bond constraint")
    if any(
        len(endpoints) != 2 or endpoints[0][0] == endpoints[1][0]
        for endpoints in exact_bond_groups.values()
    ):
        raise ValueError(f"native BNGIR {where} has malformed bond endpoints")
    if len(molecules) > 1:
        parents = list(range(len(molecules)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        for endpoints in exact_bond_groups.values():
            left, right = (endpoint[0] for endpoint in endpoints)
            parents[find(left)] = find(right)
        if len({find(index) for index in range(len(molecules))}) != 1:
            raise ValueError(
                f"native BNGIR {where} requires exactly one molecule or a connected bonded complex"
            )


def _native_state_transition_v02(
    rule: Mapping[str, Any],
    direction: Mapping[str, Any],
    index: int,
    model: Mapping[str, Any],
    *,
    validate_mappings: bool = True,
) -> None:
    """Require the explicit one-site correspondence and mutation for this slice."""
    if model["compartments"]:
        raise ValueError(
            f"native BNGIR model.rules[{index}] state transitions do not support compartments"
        )
    reactants = direction["reactants"]
    products = direction["products"]
    if len(reactants) != 1 or len(products) != 1:
        raise ValueError(
            f"native BNGIR model.rules[{index}] state transitions require one reactant and product"
        )
    if any(
        not isinstance(pattern, Mapping)
        or not isinstance(pattern.get("molecules"), list)
        or len(pattern["molecules"]) != 1
        for pattern in (reactants[0], products[0])
    ):
        raise ValueError(
            f"native BNGIR model.rules[{index}] state transitions require one molecule per pattern"
        )
    reactant = reactants[0]["molecules"][0]
    product = products[0]["molecules"][0]
    for pattern in (reactants[0], products[0]):
        if pattern.get("compartment") or pattern["compartment_prefix"]:
            raise ValueError(
                f"native BNGIR model.rules[{index}] state transitions do not support compartments"
            )
    if any(
        "compartment" in molecule or "compartment_id" in molecule
        for molecule in (reactant, product)
    ):
        raise ValueError(
            f"native BNGIR model.rules[{index}] state transitions do not support compartments"
        )
    if reactant["type_id"] != product["type_id"]:
        raise ValueError(
            f"native BNGIR model.rules[{index}] state transition must preserve molecule type"
        )
    reactant_sites = reactant.get("sites", [])
    product_sites = product.get("sites", [])
    if len(reactant_sites) != len(product_sites) or not reactant_sites:
        raise ValueError(
            f"native BNGIR model.rules[{index}] state transition requires matching nonempty site counts"
        )
    mutations = direction["mutations"]
    if not isinstance(mutations, list) or len(mutations) != 1:
        raise ValueError(
            f"native BNGIR model.rules[{index}] state transition requires one change_state mutation"
        )
    mutation = _require_mapping(
        mutations[0], f"model.rules[{index}].forward.mutations[0]"
    )
    _native_exact_keys(
        mutation,
        {"kind", "source", "state", "state_index"},
        f"model.rules[{index}].forward.mutations[0]",
    )
    source = _require_mapping(
        mutation["source"], f"model.rules[{index}].forward.mutations[0].source"
    )
    _native_exact_keys(
        source,
        {"side", "pattern", "molecule", "site"},
        f"model.rules[{index}].forward.mutations[0].source",
    )
    target_site = source["site"]
    if (
        source["side"] != "reactant"
        or source["pattern"] != 0
        or source["molecule"] != 0
        or isinstance(target_site, bool)
        or not isinstance(target_site, int)
        or not (0 <= target_site < len(reactant_sites))
    ):
        raise ValueError(
            f"native BNGIR model.rules[{index}] has a contradictory state mutation reference"
        )
    before = reactant_sites[target_site]["state"]
    after = product_sites[target_site]["state"]
    if before["value"] == after["value"]:
        raise ValueError(
            f"native BNGIR model.rules[{index}] state transition must change the site state"
        )
    if (
        mutation["kind"] != "change_state"
        or mutation["state"] != after["value"]
        or isinstance(mutation["state_index"], bool)
        or not isinstance(mutation["state_index"], int)
        or mutation["state_index"] != after["index"]
    ):
        raise ValueError(
            f"native BNGIR model.rules[{index}] state mutation does not match its product state"
        )
    for s, (r, p) in enumerate(zip(reactant_sites, product_sites)):
        if s != target_site and (
            r.get("state") != p.get("state") or r.get("bond") != p.get("bond")
        ):
            raise ValueError(
                f"native BNGIR model.rules[{index}] state transition must preserve unmodified sites"
            )
    if validate_mappings:
        expected_molecule = {
            "product": {"side": "product", "pattern": 0, "molecule": 0},
            "reactant": {"side": "reactant", "pattern": 0, "molecule": 0},
        }
        if rule["molecule_mappings"] != [expected_molecule]:
            raise ValueError(
                f"native BNGIR model.rules[{index}] state transition requires its explicit molecule mapping"
            )
        expected_components = [
            {
                "product": {"side": "product", "pattern": 0, "molecule": 0, "site": s},
                "reactant": {
                    "side": "reactant",
                    "pattern": 0,
                    "molecule": 0,
                    "site": s,
                },
            }
            for s in range(len(reactant_sites))
        ]
        if rule["component_mappings"] != expected_components:
            raise ValueError(
                f"native BNGIR model.rules[{index}] state transition requires its explicit site mapping"
            )


def _native_bond_change_v02(
    rule: Mapping[str, Any],
    direction: Mapping[str, Any],
    index: int,
    model: Mapping[str, Any],
    *,
    validate_mappings: bool = True,
) -> None:
    """Validate a two-molecule association or dissociation correspondence."""
    where = f"model.rules[{index}]"
    if model["compartments"]:
        raise ValueError(
            f"native BNGIR {where} bond changes do not support compartments"
        )
    reactants, products = direction["reactants"], direction["products"]
    mutations = direction["mutations"]
    if len(mutations) != 1 or mutations[0].get("kind") not in {
        "add_bond",
        "delete_bond",
    }:
        raise ValueError(
            f"native BNGIR {where} bond changes require one add_bond or delete_bond mutation"
        )
    mutation_kind = mutations[0]["kind"]
    association = mutation_kind == "add_bond"
    if association:
        if (
            len(reactants) != 2
            or len(products) != 1
            or any(len(pattern["molecules"]) != 1 for pattern in reactants)
            or len(products[0]["molecules"]) != 2
        ):
            raise ValueError(
                f"native BNGIR {where} bond formation requires two one-molecule reactants and one two-molecule product"
            )
        reactant_molecules = [pattern["molecules"][0] for pattern in reactants]
        product_molecules = products[0]["molecules"]
    else:
        if (
            len(reactants) != 1
            or len(reactants[0]["molecules"]) != 2
            or len(products) != 2
            or any(len(pattern["molecules"]) != 1 for pattern in products)
        ):
            raise ValueError(
                f"native BNGIR {where} bond dissociation requires one two-molecule reactant and two one-molecule products"
            )
        reactant_molecules = reactants[0]["molecules"]
        product_molecules = [pattern["molecules"][0] for pattern in products]

    if any(
        pattern["compartment_prefix"] or "compartment" in pattern
        for pattern in (*reactants, *products)
    ) or any(
        "compartment" in molecule or "compartment_id" in molecule
        for pattern in (*reactants, *products)
        for molecule in pattern["molecules"]
    ):
        raise ValueError(
            f"native BNGIR {where} bond changes do not support compartments"
        )
    if [molecule["type_id"] for molecule in reactant_molecules] != [
        molecule["type_id"] for molecule in product_molecules
    ]:
        raise ValueError(
            f"native BNGIR {where} bond change must preserve molecule types"
        )
    for molecule in (*reactant_molecules, *product_molecules):
        if not isinstance(molecule.get("sites"), list) or not molecule["sites"]:
            raise ValueError(
                f"native BNGIR {where} bond changes require nonempty sites"
            )
    r_sites0 = reactant_molecules[0]["sites"]
    p_sites0 = product_molecules[0]["sites"]
    r_sites1 = reactant_molecules[1]["sites"]
    p_sites1 = product_molecules[1]["sites"]
    if len(r_sites0) != len(p_sites0) or len(r_sites1) != len(p_sites1):
        raise ValueError(f"native BNGIR {where} bond change site counts must match")

    mutation = mutations[0]
    source = _require_mapping(mutation.get("source"), f"{where}.mutation.source")
    partner = _require_mapping(mutation.get("partner"), f"{where}.mutation.partner")
    source_site = source.get("site", 0)
    partner_site = partner.get("site", 0)
    if (
        isinstance(source_site, bool)
        or not isinstance(source_site, int)
        or not (0 <= source_site < len(r_sites0))
        or isinstance(partner_site, bool)
        or not isinstance(partner_site, int)
        or not (0 <= partner_site < len(r_sites1))
    ):
        raise ValueError(f"native BNGIR {where} bond change site index out of range")

    def exact_bond_group(site: Mapping[str, Any]) -> int:
        bond = site.get("bond", {})
        if (
            bond.get("kind") != "exact"
            or isinstance(bond.get("group"), bool)
            or not isinstance(bond.get("group"), int)
            or bond["group"] < 0
        ):
            raise ValueError(f"native BNGIR {where} requires one explicit exact bond")
        return bond["group"]

    if association:
        if r_sites0[source_site].get("bond") != {"kind": "unbound"} or r_sites1[
            partner_site
        ].get("bond") != {"kind": "unbound"}:
            raise ValueError(
                f"native BNGIR {where} bond formation requires unbound reactant sites"
            )
        g0 = exact_bond_group(p_sites0[source_site])
        g1 = exact_bond_group(p_sites1[partner_site])
        if g0 != g1:
            raise ValueError(f"native BNGIR {where} bond endpoints do not correspond")
    else:
        g0 = exact_bond_group(r_sites0[source_site])
        g1 = exact_bond_group(r_sites1[partner_site])
        if g0 != g1:
            raise ValueError(f"native BNGIR {where} bond endpoints do not correspond")
        if p_sites0[source_site].get("bond") != {"kind": "unbound"} or p_sites1[
            partner_site
        ].get("bond") != {"kind": "unbound"}:
            raise ValueError(
                f"native BNGIR {where} bond dissociation requires unbound product sites"
            )

    for s, (r, p) in enumerate(zip(r_sites0, p_sites0)):
        if s != source_site and (
            r.get("state") != p.get("state") or r.get("bond") != p.get("bond")
        ):
            raise ValueError(
                f"native BNGIR {where} bond change must preserve unmodified sites"
            )
    for s, (r, p) in enumerate(zip(r_sites1, p_sites1)):
        if s != partner_site and (
            r.get("state") != p.get("state") or r.get("bond") != p.get("bond")
        ):
            raise ValueError(
                f"native BNGIR {where} bond change must preserve unmodified sites"
            )

    molecule_mappings = []
    component_mappings = []
    for molecule_index in range(2):
        reactant_pattern = 0 if not association else molecule_index
        reactant_molecule = molecule_index if not association else 0
        product_pattern = molecule_index if not association else 0
        product_molecule = 0 if not association else molecule_index
        molecule_mappings.append(
            {
                "product": {
                    "side": "product",
                    "pattern": product_pattern,
                    "molecule": product_molecule,
                },
                "reactant": {
                    "side": "reactant",
                    "pattern": reactant_pattern,
                    "molecule": reactant_molecule,
                },
            }
        )
        cur_sites = reactant_molecules[molecule_index]["sites"]
        for s in range(len(cur_sites)):
            component_mappings.append(
                {
                    "product": {
                        "side": "product",
                        "pattern": product_pattern,
                        "molecule": product_molecule,
                        "site": s,
                    },
                    "reactant": {
                        "side": "reactant",
                        "pattern": reactant_pattern,
                        "molecule": reactant_molecule,
                        "site": s,
                    },
                }
            )
    if validate_mappings:
        if rule["molecule_mappings"] != molecule_mappings:
            raise ValueError(
                f"native BNGIR {where} bond change has contradictory molecule mappings"
            )
        if rule["component_mappings"] != component_mappings:
            raise ValueError(
                f"native BNGIR {where} bond change has contradictory site mappings"
            )

    first = {"side": "reactant", "pattern": 0, "molecule": 0, "site": source_site}
    second = {
        "side": "reactant",
        "pattern": 0 if not association else 1,
        "molecule": 1 if not association else 0,
        "site": partner_site,
    }
    expected_mutation = {
        "kind": mutation_kind,
        "source": first,
        "partner": second,
    }
    if mutations != [expected_mutation]:
        raise ValueError(
            f"native BNGIR {where} has contradictory bond mutation endpoints"
        )


def _native_multi_pattern_direction_v02(
    rule: Mapping[str, Any],
    direction: Mapping[str, Any],
    index: int,
    model: Mapping[str, Any],
    molecule_ids: set[int],
) -> None:
    """Check a rule direction that rebuilds more than one pattern.

    The native importer rebuilds a direction from its patterns, and the pattern
    structure decides the rule's operations. A direction with more than one
    reactant or product pattern is only rebuilt faithfully when the document
    states the same operations: every reactant molecule deleted and every
    product molecule added, with no molecule carried over. Anything else is an
    explicit refusal rather than an approximation.
    """
    reactants = direction["reactants"]
    products = direction["products"]
    if len(reactants) <= 1 and len(products) <= 1:
        return
    if rule["molecule_mappings"] != []:
        raise ValueError(
            f"native BNGIR model.rules[{index}] carries a molecule mapping that "
            "a multi-pattern rule direction cannot rebuild"
        )
    expected = [
        ("delete_molecule", "reactant", pattern_index)
        for pattern_index in range(len(reactants))
    ] + [
        ("add_molecule", "product", pattern_index)
        for pattern_index in range(len(products))
    ]
    observed = [
        (
            mutation["kind"],
            mutation["molecule"]["side"],
            mutation["molecule"]["pattern"],
        )
        for mutation in direction["mutations"]
    ]
    if sorted(observed) != sorted(expected):
        raise ValueError(
            f"native BNGIR model.rules[{index}] mutations do not state the "
            "delete-and-add operations of a multi-pattern rule direction"
        )
    reactant_types = {pattern["molecules"][0]["type_id"] for pattern in reactants}
    for pattern in products:
        if pattern["molecules"][0]["type_id"] in reactant_types:
            raise ValueError(
                f"native BNGIR model.rules[{index}] has a product pattern whose "
                "molecule type matches a reactant pattern; the rule direction "
                "carries a transformation the native slice cannot rebuild"
            )


def _native_reversible_direction_v02(
    direction: Mapping[str, Any], index: int, direction_name: str
) -> None:
    """Require reversible directions to encode exact independent rewrites."""
    reactants = direction["reactants"]
    products = direction["products"]
    if not reactants or not products:
        raise ValueError(
            f"native BNGIR model.rules[{index}].{direction_name} reversible "
            "rules require reactant and product patterns"
        )
    for side, patterns in (("reactants", reactants), ("products", products)):
        for pattern_index, pattern in enumerate(patterns):
            molecules = pattern["molecules"]
            if len(molecules) != 1:
                raise ValueError(
                    f"native BNGIR model.rules[{index}].{direction_name}.{side}"
                    f"[{pattern_index}] must contain one molecule"
                )
    reactant_pattern_types = [
        pattern["molecules"][0]["type_id"] for pattern in reactants
    ]
    product_pattern_types = [pattern["molecules"][0]["type_id"] for pattern in products]
    if len(set(reactant_pattern_types)) != len(reactant_pattern_types) or len(
        set(product_pattern_types)
    ) != len(product_pattern_types):
        raise ValueError(
            f"native BNGIR model.rules[{index}].{direction_name} reversible "
            "rules do not support repeated molecule-type patterns"
        )
    reactant_types = set(reactant_pattern_types)
    product_types = set(product_pattern_types)
    if reactant_types & product_types:
        raise ValueError(
            f"native BNGIR model.rules[{index}].{direction_name} reversible "
            "rules cannot carry molecule types across directions"
        )
    observed = [
        (
            mutation["kind"],
            mutation["molecule"]["side"],
            mutation["molecule"]["pattern"],
        )
        for mutation in direction["mutations"]
    ]
    expected = [
        *(("delete_molecule", "reactant", i) for i in range(len(reactants))),
        *(("add_molecule", "product", i) for i in range(len(products))),
    ]
    if sorted(observed) != sorted(expected):
        raise ValueError(
            f"native BNGIR model.rules[{index}].{direction_name}.mutations do "
            "not state the delete-and-add operations represented by its patterns"
        )


def _validate_native_v02(root: Mapping[str, Any]) -> None:
    """Fail-closed input gate for the first graph-native compatibility slice."""
    _native_exact_keys(
        root, {"format", "version", "features", "model", "protocol"}, "document"
    )
    features = _require_mapping(root["features"], "features")
    _native_exact_keys(features, {"required", "used"}, "features")
    if features["required"] != ["structured_patterns", "structured_expressions"]:
        raise ValueError("native BNGIR requires the canonical structured feature set")

    model = _require_mapping(root["model"], "model")
    sections = {
        "metadata",
        "parameters",
        "molecule_types",
        "compartments",
        "seeds",
        "observables",
        "functions",
        "energy_patterns",
        "barrier_patterns",
        "population_maps",
        "population_types",
        "rules",
    }
    _native_exact_keys(model, sections, "model")
    for section in (
        "energy_patterns",
        "barrier_patterns",
        "population_maps",
        "population_types",
    ):
        if model[section] != []:
            raise ValueError(f"native BNGIR does not support model.{section}")

    metadata = _require_mapping(model["metadata"], "model.metadata")
    _native_exact_keys(
        metadata, {"name", "version", "substance_units", "options"}, "model.metadata"
    )
    for key in ("name", "version", "substance_units"):
        if not isinstance(metadata[key], str):
            raise ValueError(f"native BNGIR model.metadata.{key} must be a string")
    if metadata["substance_units"]:
        raise ValueError("native BNGIR does not support substance-unit metadata")
    options = _require_mapping(metadata["options"], "model.metadata.options")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in options.items()
    ):
        raise ValueError(
            "native BNGIR model.metadata.options must map strings to strings"
        )
    if "BNG3AbsoluteFluxRules" in options:
        raise ValueError(
            "native BNGIR does not support BNG3AbsoluteFluxRules metadata; "
            "use the BNGL import path to preserve absolute-flux rule semantics"
        )

    parameter_ids: set[int] = set()
    parameter_names: set[str] = set()
    if not isinstance(model["parameters"], list):
        raise ValueError("native BNGIR model.parameters must be an array")
    for index, raw in enumerate(model["parameters"]):
        parameter = _require_mapping(raw, f"model.parameters[{index}]")
        _native_required_optional_keys(
            parameter,
            {"id", "name", "expression"},
            {"id", "name", "expression", "constant_value"},
            f"model.parameters[{index}]",
        )
        if (
            isinstance(parameter["id"], bool)
            or not isinstance(parameter["id"], int)
            or parameter["id"] != index
        ):
            raise ValueError("native BNGIR parameter ids must be dense and ordered")
        name = parameter["name"]
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name)
            or name in parameter_names
        ):
            raise ValueError(
                f"native BNGIR parameter name is invalid or duplicated: {name!r}"
            )
        parameter_ids.add(index)
        parameter_names.add(name)
    for index, parameter in enumerate(model["parameters"]):
        _native_expression_v02(
            parameter["expression"],
            parameter_ids,
            f"model.parameters[{index}].expression",
        )
        if "constant_value" in parameter:
            value = parameter["constant_value"]
            if not _is_native_finite_number(value):
                raise ValueError(
                    f"native BNGIR model.parameters[{index}].constant_value must be finite"
                )

    molecule_ids: set[int] = set()
    molecule_names: set[str] = set()
    molecule_types_by_id: dict[int, Mapping[str, Any]] = {}
    binding_only_type_ids: set[int] = set()
    if not isinstance(model["molecule_types"], list):
        raise ValueError("native BNGIR model.molecule_types must be an array")
    for index, raw in enumerate(model["molecule_types"]):
        molecule = _require_mapping(raw, f"model.molecule_types[{index}]")
        _native_exact_keys(
            molecule,
            {"id", "name", "population", "components"},
            f"model.molecule_types[{index}]",
        )
        name = molecule["name"]
        if (
            isinstance(molecule["id"], bool)
            or not isinstance(molecule["id"], int)
            or molecule["id"] != index
        ):
            raise ValueError("native BNGIR molecule type ids must be dense and ordered")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name)
            or name in molecule_names
        ):
            raise ValueError(
                f"native BNGIR molecule type name is invalid or duplicated: {name!r}"
            )
        if molecule["population"] is not False:
            raise ValueError(
                f"native BNGIR molecule type {name!r} must be an ordinary molecule type"
            )
        components = molecule["components"]
        if not isinstance(components, list):
            raise ValueError(
                f"native BNGIR molecule type {name!r} components must be a list"
            )
        seen_component_names = set()
        has_finite_state = False
        has_binding_only = False
        for comp_idx, raw_comp in enumerate(components):
            component = _require_mapping(
                raw_comp, f"model.molecule_types[{index}].components[{comp_idx}]"
            )
            _native_exact_keys(
                component,
                {"index", "name", "states"},
                f"model.molecule_types[{index}].components[{comp_idx}]",
            )
            component_name = component["name"]
            states = component["states"]
            if isinstance(states, list) and not states:
                has_binding_only = True
            elif isinstance(states, list) and states:
                has_finite_state = True
            if (
                component["index"] != comp_idx
                or isinstance(component["index"], bool)
                or not isinstance(component_name, str)
                or re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", component_name) is None
                or component_name in seen_component_names
                or not isinstance(states, list)
                or (states and len(states) < 2)
                or any(
                    not isinstance(state, str)
                    or re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", state) is None
                    for state in states
                )
                or len(set(states)) != len(states)
            ):
                raise ValueError(
                    f"native BNGIR molecule type {name!r} has invalid components or states"
                )
            seen_component_names.add(component_name)
        if has_binding_only and not has_finite_state:
            binding_only_type_ids.add(index)
        molecule_ids.add(index)
        molecule_names.add(name)
        molecule_types_by_id[index] = molecule

    if not model["seeds"]:
        raise ValueError("native BNGIR requires at least one seed")
    for index, raw in enumerate(model["seeds"]):
        seed = _require_mapping(raw, f"model.seeds[{index}]")
        _native_required_optional_keys(
            seed,
            {"id", "pattern", "amount", "constant"},
            {"amount", "compartment", "constant", "id", "pattern"},
            f"model.seeds[{index}]",
        )
        if "compartment" in seed and (
            not isinstance(seed["compartment"], str) or not seed["compartment"]
        ):
            raise ValueError(
                f"native BNGIR model.seeds[{index}].compartment must be a nonempty string"
            )
        if (
            isinstance(seed["id"], bool)
            or not isinstance(seed["id"], int)
            or seed["id"] != index
        ):
            raise ValueError("native BNGIR seed ids must be dense and ordered")
        if not isinstance(seed["constant"], bool):
            raise ValueError(
                f"native BNGIR model.seeds[{index}].constant must be boolean"
            )
        _native_pattern_v02(
            seed["pattern"],
            f"model.seeds[{index}].pattern",
            molecule_ids,
            molecule_types_by_id,
            require_complete=True,
        )
        _native_expression_v02(
            seed["amount"], parameter_ids, f"model.seeds[{index}].amount"
        )

    # Observables are the only model section that the v0.2 native slice
    # supports alongside seeds and rules.  Each observable term carries a
    # structured pattern (validated via _native_pattern_v02), an integer
    # quantity, and an optional count-relation operator understood by
    # CompiledModel::observablePatternCountMatches.
    observable_names: set[str] = set()
    observable_ids: set[int] = set()
    for index, raw in enumerate(model["observables"]):
        obs = _require_mapping(raw, f"model.observables[{index}]")
        _native_exact_keys(
            obs,
            {"id", "name", "kind", "terms"},
            f"model.observables[{index}]",
        )
        if (
            isinstance(obs["id"], bool)
            or not isinstance(obs["id"], int)
            or obs["id"] != index
        ):
            raise ValueError("native BNGIR observable ids must be dense and ordered")
        observable_ids.add(index)
        name = obs["name"]
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name)
            or name in observable_names
        ):
            raise ValueError(
                f"native BNGIR observable name is invalid or duplicated: {name!r}"
            )
        if obs["kind"] not in {"molecules", "species", "counter"}:
            raise ValueError(
                f"native BNGIR model.observables[{index}] has unsupported kind "
                f"{obs['kind']!r} (only 'molecules', 'species', and 'counter' are supported)"
            )
        terms = obs["terms"]
        if not isinstance(terms, list) or not terms:
            raise ValueError(
                f"native BNGIR model.observables[{index}] must have at least one term"
            )
        for term_index, term in enumerate(terms):
            term = _require_mapping(
                term, f"model.observables[{index}].terms[{term_index}]"
            )
            _native_required_optional_keys(
                term,
                {"pattern", "quantity"},
                {"pattern", "quantity", "relation"},
                f"model.observables[{index}].terms[{term_index}]",
            )
            _native_pattern_v02(
                term["pattern"],
                f"model.observables[{index}].terms[{term_index}].pattern",
                molecule_ids,
                molecule_types_by_id,
            )
            quantity = term["quantity"]
            if (
                isinstance(quantity, bool)
                or not isinstance(quantity, int)
                or quantity < 0
            ):
                raise ValueError(
                    "native BNGIR observable quantity must be a non-negative integer"
                )
            relation = term.get("relation")
            if relation is not None:
                if not isinstance(relation, str) or relation not in {
                    "==",
                    "!=",
                    ">",
                    ">=",
                    "<",
                    "<=",
                }:
                    raise ValueError(
                        f"native BNGIR model.observables[{index}].terms[{term_index}] "
                        f"has unsupported count relation: {relation!r}"
                    )
        observable_names.add(name)

    function_ids: set[int] = set()
    function_names: set[str] = set()
    function_arities: dict[int, int] = {}
    function_arguments: list[list[str]] = []
    if not isinstance(model["functions"], list):
        raise ValueError("native BNGIR model.functions must be an array")
    for index, raw in enumerate(model["functions"]):
        function = _require_mapping(raw, f"model.functions[{index}]")
        _native_exact_keys(
            function,
            {"id", "name", "arguments", "expression"},
            f"model.functions[{index}]",
        )
        if (
            isinstance(function["id"], bool)
            or not isinstance(function["id"], int)
            or function["id"] != index
        ):
            raise ValueError("native BNGIR function ids must be dense and ordered")
        name = function["name"]
        if not isinstance(name, str) or not name or name in function_names:
            raise ValueError("native BNGIR function names must be nonempty and unique")
        if name in parameter_names:
            raise ValueError(
                "native BNGIR function names must not collide with parameter names"
            )
        arguments = function["arguments"]
        if not isinstance(arguments, list) or not all(
            isinstance(argument, str) and argument for argument in arguments
        ):
            raise ValueError(
                f"native BNGIR model.functions[{index}].arguments must be nonempty strings"
            )
        if len(set(arguments)) != len(arguments):
            raise ValueError(
                f"native BNGIR model.functions[{index}].arguments must be unique"
            )
        function_ids.add(index)
        function_names.add(name)
        function_arities[index] = len(arguments)
        function_arguments.append(list(arguments))
    for index, raw in enumerate(model["functions"]):
        function = _require_mapping(raw, f"model.functions[{index}]")
        _native_expression_v02(
            function["expression"],
            parameter_ids,
            f"model.functions[{index}].expression",
            local_names=frozenset(function_arguments[index]),
            function_ids=frozenset(function_ids),
            function_arities=function_arities,
            observable_ids=frozenset(observable_ids),
            allow_function_calls=True,
        )

    rule_names: set[str] = set()
    for index, raw in enumerate(model["rules"]):
        rule = _require_mapping(raw, f"model.rules[{index}]")
        rule_keys = {
            "id",
            "name",
            "label",
            "bidirectional",
            "modifiers",
            "forward",
            "molecule_mappings",
            "component_mappings",
        }
        _native_required_optional_keys(
            rule,
            rule_keys,
            rule_keys | {"reverse", "delay", "non_consuming"},
            f"model.rules[{index}]",
        )
        if "non_consuming" in rule:
            if not isinstance(rule["non_consuming"], bool):
                raise ValueError(
                    f"native BNGIR model.rules[{index}].non_consuming must be boolean"
                )
            if rule["non_consuming"] and "delay" not in rule:
                raise ValueError(
                    f"native BNGIR model.rules[{index}] NonConsuming requires delay expression"
                )
        if "delay" in rule:
            _validate_expression_v02(
                _require_mapping(rule["delay"], f"model.rules[{index}].delay"),
                model,
                local_names=set(),
                where=f"model.rules[{index}].delay",
            )
        if (
            isinstance(rule["id"], bool)
            or not isinstance(rule["id"], int)
            or rule["id"] != index
        ):
            raise ValueError("native BNGIR rule ids must be dense and ordered")
        if (
            not isinstance(rule["name"], str)
            or not rule["name"]
            or rule["name"] in rule_names
            or not isinstance(rule["label"], str)
        ):
            raise ValueError(f"native BNGIR model.rules[{index}] has invalid names")
        rule_names.add(rule["name"])
        if not isinstance(rule["bidirectional"], bool):
            raise ValueError(
                f"native BNGIR model.rules[{index}].bidirectional must be boolean"
            )
        if rule["modifiers"] != []:
            raise ValueError(
                f"native BNGIR model.rules[{index}] does not support rule modifiers"
            )
        if rule["bidirectional"] != ("reverse" in rule):
            boundary = "requires" if rule["bidirectional"] else "does not support"
            raise ValueError(
                f"native BNGIR model.rules[{index}] {boundary} an explicit reverse direction"
            )
        if not isinstance(rule["molecule_mappings"], list) or not isinstance(
            rule["component_mappings"], list
        ):
            raise ValueError(
                f"native BNGIR model.rules[{index}] mappings must be arrays"
            )
        direction = _require_mapping(rule["forward"], f"model.rules[{index}].forward")
        _native_exact_keys(
            direction,
            {
                "reactants",
                "products",
                "rate",
                "filters",
                "local_scopes",
                "mutations",
                "transformations_complete",
            },
            f"model.rules[{index}].forward",
        )
        if direction["filters"] != [] or direction["local_scopes"] != []:
            raise ValueError(
                f"native BNGIR model.rules[{index}] does not support filters or local scopes"
            )
        if direction["transformations_complete"] is not True:
            raise ValueError(
                f"native BNGIR model.rules[{index}] has incomplete transformations"
            )
        bond_change = any(
            mutation.get("kind") in {"add_bond", "delete_bond"}
            for mutation in direction["mutations"]
        )
        uses_binding_only_type = False
        for side in ("reactants", "products"):
            for pattern in direction[side]:
                for molecule in pattern.get("molecules", []):
                    type_id = molecule.get("type_id")
                    if type_id in binding_only_type_ids:
                        uses_binding_only_type = True
        if uses_binding_only_type and not bond_change:
            raise ValueError("native BNGIR binding-only components are unsupported")
        for side in ("reactants", "products"):
            patterns = direction[side]
            if not isinstance(patterns, list) or not patterns:
                # The native slice rebuilds a rule direction from its reactant
                # and product patterns. A direction without any is an explicit
                # refusal, so the message names the boundary the consumer
                # classifies on.
                side_name = "reactant" if side == "reactants" else "product"
                raise ValueError(
                    "native BNGIR does not support a rule direction without a "
                    f"{side_name} pattern"
                )
            for pattern_index, pattern in enumerate(patterns):
                _native_pattern_v02(
                    pattern,
                    f"model.rules[{index}].{side}[{pattern_index}]",
                    molecule_ids,
                    molecule_types_by_id,
                )
        has_state_sites = any(
            any(
                component["states"]
                for component in molecule_types_by_id[molecule["type_id"]]["components"]
            )
            for side in ("reactants", "products")
            for pattern in direction[side]
            for molecule in pattern["molecules"]
        )
        if bond_change:
            _native_bond_change_v02(rule, direction, index, model)
        elif has_state_sites:
            _native_state_transition_v02(rule, direction, index, model)
        if not bond_change:
            _native_multi_pattern_direction_v02(
                rule, direction, index, model, molecule_ids
            )
        if len(rule["molecule_mappings"]) > (2 if bond_change else 1):
            raise ValueError(
                f"native BNGIR model.rules[{index}] has too many molecule mappings"
            )
        for mapping_index, raw_mapping in enumerate(
            rule["molecule_mappings"] if not bond_change else []
        ):
            mapping = _require_mapping(
                raw_mapping,
                f"model.rules[{index}].molecule_mappings[{mapping_index}]",
            )
            _native_exact_keys(
                mapping,
                {"product", "reactant"},
                f"model.rules[{index}].molecule_mappings[{mapping_index}]",
            )
            for side in ("product", "reactant"):
                ref = _require_mapping(
                    mapping[side],
                    f"model.rules[{index}].molecule_mappings[{mapping_index}].{side}",
                )
                _native_exact_keys(
                    ref,
                    {"side", "pattern", "molecule"},
                    f"model.rules[{index}].molecule_mappings[{mapping_index}].{side}",
                )
                if (
                    ref["side"] != side
                    or isinstance(ref["pattern"], bool)
                    or not isinstance(ref["pattern"], int)
                    or ref["pattern"] != 0
                    or isinstance(ref["molecule"], bool)
                    or not isinstance(ref["molecule"], int)
                    or ref["molecule"] != 0
                ):
                    raise ValueError(
                        f"native BNGIR model.rules[{index}] has an out-of-slice molecule mapping reference"
                    )
        if rule["component_mappings"] and not has_state_sites and not bond_change:
            raise ValueError(
                f"native BNGIR model.rules[{index}] does not support component mappings"
            )
        rate = _require_mapping(direction["rate"], f"model.rules[{index}].forward.rate")
        _native_exact_keys(
            rate, {"kind", "expression"}, f"model.rules[{index}].forward.rate"
        )
        if rate["kind"] != 0 or isinstance(rate["kind"], bool):
            raise ValueError(
                f"native BNGIR model.rules[{index}] requires an expression rate"
            )
        _native_expression_v02(
            rate["expression"],
            parameter_ids,
            f"model.rules[{index}].forward.rate.expression",
            function_ids=frozenset(function_ids),
            function_arities=function_arities,
            allow_function_calls=True,
        )
        mutations = direction["mutations"]
        if not isinstance(mutations, list):
            raise ValueError(
                f"native BNGIR model.rules[{index}].forward.mutations must be an array"
            )
        for mutation_index, raw_mutation in enumerate(mutations):
            if has_state_sites or bond_change:
                # The narrow state-transition validator above checked the
                # single change_state operation and all of its references.
                continue
            mutation = _require_mapping(
                raw_mutation,
                f"model.rules[{index}].forward.mutations[{mutation_index}]",
            )
            kind = mutation.get("kind")
            if not isinstance(kind, str) or kind not in {
                "add_molecule",
                "delete_molecule",
            }:
                raise ValueError(
                    f"native BNGIR model.rules[{index}] has unsupported mutation kind {kind!r}"
                )
            _native_exact_keys(
                mutation,
                {"kind", "molecule"},
                f"model.rules[{index}].forward.mutations[{mutation_index}]",
            )
            ref = _require_mapping(
                mutation["molecule"],
                f"model.rules[{index}].forward.mutations[{mutation_index}].molecule",
            )
            _native_exact_keys(
                ref,
                {"side", "pattern", "molecule"},
                f"model.rules[{index}].forward.mutations[{mutation_index}].molecule",
            )
            side_patterns = (
                direction["reactants"]
                if kind == "delete_molecule"
                else direction["products"]
            )
            if (
                ref["side"] != ("reactant" if kind == "delete_molecule" else "product")
                or isinstance(ref["pattern"], bool)
                or not isinstance(ref["pattern"], int)
                or not 0 <= ref["pattern"] < len(side_patterns)
                or isinstance(ref["molecule"], bool)
                or ref["molecule"] != 0
            ):
                raise ValueError(
                    f"native BNGIR model.rules[{index}] has a contradictory molecule mutation reference"
                )

        if rule["bidirectional"]:
            reverse = _require_mapping(rule["reverse"], f"model.rules[{index}].reverse")
            direction_keys = {
                "reactants",
                "products",
                "rate",
                "filters",
                "local_scopes",
                "mutations",
                "transformations_complete",
            }
            _native_exact_keys(reverse, direction_keys, f"model.rules[{index}].reverse")
            if reverse["filters"] != [] or reverse["local_scopes"] != []:
                raise ValueError(
                    f"native BNGIR model.rules[{index}] does not support reverse filters or local scopes"
                )
            if reverse["transformations_complete"] is not True:
                raise ValueError(
                    f"native BNGIR model.rules[{index}] has incomplete reverse transformations"
                )
            if (
                reverse["reactants"] != direction["products"]
                or reverse["products"] != direction["reactants"]
            ):
                raise ValueError(
                    f"native BNGIR model.rules[{index}] reverse direction must invert forward patterns"
                )
            reverse_rate = _require_mapping(
                reverse["rate"], f"model.rules[{index}].reverse.rate"
            )
            _native_exact_keys(
                reverse_rate,
                {"kind", "expression"},
                f"model.rules[{index}].reverse.rate",
            )
            if reverse_rate["kind"] != 0 or isinstance(reverse_rate["kind"], bool):
                raise ValueError(
                    f"native BNGIR model.rules[{index}] requires an expression reverse rate"
                )
            _native_expression_v02(
                reverse_rate["expression"],
                parameter_ids,
                f"model.rules[{index}].reverse.rate.expression",
                function_ids=frozenset(function_ids),
                function_arities=function_arities,
                allow_function_calls=True,
            )
            if not isinstance(reverse["mutations"], list):
                raise ValueError(
                    f"native BNGIR model.rules[{index}].reverse.mutations must be an array"
                )
            if bond_change:
                _native_bond_change_v02(
                    rule, reverse, index, model, validate_mappings=False
                )
            elif has_state_sites:
                _native_state_transition_v02(
                    rule, reverse, index, model, validate_mappings=False
                )
            else:
                for mutation_index, raw_mutation in enumerate(reverse["mutations"]):
                    mutation = _require_mapping(
                        raw_mutation,
                        f"model.rules[{index}].reverse.mutations[{mutation_index}]",
                    )
                    if mutation.get("kind") not in {"add_molecule", "delete_molecule"}:
                        raise ValueError(
                            f"native BNGIR model.rules[{index}] has unsupported reverse mutation kind {mutation.get('kind')!r}"
                        )
                    _native_exact_keys(
                        mutation,
                        {"kind", "molecule"},
                        f"model.rules[{index}].reverse.mutations[{mutation_index}]",
                    )
                    reference = _require_mapping(
                        mutation["molecule"],
                        f"model.rules[{index}].reverse.mutations[{mutation_index}].molecule",
                    )
                    _native_exact_keys(
                        reference,
                        {"side", "pattern", "molecule"},
                        f"model.rules[{index}].reverse.mutations[{mutation_index}].molecule",
                    )
                    mutation_side = (
                        "reactant"
                        if mutation["kind"] == "delete_molecule"
                        else "product"
                    )
                    side_patterns = (
                        reverse["reactants"]
                        if mutation_side == "reactant"
                        else reverse["products"]
                    )
                    if (
                        reference["side"] != mutation_side
                        or isinstance(reference["pattern"], bool)
                        or not isinstance(reference["pattern"], int)
                        or not 0 <= reference["pattern"] < len(side_patterns)
                        or isinstance(reference["molecule"], bool)
                        or reference["molecule"] != 0
                    ):
                        raise ValueError(
                            f"native BNGIR model.rules[{index}] has a contradictory reverse molecule mutation reference"
                        )
                if not bond_change:
                    _native_reversible_direction_v02(direction, index, "forward")
                    _native_reversible_direction_v02(reverse, index, "reverse")

    protocol = _require_mapping(root["protocol"], "protocol")
    _native_exact_keys(protocol, {"actions"}, "protocol")
    if protocol["actions"] != []:
        raise ValueError("native BNGIR does not support protocol actions")
    expected_used = sorted(
        ["structured_patterns", "structured_expressions"]
        + (["compartments"] if model.get("compartments") else [])
        + (
            ["delayed_rules"]
            if any(rule.get("delay") is not None for rule in model["rules"])
            else []
        )
        + (["functions"] if model["functions"] else [])
        + (["observables"] if model["observables"] else [])
        + (["rules"] if model["rules"] else [])
        + (["seeds"] if model["seeds"] else [])
    )
    if features["used"] != expected_used:
        raise ValueError(
            "native BNGIR features.used does not match the supported model sections"
        )


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
        if not _is_json_integer(semantic_id) or semantic_id < 0:
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
        "barrier_pattern": "barrier_patterns",
        "population_type": "population_types",
    }
    section = sections.get(kind)
    if section is None:
        raise ValueError(f"unsupported BNGIR symbol kind: {kind}")
    values = _section_id_map(model, section)
    if not _is_json_integer(index) or index < 0 or index not in values:
        raise ValueError(f"BNGIR {kind} symbol id is unknown: {index}")
    item = values[index]
    name = item.get("name")
    if section in ("energy_patterns", "barrier_patterns"):
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
# BNGL keyword spellings for builtins whose identifier differs from the wire
# name. Rendering the wire name verbatim would produce an undefined function
# call (e.g. arrhenius(...) instead of Arrhenius(...)) and fail on read-back.
_BUILTIN_NAMES = {
    "arrhenius": "Arrhenius",
    "function_product": "FunctionProduct",
    "hill": "Hill",
    "michaelis_menten": "MM",
    "saturation": "Sat",
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


def _observable_term_v02(term: Mapping[str, Any]) -> str:
    pattern_data = _require_mapping(term.get("pattern"), "observable pattern")
    pattern = _pattern_v02(pattern_data)
    relation = str(term.get("relation", ""))
    if not relation:
        return pattern
    quantity = int(term.get("quantity", 0))
    if relation == ">":
        return f"{pattern}>{quantity}"
    molecule = _require_mapping(pattern_data["molecules"][0], "observable molecule")
    return f"{molecule['type']}{relation}{quantity}"


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

    unit_defaults = metadata.get("unit_defaults") or {}
    unit_definitions = metadata.get("unit_definitions") or []
    if unit_defaults or unit_definitions:
        # Mirrors BnglWriter: authored defaults and definitions round-trip
        # through the same block normalizeUnitSyntax() consumes on read-back.
        lines.append("begin units")
        for role in sorted(unit_defaults):
            lines.append(f"  {role} = {unit_defaults[role]}")
        for definition in unit_definitions:
            lines.append(f"  unit {definition['id']} = {definition['expression']}")
        lines.append("end units")

    parameters = model.get("parameters", [])
    if parameters:
        lines.append("begin parameters")
        for item in parameters:
            line = f"  {item['name']} {_expression_v02(item['expression'], model)}"
            if item.get("unit"):
                line += f" [{item['unit']}]"
            lines.append(line)
        lines.append("end parameters")

    compartments = model.get("compartments", [])
    if compartments:
        lines.append("begin compartments")
        for item in compartments:
            suffix = f" {item['parent']}" if item.get("parent") else ""
            unit = f" [{item['unit']}]" if item.get("unit") else ""
            lines.append(
                f"  {item['name']} {int(item['dimension'])} {item['volume']}"
                f"{suffix}{unit}"
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
            line = f"  {pattern} {_expression_v02(item['amount'], model)}"
            if item.get("unit"):
                line += f" [{item['unit']}]"
            lines.append(line)
        lines.append("end seed species")

    observables = model.get("observables", [])
    if observables:
        lines.append("begin observables")
        for item in observables:
            kind = (
                "Molecules"
                if item.get("kind") == "molecules"
                else ("Species" if item.get("kind") == "species" else "Counter")
            )
            rendered_terms = [
                _observable_term_v02(term) for term in item.get("terms", [])
            ]
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

    barrier_patterns = model.get("barrier_patterns", [])
    if barrier_patterns:
        # Follows energy patterns for the same reason as the v0.1 emitter.
        lines.append("begin barrier patterns")
        for item in barrier_patterns:
            # The wire transition is BarrierPattern::toString(): it already
            # carries the label prefix, the arrow, and the energy expression,
            # so it is the whole line. Validation guaranteed it is present.
            lines.append(f"  {item['transition']}")
        lines.append("end barrier patterns")

    population_maps = model.get("population_maps", [])
    if population_maps:
        lines.append("begin population maps")
        for item in population_maps:
            label = f"{item['label']}: " if item.get("label") else ""
            args = ",".join(item.get("arguments", []))
            rate = _expression_v02(item["rate"], model)
            modifier = " TotalRate" if item.get("total_rate", False) else ""
            lines.append(
                f"  {label}{_pattern_v02(item['pattern'])} -> "
                f"{item['population']}({args}) {rate}{modifier}"
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
            if item.get("delay"):
                delay_val = item["delay"]
                if isinstance(delay_val, Mapping):
                    line += f" delay={_expression_v02(delay_val, model)}"
                else:
                    line += f" delay={delay_val}"
            if item.get("non_consuming"):
                line += " NonConsuming"
            # driven_by() follows the rate law and any modifiers, which is
            # where normalizeThermodynamicSyntax() strips it from on read-back.
            driving_work = item.get("driving_work")
            if driving_work:
                if isinstance(driving_work, str):
                    line += f" driven_by({driving_work})"
                else:
                    line += f" driven_by({_expression_v02(driving_work, model)})"
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


def from_bngir(document: str | Mapping[str, Any], *, native: bool = False):
    """Reconstruct a modern ``BioNetGenModel`` from supported BNGIR versions.

    ``native=True`` selects the deliberately narrow, parser-free BNGIR v0.2
    route. The default remains the source-compatible renderer/parser route.
    """
    if not isinstance(native, bool):
        raise TypeError("native must be a bool")
    root = _parse_document(document)
    from .model import BioNetGenModel, _cpp

    if native:
        if root["version"] != STRUCTURAL_VERSION:
            raise ValueError("native BNGIR import requires version 0.2")
        root = _load_document_v02(root)
        _validate_native_v02(root)
        model_data = _require_mapping(root["model"], "model")
        native_data = dict(model_data)
        # The observables stay in the C++ input. A model function may name an
        # observable, and the native importer resolves that name against the
        # model's observables while it rebuilds the function body, so the
        # observable list has to reach it. The wire form states a kind and
        # structured terms; the native importer takes a type and the rendered
        # pattern of each term.
        native_data["observables"] = [
            {
                "name": observable["name"],
                "type": (
                    "Molecules"
                    if observable["kind"] == "molecules"
                    else ("Species" if observable["kind"] == "species" else "Counter")
                ),
                "patterns": [
                    _observable_term_v02(term) for term in observable["terms"]
                ],
            }
            for observable in model_data["observables"]
        ]
        result_cpp = _cpp._model_from_bngir_v02(native_data)
        result = BioNetGenModel(result_cpp)
        rebuilt = _parse_document(to_bngir(result, version=STRUCTURAL_VERSION))
        if rebuilt != root:
            raise ValueError(
                "native BNGIR v0.2 payload does not match reconstructed compiled semantics"
            )
        result._native_bngir_v02_only = True
        return result

    if root["version"] == VERSION:
        root = _load_document_v01(root)
        _validate_document_properties(root)
        source = _as_bngl_v01(root)
        model_data = _require_mapping(root["model"], "model")
        name = model_data.get("name")
    else:
        root = _load_document_v02(root)
        _validate_document_properties(root)
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


class EqualityUndecided(Exception):
    """Raised when exact proof search cannot decide process equality."""

    def __init__(
        self, message: str, diagnostic: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        diag = dict(diagnostic or {})
        diag.setdefault("status", "undecided")
        diag.setdefault("message", message)
        self.diagnostic = diag


def _evaluate_model_expression_exact(
    expr_str: str,
    parameters: Mapping[str, Fraction],
    functions: Mapping[str, str] | None = None,
    _visiting: frozenset[str] = frozenset(),
) -> Fraction:
    """Evaluate the rational arithmetic subset without rounding.

    Supports exact rational arithmetic over parameters and acyclic nullary
    rational functions. Equality outside the subset must remain undecided rather
    than being established by floating-point proximity.
    """
    normalized_expr = expr_str.replace("^", "**")
    try:
        root = ast.parse(normalized_expr, mode="eval").body
    except SyntaxError as exc:
        raise ValueError(f"not a rational arithmetic expression: {expr_str}") from exc

    fn_map = functions or {}

    def visit(node: ast.AST) -> Fraction:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool):
                raise ValueError(f"boolean constant outside rational arithmetic: {expr_str}")
            if isinstance(node.value, float) and not math.isfinite(node.value):
                raise ValueError(f"non-finite literal: {expr_str}")
            return Fraction(str(node.value))
        if isinstance(node, ast.Name):
            if node.id in parameters:
                return parameters[node.id]
            if node.id in fn_map and node.id not in _visiting:
                return _evaluate_model_expression_exact(
                    fn_map[node.id], parameters, fn_map, _visiting | {node.id}
                )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if (
                not node.args
                and not node.keywords
                and node.func.id in fn_map
                and node.func.id not in _visiting
            ):
                return _evaluate_model_expression_exact(
                    fn_map[node.func.id], parameters, fn_map, _visiting | {node.func.id}
                )
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise ValueError("division by zero in rational expression")
                return left / right
            if isinstance(node.op, ast.Pow) and right.denominator == 1:
                if left == 0 and right.numerator < 0:
                    raise ValueError("division by zero in negative power")
                return left**right.numerator
        raise ValueError(f"expression is outside exact rational arithmetic: {expr_str}")

    return visit(root)


# ---------------------------------------------------------------------------
# Exact multivariate polynomial & rational-expression normalization with
# pre-cancellation pole-domain tracking (EQ-functions).
# ---------------------------------------------------------------------------

_Monomial = tuple[tuple[str, int], ...]
_Poly = tuple[tuple[_Monomial, Fraction], ...]


def _poly_from_dict(terms: Mapping[_Monomial, Fraction]) -> _Poly:
    return tuple(sorted((m, c) for m, c in terms.items() if c != 0))


def _poly_const(value: Fraction) -> _Poly:
    return (((), value),) if value != 0 else ()


def _poly_var(name: str) -> _Poly:
    return ((((name, 1),), Fraction(1)),)


def _poly_is_zero(p: _Poly) -> bool:
    return len(p) == 0


def _poly_is_const(p: _Poly) -> bool:
    return len(p) == 0 or (len(p) == 1 and p[0][0] == ())


def _poly_vars(p: _Poly) -> frozenset[str]:
    names: set[str] = set()
    for mono, _ in p:
        for name, _ in mono:
            names.add(name)
    return frozenset(names)


def _poly_add(a: _Poly, b: _Poly) -> _Poly:
    acc: dict[_Monomial, Fraction] = dict(a)
    for m, c in b:
        acc[m] = acc.get(m, Fraction(0)) + c
    return _poly_from_dict(acc)


def _poly_neg(a: _Poly) -> _Poly:
    return tuple((m, -c) for m, c in a)


def _poly_sub(a: _Poly, b: _Poly) -> _Poly:
    return _poly_add(a, _poly_neg(b))


def _mono_mul(m1: _Monomial, m2: _Monomial) -> _Monomial:
    acc: dict[str, int] = dict(m1)
    for k, e in m2:
        acc[k] = acc.get(k, 0) + e
    return tuple(sorted((k, e) for k, e in acc.items() if e > 0))


def _poly_mul(a: _Poly, b: _Poly) -> _Poly:
    if not a or not b:
        return ()
    acc: dict[_Monomial, Fraction] = {}
    for m1, c1 in a:
        for m2, c2 in b:
            m = _mono_mul(m1, m2)
            acc[m] = acc.get(m, Fraction(0)) + c1 * c2
    return _poly_from_dict(acc)


def _poly_pow(a: _Poly, exp: int) -> _Poly:
    if exp < 0:
        raise ValueError("negative polynomial exponent")
    result = _poly_const(Fraction(1))
    base = a
    e = exp
    while e > 0:
        if e & 1:
            result = _poly_mul(result, base)
        e >>= 1
        if e:
            base = _poly_mul(base, base)
    return result


def _poly_scale(p: _Poly, factor: Fraction) -> _Poly:
    if factor == 0 or not p:
        return ()
    return tuple((m, c * factor) for m, c in p)


def _poly_lead_coeff(p: _Poly) -> Fraction:
    return p[-1][1] if p else Fraction(0)


def _poly_monic(p: _Poly) -> _Poly:
    if not p:
        return ()
    return _poly_scale(p, Fraction(1) / _poly_lead_coeff(p))


def _poly_to_univariate(p: _Poly, var: str) -> list[Fraction]:
    if not p:
        return []
    deg = max((dict(m).get(var, 0) for m, _ in p), default=0)
    coeffs = [Fraction(0)] * (deg + 1)
    for m, c in p:
        coeffs[dict(m).get(var, 0)] += c
    while coeffs and coeffs[-1] == 0:
        coeffs.pop()
    return coeffs


def _univariate_to_poly(coeffs: list[Fraction], var: str) -> _Poly:
    terms: dict[_Monomial, Fraction] = {}
    for deg, c in enumerate(coeffs):
        if c != 0:
            terms[((var, deg),) if deg > 0 else ()] = c
    return _poly_from_dict(terms)


def _uni_divmod(
    a: list[Fraction], b: list[Fraction]
) -> tuple[list[Fraction], list[Fraction]]:
    rem = list(a)
    while rem and rem[-1] == 0:
        rem.pop()
    b_clean = list(b)
    while b_clean and b_clean[-1] == 0:
        b_clean.pop()
    if not b_clean:
        raise ZeroDivisionError("univariate polynomial division by zero")
    deg_b = len(b_clean) - 1
    lead_b = b_clean[-1]
    quot = [Fraction(0)] * max(0, len(rem) - deg_b)
    while len(rem) >= len(b_clean):
        shift = len(rem) - len(b_clean)
        factor = rem[-1] / lead_b
        quot[shift] = factor
        for i in range(len(b_clean)):
            rem[shift + i] -= factor * b_clean[i]
        while rem and rem[-1] == 0:
            rem.pop()
    while quot and quot[-1] == 0:
        quot.pop()
    return quot, rem


def _uni_gcd(a: list[Fraction], b: list[Fraction]) -> list[Fraction]:
    x = list(a)
    y = list(b)
    while x and x[-1] == 0:
        x.pop()
    while y and y[-1] == 0:
        y.pop()
    while y:
        _, r = _uni_divmod(x, y)
        x, y = y, r
    if x:
        lead = x[-1]
        x = [c / lead for c in x]
    return x


def _uni_derivative(a: list[Fraction]) -> list[Fraction]:
    if len(a) <= 1:
        return []
    return [a[i] * Fraction(i) for i in range(1, len(a))]


def _poly_squarefree_pole(p: _Poly) -> _Poly:
    """Return canonical square-free monic form for univariate poles, monic otherwise."""
    if _poly_is_const(p):
        return ()
    variables = _poly_vars(p)
    if len(variables) == 1:
        var = next(iter(variables))
        coeffs = _poly_to_univariate(p, var)
        deriv = _uni_derivative(coeffs)
        if deriv:
            g = _uni_gcd(coeffs, deriv)
            if len(g) > 1:
                sf, _ = _uni_divmod(coeffs, g)
                return _poly_monic(_univariate_to_poly(sf, var))
    return _poly_monic(p)


def _poly_extract_monomial_gcd(a: _Poly, b: _Poly) -> tuple[_Poly, _Poly]:
    """Cancel any common monomial factor across all terms of a and b."""
    if not a or not b:
        return a, b
    all_monos = [dict(m) for m, _ in a] + [dict(m) for m, _ in b]
    common_vars = set(all_monos[0])
    for d in all_monos[1:]:
        common_vars &= set(d)
    if not common_vars:
        return a, b
    min_exp = {v: min(d[v] for d in all_monos) for v in common_vars}

    def div_mono(p: _Poly) -> _Poly:
        out: dict[_Monomial, Fraction] = {}
        for m, c in p:
            d = dict(m)
            for v, e in min_exp.items():
                d[v] -= e
            nm = tuple(sorted((k, v) for k, v in d.items() if v > 0))
            out[nm] = c
        return _poly_from_dict(out)

    return div_mono(a), div_mono(b)


def _poly_reduce_pair(num: _Poly, den: _Poly) -> tuple[_Poly, _Poly]:
    """Reduce (num, den) to canonical exact ratio with monic denominator."""
    if _poly_is_zero(den):
        raise ValueError("division by zero in rational expression")
    if _poly_is_zero(num):
        return (), _poly_const(Fraction(1))
    num, den = _poly_extract_monomial_gcd(num, den)
    # Exact proportional cancellation handles multivariate (P*c)/(P*d)
    if _poly_monic(num) == _poly_monic(den):
        ratio = _poly_lead_coeff(num) / _poly_lead_coeff(den)
        return _poly_const(ratio), _poly_const(Fraction(1))
    variables = _poly_vars(num) | _poly_vars(den)
    if len(variables) == 1:
        var = next(iter(variables))
        u_num = _poly_to_univariate(num, var)
        u_den = _poly_to_univariate(den, var)
        g = _uni_gcd(u_num, u_den)
        if len(g) > 1:
            q_num, _ = _uni_divmod(u_num, g)
            q_den, _ = _uni_divmod(u_den, g)
            num = _univariate_to_poly(q_num, var)
            den = _univariate_to_poly(q_den, var)
    lead = _poly_lead_coeff(den)
    return _poly_scale(num, Fraction(1) / lead), _poly_scale(den, Fraction(1) / lead)


def _poly_eval(p: _Poly, assignment: Mapping[str, Fraction]) -> Fraction:
    total = Fraction(0)
    for mono, coeff in p:
        term = coeff
        for var, exp in mono:
            term *= assignment[var] ** exp
        total += term
    return total


class _RationalExpr:
    """Exact multivariate rational expression with pre-cancellation pole domain."""

    __slots__ = ("num", "den", "poles")

    def __init__(self, num: _Poly, den: _Poly, poles: frozenset[_Poly]) -> None:
        r_num, r_den = _poly_reduce_pair(num, den)
        self.num = r_num
        self.den = r_den
        cleaned_poles = set(poles)
        if not _poly_is_const(den):
            sf = _poly_squarefree_pole(den)
            if sf:
                cleaned_poles.add(sf)
        self.poles = frozenset(cleaned_poles)

    def key(self) -> tuple[_Poly, _Poly, frozenset[_Poly]]:
        return (self.num, self.den, self.poles)

    def ratio_key(self) -> tuple[_Poly, _Poly]:
        return (self.num, self.den)

    def variables(self) -> frozenset[str]:
        v = set(_poly_vars(self.num)) | set(_poly_vars(self.den))
        for p in self.poles:
            v |= set(_poly_vars(p))
        return frozenset(v)

    def eval_at(self, assignment: Mapping[str, Fraction]) -> Fraction | None:
        for pole in self.poles:
            if _poly_eval(pole, assignment) == 0:
                return None
        d_val = _poly_eval(self.den, assignment)
        if d_val == 0:
            return None
        return _poly_eval(self.num, assignment) / d_val


def _parse_rational_expr(
    expr_str: str,
    *,
    allowed_vars: frozenset[str],
    zero_arg_functions: Mapping[str, str] | None = None,
    var_renaming: Mapping[str, str] | None = None,
    _visiting: frozenset[str] = frozenset(),
) -> _RationalExpr | None:
    """Parse an expression into an exact canonical rational function with poles.

    Returns None when the expression falls outside the exact rational subset
    (e.g. transcendental functions, conditionals, TFUN).
    """
    normalized_expr = expr_str.replace("^", "**")
    try:
        root = ast.parse(normalized_expr, mode="eval").body
    except SyntaxError:
        return None

    fn_map = zero_arg_functions or {}
    rename = var_renaming or {}

    def visit(node: ast.AST) -> _RationalExpr | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool):
                return None
            if isinstance(node.value, float) and not math.isfinite(node.value):
                return None
            return _RationalExpr(
                _poly_const(Fraction(str(node.value))),
                _poly_const(Fraction(1)),
                frozenset(),
            )
        if isinstance(node, ast.Name):
            if node.id in fn_map and node.id not in _visiting:
                return _parse_rational_expr(
                    fn_map[node.id],
                    allowed_vars=allowed_vars,
                    zero_arg_functions=fn_map,
                    var_renaming=rename,
                    _visiting=_visiting | {node.id},
                )
            if node.id in allowed_vars:
                mapped = rename.get(node.id, node.id)
                return _RationalExpr(
                    _poly_var(mapped), _poly_const(Fraction(1)), frozenset()
                )
            return None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if (
                not node.args
                and not node.keywords
                and node.func.id in fn_map
                and node.func.id not in _visiting
            ):
                return _parse_rational_expr(
                    fn_map[node.func.id],
                    allowed_vars=allowed_vars,
                    zero_arg_functions=fn_map,
                    var_renaming=rename,
                    _visiting=_visiting | {node.func.id},
                )
            if not node.args and not node.keywords and node.func.id in allowed_vars:
                mapped = rename.get(node.func.id, node.func.id)
                return _RationalExpr(
                    _poly_var(mapped), _poly_const(Fraction(1)), frozenset()
                )
            return None
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            inner = visit(node.operand)
            if inner is None:
                return None
            if isinstance(node.op, ast.UAdd):
                return inner
            return _RationalExpr(_poly_neg(inner.num), inner.den, inner.poles)
        if isinstance(node, ast.BinOp):
            left = visit(node.left)
            right = visit(node.right)
            if left is None or right is None:
                return None
            poles = left.poles | right.poles
            if isinstance(node.op, ast.Add):
                return _RationalExpr(
                    _poly_add(
                        _poly_mul(left.num, right.den),
                        _poly_mul(right.num, left.den),
                    ),
                    _poly_mul(left.den, right.den),
                    poles,
                )
            if isinstance(node.op, ast.Sub):
                return _RationalExpr(
                    _poly_sub(
                        _poly_mul(left.num, right.den),
                        _poly_mul(right.num, left.den),
                    ),
                    _poly_mul(left.den, right.den),
                    poles,
                )
            if isinstance(node.op, ast.Mult):
                return _RationalExpr(
                    _poly_mul(left.num, right.num),
                    _poly_mul(left.den, right.den),
                    poles,
                )
            if isinstance(node.op, ast.Div):
                if _poly_is_zero(right.num):
                    return None
                extra_poles = set(poles)
                if not _poly_is_const(right.num):
                    sf = _poly_squarefree_pole(right.num)
                    if sf:
                        extra_poles.add(sf)
                return _RationalExpr(
                    _poly_mul(left.num, right.den),
                    _poly_mul(left.den, right.num),
                    frozenset(extra_poles),
                )
            if isinstance(node.op, ast.Pow):
                if not (_poly_is_const(right.num) and _poly_is_const(right.den)):
                    return None
                exp_val = (
                    Fraction(0)
                    if _poly_is_zero(right.num)
                    else right.num[0][1] / right.den[0][1]
                )
                if exp_val.denominator != 1 or abs(exp_val.numerator) > 16:
                    return None
                n = exp_val.numerator
                if n == 0:
                    return _RationalExpr(
                        _poly_const(Fraction(1)),
                        _poly_const(Fraction(1)),
                        poles,
                    )
                if n > 0:
                    return _RationalExpr(
                        _poly_pow(left.num, n), _poly_pow(left.den, n), poles
                    )
                if _poly_is_zero(left.num):
                    return None
                extra_poles = set(poles)
                if not _poly_is_const(left.num):
                    sf = _poly_squarefree_pole(left.num)
                    if sf:
                        extra_poles.add(sf)
                return _RationalExpr(
                    _poly_pow(left.den, -n),
                    _poly_pow(left.num, -n),
                    frozenset(extra_poles),
                )
        return None

    try:
        return visit(root)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Exact piecewise-linear / step inline TFUN normalization (EQ-time).
# ---------------------------------------------------------------------------


def _eval_tfun_exact(
    xs: tuple[Fraction, ...], ys: tuple[Fraction, ...], method: str, t: Fraction
) -> Fraction:
    if len(xs) == 1:
        return ys[0]
    if t <= xs[0]:
        return ys[0]
    if t >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= t < xs[i + 1]:
            if method == "step":
                return ys[i]
            return ys[i] + (t - xs[i]) * (ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i])
    return ys[-1]


def _canonicalize_tfun_table(
    xs: list[Fraction], ys: list[Fraction], method: str, nonnegative_domain: bool
) -> tuple[str, tuple[tuple[Fraction, Fraction], ...]]:
    """Return canonical minimal knot table for linear/step TFUN with clamping."""
    if nonnegative_domain:
        y0 = _eval_tfun_exact(tuple(xs), tuple(ys), method, Fraction(0))
        filtered = [(x, y) for x, y in zip(xs, ys) if x > 0]
        xs = [Fraction(0)] + [x for x, _ in filtered]
        ys = [y0] + [y for _, y in filtered]

    pts = list(zip(xs, ys))
    if method == "linear":
        changed = True
        while changed and len(pts) >= 3:
            changed = False
            reduced = [pts[0]]
            for i in range(1, len(pts) - 1):
                x0, y0 = reduced[-1]
                x1, y1 = pts[i]
                x2, y2 = pts[i + 1]
                if (y1 - y0) * (x2 - x0) == (y2 - y0) * (x1 - x0):
                    changed = True
                else:
                    reduced.append(pts[i])
            reduced.append(pts[-1])
            pts = reduced
        while len(pts) >= 2 and pts[0][1] == pts[1][1]:
            pts.pop(0)
        while len(pts) >= 2 and pts[-1][1] == pts[-2][1]:
            pts.pop()
        if len(pts) == 1:
            return ("const", ((Fraction(0), pts[0][1]),))
        return ("linear", tuple(pts))

    # Step interpolation (right-continuous, constant clamped outside range).
    reduced_step = [pts[0]]
    for x, y in pts[1:]:
        if y != reduced_step[-1][1]:
            reduced_step.append((x, y))
    if len(reduced_step) == 1:
        return ("const", ((Fraction(0), reduced_step[0][1]),))
    return ("step", tuple(reduced_step))


def _normalize_inline_tfun_doc(
    expr_doc: Mapping[str, Any],
    model_doc: Mapping[str, Any],
    obs_renaming: Mapping[str, str] | None = None,
) -> tuple[tuple[str, str], str, tuple[tuple[Fraction, Fraction], ...]] | None:
    """Normalize an inline table_function AST node from BNGIR v0.2."""
    if not isinstance(expr_doc, Mapping) or expr_doc.get("kind") != "table_function":
        return None
    if expr_doc.get("file"):
        return None
    method = str(expr_doc.get("method") or "linear").lower()
    if method not in {"linear", "step"}:
        return None
    raw_x = expr_doc.get("x")
    raw_y = expr_doc.get("y")
    if (
        not isinstance(raw_x, list)
        or not isinstance(raw_y, list)
        or not raw_x
        or len(raw_x) != len(raw_y)
    ):
        return None
    try:
        xs = [Fraction(str(float(v))) for v in raw_x]
        ys = [Fraction(str(float(v))) for v in raw_y]
    except (TypeError, ValueError):
        return None
    if any(xs[i] >= xs[i + 1] for i in range(len(xs) - 1)):
        return None
    args = expr_doc.get("arguments", [])
    if len(args) != 1 or not isinstance(args[0], Mapping):
        return None
    counter_doc = args[0]
    ckind = counter_doc.get("kind")
    if ckind == "time_ref":
        counter_key = ("time", "time")
        nonneg = True
    elif ckind == "observable_ref":
        sym = counter_doc.get("symbol", {})
        name = _name_for_symbol(model_doc, str(sym.get("kind")), int(sym.get("index")))
        mapped = (obs_renaming or {}).get(name, name)
        counter_key = ("obs", mapped)
        nonneg = True
    elif ckind == "parameter_ref":
        sym = counter_doc.get("symbol", {})
        name = _name_for_symbol(model_doc, str(sym.get("kind")), int(sym.get("index")))
        counter_key = ("param", name)
        nonneg = False
    else:
        return None
    canon_method, canon_pts = _canonicalize_tfun_table(xs, ys, method, nonneg)
    return (counter_key, canon_method, canon_pts)


def _tfun_counterexample(
    left_tfun: tuple[tuple[str, str], str, tuple[tuple[Fraction, Fraction], ...]],
    right_tfun: tuple[tuple[str, str], str, tuple[tuple[Fraction, Fraction], ...]],
) -> dict[str, Any] | None:
    """Return an explicit rational point where two same-counter TFUNs disagree."""
    l_counter, l_method, l_pts = left_tfun
    r_counter, r_method, r_pts = right_tfun
    if l_counter != r_counter:
        return None
    if (l_method, l_pts) == (r_method, r_pts):
        return None
    l_xs = tuple(x for x, _ in l_pts)
    l_ys = tuple(y for _, y in l_pts)
    r_xs = tuple(x for x, _ in r_pts)
    r_ys = tuple(y for _, y in r_pts)
    all_xs = sorted(set(l_xs) | set(r_xs))
    nonneg = l_counter[0] in {"time", "obs"}
    candidates: list[Fraction] = list(all_xs)
    if all_xs:
        low = all_xs[0] - Fraction(1)
        if not nonneg or low >= 0:
            candidates.append(low)
        elif nonneg:
            candidates.append(Fraction(0))
        candidates.append(all_xs[-1] + Fraction(1))
    for i in range(len(all_xs) - 1):
        mid = (all_xs[i] + all_xs[i + 1]) / Fraction(2)
        if not nonneg or mid >= 0:
            candidates.append(mid)
    for t in candidates:
        if nonneg and t < 0:
            continue
        lv = _eval_tfun_exact(l_xs, l_ys, "linear" if l_method == "const" else l_method, t)
        rv = _eval_tfun_exact(r_xs, r_ys, "linear" if r_method == "const" else r_method, t)
        if lv != rv:
            return {
                "counter": l_counter[1],
                "point": str(t),
                "left": str(lv),
                "right": str(rv),
            }
    return None


# ---------------------------------------------------------------------------
# Exact typed molecular graph parsing, isomorphism, and hierarchical renaming
# (EQ-rename, EQ-order, EQ-split, EQ-observables, EQ-energy, EQ-barrier).
# ---------------------------------------------------------------------------

_QUANTIFIER_RE = re.compile(r"^(.*?)\s*(>=|<=|==|!=|>|<)\s*(\d+)\s*$")


def _parse_graph_pattern(text: str) -> dict[str, Any] | None:
    """Parse a canonical BNGL species or observable pattern into a typed graph."""
    raw = text.strip()
    if not raw or raw == "0":
        return {"species_comp": "", "quantifier": None, "molecules": []}

    quantifier: tuple[str, int] | None = None
    q_match = _QUANTIFIER_RE.match(raw)
    if q_match:
        prefix = q_match.group(1).strip()
        if prefix and (prefix[-1] == ")" or prefix[-1].isalnum() or prefix[-1] == "_"):
            quantifier = (q_match.group(2), int(q_match.group(3)))
            raw = prefix

    species_comp = ""
    if raw.startswith("@") and ":" in raw:
        colon = raw.index(":")
        species_comp = raw[1:colon].strip()
        raw = raw[colon + 1 :].strip()

    # Split top-level '.' separating molecules (ignoring '.' inside parentheses).
    mol_tokens: list[str] = []
    depth = 0
    start = 0
    for idx, ch in enumerate(raw):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return None
        elif ch == "." and depth == 0:
            mol_tokens.append(raw[start:idx].strip())
            start = idx + 1
    if depth != 0:
        return None
    mol_tokens.append(raw[start:].strip())

    molecules: list[dict[str, Any]] = []
    for token in mol_tokens:
        if not token:
            return None
        mol_comp = ""
        if "@" in token:
            at_pos = token.rfind("@")
            if ")" not in token[at_pos:]:
                mol_comp = token[at_pos + 1 :].strip()
                token = token[:at_pos].strip()
        if "(" in token:
            if not token.endswith(")"):
                return None
            lp = token.index("(")
            mol_type = token[:lp].strip()
            sites_str = token[lp + 1 : -1].strip()
        else:
            mol_type = token.strip()
            sites_str = ""
        # Strip any local scope tag %label on molecule name if present.
        mol_scope = ""
        if "%" in mol_type:
            mol_type, mol_scope = mol_type.split("%", 1)
        sites: list[dict[str, Any]] = []
        if sites_str:
            for site_tok in sites_str.split(","):
                s = site_tok.strip()
                if not s:
                    continue
                # Extract bond tokens (!1, !+, !?, or unbound marker).
                bonds: list[str] = []
                # Split on '!' first.
                parts = s.split("!")
                head = parts[0]
                for bpart in parts[1:]:
                    bonds.append(bpart.strip())
                # Strip trailing '.' unbound marker if present.
                if head.endswith("."):
                    head = head[:-1]
                    bonds.append(".")
                # Extract state (~state) and optional label (%tag).
                site_label = ""
                if "%" in head:
                    head, site_label = head.split("%", 1)
                state: str | None = None
                if "~" in head:
                    comp_name, state = head.split("~", 1)
                else:
                    comp_name = head
                sites.append(
                    {
                        "comp": comp_name.strip(),
                        "state": state,
                        "bonds": tuple(bonds),
                        "label": site_label,
                    }
                )
        molecules.append(
            {
                "type": mol_type,
                "comp": mol_comp,
                "scope": mol_scope,
                "sites": sites,
            }
        )
    return {
        "species_comp": species_comp,
        "quantifier": quantifier,
        "molecules": molecules,
    }


def _rename_parsed_graph(
    graph: Mapping[str, Any],
    mol_map: Mapping[str, str],
    comp_map: Mapping[str, Mapping[str, str]],
    state_map: Mapping[tuple[str, str], Mapping[str, str]],
    compartment_map: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    cmap = compartment_map or {}
    new_mols = []
    for mol in graph["molecules"]:
        m_type = mol["type"]
        new_type = mol_map.get(m_type, m_type)
        c_sub = comp_map.get(m_type, {})
        new_sites = []
        for site in mol["sites"]:
            c_name = site["comp"]
            new_c = c_sub.get(c_name, c_name)
            st = site["state"]
            if st is not None:
                s_sub = state_map.get((m_type, c_name), {})
                st = s_sub.get(st, st)
            new_sites.append(
                {
                    "comp": new_c,
                    "state": st,
                    "bonds": site["bonds"],
                    "label": site["label"],
                }
            )
        new_mols.append(
            {
                "type": new_type,
                "comp": cmap.get(mol["comp"], mol["comp"]) if mol["comp"] else "",
                "scope": mol["scope"],
                "sites": new_sites,
            }
        )
    sp_comp = graph["species_comp"]
    return {
        "species_comp": cmap.get(sp_comp, sp_comp) if sp_comp else "",
        "quantifier": graph["quantifier"],
        "molecules": new_mols,
    }


def _site_bond_split(bonds: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Separate numeric bond IDs (binders) from non-numeric bond constraints."""
    numeric = tuple(b for b in bonds if b.isdigit())
    wild = tuple(sorted(b for b in bonds if not b.isdigit()))
    return numeric, wild


def _graphs_isomorphic(g1: Mapping[str, Any], g2: Mapping[str, Any]) -> bool:
    """Exact graph isomorphism modulo molecule order, site order, and bond IDs."""
    if g1["species_comp"] != g2["species_comp"] or g1["quantifier"] != g2["quantifier"]:
        return False
    mols1 = g1["molecules"]
    mols2 = g2["molecules"]
    if len(mols1) != len(mols2):
        return False
    if not mols1:
        return True

    def mol_inv(mol: Mapping[str, Any]) -> tuple[Any, ...]:
        site_invs = []
        for s in mol["sites"]:
            num_b, wild_b = _site_bond_split(s["bonds"])
            site_invs.append((s["comp"], s["state"], s["label"], len(num_b), wild_b))
        return (mol["type"], mol["comp"], mol["scope"], tuple(sorted(site_invs)))

    invs1 = [mol_inv(m) for m in mols1]
    invs2 = [mol_inv(m) for m in mols2]
    if sorted(invs1) != sorted(invs2):
        return False

    # Backtracking molecule + site matching carrying exact bond-ID bijection.
    used_m2 = [False] * len(mols2)

    def match_sites(
        sites1: list[dict[str, Any]],
        sites2: list[dict[str, Any]],
        idx: int,
        used_s2: list[bool],
        b_fwd: dict[str, str],
        b_rev: dict[str, str],
        next_mol_fn,
    ) -> bool:
        if idx == len(sites1):
            return next_mol_fn(b_fwd, b_rev)
        s1 = sites1[idx]
        num1, wild1 = _site_bond_split(s1["bonds"])
        for j, s2 in enumerate(sites2):
            if used_s2[j]:
                continue
            num2, wild2 = _site_bond_split(s2["bonds"])
            if (
                s1["comp"] != s2["comp"]
                or s1["state"] != s2["state"]
                or s1["label"] != s2["label"]
                or wild1 != wild2
                or len(num1) != len(num2)
            ):
                continue
            # Match numeric bond binders on this site (usually 0 or 1).
            if not num1:
                used_s2[j] = True
                if match_sites(sites1, sites2, idx + 1, used_s2, b_fwd, b_rev, next_mol_fn):
                    return True
                used_s2[j] = False
            elif len(num1) == 1:
                b1, b2 = num1[0], num2[0]
                if (b1 in b_fwd and b_fwd[b1] != b2) or (
                    b2 in b_rev and b_rev[b2] != b1
                ):
                    continue
                new_fwd = dict(b_fwd)
                new_rev = dict(b_rev)
                new_fwd[b1] = b2
                new_rev[b2] = b1
                used_s2[j] = True
                if match_sites(
                    sites1, sites2, idx + 1, used_s2, new_fwd, new_rev, next_mol_fn
                ):
                    return True
                used_s2[j] = False
            else:
                import itertools

                for perm in itertools.permutations(num2):
                    new_fwd = dict(b_fwd)
                    new_rev = dict(b_rev)
                    ok = True
                    for b1, b2 in zip(num1, perm):
                        if (b1 in new_fwd and new_fwd[b1] != b2) or (
                            b2 in new_rev and new_rev[b2] != b1
                        ):
                            ok = False
                            break
                        new_fwd[b1] = b2
                        new_rev[b2] = b1
                    if ok:
                        used_s2[j] = True
                        if match_sites(
                            sites1,
                            sites2,
                            idx + 1,
                            used_s2,
                            new_fwd,
                            new_rev,
                            next_mol_fn,
                        ):
                            return True
                        used_s2[j] = False
        return False

    def match_mol(m_idx: int, b_fwd: dict[str, str], b_rev: dict[str, str]) -> bool:
        if m_idx == len(mols1):
            return True
        inv = invs1[m_idx]
        m1 = mols1[m_idx]
        for j in range(len(mols2)):
            if used_m2[j] or invs2[j] != inv:
                continue
            used_m2[j] = True
            used_s2 = [False] * len(mols2[j]["sites"])
            if match_sites(
                m1["sites"],
                mols2[j]["sites"],
                0,
                used_s2,
                b_fwd,
                b_rev,
                lambda nf, nr: match_mol(m_idx + 1, nf, nr),
            ):
                return True
            used_m2[j] = False
        return False

    return match_mol(0, {}, {})


def _count_pattern_embeddings(
    pattern: Mapping[str, Any], species: Mapping[str, Any]
) -> int:
    """Count exact injective embeddings of a BNGL pattern into a species graph."""
    if pattern["species_comp"] and species["species_comp"] != pattern["species_comp"]:
        return 0
    pmols = pattern["molecules"]
    smols = species["molecules"]
    if not pmols or len(pmols) > len(smols):
        return 0

    used_m = [False] * len(smols)
    count = 0

    def match_sites(
        psites: list[dict[str, Any]],
        ssites: list[dict[str, Any]],
        s_idx: int,
        used_s: list[bool],
        b_fwd: dict[str, str],
        b_rev: dict[str, str],
        cont,
    ) -> None:
        if s_idx == len(psites):
            cont(b_fwd, b_rev)
            return
        ps = psites[s_idx]
        p_num, p_wild = _site_bond_split(ps["bonds"])
        for j, ss in enumerate(ssites):
            if used_s[j]:
                continue
            if ps["comp"] != ss["comp"]:
                continue
            if ps["state"] is not None and ps["state"] != ss["state"]:
                continue
            s_num, _ = _site_bond_split(ss["bonds"])
            # Bond compatibility:
            if "?" in p_wild:
                # Any bond state allowed.
                used_s[j] = True
                match_sites(psites, ssites, s_idx + 1, used_s, b_fwd, b_rev, cont)
                used_s[j] = False
                continue
            if "+" in p_wild:
                if not s_num:
                    continue
                used_s[j] = True
                match_sites(psites, ssites, s_idx + 1, used_s, b_fwd, b_rev, cont)
                used_s[j] = False
                continue
            if not p_num:
                # Unbound required when no bond wildcard specified.
                if s_num:
                    continue
                used_s[j] = True
                match_sites(psites, ssites, s_idx + 1, used_s, b_fwd, b_rev, cont)
                used_s[j] = False
                continue
            if len(p_num) != len(s_num):
                continue
            if len(p_num) == 1:
                b1, b2 = p_num[0], s_num[0]
                if (b1 in b_fwd and b_fwd[b1] != b2) or (
                    b2 in b_rev and b_rev[b2] != b1
                ):
                    continue
                nf = dict(b_fwd)
                nr = dict(b_rev)
                nf[b1] = b2
                nr[b2] = b1
                used_s[j] = True
                match_sites(psites, ssites, s_idx + 1, used_s, nf, nr, cont)
                used_s[j] = False

    def match_mol(m_idx: int, b_fwd: dict[str, str], b_rev: dict[str, str]) -> None:
        nonlocal count
        if m_idx == len(pmols):
            count += 1
            return
        pm = pmols[m_idx]
        for j, sm in enumerate(smols):
            if used_m[j]:
                continue
            if pm["type"] != sm["type"]:
                continue
            if pm["comp"] and pm["comp"] != sm["comp"]:
                continue
            used_m[j] = True
            used_s = [False] * len(sm["sites"])
            match_sites(
                pm["sites"],
                sm["sites"],
                0,
                used_s,
                b_fwd,
                b_rev,
                lambda nf, nr: match_mol(m_idx + 1, nf, nr),
            )
            used_m[j] = False

    match_mol(0, {}, {})
    return count


def _enumerate_signature_renamings(
    left_model: Any,
    right_model: Any,
    max_candidates: int = 4096,
) -> tuple[
    list[tuple[dict[str, str], dict[str, dict[str, str]], dict[tuple[str, str], dict[str, str]]]],
    bool,
]:
    """Enumerate consistent (molecule, component, state) bijections up to budget."""
    import itertools

    left_types = list(left_model._model.molecule_types)
    right_types = list(right_model._model.molecule_types)
    if len(left_types) != len(right_types):
        return [], False

    def type_shape(mt: Any) -> tuple[bool, tuple[int, ...]]:
        return (
            bool(mt.is_population),
            tuple(sorted(len(c.allowed_states) for c in mt.components)),
        )

    l_by_shape: dict[tuple[bool, tuple[int, ...]], list[Any]] = {}
    r_by_shape: dict[tuple[bool, tuple[int, ...]], list[Any]] = {}
    for mt in left_types:
        l_by_shape.setdefault(type_shape(mt), []).append(mt)
    for mt in right_types:
        r_by_shape.setdefault(type_shape(mt), []).append(mt)
    if set(l_by_shape) != set(r_by_shape) or any(
        len(l_by_shape[k]) != len(r_by_shape[k]) for k in l_by_shape
    ):
        return [], False

    def comp_state_renamings(
        l_mt: Any, r_mt: Any, budget: int
    ) -> tuple[list[tuple[dict[str, str], dict[tuple[str, str], dict[str, str]]]], bool]:
        l_by_arity: dict[int, list[Any]] = {}
        r_by_arity: dict[int, list[Any]] = {}
        for c in l_mt.components:
            l_by_arity.setdefault(len(c.allowed_states), []).append(c)
        for c in r_mt.components:
            r_by_arity.setdefault(len(c.allowed_states), []).append(c)

        results: list[tuple[dict[str, str], dict[tuple[str, str], dict[str, str]]]] = [
            ({}, {})
        ]
        for arity in sorted(l_by_arity):
            lc_list = l_by_arity[arity]
            rc_list = r_by_arity[arity]
            next_results: list[
                tuple[dict[str, str], dict[tuple[str, str], dict[str, str]]]
            ] = []
            for perm_c in itertools.permutations(rc_list):
                pair_state_options: list[list[dict[str, str]]] = []
                for lc, rc in zip(lc_list, perm_c):
                    l_states = list(lc.allowed_states)
                    r_states = list(rc.allowed_states)
                    if not l_states:
                        pair_state_options.append([{}])
                    else:
                        opts = [
                            dict(zip(l_states, sp))
                            for sp in itertools.permutations(r_states)
                        ]
                        pair_state_options.append(opts)
                for state_choice in itertools.product(*pair_state_options):
                    for cur_c, cur_s in results:
                        nc = dict(cur_c)
                        ns = dict(cur_s)
                        for lc, rc, smap in zip(lc_list, perm_c, state_choice):
                            nc[lc.name] = rc.name
                            if smap:
                                ns[(l_mt.name, lc.name)] = smap
                        next_results.append((nc, ns))
                        if len(next_results) > budget:
                            return next_results[:budget], True
            results = next_results
        return results, False

    candidates: list[
        tuple[
            dict[str, str],
            dict[str, dict[str, str]],
            dict[tuple[str, str], dict[str, str]],
        ]
    ] = [({}, {}, {})]
    truncated = False
    for shape in sorted(l_by_shape):
        l_group = l_by_shape[shape]
        r_group = r_by_shape[shape]
        next_candidates = []
        for perm_m in itertools.permutations(r_group):
            per_pair_options = []
            for l_mt, r_mt in zip(l_group, perm_m):
                opts, sub_trunc = comp_state_renamings(l_mt, r_mt, max_candidates)
                if sub_trunc:
                    truncated = True
                per_pair_options.append((l_mt.name, r_mt.name, opts))
            for combo in itertools.product(*(item[2] for item in per_pair_options)):
                for cur_m, cur_c, cur_s in candidates:
                    nm = dict(cur_m)
                    nc = dict(cur_c)
                    ns = dict(cur_s)
                    for (lm_name, rm_name, _), (c_sub, s_sub) in zip(
                        per_pair_options, combo
                    ):
                        nm[lm_name] = rm_name
                        nc[lm_name] = c_sub
                        ns.update(s_sub)
                    next_candidates.append((nm, nc, ns))
                    if len(next_candidates) > max_candidates:
                        return next_candidates[:max_candidates], True
        candidates = next_candidates
    return candidates, truncated


def _match_observables_exact(
    left_obs: list[Any],
    right_obs: list[Any],
    mol_map: Mapping[str, str],
    comp_map: Mapping[str, Mapping[str, str]],
    state_map: Mapping[tuple[str, str], Mapping[str, str]],
    compartment_map: Mapping[str, str] | None = None,
) -> tuple[bool, dict[str, str]]:
    """Match observables bijectively via exact graph isomorphism of patterns."""
    if len(left_obs) != len(right_obs):
        return False, {}
    if not left_obs:
        return True, {}

    def parsed_list(obs: Any, do_rename: bool) -> list[dict[str, Any]] | None:
        out = []
        for p in obs.patterns:
            g = _parse_graph_pattern(p)
            if g is None:
                return None
            if do_rename:
                g = _rename_parsed_graph(g, mol_map, comp_map, state_map, compartment_map)
            out.append(g)
        return out

    def patterns_bijective(
        l_graphs: list[dict[str, Any]], r_graphs: list[dict[str, Any]]
    ) -> bool:
        if len(l_graphs) != len(r_graphs):
            return False
        m = len(l_graphs)
        adj_p = [
            [j for j in range(m) if _graphs_isomorphic(l_graphs[i], r_graphs[j])]
            for i in range(m)
        ]
        match_r = [-1] * m

        def dfs_p(u: int, vis: list[bool]) -> bool:
            for v in adj_p[u]:
                if not vis[v]:
                    vis[v] = True
                    if match_r[v] < 0 or dfs_p(match_r[v], vis):
                        match_r[v] = u
                        return True
            return False

        return all(dfs_p(u, [False] * m) for u in range(m))

    l_parsed = [parsed_list(o, True) for o in left_obs]
    r_parsed = [parsed_list(o, False) for o in right_obs]
    if any(p is None for p in l_parsed) or any(p is None for p in r_parsed):
        return False, {}

    n = len(left_obs)
    adj: list[list[int]] = []
    for i, o_l in enumerate(left_obs):
        edges = []
        for j, o_r in enumerate(right_obs):
            if o_l.type == o_r.type and patterns_bijective(l_parsed[i], r_parsed[j]):
                edges.append(j)
        adj.append(edges)

    match_r = [-1] * n

    def dfs(u: int, visited: list[bool]) -> bool:
        for v in adj[u]:
            if not visited[v]:
                visited[v] = True
                if match_r[v] < 0 or dfs(match_r[v], visited):
                    match_r[v] = u
                    return True
        return False

    for u in range(n):
        if not dfs(u, [False] * n):
            return False, {}

    obs_map = {left_obs[match_r[j]].name: right_obs[j].name for j in range(n)}
    return True, obs_map


# ---------------------------------------------------------------------------
# Exact Lindemann-Weierstrass / TFUN / rational hazard representation
# ---------------------------------------------------------------------------

_PolyExp = tuple[tuple[Fraction, Fraction], ...]


def _poly_exp_add(a: _PolyExp, b: _PolyExp) -> _PolyExp:
    acc: dict[Fraction, Fraction] = dict(a)
    for exp_arg, coeff in b:
        acc[exp_arg] = acc.get(exp_arg, Fraction(0)) + coeff
    return tuple(sorted((e, c) for e, c in acc.items() if c != 0))


def _poly_exp_scale(a: _PolyExp, factor: Fraction) -> _PolyExp:
    if factor == 0:
        return ()
    return tuple((e, c * factor) for e, c in a)


def _hazard_add(h1: tuple[Any, ...], h2: tuple[Any, ...]) -> tuple[Any, ...] | None:
    if h1[0] == "poly_exp" and h2[0] == "poly_exp":
        return ("poly_exp", _poly_exp_add(h1[1], h2[1]))
    if h1[0] == "tfun" and h2[0] == "tfun" and h1[1] == h2[1]:
        s = h1[2] + h2[2]
        return ("poly_exp", ()) if s == 0 else ("tfun", h1[1], s)
    if h1[0] == "rational" and h2[0] == "rational":
        r1: _RationalExpr = h1[1]
        r2: _RationalExpr = h2[1]
        summed = _RationalExpr(
            _poly_add(_poly_mul(r1.num, r2.den), _poly_mul(r2.num, r1.den)),
            _poly_mul(r1.den, r2.den),
            r1.poles | r2.poles,
        )
        return ("rational", summed)
    return None


def _hazard_is_zero(h: tuple[Any, ...]) -> bool:
    if h[0] == "poly_exp":
        return len(h[1]) == 0
    if h[0] == "tfun":
        return h[2] == 0
    if h[0] == "rational":
        return _poly_is_zero(h[1].num)
    return False


def _hazard_scale(h: tuple[Any, ...], factor: Fraction) -> tuple[Any, ...]:
    if h[0] == "poly_exp":
        return ("poly_exp", _poly_exp_scale(h[1], factor))
    if h[0] == "tfun":
        return ("poly_exp", ()) if factor == 0 else ("tfun", h[1], h[2] * factor)
    if h[0] == "rational":
        r: _RationalExpr = h[1]
        return (
            "rational",
            _RationalExpr(_poly_scale(r.num, factor), r.den, r.poles),
        )
    return h


def _hazard_key(h: tuple[Any, ...]) -> Any:
    if h[0] == "rational":
        return ("rational", h[1].key())
    return h


def _compartment_unit_conversion_exact(
    reactants: tuple[str, ...],
    products: tuple[str, ...],
    compartments: Mapping[str, tuple[int, Fraction]],
    is_total_rate: bool,
) -> tuple[Fraction, bool]:
    """Compute exact BNG2/BNG3 compartment unit-conversion factor.

    Returns (factor, scaled_by_volume) where scaled_by_volume is True when a
    compartment volume non-trivially enters the propensity.
    """
    if is_total_rate or not compartments:
        return Fraction(1), False

    def species_comp(sp: str) -> str:
        g = _parse_graph_pattern(sp)
        if g is None:
            return ""
        if g["species_comp"]:
            return g["species_comp"]
        for m in g["molecules"]:
            if m["comp"]:
                return m["comp"]
        return ""

    if reactants:
        rc: list[tuple[int, Fraction]] = []
        for sp in reactants:
            cname = species_comp(sp)
            if cname in compartments:
                rc.append(compartments[cname])
        if len(rc) <= 1:
            return Fraction(1), False
        # Anchor first 2D surface, else first 3D volume, else first reactant.
        anchor = None
        for idx, (dim, _) in enumerate(rc):
            if dim == 2:
                anchor = idx
                break
        if anchor is None:
            for idx, (dim, _) in enumerate(rc):
                if dim == 3:
                    anchor = idx
                    break
        if anchor is None:
            anchor = 0
        factor = Fraction(1)
        for idx, (_, vol) in enumerate(rc):
            if idx != anchor:
                if vol == 0:
                    raise ValueError("zero compartment volume")
                factor /= vol
        return factor, True

    if products:
        for sp in products:
            cname = species_comp(sp)
            if cname in compartments:
                return compartments[cname][1], True
    return Fraction(1), False


def _rename_reaction_center_key(
    center: str,
    mol_map: Mapping[str, str],
    comp_map: Mapping[str, Mapping[str, str]],
    state_map: Mapping[tuple[str, str], Mapping[str, str]],
) -> str | None:
    """Rename a canonical C++ BarrierTable ReactionCenterKey string."""
    if ":" not in center or "|" not in center:
        return None
    kind, rest = center.split(":", 1)
    left_half, right_half = rest.split("|", 1)
    if kind == "bond":
        if "." not in left_half or "." not in right_half:
            return None
        ta, sa = left_half.split(".", 1)
        tb, sb = right_half.split(".", 1)
        nta = mol_map.get(ta, ta)
        nsa = comp_map.get(ta, {}).get(sa, sa)
        ntb = mol_map.get(tb, tb)
        nsb = comp_map.get(tb, {}).get(sb, sb)
        halves = sorted([(nta, nsa), (ntb, nsb)])
        return f"bond:{halves[0][0]}.{halves[0][1]}|{halves[1][0]}.{halves[1][1]}"
    if kind == "state":
        if "." not in left_half or "~" not in left_half or "~" not in right_half:
            return None
        ta, site_sa = left_half.split(".", 1)
        sa, st_a = site_sa.split("~", 1)
        tb, site_sb = right_half.split(".", 1)
        sb, st_b = site_sb.split("~", 1)
        nta = mol_map.get(ta, ta)
        nsa = comp_map.get(ta, {}).get(sa, sa)
        n_sta = state_map.get((ta, sa), {}).get(st_a, st_a)
        n_stb = state_map.get((tb, sb), {}).get(st_b, st_b)
        s1, s2 = sorted([n_sta, n_stb])
        return f"state:{nta}.{nsa}~{s1}|{nta}.{nsa}~{s2}"
    return None


def _reaction_center_for_jump(
    reactants: tuple[str, ...], products: tuple[str, ...]
) -> str | None:
    """Derive canonical ReactionCenterKey for simple state-change / binding jumps."""
    if len(reactants) == 1 and len(products) == 1:
        gr = _parse_graph_pattern(reactants[0])
        gp = _parse_graph_pattern(products[0])
        if gr and gp and len(gr["molecules"]) == 1 and len(gp["molecules"]) == 1:
            mr, mp = gr["molecules"][0], gp["molecules"][0]
            if mr["type"] == mp["type"]:
                rs = {s["comp"]: s["state"] for s in mr["sites"]}
                ps = {s["comp"]: s["state"] for s in mp["sites"]}
                diffs = [
                    (c, rs[c], ps[c])
                    for c in rs
                    if c in ps and rs[c] is not None and ps[c] is not None and rs[c] != ps[c]
                ]
                if len(diffs) == 1:
                    c, s1, s2 = diffs[0]
                    a, b = sorted([s1, s2])
                    return f"state:{mr['type']}.{c}~{a}|{mr['type']}.{c}~{b}"
    return None


def _parse_arrhenius_args(rate_law_str: str) -> tuple[str, str] | None:
    """Extract (phi_expr, Ea_expr) from an Arrhenius(phi, Ea) rate string."""
    s = rate_law_str.strip()
    m = re.fullmatch(r"(?i)arrhenius\s*\((.*)\)", s)
    if not m:
        return None
    inner = m.group(1)
    depth = 0
    split_pos = -1
    for i, ch in enumerate(inner):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            if split_pos != -1:
                return None
            split_pos = i
    if split_pos == -1:
        return None
    return inner[:split_pos].strip(), inner[split_pos + 1 :].strip()


def _canonical_seed_identity(model: Any, seed: Any) -> str | None:
    """Return the network identity of a seed using native graph canonicalization.

    Seed patterns keep the bond numbers written in the source, while generated
    species are named with BNG2-canonical bond numbers. String-matching the two
    silently drops seeds whose bonds were renumbered, which can manufacture a
    false equivalence certificate. Round-tripping a single seed through the
    native parser and network generator yields the same canonical identity that
    the full network reports, without reimplementing canonicalization in Python.
    """
    from .model import BioNetGenModel, _cpp

    lines: list[str] = ["begin model"]
    compartments = list(model._model.compartments)
    if compartments:
        lines.append("begin compartments")
        for compartment in compartments:
            lines.append(
                f"  {compartment.name} {compartment.dimension} {compartment.volume}"
            )
        lines.append("end compartments")
    lines.append("begin molecule types")
    for molecule_type in model._model.molecule_types:
        components = []
        for component in molecule_type.components:
            states = list(component.allowed_states)
            components.append(
                component.name + (("~" + "~".join(states)) if states else "")
            )
        name = molecule_type.name
        definition = (
            f"  {name}({','.join(components)})" if components else f"  {name}()"
        )
        if molecule_type.is_population:
            definition += " population"
        lines.append(definition)
    lines.append("end molecule types")

    pattern = seed.pattern
    if seed.compartment and "@" not in pattern:
        pattern = f"@{seed.compartment}:{pattern}"
    if pattern.startswith("$"):
        pattern = pattern[1:]
    lines.append("begin seed species")
    lines.append(f"  {pattern} 1")
    lines.append("end seed species")
    lines.append("end model")
    source = "\n".join(lines) + "\n"
    try:
        canonical = list(
            BioNetGenModel(_cpp.parse_string(source)).generate_network().species_names
        )
    except Exception:
        return None
    return canonical[0] if len(canonical) == 1 else None


def _extract_jump_hazards(
    model: Any,
    *,
    structural_doc: Mapping[str, Any] | None = None,
    apply_volume_scaling: bool = False,
    obs_renaming: Mapping[str, str] | None = None,
) -> tuple[
    dict[tuple[Any, ...], tuple[Any, ...]],
    dict[str, Fraction],
    list[str],
    bool,
    bool,
    bool,
]:
    """Extract exact symbolic/rational jump hazards and completeness signals.

    Jump keys have the form:
      (reactants, products, delay_or_None, non_consuming_bool, directed_work_or_0)
    where immediate self-loops (reactants == products and delay is None) are
    omitted.  Returns (jumps, init_counts, species_names, converged, pruned,
    any_volume_scaled).
    """
    param_dict = {p.name: Fraction(str(p.value)) for p in model.parameters}
    zero_arg_fn_bodies = {
        f.name: f.expression.to_string()
        for f in model._model.functions
        if not f.args
    }
    obs_names = frozenset(o.name for o in model._model.observables)

    # Index inline TFUN nullary functions from the v0.2 structural snapshot.
    tfun_fn_map: dict[
        str, tuple[tuple[str, str], str, tuple[tuple[Fraction, Fraction], ...]]
    ] = {}
    if structural_doc is not None:
        for fn_doc in structural_doc.get("functions", []):
            if not fn_doc.get("arguments"):
                norm_tfun = _normalize_inline_tfun_doc(
                    fn_doc.get("expression", {}), structural_doc, obs_renaming
                )
                if norm_tfun is not None:
                    tfun_fn_map[str(fn_doc["name"])] = norm_tfun

    equality_max_iter = _EQUALITY_NETWORK_MAX_ITER
    for action in getattr(model._model, "actions", []):
        if action.name == "generate_network" and "max_iter" in action.arguments:
            try:
                equality_max_iter = int(action.arguments["max_iter"])
            except (TypeError, ValueError):
                pass
            break
    net = model.generate_network(max_iter=equality_max_iter)
    species_names = list(net.species_names)

    init_counts: dict[str, Fraction] = {sp: Fraction(0) for sp in species_names}
    for seed in model._model.seed_species:
        amount_val = _evaluate_model_expression_exact(
            seed.amount.to_string(), param_dict, zero_arg_fn_bodies
        )
        identity = _canonical_seed_identity(model, seed)
        if identity is None or identity not in init_counts:
            raise EqualityUndecided(
                "A seed species has no canonical identity in the generated network",
                {
                    "seed_pattern": seed.pattern,
                    "seed_compartment": seed.compartment,
                    "canonical_identity": identity,
                },
            )
        init_counts[identity] += amount_val

    # Map authored rules by rule_name to recover delay, non_consuming,
    # TotalRate, and driving_work metadata per generated reaction.
    rules_by_name = {r.rule_name: r for r in model._model.reaction_rules}
    rxn_rule_names = list(getattr(net, "reaction_rules", []))

    # Precompute exact species energies when energy_patterns exist.
    species_energies: dict[str, Fraction] = {}
    if model._model.energy_patterns:
        parsed_ep = []
        v02_eps = (structural_doc or {}).get("energy_patterns") or []
        for ep_idx, ep in enumerate(model._model.energy_patterns):
            ep_graph = None
            if ep_idx < len(v02_eps) and isinstance(v02_eps[ep_idx], Mapping):
                ep_graph = _graph_from_v02_pattern(v02_eps[ep_idx].get("pattern", {}))
            if ep_graph is None:
                ep_graph = _parse_graph_pattern(ep.pattern)
            if ep_graph is None:
                raise EqualityUndecided(
                    "Energy pattern could not be parsed for exact delta calculation",
                    {"pattern": ep.pattern},
                )
            ep_val = _evaluate_model_expression_exact(
                ep.expression.to_string(), param_dict, zero_arg_fn_bodies
            )
            parsed_ep.append((ep_graph, ep_val))
        for sp in species_names:
            sp_graph = _parse_graph_pattern(sp)
            if sp_graph is None:
                raise EqualityUndecided(
                    "Species graph could not be parsed for exact energy calculation",
                    {"species": sp},
                )
            total_e = Fraction(0)
            for ep_graph, ep_val in parsed_ep:
                total_e += Fraction(_count_pattern_embeddings(ep_graph, sp_graph)) * ep_val
            species_energies[sp] = total_e

    # Precompute canonical barrier energies by ReactionCenterKey when present.
    barrier_by_center: dict[str, Fraction] = {}
    if structural_doc is not None and structural_doc.get("barrier_patterns"):
        for bp_doc in structural_doc.get("barrier_patterns", []):
            center = str(bp_doc.get("reaction_center") or "")
            if not center or not bp_doc.get("center_resolved"):
                raise EqualityUndecided(
                    "Barrier pattern lacks a resolved reaction center",
                    {"barrier": bp_doc},
                )
            expr_text = bp_doc.get("expression", "")
            b_val = _evaluate_model_expression_exact(
                str(expr_text), param_dict, zero_arg_fn_bodies
            )
            barrier_by_center[center] = barrier_by_center.get(center, Fraction(0)) + b_val

    compartments_map: dict[str, tuple[int, Fraction]] = {
        c.name: (int(c.dimension), Fraction(str(float(c.volume))))
        for c in model._model.compartments
    }

    jump_hazards: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    rxn_participants = net.reaction_participants
    rate_laws = net.reaction_rate_laws
    factors = net.reaction_factors
    any_volume_scaled = False

    for idx, (reactants_idx, products_idx) in enumerate(rxn_participants):
        reactants = tuple(sorted(species_names[i] for i in reactants_idx))
        products = tuple(sorted(species_names[i] for i in products_idx))

        raw_rule_name = rxn_rule_names[idx] if idx < len(rxn_rule_names) else ""
        is_reverse = raw_rule_name.startswith("_reverse__")
        base_rule_name = raw_rule_name[len("_reverse__") :] if is_reverse else raw_rule_name
        rule_obj = rules_by_name.get(base_rule_name)

        delay_spec: Fraction | None = None
        non_consuming = False
        directed_work = Fraction(0)
        is_total_rate = False
        if rule_obj is not None:
            if rule_obj.has_delay and rule_obj.delay_expression is not None:
                delay_spec = _evaluate_model_expression_exact(
                    str(rule_obj.delay_expression), param_dict, zero_arg_fn_bodies
                )
            non_consuming = bool(rule_obj.is_non_consuming)
            if rule_obj.has_driving_work and rule_obj.driving_work:
                w_val = _evaluate_model_expression_exact(
                    str(rule_obj.driving_work), param_dict, zero_arg_fn_bodies
                )
                directed_work = -w_val if is_reverse else w_val
            is_total_rate = any(
                str(m).strip().lower() == "totalrate" for m in rule_obj.modifiers
            )

        # Immediate self-loops leave the molecular state unchanged.
        if reactants == products and delay_spec is None:
            continue

        rate_law_str = rate_laws[idx]
        factor = Fraction(str(factors[idx]))

        vol_factor = Fraction(1)
        if apply_volume_scaling:
            vol_factor, was_scaled = _compartment_unit_conversion_exact(
                reactants, products, compartments_map, is_total_rate
            )
            if was_scaled:
                any_volume_scaled = True

        arr_args = _parse_arrhenius_args(rate_law_str)
        hazard: tuple[Any, ...] | None = None
        work_key = directed_work
        if arr_args is not None:
            phi_val = _evaluate_model_expression_exact(
                arr_args[0], param_dict, zero_arg_fn_bodies
            )
            ea_val = _evaluate_model_expression_exact(
                arr_args[1], param_dict, zero_arg_fn_bodies
            )
            dir_phi = (Fraction(1) - phi_val) if is_reverse else phi_val
            dg = sum((species_energies.get(sp, Fraction(0)) for sp in products), Fraction(0)) - sum(
                (species_energies.get(sp, Fraction(0)) for sp in reactants), Fraction(0)
            )
            gb = Fraction(0)
            if barrier_by_center:
                center = _reaction_center_for_jump(reactants, products)
                if center is None:
                    raise EqualityUndecided(
                        "Barrier energy lookup requires a resolved jump reaction center",
                        {"reactants": reactants, "products": products},
                    )
                gb = barrier_by_center.get(center, Fraction(0))
            exponent = -(ea_val + gb + dir_phi * (dg - directed_work))
            hazard = ("poly_exp", ((exponent, factor * vol_factor),))
            # Driving work is already folded into the exact Arrhenius exponent.
            work_key = Fraction(0)
        else:
            # Check direct inline TFUN nullary function reference (e.g. f or f()).
            bare_fn = rate_law_str.strip()
            if bare_fn.endswith("()"):
                bare_fn = bare_fn[:-2].strip()
            if bare_fn in tfun_fn_map:
                tfun_norm = tfun_fn_map[bare_fn]
                if tfun_norm[1] == "const":
                    c_val = tfun_norm[2][0][1] * factor * vol_factor
                    hazard = (
                        ("poly_exp", ((Fraction(0), c_val),))
                        if c_val != 0
                        else ("poly_exp", ())
                    )
                else:
                    hazard = ("tfun", tfun_norm, factor * vol_factor)
            else:
                try:
                    rate_val = (
                        _evaluate_model_expression_exact(
                            rate_law_str, param_dict, zero_arg_fn_bodies
                        )
                        * factor
                        * vol_factor
                    )
                    hazard = (
                        ("poly_exp", ((Fraction(0), rate_val),))
                        if rate_val != 0
                        else ("poly_exp", ())
                    )
                except ValueError:
                    # Try exact rational expression over observables + bound parameters.
                    if obs_names:
                        rat = _parse_rational_expr(
                            rate_law_str,
                            allowed_vars=frozenset(param_dict) | obs_names,
                            zero_arg_functions=zero_arg_fn_bodies,
                            var_renaming=obs_renaming,
                        )
                        if rat is not None:
                            hazard = _hazard_scale(("rational", rat), factor * vol_factor)
                    if hazard is None:
                        raise

        key = (reactants, products, delay_spec, non_consuming, work_key)
        if key in jump_hazards:
            combined = _hazard_add(jump_hazards[key], hazard)
            if combined is None:
                raise EqualityUndecided(
                    "Cannot combine heterogeneous hazard classes on the same jump",
                    {"jump": key},
                )
            jump_hazards[key] = combined
        else:
            jump_hazards[key] = hazard

    jump_hazards = {k: v for k, v in jump_hazards.items() if not _hazard_is_zero(v)}

    return (
        jump_hazards,
        init_counts,
        species_names,
        net.generation_converged,
        net.generation_pruned_species,
        any_volume_scaled,
    )


def _volume_rhs_counterexample(left_model: Any, right_model: Any) -> dict | None:
    """Decide inequality when only compartment volumes change the initial RHS."""
    try:
        from .model import _cpp

        left_jumps, left_init, left_species, left_ok, left_pruned, _ = (
            _extract_jump_hazards(left_model)
        )
        right_jumps, right_init, right_species, right_ok, right_pruned, _ = (
            _extract_jump_hazards(right_model)
        )
    except Exception:
        return None
    if (
        not (left_ok and right_ok)
        or left_pruned
        or right_pruned
        or {k: _hazard_key(v) for k, v in left_jumps.items()}
        != {k: _hazard_key(v) for k, v in right_jumps.items()}
        or set(left_species) != set(right_species)
        or set(left_species) != set(left_init)
        or set(right_species) != set(right_init)
    ):
        return None
    ordered = sorted(left_species)
    state = [float(left_init[name]) for name in ordered]
    try:
        left_net = left_model.generate_network(max_iter=_EQUALITY_NETWORK_MAX_ITER)
        right_net = right_model.generate_network(max_iter=_EQUALITY_NETWORK_MAX_ITER)
        left_rhs = _cpp._validation_ode_rhs(left_model._model, left_net, 0.0, state)
        right_rhs = _cpp._validation_ode_rhs(right_model._model, right_net, 0.0, state)
    except Exception:
        return None
    if [name for name in left_net.species_names] != ordered or [
        name for name in right_net.species_names
    ] != ordered:
        return None
    for name, a, b in zip(ordered, left_rhs, right_rhs):
        left_value = Fraction(str(float(a)))
        right_value = Fraction(str(float(b)))
        if left_value != right_value:
            return {
                "species": name,
                "left_rhs": str(left_value),
                "right_rhs": str(right_value),
            }
    return None


def _initial_state_counterexample(
    left_model: Any,
    right_model: Any,
    *,
    left_structural: Mapping[str, Any] | None = None,
    right_structural: Mapping[str, Any] | None = None,
    apply_volume_scaling: bool = False,
) -> dict | None:
    """Find an enabled jump that differs between two identically labelled models.

    Only complete, unpruned networks with the same species labels are compared,
    and the jump must be enabled by the initial state.  Such a difference is a
    decisive counterexample to equality of the initialized process generator.
    Cases outside this narrow contract stay unresolved.
    """
    from collections import Counter

    try:
        left_jumps, left_init, left_species, left_complete, left_pruned, _ = (
            _extract_jump_hazards(
                left_model,
                structural_doc=left_structural,
                apply_volume_scaling=apply_volume_scaling,
            )
        )
        right_jumps, right_init, right_species, right_complete, right_pruned, _ = (
            _extract_jump_hazards(
                right_model,
                structural_doc=right_structural,
                apply_volume_scaling=apply_volume_scaling,
            )
        )
    except Exception:
        return None
    if not (left_complete and right_complete) or left_pruned or right_pruned:
        return None
    left_types = {t.name for t in left_model._model.molecule_types}
    right_types = {t.name for t in right_model._model.molecule_types}
    if left_types != right_types:
        return None

    def enabled(key, init) -> bool:
        return all(
            init.get(species, 0) >= count for species, count in Counter(key[0]).items()
        )

    if set(left_species) != set(right_species):
        if not (
            set(left_species) < set(right_species)
            or set(right_species) < set(left_species)
        ):
            return None
        for jumps, init, other_species, side in (
            (left_jumps, left_init, set(right_species), "left"),
            (right_jumps, right_init, set(left_species), "right"),
        ):
            for key, rate in jumps.items():
                if not enabled(key, init):
                    continue
                missing = sorted(set(key[1]) - other_species)
                if missing:
                    return {
                        "jump": [list(key[0]), list(key[1])],
                        "missing_product_species": missing,
                        "side": side,
                        "rate": str(rate),
                    }
        return None

    for key, left_rate in left_jumps.items():
        if not enabled(key, left_init):
            continue
        right_rate = right_jumps.get(key)
        if right_rate is None:
            return {
                "jump": [list(key[0]), list(key[1])],
                "left_rate": str(left_rate),
                "right_rate": "0",
            }
        if _hazard_key(right_rate) != _hazard_key(left_rate):
            if left_rate[0] == "poly_exp" and right_rate[0] == "poly_exp":
                return {
                    "jump": [list(key[0]), list(key[1])],
                    "left_rate": str(left_rate),
                    "right_rate": str(right_rate),
                }
            if left_rate[0] == "tfun" and right_rate[0] == "tfun":
                if left_rate[2] == right_rate[2]:
                    w = _tfun_counterexample(left_rate[1], right_rate[1])
                    if w is not None:
                        return w
                else:
                    return {
                        "jump": [list(key[0]), list(key[1])],
                        "left_rate": str(left_rate),
                        "right_rate": str(right_rate),
                    }
    for key in right_jumps:
        if key not in left_jumps and enabled(key, right_init):
            return {
                "jump": [list(key[0]), list(key[1])],
                "left_rate": "0",
                "right_rate": str(right_jumps[key]),
            }
    return None


def _compare_functions_exact(
    left_model: Any,
    right_model: Any,
    left_structural: Mapping[str, Any],
    right_structural: Mapping[str, Any],
    obs_renaming: Mapping[str, str] | None = None,
) -> tuple[bool | None, dict[str, Any]]:
    """Compare function tables F exactly.

    Returns (True, {}) when every function has a verified equivalence
    certificate, (False, witness) when a verified counterexample exists, and
    (None, diagnostic) when undecided.
    """
    left_fns = {f.name: f for f in left_model._model.functions}
    right_fns = {f.name: f for f in right_model._model.functions}
    left_docs = {
        str(f["name"]): f for f in left_structural.get("functions", [])
    }
    right_docs = {
        str(f["name"]): f for f in right_structural.get("functions", [])
    }
    left_zero_bodies = {
        f.name: f.expression.to_string()
        for f in left_model._model.functions
        if not f.args
    }
    right_zero_bodies = {
        f.name: f.expression.to_string()
        for f in right_model._model.functions
        if not f.args
    }
    left_params = {p.name: Fraction(str(p.value)) for p in left_model.parameters}
    right_params = {p.name: Fraction(str(p.value)) for p in right_model.parameters}
    left_obs = frozenset(o.name for o in left_model._model.observables)
    right_obs = frozenset(o.name for o in right_model._model.observables)

    if set(left_fns) != set(right_fns):
        return None, {
            "left_functions": sorted(left_fns),
            "right_functions": sorted(right_fns),
        }

    if not left_fns:
        return True, {}

    all_equal = True
    for name in sorted(left_fns):
        lf = left_fns[name]
        rf = right_fns[name]
        l_args = tuple(lf.args)
        r_args = tuple(rf.args)
        l_body = lf.expression.to_string()
        r_body = rf.expression.to_string()
        if len(l_args) != len(r_args):
            return None, {"function": name, "left_args": l_args, "right_args": r_args}

        # Exact identical syntax (including same argument names) without renamed obs.
        if l_args == r_args and l_body == r_body and not (
            obs_renaming and any(k != v for k, v in obs_renaming.items())
        ):
            continue

        # Functions with formal arguments: certify alpha-equivalent rational
        # expressions; leave differing parameterized functions undecided.
        if l_args:
            l_rename = {a: f"__arg_{i}" for i, a in enumerate(l_args)}
            r_rename = {a: f"__arg_{i}" for i, a in enumerate(r_args)}
            if obs_renaming:
                l_rename.update(obs_renaming)
            l_rat = _parse_rational_expr(
                l_body,
                allowed_vars=frozenset(left_params) | left_obs | frozenset(l_args),
                zero_arg_functions=left_zero_bodies,
                var_renaming=l_rename,
            )
            r_rat = _parse_rational_expr(
                r_body,
                allowed_vars=frozenset(right_params) | right_obs | frozenset(r_args),
                zero_arg_functions=right_zero_bodies,
                var_renaming=r_rename,
            )
            if l_rat is not None and r_rat is not None and l_rat.key() == r_rat.key():
                continue
            all_equal = False
            continue

        # Nullary inline TFUN comparison (EQ-time).
        l_tfun = _normalize_inline_tfun_doc(
            left_docs.get(name, {}).get("expression", {}),
            left_structural,
            obs_renaming,
        )
        r_tfun = _normalize_inline_tfun_doc(
            right_docs.get(name, {}).get("expression", {}),
            right_structural,
            None,
        )
        if l_tfun is not None and r_tfun is not None:
            if l_tfun == r_tfun:
                continue
            witness = _tfun_counterexample(l_tfun, r_tfun)
            if witness is not None:
                return False, {"function": name, **witness}
            all_equal = False
            continue

        # Nullary exact rational expression comparison with pole checks.
        l_rat = _parse_rational_expr(
            l_body,
            allowed_vars=frozenset(left_params) | left_obs,
            zero_arg_functions=left_zero_bodies,
            var_renaming=obs_renaming,
        )
        r_rat = _parse_rational_expr(
            r_body,
            allowed_vars=frozenset(right_params) | right_obs,
            zero_arg_functions=right_zero_bodies,
            var_renaming=None,
        )
        if l_rat is not None and r_rat is not None:
            if l_rat.key() == r_rat.key():
                continue
            # Check for an explicit rational counterexample (either value
            # mismatch or definedness/pole mismatch at an admissible point).
            all_vars = sorted(l_rat.variables() | r_rat.variables())
            # 1) Test bound parameter values + admissible non-negative counts (0, 1, 2, 3, 5).
            bound_map: dict[str, Fraction] = {}
            for v in all_vars:
                if v in left_params and v in right_params and left_params[v] == right_params[v]:
                    bound_map[v] = left_params[v]
                elif v in left_params:
                    bound_map[v] = left_params[v]
                elif v in right_params:
                    bound_map[v] = right_params[v]
            # Test distinct prime/integer assignments including 0 for observables/bound zeros.
            primes = (2, 3, 5, 7, 11, 13, 17, 19)
            probe_assignments: list[dict[str, Fraction]] = []
            if len(bound_map) == len(all_vars):
                probe_assignments.append(dict(bound_map))
            # Check with 0 on each variable that is an observable or bound to 0.
            for zero_var in all_vars:
                if zero_var in right_obs or bound_map.get(zero_var) == 0:
                    a = {
                        v: (Fraction(0) if v == zero_var else Fraction(primes[i % len(primes)]))
                        for i, v in enumerate(all_vars)
                    }
                    probe_assignments.append(a)
                    # Also test small non-negative integer counts (1, 2) for pole roots like x-1=0.
                    for root_probe in (1, 2):
                        a_int = {
                            v: (Fraction(root_probe) if v == zero_var else Fraction(primes[i % len(primes)]))
                            for i, v in enumerate(all_vars)
                        }
                        probe_assignments.append(a_int)
            for shift in range(4):
                probe_assignments.append(
                    {
                        v: Fraction(primes[(i + shift) % len(primes)])
                        for i, v in enumerate(all_vars)
                    }
                )
            for assignment in probe_assignments:
                lv = l_rat.eval_at(assignment)
                rv = r_rat.eval_at(assignment)
                if lv != rv:
                    # Both defined with distinct values OR one hits a pole while
                    # the other is defined at an admissible point.
                    return False, {
                        "function": name,
                        "assignment": {k: str(v) for k, v in assignment.items()},
                        "left": "undefined" if lv is None else str(lv),
                        "right": "undefined" if rv is None else str(rv),
                    }
            all_equal = False
            continue

        all_equal = False

    if all_equal:
        return True, {}

    # Fallback: original rational parameter assignment probe for mixed bodies.
    witness = _function_counterexample(left_model, right_model)
    if witness is not None:
        return False, witness
    return None, {"left_functions": sorted(left_fns), "right_functions": sorted(right_fns)}


def _function_counterexample(left_model: Any, right_model: Any) -> dict | None:
    """Find a rational assignment where matching zero-argument functions differ.

    Only the exact rational arithmetic subset is attempted.  A differing value
    is a sound inequivalence witness for F; no witness means the case stays
    undecided, never equal.
    """
    def visible(model: Any) -> dict[str, tuple[tuple[str, ...], str]]:
        return {
            f.name: (tuple(f.args), f.expression.to_string())
            for f in model._model.functions
        }

    left_functions = visible(left_model)
    right_functions = visible(right_model)
    left_zero = {k: body for k, (args, body) in left_functions.items() if not args}
    right_zero = {k: body for k, (args, body) in right_functions.items() if not args}
    parameter_names = sorted(
        {p.name for m in (left_model, right_model) for p in m._model.parameters}
    )
    primes = (1, 2, 3, 5, 7, 11)
    for shift in range(len(primes)):
        assignment = {
            name: Fraction(primes[(i + shift) % len(primes)])
            for i, name in enumerate(parameter_names)
        }
        for name in sorted(set(left_functions) & set(right_functions)):
            left_args, left_body = left_functions[name]
            right_args, right_body = right_functions[name]
            if left_args or right_args:
                continue
            try:
                left_value = _evaluate_model_expression_exact(
                    left_body, assignment, left_zero
                )
                right_value = _evaluate_model_expression_exact(
                    right_body, assignment, right_zero
                )
            except (ValueError, TypeError):
                continue
            if left_value != right_value:
                return {
                    "function": name,
                    "assignment": {k: str(v) for k, v in assignment.items()},
                    "left": str(left_value),
                    "right": str(right_value),
                }
    return None


def _normalized_metadata(model_doc: Mapping[str, Any]) -> dict[str, Any]:
    """Extract execution-relevant metadata, excluding non-semantic model name."""
    raw = dict(model_doc.get("metadata") or {})
    raw.pop("name", None)
    unit_defs = raw.get("unit_definitions")
    if isinstance(unit_defs, list):
        raw["unit_definitions"] = sorted(
            unit_defs, key=lambda d: (str(d.get("id", "")), str(d.get("expression", "")))
        )
    return raw


def _normalized_compartments(model: Any) -> list[tuple[str, int, str, Fraction, str]]:
    """Order-independent canonical compartment descriptors."""
    out = []
    for c in model._model.compartments:
        out.append(
            (
                str(c.name),
                int(c.dimension),
                str(c.parent),
                Fraction(str(float(c.volume))),
                str(c.unit or ""),
            )
        )
    out.sort()
    return out


def _enumerate_compartment_renamings(
    left_model: Any, right_model: Any
) -> list[dict[str, str]]:
    """Enumerate valid compartment bijections when compartment name sets differ.

    When both models share the exact same compartment name inventory (e.g.
    {c1, c2}), only the identity map is allowed so distinct named compartments
    within a shared inventory are never silently swapped.
    """
    import itertools

    lc = _normalized_compartments(left_model)
    rc = _normalized_compartments(right_model)
    if len(lc) != len(rc):
        return []
    if not lc:
        return [{}]
    l_names = [c[0] for c in lc]
    r_names = [c[0] for c in rc]
    if set(l_names) == set(r_names):
        return [{name: name for name in l_names}] if lc == rc else []

    l_by_name = {c[0]: c for c in lc}
    r_by_name = {c[0]: c for c in rc}
    valid: list[dict[str, str]] = []
    if len(l_names) > 6:
        return []
    for perm in itertools.permutations(r_names):
        cmap = dict(zip(l_names, perm))
        ok = True
        for lname, rname in cmap.items():
            _, ldim, lparent, lvol, lunit = l_by_name[lname]
            _, rdim, rparent, rvol, runit = r_by_name[rname]
            mapped_parent = cmap.get(lparent, lparent) if lparent else ""
            if (ldim, mapped_parent, lvol, lunit) != (rdim, rparent, rvol, runit):
                ok = False
                break
        if ok:
            valid.append(cmap)
    return valid


def _graph_from_v02_pattern(pattern_doc: Mapping[str, Any]) -> dict[str, Any] | None:
    """Convert a C++-resolved BNGIR v0.2 structural pattern dict to a typed graph."""
    if not isinstance(pattern_doc, Mapping):
        return None
    molecules: list[dict[str, Any]] = []
    for raw_mol in pattern_doc.get("molecules", []):
        if not isinstance(raw_mol, Mapping):
            return None
        mol_type = str(raw_mol.get("type") or "")
        if not mol_type:
            return None
        sites: list[dict[str, Any]] = []
        for raw_site in raw_mol.get("sites", []):
            if not isinstance(raw_site, Mapping):
                return None
            comp_name = str(raw_site.get("component") or "")
            if not comp_name:
                return None
            state_doc = raw_site.get("state") or {}
            state_kind = state_doc.get("kind", "any")
            state_val: str | None = None
            if state_kind == "exact":
                state_val = str(state_doc.get("value"))
            elif state_kind == "set":
                values = state_doc.get("values", [])
                state_val = "~".join(str(v) for v in sorted(values))
            bond_doc = raw_site.get("bond") or {}
            alternatives = bond_doc.get("alternatives")
            bond_entries = alternatives if alternatives else [bond_doc]
            bonds: list[str] = []
            for b in bond_entries:
                bkind = b.get("kind", "unspecified")
                if bkind == "exact":
                    bonds.append(str(int(b["group"])))
                elif bkind == "bound":
                    bonds.append("+")
                elif bkind == "any":
                    bonds.append("?")
                elif bkind == "unbound":
                    bonds.append(".")
            sites.append(
                {
                    "comp": comp_name,
                    "state": state_val,
                    "bonds": tuple(bonds),
                    "label": str(raw_site.get("label") or ""),
                }
            )
        molecules.append(
            {
                "type": mol_type,
                "comp": str(raw_mol.get("compartment") or ""),
                "scope": "",
                "sites": sites,
            }
        )
    return {
        "species_comp": str(pattern_doc.get("compartment") or ""),
        "quantifier": None,
        "molecules": molecules,
    }


def _normalized_energy_map(
    model: Any,
    structural_doc: Mapping[str, Any],
    mol_map: Mapping[str, str],
    comp_map: Mapping[str, Mapping[str, str]],
    state_map: Mapping[tuple[str, str], Mapping[str, str]],
    compartment_map: Mapping[str, str] | None = None,
) -> list[tuple[dict[str, Any], Fraction]] | None:
    """Combine energy patterns by exact graph isomorphism and sum rational energies."""
    param_dict = {p.name: Fraction(str(p.value)) for p in model.parameters}
    zero_fn = {
        f.name: f.expression.to_string()
        for f in model._model.functions
        if not f.args
    }
    combined: list[tuple[dict[str, Any], Fraction]] = []
    v02_eps = structural_doc.get("energy_patterns") or []
    native_eps = list(model._model.energy_patterns)
    for idx, ep in enumerate(native_eps):
        g = None
        if idx < len(v02_eps) and isinstance(v02_eps[idx], Mapping):
            g = _graph_from_v02_pattern(v02_eps[idx].get("pattern", {}))
        if g is None:
            g = _parse_graph_pattern(ep.pattern)
        if g is None:
            return None
        g = _rename_parsed_graph(g, mol_map, comp_map, state_map, compartment_map)
        try:
            val = _evaluate_model_expression_exact(
                ep.expression.to_string(), param_dict, zero_fn
            )
        except ValueError:
            return None
        merged = False
        for i, (eg, ev) in enumerate(combined):
            if _graphs_isomorphic(eg, g):
                combined[i] = (eg, ev + val)
                merged = True
                break
        if not merged:
            combined.append((g, val))
    return [(g, v) for g, v in combined if v != 0]


def _energy_maps_equal(
    left_map: list[tuple[dict[str, Any], Fraction]],
    right_map: list[tuple[dict[str, Any], Fraction]],
) -> bool:
    if len(left_map) != len(right_map):
        return False
    used = [False] * len(right_map)
    for lg, lv in left_map:
        matched = False
        for j, (rg, rv) in enumerate(right_map):
            if not used[j] and lv == rv and _graphs_isomorphic(lg, rg):
                used[j] = True
                matched = True
                break
        if not matched:
            return False
    return True


def _normalized_barrier_map(
    model: Any,
    structural_doc: Mapping[str, Any],
    mol_map: Mapping[str, str],
    comp_map: Mapping[str, Mapping[str, str]],
    state_map: Mapping[tuple[str, str], Mapping[str, str]],
) -> dict[str, Fraction] | None:
    """Combine barrier patterns by canonical ReactionCenterKey and sum rational barriers."""
    barriers = structural_doc.get("barrier_patterns") or []
    if not barriers:
        return {}
    param_dict = {p.name: Fraction(str(p.value)) for p in model.parameters}
    zero_fn = {
        f.name: f.expression.to_string()
        for f in model._model.functions
        if not f.args
    }
    result: dict[str, Fraction] = {}
    for bp in barriers:
        if not bp.get("center_resolved"):
            return None
        center = str(bp.get("reaction_center") or "")
        renamed = _rename_reaction_center_key(center, mol_map, comp_map, state_map)
        if renamed is None:
            return None
        try:
            val = _evaluate_model_expression_exact(
                str(bp.get("expression", "")), param_dict, zero_fn
            )
        except ValueError:
            return None
        result[renamed] = result.get(renamed, Fraction(0)) + val
    return {k: v for k, v in result.items() if v != 0}


def exact_process_equal(
    left: Any,
    right: Any,
    *,
    left_doc: Mapping[str, Any] | None = None,
    right_doc: Mapping[str, Any] | None = None,
    version: str = DEFAULT_VERSION,
) -> bool:
    """Exact semantic process equality decision procedure."""
    from .model import BioNetGenModel

    left_model = (
        left if isinstance(left, BioNetGenModel) else from_bngir(left_doc or left)
    )
    right_model = (
        right if isinstance(right, BioNetGenModel) else from_bngir(right_doc or right)
    )

    try:
        left_structural = _parse_document(to_bngir(left_model, version="0.2"))["model"]
        right_structural = _parse_document(to_bngir(right_model, version="0.2"))[
            "model"
        ]
    except Exception as exc:
        raise EqualityUndecided(
            f"Could not inspect full execution contracts for exact equality: {exc}",
            {"error": str(exc)},
        ) from exc

    # Check non-lowered execution surfaces that are NOT carried into the
    # normalized jump table (population maps, TotalRate modifiers, metadata/units,
    # and raw non-rational energy/barrier features).
    def runtime_modifiers(model_doc: Mapping[str, Any]) -> list[str]:
        out = []
        for rule in model_doc.get("rules", []):
            if not isinstance(rule, Mapping):
                continue
            for m in rule.get("modifiers", []):
                kind = m.get("kind") if isinstance(m, Mapping) else str(m)
                if kind in {"total_rate", "TotalRate", "unknown"}:
                    out.append(str(kind))
        return sorted(out)

    def has_arrhenius_rules(model: Any) -> bool:
        return any(
            any(_parse_arrhenius_args(rate) is not None for rate in r.rates)
            for r in model._model.reaction_rules
        )

    left_meta = _normalized_metadata(left_structural)
    right_meta = _normalized_metadata(right_structural)
    left_pop = (
        left_structural.get("population_maps"),
        left_structural.get("population_types"),
    )
    right_pop = (
        right_structural.get("population_maps"),
        right_structural.get("population_types"),
    )
    left_rt_mods = runtime_modifiers(left_structural)
    right_rt_mods = runtime_modifiers(right_structural)

    # Check compartment relationship:
    # - exact match (order-independent)
    # - disjoint compartment renaming (same dimensions/parents/volumes/units)
    # - volume-rescaling match (same names/dimensions/parents/units, different volumes)
    left_comps = _normalized_compartments(left_model)
    right_comps = _normalized_compartments(right_model)
    same_comp_structure = left_comps == right_comps
    comp_renamings = _enumerate_compartment_renamings(left_model, right_model)
    volume_rescaling_mode = False
    if not same_comp_structure and not comp_renamings:
        l_novol = [(n, d, p, u) for n, d, p, _, u in left_comps]
        r_novol = [(n, d, p, u) for n, d, p, _, u in right_comps]
        if l_novol == r_novol and left_comps:
            volume_rescaling_mode = True

    # Protocol actions (both model actions and simulation_protocol actions).
    def action_signature(action: Any) -> tuple[str, tuple[tuple[str, str], ...]]:
        if hasattr(action, "arguments"):
            arguments = action.arguments
        elif hasattr(action, "args"):
            arguments = action.args
        else:
            arguments = {}
        if isinstance(arguments, Mapping):
            items = tuple(sorted((str(k), str(v)) for k, v in arguments.items()))
        else:
            items = ()
        return (str(action.name), items)

    left_actions = [
        ("model", action_signature(a)) for a in left_model._model.actions
    ] + [
        ("protocol", action_signature(a))
        for a in getattr(left_model._model, "protocol_actions", [])
    ]
    right_actions = [
        ("model", action_signature(a)) for a in right_model._model.actions
    ] + [
        ("protocol", action_signature(a))
        for a in getattr(right_model._model, "protocol_actions", [])
    ]

    # Concrete enabled transition difference at the initial state decides
    # inequality before structural guards (for identically labelled models).
    # Skip when energy_patterns exist without Arrhenius rules (so EQ-energy
    # unlowered semantics stay conservative) or when protocols differ.
    if (
        left_actions == right_actions
        and left_meta == right_meta
        and left_pop == right_pop
        and left_rt_mods == right_rt_mods
        and (same_comp_structure or volume_rescaling_mode)
    ):
        initial_witness = _initial_state_counterexample(
            left_model,
            right_model,
            left_structural=left_structural,
            right_structural=right_structural,
            apply_volume_scaling=volume_rescaling_mode,
        )
        if initial_witness is not None:
            return False

    # Guard non-normalized execution surfaces before proof search.
    if left_meta != right_meta:
        raise EqualityUndecided(
            "Execution-relevant metadata or units differ and require a dedicated unit certificate",
            {"left_metadata": left_meta, "right_metadata": right_meta},
        )
    if left_pop != right_pop:
        raise EqualityUndecided(
            "Population map definitions differ and require a dedicated correspondence certificate",
            {"left_population": left_pop, "right_population": right_pop},
        )
    if left_rt_mods != right_rt_mods:
        raise EqualityUndecided(
            "Runtime rule modifiers (e.g. TotalRate) differ and require a dedicated certificate",
            {"left_modifiers": left_rt_mods, "right_modifiers": right_rt_mods},
        )
    if not same_comp_structure and not comp_renamings and not volume_rescaling_mode:
        if _volume_rhs_counterexample(left_model, right_model) is not None:
            return False
        raise EqualityUndecided(
            "Compartment structures differ without a valid renaming or rescaling correspondence",
            {"left_compartments": left_comps, "right_compartments": right_comps},
        )

    if left_actions != right_actions:
        raise EqualityUndecided(
            "Protocol difference requires an exact intervention-semantics witness",
            {"left_actions": left_actions, "right_actions": right_actions},
        )

    for m in (left_model, right_model):
        for f in m._model.functions:
            body = f.expression.to_string()
            if "unknown" in body or "undecided" in body:
                raise EqualityUndecided(
                    f"Symbolic function {f.name} requires proof certificate not decidable algebraically",
                    {"function": f.name, "expression": body},
                )

    if any(
        observable.type == "Counter"
        for model in (left_model, right_model)
        for observable in model._model.observables
    ):
        raise EqualityUndecided(
            "Counter observables may expose reaction firings omitted by the state generator",
            {},
        )

    # Extract jump hazards for right model once; left model may depend on
    # observable renaming when functions reference observables.
    try:
        jumps_l, init_l, species_l, complete_l, pruned_l, vol_scaled_l = (
            _extract_jump_hazards(
                left_model,
                structural_doc=left_structural,
                apply_volume_scaling=volume_rescaling_mode,
            )
        )
        jumps_r, init_r, species_r, complete_r, pruned_r, vol_scaled_r = (
            _extract_jump_hazards(
                right_model,
                structural_doc=right_structural,
                apply_volume_scaling=volume_rescaling_mode,
            )
        )
    except EqualityUndecided:
        # Even if jump extraction declines (e.g. non-rational function in rate),
        # check whether functions F alone have an exact counterexample witness.
        fn_status, fn_info = _compare_functions_exact(
            left_model, right_model, left_structural, right_structural
        )
        if fn_status is False:
            return False
        raise
    except Exception as exc:
        fn_status, fn_info = _compare_functions_exact(
            left_model, right_model, left_structural, right_structural
        )
        if fn_status is False:
            return False
        raise EqualityUndecided(
            f"Network generation could not settle exact process equality: {exc}",
            {"error": str(exc)},
        ) from exc

    if not complete_l or not complete_r:
        raise EqualityUndecided(
            "Generated network was truncated before reaching a fixed point",
            {
                "left_generation_converged": complete_l,
                "right_generation_converged": complete_r,
            },
        )

    if pruned_l or pruned_r:
        raise EqualityUndecided(
            "Generated network omitted species due to a generation limit",
            {
                "left_generation_pruned_species": pruned_l,
                "right_generation_pruned_species": pruned_r,
            },
        )

    duplicate_species_labels = len(set(species_l)) != len(species_l) or len(
        set(species_r)
    ) != len(species_r)
    if duplicate_species_labels:
        raise EqualityUndecided(
            "Generated network has non-unique species labels; state coordinates cannot be certified",
            {
                "left_species_count": len(species_l),
                "left_unique_species_count": len(set(species_l)),
                "right_species_count": len(species_r),
                "right_unique_species_count": len(set(species_r)),
            },
        )

    # Check function table F when observable names are not renamed yet; if a
    # definite counterexample exists on parameter-only functions, return False.
    obs_l = list(left_model._model.observables)
    obs_r = list(right_model._model.observables)

    # Fast path: identically named species & same compartment names.
    def molecule_type_signatures(model: Any) -> dict[str, tuple[Any, ...]]:
        return {
            molecule_type.name: (
                molecule_type.is_population,
                tuple(
                    sorted(
                        (
                            component.name,
                            tuple(sorted(component.allowed_states)),
                        )
                        for component in molecule_type.components
                    )
                ),
            )
            for molecule_type in model._model.molecule_types
        }

    type_signatures_l = molecule_type_signatures(left_model)
    type_signatures_r = molecule_type_signatures(right_model)

    if set(species_l) == set(species_r) and (same_comp_structure or volume_rescaling_mode):
        if type_signatures_l != type_signatures_r:
            raise EqualityUndecided(
                "Identically named species require matching molecule type signatures",
                {
                    "left_type_signatures": type_signatures_l,
                    "right_type_signatures": type_signatures_r,
                },
            )
        id_mol = {t: t for t in type_signatures_l}
        id_comp = {
            mt.name: {c.name: c.name for c in mt.components}
            for mt in left_model._model.molecule_types
        }
        id_state = {
            (mt.name, c.name): {s: s for s in c.allowed_states}
            for mt in left_model._model.molecule_types
            for c in mt.components
        }
        obs_ok, obs_map = _match_observables_exact(obs_l, obs_r, id_mol, id_comp, id_state)
        fn_status, fn_info = _compare_functions_exact(
            left_model,
            right_model,
            left_structural,
            right_structural,
            obs_renaming=obs_map if obs_ok else None,
        )
        if fn_status is False:
            return False

        for sp in species_l:
            if init_l.get(sp, Fraction(0)) != init_r.get(sp, Fraction(0)):
                return False

        # Re-extract left jumps with observable renaming if observables were renamed.
        eff_jumps_l = jumps_l
        if obs_ok and any(k != v for k, v in obs_map.items()):
            eff_jumps_l, _, _, _, _, _ = _extract_jump_hazards(
                left_model,
                structural_doc=left_structural,
                apply_volume_scaling=volume_rescaling_mode,
                obs_renaming=obs_map,
            )

        if set(eff_jumps_l.keys()) != set(jumps_r.keys()):
            from collections import Counter

            def enabled(key: tuple[Any, ...]) -> bool:
                need = Counter(key[0])
                return all(
                    init_l.get(sp, Fraction(0)) >= count for sp, count in need.items()
                )

            for key in set(eff_jumps_l) | set(jumps_r):
                if enabled(key) and _hazard_key(
                    eff_jumps_l.get(key, ("poly_exp", ()))
                ) != _hazard_key(jumps_r.get(key, ("poly_exp", ()))):
                    return False
            raise EqualityUndecided(
                "Generated jump tables differ, but no initial-state counterexample was found",
                {"left_jump_count": len(eff_jumps_l), "right_jump_count": len(jumps_r)},
            )

        for key in eff_jumps_l:
            rate_l = eff_jumps_l[key]
            rate_r = jumps_r[key]
            if _hazard_key(rate_l) != _hazard_key(rate_r):
                from collections import Counter

                need = Counter(key[0])
                if all(
                    init_l.get(sp, Fraction(0)) >= count for sp, count in need.items()
                ):
                    if rate_l[0] == "poly_exp" and rate_r[0] == "poly_exp":
                        return False
                    if rate_l[0] == "tfun" and rate_r[0] == "tfun":
                        if rate_l[2] != rate_r[2] or _tfun_counterexample(rate_l[1], rate_r[1]) is not None:
                            return False
                raise EqualityUndecided(
                    "Generated rate coefficients differ without a verified counterexample",
                    {"jump": key, "left_rate": str(rate_l), "right_rate": str(rate_r)},
                )

        # If volume rescaling mode was used, require at least one volume-scaled
        # reaction so unimolecular-only models with mutated compartment volumes
        # stay undecided rather than silently discarding compartment volume.
        if volume_rescaling_mode and not (vol_scaled_l and vol_scaled_r):
            raise EqualityUndecided(
                "Compartment volumes differ with no volume-scaled reaction to witness rescaling",
                {"left_compartments": left_comps, "right_compartments": right_comps},
            )

        # For non-Arrhenius models with energy/barrier patterns, verify
        # normalized energy/barrier maps agree.
        if not (has_arrhenius_rules(left_model) and has_arrhenius_rules(right_model)):
            if left_model._model.energy_patterns or right_model._model.energy_patterns:
                le = _normalized_energy_map(
                    left_model, left_structural, id_mol, id_comp, id_state
                )
                re_ = _normalized_energy_map(
                    right_model, right_structural, id_mol, id_comp, id_state
                )
                if le is None or re_ is None or not _energy_maps_equal(le, re_):
                    raise EqualityUndecided(
                        "Energy patterns differ without Arrhenius transition-rate reduction",
                        {"left_energy": len(left_model._model.energy_patterns), "right_energy": len(right_model._model.energy_patterns)},
                    )
            if left_structural.get("barrier_patterns") or right_structural.get("barrier_patterns"):
                lb = _normalized_barrier_map(left_model, left_structural, id_mol, id_comp, id_state)
                rb = _normalized_barrier_map(right_model, right_structural, id_mol, id_comp, id_state)
                if lb is None or rb is None or lb != rb:
                    raise EqualityUndecided(
                        "Barrier patterns differ without Arrhenius transition-rate reduction",
                        {},
                    )

        if not obs_ok:
            return False

        if fn_status is not True:
            raise EqualityUndecided(
                "Function interpretations differ and have no verified equivalence certificate",
                fn_info,
            )

        return True

    # General hierarchical renaming search (molecule types, sites, states,
    # bond labels, and disjoint compartment names).
    if len(species_l) != len(species_r) or len(jumps_l) != len(jumps_r):
        raise EqualityUndecided(
            "Generated networks differ without a verified reachable counterexample",
            {"left_species": len(species_l), "right_species": len(species_r)},
        )

    if volume_rescaling_mode:
        raise EqualityUndecided(
            "Simultaneous volume rescaling and species renaming is uncertified",
            {"left_species": species_l, "right_species": species_r},
        )

    sig_renamings, sig_truncated = _enumerate_signature_renamings(
        left_model, right_model
    )
    if not sig_renamings:
        raise EqualityUndecided(
            "No hierarchical signature renaming induces a species correspondence",
            {
                "left_type_signatures": type_signatures_l,
                "right_type_signatures": type_signatures_r,
            },
        )

    parsed_species_l = {sp: _parse_graph_pattern(sp) for sp in species_l}
    parsed_species_r = {sp: _parse_graph_pattern(sp) for sp in species_r}
    if any(g is None for g in parsed_species_l.values()) or any(
        g is None for g in parsed_species_r.values()
    ):
        raise EqualityUndecided(
            "Generated species could not be parsed for exact graph isomorphism",
            {"left_species": species_l, "right_species": species_r},
        )

    comp_map_candidates = comp_renamings if comp_renamings else [{}]
    candidates = []
    for cmap in comp_map_candidates:
        for mol_map, comp_map, state_map in sig_renamings:
            species_mapping: dict[str, str] = {}
            used_r: set[str] = set()
            ok = True
            for sp_l in species_l:
                renamed_g = _rename_parsed_graph(
                    parsed_species_l[sp_l], mol_map, comp_map, state_map, cmap
                )
                found_r = None
                for sp_r in species_r:
                    if sp_r not in used_r and _graphs_isomorphic(
                        renamed_g, parsed_species_r[sp_r]
                    ):
                        found_r = sp_r
                        break
                if found_r is None:
                    ok = False
                    break
                species_mapping[sp_l] = found_r
                used_r.add(found_r)
            if ok and len(used_r) == len(species_r):
                candidates.append((mol_map, comp_map, state_map, cmap, species_mapping))

    if not candidates:
        raise EqualityUndecided(
            "No signature renaming induces the generated species correspondence",
            {
                "left_type_signatures": type_signatures_l,
                "right_type_signatures": type_signatures_r,
            },
        )

    transition_mapping_with_initial_mismatch = False
    for mol_map, comp_map, state_map, cmap, mapping in candidates:
        obs_ok, obs_map = _match_observables_exact(
            obs_l, obs_r, mol_map, comp_map, state_map, cmap
        )
        eff_jumps_l = jumps_l
        if obs_ok and any(k != v for k, v in obs_map.items()):
            eff_jumps_l, _, _, _, _, _ = _extract_jump_hazards(
                left_model,
                structural_doc=left_structural,
                obs_renaming=obs_map,
            )

        mapped_jumps_l = {}
        for (reactants, products, delay_spec, non_consuming, work_key), rate in eff_jumps_l.items():
            mapped_reactants = tuple(sorted(mapping[sp] for sp in reactants))
            mapped_products = tuple(sorted(mapping[sp] for sp in products))
            mapped_jumps_l[(mapped_reactants, mapped_products, delay_spec, non_consuming, work_key)] = rate

        if set(mapped_jumps_l.keys()) == set(jumps_r.keys()):
            if all(
                _hazard_key(mapped_jumps_l[key]) == _hazard_key(jumps_r[key])
                for key in jumps_r
            ):
                initial_matches = all(
                    init_l.get(source, Fraction(0)) == init_r.get(target, Fraction(0))
                    for source, target in mapping.items()
                )
                if not initial_matches:
                    transition_mapping_with_initial_mismatch = True
                    continue

                if not obs_ok:
                    continue

                fn_status, _ = _compare_functions_exact(
                    left_model,
                    right_model,
                    left_structural,
                    right_structural,
                    obs_renaming=obs_map,
                )
                if fn_status is not True:
                    continue

                if not (has_arrhenius_rules(left_model) and has_arrhenius_rules(right_model)):
                    if left_model._model.energy_patterns or right_model._model.energy_patterns:
                        le = _normalized_energy_map(
                            left_model, left_structural, mol_map, comp_map, state_map, cmap
                        )
                        re_ = _normalized_energy_map(
                            right_model, right_structural, {}, {}, {}, {}
                        )
                        if le is None or re_ is None or not _energy_maps_equal(le, re_):
                            continue
                    if left_structural.get("barrier_patterns") or right_structural.get("barrier_patterns"):
                        lb = _normalized_barrier_map(
                            left_model, left_structural, mol_map, comp_map, state_map
                        )
                        rb = _normalized_barrier_map(
                            right_model, right_structural, {}, {}, {}
                        )
                        if lb is None or rb is None or lb != rb:
                            continue

                return True

    if transition_mapping_with_initial_mismatch and not sig_truncated:
        return False

    raise EqualityUndecided(
        "No generated-network renaming certificate was found; inequivalence is unproved",
        {"left_species": species_l, "right_species": species_r},
    )


def semantic_equal(left: Any, right: Any, *, version: str = DEFAULT_VERSION) -> bool:
    """Compare exact process equality under BNGIR and generator semantics.

    Returns True with a verified equivalence certificate (e.g. wire match or
    generator jump vector and reachability fixed-point certificate), or False with
    a verified counterexample witness. Raises :class:`EqualityUndecided` when
    proof search cannot decide equivalence.
    """
    try:
        left_doc = _parse_document(to_bngir(left, version=version))
    except Exception as exc:
        raise EqualityUndecided(
            f"Left model cannot be serialized for exact equality: {exc}",
            {"error": str(exc)},
        ) from exc
    try:
        right_doc = _parse_document(to_bngir(right, version=version))
    except Exception as exc:
        raise EqualityUndecided(
            f"Right model cannot be serialized for exact equality: {exc}",
            {"error": str(exc)},
        ) from exc
    if left_doc == right_doc:
        return True
    return exact_process_equal(
        left, right, left_doc=left_doc, right_doc=right_doc, version=version
    )
