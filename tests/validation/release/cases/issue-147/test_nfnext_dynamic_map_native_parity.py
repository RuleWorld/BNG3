"""Pinned-native NFsim parity for the NFnext dynamic population-map conversion law.

The source map rule ``A(x~u) -> A_pop()`` with rate ``k*U()`` gives a pure-death
chain in the converted count: each of the U reactant embeddings fires at rate
``k*U``, so ``lambda(U) = k*U**2``.

The oracle is an independently written native NFsim encoding of that law: a
degradation rule ``A(x~u) -> 0`` whose global function is ``k*U`` (native NFsim
binds observables as muParser *variables*, ``Observable::addReferenceToMyself``
calls ``DefineVar(obsName, &count)``, so BNGL's ``U()`` spelling is rewritten to
``U``). The oracle is generated with the pinned BNG2 and executed with the
pinned native NFsim; no BNG3 output is used to build it. An absent oracle is
reported as NOT_TESTED (skip), never as a pass.
"""

from __future__ import annotations

import importlib.util
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.validation import oracle_perl
from tests.validation.strict import require_oracle

# Fresh local extension when present, matching the other NFnext tests.
build_so = (
    Path(__file__).resolve().parents[5]
    / "build"
    / "cpp"
    / "_bionetgen_cpp.cpython-314-darwin.so"
)
if "_bionetgen_cpp" in sys.modules:
    cpp = sys.modules["_bionetgen_cpp"]
elif build_so.exists():
    spec = importlib.util.spec_from_file_location("_bionetgen_cpp", str(build_so))
    cpp = importlib.util.module_from_spec(spec)
    sys.modules["_bionetgen_cpp"] = cpp
    assert spec.loader is not None
    spec.loader.exec_module(cpp)
else:
    import bionetgen._bionetgen_cpp as cpp

# NFnext subject model: the issue-147 dynamic population-map source.
_SUBJECT = Path(__file__).with_name("test_dynamic_population_map_rate.py").read_text()
MODEL = _SUBJECT.split('MODEL = """')[1].split('"""')[0]
EXEC_MODEL = MODEL.replace(
    "  Molecules U A(x~u)\n", "  Molecules U A(x~u)\n  Molecules P A_pop()\n"
)

# Independent native oracle source: same law, no population types (native NFsim
# models the conversion as removal of the counted particle).
ORACLE_MODEL = """begin model
begin parameters
  k 0.01
end parameters
begin molecule types
  A(x~u)
end molecule types
begin seed species
  A(x~u) 100
end seed species
begin observables
  Molecules U A(x~u)
end observables
begin functions
  rateFn() = k*U()
end functions
begin reaction rules
  R: A(x~u) -> 0 rateFn()
end reaction rules
end model
writeXML()
"""

K = 0.01
T = 1.0
RUNS = 512
SEED_BASE = 20261119


def _nfnext_ensemble():
    model = cpp.parse_string(EXEC_MODEL)
    values = []
    for i in range(RUNS):
        result = cpp.simulate_nfnext(model, [0.0, T], seed=SEED_BASE + i)
        assert result["engine"] == "nfnext"
        values.append(float(result["observables"]["U"][-1]))
    return values


def _native_ensemble(tmp_path, native_bin, bng2):
    source = tmp_path / "law.bngl"
    source.write_text(ORACLE_MODEL, encoding="utf-8")
    env = os.environ.copy()
    env["BNGPATH"] = str(bng2.parent)
    env["PERL5LIB"] = str(bng2.parent / "Perl2")
    subprocess.run(
        [
            os.environ.get("PERL", "perl"),
            str(bng2),
            "--outdir",
            str(tmp_path),
            str(source),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    xml = tmp_path / "law.xml"
    assert xml.is_file()
    # Native NFsim declares observables as variables named `U`, not functions
    # `U()`; this is a spelling translation, not a change to the rate law.
    native_xml = tmp_path / "law_native.xml"
    native_xml.write_text(
        xml.read_text(encoding="utf-8").replace("k*U()", "k*U"), encoding="utf-8"
    )
    samples = []
    for i in range(RUNS):
        out = tmp_path / f"native-{i}.gdat"
        subprocess.run(
            [
                str(native_bin),
                "-xml",
                str(native_xml),
                "-o",
                str(out),
                "-sim",
                str(T),
                "-oSteps",
                "2",
                "-seed",
                str(SEED_BASE + i),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        rows = [
            line.split()
            for line in out.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        assert rows and abs(float(rows[-1][0]) - T) < 1e-9
        samples.append(float(rows[-1][1]))
    return samples


def test_nfnext_dynamic_map_matches_pinned_native_nfsim(tmp_path):
    native = os.environ.get("NFSIM_BIN")
    bng2 = oracle_perl._bng2_path()
    require_oracle(
        bool(native) and Path(native).is_file(),
        "pinned native NFsim unavailable (set NFSIM_BIN)",
    )
    require_oracle(bng2 is not None, "pinned BNG2 unavailable (set BNG2_PERL)")
    assert native is not None and bng2 is not None

    nf = _nfnext_ensemble()
    nat = _native_ensemble(tmp_path, Path(native), bng2)

    mean_nf = sum(nf) / RUNS
    mean_nat = sum(nat) / RUNS
    var_nf = sum((v - mean_nf) ** 2 for v in nf) / (RUNS - 1)
    var_nat = sum((v - mean_nat) ** 2 for v in nat) / (RUNS - 1)
    se = math.sqrt(var_nf / RUNS + var_nat / RUNS)

    # Two-sample Kolmogorov-Smirnov distance. The DKW two-sample 95% threshold
    # for n=m=512 is about 0.084.
    sf, st = sorted(nf), sorted(nat)
    ks = max(
        abs(sum(1 for x in sf if x <= v) / RUNS - sum(1 for x in st if x <= v) / RUNS)
        for v in sf + st
    )
    assert abs(mean_nf - mean_nat) <= 4.0 * se, (
        f"NFnext {mean_nf:.4f} vs native NFsim {mean_nat:.4f} "
        f"(se={se:.4f}, KS={ks:.3f})"
    )
    assert ks <= 1.63 * math.sqrt(2.0 / RUNS), f"KS distance {ks:.3f} too large"
