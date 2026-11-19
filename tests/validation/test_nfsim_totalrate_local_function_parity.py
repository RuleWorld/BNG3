"""Pinned source-to-test parity case for NFsim Issue91 local-function TotalRate.

This is the focused, isolated case owned by the ``afad4086`` NFsim
reconciliation ledger entry.  It reduces the pinned source fixture
``test/testSuite/t3.xml`` (native Issue91 *local functions* TotalRate
rejection) to a self-contained counterexample and runs two explicit routes at
the accepted pin from ``provenance/upstreams.lock.yml``:

* baseline / upstream: the independently built native NFsim CLI on the frozen
  reduced XML, with explicit ``-xml/-o/-sim/-oSteps/-seed`` flags;
* candidate / product: the BNG3 public ``bionetgen.load(...).simulate``
  route with ``method="nf"`` and an explicit fixed seed on the reduced BNGL.

The reduced XML is byte-identical to the output of BNG3's XML writer for the
reduced BNGL at the recorded revision; it is frozen here so the native CLI's
input is stable and auditable.  Its local-function ``RateLaw`` has the same
``type="Function"`` / named-local-reference structure as the pinned source
``t3.xml`` fixture, which is checked below against the exact pinned bytes.

The assertion-free ``semantic_result`` property is intentional: the accepted
behavior differs, so this case records both outputs and classifies the
difference instead of asserting equality.  The ledger entry stays
``pending-port`` until the product behavior is aligned.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from tests.validation import compare, oracle_nfsim
from tests.validation.strict import require_oracle

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nfsim"
BNGL = FIXTURES / "localfunc_totalrate.bngl"
XML = FIXTURES / "localfunc_totalrate.xml"
BNGL_SHA256 = "b93b766175e41c7bf12db50a7752f586b0f40dd9acfac8a35e62af7febce8796"
XML_SHA256 = "73a45712e53e623edaa586d751d47f76acbbc93365b87b2aefc3be48996152f5"
SOURCE_REJECTION = "TotalRate keyword is not compatible with local functions"
# Pinned source fixture that defines the accepted behavior (Issue91).
SOURCE_FIXTURE = "test/testSuite/t3.xml"
SOURCE_RATE_LAW = 'id="RR9_RateLaw" type="Function" name="_rateLaw1"'
SOURCE_LOCAL_REF = '<Reference name="x" type="Local"/>'


@pytest.fixture
def pinned_nfsim_source():
    """The accepted NFsim source checkout and independently built oracle."""
    checkout = os.environ.get("BNG3_RECONCILIATION_NFSIM_SOURCE")
    native = oracle_nfsim.nfsim_binary()
    require_oracle(bool(checkout and native), "set the pinned NFsim source and binary")
    assert checkout is not None and native is not None
    root = Path(checkout).resolve()

    from scripts.ci.oracle_sources import load_lock, load_oracle_source

    lock = load_lock()
    source = load_oracle_source(lock, "nfsim")
    actual = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    assert actual == source["revision"]
    digest = hashlib.sha256(native.read_bytes()).hexdigest()
    assert "sha256:" + digest == lock["oracles"]["nfsim"]["artifact_digest"]
    return root, native, source["revision"], digest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_totalrate_local_function_source_rejects_product_executes(
    pinned_nfsim_source, api, tmp_path, monkeypatch, record_property
):
    """Classify the accepted-vs-product difference on the reduced case."""
    root, native, revision, digest = pinned_nfsim_source
    for path, expected in ((BNGL, BNGL_SHA256), (XML, XML_SHA256)):
        assert path.is_file(), f"missing reduced fixture: {path}"
        assert _sha256(path) == expected, f"reduced fixture changed: {path}"

    # Tie the reduced case to the pinned independent semantic fixture.
    source_xml = (root / SOURCE_FIXTURE).read_text(encoding="utf-8")
    assert SOURCE_RATE_LAW in source_xml
    assert SOURCE_LOCAL_REF in source_xml
    record_property("pinned_source_revision", revision)
    record_property("native_oracle_sha256", "sha256:" + digest)
    record_property("source_fixture", SOURCE_FIXTURE)
    record_property("source_fixture_sha256", hashlib.sha256(source_xml.encode()).hexdigest())
    record_property("reduced_bngl_sha256", BNGL_SHA256)
    record_property("reduced_xml_sha256", XML_SHA256)

    # --- baseline: upstream CLI, explicit flags and fixed seed -------------
    output = tmp_path / "upstream.gdat"
    run = subprocess.run(
        [
            str(native),
            "-xml",
            str(XML),
            "-o",
            str(output),
            "-sim",
            "1",
            "-oSteps",
            "1",
            "-seed",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    baseline_output = (run.stdout + run.stderr).strip()
    baseline_rejected = (not output.exists()) and SOURCE_REJECTION in baseline_output
    record_property("baseline_command", f"{native} -xml {XML} -o {output} -sim 1 -oSteps 1 -seed 1")
    record_property("baseline_returncode", run.returncode)
    record_property("baseline_produced_trajectory", output.exists())
    record_property("baseline_diagnostic", baseline_output)
    assert baseline_rejected, "reduced XML no longer reproduces the pinned rejection"

    if output.exists():
        values, columns = compare.parse_gdat(output)
        record_property(
            "baseline_endpoint",
            float(values[-1, columns.index("R0")]) if values is not None else None,
        )

    # --- candidate: BNG3 public route, explicit fixed seed ----------------
    monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")
    candidate = "rejected"
    candidate_detail = ""
    try:
        trajectory = api.load(str(BNGL)).simulate(
            method="nf", t_end=1, n_steps=1, seed=1
        )
    except (RuntimeError, ValueError) as error:  # pragma: no cover - diff branch
        candidate_detail = str(error)[:2000]
        record_property("candidate_result", "rejected")
    else:
        route = getattr(trajectory, "construction_path", None)
        candidate = "executed"
        record_property("candidate_result", candidate)
        record_property("candidate_construction_path", route)
    record_property("candidate_command", f"bionetgen.load({BNGL}).simulate(method='nf', t_end=1, n_steps=1, seed=1)")
    if candidate_detail:
        record_property("candidate_detail", candidate_detail)

    # The accepted behavior (reject) differs from the product (execute).
    matched = candidate == "rejected"
    record_property("semantic_result", "PASS" if matched else "FAIL")
    record_property(
        "classification",
        "agreement" if matched else "product-difference: oracle rejects, BNG3 executes",
    )
