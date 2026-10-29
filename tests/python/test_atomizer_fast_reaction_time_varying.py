"""Fast reactions whose steady state moves during the run.

SBML Level 3 Version 1 Core Sec. 4.11 asks for a pseudo steady-state
approximation of the reactions marked ``fast``.  When an event or a rule
changes the fast reaction's rate constant, or an event changes its
stoichiometry, that steady state moves with them.  The official SBML Test
Suite covers these constructs in semantic 00987, 00988 (an event sets the rate
constant), 01398 (an event changes the stoichiometry) and 01568, 01570 (the
rate constant follows a rule).

Each model below is small enough to have a closed-form reduced solution, and
the references are those closed forms, derived from the source model here and
not from the Atomizer.  They were also checked against the unreduced source
ODEs with the fast rate multiplied by 1e4 to 1e8 (scipy Radau), which converge
to the same values: O(1/F) for the smooth models and O(F^-1/2) for the models
whose steady state switches branch.

The switching models give the species held at zero a slow source on purpose.
Without one, that species is exponentially small in F when the rate constant
changes sign, and a large but finite fast rate leaves the system on the
unstable branch for a time of order one after the sign change (a delayed
bifurcation).  The reduction takes the stable root of the pseudo steady state
at every instant, which is the algebraic definition SBML gives; a large-F
simulation is not a check of it in that case.

The tests marked as native execute the generated BNGL with the BNG3 engine;
the others check the lowered model with a small RK4 integrator of the lowered
SBML structure, so the reduction's mathematics is checked without the native
extension.
"""

from __future__ import annotations

import math
import re

import numpy as np
import pytest

from bionetgen.atomizer.modern import Atomizer
from bionetgen.atomizer.modern.parser import SBMLParser

HEADER = (
    '<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" '
    'level="3" version="1">'
)
TIME = (
    '<csymbol encoding="text" '
    'definitionURL="http://www.sbml.org/sbml/symbols/time">t</csymbol>'
)
TIMES = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]


def _math(body: str) -> str:
    return f'<math xmlns="http://www.w3.org/1998/Math/MathML">{body}</math>'


def _ci(name: str) -> str:
    return f"<ci>{name}</ci>"


def _cn(value: float) -> str:
    return f"<cn>{value}</cn>"


def _apply(operator: str, *arguments: str) -> str:
    return f"<apply><{operator}/>{''.join(arguments)}</apply>"


def _species(identifier: str, amount: float) -> str:
    return (
        f'<species id="{identifier}" compartment="C" initialAmount="{amount}" '
        'hasOnlySubstanceUnits="false" boundaryCondition="false" '
        'constant="false"/>'
    )


def _reference(species: str, stoichiometry: float = 1, identifier: str = "") -> str:
    if identifier:
        return (
            f'<speciesReference species="{species}" stoichiometry="{stoichiometry}" '
            f'constant="false" id="{identifier}"/>'
        )
    return (
        f'<speciesReference species="{species}" stoichiometry="{stoichiometry}" '
        'constant="true"/>'
    )


def _reaction(identifier, reactants, products, law, fast=False) -> str:
    reactant_xml = (
        f"<listOfReactants>{''.join(reactants)}</listOfReactants>" if reactants else ""
    )
    product_xml = (
        f"<listOfProducts>{''.join(products)}</listOfProducts>" if products else ""
    )
    return (
        f'<reaction id="{identifier}" reversible="false" '
        f'fast="{"true" if fast else "false"}">{reactant_xml}{product_xml}'
        f"<kineticLaw>{_math(law)}</kineticLaw></reaction>"
    )


def _time_event(identifier: str, at: float, assignments) -> str:
    body = "".join(
        f'<eventAssignment variable="{variable}">{_math(value)}</eventAssignment>'
        for variable, value in assignments
    )
    return (
        f'<event id="{identifier}" useValuesFromTriggerTime="true">'
        '<trigger initialValue="true" persistent="true">'
        f"{_math(_apply('geq', TIME, _cn(at)))}</trigger>"
        f"<listOfEventAssignments>{body}</listOfEventAssignments></event>"
    )


