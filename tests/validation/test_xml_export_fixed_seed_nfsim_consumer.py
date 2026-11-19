"""Detector: BNG3-exported BNG-XML fixed-seed fact at a native NFsim consumer.

Scope: ONE row-level fact for ``#163`` / ``action.writeXML``.  This is a
detector-only case; it does not close ``release-formats``,
``release-format-semantics`` or ``release-capability-coverage-163``.

The fact: a ``$``-prefixed seed species is exported as ``Fixed="1"`` and the
independently built native NFsim consumer keeps that population at its seeded
count even while a rule consumes it.  ``tests/python/test_nfsim_fixed_xml.py``
only inspects that XML attribute; no consumer-level assertion existed.
Because the fixed pool is an exact invariant, one fixed-seed trajectory is
enough -- no ensemble and no statistical tolerance.

Control: change one valid observable definition in a copy of the exported XML
(``Btot``'s pattern ``B()`` -> ``A()``).  The consumer must then report the
fixed pool under ``Btot`` instead of the growing product pool.

Reused utilities: ``oracle_nfsim`` (native binary discovery and run),
``compare`` (XML well-formedness and gdat parsing), ``strict.require_oracle``,
and ``scripts.ci.oracle_sources.load_lock`` (accepted pin).  The exported bytes
come from the public ``bionetgen.load(...).write_xml(...)`` path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.ci.oracle_sources import load_lock
from tests.validation import compare, oracle_nfsim
from tests.validation.strict import require_oracle

ROOT = Path(__file__).resolve().parents[2]

# Minimal, event-free model.  A is fixed at 5; the only rule consumes A into B.
# With the Fixed="1" export intact the A pool is replenished by the consumer,
# so Atot == 5 at every sample while Btot grows from 0.
SOURCE = """begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  $A() 5
  B() 0
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
end observables
begin reaction rules
  A() -> B() k
