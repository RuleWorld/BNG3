"""Consuming checks for bounded network-free Metal workload-class evidence.

The device receipts are produced by ``verify_nfnext_workloads.py``. A passing
unit test without a physical Metal device, or a receipt that claims the full
network-free corpus or CUDA, cannot satisfy these checks.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
VERIFIER = HERE / "verify_nfnext_workloads.py"
RECEIPT_ENV = "BNG3_ISSUE474_NF_WORKLOADS"


def _verifier():
    spec = importlib.util.spec_from_file_location("issue474_nf_workloads", VERIFIER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    not any(
        row["name"] == "metal" and row["compiled"] and row["available"]
        for row in __import__("bionetgen").gpu_backend_capabilities()
    ),
    reason="physical Metal device unavailable",
)
@pytest.mark.parametrize("spec", _verifier().WORKLOADS, ids=lambda s: s["class"])
def test_workload_class_runs_with_analytic_law(spec):
    result = _verifier()._check_workload(spec)
    assert result["device"]
    assert result["checks"] and all(row["pass"] for row in result["checks"])
    assert result["conserved"] is True
    assert result["total_events"] > 0
    assert result["timings_ms"]["setup"] >= 0.0
    assert result["timings_ms"]["dispatch_wait"] > 0.0
    assert result["device_memory_bytes"] > 0
    assert result["events_per_sec_dispatch"] > 0.0
    assert result["pathwise_claim"] is False


def test_unsupported_classes_are_refused_not_approximated():
    from bionetgen.model import BioNetGenModel, _cpp as cpp

    for name, source, expected in _verifier().REFUSALS:
        model = BioNetGenModel(cpp.parse_string(source))
        selected = "cuda" if name == "cuda_backend" else "metal"
        with pytest.raises(RuntimeError, match=expected):
            model.simulate_nfnext_gpu([0.0, 1.0], batch_size=16, backend=selected)


def test_receipt_keeps_bounded_scope_and_digests():
    path = os.environ.get(RECEIPT_ENV)
    if not path:
        pytest.skip(f"set {RECEIPT_ENV} to a recorded workload receipt")
    import json

    receipt = json.loads(Path(path).read_text(encoding="utf-8"))
    assert receipt["status"] == "PASS"
    assert receipt["device"]["backend"] == "metal"
    assert receipt["cuda"]["status"] == "UNSUPPORTED"
    assert receipt["full_corpus_claimed"] is False
    assert {row["class"] for row in receipt["workloads"]} == {
        spec["class"] for spec in _verifier().WORKLOADS
    }
    assert all(
        row["pass"] for workload in receipt["workloads"] for row in workload["checks"]
    )
    assert all(row["status"] == "REFUSED" for row in receipt["refusals"])
    native = Path(receipt["source"]["native_module"])
    assert (
        hashlib.sha256(native.read_bytes()).hexdigest()
        == receipt["source"]["native_sha256"]
    )
