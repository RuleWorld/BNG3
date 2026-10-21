"""A special rate law carries the rule's statistical factor.

``A() + A() -> D() Sat(kcat, K)`` is a rule with two identical reactants, so
its rate law is scaled by the symmetry factor ``1/2!``.  The factor is a
property of the rule's reactants, not of the rate law's shape: BNG2 writes it
as a prefix on the rate law for *every* rate law type (``RateLaw::toString``
in ``RateLaw.pm``), so its own network for this rule reads::

    1 1,1 2 0.5*Sat kcat K

and this engine's own network writer emits the same prefix.  The engine used
to drop the factor for a Saturation, Hill or Michaelis-Menten law, so it
disagreed with the network it exported and with BNG2's trajectory.

The oracle here is the canonical Perl BNG2 2.9.3, run on the same model:

    perl BNG2.pl sat.bngl

It wrote ``A_tot = 15.50050409333`` and ``D_tot = 2.249747953337`` at
``t = 1``.  The engine's own ODE now reproduces those digits, and its SSA
propensity is the factor-carrying rate rather than the factor-free one.

Both of the engine's stochastic backends have to carry the factor: the native
one and the NFsim one, or the answer would depend on which backend the caller
asked for.  The NFsim route kept the symmetry factor on the transformation set
but never applied it to a special rate, so the two backends disagreed by the
factor.  The ensemble check below pins both: each backend's event total must
agree with the factor-carrying law and must disagree with the factor-free one.
"""

from __future__ import annotations

import re

import pytest

bionetgen = pytest.importorskip("bionetgen")

MODEL = """begin model
begin parameters
  kcat 0.4
  K 10
end parameters
begin molecule types
  A()
  D()
end molecule types
begin observables
  Molecules A_tot A()
  Molecules D_tot D()
end observables
begin seed species
  A() 20
end seed species
begin reaction rules
  A() + A() -> D() Sat(kcat,K)
end reaction rules
end model
"""

# BNG2 2.9.3, on the model above, at t = 1.
BNG2_A = 15.50050409333
BNG2_D = 2.249747953337


@pytest.fixture(scope="module")
def model():
    from bionetgen.model import _cpp

    return bionetgen.BioNetGenModel(_cpp.parse_string(MODEL))


def test_the_exported_network_carries_the_statistical_factor(model, tmp_path):
    # The engine has to agree with the network it exports.  BNG2's network for
    # this rule is exactly this line.
    model.generate_network()
    path = tmp_path / "sat.net"
    model.write_net(str(path))
    reactions = path.read_text().split("begin reactions", 1)[1]
    reactions = reactions.split("end reactions", 1)[0]
    assert re.search(r"\b0\.5\*Sat kcat K\b", reactions), reactions.strip()


def test_the_ode_reproduces_the_bng2_trajectory(model):
    result = model.simulate(method="ode", t_end=1.0, n_steps=20)
    assert result.observables["A_tot"][-1] == pytest.approx(BNG2_A, rel=1e-7)
    assert result.observables["D_tot"][-1] == pytest.approx(BNG2_D, rel=1e-7)


def _state(network, amounts):
    return [float(amounts.get(name, 0.0)) for name in network.species_names]


def test_the_ssa_propensity_carries_the_statistical_factor(model):
    # The propensity is the total rate 0.5 * kcat * S1 * S2 / (K + S1).  Before
    # the repair it was the factor-free kcat * S1 * S2 / (K + S1), twice the
    # canonical rate.
    from bionetgen import _bionetgen_cpp as cpp

    network = model.generate_network()
    state = _state(network, {"A()": 20.0, "D()": 0.0})
    propensities = [
        float(value)
        for value in cpp._validation_ssa_propensities(model._model, network, 0.0, state)
    ]
    canonical = 0.5 * 0.4 * 20.0 * 20.0 / (10.0 + 20.0)
    assert propensities == pytest.approx([canonical])


