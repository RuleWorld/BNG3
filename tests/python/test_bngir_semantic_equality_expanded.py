"""Focused tests for expanded exact semantic_equal decision procedures (#156).

Covers newly implemented decidable equivalence and inequivalence certificates
from ``docs/design/semantic-equal-design.md`` while strictly preserving the
exactness contract (True only with verified equivalence certificate, False only
with verified counterexample witness, EqualityUndecided otherwise).
"""

from __future__ import annotations

import json

import pytest

import bionetgen
from bionetgen.bngir import EqualityUndecided, from_bngir, semantic_equal, to_bngir
from bionetgen.model import _cpp


def M(src: str) -> bionetgen.BioNetGenModel:
    return bionetgen.BioNetGenModel(_cpp.parse_string(src))


# ---------------------------------------------------------------------------
# EQ-rename + EQ-split + EQ-observables: hierarchical type/site/state/bond
# ---------------------------------------------------------------------------


def test_eq_rename_hierarchical_types_sites_states_bonds_and_split():
    left = M(r"""
begin model
begin parameters
  k 0.6
end parameters
begin molecule types
  A(s~u~p, b)
  B(a)
end molecule types
begin seed species
  A(s~u,b!1).B(a!1) 10
end seed species
begin observables
  Molecules ActiveComplex A(b!3,s~p).B(a!3)
  Species BoundA A(b!+)
end observables
begin reaction rules
  A(s~u,b!1).B(a!1) -> A(s~p,b!1).B(a!1) k
end reaction rules
end model
""")
    right = M(r"""
begin model
begin parameters
  k1 0.2
  k2 0.4
end parameters
begin molecule types
  X(link, q~off~on)
  Y(partner)
end molecule types
begin seed species
  X(q~off,link!7).Y(partner!7) 10
end seed species
begin observables
  Species BoundX X(link!+)
  Molecules OnComplex Y(partner!9).X(q~on,link!9)
end observables
begin reaction rules
  r1: X(q~off,link!2).Y(partner!2) -> X(q~on,link!2).Y(partner!2) k1
  r2: X(q~off,link!5).Y(partner!5) -> X(q~on,link!5).Y(partner!5) k2
end reaction rules
end model
""")
    assert semantic_equal(left, right) is True

    # Negative control: mismatched initial count under full hierarchical rename.
    wrong_init = M(r"""
begin model
begin parameters
  k 0.6
end parameters
begin molecule types
  X(link, q~off~on)
  Y(partner)
end molecule types
begin seed species
  X(q~off,link!7).Y(partner!7) 11
end seed species
begin observables
  Species BoundX X(link!+)
  Molecules OnComplex Y(partner!9).X(q~on,link!9)
end observables
begin reaction rules
  X(q~off,link!2).Y(partner!2) -> X(q~on,link!2).Y(partner!2) k
end reaction rules
end model
""")
    assert semantic_equal(left, wrong_init) is False


# ---------------------------------------------------------------------------
# EQ-functions: exact rational normalization with pre-cancellation pole checks
# ---------------------------------------------------------------------------


def test_eq_functions_rational_identity_with_matching_pole_domain():
    left = M(r"""
begin model
begin parameters
  a 2
  b 3
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin observables
  Molecules Aobs A()
end observables
begin functions
  poly_f() = (a + b)^2
  rat_f() = 1/(Aobs + 1) + 1/(Aobs + 1)
  sqf_f() = (Aobs + 1)/(Aobs + 2) + 1/(Aobs + 2)^2
end functions
begin reaction rules
  A() -> B() poly_f()
end reaction rules
end model
""")
    right = M(r"""
begin model
begin parameters
  a 2
  b 3
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin observables
  Molecules Aobs A()
end observables
begin functions
  poly_f() = a^2 + 2*a*b + b^2
  rat_f() = 2/(Aobs + 1)
  sqf_f() = (Aobs^2 + 3*Aobs + 3)/(Aobs + 2)^2
end functions
begin reaction rules
  A() -> B() poly_f()
end reaction rules
end model
""")
    assert semantic_equal(left, right) is True


def test_eq_functions_pole_domain_mismatch_never_certified_equal():
    # x/x has a pole at x=0 whereas 1 is defined at x=0; Aobs=0 is admissible.
    left = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin observables
  Molecules Aobs A()
