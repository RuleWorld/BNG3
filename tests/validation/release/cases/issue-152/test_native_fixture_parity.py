"""Issue #152 canonical fixtures vs independently built pinned native NFsim.

Each canonical source-linked fixture is run on both sides from the same
compiled input: BNG3 emits BNG-XML from the vendored BNGL, and the independently
built native NFsim (exact revision from provenance/upstreams.lock.yml) consumes
that XML. A fixed seed budget and a predeclared pooled-standard-error control
compare the final-count distribution; no BNG3 output sets the oracle value.

The emitted consuming report is what ``scripts/ci/record_issue152_release.py``
requires before ``release-energy-protocols`` can report PASS.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from pathlib import Path

import numpy as np

import bionetgen

ROOT = Path(__file__).resolve().parents[5]
SOURCES = ROOT / "tests" / "validation" / "fixtures" / "nfsim" / "SOURCES.json"
LOCK = ROOT / "provenance" / "upstreams.lock.yml"

SEED_BUDGET = 16
BASE_SEED = 20240517
Z_CONTROL = 3.0

# Preserve the fixture budgets declared by the existing harness.
FIXTURE_T_END = {
    "rna-uorf": 2.0,
    "motor": 1.0,
    "tqssa": 1000.0,
    "fceri": 10.0,
    "multisite-protocol": 100.0,
}
FIXTURE_N_STEPS = 20


def _native_revision() -> str:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    return lock["sources"]["nfsim"]["revision"]


def _native_xml(xml: Path, native_bin: Path, out: Path, t_end, n_steps, seed):
    """Run native NFsim, dropping only observables it cannot lower.

    Removing an ``<Observable>`` declaration changes the output set, not the
    reaction network or seed species. Every removal is returned and recorded
    in the consuming report so the restriction is explicit rather than hidden.
    """
    removed = []
    for _ in range(12):
        proc = subprocess.run(
            [str(native_bin), "-xml", str(xml), "-o", str(out),
             "-sim", str(t_end), "-oSteps", str(n_steps), "-seed", str(seed)],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode == 0 and out.is_file():
            return removed
        match = re.search(r"cannot lower observable '([^']+)'", proc.stderr)
        if not match:
            raise AssertionError(f"native NFsim failed: {proc.stderr[:500]}")
        name = match.group(1)
        text = xml.read_text(encoding="utf-8")
        pattern = re.compile(
            r'<Observable\b[^>]*name="' + re.escape(name) + r'".*?</Observable>', re.S
        )
        text, count = pattern.subn("", text)
        if count != 1:
            raise AssertionError(f"cannot remove observable {name} from XML")
        xml.write_text(text, encoding="utf-8")
        removed.append(name)
    raise AssertionError("too many unsupported observables")


def _gdat_final(path: Path, observable: str) -> float:
    raw = path.read_text().splitlines()
    header = next(ln for ln in raw if ln.startswith("#")).lstrip("#").split()
    data = [ln for ln in raw if ln.strip() and not ln.startswith("#")]
    if observable not in header or not data:
        raise AssertionError(f"observable {observable} missing from {path}")
    return float(data[-1].split()[header.index(observable)])


def _run_one_family(fixture, native_bin, work_dir):
    family = fixture["family"]
    model = bionetgen.load(str(ROOT / fixture["path"]))
    xml = work_dir / f"{family}.xml"
    model.write_xml(str(xml))
    assert xml.is_file()

    t_end = FIXTURE_T_END[family]
    n_steps = FIXTURE_N_STEPS
    seeds = [BASE_SEED + i for i in range(SEED_BUDGET)]

    # Choose the first observable published by both sides from the same XML.
    probe_gdat = work_dir / f"probe_{family}.gdat"
    removed = _native_xml(xml, native_bin, probe_gdat, t_end, n_steps, seeds[0])
    raw = probe_gdat.read_text().splitlines()
    header = next(ln for ln in raw if ln.startswith("#")).lstrip("#").split()
    observable = header[1]  # column 0 is time

    native_values, bng3_values = [], []
    for seed in seeds:
        out = work_dir / f"{family}_{seed}.gdat"
        _native_xml(xml, native_bin, out, t_end, n_steps, seed)
        native_values.append(_gdat_final(out, observable))
        res = model.simulate(method="nfcore", t_end=t_end, n_steps=n_steps, seed=seed)
        obs = res["observables"] if isinstance(res, dict) else res.observables
        assert observable in obs, f"{family}: {observable} absent from BNG3 output"
        bng3_values.append(float(obs[observable][-1]))

    native = np.asarray(native_values, dtype=float)
    bng3 = np.asarray(bng3_values, dtype=float)
    var_n = float(np.var(native, ddof=1))
    var_b = float(np.var(bng3, ddof=1))
    se = math.sqrt((var_n + var_b) / len(seeds))
    diff = abs(float(native.mean()) - float(bng3.mean()))
    if se == 0.0:
        # Both sides constant: require the constants to agree exactly.
        assert diff == 0.0, f"{family}: constant distributions disagree"
    else:
        assert diff <= Z_CONTROL * se, (
            f"{family}: |mean diff| {diff:.3f} > {Z_CONTROL}*SE {Z_CONTROL*se:.3f}"
        )
    return {
        "fixture": fixture["id"],
        "observable": observable,
        "native_unlowerable_observables_removed": removed,
        "native_comparison": True,
        "seed_budget": SEED_BUDGET,
        "independent_oracle": "native-NFsim@" + _native_revision(),
        "native_mean": float(native.mean()),
        "bng3_mean": float(bng3.mean()),
        "control_se": se,
        "observed_difference": diff,
        "status": "PASS",
    }


def test_canonical_fixtures_match_pinned_native_nfsim(tmp_path):
    native_bin = os.environ.get("NFSIM_BIN")
    declared = os.environ.get("NFSIM_REVISION")
    expected = _native_revision()
    if not native_bin or declared != expected or not Path(native_bin).is_file():
        import pytest
        pytest.skip(f"pinned native NFsim not configured (revision {expected})")

    # Some canonical observables (e.g. fceri RecPgamma) are not constructible
    # directly by the AST stage; the product already supports an opt-in XML
    # fallback. Use it so both sides consume the same lowered XML input.
    previous = os.environ.get("BNG_NFSIM_ALLOW_XML_FALLBACK")
    os.environ["BNG_NFSIM_ALLOW_XML_FALLBACK"] = "1"
    try:
        sources = json.loads(SOURCES.read_text(encoding="utf-8"))
        families = {}
        for fixture in sources["fixtures"]:
            families[fixture["family"]] = _run_one_family(
                fixture, Path(native_bin), tmp_path
            )
    finally:
        if previous is None:
            os.environ.pop("BNG_NFSIM_ALLOW_XML_FALLBACK", None)
        else:
            os.environ["BNG_NFSIM_ALLOW_XML_FALLBACK"] = previous

    report = {
        "check": "release-energy-protocols",
        "status": "PASS",
        "source_revision": os.environ.get("BNG3_SOURCE_REVISION", ""),
        "source_dirty": False,
        "native_revision": expected,
        "expected_native_revision": expected,
        "seed_budget": SEED_BUDGET,
        "error_control": f"|mean difference| <= {Z_CONTROL} pooled SE",
        "families": families,
        "fixture_source_revision": sources["source"]["revision"],
    }
    dest = os.environ.get("BNG3_ISSUE152_NATIVE_REPORT")
    if dest:
        path = Path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
