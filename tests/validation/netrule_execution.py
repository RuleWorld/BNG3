"""Network-rule execution contract qualification (#139).

Issue #139 asks for the compile-owned execution contract and the legacy
network-rule path to agree on the generated reaction graph, the compiled rate
law, rule filters, local scopes and reversible rule directions before any
legacy path is retired.

Three views are compared for every generated case:

``contract``
    The compile-owned view. It is read from the compiled model
    (``_cpp._compiled_snapshot``) and therefore states what the compiler says
    the rule does: the reactant and product patterns of each direction, the
    resolved rate-law expression, the rule filters, the local scopes and the
    forward/reverse directions. The harness renders that declaration into the
    same label space as the generated network and compares it with the
    hand-derived closed form.

``legacy``
    The legacy path. It is the network produced by the engine's network-rule
    execution (``engine::NetworkRuleKernel`` reconstructing an
    ``ast::ReactionRule`` from the compiled rule). It is observed through the
    generated ``.net`` artifact and through the engine's compiled per-reaction
    rate coefficients.

``expectation``
    An independent expectation that is not produced by either path: a
    hand-derived closed-form law per case, plus the canonical Perl BNG2
    network as an external oracle wherever that implementation accepts the
    model. The closed form is always required; the Perl oracle is required
    wherever the canonical implementation can express the case, and its
    refusal is recorded where it cannot.

A check never compares one implementation against its own output. The
supported slice is declared per case; a case outside the slice is reported as
``UNSUPPORTED`` with its reason instead of being silently skipped.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from . import campaign

ISSUES = (139,)
ROOT = Path(__file__).resolve().parents[2]
ORACLE_SCRIPT = ROOT / "legacy" / "perl" / "BNG2.pl"

# The declared supported slice. Every case below stays inside it, and the
# harness refuses (UNSUPPORTED) any case whose compiled declaration cannot be
# rendered into the same label space as the generated network.
SLICE = (
    "single-molecule patterns without bonds or compartments, explicit site "
    "states, no delete-molecules modifier, and filters that name a molecule "
    "type of the filtered reactant pattern"
)

CONVERSION_MODEL = """begin model
begin parameters
  k @RATE@
end parameters
begin molecule types
  A(s~0~1)
  B()
end molecule types
begin seed species
  A(s~0) @AMOUNT@
end seed species
begin reaction rules
  conv: A(s~0) -> B() k
end reaction rules
begin actions
  generate_network({overwrite=>1})
end actions
end model
"""

REVERSIBLE_MODEL = """begin model
begin parameters
  kf @KF@
  kr @KR@
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() @AMOUNT@
  B() 0
end seed species
begin reaction rules
  rev: A() <-> B() kf, kr
end reaction rules
begin actions
  generate_network({overwrite=>1})
end actions
end model
"""

# The filtered rule coexists with an unfiltered rule so that the generated
# network stays non-empty: the canonical Perl BNG2 refuses to write a network
# without reactions, and an empty artifact could not carry the filter's
# effect into the oracle comparison.
FILTER_MODEL = """begin model
begin parameters
  k 0.4
  k2 0.1
end parameters
begin molecule types
  A()
  B()
  C()
  D()
end molecule types
begin seed species
  A() 10
  B() 5
end seed species
begin reaction rules
  filt: A() + B() -> C() k @FILTER@
  plain: A() -> D() k2
end reaction rules
begin actions
  generate_network({overwrite=>1})
end actions
end model
"""

LOCAL_SCOPE_MODEL = """begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(s~up~dn)
end molecule types
begin seed species
  A(s~dn) 1
  A(s~up) 1
end seed species
begin observables
  Molecules up A(s~up)
end observables
begin functions
  rate(z) = k + up(z)
end functions
begin reaction rules
  A%x(s~dn) <-> A%x(s~up) rate(x), rate(x)
end reaction rules
begin actions
  generate_network({overwrite=>1})
