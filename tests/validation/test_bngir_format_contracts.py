import hashlib
import json

from tests.validation import bngir_format_contracts as contracts


def test_contract_ids_separate_export_determinism_and_equality_scope():
    assert contracts.check_ids() == [
        "bngir-export:v02-independent-roundtrip",
        "bngir-export:v02-site-bearing-unsupported",
        "bngir-export:canonical-bytes-determinism",
        "bngir-equality:v01-v02-identity-provenance",
        "bngir-equality:approved-default-v01-explicit-v02",
    ]
    assert contracts.ISSUES == [155, 156]
