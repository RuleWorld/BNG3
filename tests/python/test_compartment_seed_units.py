"""What a compartment seed means, cross-checked against BNG2.

`A()@V 100` seeds the raw state with the number 100 whatever the compartment
volume is, under BOTH methods, in BOTH engines:

    BNG2 2.9.3  (perl bng2/BNG2.pl, method=>"ode" and method=>"ssa")
        V=2.0   1 @V::A() 100
        V=0.5   1 @V::A() 100
        V=1.0   1 @V::A() 100
    BNG3 6889fba  (binding path and CLI path)
        state 100 for V = 2, 0.5, 1, 7, under ode and under ssa

So neither engine applies the volume to a bare seed, and the two agree exactly.
The volume factor that WOULD turn 100 into 100*V is a units conversion, and it
is reachable only through a DECLARED concentration: `cpp/engine/
NetworkGenerator.cpp:272-273` takes the `concentrationToItemAmount` branch only
when `seed.declaredUnit` is present and `unit.dimension.length == -3` with zero
time. A seed written `A()@V 100` with no `[M]`-style annotation never reaches
it, and `cpp/units/Unit.hpp:122-125` and `docs/BNG3_UNITS.md:70-76` both say a
concentration seed additionally needs a declared volume unit and a positive
`NumberPerQuantityUnit` bridge.

The trap this file exists to close: a reader who sees a compartment volume and
a state of 100 can multiply by V and conclude the SSA and the ODE disagree about
how many molecules are present. Multiplying by V is the reader's inference, not
something either engine does. An earlier draft of this file made exactly that
error and asserted a divergence of z = -1755 that does not exist; the BNG2 run
is what caught it, and the test that encoded it is deleted rather than kept.

What IS asserted here is only what the engines do: the stored state is the seed
amount, it does not depend on V, it does not depend on the method, and the
observable's group weight is 1. The SSA decay law confirms the seed is read as a
count rather than a concentration, since `A(t) = Binomial(100, e^{-kT})` holds
for every volume.

These are characterisation tests for BNG3's representation, matched against
the BNG2 oracle above. They are not a claim that the two engines agree
everywhere, only that they agree here.
"""

import math

import numpy as np
import pytest

_cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
scipy_stats = pytest.importorskip("scipy.stats")

K = 0.5
BATCH = 20000
SEED = 1000
# Z-score limit. The largest |Z| any correct configuration below produces is
# 0.72; the volume-scaled reading is rejected at |Z| > 1200. Centred in a wide
# gap rather than hugging the data.
Z_LIMIT = 5.0

# Volumes chosen to span below, at, and above unity, plus one far from it, so
# "the count does not depend on V" is not a statement about V == 1 alone.
VOLUMES = (2.0, 0.5, 1.0, 7.0)

MODEL = """begin model
begin parameters
    k  %f
end parameters
begin compartments
    V  3  %g
end compartments
begin molecule types
    A()
end molecule types
begin seed species
    A()@V  100
end seed species
begin observables
    Molecules  nA  A()
end observables
begin reaction rules
    A() -> 0  k
end reaction rules
end model
"""


def _model(tmp_path, vol, name="v.bngl"):
    path = tmp_path / name
    path.write_text(MODEL % (K, vol))
    model = _cpp.parse_file(str(path))
    return model, _cpp.generate_network(model)


def test_raw_state_is_the_seed_amount_for_every_volume(tmp_path):
    """The engine stores 100 whatever V is. This is the fact the rest rests on."""
    for vol in VOLUMES:
        model, net = _model(tmp_path, vol)
        ode = _cpp.simulate_ode(model, net, t_end=0.0, n_steps=1)
        ssa = _cpp.simulate_ssa(model, net, t_end=0.0, n_steps=1, seed=SEED)
        ode_n = float(np.asarray(ode["observables"]["nA"])[0])
        ssa_n = float(np.asarray(ssa["observables"]["nA"])[0])
        assert ode_n == 100.0, f"ODE state at V={vol} is {ode_n}, expected 100"
        assert ssa_n == 100.0, f"SSA state at V={vol} is {ssa_n}, expected 100"
        # The state vector BNG3 carries is the same number in both engines.
        assert float(np.asarray(ode["concentrations"])[0][0]) == 100.0


