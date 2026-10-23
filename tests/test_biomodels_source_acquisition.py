"""Source transport failures remain separate from scientific model verdicts."""

import hashlib
import importlib.util
import io
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


def test_same_source_filename_uses_model_identity_and_content_sha(
    tmp_path, monkeypatch
):
    validator = _validator()
    first_bytes = b"<sbml id='first'/><!---->"
    second_bytes = b"<sbml id='second'/><!---->"
    first_sha = hashlib.sha256(first_bytes).hexdigest()
    second_sha = hashlib.sha256(second_bytes).hexdigest()
    # Legacy/shared caches can have identical basenames in different folders.
    (tmp_path / "legacy-a").mkdir()
    (tmp_path / "legacy-b").mkdir()
    (tmp_path / "legacy-a" / "model.xml").write_bytes(first_bytes)
    (tmp_path / "legacy-b" / "model.xml").write_bytes(second_bytes)

    def no_network(*args, **kwargs):
        raise AssertionError(
            "a verified content-addressed cache hit should avoid download"
        )

    monkeypatch.setattr(validator.urllib.request, "urlopen", no_network)
    first = {
        "id": "BIOMD0000000001",
        "filename": "model.xml",
        "sha256": first_sha,
        "download_url": "https://www.biomodels.org/model/first",
    }
    second = {
        "id": "BIOMD0000000002",
        "filename": "model.xml",
        "sha256": second_sha,
        "download_url": "https://www.biomodels.org/model/second",
    }
    first_path = validator._model_source_cache_path(tmp_path, first)
    second_path = validator._model_source_cache_path(tmp_path, second)

    assert first_path != second_path
    assert first_path == tmp_path / "sha256" / first_sha
    assert second_path == tmp_path / "sha256" / second_sha
    migrated = validator._migrate_legacy_source_cache(tmp_path, [first, second])
    assert migrated == {"expected_hashes": 2, "migrated": 2, "missing": 0}
    assert validator._download_if_needed(first_path, first) == first_sha
    assert validator._download_if_needed(second_path, second) == second_sha
    assert first_path.read_bytes() == first_bytes
    assert second_path.read_bytes() == second_bytes


def test_source_without_valid_sha_does_not_reuse_content_cache(tmp_path, monkeypatch):
    validator = _validator()
    source = tmp_path / "old" / "model.xml"
    source.parent.mkdir()
    source.write_bytes(b"cached bytes")
    target = validator._model_source_cache_path(
        tmp_path, {"id": "BIOMD0000000003", "filename": "model.xml"}
    )
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b"fresh bytes"

    def fetch(request, timeout):
        calls.append(request.full_url)
        return Response()

    monkeypatch.setattr(validator.urllib.request, "urlopen", fetch)
    entry = {
        "id": "BIOMD0000000003",
        "filename": "model.xml",
        "download_url": "https://www.biomodels.org/model/no-checksum",
    }
    assert (
        validator._download_if_needed(target, entry)
        == hashlib.sha256(b"fresh bytes").hexdigest()
    )
    assert calls == [entry["download_url"]]
    assert target.read_bytes() == b"fresh bytes"


def test_hash_addressed_worker_hit_does_not_scan_cache_tree(tmp_path, monkeypatch):
    validator = _validator()
    content = b"<sbml id='worker'/>\n"
    digest = hashlib.sha256(content).hexdigest()
    entry = {
        "id": "BIOMD0000000004",
        "filename": "model.xml",
        "sha256": digest,
        "download_url": "https://www.biomodels.org/model/worker",
    }
    path = validator._model_source_cache_path(tmp_path, entry)
    path.parent.mkdir(parents=True)
    path.write_bytes(content)

    def unexpected_scan(*args, **kwargs):
        raise AssertionError("isolated workers must use the direct SHA path")

    monkeypatch.setattr(Path, "rglob", unexpected_scan)
    assert validator._download_if_needed(path, entry) == digest


def test_downloaded_source_hash_mismatch_is_a_harness_integrity_error(
    tmp_path, monkeypatch
):
    validator = _validator()
    content = b"<sbml/>\n"
    expected = "0" * 64
    entry = {
        "download_url": "https://www.biomodels.org/model/download/BIOMD1?filename=model.xml",
        "record_url": "https://www.biomodels.org/BIOMD1?format=json",
        "filename": "model.xml",
        "sha256": expected,
    }

    monkeypatch.setattr(
        validator.urllib.request,
        "urlopen",
        lambda request, timeout: io.BytesIO(content),
    )

    with pytest.raises(RuntimeError) as caught:
        validator._download_if_needed(tmp_path / "model.xml", entry)

    actual = hashlib.sha256(content).hexdigest()
    assert validator._model_exception_status(caught.value) == "harness_error"
    assert caught.value.expected_sha256 == expected
    assert caught.value.actual_sha256 == actual
