import copy
import json
from pathlib import Path
import subprocess
import sys

import jsonschema
import pytest

from tests.validation import integrated_extensions
from tests.validation import bngir_adversarial as adversarial

SCHEMA = Path(__file__).parents[2] / "provenance/schemas/bngir-0.2.schema.json"


def test_native_bngir_adversarial_operation_is_registered():
    assert "bngir-adversarial" in integrated_extensions.OPERATIONS


def test_integrated_worker_cli_accepts_native_bngir_adversarial_operation():
    worker = Path(__file__).with_name("integrated_worker.py")
    result = subprocess.run(
        [sys.executable, str(worker), "bngir-adversarial", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "bngir-adversarial" in result.stdout


def test_generated_documents_are_independent_schema_valid_and_exactly_named():
    schema = json.loads(SCHEMA.read_text())
    cases = adversarial.generated_cases()
    assert cases
    assert len({case["id"] for case in cases}) == len(cases)
    assert set(adversarial.check_ids()) == {
        f"bngir-adversarial:{case['id']}" for case in cases
    }
    expected = integrated_extensions.expected_ids([])
    assert "campaign:bngir-adversarial" in expected
    for case in cases:
        jsonschema.validate(case["document"], schema)
        assert case["oracle"] in {"accept", "refuse"}
        assert case["document"]["format"] == "BNGIR"


def test_case_mutations_keep_the_schema_valid():
    schema = json.loads(SCHEMA.read_text())
    cases = adversarial.generated_cases()
    for case in cases:
        document = copy.deepcopy(case["document"])
        jsonschema.validate(document, schema)
        assert case["expected_semantics"]


def test_native_adapter_reports_explicit_refusals_as_diagnostic_controls():
    case = next(c for c in adversarial.generated_cases() if c["oracle"] == "refuse")

    class FakeNative:
        pass

    row = adversarial.evaluate_case(
        case,
        native_import=lambda _model: (_ for _ in ()).throw(
            adversarial.NativeRefusal("native BNGIR structural reference refused")
        ),
        wrap_model=lambda _model: FakeNative(),
    )
    assert row["status"] == "PASS"
    assert row["evidence_kind"] == "diagnostic-only"
    assert row["supported_execution"] is False
    assert row["related_issues"] == [153, 154, 155, 156]


@pytest.mark.parametrize(
    "exception",
    [
        RuntimeError("BNGIR adversarial worker attempted BNGL render/parse fallback"),
        ImportError("native extension missing"),
        ValueError("unexpected adapter error"),
    ],
)
def test_native_adapter_never_counts_unclassified_exceptions_as_refusals(exception):
    case = next(c for c in adversarial.generated_cases() if c["oracle"] == "refuse")
    row = adversarial.evaluate_case(
        case,
        native_import=lambda _model: (_ for _ in ()).throw(exception),
        wrap_model=lambda model: model,
    )
    assert row["status"] == "HARNESS_ERROR"
    assert row["evidence_kind"] == "harness-error"
    assert row["supported_execution"] is False


def test_native_adapter_marks_unexpected_runtime_errors_as_harness_errors():
    case = next(c for c in adversarial.generated_cases() if c["oracle"] == "refuse")
    row = adversarial.evaluate_case(
        case,
        native_import=lambda _model: (_ for _ in ()).throw(
            RuntimeError("unexpected native runtime failure")
        ),
        wrap_model=lambda model: model,
    )
    assert row["status"] == "HARNESS_ERROR"


def test_fallback_attempt_is_not_misclassified_as_native_refusal():
    class FakeCpp:
        def parse_string(self, _source):
            raise AssertionError("must be replaced during native import")

        def _model_from_bngir_v02(self, _model):
            return self.parse_string("fallback")

    class FakeBngir:
        def _as_bngl_v02(self, _document):
            raise AssertionError("must be replaced during native import")

    with pytest.raises(adversarial.HarnessError, match="fallback"):
        adversarial._native_import_without_bngl_fallback(
            FakeCpp(), FakeBngir(), {"model": {}}
        )


def test_native_adapter_fails_if_a_corrupt_document_is_accepted():
    case = next(c for c in adversarial.generated_cases() if c["oracle"] == "refuse")
    row = adversarial.evaluate_case(
        case, native_import=lambda _model: object(), wrap_model=lambda model: model
    )
    assert row["status"] == "FAIL"
    assert row["supported_execution"] is False
    assert row["first_difference"]["field"] == "native_refusal"