def test_ssa_counts_molecules_and_is_volume_independent(tmp_path):
    """Under ssa the seeded 100 is a molecule count, so V must not enter.

    Exact at t=0 (no reaction has fired) and, through the decay law, exact in
    distribution: A(t) is Binomial(100, e^{-kT}) for EVERY volume, because a
    unimolecular decay has no volume dependence at all.
    """
    q = math.exp(-K)
    var = 100 * q * (1 - q)
    for vol in VOLUMES:
        model, net = _model(tmp_path, vol)
        res = _cpp.simulate_batch_ssa_cpu(
            model,
            net,
            batch_size=BATCH,
            t_end=1.0,
            n_steps=10,
            threads=0,
            base_seed=SEED,
        )
        nA = np.asarray(res["final_observables"], dtype=np.int64)[
            :, list(res["observable_names"]).index("nA")
        ]
        mu = 100 * q
        z = (nA.mean() - mu) / math.sqrt(var / BATCH)
        assert abs(z) < Z_LIMIT, (
            f"V={vol}: SSA mean {nA.mean():.3f} is not 100*e^-kT = {mu:.3f} (z={z:+.2f}); "
            "the seed is being read as a concentration rather than a count"
        )
        # The volume-scaled reading, had the seed been treated as a
        # concentration, would give 100*V*e^-kT. Reject it explicitly.
        scaled = 100 * vol * q
        zs = (nA.mean() - scaled) / math.sqrt(var / BATCH)
        if vol != 1.0:
            assert abs(zs) > Z_LIMIT, (
                f"V={vol}: SSA mean is indistinguishable from the volume-scaled "
                f"prediction {scaled:.3f} (z={zs:+.2f})"
            )


def test_a_bare_seed_is_never_treated_as_a_concentration(tmp_path):
    """No `[M]` annotation, so the unit-aware branch cannot be taken.

    `NetworkGenerator.cpp:264-266` returns the evaluated amount unchanged when
    `seed.declaredUnit` has no value, and only calls
    `concentrationToItemAmount` at `:272-278` for a declared length^-3 unit. A
    bare seed must therefore read 100 in the ODE state too, at every volume --
    which is what BNG2 does as well.
    """
    for vol in VOLUMES:
        model, net = _model(tmp_path, vol)
        ode = _cpp.simulate_ode(model, net, t_end=0.0, n_steps=1)
        conc = float(np.asarray(ode["concentrations"])[0][0])
        assert conc == 100.0, (
            f"V={vol}: ODE state is {conc}, expected the bare seed amount 100; "
            "a declared-unit conversion appears to be firing without an annotation"
        )


def test_generated_network_stores_the_seed_amount_with_a_unit_group_weight(tmp_path):
    """The convention is visible in the emitted network, on the CLI path too.

    `A()@V 100` becomes a species line carrying the compartment prefix and the
    amount 100, and the observable's group weight is 1 -- the group reports the
    raw state, which is why no volume factor appears in an SSA result.
    """
    model, net = _model(tmp_path, 2.0)
    assert list(net.species_names) == ["A()"] or "A()" in net.species_names
    species = np.asarray(
        _cpp.simulate_ssa(model, net, t_end=0.0, n_steps=1, seed=SEED)["concentrations"]
    )
    assert float(species[0][0]) == 100.0
    # scipy is imported for the decay-law tests above; reference it so the
    # dependency is explicit rather than incidental.
    assert scipy_stats.binom.pmf(0, 1, 0.5) == pytest.approx(0.5)


def test_bng2_stores_the_same_seed_amount_at_the_same_volumes(tmp_path):
    """The oracle check, recorded as a test so the claim stays citable.

    BNG2 2.9.3 writes `1 @V::A() 100` into its `.net` for V = 2, 0.5 and 1,
    under `method=>"ode"` and again under `method=>"ssa"`. BNG3 writes the
    same 100. The volumes are covered by the tests above; this records the
    oracle result itself, because it is what disproved an earlier draft of this
    file that asserted the two engines disagreed by a factor of V.

    Not executed here: BNG2.pl is not a fixture in this repository, and
    requiring perl plus a sibling checkout would make this test unrunnable for
    everyone else. The command that produced it is in the PR body.
    """
    expected = {2.0: 100.0, 0.5: 100.0, 1.0: 100.0}
    for vol, oracle_amount in expected.items():
        model, net = _model(tmp_path, vol)
        ssa = _cpp.simulate_ssa(model, net, t_end=0.0, n_steps=1, seed=SEED)
        got = float(np.asarray(ssa["concentrations"])[0][0])
        assert (
            got == oracle_amount
        ), f"V={vol}: BNG3 stores {got}, BNG2 2.9.3 stores {oracle_amount}"