def _model(size, species, parameters, rules, reactions, events="") -> str:
    rule_xml = f"<listOfRules>{''.join(rules)}</listOfRules>" if rules else ""
    event_xml = f"<listOfEvents>{events}</listOfEvents>" if events else ""
    parameter_xml = "".join(
        f'<parameter id="{identifier}" value="{value}" '
        f'constant="{"true" if constant else "false"}"/>'
        for identifier, value, constant in parameters
    )
    return (
        HEADER + '<model id="fast_model" timeUnits="second">'
        f'<listOfCompartments><compartment id="C" size="{size}" constant="true"/>'
        "</listOfCompartments>"
        f"<listOfSpecies>{''.join(species)}</listOfSpecies>"
        f"<listOfParameters>{parameter_xml}</listOfParameters>{rule_xml}"
        f"<listOfReactions>{''.join(reactions)}</listOfReactions>{event_xml}"
        "</model></sbml>"
    )


def _rule_k(value: str) -> str:
    return f'<assignmentRule variable="k">{_math(value)}</assignmentRule>'


def sign_switching_rule() -> str:
    """``S1 -> S2`` fast at ``k*S1*S2*C`` with ``k = 1.2 - t``.

    The steady state holds S1 at zero while k > 0 and S2 at zero while k < 0;
    the slow reactions are ``S2 -> S3`` at ``0.3*S2*C`` and ``S3 -> S1`` at
    ``0.2*S3*C``.
    """

    return _model(
        1,
        [_species("S1", 1), _species("S2", 0.5), _species("S3", 0)],
        [("k", 1, False), ("k2", 0.3, True), ("k3", 0.2, True)],
        [_rule_k(_apply("minus", _cn(1.2), TIME))],
        [
            _reaction(
                "fast",
                [_reference("S1")],
                [_reference("S2")],
                _apply("times", _ci("k"), _ci("S1"), _ci("S2"), _ci("C")),
                fast=True,
            ),
            _reaction(
                "slow2",
                [_reference("S2")],
                [_reference("S3")],
                _apply("times", _ci("k2"), _ci("S2"), _ci("C")),
            ),
            _reaction(
                "slow3",
                [_reference("S3")],
                [_reference("S1")],
                _apply("times", _ci("k3"), _ci("S3"), _ci("C")),
            ),
        ],
    )


def event_sets_balance_constant() -> str:
    """``S1 <-> S2`` fast at ``(kf*S1 - kr*S2)*C`` in ``C = 2``; kf: 1 -> 4 at 1.75."""

    law = _apply(
        "times",
        _apply(
            "minus",
            _apply("times", _ci("kf"), _ci("S1")),
            _apply("times", _ci("kr"), _ci("S2")),
        ),
        _ci("C"),
    )
    return _model(
        2,
        [_species("S1", 1), _species("S2", 3), _species("S3", 0)],
        [("kf", 1, False), ("kr", 2, True), ("k2", 0.5, True)],
        [],
        [
            _reaction("fast", [_reference("S1")], [_reference("S2")], law, fast=True),
            _reaction(
                "slow",
                [_reference("S2")],
                [_reference("S3")],
                _apply("times", _ci("k2"), _ci("S2"), _ci("C")),
            ),
        ],
        _time_event("E1", 1.75, [("kf", _cn(4))]),
    )


def event_changes_stoichiometry() -> str:
    """``S1 -> sr S2`` fast at ``k*S1*C``; an event sets ``sr`` from 2 to 1 at 1.25."""

    return _model(
        1,
        [_species("S1", 1), _species("S2", 0), _species("S3", 0)],
        [("k", 1, True), ("k2", 0.4, True), ("k3", 0.3, True)],
        [],
        [
            _reaction(
                "fast",
                [_reference("S1")],
                [_reference("S2", 2, identifier="sr")],
                _apply("times", _ci("k"), _ci("S1"), _ci("C")),
                fast=True,
            ),
            _reaction(
                "slow2",
                [_reference("S2")],
                [_reference("S3")],
                _apply("times", _ci("k2"), _ci("S2"), _ci("C")),
            ),
            _reaction(
                "slow3",
                [_reference("S3")],
                [_reference("S1")],
                _apply("times", _ci("k3"), _ci("S3"), _ci("C")),
            ),
        ],
        _time_event("E1", 1.25, [("sr", _cn(1))]),
    )


