"""Semantic-identity correspondence of the resolved model, its ids and its
serialization (#166).

Issue #166 asks for the production lowering correspondence to be stated for a
named supported subset: how the resolved C++ model, the serialized semantic
identities and the compiled ids correspond to each other, and what refinement
that correspondence states.

This module states the correspondence as an executable contract and checks it
over a generated family of models.  The contract has four parts.

``packing``
    Every declaration namespace is *packed*: the compiled ids of a namespace
    are exactly ``0 .. n-1`` and increase with the declaration order of that
    namespace in the source.  The rule namespace additionally carries the
    source label beside the generated name, so the label is checked too.

``reference``
    Every id the serialization carries is a *reference* to one declaration: a
    pattern molecule names a molecule type, a pattern site names a component
    of that molecule type, a site state names a state of that component, a
    compartment names its parent and a resolved expression names a parameter or
    a function.  The name the serialization records beside the id must be the
    name of the declaration the id denotes.

``serialization``
    The BNGIR v0.2 document's model section is exactly the resolved model's
    compiled snapshot: the serialization loses no identity and invents none.

``refinement``
    The compiled-id assignment *refines* the name-keyed declaration
    correspondence: within a namespace two declarations share an id exactly
    when they share a name, and every reference resolves to exactly one
    declaration.  The serialized identities therefore determine the resolved
    model uniquely, and the resolved model determines the serialized identities
    uniquely.

The reference is never the product's own output.  The expected namespace
order, the component order, the state order and the expression references come
from the generator that wrote the source, so a defect in the compiler's id
assignment appears as a difference against an expectation the compiler never
produced.

The declared domain is the generated grammar below: models whose declarations
are drawn from the parameter, compartment, molecule-type, function, observable,
seed-species and reaction-rule blocks, with explicit site states and with no
energy pattern, barrier pattern or population map.  Nothing outside that
grammar is claimed.

The Lean reference (``formal/lean/BNG/Ids.lean`` and
``formal/lean/BNG/NameResolution.lean``) states the same name-to-id
correspondence in the formal model.  That artifact is a machine-checked
theorem; the executable check below is a fixture over the declared domain and
does not re-prove it.  The two stay distinct: a passing fixture here never
discharges a Lean obligation.
"""

from __future__ import annotations

import json
from pathlib import Path

from .campaign import STATUSES

ISSUES = (166,)
OPERATION = "semantic-identity"

# The named checks of this operation.  They are the executable form of the
# correspondence and of the refinement it states.
CHECKS = ("identity-packing", "identity-reference", "identity-refinement")

# The declared domain of the qualification.  Every generated case is inside it
# and the statement is claimed for it only.
DOMAIN = (
    "generated models whose declarations are drawn from the parameter, "
    "compartment, molecule-type, function, observable, seed-species and "
    "reaction-rule blocks, with explicit site states and no energy pattern, "
    "barrier pattern or population map"
)

# The machine-checked reference.  It is named so the executable fixture and the
# formal statement stay visibly distinct; the check below never claims to
# discharge it.
LEAN_REFERENCE = (
    "formal/lean/BNG/Ids.lean",
    "formal/lean/BNG/NameResolution.lean",
)

# The namespaces whose compiled ids this operation checks, and the snapshot key
# that carries each one.
NAMESPACES = (
    ("parameters", "parameters"),
    ("functions", "functions"),
    ("molecule_types", "molecule_types"),
    ("compartments", "compartments"),
    ("observables", "observables"),
    ("rules", "rules"),
)

# The symbol kinds a resolved expression may carry, and the namespace each one
# denotes.  The wire format names the kind in the singular and the namespace
# holds the declarations in the plural.
SYMBOL_NAMESPACES = {
    "parameter": "parameters",
    "function": "functions",
    "molecule_type": "molecule_types",
    "observable": "observables",
    "compartment": "compartments",
    "reaction_rule": "rules",
}


# --------------------------------------------------------------------------- #
# The generated grammar.  A case is described by structured data, so the
# expected identity table is known before the compiler ever runs.
# --------------------------------------------------------------------------- #


