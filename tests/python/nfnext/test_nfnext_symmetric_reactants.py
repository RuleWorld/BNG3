"""Independent qualification of the BNG2 combinatorial factor for identical reactants.

BNG2 2.9.3 lowers ``A(b) + A(b) -> A(b!1).A(b!1)`` to a net reaction with rate
``0.5*k`` and reactants ``1,1``: the propensity is ``k*C(A,2)``. A previous
NFnext lowering enumerated ordered embeddings and used ``k*A*(A-1)``, i.e. a
2x overcount for the symmetric product. The asymmetric product case
``A(x~u) + A(x~u) -> A(x~p) + A(x~u)`` keeps BNG2 rate ``k`` (two product
channels) and must NOT receive the factor.
"""

import math

import bionetgen._bionetgen_cpp as cpp

SYMMETRIC = """begin model
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
end molecule types
begin seed species
  A(b)@cell 2
end seed species
begin observables
  Molecules FreeA A(b)@cell
  Molecules AA A(b!1)@cell.A(b!1)@cell
end observables
begin reaction rules
  A(b)@cell + A(b)@cell -> A(b!1)@cell.A(b!1)@cell k
end reaction rules
end model
"""

ASYMMETRIC = """begin model
begin parameters
  k 2.0
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 2
end seed species
begin observables
  Molecules U A(x~u)
  Molecules P A(x~p)
end observables
begin reaction rules
  A(x~u) + A(x~u) -> A(x~p) + A(x~u) k
end reaction rules
end model
"""


def _survival(model, observable, threshold, n, t=1.0):
    survived = 0
    for seed in range(n):
        result = cpp.simulate_nfnext(model, [0.0, t], seed=seed)
        survived += int(result["observables"][observable][-1] == threshold)
    return survived


def test_symmetric_identical_reactants_use_combinatorial_factor():
    """A+A -> A.A with 2 molecules: hazard k/(N_A V)=1, survival exp(-1)."""
    model = cpp.parse_string(SYMMETRIC)
    n = 512
    survived = _survival(model, "FreeA", 2, n)
    p = math.exp(-1.0)
    se = math.sqrt(p * (1.0 - p) / n)
    assert abs(survived / n - p) <= 5.0 * se
    # The ordered-pair (2x) implementation is more than 10 sigma away.
    assert abs(p - math.exp(-2.0)) > 10.0 * se


def test_asymmetric_products_keep_ordered_pair_count():
    """A+A -> A(p)+A(u) has two product channels: BNG2 net rate k, not 0.5k."""
    model = cpp.parse_string(ASYMMETRIC)
    n = 512
    # k=2, A=2 -> hazard k*A*(A-1) = 4, so exp(-4) survive with U=2.
    survived = _survival(model, "U", 2, n)
    p = math.exp(-4.0)
    se = math.sqrt(p * (1.0 - p) / n)
    assert abs(survived / n - p) <= 5.0 * se
    # A wrongly-applied 0.5 factor gives exp(-2), far outside the bound.
    assert abs(math.exp(-2.0) - p) > 10.0 * se
