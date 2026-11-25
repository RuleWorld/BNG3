"""Positive and negative controls for #471 batch-2 (analytic, CRN, BNGsim) receipts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

CASE_DIR = Path(__file__).resolve().parent
ROOT = CASE_DIR.parents[4]
sys.path.insert(0, str(CASE_DIR))
sys.path.insert(0, str(ROOT))

import issue471_checks as checks  # noqa: E402
import test_record_issue471_bng2_receipts as base_fixture  # noqa: E402
from scripts.ci import record_issue471_bngsim_receipt as bngsim_rec  # noqa: E402
from scripts.ci import record_issue471_crn_receipt as crn_rec  # noqa: E402


@pytest.mark.parametrize(
    ("oracle_json", "consumer_json", "expect_ok"),
    [
        ('{"kf": 1.0, "kr": 2.0}', '{"kf": 1.0, "kr": 2.0000000001}', True),
        ('{"kf": 1.0, "kr": 2.0}', '{"kf": 1.0, "kr": 2.5}', False),
        ('{"kf": 1.0}', '{"kf": 1.0, "kr": 2.0}', False),
        ('{"kf": true}', '{"kf": true}', False),
        ('{"kf": 1.0}', '{"kf": "1.0"}', False),
    ],
)
def test_numeric_json_comparator_controls(
    oracle_json: str, consumer_json: str, expect_ok: bool
):
    ok, detail = checks._compare_numeric_json_bytes(
        oracle_json.encode("utf-8"), consumer_json.encode("utf-8")
    )
    assert ok is expect_ok, detail


def test_crn_bng2_comparator_controls():
    oracle_net = (
        "begin species\n"
        "  1 A() 10\n"
        "  2 B() 0\n"
        "end species\n"
        "begin reactions\n"
        "  1 1 2 k1 #make\n"
        "end reactions\n"
    ).encode("utf-8")
    valid_crn = json.dumps(
        {
            "species": [{"name": "A()"}, {"name": "B()"}],
            "complexes": [{"species": [0]}, {"species": [1]}],
            "stoichiometric_matrix": [[-1], [1]],
            "reactions": [
                {
                    "reactants": [0],
                    "products": [1],
                    "rate_law": {"rule_name": "make", "expression": "k1"},
                }
            ],
        }
    ).encode("utf-8")
    ok, detail = checks._compare_crn_bng2_bytes(oracle_net, valid_crn)
    assert ok, detail

    tampered = json.loads(valid_crn)
    tampered["stoichiometric_matrix"] = [[1], [-1]]
    ok_bad, _ = checks._compare_crn_bng2_bytes(
        oracle_net, json.dumps(tampered).encode("utf-8")
    )
    assert not ok_bad


def test_analytic_oracle_rejects_spec_digest_tamper_and_missing_law(tmp_path: Path):
    spec = tmp_path / "docs/nonequilibrium_energy.md"
    spec.parent.mkdir(parents=True)
    spec_bytes = b"# Energy spec\n"
    spec.write_bytes(spec_bytes)
    import hashlib

    spec_sha = hashlib.sha256(spec_bytes).hexdigest()
    art = tmp_path / "artifacts"
    (art / "energy.barriers").mkdir(parents=True)
    p_bytes = b"begin model\nend model\n"
    o_bytes = b'{"kf": 0.5}\n'
    c_bytes = b'{"kf": 0.5}\n'
    (art / "energy.barriers/producer.bngl").write_bytes(p_bytes)
    (art / "energy.barriers/oracle.json").write_bytes(o_bytes)
    (art / "energy.barriers/consumer.json").write_bytes(c_bytes)
    row = {
        "id": "energy.barriers",
        "status": "implemented",
        "oracle": "analytic rate ratios and detailed balance",
    }
    rev = "a" * 40
    receipt = {
        "schema_version": 2,
        "kind": "release-oracle-consumer-receipt",
        "capability_id": "energy.barriers",
        "check_id": "release-capability[energy.barriers]",
        "comparator": "release-oracle-numeric-json-v1",
        "source_revision": rev,
        "product_revision": rev,
        "oracle": {
            "name": "Analytic closed-form evaluation",
            "revision": spec_sha,
            "spec_path": "docs/nonequilibrium_energy.md",
            "spec_sha256": spec_sha,
            "law": "k_f = exp(-(Ea+B+phi*dG))",
            "path": "energy.barriers/oracle.json",
            "artifact_sha256": hashlib.sha256(o_bytes).hexdigest(),
            "executable_sha256": "1" * 64,
            "command": "python record_issue471_analytic_receipts.py",
            "expected_origin": "analytic-derivation",
            "execution": {
                "executable": "python",
                "version": "3.12",
                "command": "analytic",
                "exit_code": 0,
            },
        },
        "producer": {
            "path": "energy.barriers/producer.bngl",
            "output_sha256": hashlib.sha256(p_bytes).hexdigest(),
        },
        "consumer": {
            "path": "energy.barriers/consumer.json",
            "output_sha256": hashlib.sha256(c_bytes).hexdigest(),
            "consumed_producer_sha256": hashlib.sha256(p_bytes).hexdigest(),
            "execution": {
                "executable": "cpp",
                "version": "1",
                "command": "cpp",
                "exit_code": 0,
            },
        },
    }
    errors, comp = checks._oracle_receipt_errors(row, receipt, rev, art, tmp_path)
    assert errors == []
    assert comp is not None and comp["consumer_equals_oracle"] is True

    # Tampered spec bytes must fail fail-closed.
    spec.write_bytes(b"# Altered spec\n")
    errors_tamper, _ = checks._oracle_receipt_errors(row, receipt, rev, art, tmp_path)
    assert any("specification bytes" in e for e in errors_tamper)


def test_bngsim_receipt_rejects_mismatched_bngsim_pin(tmp_path: Path):
    repo, rev, _, bng2_root, _ = base_fixture._setup_fixture(tmp_path)
    bngsim_root = tmp_path / "oracle-bngsim"
    bngsim_rev = base_fixture._init_repo(bngsim_root, {"README.md": "bngsim"})
    lock_path = repo / "provenance/upstreams.lock.yml"
    lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_data["sources"]["bngsim"] = {"revision": bngsim_rev, "status": "accepted"}
    lock_path.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")
    base_fixture._git(repo, "add", "provenance/upstreams.lock.yml")
    base_fixture._git(repo, "commit", "-qm", "pin mock bngsim")
    rev = base_fixture._git(repo, "rev-parse", "HEAD")

    # Wrong bngsim checkout revision must fail immediately before running anything.
    wrong_bngsim = tmp_path / "wrong-bngsim"
    base_fixture._init_repo(wrong_bngsim, {"README.md": "wrong"})
    with pytest.raises(ValueError, match="pinned bngsim checkout mismatch"):
        bngsim_rec.build_bngsim_receipt(
            root=repo,
            revision=rev,
            bng2_root=bng2_root,
            bngsim_root=wrong_bngsim,
            receipts_dir=tmp_path / "r",
            artifacts_dir=tmp_path / "a",
        )
    # Also ensure crn_rec rejects dirty tree when allow_dirty=False.
    (repo / "untracked.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(ValueError, match="clean revision"):
        crn_rec.build_crn_receipt(
            root=repo,
            revision=rev,
            bng2_root=bng2_root,
            receipts_dir=tmp_path / "r2",
            artifacts_dir=tmp_path / "a2",
        )


def test_hybrid_bngl_and_xml_comparators_enforce_semantic_parity():
    ref_bngl = (
        b"# Created by BioNetGen 2.9.3\n"
        b"begin model\n"
        b"begin parameters\n  k 0.5\nend parameters\n"
        b"begin molecule types\n  A()\n  A_pop() population\n  B()\nend molecule types\n"
        b"begin observables\n  Molecules A_obs A() A_pop()\nend observables\n"
        b"begin species\n  A_pop() 10\nend species\n"
        b"begin reaction rules\n  R1_v1: A_pop() -> B() k\nend reaction rules\n"
        b"end model\n## model actions ##\nwriteXML()\n"
    )
    sub_bngl_ok = (
        b"# Generated by BioNetGen C++\n"
        b"begin model\n"
        b"begin parameters\n  k 0.50\nend parameters\n"
        b"begin molecule types\n  A\n  A_pop population\n  B\nend molecule types\n"
        b"begin seed species\n  A_pop() 10.0\nend seed species\n"
        b"begin observables\n  Molecules A_obs A(),A_pop()\nend observables\n"
        b"begin reaction rules\n  R1_v1: A_pop() -> B() k\nend reaction rules\n"
        b"end model\n## model actions ##\nwriteXML()\n"
    )
    assert checks._compare_hybrid_bngl_bytes(ref_bngl, sub_bngl_ok) == (True, "")
    assert (
        checks._compare_hybrid_bngl_bytes(
            ref_bngl, sub_bngl_ok.replace(b"A_pop population", b"A_pop")
        )[0]
        is False
    )
    assert (
        checks._compare_hybrid_bngl_bytes(
            ref_bngl, sub_bngl_ok.replace(b"k 0.50", b"k 0.75")
        )[0]
        is False
    )
    assert (
        checks._compare_hybrid_bngl_bytes(
            ref_bngl, sub_bngl_ok.replace(b"writeXML()", b"")
        )[0]
        is False
    )

    ref_xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<sbml xmlns="http://www.sbml.org/sbml/level3" level="3" version="1"><model id="probe_hpp">'
        b'<ListOfParameters><Parameter id="k" type="Constant" value="0.5"/></ListOfParameters>'
        b'<ListOfMoleculeTypes><MoleculeType id="A_pop" population="1"/></ListOfMoleculeTypes>'
        b'<ListOfSpecies><Species id="S1" concentration="10" name="A_pop()">'
        b'<ListOfMolecules><Molecule id="S1_M1" name="A_pop"/></ListOfMolecules></Species></ListOfSpecies>'
        b'<ListOfReactionRules><ReactionRule id="RR1" name="R1_v1">'
        b'<ListOfReactantPatterns><ReactantPattern id="RP1"><ListOfMolecules><Molecule id="M1" name="A_pop"/></ListOfMolecules></ReactantPattern></ListOfReactantPatterns>'
        b'<ListOfProductPatterns><ProductPattern id="PP1"><ListOfMolecules><Molecule id="M2" name="B"/></ListOfMolecules></ProductPattern></ListOfProductPatterns>'
        b'<RateLaw id="RL" type="Ele" totalrate="0"><ListOfRateConstants><RateConstant value="k"/></ListOfRateConstants></RateLaw>'
        b'<ListOfOperations><Add id="M2"/><Delete id="RP1" DeleteMolecules="0"/></ListOfOperations>'
        b"</ReactionRule></ListOfReactionRules>"
        b'<ListOfObservables><Observable id="O1" name="A_obs" type="Molecules">'
        b'<ListOfPatterns><Pattern id="P1"><ListOfMolecules><Molecule id="OM1" name="A_pop"/></ListOfMolecules></Pattern></ListOfPatterns>'
        b"</Observable></ListOfObservables></model></sbml>"
    )
    sub_xml_ok = ref_xml.replace(b'model id="probe_hpp"', b'model id=""').replace(
        b'value="0.5"', b'value="0.50"'
    )
    assert checks._compare_bngl_xml_bytes(ref_xml, sub_xml_ok) == (True, "")
    assert (
        checks._compare_bngl_xml_bytes(
            ref_xml, sub_xml_ok.replace(b'population="1"', b'population="0"')
        )[0]
        is False
    )
    assert (
        checks._compare_bngl_xml_bytes(
            ref_xml, sub_xml_ok.replace(b'DeleteMolecules="0"', b'DeleteMolecules="1"')
        )[0]
        is False
    )
    assert checks._compare_bngl_xml_bytes(ref_xml, b"<not-valid-xml")[0] is False


def test_bngsim_receipt_loads_pure_model_without_actions(tmp_path: Path, monkeypatch):
    repo, rev, _, bng2_root, _ = base_fixture._setup_fixture(tmp_path)
    bngsim_root = tmp_path / "oracle-bngsim"
    bngsim_rev = base_fixture._init_repo(bngsim_root, {"README.md": "bngsim"})
    lock_path = repo / "provenance/upstreams.lock.yml"
    lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_data["sources"]["bngsim"] = {"revision": bngsim_rev, "status": "accepted"}
    lock_path.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")
    script = bng2_root / "bng2/BNG2.pl"
    script.write_text(
        """#!/usr/bin/env perl