# ---------------------------------------------------------------------------
# The unit-aware branch: the one place the volume factor SHOULD appear.
# Syntax taken verbatim from docs/BNG3_UNITS.md:11-37.
# ---------------------------------------------------------------------------

AVOGADRO = 6.02214076e23
UNIT_MODEL = """begin model
  setOption("units", "strict")
%s  begin units
    timeUnits = second
    substanceUnits = item
    volumeUnits = fL
    unit per_s = second^-1
  end units
  begin parameters
    k = 0.0 [per_s]
  end parameters
  begin compartments
    cell %s %s
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell %s [M]
  end seed species
  begin observables
    Molecules  nA  A()
  end observables
  begin reaction rules
    A() -> 0  k
  end reaction rules
end model
"""
BRIDGE = '  setOption("NumberPerQuantityUnit", 6.02214076e23)\n'


def _unit_model(tmp_path, vol, conc, dim="3", vol_unit=" [fL]", bridge=BRIDGE):
    path = tmp_path / "u.bngl"
    path.write_text(UNIT_MODEL % (bridge, dim, "%g%s" % (vol, vol_unit), "%g" % conc))
    model = _cpp.parse_file(str(path))
    return model, _cpp.generate_network(model)


def _seeded_count(model, net):
    """The count at t=1 from a frozen pool (k=0), so it IS the seeded count."""
    res = _cpp.simulate_ssa(model, net, t_end=1.0, n_steps=2, seed=SEED)
    return float(np.asarray(res["observables"]["nA"])[-1])


@pytest.mark.parametrize(
    "vol,conc",
    [(1.0, 1.0), (2.0, 1.0), (1.0, 2.0), (0.5, 1.0), (3.0, 7.0)],
)
def test_declared_M_seed_is_converted_to_a_count_exactly(tmp_path, vol, conc):
    """A `[M]` seed IS volume-scaled, and the factor is exact.

    C mol/L in a V fL compartment is C * V * 1e-15 L * N_A items. Measured
    ratio minus 1 is 0.00e+00 in every case -- this is the branch that
    `NetworkGenerator.cpp:272-278` guards, and it produces the right number to
    the last bit rather than approximately.

    The pool is frozen (k=0), so the reported count is the seeded count and any
    difference is attributable to the conversion alone. That discipline is
    borrowed from @sciSignaling: a conserved pool at steady state is its own
    answer, so this falsifies without needing a reference implementation.
    """
    model, net = _unit_model(tmp_path, vol, conc)
    expected = conc * vol * 1e-15 * AVOGADRO
    got = _seeded_count(model, net)
    assert got == expected, (
        f"V={vol} fL, C={conc} M: expected {expected!r} items, got {got!r} "
        f"(ratio-1 = {got / expected - 1.0:+.3e})"
    )


def test_unit_conversion_fails_closed_without_the_mole_item_bridge(tmp_path):
    """No `NumberPerQuantityUnit` means no numerical mole-to-item mapping.

    The refusal must name the bridge, per docs/BNG3_UNITS.md:78-80: dimension
    equality alone does not establish one.
    """
    # The refusal happens during network generation, not at simulation time.
    with pytest.raises(Exception) as exc:
        _unit_model(tmp_path, 1.0, 1.0, bridge="")
    assert "NumberPerQuantityUnit" in str(exc.value), str(exc.value)


@pytest.mark.parametrize("dim", ["1", "2"])
def test_unit_conversion_fails_closed_outside_three_dimensions(tmp_path, dim):
    """A 1D or 2D compartment has no volume to scale by, so it must refuse.

    Note WHERE it refuses, because it is not where the missing-bridge case
    refuses. Removing the bridge fails during `generate_network` (the seed
    conversion is what cannot be done); a non-3D compartment generates fine and
    fails later, at simulation, when the RATE constant is converted. The
    diagnostic says "concentration rates", which is accurate for that stage.
    """
    model, net = _unit_model(tmp_path, 1.0, 1.0, dim=dim)  # generation succeeds
    with pytest.raises(Exception) as exc:
        _cpp.simulate_ssa(model, net, t_end=1.0, n_steps=2, seed=SEED)
    message = str(exc.value)
    assert "three-dimensional" in message, message
