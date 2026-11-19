"""Executable port of the issue #167 Lean definitions (formal evaluation).

This is a line-by-line transcription of ``formal/lean/BNG/StochasticSemantics.lean``
using exact ``fractions.Fraction`` arithmetic.  It is the *formal* side of the
production-vs-formal comparison: propensities are rational numbers, never
floats, so an exact equality assertion is a real statement rather than a
tolerance.  No result here is used as an independent scientific oracle -- the
analytic master-equation law in ``test_stochastic_semantics.py`` is that oracle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional

Exact = Fraction


@dataclass(frozen=True)
class RateSpec:
    convention: str
    constants: tuple[Exact, ...]
    exponent: int = 1

    def rate_at(self, n: int) -> Optional[Exact]:
        """Mirror of ``RateSpec.rateAt``; the symmetry factor is NOT folded in."""
        c = self.constants
        nr = Exact(n)
        if (
            self.convention
            in {"elementaryParameter", "localFunction", "builtin", "tfun"}
            and len(c) == 1
        ):
            return c[0]
        if self.convention == "localFunctionState" and len(c) == 1:
            # A local function whose body depends on the current observable
            # count: its value is k * n and the multiplicity n still applies.
            return c[0] * nr
        if self.convention == "saturation" and len(c) == 2:
            kcat, K = c
            return None if K + nr == 0 else kcat / (K + nr)
        if self.convention == "hill" and len(c) == 2:
            # Hill(k,K,h) is the total hazard k*n^h/(K^h+n^h); return the
            # per-molecule base so the shared multiplicity n is not doubled.
            v, K = c
            den = K**self.exponent + nr**self.exponent
            if den == 0:
                return None
            if n == 0:
                return Exact(0)
            return v * nr ** (self.exponent - 1) / den
        if self.convention == "michaelisMenten" and len(c) == 2:
            v, K = c
            return None if K + nr == 0 else v / (K + nr)
        return None


@dataclass(frozen=True)
class Stoich:
    species: int
    count: int


@dataclass(frozen=True)
class State:
    counts: tuple[tuple[int, int], ...] = ()

    def count(self, species: int) -> int:
        return dict(self.counts).get(species, 0)

    def set_count(self, species: int, n: int) -> "State":
        d = dict(self.counts)
        d[species] = n
        return State(tuple(sorted(d.items())))

    def consume(self, edits) -> Optional["State"]:
        s = self
        for species, k in edits:
            available = s.count(species)
            if available < k:
                return None
            s = s.set_count(species, available - k)
        return s

    def produce(self, edits) -> "State":
        s = self
        for species, k in edits:
            s = s.set_count(species, s.count(species) + k)
        return s


@dataclass(frozen=True)
class Channel:
    id: int
    rate: RateSpec
    reactants: tuple[Stoich, ...] = ()
    products: tuple[Stoich, ...] = ()
    symmetry_factor: int = 1
    total_rate: bool = False
    match_once: bool = False
    delay: Optional[Exact] = None
    energy_factor: Optional[int] = None
    gated: bool = True

    def raw_multiplicity(self, s: State) -> int:
        # Ordered embeddings n(n-1)..., matching Lean fallingFactorial.
        out = 1
        for r in self.reactants:
            n = s.count(r.species)
            for i in range(r.count):
                out *= n - i
        return out

    def multiplicity(self, s: State) -> int:
        if self.symmetry_factor == 0:
            return 0
        return self.raw_multiplicity(s) // self.symmetry_factor

    def primary_count(self, s: State) -> int:
        return s.count(self.reactants[0].species) if self.reactants else 0

    def enabled(self, s: State) -> bool:
        return self.gated and all(s.count(r.species) >= r.count for r in self.reactants)

    def energy_multiplier(self) -> int:
        return 1 if self.energy_factor is None else self.energy_factor

    def exact_propensity(self, s: State) -> Exact:
        if not self.enabled(s):
            return Exact(0)
        base = self.rate.rate_at(self.primary_count(s))
        base = Exact(0) if base is None else base
        mult = 1 if self.total_rate else self.multiplicity(s)
        return base * mult * self.energy_multiplier()

    def apply_state_update(self, s: State) -> Optional[State]:
        mid = s.consume([(r.species, r.count) for r in self.reactants])
        return (
            None
            if mid is None
            else mid.produce([(p.species, p.count) for p in self.products])
        )


def raw_embeddings(s: State, reactants) -> int:
    """Ordered embeddings n(n-1)... before the symmetry factor (Lean
    ``fallingFactorial`` product).  Used to check the production factor."""
    out = 1
    for r in reactants:
        n = s.count(r.species)
        for i in range(r.count):
            out *= n - i
    return out


def total_propensity(channels, s: State) -> Exact:
    return sum((ch.exact_propensity(s) for ch in channels), Exact(0))


def next_channel_prob(channels, s: State, channel_id: int) -> Exact:
    total = total_propensity(channels, s)
    if total == 0:
        return Exact(0)
    return (
        next(
            (ch.exact_propensity(s) for ch in channels if ch.id == channel_id), Exact(0)
        )
        / total
    )


@dataclass
class Case:
    """One enumerated issue #167 rate-convention slice."""

    id: str
    convention: str
    constants: tuple[Exact, ...]
    exponent: int
    n0: int
    k: Exact
    reactants: tuple[Stoich, ...]
    products: tuple[Stoich, ...]
    symmetry_factor: int
    rate_law_symbol: str
    bngl_rate: str
    extra_bngl: str = ""
    distribution_supported: bool = True

    def formal_channel(self) -> Channel:
        return Channel(
            id=0,
            rate=RateSpec(self.convention, self.constants, self.exponent),
            reactants=self.reactants,
            products=self.products,
            symmetry_factor=self.symmetry_factor,
        )

    def initial_state(self) -> State:
        if self.reactants:
            return State(
                ((self.reactants[0].species, self.n0), (self.products[0].species, 0))
            )
        return State(((self.products[0].species, 0),))


