"""Executable rate-law and local-function contract (issue #143).

Issue #143 asks for the shared rate-law contract to be stated once: the
special-rate, TFUN, scope, multiplicity and dependency/evaluation conventions
that the engine, the network generator and the writers must agree on, and for
the supported backends' coefficients, right-hand sides and propensities to be
compared against an independent reference rather than against another
implementation's own output.

This module states that contract executably.

``CONVENTIONS``
    The conventions, written once. Every case below is checked against them.

``SUPPORTED_SLICE``
    The declared supported subset. A case whose compiled declaration does not
    match the slice is reported as ``UNSUPPORTED`` with the reason that names
    the construct that put it outside; it is never skipped quietly.

The independent reference is always a closed form written here in the harness:

* the elementary, saturation and Hill coefficient laws are the closed-form
  rate expressions of the generated model;
* the Michaelis-Menten coefficient is the self-consistent free-substrate root
  of the quadratic the law defines;
* the table-function coefficient is the linear interpolation of the tabulated
  knots, clamped outside the tabulated range;
* the local-scope coefficient is the declared rate plus the scoped count;
* the right-hand side is the stoichiometry of the generated reaction applied to
  the coefficient and the state;
* the SSA propensity is the coefficient times the discrete reactant product,
  with the identical-reactant correction and the total-rate exemption.

The engine is observed through its own compiled reaction data: the per-reaction
coefficient, the per-species derivative and the per-reaction propensity. The
comparison never reads a value that the engine produced from the same quantity
the expectation is derived from.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

ISSUES = (143,)

# The compiled rate-law kinds, as reported by the compiled-model snapshot.
RATE_LAW_KINDS = {
    "expression": 0,
    "arrhenius": 1,
    "saturation": 2,
    "michaelis_menten": 3,
    "hill": 4,
    "function_product": 5,
    "hybrid": 6,
}

# The declared supported subset. A case outside this slice is reported as
# UNSUPPORTED with the construct that put it outside, never skipped.
SUPPORTED_SLICE = (
    "single-reaction rules over free, non-compartment molecules with no "
    "filter, no rule modifier, no energy pattern and no population map; rate "
    "laws that resolve to an elementary parameter rate, a Saturation or Hill "
    "special rate, a two-reactant MichaelisMenten special rate, a table "
    "function, or a model function whose only argument is a local molecule "
    "scope"
)

# The conventions, stated once. Each case is checked against these.
CONVENTIONS = {
    "special-rate": (
        "Sat(Vmax,Km) is a total rate: the coefficient is Vmax*S/(Km+S) for "
        "the first reactant species S and the coefficient is not multiplied by "
        "the reactant concentration again. Hill(Vmax,Kh,n) is a total rate "
        "with coefficient Vmax*S^n/(Kh^n+S^n). MM(kcat,Km) is qualified in its "
        "two-reactant form, as in BNG2: the first declared reactant is the "
        "substrate St and the second is the enzyme Et, the free substrate S is "
        "the positive root of S^2 + (Km + Et - St)*S - St*Km, and the total "
        "rate is kcat*Et*S/(Km + S). A single-reactant MM is outside the "
        "qualified slice: BNG2 refuses it, and BNG3 lowers it as a saturation."
    ),
    "tfun": (
        "A table function is linearly interpolated between its knots and is "
        "clamped to the first/last tabulated value outside the tabulated "
        "range; the 'step' method takes the value of the knot to the left."
    ),
    "scope": (
        "A local molecule scope binds one matched reactant molecule; a scoped "
        "observable reference counts the matching molecules inside that scope "
        "only. The scoped rate is resolved per generated reaction, so its "
        "coefficient is a property of the generated reaction, not of the "
        "global state."
    ),
    "multiplicity": (
        "The compiled coefficient of an ordinary reaction is the elementary "
        "rate constant times the symmetry factor 1/n! for n identical reactant "
        "species. The ODE rate multiplies the coefficient by the product of "
        "the reactant amounts; the SSA propensity multiplies it by the "
        "discrete product n*(n-1)*... of the reactant populations and is the "
        "coefficient itself for a total rate. The symmetry factor is a "
        "property of the rule's reactants and not of the rate law's shape, so "
        "a Saturation, Hill or Michaelis-Menten law of a rule with identical "
        "reactants carries the same 1/n! factor, as BNG2's own network writer "
        "and this engine's own network writer both emit."
    ),
    "dependency": (
        "A rate that reads an observable, the clock or a table function is a "
        "functional rate: its coefficient is re-evaluated at every evaluation "
        "point from the current state and time, and it is never memoized from "
        "an earlier state or an earlier time."
    ),
    "cache": (
        "A parameter change invalidates every cached value that depends on it, "
        "including a parameter that is defined in terms of it, and the "
        "generated network that carries the compiled rate law is rebuilt."
    ),
}

# The convention each generated case family demonstrates.
FAMILY_CONVENTION = {
    "elementary": "multiplicity",
    "special-saturation": "special-rate",
    "special-hill": "special-rate",
    "special-michaelis-menten": "special-rate",
    "special-multiplicity": "multiplicity",
    "table-function": "tfun",
    "local-scope": "scope",
    "multiplicity": "multiplicity",
    "dependency": "dependency",
    "cache-invalidation": "cache",
}

# The numeric tolerance for the closed-form comparisons. The engine evaluates
# the same closed forms in double precision, so the tolerance only absorbs the
# last-bit differences of the order of operations.
TOLERANCE = 1e-9

# The tolerance of the trajectory control. It is the error budget of the
# numerical solver, not of the rate law: the solver is run far tighter than
# this, so the comparison measures the rate law and not the solver.
TRAJECTORY_TOLERANCE = 1e-7

# The ODE horizon and step count of the trajectory control.
TRAJECTORY_END = 2.0
TRAJECTORY_STEPS = 200


class UnsupportedSlice(ValueError):
    """The case cannot be qualified inside the declared supported slice."""


def _model_source(
    *,
    parameters: str,
    molecule_types: str,
    seeds: str,
    observables: str = "",
    functions: str = "",
    rules: str,
    extra: str = "",
) -> str:
    blocks = ["begin model", "begin parameters\n" + parameters + "\nend parameters"]
    if extra:
        blocks.append(extra.strip("\n"))
    blocks.append("begin molecule types\n" + molecule_types + "\nend molecule types")
    blocks.append("begin seed species\n" + seeds + "\nend seed species")
    if observables:
        blocks.append("begin observables\n" + observables + "\nend observables")
    if functions:
        blocks.append("begin functions\n" + functions + "\nend functions")
    blocks.append("begin reaction rules\n" + rules + "\nend reaction rules")
    blocks.append("end model")
    return "\n".join(blocks) + "\n"


def _elementary_cases():
    cases = []
    for index, (rate, amount) in enumerate(((0.4, 10), (0.05, 100))):
        cases.append(
            dict(
                id=f"elementary-r{index}",
                family="elementary",
                bngl=_model_source(
                    parameters=f"  k {rate!r}",
                    molecule_types="  A()\n  B()",
                    seeds=f"  A() {amount}\n  B() 0",
                    observables="  Molecules A A()\n  Molecules B B()",
                    rules="  A() -> B() k",
                ),
                rate_law_kind="expression",
                states=[{"A()": float(amount), "B()": 0.0}],
                reactions=[
                    [
                        dict(
                            reactants=["A()"],
                            products=["B()"],
                            coefficient=rate,
                            propensity=rate * amount,
                        )
                    ]
                ],
                rhs=[{"A()": -rate * amount, "B()": rate * amount}],
                expectation=(
                    "the elementary mass-action coefficient k, the derivative "
                    "-k*A and the discrete propensity k*n"
                ),
            )
        )
    return cases


def _saturation_cases():
    cases = []
    for index, (vmax, km, amount) in enumerate(((2.0, 10.0, 1000), (0.5, 4.0, 40))):
        coefficient = vmax * amount / (km + amount)
        cases.append(
            dict(
                id=f"special-sat-r{index}",
                family="special-saturation",
                bngl=_model_source(
                    parameters=f"  Vmax {vmax!r}\n  Km {km!r}",
                    molecule_types="  A()",
                    seeds=f"  A() {amount}",
                    rules="  A() -> 0 Sat(Vmax,Km)",
                ),
                rate_law_kind="saturation",
                states=[{"A()": float(amount)}],
                reactions=[
                    [
                        dict(
                            reactants=["A()"],
                            products=[],
                            coefficient=coefficient,
                            propensity=coefficient,
                        )
                    ]
                ],
                rhs=[{"A()": -coefficient}],
                expectation=(
                    "the total saturation rate Vmax*S/(Km+S) at the seeded "
                    "substrate amount"
                ),
            )
        )
    return cases


def _hill_cases():
    cases = []
    for index, (vmax, kh, exponent, amount) in enumerate(
        ((2.0, 10.0, 2, 1000), (3.0, 5.0, 3, 50))
    ):
        coefficient = vmax * amount**exponent / (kh**exponent + amount**exponent)
        cases.append(
            dict(
                id=f"special-hill-r{index}",
                family="special-hill",
                bngl=_model_source(
                    parameters=(f"  Vmax {vmax!r}\n  Kh {kh!r}\n  n {exponent!r}"),
                    molecule_types="  A()",
                    seeds=f"  A() {amount}",
                    rules="  A() -> 0 Hill(Vmax,Kh,n)",
                ),
                rate_law_kind="hill",
                states=[{"A()": float(amount)}],
                reactions=[
                    [
                        dict(
                            reactants=["A()"],
                            products=[],
                            coefficient=coefficient,
                            propensity=coefficient,
                        )
                    ]
                ],
                rhs=[{"A()": -coefficient}],
                expectation=(
                    "the total Hill rate Vmax*S^n/(Kh^n+S^n) at the seeded "
                    "substrate amount"
                ),
            )
        )
    return cases


def _michaelis_menten_cases():
    cases = []
    for index, (kcat, km, substrate, enzyme) in enumerate(
        ((2.0, 10.0, 100, 5), (0.4, 25.0, 60, 12))
    ):
        # The self-consistent free substrate: the positive root of
        # S^2 + (Km + Et - St)*S - St*Km.
        offset = substrate - enzyme - km
        free = 0.5 * (offset + math.sqrt(offset * offset + 4.0 * substrate * km))
        coefficient = kcat * enzyme * free / (km + free)
        cases.append(
            dict(
                id=f"special-mm-r{index}",
                family="special-michaelis-menten",
                bngl=_model_source(
                    parameters=f"  kcat {kcat!r}\n  Km {km!r}",
                    molecule_types="  E()\n  S()",
                    seeds=f"  E() {enzyme}\n  S() {substrate}",
                    rules="  S() + E() -> E() MM(kcat,Km)",
                ),
                rate_law_kind="michaelis_menten",
                states=[{"E()": float(enzyme), "S()": float(substrate)}],
                reactions=[
                    [
                        dict(
                            reactants=["S()", "E()"],
                            products=["E()"],
                            coefficient=coefficient,
                            propensity=coefficient,
                        )
                    ]
                ],
                rhs=[{"E()": 0.0, "S()": -coefficient}],
                expectation=(
                    "the self-consistent Michaelis-Menten total rate "
                    "kcat*Et*S/(Km+S) at the seeded substrate and enzyme amounts"
                ),
            )
        )
    return cases


def _tfun_cases():
    # The tabulated knots and the values the convention states for them.
    xs = [0.0, 1.0, 2.0]
    ys = [0.0, 10.0, 20.0]
    cases = []
    for index, (time, expected) in enumerate(((0.5, 5.0), (-1.0, 0.0), (3.0, 20.0))):
        cases.append(
            dict(
                id=f"tfun-t{index}",
                family="table-function",
                bngl=_model_source(
                    parameters="  k 1",
                    molecule_types="  X()",
                    seeds="  X() 0",
                    functions="  f() = tfun([0,1,2], [0,10,20], time)",
                    rules="  0 -> X() f()",
                ),
                rate_law_kind="expression",
                time=time,
                states=[{"X()": 0.0}],
                reactions=[
                    [
                        dict(
                            reactants=[],
                            products=["X()"],
                            coefficient=expected,
                            propensity=expected,
                        )
                    ]
                ],
                rhs=[{"X()": expected}],
                expectation=(
                    "the linear interpolation of the tabulated knots, clamped "
                    "outside the tabulated range"
                ),
            )
        )
    return cases


def _local_scope_cases():
    return [
        dict(
            id="local-scope",
            family="local-scope",
            bngl=_model_source(
                parameters="  k 1.0",
                molecule_types="  A(s~up~dn)",
                seeds="  A(s~dn) 1\n  A(s~up) 1",
                observables="  Molecules up A(s~up)",
                functions="  rate(z) = k + up(z)",
                rules="  A%x(s~dn) <-> A%x(s~up) rate(x), rate(x)",
            ),
            rate_law_kind="expression",
            states=[{"A(s~dn)": 1.0, "A(s~up)": 1.0}],
            reactions=[
                [
                    # The forward direction's scope holds the A(s~dn)
                    # molecule, so the scoped count of `up` is zero; the
                    # reverse direction's scope holds the A(s~up) molecule, so
                    # the scoped count is one.
                    dict(
                        reactants=["A(s~dn)"],
                        products=["A(s~up)"],
                        coefficient=1.0,
                        propensity=1.0,
                    ),
                    dict(
                        reactants=["A(s~up)"],
                        products=["A(s~dn)"],
                        coefficient=2.0,
                        propensity=2.0,
                    ),
                ]
            ],
            rhs=[{"A(s~dn)": 1.0, "A(s~up)": -1.0}],
            expectation=(
                "the scoped rate k plus the scoped count of the `up` observable "
                "in each direction's local scope"
            ),
        )
    ]


def _special_multiplicity_cases():
    """A special rate law on a rule with identical reactants.

    The symmetry factor is a property of the rule's reactants, not of the
    rate law's shape.  BNG2 writes it as a prefix on the rate law for every
    rate law type (``RateLaw::toString``), so its own network for
    ``A() + A() -> D() Sat(Vmax,Km)`` reads ``0.5*Sat Vmax Km``; this engine's
    own network writer emits the same prefix.  The engine used to drop the
    factor for a special rate law, so it disagreed with the network it
    exported and with BNG2's trajectory.
    """
    cases = []
    for index, (vmax, km, amount) in enumerate(((0.4, 10.0, 20), (2.0, 5.0, 50))):
        # BNG2's Sat lowering: statFactor * Vmax * S1 * S2 / (Km + S1).
        coefficient = 0.5 * vmax * amount * amount / (km + amount)
        cases.append(
            dict(
                id=f"special-multiplicity-r{index}",
                family="special-multiplicity",
                bngl=_model_source(
                    parameters=f"  Vmax {vmax!r}\n  Km {km!r}",
                    molecule_types="  A()\n  D()",
                    seeds=f"  A() {amount}",
                    rules="  A() + A() -> D() Sat(Vmax,Km)",
                ),
                rate_law_kind="saturation",
                states=[{"A()": float(amount), "D()": 0.0}],
                reactions=[
                    [
                        dict(
                            reactants=["A()", "A()"],
                            products=["D()"],
                            coefficient=coefficient,
                            propensity=coefficient,
                        )
                    ]
                ],
                rhs=[{"A()": -2.0 * coefficient, "D()": coefficient}],
                expectation=(
                    "the saturation rate Vmax*S1*S2/(Km+S1) scaled by the "
                    "statistical factor 1/2! of the identical reactants, and "
                    "the propensity of that same total rate"
                ),
            )
        )
    return cases


def _multiplicity_cases():
    cases = []
    # Distinct reactants: no symmetry factor.
    cases.append(
        dict(
            id="multiplicity-distinct",
            family="multiplicity",
            bngl=_model_source(
                parameters="  k 0.4",
                molecule_types="  A()\n  B()\n  C()",
                seeds="  A() 6\n  B() 5\n  C() 0",
                rules="  A() + B() -> C() k",
            ),
            rate_law_kind="expression",
            states=[{"A()": 6.0, "B()": 5.0, "C()": 0.0}],
            reactions=[
                [
                    dict(
                        reactants=["A()", "B()"],
                        products=["C()"],
                        coefficient=0.4,
                        propensity=0.4 * 6 * 5,
                    )
                ]
            ],
            rhs=[{"A()": -12.0, "B()": -12.0, "C()": 12.0}],
            expectation=(
                "the coefficient k of a distinct-reactant reaction, the "
                "derivative -k*A*B and the discrete propensity k*nA*nB"
            ),
        )
    )
    # Identical reactants: the symmetry factor 1/2! and the discrete
    # correction n*(n-1).
    cases.append(
        dict(
            id="multiplicity-identical",
            family="multiplicity",
            bngl=_model_source(
                parameters="  k 0.4",
                molecule_types="  A()\n  B()",
                seeds="  A() 6\n  B() 0",
                rules="  A() + A() -> B() k",
            ),
            rate_law_kind="expression",
            states=[{"A()": 6.0, "B()": 0.0}],
            reactions=[
                [
                    dict(
                        reactants=["A()", "A()"],
                        products=["B()"],
                        coefficient=0.2,
                        propensity=0.2 * 6 * 5,
                    )
                ]
            ],
            rhs=[{"A()": -14.4, "B()": 7.2}],
            expectation=(
                "the coefficient k/2! of an identical-reactant reaction, the "
                "derivative -(k/2)*A^2 and the discrete propensity "
                "(k/2)*n*(n-1)"
            ),
        )
    )
    return cases


def _dependency_cases():
    return [
        dict(
            id="dependency-observable",
            family="dependency",
            bngl=_model_source(
                parameters="  k 0.5",
                molecule_types="  B()\n  C()",
                seeds="  B() 10\n  C() 0",
                observables="  Molecules B B()",
                rules="  B() -> C() k*B()",
            ),
            rate_law_kind="expression",
            # Two states of the same model: the coefficient must follow the
            # observable, not a value captured at the first evaluation.
            states=[{"B()": 10.0, "C()": 0.0}, {"B()": 4.0, "C()": 0.0}],
            reactions=[
                [
                    dict(
                        reactants=["B()"],
                        products=["C()"],
                        coefficient=5.0,
                        propensity=5.0 * 10,
                    )
                ],
                [
                    dict(
                        reactants=["B()"],
                        products=["C()"],
                        coefficient=2.0,
                        propensity=2.0 * 4,
                    )
                ],
            ],
            rhs=[{"B()": -50.0, "C()": 50.0}, {"B()": -8.0, "C()": 8.0}],
            expectation=(
                "the coefficient k times the current observable value, "
                "re-evaluated at each state"
            ),
        )
    ]


def _cache_cases():
    return [
        dict(
            id="cache-rate-parameter",
            family="cache-invalidation",
            bngl=_model_source(
                parameters="  k 0.4",
                molecule_types="  A()\n  B()",
                seeds="  A() 10\n  B() 0",
                observables="  Molecules A A()",
                rules="  A() -> B() k",
            ),
            rate_law_kind="expression",
            states=[{"A()": 10.0, "B()": 0.0}],
            reactions=[
                [
                    dict(
                        reactants=["A()"],
                        products=["B()"],
                        coefficient=0.4,
                        propensity=4.0,
                    )
                ]
            ],
            rhs=[{"A()": -4.0, "B()": 4.0}],
            expectation="the elementary coefficient k before the change",
            # The change that must invalidate the dependent caches.
            mutation=dict(parameter="k", value=0.8),
            mutated=dict(
                reactions=[
                    [
                        dict(
                            reactants=["A()"],
                            products=["B()"],
                            coefficient=0.8,
                            propensity=8.0,
                        )
                    ]
                ],
                rhs={"A()": -8.0, "B()": 8.0},
                trajectory=dict(rate=0.8, initial=10.0),
            ),
            expectation_after=(
                "the coefficient of the changed rate parameter, the rebuilt "
                "network and the closed-form decay of the changed rate"
            ),
        ),
        dict(
            id="cache-rate-dependency",
            family="cache-invalidation",
            bngl=_model_source(
                parameters="  k 0.4\n  k2 2*k",
                molecule_types="  A()\n  B()",
                seeds="  A() 10\n  B() 0",
                observables="  Molecules A A()",
                rules="  A() -> B() k2",
            ),
            rate_law_kind="expression",
            states=[{"A()": 10.0, "B()": 0.0}],
            reactions=[
                [
                    dict(
                        reactants=["A()"],
                        products=["B()"],
                        coefficient=0.8,
                        propensity=8.0,
                    )
                ]
            ],
            rhs=[{"A()": -8.0, "B()": 8.0}],
            expectation="the coefficient of the parameter defined as 2*k",
            mutation=dict(parameter="k", value=0.6),
            mutated=dict(
                reactions=[
                    [
                        dict(
                            reactants=["A()"],
                            products=["B()"],
                            coefficient=1.2,
                            propensity=12.0,
                        )
                    ]
                ],
                rhs={"A()": -12.0, "B()": 12.0},
                trajectory=dict(rate=1.2, initial=10.0),
            ),
            expectation_after=(
                "the coefficient of the dependent parameter after its "
                "dependency changed, the rebuilt network and the closed-form "
                "decay of the changed rate"
            ),
        ),
    ]


def _boundary_cases():
    """Cases whose compiled declaration is outside the declared slice."""
    return [
        dict(
            id="boundary-compartment",
            construct="compartment",
            bngl=_model_source(
                parameters="  k 0.4",
                molecule_types="  A()",
                seeds="  A() 10",
                extra="begin compartments\n  cell 1 1\nend compartments",
                rules="  @cell:A() -> 0 k",
            ),
        ),
        dict(
            id="boundary-filter",
            construct="filter",
            bngl=_model_source(
                parameters="  k 0.4",
                molecule_types="  A()\n  B()",
                seeds="  A() 10\n  B() 0",
                rules="  A() + B() -> A() k include_reactants(1,A)",
            ),
        ),
        dict(
            id="boundary-modifier",
            construct="modifier",
            bngl=_model_source(
                parameters="  k 0.4",
                molecule_types="  A()",
                seeds="  A() 10",
                rules="  A() -> 0 k MatchOnce",
            ),
        ),
        dict(
            id="boundary-energy",
            construct="energy",
            bngl=_model_source(
                parameters="  k 0.4\n  Gf 1",
                molecule_types="  A()",
                seeds="  A() 10",
                extra="begin energy patterns\n  A() Gf\nend energy patterns",
                rules="  A() -> 0 k",
            ),
        ),
        dict(
            id="boundary-population-map",
            construct="population map",
            bngl=_model_source(
                parameters="  k 0.4\n  k_gather 0.2",
                molecule_types="  A()\n  A_pop()",
                seeds="  A() 10",
                extra=(
                    "begin population maps\n  A() -> A_pop() k_gather\n"
                    "end population maps"
                ),
                rules="  A() -> 0 k",
            ),
        ),
    ]


def cases():
    """Return the generated, parameterized rate-law cases."""
    return [
        *_elementary_cases(),
        *_saturation_cases(),
        *_hill_cases(),
        *_michaelis_menten_cases(),
        *_tfun_cases(),
        *_local_scope_cases(),
        *_multiplicity_cases(),
        *_special_multiplicity_cases(),
        *_dependency_cases(),
        *_cache_cases(),
    ]


def boundary_cases():
    """Return the generated cases that sit outside the declared slice."""
    return _boundary_cases()


def check_ids():
    """Stable expected check identities for the rate-law qualification."""
    ids = []
    for case in cases():
        ids += [
            f"rate-law-contract:{case['id']}:{aspect}"
            for aspect in ("coefficient", "rhs", "propensity")
        ]
        if case.get("mutation") is not None:
            ids.append(f"rate-law-contract:{case['id']}:cache-invalidation")
    ids += [f"rate-law-contract:{case['id']}:slice" for case in boundary_cases()]
    return ids


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(case_id, aspect, status, detail, artifact, first_difference=None, **extra):
    row = {
        "id": f"rate-law-contract:{case_id}:{aspect}",
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
    row.update(extra)
    return row


def _close(observed, expected):
    if expected is None or observed is None:
        return observed == expected
    return abs(float(observed) - float(expected)) <= TOLERANCE * max(
        1.0, abs(float(expected))
    )


def _difference(field, expected, observed):
    return dict(field=field, expected=expected, observed=observed)


def _compiled_rate_kind(snapshot, rule_index=0):
    rules = snapshot.get("rules") or []
    if len(rules) <= rule_index:
        raise UnsupportedSlice("the compiled model declares no rule to inspect")
    rate = rules[rule_index].get("forward", {}).get("rate")
    if not rate:
        raise UnsupportedSlice("the compiled rule direction has no rate law")
    return int(rate["kind"])


def _slice_guard(snapshot, case):
    """Reject a case whose compiled declaration left the declared slice."""
    rules = snapshot.get("rules") or []
    if not rules:
        raise UnsupportedSlice("the compiled model declares no reaction rule")
    if snapshot.get("compartments"):
        raise UnsupportedSlice("the model declares a compartment")
    if snapshot.get("population_maps"):
        raise UnsupportedSlice("the model declares a population map")
    if snapshot.get("energy_patterns"):
        raise UnsupportedSlice("the model declares an energy pattern")
    for rule in rules:
        for modifier in rule.get("modifiers") or []:
            kind = str(modifier.get("kind"))
            if kind in ("include_reactants", "exclude_reactants"):
                raise UnsupportedSlice("the rule declares a filter")
            if kind in ("include_products", "exclude_products"):
                raise UnsupportedSlice("the rule declares a filter")
            raise UnsupportedSlice("the rule declares a modifier: " + kind)
        for direction in (rule.get("forward"), rule.get("reverse")):
            if not direction:
                continue
            if direction.get("filters"):
                raise UnsupportedSlice("the rule declares a filter")
            for pattern in direction.get("reactants") or []:
                if pattern.get("compartment") or pattern.get("compartment_prefix"):
                    raise UnsupportedSlice(
                        "the rule declares a compartment-scoped pattern"
                    )
    kind = _compiled_rate_kind(snapshot)
    expected = RATE_LAW_KINDS[case["rate_law_kind"]]
    if kind != expected:
        raise UnsupportedSlice(
            "the compiled rate-law kind is "
            + str(kind)
            + ", not the declared "
            + case["rate_law_kind"]
        )


def _reaction_view(model, network, coefficients, propensities):
    """Describe the compiled reactions with their coefficients and propensities."""
    from bionetgen import _bionetgen_cpp as cpp

    flattened = cpp.jax_ode_flatten(model._model, network)
    names = list(network.species_names)
    reactant_offsets = list(flattened["reactant_offsets"])
    reactant_species = list(flattened["reactant_species"])
    product_offsets = list(flattened["product_offsets"])
    product_species = list(flattened["product_species"])
    reactions = []
    for index, coefficient in enumerate(coefficients):
        reactants = [
            names[reactant_species[position]]
            for position in range(reactant_offsets[index], reactant_offsets[index + 1])
        ]
        products = [
            names[product_species[position]]
            for position in range(product_offsets[index], product_offsets[index + 1])
        ]
        reactions.append(
            dict(
                reactants=reactants,
                products=products,
                coefficient=float(coefficient),
                propensity=float(propensities[index]),
            )
        )
    return reactions


def _match_reaction(expected, observed):
    """Find the observed reaction with the expected reactant/product signature."""
    matches = [
        item
        for item in observed
        if sorted(item["reactants"]) == sorted(expected["reactants"])
        and sorted(item["products"]) == sorted(expected["products"])
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _compare_reactions(expected, observed, field):
    for item in expected:
        match = _match_reaction(item, observed)
        if match is None:
            return _difference(
                field + ".reaction",
                dict(reactants=item["reactants"], products=item["products"]),
                [
                    dict(reactants=entry["reactants"], products=entry["products"])
                    for entry in observed
                ],
            )
        if not _close(match[field], item[field]):
            return _difference(
                field + "." + "+".join(item["reactants"] or ["source"]),
                item[field],
                match[field],
            )
    return None


def _compare_rhs(expected, observed_by_name):
    for name, value in expected.items():
        if name not in observed_by_name:
            return _difference("rhs.species", name, sorted(observed_by_name))
        if not _close(observed_by_name[name], value):
            return _difference("rhs." + name, value, observed_by_name[name])
    return None


def _trajectory_difference(observed, expected):
    times = observed["time"]
    values = observed["A"]
    for index, time in enumerate(times):
        reference = expected["initial"] * math.exp(-expected["rate"] * float(time))
        value = float(values[index])
        if abs(value - reference) > TRAJECTORY_TOLERANCE * max(1.0, abs(reference)):
            return _difference(
                "trajectory.A",
                reference,
                value,
            )
    return None


def _evaluate(model, network, state, time):
    from bionetgen import _bionetgen_cpp as cpp

    coefficients = [
        float(value)
        for value in cpp._validation_ode_rate_coefficients(
            model._model, network, time, state
        )
    ]
    propensities = [
        float(value)
        for value in cpp._validation_ssa_propensities(
            model._model, network, time, state
        )
    ]
    derivative = [
        float(value)
        for value in cpp._validation_ode_rhs(model._model, network, time, state)
    ]
    return coefficients, propensities, derivative


def _state_vector(network, state):
    names = list(network.species_names)
    missing = sorted(set(state) - set(names))
    if missing:
        raise UnsupportedSlice(
            "the generated network does not carry the species: " + ", ".join(missing)
        )
    return [float(state.get(name, 0.0)) for name in names]


def _run_case(case, directory: Path):
    """Evaluate one supported case and return its rows."""
    import bionetgen
    from bionetgen.model import _cpp

    artifact = directory / (case["id"] + ".bngl")
    artifact.write_text(case["bngl"], encoding="utf-8")
    model = bionetgen.BioNetGenModel(_cpp.parse_string(case["bngl"]))
    snapshot = _cpp._compiled_snapshot(model._model)
    _slice_guard(snapshot, case)
    network = model.generate_network()
    names = list(network.species_names)

    time = float(case.get("time", 0.0))
    rows = []
    coefficient_difference = None
    rhs_difference = None
    propensity_difference = None
    for index, state in enumerate(case["states"]):
        vector = _state_vector(network, state)
        coefficients, propensities, derivative = _evaluate(model, network, vector, time)
        observed = _reaction_view(model, network, coefficients, propensities)
        expected = case["reactions"][index]
        if coefficient_difference is None:
            coefficient_difference = _compare_reactions(
                expected, observed, "coefficient"
            )
        if propensity_difference is None:
            propensity_difference = _compare_reactions(expected, observed, "propensity")
        if rhs_difference is None:
            rhs_difference = _compare_rhs(
                case["rhs"][index], dict(zip(names, derivative))
            )

    for aspect, difference in (
        ("coefficient", coefficient_difference),
        ("rhs", rhs_difference),
        ("propensity", propensity_difference),
    ):
        rows.append(
            _row(
                case["id"],
                aspect,
                "FAIL" if difference else "PASS",
                (
                    (
                        f"the compiled {aspect} agrees with the closed-form "
                        f"expectation for the {case['family']} slice "
                        f"(supported slice: {SUPPORTED_SLICE})"
                    )
                    if not difference
                    else f"{aspect} differs: {difference}"
                ),
                artifact,
                difference,
                expectation=case["expectation"],
                convention=CONVENTIONS.get(FAMILY_CONVENTION.get(case["family"])),
            )
        )

    if case.get("mutation") is not None:
        rows.append(_run_cache_case(case, model, network, artifact, directory))
    return rows


def _run_cache_case(case, model, network, artifact, directory):
    """Change a rate (or a rate's dependency) and check the caches follow."""
    import bionetgen

    mutation = case["mutation"]
    names = list(network.species_names)
    model.set_parameter(mutation["parameter"], float(mutation["value"]))
    # The model discards its cached network on a parameter change; the
    # regenerated network must carry the changed rate law.
    rebuilt = model.generate_network()
    after_state = _state_vector(rebuilt, case["states"][0])
    coefficients, propensities, derivative = _evaluate(
        model, rebuilt, after_state, float(case.get("time", 0.0))
    )
    observed = _reaction_view(model, rebuilt, coefficients, propensities)
    difference = _compare_reactions(
        case["mutated"]["reactions"][0], observed, "coefficient"
    )
    if difference is None:
        difference = _compare_reactions(
            case["mutated"]["reactions"][0], observed, "propensity"
        )
    if difference is None:
        difference = _compare_rhs(case["mutated"]["rhs"], dict(zip(names, derivative)))
    if difference is None and case["mutated"].get("trajectory"):
        result = model.simulate(
            method="ode",
            t_end=TRAJECTORY_END,
            n_steps=TRAJECTORY_STEPS,
            rtol=1e-10,
            atol=1e-12,
        )
        difference = _trajectory_difference(
            dict(time=result.time, A=result.observables["A"]),
            case["mutated"]["trajectory"],
        )
    return _row(
        case["id"],
        "cache-invalidation",
        "FAIL" if difference else "PASS",
        (
            (
                "the changed rate and every value derived from it are recomputed: "
                f"{case['expectation_after']}"
            )
            if not difference
            else f"cache invalidation differs: {difference}"
        ),
        artifact,
        difference,
        expectation=case["expectation_after"],
        convention=CONVENTIONS["cache"],
        mutation=dict(case["mutation"]),
    )


def _run_boundary_case(case, directory: Path):
    """Classify a case that is outside the declared slice."""
    import bionetgen
    from bionetgen.model import _cpp

    artifact = directory / (case["id"] + ".bngl")
    artifact.write_text(case["bngl"], encoding="utf-8")
    reason = None
    try:
        model = bionetgen.BioNetGenModel(_cpp.parse_string(case["bngl"]))
        snapshot = _cpp._compiled_snapshot(model._model)
    except Exception as exc:  # pragma: no cover - diagnostic only
        reason = f"{type(exc).__name__}: {exc}"
        snapshot = {}
    if reason is None:
        try:
            _slice_guard(snapshot, dict(rate_law_kind="expression"))
        except UnsupportedSlice as exc:
            reason = str(exc)
        else:
            reason = "the case was not classified as outside the slice"
    named = case["construct"].lower() in (reason or "").lower()
    difference = None
    if not named:
        difference = _difference(
            "slice.reason", "a reason naming " + case["construct"], reason
        )
    return _row(
        case["id"],
        "slice",
        "FAIL" if difference else "PASS",
        (
            (
                "the case is outside the declared slice and is reported as "
                f"unsupported with the reason: {reason}"
            )
            if not difference
            else f"the slice classification differs: {difference}"
        ),
        artifact,
        difference,
        unsupported_reason=reason,
        support_required=False,
    )


def run_worker(directory: Path):
    """Execute every generated case and return one row per named check."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in cases():
        try:
            rows.extend(_run_case(case, directory))
        except UnsupportedSlice as exc:
            for aspect in ("coefficient", "rhs", "propensity"):
                rows.append(
                    _row(
                        case["id"],
                        aspect,
                        "UNSUPPORTED",
                        f"the case is outside the qualified slice: {exc}",
                        directory / (case["id"] + ".bngl"),
                        {"field": "case", "detail": str(exc)},
                    )
                )
        except Exception as exc:  # pragma: no cover - diagnostic only
            for aspect in ("coefficient", "rhs", "propensity"):
                rows.append(
                    _row(
                        case["id"],
                        aspect,
                        "HARNESS_ERROR",
                        f"{type(exc).__name__}: {exc}",
                        directory / (case["id"] + ".bngl"),
                    )
                )
    for case in boundary_cases():
        try:
            rows.append(_run_boundary_case(case, directory))
        except Exception as exc:  # pragma: no cover - diagnostic only
            rows.append(
                _row(
                    case["id"],
                    "slice",
                    "HARNESS_ERROR",
                    f"{type(exc).__name__}: {exc}",
                    directory / (case["id"] + ".bngl"),
                )
            )
    return rows
