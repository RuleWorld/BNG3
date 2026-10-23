"""A corpus pass requires each selected SBML record to be comparable."""

from scripts.ci.validate_published_biomodels import _supported_surface_passed


def test_not_comparable_record_prevents_supported_surface_pass():
    assert not _supported_surface_passed(
        partial=False,
        counts_match=True,
        failed_records=0,
        harness_error_records=0,
        timeout_records=0,
        not_comparable_records=1,
    )


def test_complete_compared_surface_passes_and_hard_nonpasses_do_not():
    arguments = {
        "partial": False,
        "counts_match": True,
        "failed_records": 0,
        "harness_error_records": 0,
        "timeout_records": 0,
        "not_comparable_records": 0,
    }
    assert _supported_surface_passed(**arguments)
    for key in (
        "partial",
        "failed_records",
        "harness_error_records",
        "timeout_records",
    ):
        altered = arguments.copy()
        altered[key] = True if key == "partial" else 1
        assert not _supported_surface_passed(**altered)
