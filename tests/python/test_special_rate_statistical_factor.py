"""A special rate law carries the rule's statistical factor.

``A() + A() -> D() Sat(kcat, K)`` is a rule with two identical reactants, so
its rate law is scaled by the symmetry factor ``1/2!``.  The factor is a
property of the rule's reactants, not of the rate law's shape: canonical Perl
BNG2 writes it as a prefix on the rate law for *every* rate law type
(``RateLaw::toString`` in ``RateLaw.pm``), so its own network for this rule
reads::

    1 1,1 2 0.5*Sat kcat K

and this engine's own network writer emits the same prefix.  The engine used
to drop the factor for a Saturation, Hill or Michaelis-Menten law, so it
disagreed with the network it exported and with BNG2's trajectory.

The oracle is canonical Perl BNG2, run on the same model:

    perl legacy/perl/BNG2.pl sat.bngl

It wrote ``0.5*Sat kcat K`` for the network.  Its own network runner
(``bng2/bin/run_network``, the standalone CVODE engine that ships with
BioNetGen) propagated that network to ``A_tot = 15.500504441750`` and
``D_tot = 2.249747779126`` at ``t = 1`` with ``rtol = atol = 1e-12``; the
closed-form integration of the same law gives ``15.500504441753`` and
``2.249747779123``.  The engine's own ODE now reproduces those digits.

A ``TotalRate`` rule is the one rate law that takes no statistical factor: it
states the macroscopic total rate of the reaction, so the factor must not be
applied to it.  Canonical BioNetGen implements that in ``Rxn.pm``
(``my $sf = ($rxn->RxnRule && $rxn->RxnRule->TotalRate) ? 1 : $rxn->StatFactor``)
and this engine's own network writer already leaves the prefix off for such a
rule.  The engine has to agree with the network it exports here too.

Both of the engine's stochastic backends have to carry the factor: the native
one and the NFsim one, or the answer would depend on which backend the caller
asked for.  The NFsim route kept the symmetry factor on the transformation
set but never applied it to a special rate, so the two backends disagreed by
the factor.  The ensemble check below pins both against the analytic count law
of the declared convention, under a recorded seed policy and run budget.

The native SSA, NFsim, and canonical BioNetGen use the discrete distinct-pair
count for stochastic propensities.  Canonical BioNetGen's discrete saturating
rate (``bng2/Network3/src/network.cpp``, ``SATURATION``) multiplies a repeated
reactant by ``X[iarr[ig]] - n``; NFsim applies the same correction in
``BasicRxnClass::getCorrectedReactantCount``.  The ODE retains the continuous
count, as canonical BioNetGen does when its ``discrete`` flag is off.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

bionetgen = pytest.importorskip("bionetgen")

REPO = Path(__file__).resolve().parents[2]
BNG2 = REPO / "legacy" / "perl" / "BNG2.pl"

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

TOTAL_RATE_MODEL = """begin model
begin parameters
  k 0.4
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
  A() + A() -> D() k TotalRate