K = Exact(4, 10)  # 0.4, named `k` in every n20-k04 case
KM = Exact(10)
HILL_EXP = 2

CASES = (
    Case(
        id="parameter-n20-k04",
        convention="elementaryParameter",
        constants=(K,),
        exponent=1,
        n0=20,
        k=K,
        reactants=(Stoich(0, 1),),
        products=(Stoich(1, 1),),
        symmetry_factor=1,
        rate_law_symbol="k",
        bngl_rate="k",
    ),
    Case(
        id="local-function-n20-k04",
        convention="localFunction",
        constants=(K,),
        exponent=1,
        n0=20,
        k=K,
        reactants=(Stoich(0, 1),),
        products=(Stoich(1, 1),),
        symmetry_factor=1,
        rate_law_symbol="f()",
        bngl_rate="f()",
        extra_bngl="begin functions\n  f() = k\nend functions\n",
    ),
    Case(
        id="local-function-state-n20-k04",
        convention="localFunctionState",
        constants=(K,),
        exponent=1,
        n0=20,
        k=K,
        reactants=(Stoich(0, 1),),
        products=(Stoich(1, 1),),
        symmetry_factor=1,
        rate_law_symbol="f()",
        bngl_rate="f()",
        extra_bngl="begin functions\n  f() = k*nA\nend functions\n",
    ),
    Case(
        id="builtin-n20-k04",
        convention="builtin",
        constants=(K,),
        exponent=1,
        n0=20,
        k=K,
        reactants=(Stoich(0, 1),),
        products=(Stoich(1, 1),),
        symmetry_factor=1,
        rate_law_symbol="abs(k)",
        bngl_rate="abs(k)",
    ),
    Case(
        id="tfun-n20-k04",
        convention="tfun",
        constants=(K,),
        exponent=1,
        n0=20,
        k=K,
        reactants=(Stoich(0, 1),),
        products=(Stoich(1, 1),),
        symmetry_factor=1,
        rate_law_symbol="TFUN(time,",
        bngl_rate='TFUN(time, "rates.dat")',
        extra_bngl='begin functions\n  f() = TFUN(time, "rates.dat")\nend functions\n',
        distribution_supported=False,  # time-dependent functional rate: SSA refuses by contract
    ),
    Case(
        id="saturation-n20-k04",
        convention="saturation",
        constants=(K, KM),
        exponent=1,
        n0=20,
        k=K,
        reactants=(Stoich(0, 1),),
        products=(Stoich(1, 1),),
        symmetry_factor=1,
        rate_law_symbol="Sat(k, K)",
        bngl_rate="Sat(k,K)",
    ),
    Case(
        id="hill-n20-k04",
        convention="hill",
        constants=(K, KM),
        exponent=HILL_EXP,
        n0=20,
        k=K,
        reactants=(Stoich(0, 1),),
        products=(Stoich(1, 1),),
        symmetry_factor=1,
        rate_law_symbol="Hill(k, K, n)",
        bngl_rate="Hill(k,K,n)",
    ),
    Case(
        id="elementary-bimolecular-n20-k04",
        convention="elementaryParameter",
        constants=(K,),
        exponent=1,
        n0=20,
        k=K,
        reactants=(Stoich(0, 2),),
        products=(Stoich(1, 1),),
        symmetry_factor=2,
        rate_law_symbol="k",
        bngl_rate="k",
    ),
)


def bngl_for(case: Case) -> str:
    return (
        "begin model\n"
        "begin parameters\n"
        "  k 0.4\n  K 10\n  n 2\n"
        "end parameters\n"
        "begin molecule types\n  A()\n  B()\nend molecule types\n"
        "begin seed species\n  A() 20\nend seed species\n"
        "begin observables\n  Molecules nA A()\n  Molecules nB B()\nend observables\n"
        + case.extra_bngl
        + "begin reaction rules\n"
        + ("  A() + A() -> B() " if case.symmetry_factor == 2 else "  A() -> B() ")
        + case.bngl_rate
        + "\nend reaction rules\nend model\n"
    )


CASES_BY_ID = {c.id: c for c in CASES}
