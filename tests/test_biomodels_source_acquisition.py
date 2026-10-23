"""Source transport failures remain separate from scientific model verdicts."""

import importlib.util
import urllib.error
from pathlib import Path

import pytest


def _validator():
    path = (
        Path(__file__).parents[1] / "scripts" / "ci" / "validate_published_biomodels.py"
    )
    spec = importlib.util.spec_from_file_location("biomodels_validator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_fetch_error_retains_both_public_endpoints(tmp_path, monkeypatch):
    validator = _validator()
    entry = {
        "download_url": "https://www.biomodels.org/model/download/BIOMD1?filename=model.xml",
        "record_url": "https://www.biomodels.org/BIOMD1?format=json",
        "filename": "model.xml",
    }

    def denied(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(validator.urllib.request, "urlopen", denied)
    monkeypatch.setattr(
        validator,
        "_fetch_json",
        lambda url: (_ for _ in ()).throw(
            urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        ),
    )

    with pytest.raises(validator.SourceAcquisitionError) as caught:
        validator._download_if_needed(tmp_path / "model.xml", entry)

    assert entry["download_url"] in str(caught.value)
    assert entry["record_url"] in str(caught.value)
    assert "HTTPError" in str(caught.value)
    assert [attempt["http_status"] for attempt in caught.value.attempts] == [403, 403]
    assert [attempt["url"] for attempt in caught.value.attempts] == [
        entry["download_url"],
        entry["record_url"],
    ]
    assert validator._model_exception_status(caught.value) == "harness_error"
    assert (
        validator._model_exception_status(RuntimeError("conversion failed")) == "failed"
    )
