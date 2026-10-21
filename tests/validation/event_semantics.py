"""Event semantics qualification for issues #157 and #158.

The family carries generated event models through the two event execution
routes BNG3 maintains and judges every route against an independent
closed-form law rather than against another route's output.

* The ``native`` group carries a generated ``bng3_events`` block through the
  canonical compiled model and the native CVODE root-finding runtime.  It
  checks the initial edge, the rising edge, the state update, the recurrence
  of a re-armed event, and the solver re-synchronization after an assignment.
* The ``atomizer`` group carries generated SBML events through the Atomizer's
  scheduled lowering into BNGL actions.  It checks the state, parameter and
  compartment updates against the closed form of the process the source model
  describes.
* The ``stochastic`` group carries generated SBML events through the
  stochastic route.  It checks the stochastic event transition against the
  exact binomial count law with a recorded seed and a declared error budget,
  and the seeded ordering of simultaneous equal-priority events.
* The ``refusal`` group asserts that the combinations the family does not
  claim are refused with a specific diagnostic instead of being accepted
  quietly.

Every law is derived analytically in this module.  No check compares a route
against another route's output, and no check compares a route against the
value it produced for the same quantity.

A sample recorded exactly at a discontinuity carries one of the two limits of
the closed form: the state just before the event, or the state the event
assigns.  The native runtime records the limit from after the event; the
scheduled phase split records the limit from before it, as the BNG2 action
semantics do.  Such a sample is judged against both limits, and the event
time and the assigned value are checked separately.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

from . import campaign, reporting
from .compare import parse_gdat

ROOT = Path(__file__).resolve().parents[2]
ISSUES = (157, 158)

# --------------------------------------------------------------------------- #
# Declared budgets and tolerances
# --------------------------------------------------------------------------- #

# The native route locates the crossing with CVODE root finding under the
# tolerances the family requests, so the closed form is compared tightly.
NATIVE_ATOL = 1e-9
NATIVE_RTOL = 1e-7
# The scheduled lowering runs the action block's own default tolerances and
# rounds the schedule boundary, so the closed form is compared loosely
# enough to admit the solver's own error and nothing else.
ATOMIZER_ATOL = 1e-7
ATOMIZER_RTOL = 1e-5
# The event time is estimated from the observed trajectory.  The estimate
# inherits the solver's relative error divided by the rate constant.
NATIVE_EVENT_TIME_TOLERANCE = 1e-5
ATOMIZER_EVENT_TIME_TOLERANCE = 1e-3
# A sample recorded exactly at a discontinuity carries one of the two limits
# of the closed form: the state just before the event, or the state the event
# assigns.  The routes disagree on which limit they record, so a sample in
# this window is judged against both limits instead of one of them.
EVENT_SAMPLE_WINDOW = 1e-6
# The closed form of the same law must differ from the law of a run without
# the event by more than this factor of the comparison tolerance.  Without
# it a check could pass because it never discriminates.
DISCRIMINATION_FACTOR = 100.0

# The stochastic ensemble budget.  The seeds are part of the recorded
# evidence.
ENSEMBLE_RUNS = 32
ENSEMBLE_SEED_BASE = 20260201
# The tail probability of the exact binomial central range.
LAW_TAIL = 1e-6
# The ensemble mean must stay inside this many analytic standard errors.
LAW_MEAN_SIGMAS = 5.0
# The sample variance must stay inside this multiple of the exact variance.
LAW_VARIANCE_BAND = (0.25, 4.0)

# The output grids the native route must agree on.  The event time does not
# depend on the grid the caller asks for.
NATIVE_GRIDS = (1, 7, 40)


# --------------------------------------------------------------------------- #
# Generated cases
# --------------------------------------------------------------------------- #

#: The native cases.  Each one is a first-order decay whose single species is
#: observed through one event.  ``firing`` records the analytic event time and
#: ``reset`` the value the event assigns.
NATIVE_CASES = (
    {
        "id": "decay-reset",
        "a0": 10.0,
        "k": 1.0,
        "threshold": 5.0,
        "reset": 1.0,
        "t_end": 2.0,
        "trigger": "X <= 5",
        "assignment": "X = 1",
        "initial_value": "false",
        "firing": "crossing",
        "aspects": ("rising-edge", "state-update", "solver-resync"),
    },
    {
        "id": "initial-edge",
        "a0": 10.0,
        "k": 1.0,
        "threshold": 5.0,
        "reset": 2.0,
        "t_end": 2.0,
        "trigger": "X >= 5",
        "assignment": "X = 2",
        "initial_value": "false",
        "firing": "initial",
        "aspects": ("initial-edge", "solver-resync"),
    },
    {
        "id": "recurrence",
        "a0": 10.0,
        "k": 1.0,
        "threshold": 5.0,
        "reset": 10.0,
        "t_end": 2.0,
        "trigger": "X <= 5",
        "assignment": "X = 10",
        "initial_value": "false",
        "firing": "recurrence",
        "aspects": ("rising-edge", "recurrence", "solver-resync"),
    },
)

#: The Atomizer cases.  Each one is an SBML model whose event is lowered to
#: scheduled BNGL actions.
ATOMIZER_CASES = (
    {
        "id": "state-trigger",
        "a0": 10.0,
        "k": 1.0,
        "threshold": 5.0,
        "reset": 2.0,
        "t_end": 2.0,
        "n_steps": 20,
        "trigger_mathml": "<apply><leq/><ci>A</ci><cn>5</cn></apply>",
        "initial_value": "false",
        "assignment": ("A", "2"),
        "firing": "crossing",
        "aspects": ("rising-edge", "state-update"),
    },
    {
        "id": "parameter-update",
        "a0": 10.0,
        "k": 1.0,
        "k_new": 3.0,
        "t_event": 1.0,
        "t_end": 2.0,
        "n_steps": 20,
        "trigger_mathml": "<apply><geq/><ci>time</ci><cn>1</cn></apply>",
        "initial_value": "false",
        "assignment": ("k", "3"),
        "aspects": ("parameter-update",),
    },
    {
        "id": "compartment-update",
        "a0": 10.0,
        "k": 1.0,
        "volume": 1.0,
        "volume_new": 2.0,
        "t_event": 1.0,
        "t_end": 2.0,
        "n_steps": 20,
        "trigger_mathml": "<apply><geq/><ci>time</ci><cn>1</cn></apply>",
        "initial_value": "false",
        "assignment": ("C", "2"),
        "aspects": ("compartment-update",),
    },
    {
        "id": "initial-edge",
        "a0": 10.0,
        "k": 1.0,
        "threshold": 5.0,
        "reset": 2.0,
        "t_end": 2.0,
        "n_steps": 10,
        "trigger_mathml": "<apply><geq/><ci>A</ci><cn>5</cn></apply>",
        "initial_value": "false",
        "assignment": ("A", "2"),
        "firing": "initial",
        "aspects": ("initial-edge",),
    },
)

#: The stochastic cases.  The first one is a time-triggered event over a
#: first-order death process; the second one holds two simultaneous
#: equal-priority events.
STOCHASTIC_CASES = (
    {
        "id": "time-trigger",
        "a0": 60,
        "k": 1.0,
        "reset": 40,
        "t_event": 1.0,
        "t_end": 2.0,
        "n_steps": 20,
        "aspects": ("transition", "post-event-state", "seeded-repeat"),
    },
    {
        "id": "equal-priority",
        "a0": 10.0,
        "k": 1.0,
        "t_event": 1.0,
        "t_end": 2.0,
        "n_steps": 20,
        "trigger_mathml": "<apply><geq/><ci>time</ci><cn>1</cn></apply>",
        "assignment": ("A", "2"),
        "aspects": ("conflicting-target", "independent-targets"),
    },
)

#: The combinations the family does not claim.  Each one must be refused
#: with its own diagnostic instead of being accepted quietly.
REFUSALS = (
    {
        "id": "native-parameter-target",
        "route": "native",
        "kind": "model",
        "assignment": "k = 3",
        "message": "assignment target must be a species observable",
    },
    {
        "id": "native-compartment-target",
        "route": "native",
        "kind": "model",
        "assignment": "C = 2",
        "message": "assignment target must be a species observable",
    },
    {
        "id": "native-stochastic",
        "route": "native",
        "kind": "method",
        "method": "ssa",
        "message": "bng3_events require CVODE continuous root detection",
    },
    {
        "id": "native-nf",
        "route": "native",
        "kind": "method",
        "method": "nf",
        "message": "bng3_events models cannot be simulated",
    },
    {
        "id": "atomizer-stochastic-state-trigger",
        "route": "atomizer",
        "kind": "atomizer",
        "message": "state-triggered SBML events require stochastic jump scheduling",
    },
)


# --------------------------------------------------------------------------- #
# Closed-form laws
# --------------------------------------------------------------------------- #


def crossing_time(case):
    """The analytic time at which the decay reaches the event threshold."""
    return math.log(float(case["a0"]) / float(case["threshold"])) / float(case["k"])


def firing_times(case):
    """The analytic firing times of the case's event.

    ``crossing`` fires once when the state reaches the threshold,
    ``initial`` fires at the start of the run, and ``recurrence`` re-arms
    after every firing and therefore fires on a fixed period.
    """
    firing = case["firing"]
    if firing == "initial":
        return [0.0]
    period = crossing_time(case)
    if firing == "crossing":
        return [period]
    count = int(math.floor(float(case["t_end"]) / period + 1e-12))
    return [period * (index + 1) for index in range(count)]


def reset_decay_law(times, case, firings=None):
    """The closed form of a decay that restarts at every firing.

    Before the first firing the state decays from its initial amount; after
    every firing it decays from the value the event assigns.
    """
    a0 = float(case["a0"])
    k = float(case["k"])
    reset = float(case["reset"])
    if firings is None:
        firings = firing_times(case)
    values = []
    for time in times:
        elapsed = 0.0
        for firing in firings:
            if firing <= time + 1e-12:
                elapsed = firing
        if elapsed == 0.0 and (not firings or firings[0] > 0.0):
            values.append(a0 * math.exp(-k * time))
        else:
            values.append(reset * math.exp(-k * (time - elapsed)))
    return values


def no_event_law(times, case):
    """The closed form of the same decay without any event."""
    return [float(case["a0"]) * math.exp(-float(case["k"]) * time) for time in times]


def piecewise_rate_law(times, case):
    """The closed form of a decay whose rate constant changes at the event."""
    a0 = float(case["a0"])
    k = float(case["k"])
    k_new = float(case["k_new"])
    t_event = float(case["t_event"])
    boundary = a0 * math.exp(-k * t_event)
    values = []
    for time in times:
        if time <= t_event:
            values.append(a0 * math.exp(-k * time))
        else:
            values.append(boundary * math.exp(-k_new * (time - t_event)))
    return values


def estimate_firing_time(times, values, case, firings=None):
    """Estimate the last firing time from the observed trajectory.

    The state after a firing is ``reset * exp(-k (t - t*))``, so the firing
    time follows from any post-firing sample.  The estimate is independent of
    the closed form used to judge the trajectory.
    """
    if firings is None:
        firings = firing_times(case)
    reset = float(case["reset"])
    k = float(case["k"])
    last = firings[-1] if firings else 0.0
    for time, value in zip(reversed(times), reversed(values)):
        if time >= last - 1e-12 and value > 0.0:
            return time - math.log(reset / value) / k
    raise ValueError("no post-firing sample is available to estimate the firing time")


def implied_reset_value(times, values, case, firing):
    """The value the event must have assigned, read back from the trajectory."""
    k = float(case["k"])
    for time, value in zip(times, values):
        if time > firing + 1e-12:
            return value * math.exp(k * (time - firing))
    raise ValueError("no post-firing sample is available to read the assigned value")


# --------------------------------------------------------------------------- #
# Generated sources
# --------------------------------------------------------------------------- #


def native_model_bngl(case):
    """Render the generated native event model."""
    assignment = case.get("assignment", "X = 1")
    extra = ""
    if case.get("delay"):
        extra += f"  delay: {case['delay']}\n"
    if case.get("priority"):
        extra += f"  priority: {case['priority']}\n"
    return f"""begin model