def _molecule(name, *components):
    """One molecule: a name and (component, state) pairs; a None state is free."""
    return (name, tuple(components))


def _pattern(*molecules):
    """One pattern: an ordered tuple of molecules."""
    return tuple(molecules)


def _render_expression(expression):
    """Render one structured expression as BNGL source text."""
    kind = expression[0]
    if kind == "number":
        return repr(float(expression[1]))
    if kind == "parameter":
        return expression[1]
    if kind == "function":
        arguments = ",".join(_render_expression(item) for item in expression[2])
        return f"{expression[1]}({arguments})"
    if kind == "binary":
        operator, left, right = expression[1], expression[2], expression[3]
        return f"{_render_expression(left)} {operator} {_render_expression(right)}"
    raise ValueError("unknown expression kind: " + str(kind))


def _expression_references(expression):
    """Return the (kind, name) declarations one structured expression names."""
    kind = expression[0]
    if kind == "number":
        return []
    if kind == "parameter":
        return [("parameter", expression[1])]
    if kind == "function":
        references = [("function", expression[1])]
        for argument in expression[2]:
            references.extend(_expression_references(argument))
        return references
    if kind == "binary":
        return _expression_references(expression[2]) + _expression_references(
            expression[3]
        )
    raise ValueError("unknown expression kind: " + str(kind))


def _render_molecule(molecule):
    name, components = molecule
    if not components:
        return name
    sites = [
        component if state is None else f"{component}~{state}"
        for component, state in components
    ]
    return f"{name}({','.join(sites)})"


def _render_pattern(pattern):
    return ".".join(_render_molecule(molecule) for molecule in pattern)


def _render_model(spec):
    """Render one generated case as a BNGL model."""
    lines = ["begin model"]
    if spec["parameters"]:
        lines.append("begin parameters")
        for name, expression in spec["parameters"]:
            lines.append(f"  {name} {_render_expression(expression)}")
        lines.append("end parameters")
    if spec["compartments"]:
        lines.append("begin compartments")
        for name, dimension, volume, parent in spec["compartments"]:
            suffix = f" {parent}" if parent else ""
            lines.append(f"  {name} {dimension} {volume}{suffix}")
        lines.append("end compartments")
    if spec["molecule_types"]:
        lines.append("begin molecule types")
        for name, components in spec["molecule_types"]:
            sites = ",".join(
                component + ("".join(f"~{state}" for state in states))
                for component, states in components
            )
            lines.append(f"  {name}({sites})" if sites else f"  {name}")
        lines.append("end molecule types")
    if spec["functions"]:
        lines.append("begin functions")
        for name, arguments, body in spec["functions"]:
            joined = ",".join(arguments)
            lines.append(f"  {name}({joined}) = {_render_expression(body)}")
        lines.append("end functions")
    if spec["observables"]:
        lines.append("begin observables")
        for kind, name, patterns in spec["observables"]:
            rendered = ",".join(_render_pattern(pattern) for pattern in patterns)
            lines.append(f"  {kind} {name} {rendered}")
        lines.append("end observables")
    if spec["seeds"]:
        lines.append("begin seed species")
        for pattern, amount in spec["seeds"]:
            lines.append(f"  {_render_pattern(pattern)} {amount}")
        lines.append("end seed species")
    if spec["rules"]:
        lines.append("begin reaction rules")
        for label, reactants, products, rate in spec["rules"]:
            prefix = f"{label} " if label else ""
            left = "+".join(_render_pattern(pattern) for pattern in reactants)
            right = "+".join(_render_pattern(pattern) for pattern in products)
            lines.append(f"  {prefix}{left} -> {right} {_render_expression(rate)}")
        lines.append("end reaction rules")
    lines.append("end model")
    return "\n".join(lines) + "\n"