def event_changes_balance_stoichiometry() -> str:
    """``S1 <-> sr S2`` fast at ``(2*S1 - S2)*C``; sr: 1 -> 3 at 1.75; ``S2 -> 0``."""

    law = _apply(
        "times",
        _apply(
            "minus",
            _apply("times", _ci("kf"), _ci("S1")),
            _apply("times", _ci("kr"), _ci("S2")),
        ),
        _ci("C"),
    )
    return _model(
        1,
        [_species("S1", 2), _species("S2", 1)],
        [("kf", 2, True), ("kr", 1, True), ("k2", 0.5, True)],
        [],
        [
            _reaction(
                "fast",
                [_reference("S1")],
                [_reference("S2", 1, identifier="sr")],
                law,
                fast=True,
            ),
            _reaction(
                "slow",
                [_reference("S2")],
                [],
                _apply("times", _ci("k2"), _ci("S2"), _ci("C")),
            ),
        ],
        _time_event("E1", 1.75, [("sr", _cn(3))]),
    )


def event_keeps_rate_constant_positive() -> str:
    """``S1 -> S2`` fast at ``k*S1``; an event sets k from 1 to 5 at 1.25."""

    return _model(
        1,
        [_species("S1", 1), _species("S2", 0), _species("S3", 0)],
        [("k", 1, False), ("k2", 0.5, True)],
        [],
        [
            _reaction(
                "fast",
                [_reference("S1")],
                [_reference("S2")],
                _apply("times", _ci("k"), _ci("S1")),
                fast=True,
            ),
            _reaction(
                "slow",
                [_reference("S2")],
                [_reference("S3")],
                _apply("times", _ci("k2"), _ci("S2")),
            ),
        ],
        _time_event("E1", 1.25, [("k", _cn(5))]),
    )


def event_turns_the_fast_reaction_off() -> str:
    """``S1 -> S2`` fast at ``k*S1``; an event sets k from 1 to 0 at 1.25.

    No slow reaction produces S1, so S1 is zero from the start and stays
    zero after the fast reaction stops.
    """

    return event_keeps_rate_constant_positive().replace(
        '<eventAssignment variable="k">'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>5</cn></math>',
        '<eventAssignment variable="k">'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0</cn></math>',
    )


def rate_constant_reads_another_species() -> str:
    """``S1 -> S2`` fast at ``k*S1*S2`` with ``k = S3 - 0.5`` and ``S3 = e^-t``.

    k changes sign at ``t = ln 2``; the slow reactions are ``0 -> S1`` at
    ``0.05``, ``S2 -> 0`` at ``0.4*S2`` and ``S3 -> 0`` at ``S3``.
    """

    return _model(
        1,
        [_species("S1", 1), _species("S2", 0.5), _species("S3", 1)],
        [("k", 0.5, False), ("k2", 0.4, True)],
        [_rule_k(_apply("minus", _ci("S3"), _cn(0.5)))],
        [
            _reaction(
                "fast",
                [_reference("S1")],
                [_reference("S2")],
                _apply("times", _ci("k"), _ci("S1"), _ci("S2")),
                fast=True,
            ),
            _reaction(
                "slow2", [_reference("S2")], [], _apply("times", _ci("k2"), _ci("S2"))
            ),
            _reaction("slow3", [_reference("S3")], [], _ci("S3")),
            _reaction("source", [], [_reference("S1")], _cn(0.05)),
        ],
    )


# --- closed-form references, in amounts ---------------------------------


def _expm(matrix: np.ndarray, time: float) -> np.ndarray:
    values, vectors = np.linalg.eig(matrix)
    return (vectors @ np.diag(np.exp(values * time)) @ np.linalg.inv(vectors)).real


def reference_sign_switching(time: float):
    # The pool S1 + S2 + S3 = 1.5 is conserved.  While k > 0, S1 = 0 and
    # dS3/dt = 0.3*(1.5 - S3) - 0.2*S3; once k < 0, S2 = 0 and S3 decays at 0.2.
    switch = 1.2
    if time < switch:
        s3 = 0.9 * (1 - math.exp(-0.5 * time))
        return {"S1": 0.0, "S2": 1.5 - s3, "S3": s3}
    s3 = 0.9 * (1 - math.exp(-0.5 * switch)) * math.exp(-0.2 * (time - switch))
    return {"S1": 1.5 - s3, "S2": 0.0, "S3": s3}