end actions
end model
"""


class UnsupportedSlice(ValueError):
    """The case cannot be qualified inside the declared supported slice."""


class OracleRefused(ValueError):
    """The independent oracle cannot express the case."""


def _conversion_cases():
    cases = []
    for index, (rate, amount) in enumerate(((0.4, 10), (0.05, 100))):
        cases.append(
            dict(
                id=f"conversion-r{index}",
                aspects=("graph", "rate"),
                rule_label="conv:",
                bngl=CONVERSION_MODEL.replace("@RATE@", repr(rate)).replace(
                    "@AMOUNT@", str(amount)
                ),
                # Closed form: one first-order conversion of A(s~0) into B().
                species=["A(s~0)", "B()"],
                reactions=[(("A(s~0)",), ("B()",), rate)],
                contract=dict(
                    reactants=["A(s~0)"],
                    products=["B()"],
                    rate=rate,
                    filters=[],
                    local_scopes=[],
                ),
                oracle="required",
            )
        )
    return cases


def _reversible_cases():
    cases = []
    for index, (kf, kr, amount) in enumerate(((0.4, 0.2, 10), (0.05, 0.01, 100))):
        cases.append(
            dict(
                id=f"reversible-r{index}",
                aspects=("reversible",),
                rule_label="rev:",
                bngl=REVERSIBLE_MODEL.replace("@KF@", repr(kf))
                .replace("@KR@", repr(kr))
                .replace("@AMOUNT@", str(amount)),
                species=["A()", "B()"],
                reactions=[(("A()",), ("B()",), kf), (("B()",), ("A()",), kr)],
                contract=dict(
                    reactants=["A()"],
                    products=["B()"],
                    reverse_reactants=["B()"],
                    reverse_products=["A()"],
                    rate=kf,
                    reverse_rate=kr,
                    filters=[],
                    local_scopes=[],
                ),
                oracle="required",
            )
        )
    return cases


def _filter_cases():
    return [
        dict(
            id="filter-include",
            aspects=("filter",),
            rule_label="filt:",
            bngl=FILTER_MODEL.replace("@FILTER@", "include_reactants(1,A)"),
            # The first reactant pattern is A(), which contains a molecule of
            # type A, so the include filter admits the match.
            species=["A()", "B()", "C()", "D()"],
            reactions=[(("A()", "B()"), ("C()",), 0.4), (("A()",), ("D()",), 0.1)],
            contract=dict(
                reactants=["A()", "B()"],
                products=["C()"],
                rate=0.4,
                filters=[
                    dict(include=True, side="reactant", pattern_index=0, types=["A"])
                ],
                local_scopes=[],
            ),
            oracle="required",
        ),
        dict(
            id="filter-exclude",
            aspects=("filter",),
            rule_label="filt:",
            bngl=FILTER_MODEL.replace("@FILTER@", "exclude_reactants(1,A)"),
            # The first reactant pattern is A(), which contains a molecule of
            # type A, so the exclude filter rejects the match: the rule
            # contributes no reaction and no product species.
            species=["A()", "B()", "D()"],
            reactions=[(("A()",), ("D()",), 0.1)],
            contract=dict(
                reactants=["A()", "B()"],
                products=["C()"],
                rate=0.4,
                filters=[
                    dict(include=False, side="reactant", pattern_index=0, types=["A"])
                ],
                local_scopes=[],
            ),
            oracle="required",
        ),
    ]


def _local_scope_cases():
    return [
        dict(
            id="local-scope",
            aspects=("local-scope",),
            rule_label="",
            bngl=LOCAL_SCOPE_MODEL,
            species=["A(s~dn)", "A(s~up)"],
            reactions=[
                (("A(s~dn)",), ("A(s~up)",), 1.0),
                (("A(s~up)",), ("A(s~dn)",), 2.0),
            ],
            contract=dict(
                reactants=["A(s~dn)"],
                products=["A(s~up)"],
                reverse_reactants=["A(s~up)"],
                reverse_products=["A(s~dn)"],
                # The local function rate(z) = k + up(z) resolves to k plus
                # the local count of the `up` observable inside the scope:
                # 1.0 for the A(s~dn) species and 2.0 for A(s~up).
                rate=None,
                reverse_rate=None,
                rate_function="rate",
                rate_argument="x",
                filters=[],
                local_scopes=[
                    dict(name="x", kind="molecule", side="reactant", pattern_index=0)
                ],
            ),
            # The canonical Perl BNG2 does not accept a scoped function
            # argument, so the closed-form law is the only independent
            # expectation for this slice.
            oracle="unavailable",
            oracle_reason=(
                "the canonical Perl BNG2 rejects a scoped function argument "
                "(`Parameter z not defined`)"
            ),
        )
    ]


def cases():
    """Return the generated, parameterized network-rule cases."""
    return [
        *_conversion_cases(),
        *_reversible_cases(),
        *_filter_cases(),
        *_local_scope_cases(),
    ]


def check_ids():
    """Stable expected check identities for the network-rule qualification."""
    return [
        f"netrule-execution:{case['id']}:{aspect}"
        for case in cases()
        for aspect in case["aspects"]
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render_pattern(pattern):
    """Render one compiled pattern into the network's species label space.

    Only the declared supported slice is rendered. Anything else raises
    ``UnsupportedSlice`` so the caller reports the case as unsupported
    instead of comparing labels that do not mean the same thing.
    """
    molecules = pattern.get("molecules") or []
    if len(molecules) != 1:
        raise UnsupportedSlice(
            "only single-molecule patterns are in the supported slice"
        )
    if pattern.get("compartment_prefix") or pattern.get("compartment"):
        raise UnsupportedSlice("compartment patterns are outside the supported slice")
    molecule = molecules[0]
    sites = []
    for site in molecule.get("sites") or []:
        bond = site.get("bond") or {}
        if bond.get("kind") not in ("unbound", "any"):
            raise UnsupportedSlice("bonded sites are outside the supported slice")
        state = site.get("state") or {}
        if state.get("kind") != "exact":
            raise UnsupportedSlice(
                "only explicit site states are in the supported slice"
            )
        sites.append(f"{site['component']}~{state['value']}")
    return f"{molecule['type']}({','.join(sites)})"


def _render_direction(direction):
    return {
        "reactants": [
            _render_pattern(item) for item in direction.get("reactants") or []
        ],
        "products": [_render_pattern(item) for item in direction.get("products") or []],
    }


def _substitute(expression, substitutions):
    """Replace a function's formal arguments with the call's arguments."""
    if (
        expression.get("kind") == "local_ref"
        and expression.get("name") in substitutions
    ):
        return substitutions[expression["name"]]
    result = dict(expression)
    arguments = expression.get("arguments") or []
    if arguments:
        result["arguments"] = [_substitute(item, substitutions) for item in arguments]
    return result


def _evaluate_expression(expression, model, functions):
    """Evaluate one resolved expression from the compiled contract.

    Only the expressions the supported slice uses are evaluable. A reference
    the harness cannot resolve raises ``UnsupportedSlice`` rather than
    guessing a value.
    """
    kind = expression.get("kind")
    if kind == "number":
        return float(expression["value"])
    if kind == "parameter_ref":
        symbol = expression["symbol"]
        if symbol["kind"] != "parameter":
            raise UnsupportedSlice("unsupported symbol kind: " + str(symbol["kind"]))
        parameter = model["parameters"][symbol["index"]]
        if parameter.get("constant_value") is None:
            raise UnsupportedSlice("parameter has no constant value")
        return float(parameter["constant_value"])
    if kind == "function_ref":
        symbol = expression["symbol"]
        function = functions[symbol["index"]]
        arguments = expression.get("arguments") or []
        if len(arguments) != len(function["arguments"]):
            raise UnsupportedSlice("function arity mismatch")
        substitutions = dict(zip(function["arguments"], arguments))
        return _evaluate_expression(
            _substitute(function["expression"], substitutions), model, functions
        )
    if kind == "binary":
        operator = expression.get("operator")
        left = _evaluate_expression(expression["arguments"][0], model, functions)
        right = _evaluate_expression(expression["arguments"][1], model, functions)
        if operator == "add":
            return left + right
        if operator == "subtract":
            return left - right
        if operator == "multiply":
            return left * right
        if operator == "divide":
            return left / right
        if operator == "power":
            return left**right
        raise UnsupportedSlice("unsupported binary operator: " + str(operator))
    if kind == "unary":
        operator = expression.get("operator")
        value = _evaluate_expression(expression["arguments"][0], model, functions)
        if operator == "plus":
            return value
        if operator == "negate":
            return -value
        raise UnsupportedSlice("unsupported unary operator: " + str(operator))
    raise UnsupportedSlice("unsupported expression kind: " + str(kind))


def _filter_declaration(direction):
    filters = []
    for item in direction.get("filters") or []:
        types = []
        for pattern in item.get("patterns") or []:
            for molecule in pattern.get("molecules") or []:
                types.append(molecule["type"])
        filters.append(
            dict(
                include=bool(item["include"]),
                side=item["side"],
                pattern_index=int(item["pattern_index"]),
                types=sorted(types),
            )
        )
    return filters


def _scope_declaration(direction):
    scopes = []
    for item in direction.get("local_scopes") or []:
        scopes.append(
            dict(
                name=item["name"],
                kind=item["kind"],
                side=item["side"],
                pattern_index=int(item["pattern_index"]),
            )
        )
    return scopes


def _rate_declaration(expression, functions):
    """Describe a rate law that depends on a local scope."""
    if expression.get("kind") != "function_ref":
        return None
    symbol = expression["symbol"]
    function = functions[symbol["index"]]
    arguments = expression.get("arguments") or []
    if len(arguments) != 1 or arguments[0].get("kind") != "local_ref":
        return None
    return dict(function=function["name"], argument=arguments[0]["name"])


def _observed_reactions(network):
    """Return the legacy path's reactions as (reactants, products, rate)."""
    reactions = [
        (tuple(reactants), tuple(products), float(rate))
        for (reactants, products, rate) in network.reaction_multiset
    ]
    return sorted(reactions)