def _expected_identity(spec):
    """Build the independently known identity table of one generated case."""
    components = {}
    states = {}
    for name, declared in spec["molecule_types"]:
        components[name] = {
            component: index for index, (component, _) in enumerate(declared)
        }
        states[name] = {
            component: {state: index for index, state in enumerate(component_states)}
            for component, component_states in declared
        }
    return {
        "namespaces": {
            "parameters": [name for name, _ in spec["parameters"]],
            "functions": [name for name, _, _ in spec["functions"]],
            "molecule_types": [name for name, _ in spec["molecule_types"]],
            "compartments": [name for name, _, _, _ in spec["compartments"]],
            "observables": [name for _, name, _ in spec["observables"]],
            "rules": [f"R{index + 1}" for index in range(len(spec["rules"]))],
        },
        "seed_count": len(spec["seeds"]),
        "rule_labels": [label for label, _, _, _ in spec["rules"]],
        "components": components,
        "states": states,
        "compartment_parents": {
            name: parent for name, _, _, parent in spec["compartments"]
        },
        "parameter_references": [
            _expression_references(expression) for _, expression in spec["parameters"]
        ],
        "function_references": [
            _expression_references(body) for _, _, body in spec["functions"]
        ],
        "rule_references": [
            _expression_references(rate) for _, _, _, rate in spec["rules"]
        ],
    }


def _case(case_id, purpose, spec):
    """Return one generated case with its source and its expected identities."""
    return {
        "id": case_id,
        "purpose": purpose,
        "text": _render_model(spec),
        "expected": _expected_identity(spec),
    }


