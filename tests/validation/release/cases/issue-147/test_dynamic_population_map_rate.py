"""Dynamic population-map rate: pinned BNG2 lowering and independent NFnext parity.

Pinned BNG2 lowers ``k_gather * U()`` into an observable-dependent rate law on
the generated map rule. NFnext now executes that rule: the observable is
re-evaluated after every conversion, so the converted count follows a pure-death
CTMC with ``lambda(n) = k_gather * n**2`` (the rate times n embeddings).

The expected mean comes from an independently written Gillespie SSA with its own
RNG, not from BNG3 output. A frozen-observable law (rate sampled once at its
initial value) is rejected as a discriminator. No expected value or tolerance is
normalised to BNG3 output.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import random
import subprocess

from tests.validation import oracle_perl
from tests.validation.strict import require_oracle

import bionetgen._bionetgen_cpp as cpp

MODEL = """begin model
begin parameters
  k_gather 0.01
end parameters
begin molecule types
  A(x~u)
end molecule types
begin population types
  A_pop()
end population types
begin seed species
  A(x~u) 100
end seed species
begin observables
  Molecules U A(x~u)
end observables
begin reaction rules
  A(x~u) -> A(x~u) k_gather
end reaction rules
begin population maps
  A(x~u) -> A_pop() k_gather * U()
end population maps
end model
"""


def test_bng2_lowers_dynamic_population_map_rate(tmp_path):
    """Pinned BNG2 accepts the source and emits an observable-dependent map rate."""
    bng2 = oracle_perl._bng2_path()
    require_oracle(bng2 is not None, "pinned BNG2 unavailable (set BNG2_PERL)")
    assert bng2 is not None
    source = tmp_path / "dyn_popmap.bngl"
    source.write_text(
        MODEL + '\ngenerate_hybrid_model({overwrite=>1, actions=>["writeXML()"]})\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["BNGPATH"] = str(bng2.parent)
    env["PERL5LIB"] = str(bng2.parent / "Perl2")
    proc = subprocess.run(
        [
            os.environ.get("PERL", "perl"),
            str(bng2),
            "--outdir",
            str(tmp_path),
            str(source),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    hybrid = tmp_path / "dyn_popmap_hpp.bngl"
    assert hybrid.is_file(), "BNG2 did not generate a hybrid BNGL"
    text = hybrid.read_text(encoding="utf-8")
    # The observable-dependent rate law survives BNG2's lowering and is attached
    # to the generated population-map rule: this is the required source semantics.
    assert "_rateLaw1() = k_gather*U()" in text
    assert "_MapRule0:  A(x~u) -> A_pop()  _rateLaw1()" in text


# Same source plus a population observable so conversions can be counted.
EXEC_MODEL = MODEL.replace(
    "  Molecules U A(x~u)\n", "  Molecules U A(x~u)\n  Molecules P A_pop()\n"
)
K = 0.01
N0 = 100
T = 1.0
RUNS = 512
SEED_BASE = 20261119


def _independent_ssa_mean():
    """Exact pure-death SSA for lambda(n) = K*n**2, written without BNG3 code."""
    rng = random.Random(0xC0FFEE)
    total = 0
    for _ in range(RUNS):
        n = N0
        t = 0.0
        while n > 0:
            rate = K * n * n
            t += rng.expovariate(rate)
            if t > T:
                break
            n -= 1
        total += n
    return total / RUNS


def _nfnext_ensemble():
    model = cpp.parse_string(EXEC_MODEL)
    assert model is not None
    values = []
    for i in range(RUNS):
        result = cpp.simulate_nfnext(model, [0.0, T], seed=SEED_BASE + i)
        assert result["engine"] == "nfnext"
        obs = result["observables"]
        u = float(obs["U"][-1])
        p = float(obs["P"][-1])
        # Whole-complex conversion conserves the converted material.
        assert abs(u + p - N0) < 1e-9, (u, p)
        values.append(u)
    mean = sum(values) / RUNS
    var = sum((v - mean) ** 2 for v in values) / (RUNS - 1)
    return mean, math.sqrt(var / RUNS)


def test_nfnext_dynamic_population_map_matches_independent_pure_death_ssa():
    """NFnext re-evaluates the map rate on every conversion."""
    nf_mean, nf_se = _nfnext_ensemble()
    ssa_mean = _independent_ssa_mean()
    # Fixed seeds make this reproducible; the independent SSA oracle has its
    # own small Monte-Carlo error, and a 4-sigma band on the NFnext ensemble
    # mean still separates the two laws at this budget.
    assert abs(nf_mean - ssa_mean) <= 4.0 * nf_se, (
        f"NFnext U(T)={nf_mean:.3f} vs independent SSA {ssa_mean:.3f} (se={nf_se:.3f})"
    )
    # Frozen-observable wrong law: U0 * exp(-k*U0*T) ~ 36.8, far below the
    # state-dependent pure-death law.
    frozen = N0 * math.exp(-K * N0 * T)
    assert nf_mean - frozen > 4.0 * nf_se, (
        f"NFnext {nf_mean:.3f} not separated from frozen-rate law {frozen:.3f}"
    )