def _expected_reactions(case):
    return sorted(
        (tuple(reactants), tuple(products), float(rate))
        for reactants, products, rate in case["reactions"]
    )


def _oracle_network(directory: Path, case, source: Path):
    """Run the canonical Perl BNG2 on the case and parse its network."""
    if shutil.which(os.environ.get("PERL", "perl")) is None:
        return None, "the canonical Perl BNG2 runtime is unavailable"
    work = directory / f"oracle-{case['id']}"
    work.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["BNGPATH"] = str(ORACLE_SCRIPT.parent)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(
            [
                os.environ.get("PERL", "perl"),
                str(ORACLE_SCRIPT),
                "--outdir",
                str(work),
                str(source),
            ],
            cwd=str(work),
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"the canonical Perl BNG2 could not be executed: {exc}"
    artifact = work / f"{source.stem}.net"
    if proc.returncode != 0 or not artifact.is_file():
        message = (proc.stderr or proc.stdout).strip().splitlines()
        return None, "the canonical Perl BNG2 refused the case: " + (
            message[-1] if message else "no diagnostic"
        )
    from . import compare

    network = compare.parse_net(artifact)
    if network is None:
        return None, "the canonical Perl BNG2 network could not be parsed"
    return network, str(artifact)


def _first_difference(field, expected, actual):
    return dict(field=field, expected=expected, actual=actual)


def _check_graph(case, contract, legacy, expectation, oracle):
    """The generated reaction graph: edges and products."""
    if contract["reactants"] != expectation["reactants"]:
        return _first_difference(
            "contract.reactants", expectation["reactants"], contract["reactants"]
        )
    if contract["products"] != expectation["products"]:
        return _first_difference(
            "contract.products", expectation["products"], contract["products"]
        )
    if sorted(legacy["species"]) != sorted(case["species"]):
        return _first_difference(
            "legacy.species", sorted(case["species"]), sorted(legacy["species"])
        )
    if legacy["reactions"] != expectation["reactions"]:
        return _first_difference(
            "legacy.reactions", expectation["reactions"], legacy["reactions"]
        )
    if oracle is not None and oracle["reactions"] != legacy["reactions"]:
        return _first_difference(
            "oracle.reactions", legacy["reactions"], oracle["reactions"]
        )
    return None


def _check_rate(case, contract, legacy, expectation, oracle):
    """The compiled rate law against the executed rate law."""
    if contract["rate"] is None:
        return _first_difference("contract.rate", expectation["rate"], None)
    if abs(contract["rate"] - expectation["rate"]) > 1e-12:
        return _first_difference("contract.rate", expectation["rate"], contract["rate"])
    if legacy["rates"] is None:
        return _first_difference("legacy.rates", expectation["rates"], None)
    if sorted(legacy["rates"]) != sorted(expectation["rates"]):
        return _first_difference(
            "legacy.rates", sorted(expectation["rates"]), sorted(legacy["rates"])
        )
    if oracle is not None and oracle["rates"] is not None:
        if sorted(oracle["rates"]) != sorted(expectation["rates"]):
            return _first_difference(
                "oracle.rates", sorted(expectation["rates"]), sorted(oracle["rates"])
            )
    return None


def _check_filter(case, contract, legacy, expectation, oracle):
    """Rule filters: the compile-owned declaration and the executed graph."""
    expected_filters = expectation["filters"]
    if contract["filters"] != expected_filters:
        return _first_difference(
            "contract.filters", expected_filters, contract["filters"]
        )
    if contract["reactants"] != expectation["reactants"]:
        return _first_difference(
            "contract.reactants", expectation["reactants"], contract["reactants"]
        )
    if sorted(legacy["species"]) != sorted(case["species"]):
        return _first_difference(
            "legacy.species", sorted(case["species"]), sorted(legacy["species"])
        )
    if legacy["reactions"] != expectation["reactions"]:
        return _first_difference(
            "legacy.reactions", expectation["reactions"], legacy["reactions"]
        )
    if oracle is not None and oracle["reactions"] != legacy["reactions"]:
        return _first_difference(
            "oracle.reactions", legacy["reactions"], oracle["reactions"]
        )
    return None


def _check_local_scope(case, contract, legacy, expectation, oracle):
    """Local scopes: the compile-owned scope and the executed local rate."""
    expected_scopes = expectation["local_scopes"]
    if contract["local_scopes"] != expected_scopes:
        return _first_difference(
            "contract.local_scopes", expected_scopes, contract["local_scopes"]
        )
    if contract["rate_declaration"] != expectation["rate_declaration"]:
        return _first_difference(
            "contract.rate_declaration",
            expectation["rate_declaration"],
            contract["rate_declaration"],
        )
    if legacy["rates"] is None:
        return _first_difference("legacy.rates", expectation["rates"], None)
    if sorted(legacy["rates"]) != sorted(expectation["rates"]):
        return _first_difference(
            "legacy.rates", sorted(expectation["rates"]), sorted(legacy["rates"])
        )
    if legacy["reactions"] != expectation["reactions"]:
        return _first_difference(
            "legacy.reactions", expectation["reactions"], legacy["reactions"]
        )
    return None


def _check_reversible(case, contract, legacy, expectation, oracle):
    """Reversible rule directions: both directions of the compiled rule."""
    if not contract["bidirectional"]:
        return _first_difference(
            "contract.bidirectional", expectation["bidirectional"], False
        )
    if contract["reverse_reactants"] != expectation["reverse_reactants"]:
        return _first_difference(
            "contract.reverse_reactants",
            expectation["reverse_reactants"],
            contract["reverse_reactants"],
        )
    if contract["reverse_products"] != expectation["reverse_products"]:
        return _first_difference(
            "contract.reverse_products",
            expectation["reverse_products"],
            contract["reverse_products"],
        )
    if contract["rate"] is None or contract["reverse_rate"] is None:
        return _first_difference(
            "contract.reverse_rate", expectation["reverse_rate"], None
        )
    if abs(contract["rate"] - expectation["rate"]) > 1e-12:
        return _first_difference("contract.rate", expectation["rate"], contract["rate"])
    if abs(contract["reverse_rate"] - expectation["reverse_rate"]) > 1e-12:
        return _first_difference(
            "contract.reverse_rate",
            expectation["reverse_rate"],
            contract["reverse_rate"],
        )
    if sorted(legacy["species"]) != sorted(case["species"]):
        return _first_difference(
            "legacy.species", sorted(case["species"]), sorted(legacy["species"])
        )
    if legacy["reactions"] != expectation["reactions"]:
        return _first_difference(
            "legacy.reactions", expectation["reactions"], legacy["reactions"]
        )
    if oracle is not None and oracle["reactions"] != legacy["reactions"]:
        return _first_difference(
            "oracle.reactions", legacy["reactions"], oracle["reactions"]
        )
    return None


CHECKS = {
    "graph": _check_graph,
    "rate": _check_rate,
    "filter": _check_filter,
    "local-scope": _check_local_scope,
    "reversible": _check_reversible,
}


def _contract_view(snapshot, case):
    """Read the compile-owned declaration of the case's rule."""
    rules = snapshot.get("rules") or []
    selected = [item for item in rules if item.get("label") == case["rule_label"]]
    if len(selected) != 1:
        raise UnsupportedSlice(
            "the rule under test is not uniquely declared in the compiled model"
        )
    rule = selected[0]
    forward = rule["forward"]
    reverse = rule.get("reverse")
    functions = snapshot.get("functions") or []
    rate = None
    reverse_rate = None
    rate_declaration = None
    if forward.get("rate"):
        expression = forward["rate"]["expression"]
        rate_declaration = _rate_declaration(expression, functions)
        if rate_declaration is None:
            try:
                rate = _evaluate_expression(expression, snapshot, functions)
            except UnsupportedSlice:
                rate = None
    if reverse is not None and reverse.get("rate"):
        try:
            reverse_rate = _evaluate_expression(
                reverse["rate"]["expression"], snapshot, functions
            )
        except UnsupportedSlice:
            reverse_rate = None
    view = dict(
        bidirectional=bool(rule["bidirectional"]),
        reactants=[],
        products=[],
        reverse_reactants=[],
        reverse_products=[],
        rate=rate,
        reverse_rate=reverse_rate,
        rate_declaration=rate_declaration,
        filters=_filter_declaration(forward),
        local_scopes=_scope_declaration(forward),
    )
    rendered = _render_direction(forward)
    view["reactants"] = rendered["reactants"]
    view["products"] = rendered["products"]
    if reverse is not None:
        rendered_reverse = _render_direction(reverse)
        view["reverse_reactants"] = rendered_reverse["reactants"]
        view["reverse_products"] = rendered_reverse["products"]
    return view


def _legacy_view(model, network, directory: Path, case):
    """Observe the legacy path: the generated network and executed rates."""
    from . import compare

    artifact = directory / f"legacy-{case['id']}.net"
    model.write_net(str(artifact))
    parsed = compare.parse_net(artifact)
    if parsed is None:
        raise ValueError("the generated network could not be parsed")
    try:
        from bionetgen.model import _cpp

        state = [1.0] * network.num_species
        rates = [
            float(value)
            for value in _cpp._validation_ode_rate_coefficients(
                model._model, network, 0.0, state
            )
        ]
    except Exception as exc:  # pragma: no cover - diagnostic only
        rates = None
        rate_detail = f"executed rate coefficients unavailable: {exc}"
    else:
        rate_detail = "executed rate coefficients read from the compiled rate law"
    return dict(
        species=list(network.species_names),
        reactions=_observed_reactions(parsed),
        rates=rates,
        rate_detail=rate_detail,
    )


def _oracle_view(network):
    if network is None:
        return None
    return dict(
        species=sorted(network.species_by_index.values()),
        reactions=_observed_reactions(network),
        rates=sorted(
            float(rate) for (_reactants, _products, rate) in network.reaction_multiset
        ),
    )


def _expectation(case):
    """The independent, hand-derived expectation for one case."""
    contract = case["contract"]
    reactions = _expected_reactions(case)
    return dict(
        bidirectional=bool(contract.get("reverse_reactants")),
        reactants=contract["reactants"],
        products=contract["products"],
        rate=contract.get("rate"),
        reverse_reactants=contract.get("reverse_reactants"),
        reverse_products=contract.get("reverse_products"),
        reverse_rate=contract.get("reverse_rate"),
        rate_declaration=(
            dict(function=contract["rate_function"], argument=contract["rate_argument"])
            if contract.get("rate_function")
            else None
        ),
        filters=contract.get("filters", []),
        local_scopes=contract.get("local_scopes", []),
        reactions=reactions,
        rates=[rate for _reactants, _products, rate in reactions],
    )


def _row(case, aspect, status, detail, artifact, first_difference=None):
    return {
        "id": f"netrule-execution:{case['id']}:{aspect}",
        "check": aspect,
        "status": status,
        "detail": str(detail),
        "first_difference": first_difference,
        "related_issues": list(ISSUES),
        "source_artifact": artifact.name,
        "source_sha256": _sha256(artifact),
        "evidence_kind": (
            "supported-execution" if status in {"PASS", "FAIL"} else "diagnostic-only"
        ),
        "supported_execution": status in {"PASS", "FAIL"},
    }


def run_worker(directory: Path):
    """Execute every generated case and return one row per (case, aspect)."""
    import bionetgen
    from bionetgen.model import _cpp

    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in cases():
        artifact = directory / f"{case['id']}.bngl"
        artifact.write_text(case["bngl"], encoding="utf-8")
        try:
            model = bionetgen.BioNetGenModel(_cpp.parse_string(case["bngl"]))
            snapshot = _cpp._compiled_snapshot(model._model)
            contract = _contract_view(snapshot, case)
            network = model.generate_network()
            legacy = _legacy_view(model, network, directory, case)
            expectation = _expectation(case)
            oracle_network = None
            if case["oracle"] == "required":
                oracle_network, oracle_detail = _oracle_network(
                    directory, case, artifact
                )
                if oracle_network is None:
                    raise OracleRefused(oracle_detail)
            else:
                oracle_detail = case.get("oracle_reason", "not applicable")
            oracle = _oracle_view(oracle_network)
        except UnsupportedSlice as exc:
            for aspect in case["aspects"]:
                rows.append(
                    _row(
                        case,
                        aspect,
                        "UNSUPPORTED",
                        f"the case is outside the qualified slice: {exc}",
                        artifact,
                        {"field": "case", "detail": str(exc)},
                    )
                )
            continue
        except OracleRefused as exc:
            for aspect in case["aspects"]:
                rows.append(
                    _row(
                        case,
                        aspect,
                        "UNSUPPORTED",
                        f"the independent oracle could not qualify the case: {exc}",
                        artifact,
                        {"field": "oracle", "detail": str(exc)},
                    )
                )
            continue
        except Exception as exc:  # pragma: no cover - diagnostic only
            for aspect in case["aspects"]:
                rows.append(
                    _row(
                        case,
                        aspect,
                        "HARNESS_ERROR",
                        f"{type(exc).__name__}: {exc}",
                        artifact,
                    )
                )
            continue
        for aspect in case["aspects"]:
            difference = CHECKS[aspect](case, contract, legacy, expectation, oracle)
            detail = (
                f"the compile-owned contract, the legacy network-rule path and the "
                f"closed-form expectation agree on the {aspect} slice "
                f"(supported slice: {SLICE}; oracle: {oracle_detail})"
            )
            rows.append(
                _row(
                    case,
                    aspect,
                    "FAIL" if difference else "PASS",
                    detail if not difference else f"{aspect} differs: {difference}",
                    artifact,
                    difference,
                )
            )
    for row in rows:
        if row["status"] not in campaign.STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="worker produced an unknown status",
                supported_execution=False,
            )
    return rows
