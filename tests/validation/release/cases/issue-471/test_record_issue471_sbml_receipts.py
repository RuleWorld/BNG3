"""Contract and negative-control tests for #471 SBML Core & Comp receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import issue471_checks
from scripts.ci import record_issue471_sbml_receipts as mod


def test_sbml_row_coverage_maps_all_104_core_and_25_comp_rows():
    core_map, comp_map = mod._select_row_case_map(ROOT)
    assert len(core_map) == 99
    assert len(mod.ANALYTIC_CORE_FIXTURES) == 5
    assert len(core_map) + len(mod.ANALYTIC_CORE_FIXTURES) == 104
    assert len(comp_map) == 25
    assert set(core_map).isdisjoint(mod.ANALYTIC_CORE_FIXTURES)
    for rel_path in mod.ANALYTIC_CORE_FIXTURES.values():
        assert (ROOT / rel_path).is_file()


def test_ssts_csv_comparator_accepts_exact_and_within_settings_bounds():
    oracle = {
        "case_id": "00004",
        "settings": {"relative": 1e-4, "absolute": 1e-4},
        "columns": ["time", "S1", "S2"],
        "rows": [
            [0.0, 1.0, "INF"],
            [1.0, 0.5, "NaN"],
        ],
    }
    consumer_ok = {
        "columns": ["time", "S1", "S2"],
        "rows": [
            [0.0, 1.0 + 1e-6, "INF"],
            [1.0, 0.5 - 1e-6, "NaN"],
        ],
    }
    ok, msg = issue471_checks._compare_ssts_csv_bytes(
        json.dumps(oracle).encode(), json.dumps(consumer_ok).encode()
    )
    assert ok, msg


def test_ssts_csv_comparator_rejects_perturbation_inf_nan_and_excessive_bounds():
    oracle = {
        "case_id": "00004",
        "settings": {"relative": 1e-4, "absolute": 1e-4},
        "columns": ["time", "S1", "S2"],
        "rows": [[0.0, 1.0, "INF"], [1.0, 0.5, "NaN"]],
    }
    # Value perturbation exceeding bound
    bad_val = {
        "columns": ["time", "S1", "S2"],
        "rows": [[0.0, 1.05, "INF"], [1.0, 0.5, "NaN"]],
    }
    ok, msg = issue471_checks._compare_ssts_csv_bytes(
        json.dumps(oracle).encode(), json.dumps(bad_val).encode()
    )
    assert not ok
    assert "trajectory mismatch" in msg

    # Wrong sign of Inf
    bad_inf = {
        "columns": ["time", "S1", "S2"],
        "rows": [[0.0, 1.0, "-INF"], [1.0, 0.5, "NaN"]],
    }
    ok, msg = issue471_checks._compare_ssts_csv_bytes(
        json.dumps(oracle).encode(), json.dumps(bad_inf).encode()
    )
    assert not ok
    assert "Inf mismatch" in msg

    # NaN replaced by finite number
    bad_nan = {
        "columns": ["time", "S1", "S2"],
        "rows": [[0.0, 1.0, "INF"], [1.0, 0.5, 0.0]],
    }
    ok, msg = issue471_checks._compare_ssts_csv_bytes(
        json.dumps(oracle).encode(), json.dumps(bad_nan).encode()
    )
    assert not ok
    assert "NaN mismatch" in msg

    # Tampered settings exceeding ceiling
    inflated = dict(oracle, settings={"relative": 0.5, "absolute": 1e-4})
    ok, msg = issue471_checks._compare_ssts_csv_bytes(
        json.dumps(inflated).encode(), json.dumps(bad_val).encode()
    )
    assert not ok
    assert "out of allowed range" in msg


def test_ssts_receipt_validation_accepts_core_and_comp_and_rejects_tamper(
    tmp_path: Path,
):
    ssts_rev = mod._load_ssts_lock_revision(ROOT)
    rev = "a" * 40
    art_root = tmp_path / "artifacts"
    (art_root / "ssts" / "01134").mkdir(parents=True)
    prod = b"<sbml/>"
    oracle = json.dumps(
        {
            "case_id": "01134",
            "settings": {"relative": 1e-4, "absolute": 1e-4},
            "columns": ["time", "S1"],
            "rows": [[0.0, 1.0], [1.0, 0.5]],
        }
    ).encode()
    consumer = json.dumps(
        {
            "columns": ["time", "S1"],
            "rows": [[0.0, 1.0], [1.0, 0.5]],
        }
    ).encode()
    (art_root / "ssts/01134/producer.xml").write_bytes(prod)
    (art_root / "ssts/01134/oracle.json").write_bytes(oracle)
    (art_root / "ssts/01134/consumer.json").write_bytes(consumer)

    row = {
        "id": "sbml.comp.ModelDefinition.id",
        "oracle": "libSBML/JSBML flattening plus independent source simulation",
    }
    receipt = {
        "schema_version": 2,
        "kind": "release-oracle-consumer-receipt",
        "capability_id": row["id"],
        "check_id": f"release-capability[{row['id']}]",
        "comparator": "release-oracle-ssts-csv-v1",
        "source_revision": rev,
        "product_revision": rev,
        "oracle": {
            "name": "official SSTS comp independent source simulation (sbml-test-suite 01134)",
            "source_id": "sbml-test-suite",
            "revision": ssts_rev,
            "path": "ssts/01134/oracle.json",
            "artifact_sha256": hashlib.sha256(oracle).hexdigest(),
            "command": "sbml-test-suite/cases/semantic/01134/01134-results.csv",
            "expected_origin": "official-expected-data",
            "execution": {
                "executable": "sbml-test-suite",
                "version": ssts_rev[:12],
                "command": "sbml-test-suite/cases/semantic/01134/01134-results.csv",
                "exit_code": 0,
            },
        },
        "producer": {
            "path": "ssts/01134/producer.xml",
            "output_sha256": hashlib.sha256(prod).hexdigest(),
        },
        "consumer": {
            "path": "ssts/01134/consumer.json",
            "output_sha256": hashlib.sha256(consumer).hexdigest(),
            "consumed_producer_sha256": hashlib.sha256(prod).hexdigest(),
            "execution": {
                "executable": "bionetgen._bionetgen_cpp",
                "version": rev[:12],
                "command": "Atomizer + BioNetGenModel.simulate(method='ode')",
                "exit_code": 0,
            },
        },
    }
    errors, comp = issue471_checks._oracle_receipt_errors(
        row, receipt, rev, art_root, ROOT
    )
    assert errors == []
    assert comp is not None
    assert comp["id"] == "release-oracle-ssts-csv-v1"
    assert comp["consumer_equals_oracle"] is True

    # Negative control: mutated consumer trajectory fails comparator even if sha matches
    tampered = json.dumps(
        {
            "columns": ["time", "S1"],
            "rows": [[0.0, 1.0], [1.0, 0.9]],
        }
    ).encode()
    (art_root / "ssts/01134/consumer.json").write_bytes(tampered)
    receipt["consumer"]["output_sha256"] = hashlib.sha256(tampered).hexdigest()
    errors2, comp2 = issue471_checks._oracle_receipt_errors(
        row, receipt, rev, art_root, ROOT
    )
    assert any("consumer output differs from oracle" in e for e in errors2)
    assert comp2 is not None and comp2["consumer_equals_oracle"] is False
