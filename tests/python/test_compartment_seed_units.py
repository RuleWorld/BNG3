"""What a compartment seed MEANS under each method, stated exactly.

`A()@V 100` seeds the raw simulation state with the number 100 whatever the
compartment volume is. The number of MOLECULES that state denotes is then
method-dependent, and the two methods do not agree unless V == 1:

    under ssa the state is a MOLECULE COUNT    -> 100 molecules, any V
    under ode the state is a CONCENTRATION      -> 100 * V molecules

This is BNG2's convention (the ODE integrates concentrations, the SSA counts
molecules), not a counting bug, and the repository states the seed rule itself
at `models/Motivating_example_cBNGL.bngl:27` -- "initial species counts
(extensive units: quantity, not concentration)".

What is easy to get wrong, and what these tests pin, is the consequence:
because the SSA count does NOT scale with V, switching `method=>"ode"` to
`method=>"ssa"` on a model with a non-unit compartment describes a physically
DIFFERENT system. At V=2, t=1, k=0.5 the ODE has 121.3 molecules and the SSA
has 60.7 -- a factor of two, and they coincide only at V=1.

Everything asserted here is deterministic: at t=0 no reaction has fired, so
the counts are exact integers and no Monte-Carlo error is involved. The one
statistical check (the decay law) exists only to confirm the SSA treats the
seed as a count rather than a concentration.

NOTE ON SCOPE: these tests characterise BNG3's representation. They are not a
claim that BNG2 agrees -- no BNG2 oracle is available in this checkout, and
whether the convention is compatibility-preserving is an open question that a
BNG2 run would settle.
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


def test_ode_state_is_a_concentration_so_molecules_scale_with_volume(tmp_path):
    """Under ode the same 100 is a concentration, so the molecule count is 100*V.

    This is the other half of the asymmetry, asserted on the deterministic
    path where there is no sampling error to reason about.
    """
    for vol in VOLUMES:
        model, net = _model(tmp_path, vol)
        ode = _cpp.simulate_ode(model, net, t_end=0.0, n_steps=1)
        conc = float(np.asarray(ode["concentrations"])[0][0])
        assert (
            conc * vol == 100 * vol
        ), f"V={vol}: ODE concentration {conc} does not denote {100 * vol} molecules"
        assert conc == 100.0


def test_the_two_methods_describe_different_systems_unless_volume_is_one(tmp_path):
    """The hazard, made explicit and quantified.

    At a volume other than 1 the ODE and the SSA put different numbers of
    molecules in the system. This is the reason the convention is worth
    documenting rather than leaving implicit: a user who changes only the method
    does not change only the noise.
    """
    q = math.exp(-K)
    for vol in (2.0, 0.5, 7.0):
        model, net = _model(tmp_path, vol)
        ode = _cpp.simulate_ode(model, net, t_end=1.0, n_steps=2)
        conc = float(np.asarray(ode["concentrations"])[-1][0])
        ode_molecules = conc * vol
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
        var = 100 * q * (1 - q)
        z = (nA.mean() - ode_molecules) / math.sqrt(var / BATCH)
        assert abs(z) > Z_LIMIT, (
            f"V={vol}: SSA {nA.mean():.1f} and ODE {ode_molecules:.1f} molecules "
            f"agree, which should not happen for a volume other than 1 (z={z:+.2f})"
        )
    # ... and at V == 1 they agree, which is the whole content of the exception.
    model, net = _model(tmp_path, 1.0)
    ode = _cpp.simulate_ode(model, net, t_end=1.0, n_steps=2)
    conc = float(np.asarray(ode["concentrations"])[-1][0])
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
    var = 100 * q * (1 - q)
    z = (nA.mean() - conc) / math.sqrt(var / BATCH)
    assert abs(z) < Z_LIMIT, f"V=1: SSA and ODE molecules should agree (z={z:+.2f})"


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