def generated_cases():
    """Return the generated, parameterized semantic-identity cases.

    The family varies the declaration surface: how many molecule types there
    are, whether two molecule types share a component name (the compiled
    component ids are declaration-local, so the same name must not share an
    id), whether a compartment has a parent, whether a rate law calls a
    function, and whether the same declarations are written in a different
    order (the compiled ids follow the declaration order, so the same names
    in another order must carry another id).
    """
    cases = []

    # One declaration of every kind, at its smallest size.
    cases.append(
        _case(
            "single-declaration",
            "one parameter, one molecule type, one compartment, one function, "
            "one observable, one seed species and one rule",
            {
                "parameters": (("k", ("number", 0.5)),),
                "compartments": (("PM", 2, 1.0, None),),
                "molecule_types": (("A", (("x", ("u", "p")),)),),
                "functions": (("f", ("v",), ("number", 1.0)),),
                "observables": (("Molecules", "O1", (_pattern(_molecule("A")),)),),
                "seeds": ((_pattern(_molecule("A", ("x", "u"))), 10),),
                "rules": (
                    (
                        "",
                        (_pattern(_molecule("A", ("x", "u"))),),
                        (_pattern(_molecule("A", ("x", "p"))),),
                        ("parameter", "k"),
                    ),
                ),
            },
        )
    )

    # Two molecule types that share a component name: the component ids are
    # declaration-local, so the shared name must not share an id.
    cases.append(
        _case(
            "shared-component-name",
            "two molecule types that declare the same component name, with "
            "distinct state sets",
            {
                "parameters": (
                    ("k", ("number", 0.5)),
                    ("k2", ("binary", "+", ("parameter", "k"), ("number", 1.0))),
                ),
                "compartments": (
                    ("PM", 2, 1.0, None),
                    ("CP", 3, 1.0, "PM"),
                ),
                "molecule_types": (
                    ("A", (("x", ("u", "p")),)),
                    ("B", (("x", ("on", "off")),)),
                ),
                "functions": (
                    ("f", ("v",), ("binary", "+", ("parameter", "k"), ("number", 1.0))),
                ),
                "observables": (
                    ("Molecules", "O1", (_pattern(_molecule("A", ("x", None))),)),
                    ("Species", "O2", (_pattern(_molecule("B", ("x", None))),)),
                ),
                "seeds": (
                    (_pattern(_molecule("A", ("x", "u"))), 10),
                    (_pattern(_molecule("B", ("x", "on"))), 5),
                ),
                "rules": (
                    (
                        "conv:",
                        (_pattern(_molecule("A", ("x", "u"))),),
                        (_pattern(_molecule("A", ("x", "p"))),),
                        ("parameter", "k"),
                    ),
                    (
                        "call:",
                        (_pattern(_molecule("B", ("x", "on"))),),
                        (_pattern(_molecule("B", ("x", "off"))),),
                        ("function", "f", (("parameter", "k2"),)),
                    ),
                ),
            },
        )
    )

    # The same declarations as the previous case, written in another order.
    # The compiled ids follow the declaration order, so the same names carry
    # another id: the id assignment refines the *ordered* declaration list and
    # is not a function of the name alone.
    cases.append(
        _case(
            "reordered-declarations",
            "the shared-component model with its declarations written in a "
            "different order, so the same names carry different compiled ids",
            {
                "parameters": (
                    ("k2", ("binary", "+", ("parameter", "k"), ("number", 1.0))),
                    ("k", ("number", 0.5)),
                ),
                "compartments": (
                    ("CP", 3, 1.0, "PM"),
                    ("PM", 2, 1.0, None),
                ),
                "molecule_types": (
                    ("B", (("x", ("on", "off")),)),
                    ("A", (("x", ("u", "p")),)),
                ),
                "functions": (
                    ("f", ("v",), ("binary", "+", ("parameter", "k"), ("number", 1.0))),
                ),
                "observables": (
                    ("Species", "O2", (_pattern(_molecule("B", ("x", None))),)),
                    ("Molecules", "O1", (_pattern(_molecule("A", ("x", None))),)),
                ),
                "seeds": (
                    (_pattern(_molecule("B", ("x", "on"))), 5),
                    (_pattern(_molecule("A", ("x", "u"))), 10),
                ),
                "rules": (
                    (
                        "call:",
                        (_pattern(_molecule("B", ("x", "on"))),),
                        (_pattern(_molecule("B", ("x", "off"))),),
                        ("function", "f", (("parameter", "k2"),)),
                    ),
                    (
                        "conv:",
                        (_pattern(_molecule("A", ("x", "u"))),),
                        (_pattern(_molecule("A", ("x", "p"))),),
                        ("parameter", "k"),
                    ),
                ),
            },
        )
    )

    # A wider family: three molecule types, three compartments and three
    # rules, so the packing is checked over more than one declaration per
    # namespace.
    cases.append(
        _case(
            "three-of-each",
            "three parameters, three molecule types, three compartments, three "
            "observables, three seed species and three rules",
            {
                "parameters": (
                    ("k1", ("number", 0.1)),
                    ("k2", ("number", 0.2)),
                    ("k3", ("binary", "*", ("parameter", "k1"), ("parameter", "k2"))),
                ),
                "compartments": (
                    ("PM", 2, 1.0, None),
                    ("CP", 3, 1.0, "PM"),
                    ("ER", 3, 0.5, "CP"),
                ),
                "molecule_types": (
                    ("A", (("x", ("u", "p")), ("y", ()))),
                    ("B", (("x", ("u", "p")),)),
                    ("C", (("z", ()),)),
                ),
                "functions": (
                    (
                        "f",
                        ("v",),
                        ("binary", "+", ("parameter", "k1"), ("number", 1.0)),
                    ),
                    (
                        "g",
                        ("v",),
                        ("binary", "*", ("parameter", "k2"), ("number", 2.0)),
                    ),
                ),
                "observables": (
                    ("Molecules", "O1", (_pattern(_molecule("A", ("x", None))),)),
                    ("Molecules", "O2", (_pattern(_molecule("B", ("x", None))),)),
                    ("Species", "O3", (_pattern(_molecule("C", ("z", None))),)),
                ),
                "seeds": (
                    (_pattern(_molecule("A", ("x", "u"))), 10),
                    (_pattern(_molecule("B", ("x", "u"))), 20),
                    (_pattern(_molecule("C", ("z", None))), 30),
                ),
                "rules": (
                    (
                        "r1:",
                        (_pattern(_molecule("A", ("x", "u"))),),
                        (_pattern(_molecule("A", ("x", "p"))),),
                        ("parameter", "k1"),
                    ),
                    (
                        "r2:",
                        (_pattern(_molecule("B", ("x", "u"))),),
                        (_pattern(_molecule("C", ("z", None))),),
                        ("parameter", "k2"),
                    ),
                    (
                        "r3:",
                        (_pattern(_molecule("A", ("x", "p"))),),
                        (_pattern(_molecule("B", ("x", "p"))),),
                        ("function", "f", (("parameter", "k3"),)),
                    ),
                ),
            },
        )
    )

    return tuple(cases)