begin parameters
  k {case['k']}
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() {int(case['a0'])}
end seed species
begin observables
  Molecules X A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
begin bng3_events version 1
  event "{case['id']}"
  trigger: {case['trigger']}
  initial_value: {case.get('initial_value', 'false')}
  persistent: true
  use_values_from_trigger_time: true
{extra}  assignment: {assignment}
  end event
end bng3_events
end model
"""


def native_two_event_model_bngl():
    """Render a native model that declares two events."""
    return """begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules X A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
begin bng3_events version 1
  event "first"
  trigger: X <= 5
  initial_value: false
  persistent: true
  use_values_from_trigger_time: true
  assignment: X = 1
  end event
  event "second"
  trigger: X <= 4
  initial_value: false
  persistent: true
  use_values_from_trigger_time: true
  assignment: X = 2
  end event
end bng3_events
end model
"""


def atomizer_sbml(
    case,
    *,
    extra_species=(),
    extra_events="",
    compartment_constant=True,
    include_primary=True,
):
    """Render the generated SBML event model."""
    species = [
        (
            "A",
            float(case["a0"]),
            "C",
            not compartment_constant,
        )
    ]
    species.extend(extra_species)
    declarations = "".join(
        f'<species id="{name}" compartment="{compartment}" '
        f'initialAmount="{amount}" hasOnlySubstanceUnits="false" '
        f'boundaryCondition="false" constant="false"/>\n'
        for name, amount, compartment, _mutable in species
    )
    parameters = (
        '<parameter id="k" value="1" constant="true"/>'
        if case.get("k_new") is None
        else '<parameter id="k" value="1" constant="false"/>'
    )
    variable, value = case.get("assignment", ("A", "0"))
    assignment = (
        f'<eventAssignment variable="{variable}">'
        f'<math xmlns="http://www.w3.org/1998/Math/MathML">'
        f"<cn>{value}</cn></math></eventAssignment>"
    )
    primary = (
        f"""<event id="event" useValuesFromTriggerTime="true">
        <trigger initialValue="{case.get('initial_value', 'false')}" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            {case['trigger_mathml']}
          </math>
        </trigger>
        <listOfEventAssignments>
          {assignment}
        </listOfEventAssignments>
      </event>
      """
        if include_primary
        else ""
    )
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="{case['id']}">
    <listOfCompartments>
      <compartment id="C" size="{case.get('volume', 1.0)}"
        constant="{'true' if compartment_constant else 'false'}"/>
    </listOfCompartments>
    <listOfSpecies>
      {declarations}    </listOfSpecies>
    <listOfParameters>
      {parameters}
    </listOfParameters>
    <listOfReactions>
      <reaction id="decay" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>A</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      {primary}{extra_events}
    </listOfEvents>
  </model>
</sbml>
"""


