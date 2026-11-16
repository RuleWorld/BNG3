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

# With one A and one B in 1 fL, k / (N_A * V) = 1 s^-1.
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
end observables
begin reaction rules
  A(b)@cell + B(a)@cell -> A(b!1)@cell.B(a!1)@cell k
end reaction rules
end model
"""


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
    for seed in range(n):
        result = cpp.simulate_nfnext(model, [0.0, 1.0], seed=seed)
        assert result["engine"] == "nfnext"
        surviving += int(result["observables"]["FreeA"][-1])
    p = math.exp(-1.0)
    se = math.sqrt(p * (1.0 - p) / n)
    # Fixed budget and 5-sigma binomial bound; the doubled-rate alternative is
    # outside this bound even at the nearest allowed observed value.
    assert abs(surviving / n - p) <= 5.0 * se
    assert abs(p - math.exp(-2.0)) > 10.0 * se
