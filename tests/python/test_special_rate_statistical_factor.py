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