end observables
begin functions
  f() = Aobs / Aobs
end functions
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    right = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin observables
  Molecules Aobs A()
end observables
begin functions
  f() = 1
end functions
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    assert semantic_equal(left, right) is False

    # (Aobs^2 - 1)/(Aobs - 1) has a pole at Aobs=1 whereas Aobs + 1 does not.
    pole_at_one = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin observables
  Molecules Aobs A()
end observables
begin functions
  f() = (Aobs^2 - 1) / (Aobs - 1)
end functions
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    no_pole = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin observables
  Molecules Aobs A()
end observables
begin functions
  f() = Aobs + 1
end functions
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    assert semantic_equal(pole_at_one, no_pole) is False


def test_eq_functions_multiparameter_difference_and_transcendental_undecided():
    diff_a = M(r"""
begin model
begin parameters
  a 2
  b 2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin functions
  f() = a - b
end functions
begin reaction rules
  A() -> B() 1
end reaction rules
end model
""")
    diff_b = M(r"""
begin model
begin parameters
  a 2
  b 2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin functions
  f() = 0
end functions
begin reaction rules
  A() -> B() 1
end reaction rules
end model
""")
    # As symbolic functions of (a, b), a - b != 0 at (a=3, b=5).
    assert semantic_equal(diff_a, diff_b) is False

    # Unproved transcendental identity must raise EqualityUndecided, never False.
    trig_a = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin functions
  f() = sin(k)^2 + cos(k)^2
end functions
begin reaction rules
  A() -> B() 1
end reaction rules
end model
""")
    trig_b = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin functions
  f() = 1
end functions
begin reaction rules
  A() -> B() 1
end reaction rules
end model
""")
    with pytest.raises(EqualityUndecided):
        semantic_equal(trig_a, trig_b)


# ---------------------------------------------------------------------------
# EQ-time: piecewise-linear / step inline TFUN exact knot normalization
# ---------------------------------------------------------------------------


def test_eq_time_tfun_collinear_and_clamping_knot_normalization():
    def tfun_model(expr: str) -> bionetgen.BioNetGenModel:
        return M(f"""
begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin functions
  rate() = {expr}
end functions
begin reaction rules
  A() -> B() rate()
end reaction rules
end model
""")

    # Redundant collinear interior knot (1, 2) on segment (0, 0)-(2, 4).
    assert semantic_equal(
        tfun_model("TFUN([0, 1, 2], [0, 2, 4], time)"),
        tfun_model("TFUN([0, 2], [0, 4], time)"),
    ) is True

    # Redundant flat leading/trailing clamped knots.
    assert semantic_equal(
        tfun_model("TFUN([0, 1, 2, 3], [2, 2, 4, 4], time)"),
        tfun_model("TFUN([1, 2], [2, 4], time)"),
    ) is True

    # Step TFUN with redundant equal-height knot.
    assert semantic_equal(
        tfun_model('TFUN([0, 1, 2, 3], [1, 1, 5, 5], time, method=>"step")'),
        tfun_model('TFUN([0, 2], [1, 5], time, method=>"step")'),
    ) is True

    # Negative controls: changed knot value, changed endpoint, linear vs step.
    assert semantic_equal(
        tfun_model("TFUN([0, 2], [0, 4], time)"),
        tfun_model("TFUN([0, 2], [0, 5], time)"),
    ) is False
    assert semantic_equal(
        tfun_model("TFUN([0, 2], [0, 4], time)"),
        tfun_model("TFUN([0, 3], [0, 4], time)"),
    ) is False
    assert semantic_equal(
        tfun_model('TFUN([0, 2], [0, 4], time, method=>"linear")'),
        tfun_model('TFUN([0, 2], [0, 4], time, method=>"step")'),
    ) is False


# ---------------------------------------------------------------------------
# EQ-volume: consistent volume rescaling & disjoint compartment renaming
# ---------------------------------------------------------------------------


