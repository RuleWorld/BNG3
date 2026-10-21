"""The export-format tier must detect semantic loss, not just invalid files.

``tests/validation/export_format_tier.py`` populates issue #163's format tier:
generated model cases are written in every supported export format, read back
where the format supports a round trip, compared against an independent
closed-form law, consumed by a named downstream consumer, and refused
explicitly where a format cannot represent a feature the model uses.

These tests execute the tier and then mutate it, so that a check which cannot
fail is caught here rather than in a campaign report.
"""

from __future__ import annotations

import json

import pytest

from tests.validation import export_format_tier
from tests.validation.strict import require_oracle

ROUNDTRIP_SUFFIXES = ("roundtrip-semantics", "downstream-consumption")
REVISION = "a" * 40


def _independent_consumers_available() -> bool:
    try:
        import libsbml  # noqa: F401
        import roadrunner  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.fixture(scope="module")
def tier_rows(tmp_path_factory, bng_cpp):
    require_oracle(
        export_format_tier.bionetgen is not None,
        "compiled bionetgen extension not importable",
    )
    directory = tmp_path_factory.mktemp("export_format_tier")
    return export_format_tier.run_worker(directory, bng_cpp=bng_cpp)


def _by_id(rows):
    return {row["id"]: row for row in rows}


def test_tier_declares_a_nonempty_format_tier_with_named_checks():
    ids = export_format_tier.check_ids()
    assert ids, "the export-format tier must not be empty"
    assert len(ids) == len(set(ids)), "check identities must be unique"
    formats = {
        identity.split(":")[2]
        for identity in ids
        if identity.startswith("export-format-tier:") and identity.count(":") == 3
    }
    assert formats, "the tier must name at least one export format"
    assert set(export_format_tier.ROUNDTRIP_FORMATS) <= formats
    assert set(export_format_tier.REFUSAL_FORMATS) <= formats
    assert set(export_format_tier.ENERGY_CAPABLE_FORMATS) <= formats
    # Every round-trip format needs a consumer that is not the writer.
    assert set(export_format_tier.CONSUMERS) == set(
        export_format_tier.ROUNDTRIP_FORMATS
    )


def test_tier_executes_every_named_check(tier_rows):
    rows = _by_id(tier_rows)
    expected = export_format_tier.check_ids()
    assert sorted(rows) == sorted(expected)
    for identity in expected:
        row = rows[identity]
        assert row["status"] in {
            "PASS",
            "UNSUPPORTED",
        }, f"{identity} did not complete: {row['detail']}"
        if row["status"] == "UNSUPPORTED":
            # An unsupported consumer is a recorded boundary, never a pass.
            assert "unavailable" in row["detail"], row["detail"]
            assert row["supported_execution"] is False
            # Only the SBML route depends on optional independent consumers.
            assert ":sbml:" in identity, identity
            continue
        assert row["related_issues"] == [163], identity
        if identity.endswith("explicit-refusal"):
            # A recorded refusal proves a boundary; it is never support
            # evidence for the format.
            assert row["evidence_kind"] == "diagnostic-only", identity
            assert row["supported_execution"] is False, identity
            continue
        assert row["supported_execution"] is True, identity
        assert row["evidence_kind"] == "supported-execution", identity
    require_oracle(
        _independent_consumers_available(),
        "libSBML and libRoadRunner are required to execute the SBML export route",
    )
    assert all(row["status"] == "PASS" for row in tier_rows), [
        (row["id"], row["detail"]) for row in tier_rows if row["status"] != "PASS"
    ]


def test_roundtrip_formats_reproduce_the_closed_form_law(tier_rows):
    rows = _by_id(tier_rows)
    for case in export_format_tier.cases():
        for fmt in export_format_tier.ROUNDTRIP_FORMATS:
            identity = f"export-format-tier:{case['id']}:{fmt}:downstream-consumption"
            row = rows[identity]
            if row["status"] != "PASS":
                assert ":sbml:" in identity, identity
                require_oracle(
                    False,
                    "libSBML and libRoadRunner are required for the SBML export route",
                )
            assert row["status"] == "PASS", f"{identity}: {row['detail']}"
            assert export_format_tier.CONSUMERS[fmt] in row["detail"]


def test_unsupported_feature_is_refused_explicitly(tier_rows):
    rows = _by_id(tier_rows)
    for fmt in export_format_tier.REFUSAL_FORMATS:
        identity = f"export-format-tier:refusal:{fmt}:explicit-refusal"
        row = rows[identity]
        assert row["status"] == "PASS", f"{identity}: {row['detail']}"
        assert export_format_tier.ENERGY_FEATURE in row["detail"]


def test_representable_feature_is_not_refused(tier_rows):
    rows = _by_id(tier_rows)
    for fmt in export_format_tier.ENERGY_CAPABLE_FORMATS:
        identity = f"export-format-tier:energy-control:{fmt}:feature-preserved"
        row = rows[identity]
        assert row["status"] == "PASS", f"{identity}: {row['detail']}"


