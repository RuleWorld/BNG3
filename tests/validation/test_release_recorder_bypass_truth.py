"""Negative controls for release recorder local-only modes."""

import pytest

from scripts.ci import (
    record_delay_release,
    record_hybrid_release,
    record_issue138_release,
    record_issue143_release,
    record_issue147_release,
    record_jax_release,
)


@pytest.mark.parametrize(
    "recorder",
    [
        record_delay_release,
        record_hybrid_release,
        record_issue138_release,
        record_issue143_release,
        record_issue147_release,
        record_jax_release,
    ],
)
def test_skipped_execution_cannot_be_release_pass(recorder):
    report = recorder.build_release_record(skip_tests=True, allow_dirty=True)
    assert all(row["status"] != "PASS" for row in report["results"])
    assert all(row["supported_execution"] is False for row in report["results"])


@pytest.mark.parametrize(
    "recorder",
    [
        record_delay_release,
        record_hybrid_release,
        record_issue138_release,
        record_issue143_release,
        record_issue147_release,
        record_jax_release,
    ],
)
def test_allowed_dirty_checkout_is_reported(recorder, monkeypatch):
    original_run = recorder.subprocess.run

    def run(cmd, **kwargs):
        result = original_run(cmd, **kwargs)
        if "status" in cmd:
            result.stdout = " M tracked.py\n"
        return result

    monkeypatch.setattr(recorder.subprocess, "run", run)
    report = recorder.build_release_record(skip_tests=True, allow_dirty=True)
    assert report["source"]["dirty"] is True


@pytest.mark.parametrize(
    "recorder",
    [
        record_delay_release,
        record_hybrid_release,
        record_issue138_release,
        record_issue143_release,
        record_issue147_release,
        record_jax_release,
    ],
)
def test_untracked_source_is_reported_dirty(recorder, monkeypatch):
    original_run = recorder.subprocess.run

    def run(cmd, **kwargs):
        result = original_run(cmd, **kwargs)
        if "status" in cmd:
            result.stdout = "" if "--untracked-files=no" in cmd else "?? source.py\n"
        return result

    monkeypatch.setattr(recorder.subprocess, "run", run)
    report = recorder.build_release_record(skip_tests=True, allow_dirty=True)
    assert report["source"]["dirty"] is True