CASES = generated_cases()


def check_ids():
    """Stable expected check identities for the semantic-identity operation."""
    return [f"{OPERATION}:{case['id']}:{name}" for case in CASES for name in CHECKS]


# --------------------------------------------------------------------------- #
# The checks.
# --------------------------------------------------------------------------- #


def _difference(field, expected, actual):
    return dict(field=field, expected=expected, actual=actual)


def _namespace_entries(snapshot, key):
    return [(item["id"], item["name"]) for item in snapshot[key]]


def _packing_differences(snapshot, expected):
    """The namespace packing: dense ids in declaration order, names as declared."""
    differences = []
    for namespace, key in NAMESPACES:
        names = expected["namespaces"][namespace]
        observed = _namespace_entries(snapshot, key)
        wanted = [(index, name) for index, name in enumerate(names)]
        if observed != wanted:
            differences.append(_difference(f"{namespace}.packing", wanted, observed))
    seeds = [item["id"] for item in snapshot["seeds"]]
    if seeds != list(range(expected["seed_count"])):
        differences.append(
            _difference(
                "seeds.packing",
                list(range(expected["seed_count"])),
                seeds,
            )
        )
    labels = [item["label"] for item in snapshot["rules"]]
    if labels != expected["rule_labels"]:
        differences.append(_difference("rules.labels", expected["rule_labels"], labels))
    return differences


def _expression_references_observed(expression):
    """Collect the (kind, index) symbol references of one resolved expression."""
    references = []

    def visit(node):
        if not isinstance(node, dict):
            return
        symbol = node.get("symbol")
        if isinstance(symbol, dict):
            references.append((symbol.get("kind"), symbol.get("index")))
        for argument in node.get("arguments") or []:
            visit(argument)

    visit(expression)
    return references