end reaction rules
end model
"""

FIXED_COUNT = 5.0
T_END = 5.0
N_STEPS = 10
SEED = 7
OBSERVABLES = ("Atot", "Btot")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pin(native: Path) -> tuple[str, str]:
    """Return (accepted source revision, native binary digest)."""
    lock = load_lock()
    expected = lock["sources"]["nfsim"]["revision"]
    root = native.parent.parent
    actual = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    assert (
        actual == expected
    ), f"native NFsim was not built from the accepted pin: {actual} != {expected}"
    return expected, hashlib.sha256(native.read_bytes()).hexdigest()


def _export(api, source: Path, out_xml: Path) -> Path:
    """Public exporter; assert the exact artifact exists before consuming it."""
    api.load(str(source)).write_xml(str(out_xml))
    assert out_xml.is_file(), f"writeXML produced no artifact: {out_xml}"
    return out_xml


def _assert_fixed_structure(xml: Path) -> None:
    """Structural preconditions on the exported bytes (not the semantic fact)."""
    ok, msg = compare.check_xml_wellformed(xml)
    assert ok, f"exported BNG-XML is not well-formed: {msg}"
    root = xml.read_text(encoding="utf-8")
    species = []
    for element in ET.fromstring(root).iter():
        if element.tag.rsplit("}", 1)[-1] != "Species":
            continue
        molecules = [
            child
            for child in element.iter()
            if child.tag.rsplit("}", 1)[-1] == "Molecule" and child.get("name") == "A"
        ]
        if molecules:
            species.append(element)
    assert species and all(
        s.get("Fixed") == "1" for s in species
    ), "exported BNG-XML did not mark the $-prefixed seed A() as Fixed=1"
    names = set(re.findall(r'<Observable\s+id="O\d+"\s+name="([^"]+)"', root))
    assert set(OBSERVABLES) <= names, f"exported observables missing: {names}"


def _run_consumer(xml: Path, work_dir: Path) -> tuple[dict[str, list[float]], str]:
    """Run the pinned native NFsim on the exact exported bytes."""
    gdat, error = oracle_nfsim.run_nfsim(
        xml, work_dir, t_end=T_END, n_steps=N_STEPS, seed=SEED
    )
    require_oracle(gdat is not None, f"native NFsim produced no trajectory: {error}")
    assert gdat is not None
    data, columns = compare.parse_gdat(gdat)
    require_oracle(
        data is not None and columns is not None,
        "native NFsim gdat could not be parsed",
    )
    assert data is not None and columns is not None
    for name in OBSERVABLES:
        assert name in columns, f"consumer did not report observable {name}: {columns}"
    return (
        {
            name: [float(v) for v in data[:, columns.index(name)]]
            for name in OBSERVABLES
        },
        str(gdat),
    )


@pytest.mark.export
@pytest.mark.nf
def test_exported_xml_fixed_seed_consumed_by_native_nfsim(
    api, tmp_path, record_property
):
    """Qualify one exported BNG-XML fact through the accepted native oracle."""
    native = oracle_nfsim.nfsim_binary()
    require_oracle(native is not None, "native NFsim binary not found (set NFSIM_BIN)")
    assert native is not None
    revision, binary_digest = _pin(native)

    source = tmp_path / "fixed_seed.bngl"
    source.write_text(SOURCE, encoding="utf-8")
    source_digest = _sha256(source)
    exported = _export(api, source, tmp_path / "fixed_seed.xml")
    xml_digest = _sha256(exported)
    _assert_fixed_structure(exported)

    baseline, baseline_gdat = _run_consumer(exported, tmp_path / "baseline")

    # The stated fact: fixed pool exact at every sample; product grows.
    assert all(value == FIXED_COUNT for value in baseline["Atot"]), baseline
    assert baseline["Btot"][0] == 0.0, baseline
    assert baseline["Btot"][-1] > 0.0, baseline

    # Control: change one valid observable definition in a copy of the exact
    # exported bytes.  The consumer must follow the new pattern.
    original = exported.read_text(encoding="utf-8")
    control_xml = tmp_path / "fixed_seed_control.xml"
    rewritten, substitutions = re.subn(
        r'(<Observable id="O2" name="Btot"[^>]*>\s*<ListOfPatterns>\s*'
        r'<Pattern[^>]*>\s*<ListOfMolecules>\s*<Molecule id="[^"]+" name=")B(")',
        r"\1A\2",
        original,
        count=1,
    )
    assert substitutions == 1, "could not change Btot's pattern in the exported XML"
    control_xml.write_text(rewritten, encoding="utf-8")
    assert _sha256(control_xml) != xml_digest

    control, control_gdat = _run_consumer(control_xml, tmp_path / "control")
    assert all(value == FIXED_COUNT for value in control["Btot"]), control
    assert control["Btot"][-1] != baseline["Btot"][-1], (baseline, control)

    command = (
        f"{native} -xml {exported} -o {Path(baseline_gdat).with_suffix('')}.gdat "
        f"-sim {T_END:g} -oSteps {N_STEPS} -seed {SEED}"
    )
    evidence = {
        "row": "action.writeXML",
        "issue": 163,
        "scope": "one exported BNG-XML fixed-seed fact; detector only",
        "bng3_revision": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip(),
        "nfsim_source_revision": revision,
        "nfsim_binary_sha256": binary_digest,
        "source_sha256": source_digest,
        "exported_xml_sha256": xml_digest,
        "control_xml_sha256": _sha256(control_xml),
        "command": command,
        "seed": SEED,
        "t_end": T_END,
        "n_steps": N_STEPS,
        "baseline_endpoint": {k: v[-1] for k, v in baseline.items()},
        "control_endpoint": {k: v[-1] for k, v in control.items()},
        "comparator": "Atot == 5 at every sample; Btot[0]==0 and Btot[-1]>0; "
        "control Btot == 5 and differs from baseline Btot[-1]",
        "result": "PASS",
    }
    for key, value in evidence.items():
        record_property(key, value)
    evidence_dir = os.environ.get("BNG3_XML_CONSUMER_EVIDENCE_DIR")
    if evidence_dir:
        target = Path(evidence_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "xml-consumer-evidence.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
