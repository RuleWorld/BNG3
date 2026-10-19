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
        assert case["oracle"] in {
            "accept",
            "refuse",
            "unsupported",
            "accept-or-unsupported",
        }
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
    assert row["related_issues"] == [153, 154, 155, 156, 163]


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


def test_structural_cases_declare_independent_trajectories_and_boundary_policy():
    cases = {case["id"]: case for case in adversarial.generated_cases()}
    for name in (
        "molecule-id-permutation",
        "compartment-suffix",
        "compartment-prefix",
        "molecule-compartment",
    ):
        case = cases[name]
        assert case["expected_semantics"]["trajectory"]
        assert case["oracle"] in {"accept", "accept-or-unsupported"}
    assert cases["bonded-complex-boundary"]["oracle"] == "unsupported"
    assert cases["unknown-pattern-compartment"]["oracle"] == "refuse"


def test_structural_loss_detector_rejects_missing_compartment():
    expected = {"A()@cell": 100.0, "B()@cell": 0.0}
    difference = adversarial.compare_observation(
        "seed", {"A()": 100.0, "B()": 0.0}, expected
    )
    assert difference["field"] == "seed.species"


def test_species_name_normalization_is_independent_of_the_compartment_spelling():
    """The three compartment spellings name one compartmented species."""
    assert adversarial._canonical_species_name("@cell::A()") == "A()@cell"
    assert adversarial._canonical_species_name("@cell:A()") == "A()@cell"
    assert adversarial._canonical_species_name("A()") == "A()"
    assert adversarial._canonical_species_name("A()@cell") == "A()@cell"


def test_optional_supported_structure_refusal_is_unsupported_not_pass():
    case = {
        "id": "future-compartment",
        "oracle": "accept-or-unsupported",
        "document": {},
        "expected_semantics": {},
    }
    row = adversarial.evaluate_case(
        case,
        native_import=lambda _: (_ for _ in ()).throw(
            adversarial.NativeRefusal("native BNGIR does not support compartments")
        ),
        wrap_model=lambda x: x,
    )
    assert row["status"] == "UNSUPPORTED"
    assert row["supported_execution"] is False


def test_positive_structure_does_not_hide_unexpected_native_refusal():
    case = next(c for c in adversarial.CASES if c["id"] == "compartment-suffix")
    row = adversarial.evaluate_case(
        case,
        native_import=lambda _: (_ for _ in ()).throw(
            adversarial.NativeRefusal(
                "native BNGIR molecule type reference is out of range"
            )
        ),
        wrap_model=lambda x: x,
    )
    assert row["status"] == "FAIL"


def test_worker_cli_accepts_registered_adversarial_execution():
    import ast

    tree = ast.parse((Path(__file__).parent / "integrated_worker.py").read_text())
    choices = next(
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "choices"
    )
    assert "bngir-adversarial" in ast.literal_eval(choices)


def test_numeric_seed_rhs_and_trajectory_corruption_are_detected():
    for field in ("seed", "rhs", "trajectory"):
        difference = adversarial.compare_observation(
            field, {"A()": 99.0}, {"A()": 100.0}
        )
        assert difference == dict(field=field + ".A()", expected=100.0, actual=99.0)