use strict;
use warnings;
my ($outdir, $file);
for (my $i = 0; $i < @ARGV; $i++) {
    if ($ARGV[$i] eq '--outdir') { $outdir = $ARGV[++$i]; }
    else { $file = $ARGV[$i]; }
}
open(my $in, '<', $file) or die $!;
local $/; my $txt = <$in>; close($in);
die "missing simulate action" unless $txt =~ /simulate\\(/;
open(my $out, '>', "$outdir/bngsim_ode.gdat") or die $!;
print $out "# time Aobs Bobs\\n0 100 0\\n2 60 40\\n";
close($out);
exit 0;
""",
        encoding="utf-8",
    )
    base_fixture._git(bng2_root, "add", "bng2/BNG2.pl")
    base_fixture._git(bng2_root, "commit", "-qm", "mock bng2 gdat")
    lock_data["sources"]["bionetgen"]["revision"] = base_fixture._git(
        bng2_root, "rev-parse", "HEAD"
    )
    lock_path.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")
    base_fixture._git(repo, "add", "provenance/upstreams.lock.yml")
    base_fixture._git(repo, "commit", "-qm", "pin mock oracles")
    rev = base_fixture._git(repo, "rev-parse", "HEAD")

    class _FakeResult:
        time = [0.0, 2.0]
        observables = {"Aobs": [100.0, 60.0], "Bobs": [0.0, 40.0]}

    class _FakeModel:
        def simulate(self, **kwargs):
            assert kwargs["method"] == "ode"
            assert kwargs["backend"] == "bngsim"
            return _FakeResult()

    loaded_texts: list[str] = []

    class _FakeBionetgen:
        @staticmethod
        def load(path: Path):
            txt = Path(path).read_text(encoding="utf-8")
            loaded_texts.append(txt)
            if "simulate(" in txt or "generate_network(" in txt:
                raise RuntimeError("BNGsim adapter rejected model action")
            return _FakeModel()

    monkeypatch.setitem(sys.modules, "bionetgen", _FakeBionetgen)
    receipts = tmp_path / "receipts"
    artifacts = tmp_path / "artifacts"
    summary = bngsim_rec.build_bngsim_receipt(
        root=repo,
        revision=rev,
        bng2_root=bng2_root,
        bngsim_root=bngsim_root,
        receipts_dir=receipts,
        artifacts_dir=artifacts,
    )
    assert summary["emitted_rows"] == ["backend.bngsim"]
    assert len(loaded_texts) == 1
    assert "simulate(" not in loaded_texts[0]
    assert "generate_network(" not in loaded_texts[0]
    report = checks.oracle_independence_report(repo, receipts, rev, artifacts)
    assert report["grounded_execution_rows"] == 1
    assert report["owned_comparisons"][0]["consumer_equals_oracle"] is True