def test_eq_volume_consistent_rescaling_and_disjoint_rename():
    def bimol(comp: str, volume: float, rate: float) -> bionetgen.BioNetGenModel:
        return M(f"""
begin model
begin parameters
  k {rate}
end parameters
begin compartments
  {comp} 3 {volume}
end compartments
begin molecule types
  A()
  B()
end molecule types
begin seed species
  @{comp}:A() 10
end seed species
begin reaction rules
  @{comp}:A() + @{comp}:A() -> @{comp}:B() k
end reaction rules
end model
""")

    # Doubling both volume and bimolecular rate preserves exact propensity k/V = 1/2.
    assert semantic_equal(bimol("cell", 2, 1), bimol("cell", 4, 2)) is True
    # Disjoint compartment rename with identical volume.
    assert semantic_equal(bimol("cell", 2, 1), bimol("cyt", 2, 1)) is True
    # Negative control: double-applying volume (or failing to scale rate).
    assert semantic_equal(bimol("cell", 2, 1), bimol("cell", 4, 0.5)) is False
    assert semantic_equal(bimol("cell", 2, 1), bimol("cell", 4, 1)) is False


# ---------------------------------------------------------------------------
# EQ-energy, EQ-barrier, EQ-reservoir: exact Arrhenius exponent normalization
# ---------------------------------------------------------------------------


def test_eq_energy_arrhenius_rearranged_deltas_and_rate_scaling_witness():
    # Both models have exact dG = E(A(s~p)) - E(A(s~u)) = +2.
    shifted_energy = M(r"""
begin model
begin molecule types
  A(s~u~p)
end molecule types
begin parameters
  phi 0.5
  Ea 1.0
end parameters
begin seed species
  A(s~u) 10
end seed species
begin energy patterns
  e_u: A(s~u) -1.0
  e_p: A(s~p) 1.0
end energy patterns
begin reaction rules
  A(s~u) <-> A(s~p) Arrhenius(phi, Ea)
end reaction rules
end model
""")
    canonical_energy = M(r"""
begin model
begin molecule types
  A(s~u~p)
end molecule types
begin parameters
  phi 0.5
  Ea 1.0
end parameters
begin seed species
  A(s~u) 10
end seed species
begin energy patterns
  ep_a: A(s~p) 1.5
  ep_b: A(s~p) 0.5
end energy patterns
begin reaction rules
  A(s~u) <-> A(s~p) Arrhenius(phi, Ea)
end reaction rules
end model
""")
    assert semantic_equal(shifted_energy, canonical_energy) is True

    # Negative control: same equilibrium ratio dG=+2, but activation energy Ea
    # shifted (all rates scaled by exp(-1)) -> strictly different dynamics.
    scaled_rates = M(r"""
begin model
begin molecule types
  A(s~u~p)
end molecule types
begin parameters
  phi 0.5
  Ea 2.0
end parameters
begin seed species
  A(s~u) 10
end seed species
begin energy patterns
  ep: A(s~p) 2.0
end energy patterns
begin reaction rules
  A(s~u) <-> A(s~p) Arrhenius(phi, Ea)
end reaction rules
end model
""")
    assert semantic_equal(canonical_energy, scaled_rates) is False


def test_eq_barrier_partition_and_shift_witness_and_v02_roundtrip():
    single_barrier = M(r"""
begin model
begin molecule types
  A(s~u~p)
end molecule types
begin parameters
  phi 0.5
  Ea 1.0
  Gb 2.0
end parameters
begin seed species
  A(s~u) 10
end seed species
begin energy patterns
  ep: A(s~p) 1.0
end energy patterns
begin barrier patterns
  bp: A(s~u) -> A(s~p) Gb
end barrier patterns
begin reaction rules
  A(s~u) <-> A(s~p) Arrhenius(phi, Ea)
end reaction rules
end model
""")
    split_barrier = M(r"""
begin model
begin molecule types
  A(s~u~p)
end molecule types
begin parameters
  phi 0.5
  Ea 1.0
  Gb1 0.75
  Gb2 1.25
end parameters
begin seed species
  A(s~u) 10
end seed species
begin energy patterns
  ep: A(s~p) 1.0
end energy patterns
begin barrier patterns
  bp1: A(s~u) -> A(s~p) Gb1
  bp2: A(s~p) -> A(s~u) Gb2
end barrier patterns
begin reaction rules
  A(s~u) <-> A(s~p) Arrhenius(phi, Ea)
end reaction rules
end model
""")
    # BNGIR v0.2 serialization & round-trip now succeeds for barrier models.
    doc = json.loads(to_bngir(single_barrier, version="0.2"))
    assert isinstance(doc["model"]["barrier_patterns"][0]["expression"], str)
    restored = from_bngir(doc)
    assert semantic_equal(single_barrier, restored) is True
    assert semantic_equal(single_barrier, split_barrier) is True

    # Negative control: shifted barrier changes exact hazard.
    shifted_barrier = M(r"""
begin model
begin molecule types
  A(s~u~p)
end molecule types
begin parameters
  phi 0.5
  Ea 1.0
  Gb 3.0
end parameters
begin seed species
  A(s~u) 10
end seed species
begin energy patterns
  ep: A(s~p) 1.0
end energy patterns
begin barrier patterns
  bp: A(s~u) -> A(s~p) Gb
end barrier patterns
begin reaction rules
  A(s~u) <-> A(s~p) Arrhenius(phi, Ea)
end reaction rules
end model
""")
    assert semantic_equal(single_barrier, shifted_barrier) is False