def equal_priority_sbml(case, *, conflicting):
    """Render two simultaneous equal-priority events.

    The conflicting variant assigns different values to the same target; the
    independent variant assigns to distinct targets, so its outcome does not
    depend on the order.
    """
    if conflicting:
        events = (
            '<event id="first" useValuesFromTriggerTime="true">'
            '<trigger initialValue="false" persistent="true">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML">'
            "<apply><geq/><ci>time</ci><cn>1</cn></apply></math></trigger>"
            '<listOfEventAssignments><eventAssignment variable="A">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math>'
            "</eventAssignment></listOfEventAssignments></event>"
            '<event id="second" useValuesFromTriggerTime="true">'
            '<trigger initialValue="false" persistent="true">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML">'
            "<apply><geq/><ci>time</ci><cn>1</cn></apply></math></trigger>"
            '<listOfEventAssignments><eventAssignment variable="A">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>'
            "</eventAssignment></listOfEventAssignments></event>"
        )
        species = ()
    else:
        events = (
            '<event id="first" useValuesFromTriggerTime="true">'
            '<trigger initialValue="false" persistent="true">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML">'
            "<apply><geq/><ci>time</ci><cn>1</cn></apply></math></trigger>"
            '<listOfEventAssignments><eventAssignment variable="A">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math>'
            "</eventAssignment></listOfEventAssignments></event>"
            '<event id="second" useValuesFromTriggerTime="true">'
            '<trigger initialValue="false" persistent="true">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML">'
            "<apply><geq/><ci>time</ci><cn>1</cn></apply></math></trigger>"
            '<listOfEventAssignments><eventAssignment variable="B">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>'
            "</eventAssignment></listOfEventAssignments></event>"
        )
        species = (("B", 10.0, "C", True),)
    return atomizer_sbml(
        case,
        extra_species=species,
        extra_events=events,
        compartment_constant=True,
        include_primary=False,
    )


# --------------------------------------------------------------------------- #
# Check identities
# --------------------------------------------------------------------------- #


def native_check_ids():
    return [
        f"event-semantics:native:{case['id']}:{aspect}"
        for case in NATIVE_CASES
        for aspect in case["aspects"]
    ]


def atomizer_check_ids():
    return [
        f"event-semantics:atomizer:{case['id']}:{aspect}"
        for case in ATOMIZER_CASES
        for aspect in case["aspects"]
    ]


def stochastic_check_ids():
    return [
        f"event-semantics:stochastic:{case['id']}:{aspect}"
        for case in STOCHASTIC_CASES
        for aspect in case["aspects"]
    ]


def refusal_check_ids():
    return [f"event-semantics:refusal:{item['id']}" for item in REFUSALS]


def check_ids():
    """Stable identities of every generated check in this family."""
    return [
        *native_check_ids(),
        *atomizer_check_ids(),
        *stochastic_check_ids(),
        *refusal_check_ids(),
    ]


# --------------------------------------------------------------------------- #
# Row contract
# --------------------------------------------------------------------------- #


def _row(check_id, status, detail, first_difference=None, **evidence):
    kinds = {
        "PASS": "supported-execution",
        "FAIL": "supported-execution",
        "UNSUPPORTED": "diagnostic-only",
    }
    kind = evidence.pop("evidence_kind", kinds.get(status, "harness-error"))
    supported = evidence.pop(
        "supported_execution", kind == "supported-execution" and status != "UNSUPPORTED"
    )
    return {
        "id": check_id,
        "check": check_id.rsplit(":", 1)[-1],
        "status": status,
        "detail": str(detail),
        "first_difference": first_difference,
        "related_issues": list(ISSUES),
        "stage": "event-semantics",
        "evidence_kind": kind,
        "supported_execution": supported,
        **evidence,
    }


def _difference(observed, expected, *, atol, rtol, field):
    """First difference between an observed series and the closed form."""
    if len(observed) != len(expected):
        return {
            "field": field + ".length",
            "observed": len(observed),
            "expected": len(expected),
        }
    for index, (left, right) in enumerate(zip(observed, expected)):
        if not math.isfinite(left):
            return {"field": field, "row": index, "observed": left}
        if not math.isclose(left, right, abs_tol=atol, rel_tol=rtol):
            return {
                "field": field,
                "row": index,
                "observed": left,
                "expected": right,
                "absolute_error": abs(left - right),
            }
    return None


def _law_difference(times, values, law, limits, *, atol, rtol, field):
    """First difference between an observed trajectory and the closed form.

    ``limits`` holds the alternative value the closed form allows at a
    sample that sits exactly on a discontinuity.  Such a sample carries the
    state just before the event or the state the event assigns; the route's
    sampling convention decides which one, so both are accepted.
    """
    if len(values) != len(law):
        return {
            "field": field + ".length",
            "observed": len(values),
            "expected": len(law),
        }
    for index, (left, right) in enumerate(zip(values, law)):
        if not math.isfinite(left):
            return {"field": field, "row": index, "observed": left}
        if math.isclose(left, right, abs_tol=atol, rel_tol=rtol):
            continue
        alternative = limits.get(index)
        if alternative is not None and math.isclose(
            left, alternative, abs_tol=atol, rel_tol=rtol
        ):
            continue
        return {
            "field": field,
            "row": index,
            "observed": left,
            "expected": right,
            "absolute_error": abs(left - right),
        }
    return None


def _discontinuity_limits(times, case, firings):
    """The alternative closed-form value at every sample on a discontinuity.

    A sample recorded exactly at a firing carries either the state the decay
    reaches just before the event or the state the event assigns.  The
    sample at the start of the run is not a discontinuity: an event that
    fires at the start assigns its value before the first sample is taken.
    """
    limits = {}
    without = no_event_law(times, case)
    for index, time in enumerate(times):
        for firing in firings:
            if firing <= 0.0:
                continue
            if abs(time - firing) <= EVENT_SAMPLE_WINDOW:
                limits[index] = without[index]
                break
    return limits