def test_wrong_law_is_detected(tmp_path, bng_cpp, monkeypatch):
    """A wrong independent expectation must fail the consumption checks."""
    original = export_format_tier.case_law

    def broken(case):
        values = original(case)
        return {name: values[name] * 1.5 for name in values}

    monkeypatch.setattr(export_format_tier, "case_law", broken)
    rows = export_format_tier.run_worker(tmp_path, bng_cpp=bng_cpp)
    failures = {row["id"] for row in rows if row["status"] == "FAIL"}
    expected = {
        identity
        for identity in export_format_tier.check_ids()
        if identity.endswith("downstream-consumption")
        and (_independent_consumers_available() or ":sbml:" not in identity)
    }
    assert failures == expected, failures


def test_broken_export_is_detected(tmp_path, bng_cpp, monkeypatch):
    """A writer that changes the exported model must fail the round trip."""
    original = export_format_tier._write_format

    def broken(model, fmt, path):
        original(model, fmt, path)
        if fmt == "bngl":
            path.write_text(
                path.read_text(encoding="utf-8").replace("A() N", "A() 0"),
                encoding="utf-8",
            )

    monkeypatch.setattr(export_format_tier, "_write_format", broken)
    rows = export_format_tier.run_worker(tmp_path, bng_cpp=bng_cpp)
    failures = {row["id"] for row in rows if row["status"] == "FAIL"}
    expected = {
        identity
        for identity in export_format_tier.check_ids()
        if ":bngl:" in identity and identity.endswith(ROUNDTRIP_SUFFIXES)
    }
    assert failures == expected, failures


def test_silent_loss_is_detected(tmp_path, bng_cpp, monkeypatch):
    """A writer that drops the feature instead of refusing must fail."""
    original = export_format_tier._write_format

    def broken(model, fmt, path):
        if fmt == "latex":
            path.write_text("% dropped the energy patterns\n", encoding="utf-8")
            return path
        return original(model, fmt, path)

    monkeypatch.setattr(export_format_tier, "_write_format", broken)
    rows = export_format_tier.run_worker(tmp_path, bng_cpp=bng_cpp)
    failures = {row["id"] for row in rows if row["status"] == "FAIL"}
    assert failures == {"export-format-tier:refusal:latex:explicit-refusal"}, failures


def test_refusal_without_naming_the_feature_is_detected(tmp_path, bng_cpp, monkeypatch):
    """A refusal that does not name the feature must fail."""
    original = export_format_tier._write_format

    def broken(model, fmt, path):
        if fmt == "matlab":
            raise RuntimeError("export failed")
        return original(model, fmt, path)

    monkeypatch.setattr(export_format_tier, "_write_format", broken)
    rows = export_format_tier.run_worker(tmp_path, bng_cpp=bng_cpp)
    failures = {row["id"] for row in rows if row["status"] == "FAIL"}
    assert failures == {"export-format-tier:refusal:matlab:explicit-refusal"}, failures


def test_artifact_left_behind_a_refusal_is_detected(tmp_path, bng_cpp, monkeypatch):
    """A refusal that still leaves an artifact must fail."""
    original = export_format_tier._write_format

    def broken(model, fmt, path):
        if fmt == "sbml" and path.name.startswith("energy.export"):
            path.write_text("<sbml/>\n", encoding="utf-8")
            raise RuntimeError(
                "SBML export rejected model: energy patterns cannot be "
                "represented in this format."
            )
        return original(model, fmt, path)

    monkeypatch.setattr(export_format_tier, "_write_format", broken)
    rows = export_format_tier.run_worker(tmp_path, bng_cpp=bng_cpp)
    failures = {row["id"] for row in rows if row["status"] == "FAIL"}
    assert failures == {"export-format-tier:refusal:sbml:explicit-refusal"}, failures


def test_named_checks_demonstrate_the_issue_163_obligation(tier_rows):
    """The catalog must name exactly the checks the tier executes."""
    from tests.validation import issue_queue

    require_oracle(
        _independent_consumers_available(),
        "libSBML and libRoadRunner are required to execute the SBML export route",
    )
    catalog = json.loads(
        (issue_queue.ROOT / "provenance/issue-obligations.json").read_text(
            encoding="utf-8"
        )
    )
    issue = next(row for row in catalog["issues"] if row["number"] == 163)
    obligation = next(
        row
        for row in issue["obligations"]
        if row["id"]
        == "issue:163:populate-a-nonempty-format-tier-and-verify-semantic-round-trips"
    )
    required = [check["id"] for check in obligation["required_checks"]]
    assert sorted(required) == sorted(export_format_tier.check_ids())
    report = dict(
        source=dict(revision=REVISION, dirty=False),
        subject=dict(binary="bng_cpp", sha256="c" * 64),
        references={},
        results=[
            {
                "id": row["id"],
                "status": row["status"],
                "check": row["check"],
                "related_issues": row["related_issues"],
                "supported_execution": row["supported_execution"],
                "evidence_kind": row["evidence_kind"],
            }
            for row in tier_rows
        ],
    )
    assessed = issue_queue.assess_obligations([obligation], [report], REVISION)
    outcome = assessed["obligations"][0]
    assert outcome["technical_status"] == "DEMONSTRATED", outcome
    assert not outcome["missing_evidence"], outcome["missing_evidence"]