def _reference_differences(snapshot, expected):
    """Every recorded id must denote the declaration the record names."""
    differences = []
    names = expected["namespaces"]

    def check_namespace_expression(path, expression, wanted):
        observed = _expression_references_observed(expression)
        resolved = []
        for kind, index in observed:
            namespace = SYMBOL_NAMESPACES.get(kind)
            table = names.get(namespace) if namespace else None
            if (
                table is None
                or not isinstance(index, int)
                or isinstance(index, bool)
                or not 0 <= index < len(table)
            ):
                differences.append(
                    _difference(
                        path,
                        wanted,
                        [
                            (
                                (kind, index)
                                if table is None
                                else (
                                    kind,
                                    f"index {index} outside 0..{len(table) - 1}",
                                )
                            )
                        ],
                    )
                )
                return
            resolved.append((kind, table[index]))
        if resolved != wanted:
            differences.append(_difference(path, wanted, resolved))

    for index, parameter in enumerate(snapshot["parameters"]):
        check_namespace_expression(
            f"parameters[{index}].expression",
            parameter["expression"],
            expected["parameter_references"][index],
        )
    for index, function in enumerate(snapshot["functions"]):
        check_namespace_expression(
            f"functions[{index}].expression",
            function["expression"],
            expected["function_references"][index],
        )
    for index, rule in enumerate(snapshot["rules"]):
        rate = rule["forward"].get("rate")
        if rate is not None:
            check_namespace_expression(
                f"rules[{index}].forward.rate.expression",
                rate.get("expression", {}),
                expected["rule_references"][index],
            )

    for index, compartment in enumerate(snapshot["compartments"]):
        parent = expected["compartment_parents"][compartment["name"]]
        if parent is None:
            if "parent_id" in compartment:
                differences.append(
                    _difference(
                        f"compartments[{index}].parent_id",
                        None,
                        compartment["parent_id"],
                    )
                )
            continue
        wanted = names["compartments"].index(parent)
        if compartment.get("parent_id") != wanted:
            differences.append(
                _difference(
                    f"compartments[{index}].parent_id",
                    wanted,
                    compartment.get("parent_id"),
                )
            )
        if compartment.get("parent") != parent:
            differences.append(
                _difference(
                    f"compartments[{index}].parent",
                    parent,
                    compartment.get("parent"),
                )
            )

    def check_pattern(path, pattern):
        for molecule_index, molecule in enumerate(pattern.get("molecules", [])):
            molecule_path = f"{path}.molecules[{molecule_index}]"
            type_name = molecule.get("type")
            if type_name not in names["molecule_types"]:
                differences.append(
                    _difference(
                        molecule_path + ".type",
                        "a declared molecule type",
                        type_name,
                    )
                )
                continue
            wanted = names["molecule_types"].index(type_name)
            if molecule.get("type_id") != wanted:
                differences.append(
                    _difference(
                        molecule_path + ".type_id",
                        wanted,
                        molecule.get("type_id"),
                    )
                )
            components = expected["components"][type_name]
            states = expected["states"][type_name]
            for site_index, site in enumerate(molecule.get("sites", [])):
                site_path = f"{molecule_path}.sites[{site_index}]"
                component = site.get("component")
                if component not in components:
                    differences.append(
                        _difference(
                            site_path + ".component",
                            "a declared component",
                            component,
                        )
                    )
                    continue
                if site.get("component_index") != components[component]:
                    differences.append(
                        _difference(
                            site_path + ".component_index",
                            components[component],
                            site.get("component_index"),
                        )
                    )
                state = site.get("state", {})
                declared = states[component]
                if state.get("kind") == "exact":
                    value = state.get("value")
                    if value not in declared:
                        differences.append(
                            _difference(site_path + ".state.value", "a state", value)
                        )
                    elif state.get("index") != declared[value]:
                        differences.append(
                            _difference(
                                site_path + ".state.index",
                                declared[value],
                                state.get("index"),
                            )
                        )
                elif state.get("kind") == "set":
                    values = state.get("values", [])
                    indices = state.get("indices", [])
                    wanted_indices = [
                        declared[value] for value in values if value in declared
                    ]
                    if len(wanted_indices) != len(values) or indices != wanted_indices:
                        differences.append(
                            _difference(
                                site_path + ".state.indices",
                                wanted_indices,
                                indices,
                            )
                        )

    for index, seed in enumerate(snapshot["seeds"]):
        check_pattern(f"seeds[{index}].pattern", seed["pattern"])
    for index, observable in enumerate(snapshot["observables"]):
        for term_index, term in enumerate(observable.get("terms", [])):
            check_pattern(
                f"observables[{index}].terms[{term_index}].pattern",
                term["pattern"],
            )
    for index, rule in enumerate(snapshot["rules"]):
        for side in ("reactants", "products"):
            for pattern_index, pattern in enumerate(rule["forward"].get(side, [])):
                check_pattern(
                    f"rules[{index}].forward.{side}[{pattern_index}]",
                    pattern,
                )
    return differences


def _refinement_differences(snapshot, expected):
    """The refinement: ids determine names and every reference is well-founded."""
    differences = []
    for namespace, key in NAMESPACES:
        entries = _namespace_entries(snapshot, key)
        identifiers = [identifier for identifier, _ in entries]
        declared = [name for _, name in entries]
        if len(set(identifiers)) != len(identifiers):
            differences.append(
                _difference(namespace + ".ids.unique", "unique ids", identifiers)
            )
        if len(set(declared)) != len(declared):
            differences.append(
                _difference(namespace + ".names.unique", "unique names", declared)
            )
        if identifiers != sorted(identifiers):
            differences.append(
                _difference(namespace + ".ids.ordered", "ascending ids", identifiers)
            )
        if declared != expected["namespaces"][namespace]:
            differences.append(
                _difference(
                    namespace + ".names",
                    expected["namespaces"][namespace],
                    declared,
                )
            )
    # Every reference must be well founded: it denotes one declaration of the
    # namespace the reference names.
    for difference in _reference_differences(snapshot, expected):
        differences.append(difference)
    return differences