end reaction rules
end model
"""

# Canonical BioNetGen's own network runner, run on the network it wrote for
# the model above with ``rtol = atol = 1e-12``:
#     run_network -r 1e-12 -a 1e-12 sat.net 0 0.5 1.0
# The closed-form integration of the same law agrees to 1e-13.
BNG2_A = 15.500504441750
BNG2_D = 2.249747779126

# The same law without the statistical factor.  The engine used to produce
# this trajectory, so every check below has to reject it.
FACTOR_FREE_A = 12.294175238866
FACTOR_FREE_D = 3.852912380567


def _model(text: str = MODEL):
    from bionetgen.model import _cpp

    return bionetgen.BioNetGenModel(_cpp.parse_string(text))


def _net_reactions(model) -> str:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "m.net"
        model.write_net(str(path))
        body = path.read_text()
    return body.split("begin reactions", 1)[1].split("end reactions", 1)[0].strip()


def _rate_coefficients(model, network, state):
    from bionetgen import _bionetgen_cpp as cpp

    return [
        float(value)
        for value in cpp._validation_ode_rate_coefficients(
            model._model, network, 0.0, state
        )
    ]


# --------------------------------------------------------------------------
# The canonical oracle.
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    shutil.which("perl") is None or not BNG2.is_file(),
    reason="bundled Perl BNG2.pl is unavailable",
)
def test_canonical_bng2_writes_the_statistical_factor_on_a_saturation_law(tmp_path):
    """Canonical Perl BNG2 is the oracle for the factor's scope."""
    model = tmp_path / "sat.bngl"
    model.write_text(
        """
begin parameters
  kcat 0.4
  K 10
end parameters

begin species
  A() 20
end species

begin reaction rules
  A() + A() -> D() Sat(kcat,K)
end reaction rules

begin observables
  Molecules A_tot A
  Molecules D_tot D
end observables

begin actions
  generate_network()
end actions
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["perl", str(BNG2), str(model)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    network = (tmp_path / "sat.net").read_text()
    reactions = network.split("begin reactions", 1)[1].split("end reactions", 1)[0]
    assert re.search(r"\b0\.5\*Sat kcat K\b", reactions), reactions.strip()


# --------------------------------------------------------------------------
# The engine has to agree with the network it exports.
# --------------------------------------------------------------------------


def test_the_exported_network_carries_the_statistical_factor():
    model = _model()
    model.generate_network()
    reactions = _net_reactions(model)
    assert re.search(r"\b0\.5\*Sat kcat K\b", reactions), reactions


def test_the_ode_reproduces_the_canonical_bng2_trajectory():
    model = _model()
    result = model.simulate(method="ode", t_end=1.0, n_steps=20)
    assert result.observables["A_tot"][-1] == pytest.approx(BNG2_A, rel=1e-6)
    assert result.observables["D_tot"][-1] == pytest.approx(BNG2_D, rel=1e-6)
    # The factor-free law is a different model and has to be rejected.
    assert result.observables["D_tot"][-1] != pytest.approx(FACTOR_FREE_D, rel=1e-3)


def test_the_compiled_rate_coefficient_carries_the_statistical_factor():
    # The rate coefficient of the special law is the total rate
    # 0.5 * kcat * S1 * S2 / (K + S1).  Before the repair it was the
    # factor-free kcat * S1 * S2 / (K + S1), twice the canonical rate.
    model = _model()
    network = model.generate_network()
    coefficients = _rate_coefficients(model, network, [20.0, 0.0])
    canonical = 0.5 * 0.4 * 20.0 * 20.0 / (10.0 + 20.0)
    assert coefficients == pytest.approx([canonical])
    assert coefficients != pytest.approx([2.0 * canonical])


def test_a_total_rate_rule_takes_no_statistical_factor():
    """A TotalRate rule states the macroscopic total rate of the reaction.

    Canonical BioNetGen forces the statistical factor to one for such a rule
    (``Rxn.pm``), this engine's network writer leaves the prefix off, and the
    engine has to agree with both.
    """
    model = _model(TOTAL_RATE_MODEL)
    network = model.generate_network()
    reactions = _net_reactions(model)
    assert not re.search(r"\b0\.5\*", reactions), reactions
    coefficients = _rate_coefficients(model, network, [20.0, 0.0])
    assert coefficients == pytest.approx([0.4])


def test_a_rule_with_distinct_reactants_takes_no_statistical_factor():
    model = _model(
        MODEL.replace("A() + A() -> D() Sat(kcat,K)", "A() + E() -> D() Sat(kcat,K)")
        .replace("  A()\n  D()", "  A()\n  E()\n  D()")
        .replace("  A() 20", "  A() 20\n  E() 1")
    )
    network = model.generate_network()
    reactions = _net_reactions(model)
    assert not re.search(r"\b0\.5\*", reactions), reactions
    coefficients = _rate_coefficients(model, network, [20.0, 1.0, 0.0])
    assert coefficients == pytest.approx([0.4 * 20.0 * 1.0 / (10.0 + 20.0)])


# --------------------------------------------------------------------------
# Both stochastic backends have to carry the factor.
#
# The comparison is distributional.  The two backends construct their event
# streams differently, so equal seeds do not establish pathwise equivalence;
# each backend is compared against the analytic count law of the convention
# that backend implements instead.
#
# Seed policy: seeds 1..TRAJECTORIES, one trajectory per seed, one model
# instance per backend.  Run budget: TRAJECTORIES trajectories per backend
# over a horizon of 1.0 time unit.
# --------------------------------------------------------------------------

TRAJECTORIES = 4000
HORIZON = 1.0
STEP = 2  # the rule consumes two A molecules per event
POPULATION = 20
KCAT = 0.4
KM = 10.0


def _discrete_hazard(population: float, factor: float = 0.5) -> float:
    """The count convention of canonical BioNetGen's discrete rate.

    ``bng2/Network3/src/network.cpp`` multiplies a repeated reactant by
    ``X[iarr[ig]] - n``, so the second copy of a reactant counts the
    distinct pairs rather than the plain population.
    """
    return factor * KCAT * population * (population - 1.0) / (KM + population)


def _expected_events(hazard) -> float:
    """The expected number of events, from the master equation.

    The generator is a pure death with a step of two: the population falls
    from ``n`` to ``n - 2`` at the given hazard.  The distribution is
    integrated here, independently of the engine.
    """
    states = list(range(POPULATION, -1, -STEP))
    index = {value: position for position, value in enumerate(states)}
    rates = [hazard(value) for value in states]
    steps = 20000
    h = HORIZON / steps
    weights = [0.0] * len(states)
    weights[index[POPULATION]] = 1.0

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
        weight * (POPULATION - value) / STEP for weight, value in zip(weights, states)
    )


def _ensemble(backend: str) -> list[float]:
    """The final event count of every trajectory of the recorded run budget."""
    model = _model()
    values = []
    for seed in range(1, TRAJECTORIES + 1):
        result = model.simulate(method=backend, t_end=HORIZON, n_steps=20, seed=seed)
        values.append(float(result.observables["D_tot"][-1]))
    return values


#: The count convention each backend implements, and the analytic mean of the
#: corresponding law with and without the statistical factor.
BACKENDS = {
    "ssa": _discrete_hazard,
    "nf": _discrete_hazard,
}


@pytest.mark.parametrize("backend", ["ssa", "nf"])
def test_every_stochastic_backend_carries_the_statistical_factor(backend):
    values = _ensemble(backend)
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    stderr = (variance / len(values)) ** 0.5

    hazard = BACKENDS[backend]
    carrying = _expected_events(hazard)
    free = _expected_events(lambda population: hazard(population, 1.0))
    band = 4.0 * stderr
    assert abs(mean - carrying) <= band, (
        f"{backend}: {mean:.4f} events, the factor-carrying law expects "
        f"{carrying:.4f} +/- {band:.4f}"
    )
    # The factor-free law is twice the rate, so it has to be rejected.
    assert abs(mean - free) > band, (
        f"{backend}: {mean:.4f} events, the factor-free law expects {free:.4f}; "
        "the statistical factor is missing"
    )


def test_the_two_stochastic_backends_carry_the_same_statistical_factor():
    """The two backends implement the same stochastic count law and factor."""
    summaries = {}
    for backend in ("ssa", "nf"):
        values = _ensemble(backend)
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        summaries[backend] = (mean, math.sqrt(variance / len(values)))

    observed = abs(summaries["ssa"][0] - summaries["nf"][0])
    pooled_stderr = math.hypot(summaries["ssa"][1], summaries["nf"][1])
    assert observed <= 4.0 * pooled_stderr, (
        f"the backends differ by {observed:.4f} events, more than four pooled "
        f"standard errors ({4.0 * pooled_stderr:.4f})"
    )


def test_hill_ssa_uses_discrete_count_for_a_repeated_co_reactant():
    """The Hill substrate stays continuous; its repeated co-reactant is discrete.

    Starting with two A molecules allows at most one firing. The Hill
    substrate contributes ``A/(K+A)`` while the second, identical reactant
    contributes ``A-1`` in the stochastic law. This separates the discrete
    propensity from the previous continuous ``A*A`` evaluation.
    """
    hill_model = MODEL.replace("kcat 0.4", "kcat 20").replace("K 10", "K 0.1")
    hill_model = hill_model.replace("A() 20", "A() 2").replace(
        "Sat(kcat,K)", "Hill(kcat,K,1)"
    )
    model = _model(hill_model)
    horizon = 0.05
    trajectories = 1000
    discrete_rate = 0.5 * 20.0 * 2.0 / (0.1 + 2.0) * (2.0 - 1.0)
    discrete_probability = 1.0 - math.exp(-discrete_rate * horizon)
    continuous_rate = 0.5 * 20.0 * 2.0 / (0.1 + 2.0) * 2.0
    continuous_probability = 1.0 - math.exp(-continuous_rate * horizon)

    events = [
        float(
            model.simulate(
                method="ssa", t_end=horizon, n_steps=1, seed=seed
            ).observables["D_tot"][-1]
        )
        for seed in range(1, trajectories + 1)
    ]
    mean = sum(events) / trajectories
    sample_variance = sum((event - mean) ** 2 for event in events) / (trajectories - 1)
    band = 4.0 * math.sqrt(sample_variance / trajectories)

    assert abs(mean - discrete_probability) <= band, (
        mean,
        discrete_probability,
        band,
    )
    assert abs(mean - continuous_probability) > band, (
        mean,
        continuous_probability,
        band,
    )