def test_eq_reservoir_orientation_reversal_with_and_without_work_sign():
    fwd = M(r"""
begin model
begin molecule types
  A(s~u~p)
end molecule types
begin parameters
  phi 0.3
  Ea 1.0
  W 2.0
end parameters
begin seed species
  A(s~u) 10
end seed species
begin energy patterns
  ep: A(s~p) 1.0
end energy patterns
begin reaction rules
  A(s~u) <-> A(s~p) Arrhenius(phi, Ea) driven_by(W)
end reaction rules
end model
""")
    rev_neg_work = M(r"""
begin model
begin molecule types
  A(s~u~p)
end molecule types
begin parameters
  phi 0.7
  Ea 1.0
  W -2.0
end parameters
begin seed species
  A(s~u) 10
end seed species
begin energy patterns
  ep: A(s~p) 1.0
end energy patterns
begin reaction rules
  A(s~p) <-> A(s~u) Arrhenius(phi, Ea) driven_by(W)
end reaction rules
end model
""")
    rev_same_work = M(r"""
begin model
begin molecule types
  A(s~u~p)
end molecule types
begin parameters
  phi 0.7
  Ea 1.0
  W 2.0
end parameters
begin seed species
  A(s~u) 10
end seed species
begin energy patterns
  ep: A(s~p) 1.0
end energy patterns
begin reaction rules
  A(s~p) <-> A(s~u) Arrhenius(phi, Ea) driven_by(W)
end reaction rules
end model
""")
    assert semantic_equal(fwd, rev_neg_work) is True
    assert semantic_equal(fwd, rev_same_work) is False


# ---------------------------------------------------------------------------
# EQ-delay & EQ-nonconsuming
# ---------------------------------------------------------------------------


def test_eq_delay_and_nonconsuming_normalization_and_witnesses():
    delayed_a = M(r"""
begin model
begin parameters
  k 1.5
  tau 2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> B() k delay=tau
end reaction rules
end model
""")
    delayed_renamed_split = M(r"""
begin model
begin parameters
  k1 0.5
  k2 1.0
  d 4
end parameters
begin molecule types
  X()
  Y()
end molecule types
begin seed species
  X() 10
end seed species
begin reaction rules
  r1: X() -> Y() k1 delay=d/2
  r2: X() -> Y() k2 delay=2
end reaction rules
end model
""")
    delayed_diff = M(r"""
begin model
begin parameters
  k 1.5
  tau 3
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> B() k delay=tau
end reaction rules
end model
""")
    assert semantic_equal(delayed_a, delayed_renamed_split) is True
    assert semantic_equal(delayed_a, delayed_diff) is False

    # Consuming vs NonConsuming catalytic delayed rule.
    consuming = M(r"""
begin model
begin parameters
  k 1
  tau 2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin reaction rules
  A() -> A() + B() k delay=tau
end reaction rules
end model
""")
    nonconsuming = M(r"""
begin model
begin parameters
  k 1
  tau 2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin reaction rules
  A() -> A() + B() k delay=tau NonConsuming
end reaction rules
end model
""")
    nonconsuming_renamed = M(r"""
begin model
begin parameters
  k 1
  d 2
end parameters
begin molecule types
  X()
  Y()
end molecule types
begin seed species
  X() 5
end seed species
begin reaction rules
  X() -> X() + Y() k delay=d NonConsuming
end reaction rules
end model
""")
    assert semantic_equal(nonconsuming, nonconsuming_renamed) is True
    assert semantic_equal(consuming, nonconsuming) is False