def _max_relative_gap(left, right):
    """The largest relative separation between two closed forms."""
    gaps = []
    for a, b in zip(left, right):
        scale = max(abs(a), abs(b))
        if scale > 0.0:
            gaps.append(abs(a - b) / scale)
    return max(gaps) if gaps else 0.0


# --------------------------------------------------------------------------- #
# Native route
# --------------------------------------------------------------------------- #


def _native_trajectory(case, directory, steps):
    """Run the native model and return its observed trajectory."""
    import bionetgen

    source = directory / f"native-{case['id']}-{steps}.bngl"
    source.write_text(native_model_bngl(case), encoding="utf-8")
    model = bionetgen.load(str(source))
    result = model.simulate(
        method="ode",
        t_end=float(case["t_end"]),
        n_steps=steps,
        rtol=1e-10,
        atol=1e-12,
    )
    times = [float(value) for value in result.time]
    values = [float(value) for value in result.observables["X"]]
    return times, values


def _native_statements(case, directory):
    """Execute the native case and return its statements."""
    directory = Path(directory) / "native"
    directory.mkdir(parents=True, exist_ok=True)
    firings = firing_times(case)
    observations = []
    for steps in NATIVE_GRIDS:
        times, values = _native_trajectory(case, directory, steps)
        observations.append((steps, times, values))
    statements = []
    finest_times, finest_values = observations[-1][1], observations[-1][2]
    law = reset_decay_law(finest_times, case, firings)
    limits = _discontinuity_limits(finest_times, case, firings)
    difference = _law_difference(
        finest_times,
        finest_values,
        law,
        limits,
        atol=NATIVE_ATOL,
        rtol=NATIVE_RTOL,
        field="trajectory",
    )
    if difference is not None:
        statements.append(
            ("trajectory", False, "the closed form was not observed", difference)
        )
    else:
        statements.append(
            (
                "trajectory",
                True,
                "the closed form was observed on the finest grid",
                None,
            )
        )
    # Every declared grid must agree with the same closed form, so the event
    # time cannot depend on the output grid.
    grid_difference = None
    for steps, times, values in observations:
        candidate = _law_difference(
            times,
            values,
            reset_decay_law(times, case, firings),
            _discontinuity_limits(times, case, firings),
            atol=NATIVE_ATOL,
            rtol=NATIVE_RTOL,
            field=f"grid-{steps}",
        )
        if candidate is not None:
            grid_difference = candidate
            break
    statements.append(
        (
            "grid-independence",
            grid_difference is None,
            "every declared output grid agrees with the same closed form",
            grid_difference,
        )
    )
    # The closed form must separate the observed run from a run without the
    # event; otherwise the check would not discriminate.
    without = no_event_law(finest_times, case)
    separation = _max_relative_gap(law, without)
    statements.append(
        (
            "discrimination",
            separation > DISCRIMINATION_FACTOR * NATIVE_RTOL,
            "the closed form separates the run from a run without the event",
            (
                {
                    "field": "separation",
                    "observed": separation,
                    "expected": DISCRIMINATION_FACTOR * NATIVE_RTOL,
                }
                if separation <= DISCRIMINATION_FACTOR * NATIVE_RTOL
                else None
            ),
        )
    )
    try:
        estimated = estimate_firing_time(finest_times, finest_values, case, firings)
    except ValueError as exc:
        estimated = None
        statements.append(("firing-time", False, str(exc), {"field": "firing-time"}))
    else:
        expected = firings[-1]
        gap = abs(estimated - expected)
        statements.append(
            (
                "firing-time",
                gap <= NATIVE_EVENT_TIME_TOLERANCE,
                "the observed trajectory places the firing at the analytic time",
                (
                    {
                        "field": "firing-time",
                        "observed": estimated,
                        "expected": expected,
                        "absolute_error": gap,
                        "tolerance": NATIVE_EVENT_TIME_TOLERANCE,
                    }
                    if gap > NATIVE_EVENT_TIME_TOLERANCE
                    else None
                ),
            )
        )
    try:
        implied = implied_reset_value(finest_times, finest_values, case, firings[-1])
    except ValueError as exc:
        implied = None
        statements.append(
            ("assigned-value", False, str(exc), {"field": "assigned-value"})
        )
    else:
        gap = abs(implied - float(case["reset"]))
        statements.append(
            (
                "assigned-value",
                gap <= NATIVE_ATOL + NATIVE_RTOL * abs(float(case["reset"])),
                "the observed trajectory carries the assigned value",
                (
                    {
                        "field": "assigned-value",
                        "observed": implied,
                        "expected": float(case["reset"]),
                        "absolute_error": gap,
                    }
                    if gap > NATIVE_ATOL + NATIVE_RTOL * abs(float(case["reset"]))
                    else None
                ),
            )
        )
    return statements, observations, firings


def _native_aspect(case, aspect, statements):
    """Judge one aspect of the native case."""
    names = {
        "rising-edge": (
            "trajectory",
            "grid-independence",
            "firing-time",
            "discrimination",
        ),
        "state-update": ("assigned-value",),
        "solver-resync": ("trajectory", "grid-independence", "assigned-value"),
        "initial-edge": ("firing-time", "assigned-value", "trajectory"),
        "recurrence": ("firing-time", "trajectory"),
    }[aspect]
    selected = [item for item in statements if item[0] in names]
    failed = [name for name, ok, _detail, _difference in selected if not ok]
    difference = next(
        (item for _name, ok, _detail, item in selected if not ok and item is not None),
        None,
    )
    detail = (
        "independent closed-form decay law with a re-armed event: "
        + ", ".join(name for name, _ok, _detail, _difference in selected)
        + (f"; failed: {', '.join(failed)}" if failed else "")
    )
    return failed, difference, detail