def reference_balance_event(time: float):
    # T = n1 + n2 = 4; kf*n1 = 2*n2, so n2 = kf*T/(2 + kf) and dT/dt = -0.5*n2.
    event = 1.75
    if time < event:
        pool = 4 * math.exp(-time / 6)
        return {"S1": 2 * pool / 3, "S2": pool / 3, "S3": 4 - pool}
    pool = 4 * math.exp(-event / 6) * math.exp(-(time - event) / 3)
    return {"S1": pool / 3, "S2": 2 * pool / 3, "S3": 4 - pool}


def reference_stoichiometry_event(time: float):
    # S1 is held at zero; every S1 produced becomes sr S2, so
    # dS2/dt = -0.4*S2 + 0.3*sr*S3 and dS3/dt = 0.4*S2 - 0.3*S3, S2(0) = 2.
    event = 1.25

    def system(sr):
        return np.array([[-0.4, 0.3 * sr], [0.4, -0.3]])

    start = np.array([2.0, 0.0])
    if time < event:
        state = _expm(system(2), time) @ start
    else:
        state = _expm(system(1), time - event) @ (_expm(system(2), event) @ start)
    return {"S1": 0.0, "S2": float(state[0]), "S3": float(state[1])}


def reference_balance_stoichiometry_event(time: float):
    # 2*S1 = S2 holds throughout; the pool sr*n1 + n2 = n1*(sr + 2) changes
    # at -0.5*n2 = -n1, and the amounts do not jump when sr changes.
    event = 1.75
    if time < event:
        n1 = math.exp(-time / 3)
    else:
        n1 = math.exp(-event / 3) * math.exp(-(time - event) / 5)
    return {"S1": n1, "S2": 2 * n1}


def reference_positive_event(time: float):
    s2 = math.exp(-0.5 * time)
    return {"S1": 0.0, "S2": s2, "S3": 1 - s2}


def reference_reads_another_species(time: float):
    # T = S1 + S2 starts at 1.5.  While k > 0 (t < ln 2) S2 carries it and
    # dT/dt = 0.05 - 0.4*T; once k < 0, S1 carries it and dT/dt = 0.05.
    switch = math.log(2)
    s3 = math.exp(-time)
    if time < switch:
        return {
            "S1": 0.0,
            "S2": 0.125 + 1.375 * math.exp(-0.4 * time),
            "S3": s3,
        }
    pool = 0.125 + 1.375 * math.exp(-0.4 * switch)
    return {"S1": pool + 0.05 * (time - switch), "S2": 0.0, "S3": s3}


CASES = {
    "sign_switching_rule": (sign_switching_rule, reference_sign_switching, 1),
    "event_sets_balance_constant": (
        event_sets_balance_constant,
        reference_balance_event,
        2,
    ),
    "event_changes_stoichiometry": (
        event_changes_stoichiometry,
        reference_stoichiometry_event,
        1,
    ),
    "event_changes_balance_stoichiometry": (
        event_changes_balance_stoichiometry,
        reference_balance_stoichiometry_event,
        1,
    ),
    "event_keeps_rate_constant_positive": (
        event_keeps_rate_constant_positive,
        reference_positive_event,
        1,
    ),
    "event_turns_the_fast_reaction_off": (
        event_turns_the_fast_reaction_off,
        reference_positive_event,
        1,
    ),
    "rate_constant_reads_another_species": (
        rate_constant_reads_another_species,
        reference_reads_another_species,
        1,
    ),
}


# --- a small integrator of the lowered SBML structure --------------------

_CALLS = {
    "_if": lambda condition, yes, no: yes if condition else no,
    "gt": lambda left, right: left > right,
    "lt": lambda left, right: left < right,
    "geq": lambda left, right: left >= right,
    "leq": lambda left, right: left <= right,
}


def _compile(text: str):
    source = re.sub(r"\bif\s*\(", "_if(", str(text)).replace("^", "**")
    return compile(source, "<lowered>", "eval")


