"""Diagnostic: a dynamic population-map rate is valid BNG2 input that BNG3 refuses.

Refusal characterisation, NOT support evidence. Pinned BNG2 lowers a dynamic
population-map rate into an observable-dependent rate law on the generated map
rule; BNG3's NFIR lowering fails closed with an explicit refusal instead of
silently approximating it. This records the concrete unmet clause for #147/#150:
representation -> propensity -> conversion -> observables of a dynamic
population map is not yet lowered/executed. No expected value or tolerance is
normalised to BNG3 output.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

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


def test_bng3_fails_closed_on_dynamic_population_map_rate():
    """BNG3 refuses the construct explicitly; it is never silently approximated.

    The public entry point refuses un-lowered population maps. The dedicated
    dynamic-rate refusal lives in the NFIR lowering bridge
    (`cpp/nfnext/src/from_bng.cpp`: "dynamic population map rates with
    unresolvable static evaluation are not supported in NFIR lowering") and is
    covered by the native lowering-bridge architecture contract. What this check
    pins is that the valid BNG2 input above is not silently executed as an
    approximation: it fails closed with a population-map diagnostic.
    """
    model = cpp.parse_string(MODEL)
    assert model is not None
    with pytest.raises(RuntimeError, match="population map"):
        cpp.simulate_nfnext(model, [0.0, 1.0], seed=42)
