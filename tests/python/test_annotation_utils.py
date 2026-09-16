from bionetgen.atomizer.atomizer.annotation_utils import (
    identifiers_org_database,
    identifiers_org_databases,
)


def test_identifiers_org_database_parses_only_the_authorized_host():
    assert (
        identifiers_org_database("https://identifiers.org/uniprot/P12345") == "uniprot"
    )
    assert identifiers_org_database("http://identifiers.org/chebi/CHEBI:123") == "chebi"
    assert (
        identifiers_org_database("https://evil.example/identifiers.org/uniprot/P12345")
        is None
    )
    assert (
        identifiers_org_database("https://identifiers.org.evil.example/uniprot/P12345")
        is None
    )


def test_identifiers_org_databases_ignores_malformed_or_incomplete_values():
    values = {
        "https://identifiers.org/uniprot/P12345",
        "https://identifiers.org/chebi/CHEBI:123",
        "not a URL",
        "https://identifiers.org/uniprot",
    }
    assert identifiers_org_databases(values) == {"uniprot", "chebi"}