def _lowered_amounts(model, times, breakpoints=()):
    """Integrate the lowered model (RK4, step 1e-3) and return species amounts."""

    assigned = [
        (rule.variable, _compile(rule.math))
        for rule in model.rules
        if rule.type == "assignment"
    ]
    rated = [
        (rule.variable, _compile(rule.math))
        for rule in model.rules
        if rule.type == "rate"
    ]
    assigned_names = {name for name, _ in assigned}
    volume = {name: float(c.size) for name, c in model.compartments.items()}
    state = [
        name
        for name, species in model.species.items()
        if name not in assigned_names and not species.constant
    ]
    state += [name for name, _ in rated if name in model.parameters]
    parameters = {name: float(p.value) for name, p in model.parameters.items()}
    laws = []
    for reaction in model.reactions.values():
        changes = {}
        for reference in reaction.reactants:
            changes[reference.species] = changes.get(reference.species, 0.0) - float(
                reference.stoichiometry
            )
        for reference in reaction.products:
            changes[reference.species] = changes.get(reference.species, 0.0) + float(
                reference.stoichiometry
            )
        local = {
            str(parameter.id): float(parameter.value)
            for parameter in reaction.kinetic_law.local_parameters
        }
        laws.append((_compile(reaction.kinetic_law.math), changes, local))

    def species_volume(name):
        return volume[model.species[name].compartment]

    def namespace(time, values):
        scope = dict(_CALLS)
        scope.update(volume)
        scope.update(parameters)
        scope["time"] = time
        for name, value in zip(state, values):
            if name in model.species:
                value = value / species_volume(name)
            scope[name] = value
        for _ in range(len(assigned) + 1):
            for name, code in assigned:
                scope[name] = eval(code, {"__builtins__": {}}, scope)
        return scope

    def derivative(time, values):
        scope = namespace(time, values)
        index = {name: position for position, name in enumerate(state)}
        result = np.zeros(len(values))
        for code, changes, local in laws:
            rate = eval(code, {"__builtins__": {}}, {**scope, **local})
            for name, change in changes.items():
                if name in index:
                    result[index[name]] += change * rate
        for name, code in rated:
            rate = eval(code, {"__builtins__": {}}, scope)
            if name in model.species:
                rate *= species_volume(name)
            result[index[name]] = rate
        return result

    events = []
    for event in model.events:
        match = re.fullmatch(r"\s*geq\(time,\s*([-+0-9.eE]+)\)\s*", str(event.trigger))
        assert match, event.trigger
        events.append((float(match.group(1)), event))

    values = []
    for name in state:
        if name in model.species:
            species = model.species[name]
            values.append(
                float(species.initial_amount)
                if species.initial_amount_set
                else float(species.initial_concentration) * species_volume(name)
            )
        else:
            values.append(parameters[name])
    values = np.array(values)
    stops = sorted({*times, *(at for at, _ in events), *breakpoints})
    now = 0.0
    samples = {}
    for stop in stops:
        while now < stop - 1e-15:
            step = min(1e-3, stop - now)
            k1 = derivative(now, values)
            k2 = derivative(now + step / 2, values + step / 2 * k1)
            k3 = derivative(now + step / 2, values + step / 2 * k2)
            k4 = derivative(now + step, values + step * k3)
            values = values + step / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
            now += step
        now = stop
        for at, event in events:
            if abs(at - stop) < 1e-12:
                scope = namespace(now, values)
                updates = [
                    (assignment.variable, eval(_compile(assignment.math), {}, scope))
                    for assignment in event.assignments
                ]
                for name, value in updates:
                    parameters[name] = value
        if any(abs(stop - time) < 1e-12 for time in times):
            scope = namespace(now, values)
            samples[stop] = {
                name: scope[name] * species_volume(name) for name in model.species
            }
    return [samples[min(samples, key=lambda key: abs(key - time))] for time in times]


def _fast_warning(model):
    warnings = [
        warning
        for warning in model.import_warnings
        if warning.category == "fastReaction"
    ]
    assert len(warnings) == 1
    return warnings[0]


