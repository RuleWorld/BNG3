from tests.validation import bngir_reconstruction_contracts as contracts


def test_reconstruction_and_migration_check_ids_are_namespaced():
    assert contracts.check_ids() == [
        "bngir-reconstruction:source-text-independent-v02",
        "bngir-version-migration:v01-v02-feature-matrix",
        "bngir-version-migration:v01-v02-refusal-ownership",
    ]
    assert contracts.ISSUES == [153, 154]


def test_every_recorded_gap_names_a_catalog_owner():
    from tests.validation import bngir_reconstruction_contracts as contracts

    owners = contracts._catalog_owners()
    for identifier, owner in contracts.KNOWN_GAPS.items():
        assert owner in owners, identifier
        assert identifier in {cell["id"] for cell in contracts.MATRIX}


def test_matrix_covers_each_feature_cell_once():
    identifiers = [cell["id"] for cell in contracts.MATRIX]
    assert len(identifiers) == len(set(identifiers))
    assert "molecule-components" in identifiers
    assert "protocol-actions" in identifiers
    assert "population-types" in identifiers


def test_independent_document_is_not_the_writer_output():
    import json

    document = contracts.independent_document()
    assert document["format"] == "BNGIR"
    assert document["version"] == "0.2"
    assert document["model"]["metadata"]["name"] == "independent_reconstruction"
    # A writer-produced document would carry the writer's own feature vocabulary;
    # the authored one states the features it uses explicitly.
    assert json.dumps(document, sort_keys=True)
    assert "seeds" in document["features"]["used"]