def test_a_rule_with_distinct_reactants_is_unchanged():
    # The factor only applies to identical reactants, so a distinct-reactant
    # saturation law must not pick it up.
    from bionetgen.model import _cpp

    distinct = (
        MODEL.replace("A() + A() -> D() Sat(kcat,K)", "A() + E() -> D() Sat(kcat,K)")
        .replace("  A()\n  D()", "  A()\n  E()\n  D()")
        .replace("  A() 20", "  A() 20\n  E() 1")
    )
    other = bionetgen.BioNetGenModel(_cpp.parse_string(distinct))
    network = other.generate_network()
    state = _state(network, {"A()": 20.0, "E()": 1.0, "D()": 0.0})
    from bionetgen import _bionetgen_cpp as cpp

    propensities = [
        float(value)
        for value in cpp._validation_ssa_propensities(other._model, network, 0.0, state)
    ]
    assert propensities == pytest.approx([0.4 * 20.0 * 1.0 / (10.0 + 20.0)])


# --------------------------------------------------------------------------
# Both stochastic backends have to carry the factor.
# --------------------------------------------------------------------------

TRAJECTORIES = 40
HORIZON = 1.0
STEP = 2  # the rule consumes two A molecules per event

# The hazard of the rule's event rate at a population of n A molecules.
# The factor-carrying law is BNG2's canonical network semantics: the network
# reads ``0.5*Sat kcat K``, so the event rate is 0.5*kcat*n^2/(K+n).
FACTOR = 0.5


def _hazard(population, factor=FACTOR):
    return factor * 0.4 * population * population / (10.0 + population)


def _expected_events(factor=FACTOR, horizon=HORIZON, steps=20000):
    """The expected number of events, from the master equation.

    The generator is a pure death with a step of two: the population falls
    from ``n`` to ``n - 2`` at the hazard above.  The distribution is
    integrated here, independently of the engine.
    """
    population = 20
    states = list(range(population, -1, -STEP))
    index = {value: position for position, value in enumerate(states)}
    rates = [_hazard(value, factor) for value in states]
    h = horizon / steps
    weights = [0.0] * len(states)
    weights[index[population]] = 1.0

    def derivative(current):
        out = [0.0] * len(states)
        for position, value in enumerate(states):
            out[position] += -rates[position] * current[position]
            if position + 1 < len(states):
                out[position + 1] += rates[position] * current[position]
        return out

    for _ in range(steps):
        k1 = derivative(weights)
        k2 = derivative([w + 0.5 * h * d for w, d in zip(weights, k1)])
        k3 = derivative([w + 0.5 * h * d for w, d in zip(weights, k2)])
        k4 = derivative([w + h * d for w, d in zip(weights, k3)])
        weights = [
            w + h / 6.0 * (a + 2.0 * b + 2.0 * c + d)
            for w, a, b, c, d in zip(weights, k1, k2, k3, k4)
        ]
    return sum(
        weight * (population - value) / STEP for weight, value in zip(weights, states)
    )


@pytest.mark.parametrize("backend", ["ssa", "nf"])
def test_every_stochastic_backend_carries_the_statistical_factor(backend):
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODEL))
    total = 0
    for seed in range(1, TRAJECTORIES + 1):
        result = model.simulate(method=backend, t_end=HORIZON, n_steps=20, seed=seed)
        total += float(result.observables["D_tot"][-1])

    # The event count is a sum of independent Bernoulli-like counts, so its
    # spread is set by the number of events; the band below is four standard
    # deviations of the factor-carrying law's total.
    carrying = _expected_events(FACTOR) * TRAJECTORIES
    free = _expected_events(1.0) * TRAJECTORIES
    spread = (carrying**0.5) * 4.0
    assert abs(total - carrying) <= spread, (
        f"{backend}: {total} events, the factor-carrying law expects "
        f"{carrying:.1f} +/- {spread:.1f}"
    )
    # The factor-free law is twice the rate, so it has to be rejected.
    assert abs(total - free) > spread, (
        f"{backend}: {total} events, the factor-free law expects {free:.1f}; "
        "the statistical factor is missing"
    )


def test_the_two_stochastic_backends_agree():
    totals = {}
    for backend in ("ssa", "nf"):
        model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODEL))
        total = 0
        for seed in range(1, TRAJECTORIES + 1):
            result = model.simulate(
                method=backend, t_end=HORIZON, n_steps=20, seed=seed
            )
            total += float(result.observables["D_tot"][-1])
        totals[backend] = total
    expected = _expected_events(FACTOR) * TRAJECTORIES
    spread = (expected**0.5) * 4.0
    assert abs(totals["ssa"] - totals["nf"]) <= spread, totals