@pytest.mark.parametrize("name", sorted(CASES))
def test_time_varying_fast_reaction_reduces(name):
    builder, _reference_values, _volume = CASES[name]
    model = SBMLParser().parse(builder())
    warning = _fast_warning(model)
    assert warning.severity == "info", warning.message
    assert "is marked fast" in warning.message
    assert "reduces to one" in warning.message
    assert "fast" not in model.reactions


@pytest.mark.parametrize("name", sorted(CASES))
def test_lowered_model_reproduces_the_closed_form_steady_state(name):
    builder, reference, _volume = CASES[name]
    model = SBMLParser().parse(builder())
    breakpoints = {
        "sign_switching_rule": (1.2,),
        "rate_constant_reads_another_species": (math.log(2),),
    }.get(name, ())
    lowered = _lowered_amounts(model, TIMES, breakpoints)
    # The switch of this model depends on the state (S3 crossing 0.5), so a
    # fixed RK4 step can evaluate its last stage on either side of it; that
    # costs at most about h * 0.4 * T / 6 ~ 1e-4 in the pool.
    tolerance = 2e-4 if name == "rate_constant_reads_another_species" else 1e-9
    for time, row in zip(TIMES, lowered):
        for species, expected in reference(time).items():
            assert row[species] == pytest.approx(
                expected, rel=tolerance, abs=tolerance
            ), f"{name}: {species} at t={time}"


def test_sign_switching_follows_the_sign_of_the_rule():
    model = SBMLParser().parse(sign_switching_rule())
    rules = {rule.variable: rule.math for rule in model.rules}
    assert "S1" in rules and "S2" in rules
    assert "gt(" in rules["S1"] and "gt(" in rules["S2"]
    assert "the species the fast reaction holds at zero follows the sign" in (
        _fast_warning(model).message
    )
    # The slow reactions read the two species but no longer change them.
    assert [reference.species for reference in model.reactions["slow2"].products] == [
        "S3"
    ]
    assert not model.reactions["slow2"].reactants
    assert not model.reactions["slow3"].products


def test_local_parameter_of_the_fast_law_is_replaced_by_its_value():
    """A local parameter is scoped to its kinetic law, so its value replaces it."""

    law = _apply("times", _ci("k"), _ci("S1"), _ci("S2"), _ci("C"))
    local = _apply("times", _ci("kl"), _ci("k"), _ci("S1"), _ci("S2"), _ci("C"))
    xml = sign_switching_rule().replace(
        f"<kineticLaw>{_math(law)}</kineticLaw>",
        f"<kineticLaw>{_math(local)}<listOfLocalParameters>"
        '<localParameter id="kl" value="2"/></listOfLocalParameters></kineticLaw>',
    )
    assert 'localParameter id="kl"' in xml
    model = SBMLParser().parse(xml)
    assert _fast_warning(model).severity == "info"
    for rule in model.rules:
        assert not re.search(r"\bkl\b", rule.math), rule.math
    lowered = _lowered_amounts(model, TIMES, (1.2,))
    for time, row in zip(TIMES, lowered):
        for species, expected in reference_sign_switching(time).items():
            assert row[species] == pytest.approx(expected, rel=1e-9, abs=1e-9)


def test_constant_balance_replaces_a_slow_law_local_parameter():
    """The constant-coefficient balance copies the slow laws into rate rules.

    A local parameter of a slow law used to be copied by name, and the
    writer then dropped the rules because the name has no global scope.
    """

    law = _apply(
        "minus",
        _apply("times", _ci("kf"), _ci("S1")),
        _apply("times", _ci("kr"), _ci("S2")),
    )
    slow = (
        f"<kineticLaw>{_math(_apply('times', _ci('kl'), _ci('S2')))}"
        '<listOfLocalParameters><localParameter id="kl" value="0.5"/>'
        "</listOfLocalParameters></kineticLaw>"
    )
    xml = _model(
        1,
        [_species("S1", 1), _species("S2", 3), _species("S3", 0)],
        [("kf", 1, True), ("kr", 2, True)],
        [],
        [
            _reaction("fast", [_reference("S1")], [_reference("S2")], law, fast=True),
            _reaction("slow", [_reference("S2")], [_reference("S3")], _cn(0)).replace(
                f"<kineticLaw>{_math(_cn(0))}</kineticLaw>", slow
            ),
        ],
    )
    model = SBMLParser().parse(xml)
    assert _fast_warning(model).severity == "info"
    for rule in model.rules:
        assert not re.search(r"\bkl\b", rule.math), rule.math
    atomized = Atomizer(atomize=False, quiet_mode=True).atomize(xml)
    assert "[dropped]" not in atomized.bngl
    # kf*S1 = kr*S2 holds with T = S1 + S2 = 4 and dT/dt = -0.5*S2 = -T/6.
    lowered = _lowered_amounts(model, TIMES)
    for time, row in zip(TIMES, lowered):
        pool = 4 * math.exp(-time / 6)
        expected = {"S1": 2 * pool / 3, "S2": pool / 3, "S3": 4 - pool}
        for species, value in expected.items():
            assert row[species] == pytest.approx(value, rel=1e-9, abs=1e-9)


