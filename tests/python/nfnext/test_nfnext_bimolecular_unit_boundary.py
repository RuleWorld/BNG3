"""Bounded physical-unit checks for the NFnext production entry point."""

import math

import pytest

import bionetgen._bionetgen_cpp as cpp

MISSING_VOLUME = """begin model
begin parameters
  k 1e6 [M^-1*s^-1]
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 10
  B(a) 10
end seed species
begin reaction rules
  A(b)+B(a)->A(b!1).B(a!1) k
end reaction rules
end model
"""

# With one A and one B in 1 fL, k / (N_A * V) = 1 s^-1, so P(A still free
# at t=1) = exp(-1). BNG2 2.9.3 independently lowers A(b) to the free A
# species only, confirming that FreeA is the correct observable.
COMPLETE_VOLUME = """begin model
setOption("units", "strict")
setOption("NumberPerQuantityUnit", 6.02214076e23)
begin units
  timeunits second
end units
begin parameters
  k 6.02214076e8 [M^-1/second]
  Vc 1 [fL]
end parameters
begin compartments
  cell 3 Vc [fL]
end compartments
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b)@cell 1
  B(a)@cell 1
end seed species
begin observables
  Molecules FreeA A(b)@cell
  Molecules BoundAB A(b!1).B(a!1)@cell
end observables
begin reaction rules
  A(b)@cell + B(a)@cell -> A(b!1)@cell.B(a!1)@cell k
end reaction rules
end model
"""

# Same source but with the volume declared as 0.5 fL. The correct count rate
# doubles to 2 s^-1, giving exp(-2) survival. This is the wrong-volume control:
# the exp(-1) acceptance bound must reject it.
HALF_VOLUME = COMPLETE_VOLUME.replace("Vc 1 [fL]", "Vc 0.5 [fL]").replace(
    "cell 3 Vc [fL]", "cell 3 Vc [fL]"
)


def test_missing_volume_refuses_for_its_specific_reason():
    model = cpp.parse_string(MISSING_VOLUME)
    with pytest.raises(
        RuntimeError,
        match="physical bimolecular rate requires one declared reactant volume unit",
    ):
        cpp.simulate_nfnext(model, [0.0, 1.0], seed=1)


def test_complete_volume_matches_independent_first_event_law():
    model = cpp.parse_string(COMPLETE_VOLUME)
    n = 512
    surviving = 0
    bound = 0
    for seed in range(n):
        result = cpp.simulate_nfnext(model, [0.0, 1.0], seed=seed)
        assert result["engine"] == "nfnext"
        surviving += int(result["observables"]["FreeA"][-1])
        bound += int(result["observables"]["BoundAB"][-1])
    p = math.exp(-1.0)
    se = math.sqrt(p * (1.0 - p) / n)
    # Fixed seed budget and a 5-sigma binomial bound. The doubled-rate
    # alternative (exp(-2)) is more than 10 sigma away at this budget.
    assert abs(surviving / n - p) <= 5.0 * se
    assert abs(p - math.exp(-2.0)) > 10.0 * se
    # FreeA and the bound complex are complementary for this one-event model.
    assert surviving + bound == n


def test_wrong_volume_is_outside_accepted_law():
    """The acceptance bound must reject a doubled-rate (halved-volume) model."""
    model = cpp.parse_string(HALF_VOLUME)
    n = 256
    surviving = 0
    for seed in range(n):
        surviving += int(
            cpp.simulate_nfnext(model, [0.0, 1.0], seed=seed)["observables"]["FreeA"][
                -1
            ]
        )
    p_wrong = math.exp(-2.0)
    se = math.sqrt(p_wrong * (1.0 - p_wrong) / n)
    # Observed survival must agree with the doubled-rate law, not exp(-1).
    assert abs(surviving / n - p_wrong) <= 5.0 * se
    assert abs(surviving / n - math.exp(-1.0)) > 5.0 * se


def test_listed_site_without_bond_notation_counts_only_free_species():
    """A(b) must match free A only, as in BNG2; A() counts all A.

    Regression for the NFnext observable lowering that previously treated an
    unspecified bond as a wildcard, so a bound A kept counting as free.
    """
    bngl = COMPLETE_VOLUME.replace(
        "  Molecules FreeA A(b)@cell\n",
        "  Molecules FreeA A(b)@cell\n  Molecules TotalA A()@cell\n",
    )
    model = cpp.parse_string(bngl)
    bound_seen = False
    for seed in range(64):
        result = cpp.simulate_nfnext(model, [0.0, 1.0], seed=seed)
        free = int(result["observables"]["FreeA"][-1])
        total = int(result["observables"]["TotalA"][-1])
        assert total == 1
        assert free in (0, 1)
        if free == 0:
            bound_seen = True
    assert bound_seen, "free-site observable never dropped after binding"