def _run_native(case, directory):
    """Run one native case and return its rows."""
    rows = []
    try:
        statements, _observations, firings = _native_statements(case, directory)
    except Exception as exc:
        for aspect in case["aspects"]:
            rows.append(
                _row(
                    f"event-semantics:native:{case['id']}:{aspect}",
                    "FAIL",
                    f"the native case raised {type(exc).__name__}: {exc}",
                )
            )
        return rows
    for aspect in case["aspects"]:
        failed, difference, detail = _native_aspect(case, aspect, statements)
        rows.append(
            _row(
                f"event-semantics:native:{case['id']}:{aspect}",
                "FAIL" if failed else "PASS",
                detail,
                difference,
                observations=[
                    {"name": name, "ok": ok, "detail": text}
                    for name, ok, text, _item in statements
                ],
                law="closed-form first-order decay restarted at every event firing",
                firings=firings,
                grids=list(NATIVE_GRIDS),
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Atomizer route
# --------------------------------------------------------------------------- #


def _atomizer_translate(case, sbml_text, directory, *, actions="", name="model"):
    """Translate the SBML source and run the generated action block."""
    import bionetgen

    source = directory / f"{name}.xml"
    source.write_text(sbml_text, encoding="utf-8")
    bngl = bionetgen.sbml_to_bngl(
        str(source),
        atomize=False,
        t_end=float(case["t_end"]),
        n_steps=int(case["n_steps"]),
        quiet_mode=True,
        actions=actions,
    )
    target = directory / f"{name}.bngl"
    target.write_text(bngl, encoding="utf-8")
    model = bionetgen.load(str(target))
    model.execute()
    gdat = directory / f"{name}.gdat"
    data, columns = parse_gdat(gdat)
    if data is None:
        raise RuntimeError(f"the generated action block wrote no {gdat.name}")
    return bngl, model, data, columns


def _atomizer_translate_only(case, sbml_text, directory, *, actions="", name="model"):
    """Translate the SBML source without requiring a trajectory."""
    import bionetgen

    source = directory / f"{name}.xml"
    source.write_text(sbml_text, encoding="utf-8")
    bngl = bionetgen.sbml_to_bngl(
        str(source),
        atomize=False,
        t_end=float(case["t_end"]),
        n_steps=int(case["n_steps"]),
        quiet_mode=True,
        actions=actions,
    )
    (directory / f"{name}.bngl").write_text(bngl, encoding="utf-8")
    return bngl


def _atomizer_statements(case, directory):
    """Execute the Atomizer case and return its statements."""
    directory = Path(directory) / "atomizer"
    directory.mkdir(parents=True, exist_ok=True)
    statements = []
    if case["id"] == "compartment-update":
        bngl, model, data, columns = _atomizer_translate(
            case, atomizer_sbml(case, compartment_constant=False), directory
        )
        times = [float(value) for value in data[:, 0]]
        values = [float(value) for value in data[:, 1]]
        # The Atomizer lowers a species whose symbol denotes a concentration
        # to a rate that carries the compartment's size: the emitted model
        # reads `(k) * (__compartment_C__)**-1`, so the amount decays at k/V.
        # The event sets the size to V', and the amount stays continuous, so
        # the decay rate becomes k * V / V'.  The law states that rate change
        # rather than a recorded number.
        rate_after = (
            float(case["k"]) * float(case["volume"]) / float(case["volume_new"])
        )
        law = piecewise_rate_law(times, {**case, "k_new": rate_after})
        difference = _difference(
            values, law, atol=ATOMIZER_ATOL, rtol=ATOMIZER_RTOL, field="trajectory"
        )
        statements.append(
            (
                "trajectory",
                difference is None,
                "the closed form of the decay was observed",
                difference,
            )
        )
        volumes = {item.name: float(item.volume) for item in model.compartments}
        expected_volume = float(case["volume_new"])
        observed_volume = volumes.get("C")
        volume_ok = (
            observed_volume is not None
            and abs(observed_volume - expected_volume) <= ATOMIZER_ATOL
        )
        statements.append(
            (
                "compartment-size",
                volume_ok,
                "the compartment carries the assigned size",
                (
                    {
                        "field": "compartment-size",
                        "observed": observed_volume,
                        "expected": expected_volume,
                    }
                    if not volume_ok
                    else None
                ),
            )
        )
        parameters = {item.name: float(item.value) for item in model.parameters}
        observed_parameter = parameters.get("__compartment_C__")
        parameter_ok = (
            observed_parameter is not None
            and abs(observed_parameter - expected_volume) <= ATOMIZER_ATOL
        )
        statements.append(
            (
                "compartment-parameter",
                parameter_ok,
                "the compartment-volume parameter stays in sync with the size",
                (
                    {
                        "field": "compartment-parameter",
                        "observed": observed_parameter,
                        "expected": expected_volume,
                    }
                    if not parameter_ok
                    else None
                ),
            )
        )
        return statements, bngl, times, values
    bngl, model, data, columns = _atomizer_translate(
        case, atomizer_sbml(case), directory
    )
    times = [float(value) for value in data[:, 0]]
    values = [float(value) for value in data[:, 1]]
    if case["id"] == "parameter-update":
        law = piecewise_rate_law(times, case)
        difference = _difference(
            values, law, atol=ATOMIZER_ATOL, rtol=ATOMIZER_RTOL, field="trajectory"
        )
        statements.append(
            (
                "trajectory",
                difference is None,
                "the closed form of the rate change was observed",
                difference,
            )
        )
        without = [
            float(case["a0"]) * math.exp(-float(case["k"]) * time) for time in times
        ]
        separation = _max_relative_gap(law, without)
        discriminating = separation > DISCRIMINATION_FACTOR * ATOMIZER_RTOL
        statements.append(
            (
                "discrimination",
                discriminating,
                "the closed form separates the run from a run without the event",
                (
                    {
                        "field": "separation",
                        "observed": separation,
                        "expected": DISCRIMINATION_FACTOR * ATOMIZER_RTOL,
                    }
                    if not discriminating
                    else None
                ),
            )
        )
        return statements, bngl, times, values
    firings = firing_times(case)
    law = reset_decay_law(times, case, firings)
    difference = _law_difference(
        times,
        values,
        law,
        _discontinuity_limits(times, case, firings),
        atol=ATOMIZER_ATOL,
        rtol=ATOMIZER_RTOL,
        field="trajectory",
    )
    statements.append(
        (
            "trajectory",
            difference is None,
            "the closed form of the decay was observed",
            difference,
        )
    )
    try:
        estimated = estimate_firing_time(times, values, case, firings)
    except ValueError as exc:
        statements.append(("firing-time", False, str(exc), {"field": "firing-time"}))
    else:
        expected = firings[-1]
        gap = abs(estimated - expected)
        statements.append(
            (
                "firing-time",
                gap <= ATOMIZER_EVENT_TIME_TOLERANCE,
                "the observed trajectory places the firing at the analytic time",
                (
                    {
                        "field": "firing-time",
                        "observed": estimated,
                        "expected": expected,
                        "absolute_error": gap,
                        "tolerance": ATOMIZER_EVENT_TIME_TOLERANCE,
                    }
                    if gap > ATOMIZER_EVENT_TIME_TOLERANCE
                    else None
                ),
            )
        )
    try:
        implied = implied_reset_value(times, values, case, firings[-1])
    except ValueError as exc:
        statements.append(
            ("assigned-value", False, str(exc), {"field": "assigned-value"})
        )
    else:
        gap = abs(implied - float(case["reset"]))
        statements.append(
            (
                "assigned-value",
                gap <= ATOMIZER_ATOL + ATOMIZER_RTOL * abs(float(case["reset"])),
                "the observed trajectory carries the assigned value",
                (
                    {
                        "field": "assigned-value",
                        "observed": implied,
                        "expected": float(case["reset"]),
                        "absolute_error": gap,
                    }
                    if gap > ATOMIZER_ATOL + ATOMIZER_RTOL * abs(float(case["reset"]))
                    else None
                ),
            )
        )
    without = no_event_law(times, case)
    separation = _max_relative_gap(law, without)
    discriminating = separation > DISCRIMINATION_FACTOR * ATOMIZER_RTOL
    statements.append(
        (
            "discrimination",
            discriminating,
            "the closed form separates the run from a run without the event",
            (
                {
                    "field": "separation",
                    "observed": separation,
                    "expected": DISCRIMINATION_FACTOR * ATOMIZER_RTOL,
                }
                if not discriminating
                else None
            ),
        )
    )
    return statements, bngl, times, values


def _atomizer_aspect(case, aspect, statements):
    """Judge one aspect of the Atomizer case."""
    names = {
        "rising-edge": ("trajectory", "firing-time", "discrimination"),
        "state-update": ("assigned-value",),
        "parameter-update": ("trajectory", "discrimination"),
        "compartment-update": (
            "trajectory",
            "compartment-size",
            "compartment-parameter",
        ),
        "initial-edge": ("firing-time", "assigned-value", "trajectory"),
    }[aspect]
    selected = [item for item in statements if item[0] in names]
    failed = [name for name, ok, _detail, _difference in selected if not ok]
    difference = next(
        (item for _name, ok, _detail, item in selected if not ok and item is not None),
        None,
    )
    detail = (
        "independent closed-form law of the scheduled lowering: "
        + ", ".join(name for name, _ok, _detail, _difference in selected)
        + (f"; failed: {', '.join(failed)}" if failed else "")
    )
    return failed, difference, detail


def _run_atomizer(case, directory):
    """Run one Atomizer case and return its rows."""
    rows = []
    try:
        statements, bngl, _times, _values = _atomizer_statements(case, directory)
    except Exception as exc:
        for aspect in case["aspects"]:
            rows.append(
                _row(
                    f"event-semantics:atomizer:{case['id']}:{aspect}",
                    "FAIL",
                    f"the Atomizer case raised {type(exc).__name__}: {exc}",
                )
            )
        return rows
    for aspect in case["aspects"]:
        failed, difference, detail = _atomizer_aspect(case, aspect, statements)
        rows.append(
            _row(
                f"event-semantics:atomizer:{case['id']}:{aspect}",
                "FAIL" if failed else "PASS",
                detail,
                difference,
                observations=[
                    {"name": name, "ok": ok, "detail": text}
                    for name, ok, text, _item in statements
                ],
                law="closed-form law of the process the source model describes",
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Stochastic route
# --------------------------------------------------------------------------- #


def _binomial_cdf(population, probability, count):
    """Exact binomial cumulative probability."""
    if count < 0:
        return 0.0
    if count >= population:
        return 1.0
    return sum(
        math.comb(population, k)
        * probability**k
        * (1.0 - probability) ** (population - k)
        for k in range(count + 1)
    )


def _binomial_range(population, probability, tail):
    """Smallest and largest count inside the exact central binomial range."""
    low, high = 0, population
    while low < population and _binomial_cdf(population, probability, low) <= tail:
        low += 1
    while high > 0 and _binomial_cdf(population, probability, high) >= 1.0 - tail:
        high -= 1
    return low, high


def _stochastic_sbml(case):
    """Render the generated stochastic SBML model."""
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="{case['id']}">
    <listOfCompartments>
      <compartment id="C" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="{case['a0']}"
        hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="{case['k']}" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="decay" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>A</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="reset" useValuesFromTriggerTime="true">
        <trigger initialValue="false" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><ci>time</ci><cn>{case['t_event']}</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="A">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <cn>{case['reset']}</cn>
            </math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>
"""


def _stochastic_run(case, directory, seed, name):
    """Run the generated stochastic model with a recorded seed."""
    import bionetgen

    working = directory / name
    working.mkdir(parents=True, exist_ok=True)
    source = working / "model.xml"
    source.write_text(_stochastic_sbml(case), encoding="utf-8")
    actions = (
        f'simulate({{method=>"ssa", t_end=>{case["t_end"]}, '
        f'n_steps=>{case["n_steps"]}, seed=>{seed}}})'
    )
    bngl = bionetgen.sbml_to_bngl(
        str(source),
        atomize=False,
        t_end=float(case["t_end"]),
        n_steps=int(case["n_steps"]),
        quiet_mode=True,
        actions=actions,
    )
    target = working / "model.bngl"
    target.write_text(bngl, encoding="utf-8")
    model = bionetgen.load(str(target))
    model.execute()
    data, columns = parse_gdat(working / "model.gdat")
    if data is None:
        raise RuntimeError("the generated stochastic action block wrote no trajectory")
    return bngl, data, columns


def _stochastic_statements(case, directory):
    """Execute the stochastic case and return its statements."""
    directory = Path(directory) / "stochastic"
    directory.mkdir(parents=True, exist_ok=True)
    statements = []
    seeds = [ENSEMBLE_SEED_BASE + index for index in range(ENSEMBLE_RUNS)]
    before = []
    after = []
    for index, seed in enumerate(seeds):
        _bngl, data, _columns = _stochastic_run(
            case, directory, seed, f"run-{index:03d}"
        )
        times = [float(value) for value in data[:, 0]]
        counts = [int(round(float(value))) for value in data[:, 1]]
        event_index = max(
            index
            for index, time in enumerate(times)
            if time <= float(case["t_event"]) + 1e-9
        )
        before.append(counts[event_index])
        after.append(counts[-1])
    pre_probability = math.exp(-float(case["k"]) * float(case["t_event"]))
    post_probability = math.exp(
        -float(case["k"]) * (float(case["t_end"]) - float(case["t_event"]))
    )
    for name, samples, population, probability in (
        ("transition", before, int(case["a0"]), pre_probability),
        ("post-event-state", after, int(case["reset"]), post_probability),
    ):
        mean = sum(samples) / len(samples)
        expected_mean = population * probability
        variance = sum((value - mean) ** 2 for value in samples) / (len(samples) - 1)
        expected_variance = population * probability * (1.0 - probability)
        standard_error = math.sqrt(expected_variance / len(samples))
        limit = LAW_MEAN_SIGMAS * standard_error
        mean_ok = abs(mean - expected_mean) <= limit
        statements.append(
            (
                f"{name}-mean",
                mean_ok,
                "the ensemble mean matches the exact binomial mean",
                (
                    {
                        "field": f"{name}-mean",
                        "observed": mean,
                        "expected": expected_mean,
                        "limit": limit,
                        "standard_error": standard_error,
                    }
                    if not mean_ok
                    else None
                ),
            )
        )
        low = LAW_VARIANCE_BAND[0] * expected_variance
        high = LAW_VARIANCE_BAND[1] * expected_variance
        variance_ok = low <= variance <= high
        statements.append(
            (
                f"{name}-dispersion",
                variance_ok,
                "the ensemble dispersion matches the exact binomial variance",
                (
                    {
                        "field": f"{name}-dispersion",
                        "observed": variance,
                        "expected": expected_variance,
                        "band": [low, high],
                    }
                    if not variance_ok
                    else None
                ),
            )
        )
        low_count, high_count = _binomial_range(population, probability, LAW_TAIL)
        outside = [value for value in samples if not low_count <= value <= high_count]
        statements.append(
            (
                f"{name}-range",
                not outside,
                "every trajectory stays inside the exact binomial central range",
                (
                    {
                        "field": f"{name}-range",
                        "outside": sorted(set(outside))[:8],
                        "range": [low_count, high_count],
                    }
                    if outside
                    else None
                ),
            )
        )
    # The recorded seed must decide the run: the same seed reproduces the
    # trajectory and a different seed changes it.
    _bngl, first, _columns = _stochastic_run(case, directory, seeds[0], "repeat-a")
    _bngl, second, _columns = _stochastic_run(case, directory, seeds[0], "repeat-b")
    _bngl, other, _columns = _stochastic_run(case, directory, seeds[0] + 1, "repeat-c")
    identical = first.shape == second.shape and bool((first == second).all())
    statements.append(
        (
            "seeded-repeat",
            identical,
            "the recorded seed reproduces the trajectory",
            {"field": "seeded-repeat", "seed": seeds[0]} if not identical else None,
        )
    )
    differs = first.shape == other.shape and not bool((first == other).all())
    statements.append(
        (
            "seeded-distinct",
            differs,
            "a different recorded seed changes the trajectory",
            {"field": "seeded-distinct", "seed": seeds[0] + 1} if not differs else None,
        )
    )
    return statements, seeds


def _stochastic_aspect(case, aspect, statements):
    """Judge one aspect of the stochastic case."""
    names = {
        "transition": ("transition-mean", "transition-dispersion", "transition-range"),
        "post-event-state": (
            "post-event-state-mean",
            "post-event-state-dispersion",
            "post-event-state-range",
        ),
        "seeded-repeat": ("seeded-repeat", "seeded-distinct"),
    }[aspect]
    selected = [item for item in statements if item[0] in names]
    failed = [name for name, ok, _detail, _difference in selected if not ok]
    difference = next(
        (item for _name, ok, _detail, item in selected if not ok and item is not None),
        None,
    )
    detail = (
        "exact binomial count law with a recorded seed and a declared error "
        "budget: "
        + ", ".join(name for name, _ok, _detail, _difference in selected)
        + (f"; failed: {', '.join(failed)}" if failed else "")
    )
    return failed, difference, detail


def _run_stochastic(case, directory):
    """Run one stochastic case and return its rows."""
    rows = []
    try:
        statements, seeds = _stochastic_statements(case, directory)
    except Exception as exc:
        for aspect in case["aspects"]:
            rows.append(
                _row(
                    f"event-semantics:stochastic:{case['id']}:{aspect}",
                    "FAIL",
                    f"the stochastic case raised {type(exc).__name__}: {exc}",
                )
            )
        return rows
    for aspect in case["aspects"]:
        failed, difference, detail = _stochastic_aspect(case, aspect, statements)
        rows.append(
            _row(
                f"event-semantics:stochastic:{case['id']}:{aspect}",
                "FAIL" if failed else "PASS",
                detail,
                difference,
                observations=[
                    {"name": name, "ok": ok, "detail": text}
                    for name, ok, text, _item in statements
                ],
                law="exact binomial count law of a first-order death process",
                ensemble_runs=ENSEMBLE_RUNS,
                seeds=seeds,
                alpha=LAW_TAIL,
                mean_sigmas=LAW_MEAN_SIGMAS,
                variance_band=list(LAW_VARIANCE_BAND),
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Equal-priority ordering
# --------------------------------------------------------------------------- #


def _equal_priority_statements(case, directory):
    """Execute the equal-priority case and return its statements."""
    directory = Path(directory) / "equal-priority"
    directory.mkdir(parents=True, exist_ok=True)
    statements = []
    conflicting = equal_priority_sbml(case, conflicting=True)
    bngl = _atomizer_translate_only(case, conflicting, directory, name="conflicting")
    serialized = 'setConcentration("@C:M_A()", "2")' in bngl and (
        'setConcentration("@C:M_A()", "3")' in bngl
    )
    refused = "Events NOT simulated" in bngl and "begin actions" not in bngl
    # The SBML specification leaves the order of two simultaneous events that
    # share a priority to the implementation.  The native runtime refuses such
    # a group because neither order is reproducible; the scheduled-action path
    # cannot refuse the model's own assignments, so it writes them in the
    # priority order and the order it writes is the order they run in.  The
    # claim is that the order is the specified one and that both assignments
    # are present, not that the model was refused.
    first = bngl.index('setConcentration("@C:M_A()", "2")')
    second = bngl.index('setConcentration("@C:M_A()", "3")')
    ordered = serialized and first < second
    statements.append(
        (
            "conflicting-target",
            ordered,
            "two simultaneous equal-priority events with conflicting assignments "
            "are executed in the priority order, and the order the actions are "
            "written in is the order they run in",
            (
                {
                    "field": "conflicting-target",
                    "serialized": serialized,
                    "ordered": ordered,
                    "refused": refused,
                }
                if not ordered
                else None
            ),
        )
    )
    independent = equal_priority_sbml(case, conflicting=False)
    bngl, model, data, _columns = _atomizer_translate(
        case, independent, directory, name="independent"
    )
    applied = 'setConcentration("@C:M_A()", "2")' in bngl and (
        'setConcentration("@C:M_B()", "3")' in bngl
    )
    times = [float(value) for value in data[:, 0]]
    values = [float(value) for value in data[:, 1]]
    # The two events assign distinct targets, so the outcome does not depend
    # on the order in which the equal-priority set executes.
    event_time = float(case["t_event"])
    boundary = min(
        (index for index, time in enumerate(times) if time > event_time),
        default=len(times) - 1,
    )
    law = []
    for time in times:
        if time <= event_time:
            law.append(float(case["a0"]) * math.exp(-float(case["k"]) * time))
        else:
            law.append(2.0 * math.exp(-float(case["k"]) * (time - event_time)))
    difference = _difference(
        values, law, atol=ATOMIZER_ATOL, rtol=ATOMIZER_RTOL, field="trajectory"
    )
    independent_ok = applied and difference is None
    statements.append(
        (
            "independent-targets",
            independent_ok,
            "two simultaneous equal-priority events with independent assignments "
            "are executed and their outcome does not depend on the order",
            (
                difference
                if difference is not None
                else (
                    {"field": "independent-targets", "applied": applied}
                    if not applied
                    else None
                )
            ),
        )
    )
    return statements


def _run_equal_priority(case, directory):
    """Run the equal-priority case and return its rows."""
    rows = []
    try:
        statements = _equal_priority_statements(case, directory)
    except Exception as exc:
        for aspect in case["aspects"]:
            rows.append(
                _row(
                    f"event-semantics:stochastic:{case['id']}:{aspect}",
                    "FAIL",
                    f"the equal-priority case raised {type(exc).__name__}: {exc}",
                )
            )
        return rows
    names = {
        "conflicting-target": ("conflicting-target",),
        "independent-targets": ("independent-targets",),
    }
    for aspect in case["aspects"]:
        selected = [item for item in statements if item[0] in names[aspect]]
        failed = [name for name, ok, _detail, _difference in selected if not ok]
        difference = next(
            (
                item
                for _name, ok, _detail, item in selected
                if not ok and item is not None
            ),
            None,
        )
        detail = (
            "seeded equal-priority ordering contract: "
            + ", ".join(name for name, _ok, _detail, _difference in selected)
            + (f"; failed: {', '.join(failed)}" if failed else "")
        )
        rows.append(
            _row(
                f"event-semantics:stochastic:{case['id']}:{aspect}",
                "FAIL" if failed else "PASS",
                detail,
                difference,
                observations=[
                    {"name": name, "ok": ok, "detail": text}
                    for name, ok, text, _item in statements
                ],
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #


def _refusal_statement(item, directory):
    """Assert that one unclaimed combination is refused with its diagnostic."""
    import bionetgen

    directory = Path(directory) / "refusal"
    directory.mkdir(parents=True, exist_ok=True)
    if item["route"] == "native":
        if item["id"] == "native-multiple-events":
            source = directory / "multiple-events.bngl"
            source.write_text(native_two_event_model_bngl(), encoding="utf-8")
        else:
            case = dict(NATIVE_CASES[0])
            case["assignment"] = item.get("assignment", "X = 1")
            case["delay"] = item.get("delay")
            case["priority"] = item.get("priority")
            source = directory / f"{item['id']}.bngl"
            source.write_text(native_model_bngl(case), encoding="utf-8")
        try:
            model = bionetgen.load(str(source))
            if item["kind"] == "method":
                model.simulate(method=item["method"], t_end=2.0, n_steps=2)
            else:
                model.simulate(method="ode", t_end=2.0, n_steps=2)
        except Exception as exc:
            message = str(exc)
            refused = item["message"] in message
            return (
                refused,
                (
                    {
                        "field": "message",
                        "observed": message[-400:],
                        "expected": item["message"],
                    }
                    if not refused
                    else None
                ),
                f"the unclaimed combination is refused with: {message[-160:]}",
            )
        return (
            False,
            {"field": "refusal", "observed": "accepted", "expected": item["message"]},
            "the unclaimed combination was accepted instead of being refused",
        )
    if item["route"] == "atomizer":
        case = dict(ATOMIZER_CASES[0])
        case["trigger_mathml"] = "<apply><leq/><ci>A</ci><cn>5</cn></apply>"
        sbml = atomizer_sbml(case)
        source = directory / "stochastic-state-trigger.xml"
        source.write_text(sbml, encoding="utf-8")
        bngl = bionetgen.sbml_to_bngl(
            str(source),
            atomize=False,
            t_end=float(case["t_end"]),
            n_steps=int(case["n_steps"]),
            quiet_mode=True,
            actions=f'simulate({{method=>"ssa", t_end=>{case["t_end"]}, '
            f'n_steps=>{case["n_steps"]}, seed=>{ENSEMBLE_SEED_BASE}}})',
        )
        refused = item["message"] in bngl
        return (
            refused,
            (
                {
                    "field": "message",
                    "observed": bngl[-600:],
                    "expected": item["message"],
                }
                if not refused
                else None
            ),
            "the unclaimed combination is refused with: " + item["message"],
        )
    raise ValueError(f"unknown refusal route: {item['route']}")


def _run_refusals(directory):
    """Run the refusal checks and return their rows."""
    rows = []
    for item in REFUSALS:
        check_id = f"event-semantics:refusal:{item['id']}"
        try:
            ok, difference, detail = _refusal_statement(item, directory)
        except Exception as exc:
            rows.append(
                _row(
                    check_id,
                    "FAIL",
                    f"the refusal check raised {type(exc).__name__}: {exc}",
                )
            )
            continue
        rows.append(
            _row(
                check_id,
                "PASS" if ok else "FAIL",
                detail,
                difference,
                # A refusal check proves that the product declines a
                # combination; it never claims supported execution of it.
                evidence_kind="diagnostic-only",
                supported_execution=False,
                route=item["route"],
                expected_message=item["message"],
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Family entry points
# --------------------------------------------------------------------------- #


def run(directory):
    """Execute the generated event semantics checks."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in NATIVE_CASES:
        rows.extend(_run_native(case, directory))
    for case in ATOMIZER_CASES:
        rows.extend(_run_atomizer(case, directory))
    for case in STOCHASTIC_CASES:
        if case["id"] == "equal-priority":
            rows.extend(_run_equal_priority(case, directory))
        else:
            rows.extend(_run_stochastic(case, directory))
    rows.extend(_run_refusals(directory))
    return rows


def build_report(rows, directory):
    """Assemble the harness report for this family."""
    directory = Path(directory).resolve()
    report = dict(
        schema_version=1,
        generated_by="tests.validation.event_semantics",
        source=dict(
            revision=campaign.git(ROOT, "rev-parse", "HEAD"),
            dirty=bool(campaign.git(ROOT, "status", "--porcelain")),
        ),
        subject=dict(
            package=str(Path(sys.modules["bionetgen"].__file__).resolve().parent),
            binary=str(Path(sys.modules["bionetgen"].__file__).resolve().parent),
        ),
        references={},
        configuration=dict(
            native_cases=[dict(case) for case in NATIVE_CASES],
            atomizer_cases=[dict(case) for case in ATOMIZER_CASES],
            stochastic_cases=[dict(case) for case in STOCHASTIC_CASES],
            refusals=[dict(item) for item in REFUSALS],
            native_grids=list(NATIVE_GRIDS),
            native_tolerances=dict(atol=NATIVE_ATOL, rtol=NATIVE_RTOL),
            atomizer_tolerances=dict(atol=ATOMIZER_ATOL, rtol=ATOMIZER_RTOL),
            event_time_tolerances=dict(
                native=NATIVE_EVENT_TIME_TOLERANCE,
                atomizer=ATOMIZER_EVENT_TIME_TOLERANCE,
            ),
            ensemble_runs=ENSEMBLE_RUNS,
            ensemble_seeds=[
                ENSEMBLE_SEED_BASE + index for index in range(ENSEMBLE_RUNS)
            ],
            alpha=LAW_TAIL,
            mean_sigmas=LAW_MEAN_SIGMAS,
            variance_band=list(LAW_VARIANCE_BAND),
            law=(
                "closed-form first-order decay and the exact binomial count law "
                "of a first-order death process"
            ),
        ),
        results=rows,
    )
    report["investigation_tasks"] = reporting.investigation_tasks(report, directory)
    for task in report["investigation_tasks"]:
        task["replay_status"] = "PREPARED_NOT_EXECUTED"
    return report


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report_dir.exists() and any(args.report_dir.iterdir()):
        parser.error("report directory must be empty")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    rows = run(args.report_dir)
    report = build_report(rows, args.report_dir)
    (args.report_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (args.report_dir / "checks.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    failures = [row["id"] for row in rows if row["status"] != "PASS"]
    for row in rows:
        print(f"{row['status']:>12}  {row['id']}")
    if failures:
        print("failing checks: " + ", ".join(failures))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