def test_event_changed_stoichiometry_keeps_the_amounts_continuous():
    model = SBMLParser().parse(event_changes_balance_stoichiometry())
    # The stoichiometry is a parameter that the event assigns; the reactant
    # keeps its amount as the state and the product follows the balance.
    assert not model.parameters["sr"].constant
    rules = {rule.variable: rule for rule in model.rules}
    assert rules["S1"].type == "rate"
    assert rules["S2"].type == "assignment"
    assert model.species["S1"].initial_amount == pytest.approx(1.0)
    assert [assignment.variable for assignment in model.events[0].assignments] == ["sr"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_generated_bngl_has_no_dropped_construct(name):
    builder, _reference_values, _volume = CASES[name]
    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=3, n_steps=6).atomize(
        builder()
    )
    assert atomized.success, atomized.error
    notes = atomized.bngl[atomized.bngl.find("SBML IMPORT NOTES") :]
    assert "[dropped]" not in notes
    assert "[approximated]" not in notes
    assert not re.search(r"^\s*fast:", atomized.bngl, re.M)


def test_event_that_sets_the_rate_constant_is_a_scheduled_parameter_change():
    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=3, n_steps=6).atomize(
        event_sets_balance_constant()
    )
    assert 'setParameter("kf", "4")' in atomized.bngl
    # The two species are the balance's closed-form functions of the pool.
    assert re.search(r"^\s*S1\(\) = .*__fast_pool_fast_amt", atomized.bngl, re.M)
    assert re.search(r"^\s*S2\(\) = .*kf.*__fast_pool_fast_amt", atomized.bngl, re.M)


def _refusal(xml: str) -> str:
    warning = _fast_warning(SBMLParser().parse(xml))
    assert warning.severity == "approximated", warning.message
    return warning.message


def test_single_species_rate_with_a_rule_constant_is_refused():
    """``k*S1`` with ``k = 1 - t`` has no steady state once ``k < 0``.

    Before this change the rule's declared value 1 was read as the constant,
    and the reduction silently held S1 at zero for the whole run.
    """

    xml = _model(
        1,
        [_species("S1", 1), _species("S2", 0)],
        [("k", 1, False)],
        [_rule_k(_apply("minus", _cn(1), TIME))],
        [
            _reaction(
                "fast",
                [_reference("S1")],
                [_reference("S2")],
                _apply("times", _ci("k"), _ci("S1")),
                fast=True,
            )
        ],
    )
    assert "not provably positive for the whole run" in _refusal(xml)


def test_turning_off_a_fast_reaction_whose_species_has_a_source_is_refused():
    """Once k = 0 the slow source would refill S1, so S1 is no longer held."""

    xml = event_turns_the_fast_reaction_off().replace(
        "</listOfReactions>",
        _reaction("source", [], [_reference("S1")], _cn(0.1)) + "</listOfReactions>",
    )
    assert "not provably positive for the whole run" in _refusal(xml)


def test_rate_constant_reading_a_converted_species_is_refused():
    xml = rate_constant_reads_another_species().replace(
        _rule_k(_apply("minus", _ci("S3"), _cn(0.5))),
        _rule_k(_apply("minus", _ci("S2"), _cn(0.5))),
    )
    assert "coefficients that do not depend on the species" in _refusal(xml)


