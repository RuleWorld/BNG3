"""Executable NFnext slice contract (issue #147).

Issue #147 asks for the NFnext lowering to be extended per approved semantic
family, and for each slice to carry a representation, an executor and an
independent test, with an explicit rejection for everything outside the
approved scope.

This module states that contract executably, one slice per candidate family.

``SLICES``
    The approved supported slice. It is deliberately small: unary site-state
    rules with a static elementary rate, isolated integer seed populations and
    unary ``Molecules`` observables.

``FAMILIES``
    The candidate families of the capability matrix, each with the boundary
    the product is expected to hold:

    * a supported family lowers into NFIR, executes, and reproduces an
      independent closed-form law;
    * a refused family is refused by name, in the representation and in the
      executor, and is never approximated by a partial lowering.

The independent reference of the supported slice is the exact pure-death law:
every molecule of the seeded population converts independently at the declared
rate, so the number of unconverted molecules at time ``T`` is binomial with
``N0`` trials and success probability ``exp(-k*T)``. The harness compares the
executor ensemble against that law; it never compares NFnext against another
implementation's output.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

ISSUES = (147,)

# The approved supported slice. Everything outside it stays refused by name.
SLICES = (
    "unary site-state rules with a static elementary rate, isolated integer "
    "seed populations, and unary Molecules observables; every other semantic "
    "family is refused by name instead of being approximated"
)

# The independent reference of the supported slice: the exact pure-death law
# of the seeded population.
REFERENCE = (
    "the exact pure-death law: every seeded molecule converts independently "
    "at the declared rate, so the unconverted count at time T is binomial with "
    "N0 trials and success probability exp(-k*T)"
)

# The ensemble budget and the error budget of the stochastic comparison. The
# bound is a normal-approximation bound over the recorded ensemble, not a
# pathwise claim.
ENSEMBLE_RUNS = 256
SIGMA_BUDGET = 4.0

# The horizon of the comparison.
HORIZON = 2.0

# The seeded population of the supported family.
SEED_COUNT = 100


class UnsupportedSlice(ValueError):
    """The case cannot be qualified inside the approved NFnext slice."""


def _unary_model(rate=0.5):
    return (
        "begin model\n"
        "begin parameters\n"
        f"  k {rate!r}\n"
        "end parameters\n"
        "begin molecule types\n"
        "  A(x~u~p)\n"
        "end molecule types\n"
        "begin seed species\n"
        f"  A(x~u) {SEED_COUNT}\n"
        "end seed species\n"
        "begin observables\n"
        "  Molecules U A(x~u)\n"
        "  Molecules P A(x~p)\n"
        "end observables\n"
        "begin reaction rules\n"
        "  A(x~u) -> A(x~p) k\n"
        "end reaction rules\n"
        "end model\n"
    )


def _dynamic_rate_model():
    return (
        "begin model\n"
        "begin parameters\n"
        "  k 0.5\n"
        "end parameters\n"
        "begin molecule types\n"
        "  A(x~u~p)\n"
        "end molecule types\n"
        "begin seed species\n"
        f"  A(x~u) {SEED_COUNT}\n"
        "end seed species\n"
        "begin observables\n"
        "  Molecules U A(x~u)\n"
        "end observables\n"
        "begin reaction rules\n"
        "  A(x~u) -> A(x~p) k*U()\n"
        "end reaction rules\n"
        "end model\n"
    )


def _filter_model():
    return (
        "begin model\n"
        "begin parameters\n"
        "  k 0.5\n"
        "end parameters\n"
        "begin molecule types\n"
        "  A(x~u~p)\n"
        "  B()\n"
        "end molecule types\n"
        "begin seed species\n"
        f"  A(x~u) {SEED_COUNT}\n"
        "  B() 0\n"
        "end seed species\n"
        "begin reaction rules\n"
        "  A(x~u) + B() -> A(x~u) k include_reactants(1,A)\n"
        "end reaction rules\n"
        "end model\n"
    )


def _modifier_model():
    return (
        "begin model\n"
        "begin parameters\n"
        "  k 0.5\n"
        "end parameters\n"
        "begin molecule types\n"
        "  A(x~u~p)\n"
        "end molecule types\n"
        "begin seed species\n"
        f"  A(x~u) {SEED_COUNT}\n"
        "end seed species\n"
        "begin reaction rules\n"
        "  A(x~u) -> A(x~p) k MatchOnce\n"
        "end reaction rules\n"
        "end model\n"
    )


def _compartment_model():
    return (
        "begin model\n"
        "begin parameters\n"
        "  k 0.5\n"
        "end parameters\n"
        "begin compartments\n"
        "  cell 1 1\n"
        "end compartments\n"
        "begin molecule types\n"
        "  A(x~u~p)\n"
        "end molecule types\n"
        "begin seed species\n"
        f"  A(x~u) {SEED_COUNT}\n"
        "end seed species\n"
        "begin reaction rules\n"
        "  A(x~u) -> A(x~p) k\n"
        "end reaction rules\n"
        "end model\n"
    )


def _population_map_model():
    return (
        "begin model\n"
        "begin parameters\n"
        "  k 0.5\n"
        "  k_gather 0.2\n"
        "end parameters\n"
        "begin molecule types\n"
        "  A(x~u~p)\n"
        "  A_pop()\n"
        "end molecule types\n"
        "begin seed species\n"
        f"  A(x~u) {SEED_COUNT}\n"
        "end seed species\n"
        "begin population maps\n"
        "  A() -> A_pop() k_gather\n"
        "end population maps\n"
        "begin reaction rules\n"
        "  A(x~u) -> A(x~p) k\n"
        "end reaction rules\n"
        "end model\n"
    )


def _energy_model():
    return (
        "begin model\n"
        "begin parameters\n"
        "  k 0.5\n"
        "  Gf 1\n"
        "end parameters\n"
        "begin molecule types\n"
        "  A(x~u~p)\n"
        "end molecule types\n"
        "begin seed species\n"
        f"  A(x~u) {SEED_COUNT}\n"
        "end seed species\n"
        "begin energy patterns\n"
        "  A(x~u) Gf\n"
        "end energy patterns\n"
        "begin reaction rules\n"
        "  A(x~u) -> A(x~p) k\n"
        "end reaction rules\n"
        "end model\n"
    )


def families():
    """Return the candidate families and the boundary each one must hold."""
    return [
        dict(
            id="unary-site-state",
            family="unary site-state rules",
            supported=True,
            keyword="unary site-state",
            bngl=_unary_model(),
            rate=0.5,
        ),
        dict(
            id="dynamic-rates",
            family="dynamic rates",
            supported=False,
            keyword="dynamic",
            bngl=_dynamic_rate_model(),
        ),
        dict(
            id="filters",
            family="rule filters",
            supported=False,
            keyword="filter",
            bngl=_filter_model(),
        ),
        dict(
            id="modifiers",
            family="rule modifiers",
            supported=False,
            keyword="modifier",
            bngl=_modifier_model(),
        ),
        dict(
            id="compartments",
            family="compartments",
            supported=False,
            keyword="compartment",
            bngl=_compartment_model(),
        ),
        dict(
            id="population-maps",
            family="population maps",
            supported=False,
            keyword="population",
            bngl=_population_map_model(),
        ),
        dict(
            id="energy",
            family="energy patterns",
            supported=False,
            keyword="energy",
            bngl=_energy_model(),
        ),
    ]


def check_ids():
    """Stable expected check identities for the NFnext slice qualification."""
    return [
        f"nfnext-slices:{family['id']}:{aspect}"
        for family in families()
        for aspect in ("representation", "executor", "independent-reference")
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(family_id, aspect, status, detail, artifact, first_difference=None, **extra):
    # A refused family demonstrates a refusal, not a supported execution: its
    # evidence kind stays diagnostic so that no report can read it as support.
    supported = bool(extra.pop("supported_execution", False))
    row = {
        "id": f"nfnext-slices:{family_id}:{aspect}",
        "check": aspect,
        "status": status,
        "detail": str(detail),
        "first_difference": first_difference,
        "related_issues": list(ISSUES),
        "source_artifact": artifact.name,
        "source_sha256": _sha256(artifact),
        "evidence_kind": (
            "supported-execution"
            if supported and status in {"PASS", "FAIL"}
            else "diagnostic-only"
        ),
        "supported_execution": supported and status in {"PASS", "FAIL"},
    }
    row.update(extra)
    return row


def _difference(field, expected, observed, **extra):
    difference = dict(field=field, expected=expected, observed=observed)
    difference.update(extra)
    return difference


def _constant_rate_expression(expression, parameters):
    """True when the compiled rate expression is a constant parameter."""
    if expression.get("kind") != "parameter_ref":
        return False
    symbol = expression.get("symbol") or {}
    if symbol.get("kind") != "parameter":
        return False
    index = symbol.get("index")
    if not isinstance(index, int) or index >= len(parameters):
        return False
    return parameters[index].get("constant_value") is not None


def _snapshot_constructs(snapshot):
    """Read the semantic constructs the source model declares.

    This is the harness's own reading of the compiled model. It is the
    independent attribution of a refusal: a family is only refused because
    the source declares it.
    """
    constructs = {
        "compartment": bool(snapshot.get("compartments")),
        "population map": bool(snapshot.get("population_maps")),
        "energy pattern": bool(snapshot.get("energy_patterns")),
        "filter": False,
        "modifier": False,
        "dynamic rate": False,
    }
    parameters = snapshot.get("parameters") or []
    for rule in snapshot.get("rules") or []:
        for modifier in rule.get("modifiers") or []:
            kind = str(modifier.get("kind"))
            if kind in ("include_reactants", "exclude_reactants"):
                constructs["filter"] = True
            elif kind in ("include_products", "exclude_products"):
                constructs["filter"] = True
            else:
                constructs["modifier"] = True
        for direction in (rule.get("forward"), rule.get("reverse")):
            if not direction:
                continue
            if direction.get("filters"):
                constructs["filter"] = True
            rate = direction.get("rate")
            if rate and not _constant_rate_expression(
                rate.get("expression") or {}, parameters
            ):
                constructs["dynamic rate"] = True
    return constructs


def _expected_representation(family, lowered, snapshot):
    """Compare the lowered NFIR against the declared representation."""
    if family["supported"]:
        problems = []
        rules = lowered.get("rules") or []
        if len(rules) != 1:
            problems.append(_difference("rules.count", 1, len(rules)))
        else:
            rule = rules[0]
            if not _close(rule.get("rate"), family["rate"]):
                problems.append(
                    _difference("rule.rate", family["rate"], rule.get("rate"))
                )
            if rule.get("rate_law_kind") != "elementary":
                problems.append(
                    _difference(
                        "rule.rate_law_kind", "elementary", rule.get("rate_law_kind")
                    )
                )
            nodes = rule["pattern"].get("nodes") or []
            if len(nodes) != 1:
                problems.append(_difference("rule.pattern.nodes", 1, len(nodes)))
            kinds = sorted(item["kind"] for item in rule.get("predicates") or [])
            if kinds != ["site_free", "site_state_eq"]:
                problems.append(
                    _difference(
                        "rule.predicates", ["site_free", "site_state_eq"], kinds
                    )
                )
            actions = rule.get("actions") or []
            if len(actions) != 1 or actions[0].get("kind") != "set_site_state":
                problems.append(
                    _difference(
                        "rule.actions",
                        ["set_site_state"],
                        [item.get("kind") for item in actions],
                    )
                )
            # The state indices are derived from the source declaration, not
            # from the lowered IR: `u` is the first declared state and `p` the
            # second.
            states = _declared_states(snapshot, "A", "x")
            if states != ["u", "p"]:
                problems.append(_difference("molecule.states", ["u", "p"], states))
            if nodes and rule.get("predicates"):
                predicate = next(
                    (
                        item
                        for item in rule["predicates"]
                        if item["kind"] == "site_state_eq"
                    ),
                    None,
                )
                if predicate is not None and predicate.get("value") != 0:
                    problems.append(
                        _difference("rule.predicate.value", 0, predicate.get("value"))
                    )
                if actions and actions[0].get("value") != 1:
                    problems.append(
                        _difference("rule.action.value", 1, actions[0].get("value"))
                    )
        if lowered.get("ok") is not True:
            problems.append(_difference("lowering.ok", True, lowered.get("ok")))
        return problems
    # A refused family: the representation must report the construct and must
    # not carry a partial approximation of it.
    issues = lowered.get("issues") or []
    messages = " | ".join(str(item.get("message")) for item in issues)
    problems = []
    if family["keyword"].lower() not in messages.lower():
        problems.append(
            _difference(
                "lowering.issue", "a message naming " + family["keyword"], messages
            )
        )
    errors = [item for item in issues if item.get("severity") == "error"]
    if errors and lowered.get("rules"):
        problems.append(
            _difference(
                "lowering.rules",
                [],
                [item.get("name") for item in lowered.get("rules") or []],
            )
        )
    return problems


def _declared_states(snapshot, molecule, site):
    for item in snapshot.get("molecule_types") or []:
        if item.get("name") != molecule:
            continue
        for component in item.get("components") or []:
            if component.get("name") == site:
                return list(component.get("states") or [])
    return []


def _expected_executor(family, execution):
    """Compare the executor outcome against the declared boundary."""
    problems = []
    if family["supported"]:
        if execution.get("refused"):
            problems.append(
                _difference("execution.refused", False, execution.get("reason"))
            )
            return problems
        columns = list(execution.get("columns") or [])
        if columns != ["time", "U", "P"]:
            problems.append(
                _difference("execution.columns", ["time", "U", "P"], columns)
            )
        rows = execution.get("rows") or []
        if not rows:
            problems.append(_difference("execution.rows", "at least one row", []))
            return problems
        first = rows[0]
        if [float(value) for value in first] != [0.0, float(SEED_COUNT), 0.0]:
            problems.append(
                _difference(
                    "execution.first_row",
                    [0.0, float(SEED_COUNT), 0.0],
                    [float(value) for value in first],
                )
            )
        previous = None
        for row in rows:
            values = [float(value) for value in row]
            if values[1] + values[2] != float(SEED_COUNT):
                problems.append(
                    _difference(
                        "execution.conservation",
                        float(SEED_COUNT),
                        values[1] + values[2],
                    )
                )
            if previous is not None and values[1] > previous:
                problems.append(
                    _difference("execution.monotone", "<= " + str(previous), values[1])
                )
            previous = values[1]
        return problems
    if not execution.get("refused"):
        problems.append(
            _difference(
                "execution.refused",
                "a refusal naming " + family["keyword"],
                "the executor produced rows",
            )
        )
        return problems
    reason = str(execution.get("reason") or "")
    if family["keyword"].lower() not in reason.lower():
        problems.append(
            _difference(
                "execution.reason", "a reason naming " + family["keyword"], reason
            )
        )
    if execution.get("rows"):
        problems.append(_difference("execution.rows", [], execution.get("rows")))
    return problems


def _close(observed, expected):
    if observed is None or expected is None:
        return observed == expected
    return abs(float(observed) - float(expected)) <= 1e-9 * max(
        1.0, abs(float(expected))
    )


def _independent_reference(family, model, snapshot):
    """Compare the executor ensemble against the independent closed-form law."""
    from bionetgen import _bionetgen_cpp as cpp

    if not family["supported"]:
        # The family is refused before execution, so no law can be compared.
        # The independent reference is the attribution of the refusal: the
        # source declares the construct and the product refused it by name.
        constructs = _snapshot_constructs(snapshot)
        present = [name for name, value in constructs.items() if value]
        expected = family["keyword"].lower()
        named = [name for name in present if expected in name.lower()]
        if not named:
            return _difference(
                "reference.construct",
                "the source declares " + family["keyword"],
                present,
            )
        return None
    rate = float(family["rate"])
    expectation = SEED_COUNT * math.exp(-rate * HORIZON)
    samples = []
    for seed in range(ENSEMBLE_RUNS):
        execution = cpp._nfnext_execute(
            model._model, [0.0, HORIZON], seed, 1_000_000, 1_000_000
        )
        if execution.get("refused"):
            return _difference(
                "reference.execution",
                "an executed trajectory",
                execution.get("reason"),
            )
        rows = execution.get("rows") or []
        if not rows:
            return _difference("reference.rows", "at least one row", [])
        samples.append(float(rows[-1][1]))
    mean = sum(samples) / len(samples)
    variance = sum((value - mean) ** 2 for value in samples) / max(1, len(samples) - 1)
    probability = math.exp(-rate * HORIZON)
    exact_variance = SEED_COUNT * probability * (1.0 - probability)
    standard_error = math.sqrt(exact_variance / len(samples))
    limit = SIGMA_BUDGET * standard_error
    if abs(mean - expectation) > limit:
        return _difference(
            "reference.mean",
            expectation,
            mean,
            limit=limit,
            ensemble_runs=len(samples),
        )
    # The spread is a distributional property of the pure-death law and not
    # only of its mean.
    if exact_variance > 0.0 and not (0.5 <= variance / exact_variance <= 2.0):
        return _difference(
            "reference.variance",
            exact_variance,
            variance,
            ensemble_runs=len(samples),
        )
    # The reproducibility control: the same seed must reproduce the path.
    first = cpp._nfnext_execute(model._model, [0.0, HORIZON], 7, 1_000_000, 1_000_000)
    second = cpp._nfnext_execute(model._model, [0.0, HORIZON], 7, 1_000_000, 1_000_000)
    if first.get("rows") != second.get("rows"):
        return _difference(
            "reference.reproducibility",
            first.get("rows"),
            second.get("rows"),
        )
    return None


def _run_family(family, directory: Path):
    import bionetgen
    from bionetgen import _bionetgen_cpp as cpp
    from bionetgen.model import _cpp

    artifact = directory / (family["id"] + ".bngl")
    artifact.write_text(family["bngl"], encoding="utf-8")
    model = bionetgen.BioNetGenModel(_cpp.parse_string(family["bngl"]))
    snapshot = _cpp._compiled_snapshot(model._model)
    lowered = cpp._nfnext_lower(model._model)
    execution = cpp._nfnext_execute(
        model._model, [0.0, HORIZON], 7, 1_000_000, 1_000_000
    )

    representation = _expected_representation(family, lowered, snapshot)
    executor = _expected_executor(family, execution)
    reference = _independent_reference(family, model, snapshot)

    boundary = (
        "the family is inside the approved slice and reproduces " + REFERENCE
        if family["supported"]
        else "the family is outside the approved slice and is refused by name"
    )
    supported = bool(family["supported"])
    rows = [
        _row(
            family["id"],
            "representation",
            "FAIL" if representation else "PASS",
            (
                (
                    "the NFIR representation matches the declared representation; "
                    + boundary
                )
                if not representation
                else f"the representation differs: {representation[0]}"
            ),
            artifact,
            representation[0] if representation else None,
            supported_execution=supported,
            expectation=(
                "one NFIR rule with the declared rate, predicates and action"
                if family["supported"]
                else "a lowering issue naming " + family["keyword"]
            ),
            slice=SLICES,
        ),
        _row(
            family["id"],
            "executor",
            "FAIL" if executor else "PASS",
            (
                ("the executor outcome matches the declared boundary; " + boundary)
                if not executor
                else f"the executor differs: {executor[0]}"
            ),
            artifact,
            executor[0] if executor else None,
            supported_execution=supported,
            expectation=(
                "the declared columns and a conserving, monotone trajectory"
                if family["supported"]
                else "a refusal naming " + family["keyword"]
            ),
        ),
        _row(
            family["id"],
            "independent-reference",
            "FAIL" if reference else "PASS",
            (
                (
                    "the executor ensemble agrees with the independent reference: "
                    + REFERENCE
                )
                if family["supported"] and not reference
                else (
                    "the refusal is attributable to the construct the source "
                    "declares"
                    if not family["supported"] and not reference
                    else f"the independent reference differs: {reference}"
                )
            ),
            artifact,
            reference,
            supported_execution=supported,
            expectation=(
                REFERENCE
                if family["supported"]
                else "the source declares " + family["keyword"]
            ),
            ensemble_runs=ENSEMBLE_RUNS if family["supported"] else None,
            alpha=None,
        ),
    ]
    return rows


def run_worker(directory: Path):
    """Execute every family and return one row per named check."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for family in families():
        try:
            rows.extend(_run_family(family, directory))
        except Exception as exc:  # pragma: no cover - diagnostic only
            for aspect in ("representation", "executor", "independent-reference"):
                rows.append(
                    _row(
                        family["id"],
                        aspect,
                        "HARNESS_ERROR",
                        f"{type(exc).__name__}: {exc}",
                        directory / (family["id"] + ".bngl"),
                    )
                )
    return rows
