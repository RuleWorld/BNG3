"""Unit checks for the pinned public BioModels validation manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "provenance" / "published-biomodels.json"


def test_published_biomodel_manifest_is_pinned_and_well_formed():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    models = manifest["models"]
    ids = [model["id"] for model in models]
    assert len(models) == 8
    assert len(ids) == len(set(ids))
    for model in models:
        assert model["filename"] == f"{model['id']}_url.xml"
        assert len(model["sha256"]) == hashlib.sha256().digest_size * 2
        int(model["sha256"], 16)
        assert "{id}" in manifest["download_url_template"]
        assert "{filename}" in manifest["download_url_template"]