# ---------------------------------------------------------------------------
# EQ-modifiers & non-semantic metadata
# ---------------------------------------------------------------------------


def test_eq_modifiers_exhaustive_include_exclude_and_delete_molecules():
    unguarded = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A(s~u~p)
  B()
end molecule types
begin seed species
  A(s~u) 5
  A(s~p) 5
end seed species
begin reaction rules
  A(s) -> B() k
end reaction rules
end model
""")
    partitioned = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A(s~u~p)
  B()
end molecule types
begin seed species
  A(s~u) 5
  A(s~p) 5
end seed species
begin reaction rules
  r_inc: A(s) -> B() k include_reactants(1, A(s~u))
  r_exc: A(s) -> B() k exclude_reactants(1, A(s~u))
end reaction rules
end model
""")
    assert semantic_equal(unguarded, partitioned) is True

    # DeleteMolecules vs whole-species deletion on a trimer.
    del_mol = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A(b)
  B(a,c)
  C(b)
end molecule types
begin seed species
  A(b!1).B(a!1,c!2).C(b!2) 5
end seed species
begin reaction rules
  B() -> 0 k DeleteMolecules
end reaction rules
end model
""")
    del_whole = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A(b)
  B(a,c)
  C(b)
end molecule types
begin seed species
  A(b!1).B(a!1,c!2).C(b!2) 5
end seed species
begin reaction rules
  B() -> 0 k
end reaction rules
end model
""")
    assert semantic_equal(del_mol, del_whole) is False


def test_eq_metadata_model_name_is_not_process_semantics():
    m1 = M(r"""
setModelName("alpha_name")
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    m2 = M(r"""
setModelName("beta_name")
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    assert semantic_equal(m1, m2) is True


def test_eq_renamed_observable_in_rational_functional_rate():
    left = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin observables
  Molecules Aobs A()
end observables
begin functions
  rate() = k * Aobs / (Aobs + 1)
end functions
begin reaction rules
  A() -> B() rate()
end reaction rules
end model
""")
    right = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  X()
  Y()
end molecule types
begin seed species
  X() 5
end seed species
begin observables
  Molecules Xobs X()
end observables
begin functions
  rate() = (k * Xobs) / (1 + Xobs)
end functions
begin reaction rules
  X() -> Y() rate()
end reaction rules
end model
""")
    assert semantic_equal(left, right) is True


def test_eq_volume_zero_order_synthesis_rescaling():
    def synth(volume: float, rate: float) -> bionetgen.BioNetGenModel:
        return M(f"""
begin model
begin parameters
  k {rate}
end parameters
begin compartments
  cell 3 {volume}
end compartments
begin molecule types
  A()
end molecule types
begin seed species
  @cell:A() 1
end seed species
begin reaction rules
  0 -> @cell:A() k
end reaction rules
end model
""")

    # Effective synthesis rate is k * V = 4 in both models.
    assert semantic_equal(synth(2, 2), synth(4, 1)) is True
    # Unscaled rate yields k * V = 4 vs 8.
    assert semantic_equal(synth(2, 2), synth(4, 2)) is False


def test_eq_reservoir_non_arrhenius_orientation_reversal():
    fwd = M(r"""
begin model
begin parameters
  kf 2
  kr 1
  W 3
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
  B() 5
end seed species
begin reaction rules
  A() <-> B() kf, kr driven_by(W)
end reaction rules
end model
""")
    rev_neg = M(r"""
begin model
begin parameters
  kf 2
  kr 1
  W -3
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
  B() 5
end seed species
begin reaction rules
  B() <-> A() kr, kf driven_by(W)
end reaction rules
end model
""")
    rev_same = M(r"""
begin model
begin parameters
  kf 2
  kr 1
  W 3
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
  B() 5
end seed species
begin reaction rules
  B() <-> A() kr, kf driven_by(W)
end reaction rules
end model
""")
    assert semantic_equal(fwd, rev_neg) is True
    assert semantic_equal(fwd, rev_same) is False


def test_eq_serialization_unit_loss_never_certified_equal():
    with_units = M(r"""
begin model
begin units
  substanceUnits = molecule
  timeUnits = s
end units
begin parameters
  k 1 [1/s]
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    without_units = M(r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
end seed species
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    with pytest.raises(EqualityUndecided):
        semantic_equal(with_units, without_units)