def test_event_that_zeroes_a_switching_rate_constant_is_refused():
    xml = _model(
        1,
        [_species("S1", 1), _species("S2", 1)],
        [("k", 1, False)],
        [],
        [
            _reaction(
                "fast",
                [_reference("S1")],
                [_reference("S2")],
                _apply("times", _ci("k"), _ci("S1"), _ci("S2")),
                fast=True,
            )
        ],
        _time_event("E1", 1, [("k", _cn(-1))]) + _time_event("E2", 2, [("k", _cn(0))]),
    )
    assert "sets the fast reaction's rate constant to zero" in _refusal(xml)


def test_stoichiometry_event_with_a_time_varying_rate_constant_is_refused():
    """Both moving would need a pool assignment computed from the state."""

    xml = (
        event_changes_balance_stoichiometry()
        .replace(
            '<parameter id="kf" value="2" constant="true"/>',
            '<parameter id="kf" value="2" constant="false"/>',
        )
        .replace(
            "</listOfEvents>",
            _time_event("E2", 2.5, [("kf", _cn(3))]) + "</listOfEvents>",
        )
    )
    assert "needs an assignment computed from the state" in _refusal(xml)


def test_balance_with_the_positive_term_on_the_product_is_refused():
    law = _apply(
        "minus",
        _apply("times", _ci("kf"), _ci("S2")),
        _apply("times", _ci("kr"), _ci("S1")),
    )
    xml = _model(
        1,
        [_species("S1", 1), _species("S2", 1)],
        [("kf", 1, False), ("kr", 1, True)],
        [],
        [_reaction("fast", [_reference("S1")], [_reference("S2")], law, fast=True)],
        _time_event("E1", 1, [("kf", _cn(2))]),
    )
    assert "balance is not stable" in _refusal(xml)


# --- native execution ----------------------------------------------------


def _run(bngl: str, tmp_path):
    import bionetgen

    if "simulate(" not in bngl:
        grid = ",".join(repr(time) for time in TIMES)
        bngl += (
            "\nbegin actions\n  generate_network({overwrite=>1})\n"
            f'  simulate({{method=>"ode", t_start=>0, t_end=>{TIMES[-1]}, '
            f"sample_times=>[{grid}]}})\nend actions\n"
        )
    bngl = bngl.replace(
        "simulate({", "simulate({print_functions=>1, atol=>1e-12, rtol=>1e-10, "
    )
    source = tmp_path / "model.bngl"
    source.write_text(bngl, encoding="utf-8")
    bionetgen.load(str(source)).execute()
    output = (tmp_path / "model.gdat").read_text()
    header = [field.strip() for field in output.splitlines()[0].lstrip("#").split()]
    rows = {}
    for line in output.splitlines()[1:]:
        if not line.strip() or line.startswith("#"):
            continue
        fields = [float(field) for field in line.split()]
        # The last row written for a time is the value after any event there.
        rows[round(fields[0], 9)] = dict(zip(header, fields))
    return rows


def _amount(row, species: str, volume: float) -> float:
    if f"{species}_amt" in row:
        return row[f"{species}_amt"]
    for column in (species, f"{species}()"):
        if column in row:
            # A function carries the species' SBML value, a concentration.
            return row[column] * volume
    raise AssertionError(f"no column for {species}: {sorted(row)}")


@pytest.mark.parametrize("name", sorted(CASES))
def test_native_engine_reproduces_the_closed_form_steady_state(name, tmp_path):
    builder, reference, volume = CASES[name]
    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=3, n_steps=6).atomize(
        builder()
    )
    assert atomized.success, atomized.error
    rows = _run(atomized.bngl, tmp_path)
    for time in TIMES:
        row = rows[round(time, 9)]
        for species, expected in reference(time).items():
            assert _amount(row, species, volume) == pytest.approx(
                expected, rel=1e-6, abs=1e-7
            ), f"{name}: {species} at t={time}"


def test_generated_source_documents_are_valid_sbml():
    libsbml = pytest.importorskip("libsbml")
    for source in [builder() for builder, *_ in CASES.values()]:
        document = libsbml.readSBMLFromString(source)
        document.checkConsistency()
        errors = [
            document.getError(index).getMessage()
            for index in range(document.getNumErrors())
            if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
        ]
        assert not errors, errors
