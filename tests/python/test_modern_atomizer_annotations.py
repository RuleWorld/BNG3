"""Source-derived tests for modern Atomizer annotation handling.

Expectations mirror the public RuleWorld/bngplayground annotation parser at
the pinned reference revision, not the implementation under test.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from bionetgen.atomizer.modern import (
    AnnotationInfo,
    SBMLModel,
    SBMLSpecies,
    annotations_to_json,
    compute_annotation_stats,
    extract_uniprot_accessions,
    find_equivalent_species,
    get_all_annotations,
    parse_resource_uri,
)


def _species(
    species_id: str,
    name: str,
    annotations: list[AnnotationInfo],
) -> SBMLSpecies:
    return SBMLSpecies(id=species_id, name=name, annotations=annotations)


def _model(*species: SBMLSpecies) -> SBMLModel:
    return SBMLModel(
        id="annotation_fixture",
        species=OrderedDict((item.id, item) for item in species),
    )


def test_annotation_parser_extracts_resources_and_filters_empty_species():
    model = _model(
        _species(
            "s1",
            "Species One",
            [
                AnnotationInfo(
                    qualifier_type=1,
                    biological_qualifier=0,
                    resources=["urn:miriam:uniprot:P12345"],
                )
            ],
        ),
        _species("s2", "Species Two", []),
        _species(
            "s3",
            "Species Three",
            [
                AnnotationInfo(
                    qualifier_type=1,
                    biological_qualifier=0,
                    resources=[
                        "uniprot:Q98765",
                        "https://identifiers.org/go/1234567",
                        "https://identifiers.org/pubmed/12345",
                    ],
                )
            ],
        ),
    )

    annotations = get_all_annotations(model)

    assert list(annotations) == ["s1", "s3"]
    assert [(item.database, item.identifier) for item in annotations["s1"]] == [
        ("uniprot", "P12345")
    ]
    assert [(item.database, item.identifier) for item in annotations["s3"]] == [
        ("uniprot", "Q98765"),
        ("go", "1234567"),
        ("pubmed", "12345"),
    ]


def test_annotation_parser_handles_reference_uri_forms_and_uniprot_extraction():
    assert parse_resource_uri("https://identifiers.org/uniprot/P99999") == (
        "uniprot",
        "P99999",
    )
    assert parse_resource_uri("urn:miriam:uniprot:P11111") == (
        "uniprot",
        "P11111",
    )

    model = _model(
        _species(
            "s1",
            "Species One",
            [
                AnnotationInfo(
                    qualifier_type=1,
                    biological_qualifier=0,
                    resources=["uniprot/P12345", "uniprot:Q67890"],
                )
            ],
        ),
        _species(
            "s2",
            "Species Two",
            [
                AnnotationInfo(
                    qualifier_type=1,
                    biological_qualifier=0,
                    resources=["kegg.compound/C00001"],
                )
            ],
        ),
    )

    assert extract_uniprot_accessions(model) == {
        "s1": ["P12345", "Q67890"]
    }


def test_annotation_parser_groups_only_identity_qualifiers():
    model = _model(
        _species(
            "s1",
            "Long Species Name",
            [
                AnnotationInfo(
                    qualifier_type=1,
                    biological_qualifier=1,
                    resources=["uniprot:P12345"],
                ),
                AnnotationInfo(
                    qualifier_type=1,
                    biological_qualifier=0,
                    resources=["uniprot:P12345"],
                ),
            ],
        ),
        _species(
            "s2",
            "S",
            [
                AnnotationInfo(
                    qualifier_type=1,
                    biological_qualifier=3,
                    resources=["https://identifiers.org/uniprot/P12345"],
                )
            ],
        ),
        _species(
            "s3",
            "Other",
            [
                AnnotationInfo(
                    qualifier_type=1,
                    biological_qualifier=1,
                    resources=["uniprot:P12345"],
                )
            ],
        ),
    )

    equivalent = find_equivalent_species(model)

    assert equivalent == {"uniprot:P12345": ["s1", "s2"]}


def test_annotation_parser_emits_reference_json_and_stats():
    model = _model(
        _species(
            "s1",
            "",
            [
                AnnotationInfo(
                    qualifier_type=1,
                    biological_qualifier=0,
                    resources=["uniprot:P12345"],
                )
            ],
        ),
        _species("s2", "Species Two", []),
    )

    annotation_map = get_all_annotations(model)
    payload = annotations_to_json(model, annotation_map)

    assert '"name": "s1"' in payload
    assert '"identifier": "P12345"' in payload
    assert compute_annotation_stats(model).annotated_species == 1
    assert compute_annotation_stats(model).annotation_count == 1


def test_atomizer_annotation_payload_matches_reference_shape():
    from bionetgen.atomizer.modern import Atomizer

    sbml = """<?xml version="1.0"?>
    <sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
          xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
          xmlns:bqbiol="http://biomodels.net/biology-qualifiers/"
          level="3" version="1">
      <model id="annotation_payload">
        <listOfCompartments><compartment id="cell" size="1"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" name="A" compartment="cell" initialAmount="1">
            <annotation><rdf:RDF><rdf:Description rdf:about="#A">
              <bqbiol:is><rdf:Bag><rdf:li rdf:resource="uniprot:P12345"/></rdf:Bag></bqbiol:is>
            </rdf:Description></rdf:RDF></annotation>
          </species>
          <species id="B" name="B" compartment="cell"/>
        </listOfSpecies>
      </model>
    </sbml>
    """

    result = Atomizer(annotation=True).atomize(sbml)

    assert result.success is True
    assert set(result.annotation) == {"species", "reactions", "compartments"}
    assert set(result.annotation["species"]) == {"A"}
    assert result.annotation["species"]["A"]["annotations"][0]["resources"] == [
        "uniprot:P12345"
    ]


def test_bng_xml_converter_preserves_reference_sections_and_bonds():
    from bionetgen.atomizer.modern import convert_bng_xml_to_bngl

    xml = Path(__file__).parent / "test" / "test.xml"
    bngl = convert_bng_xml_to_bngl(xml.read_text(encoding="utf-8"))

    assert "begin parameters" in bngl
    assert "begin molecule types" in bngl
    assert "begin seed species" in bngl
    assert "begin reaction rules" in bngl
    assert "kon 10" in bngl
    assert "X(y,p~0)" in bngl
    assert "X(y!1,p~0).Y(x!1)" in bngl