def _serialization_differences(snapshot, document):
    """The BNGIR document must carry exactly the resolved model's identities."""
    resolved = dict(snapshot)
    resolved.pop("actions", None)
    metadata = resolved.pop("metadata", {})
    wanted = {"metadata": metadata, **resolved}
    observed = document.get("model")
    if observed == wanted:
        return []
    missing = sorted(set(wanted) - set(observed or {}))
    extra = sorted(set(observed or {}) - set(wanted))
    changed = sorted(
        key for key in set(wanted) & set(observed or {}) if wanted[key] != observed[key]
    )
    return [
        _difference(
            "bngir.model",
            {"missing": missing, "extra": extra, "changed": changed},
            "the serialized model section differs from the resolved model",
        )
    ]


def _evaluate(case, snapshot, document):
    """Return the three named observations of one case."""
    expected = case["expected"]
    packing = _packing_differences(snapshot, expected)
    packing += _serialization_differences(snapshot, document)
    references = _reference_differences(snapshot, expected)
    refinement = _refinement_differences(snapshot, expected)
    return {
        "identity-packing": packing,
        "identity-reference": references,
        "identity-refinement": refinement,
    }


def _row(case, name, status, detail, differences=None):
    return {
        "id": f"{OPERATION}:{case['id']}:{name}",
        "check": name,
        "related_issues": list(ISSUES),
        "supported_execution": True,
        "evidence_kind": "supported-execution",
        "status": status,
        "detail": detail,
        "first_difference": differences[0] if differences else None,
    }


def run_worker(directory: Path):
    """Check the generated cases against the resolved model and its ids."""
    import bionetgen
    import bionetgen.bngir as bngir_module
    from bionetgen.model import _cpp

    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in CASES:
        case_dir = directory / case["id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        source = case_dir / "model.bngl"
        try:
            source.write_text(case["text"], encoding="utf-8")
        except OSError as exc:
            detail = (
                "the generated model could not be written: "
                f"{type(exc).__name__}: {exc}"
            )
            for name in CHECKS:
                rows.append(
                    _row(
                        case,
                        name,
                        "HARNESS_ERROR",
                        detail,
                        differences=[
                            _difference(
                                "source.write", "a writable model file", str(exc)
                            )
                        ],
                    )
                )
            continue
        try:
            model = bionetgen.load(str(source))
            snapshot = _cpp._compiled_snapshot(model._model)
            document = json.loads(bngir_module.to_bngir(model, version="0.2"))
        except Exception as exc:
            detail = (
                "the generated model could not be resolved into a compiled model: "
                f"{type(exc).__name__}: {exc}"
            )
            for name in CHECKS:
                rows.append(
                    _row(
                        case,
                        name,
                        "HARNESS_ERROR",
                        detail,
                        differences=[
                            _difference("compile", "a compiled model", str(exc))
                        ],
                    )
                )
            continue
        differences = _evaluate(case, snapshot, document)
        details = {
            "identity-packing": (
                "the compiled ids are dense in declaration order and the "
                "serialized model section is exactly the resolved model"
            ),
            "identity-reference": (
                "every serialized id reference denotes the declaration the "
                "serialization names beside it"
            ),
            "identity-refinement": (
                "the compiled ids refine the name-keyed declaration "
                "correspondence and every reference is well founded"
            ),
        }
        for name in CHECKS:
            rows.append(
                _row(
                    case,
                    name,
                    "FAIL" if differences[name] else "PASS",
                    details[name],
                    differences=differences[name],
                )
            )
    for row in rows:
        if row.get("status") not in STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="the semantic-identity adapter emitted an invalid status",
            )
    return rows
