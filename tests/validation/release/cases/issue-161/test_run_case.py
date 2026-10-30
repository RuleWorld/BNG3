"""Focused provenance-helper controls for the Issue 161 runner."""

from __future__ import annotations

import builtins
from pathlib import Path
import subprocess

from run_case import (
    _authored_export_acceptance,
    _compare_source_networks,
    _git_identity,
    _preserve_evidence_file,
    _reference_sbml_validity,
    sbml_validity,
    source_contract_eligible,
    _sbml_validity,
    _xml_mutation_controls,
    _unit_compartment_source,
)


def test_evidence_file_is_copied_to_requested_artifact_path(tmp_path: Path):
    source = tmp_path / "generated.xml"
    source.write_text("<sbml/>", encoding="utf-8")
    artifacts = tmp_path / "evidence"

    path = _preserve_evidence_file(source, artifacts, "candidate.xml")

    assert Path(path) == artifacts / "candidate.xml"
    assert Path(path).read_text(encoding="utf-8") == "<sbml/>"


def test_source_network_oracle_comparison_detects_seed_quantity_changes(
    tmp_path: Path,
):
    reference = tmp_path / "reference.net"
    candidate = tmp_path / "candidate.net"
    prefix = """begin species
    1 A() {amount} 0
end species
begin reactions
end reactions
"""
    reference.write_text(prefix.format(amount="100"), encoding="utf-8")
    candidate.write_text(prefix.format(amount="101"), encoding="utf-8")

    diff = _compare_source_networks(reference, candidate)

    assert not diff.ok
    assert diff.initial_amounts_changed == {"A()"}


def test_git_identity_accepts_bng2_file_path_and_reports_checkout_dirty_state(
    tmp_path: Path,
):
    checkout = tmp_path / "oracle"
    script = checkout / "bng2" / "BNG2.pl"
    script.parent.mkdir(parents=True)
    script.write_text("# pinned oracle\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "init", "--quiet"], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.name", "Test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(checkout), "add", "bng2/BNG2.pl"], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "commit", "--quiet", "-m", "oracle"],
        check=True,
    )

    clean = _git_identity(script)
    assert clean["root"] == str(checkout)
    assert clean["revision"]
    assert clean["dirty"] is False

    script.write_text("# modified oracle\n", encoding="utf-8")
    dirty = _git_identity(script)
    assert dirty["root"] == str(checkout)
    assert dirty["revision"] == clean["revision"]
    assert dirty["dirty"] is True


def test_sbml_validity_marks_invalid_reference_without_relabeling_candidate(
    tmp_path: Path,
):
    invalid = tmp_path / "invalid.xml"
    invalid.write_text("<notSBML/>", encoding="utf-8")

    reference = _reference_sbml_validity(invalid)
    candidate = _sbml_validity(invalid)

    assert reference["classification"] == "reference-invalid"
    assert reference["severity_error_count"] > 0
    assert candidate["status"] == "invalid"
    assert "classification" not in candidate


def test_sbml_validity_accepts_a_valid_level_three_document(tmp_path: Path):
    valid = tmp_path / "valid.xml"
    valid.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="m"/>
</sbml>""",
        encoding="utf-8",
    )

    result = _sbml_validity(valid)

    assert result["status"] == "valid"
    assert result["severity_error_count"] == 0


def test_missing_libsbml_is_unavailable_and_cannot_enable_source_fallback(
    tmp_path: Path, monkeypatch
):
    xml = tmp_path / "candidate.xml"
    xml.write_text("<sbml/>", encoding="utf-8")
    original_import = builtins.__import__

    def import_without_libsbml(name, *args, **kwargs):
        if name == "libsbml":
            raise ModuleNotFoundError("No module named 'libsbml'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_libsbml)

    result = sbml_validity(xml)

    assert result == {
        "status": "unavailable",
        "error": "python-libsbml is required for SBML validity checks",
    }
    assert not source_contract_eligible(
        {"status": "invalid"},
        result,
        {"status": "pass"},
        {"bond": {"status": "pass"}},
    )


def test_bounded_source_transform_handles_both_issue_161_models():
    cases = Path(__file__).parent
    main = _unit_compartment_source(cases / "test_write_sbml_multi.bngl")
    state_bearing = _unit_compartment_source(
        cases / "state_bearing_binding_refusal.bngl"
    )

    assert "begin compartments\n    default 3 1\nend compartments" in main
    assert "@default:R(l,l)     300" in main
    assert "@default:L(r,r,r)  1200" in main
    assert "@default:R(l) + @default:L(r,r,r)" in main
    assert "begin compartments\n    default 3 1\nend compartments" in state_bearing
    assert "@default:R(l~u) 100" in state_bearing
    assert "@default:L(r)   100" in state_bearing
    assert "@default:R(l~u) + @default:L(r)" in state_bearing


def test_structural_comparator_detects_all_semantic_mutation_controls(tmp_path: Path):
    xml = tmp_path / "candidate.xml"
    xml.write_text(
        """<sbml xmlns:multi="urn:multi"><model>
  <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
  <listOfParameters/>
  <listOfSpeciesTypes>
    <speciesType id="T"><listOfSpeciesTypeInstances>
      <speciesTypeInstance id="a" speciesType="R"><listOfSpeciesTypeComponentIndexes>
        <speciesTypeComponentIndex id="a1" component="x"/>
      </listOfSpeciesTypeComponentIndexes></speciesTypeInstance>
      <speciesTypeInstance id="b" speciesType="L"><listOfSpeciesTypeComponentIndexes>
        <speciesTypeComponentIndex id="b1" component="y"/>
        <speciesTypeComponentIndex id="b2" component="z"/>
      </listOfSpeciesTypeComponentIndexes></speciesTypeInstance>
    </listOfSpeciesTypeInstances><listOfSpeciesTypeBindings>
      <inSpeciesTypeBond id="bond" bindingSite1="a1" bindingSite2="b1"/>
    </listOfSpeciesTypeBindings></speciesType>
    <speciesType id="State"><listOfSpeciesFeatures>
      <speciesFeature id="s"><listOfPossibleSpeciesFeatureValues>
        <possibleSpeciesFeatureValue id="u"/><possibleSpeciesFeatureValue id="p"/>
      </listOfPossibleSpeciesFeatureValues></speciesFeature></listOfSpeciesFeatures>
    </speciesType>
  </listOfSpeciesTypes>
  <listOfSpecies><species id="s" initialAmount="100">
    <speciesFeature id="f"><speciesFeatureValue value="u"/></speciesFeature>
  </species></listOfSpecies>
  <listOfReactions><reaction id="r"><listOfReactants/><listOfProducts/>
    <listOfSpeciesTypeComponentMapInProducts>
      <speciesTypeComponentMapInProduct reactant="a" reactantComponent="a1" productComponent="a1"/>
      <speciesTypeComponentMapInProduct reactant="b" reactantComponent="b1" productComponent="b2"/>
    </listOfSpeciesTypeComponentMapInProducts>
    <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply>
      <times/><cn>0.1</cn><ci>s</ci>
    </apply></math></kineticLaw>
  </reaction></listOfReactions>
</model></sbml>""",
        encoding="utf-8",
    )

    controls = _xml_mutation_controls(xml)

    assert {name: result["status"] for name, result in controls.items()} == {
        "bond": "pass",
        "state": "pass",
        "component_map_target": "pass",
        "initial_quantity": "pass",
        "compartment_volume": "pass",
        "reaction_rate": "pass",
    }


def test_invalid_reference_uses_source_contract_without_passing_strict_diff():
    result = _authored_export_acceptance(
        strict_match=False,
        reference_validity={"status": "invalid"},
        candidate_validity={"status": "valid"},
        semantic_contract={"status": "pass"},
        contract_mutations={"missing_bond": {"status": "pass"}},
    )

    assert result == {
        "acceptance_status": "pass",
        "oracle": "source-authored-contract",
        "strict_comparison_status": "reference-invalid",
    }


def test_valid_reference_still_requires_strict_structural_match():
    result = _authored_export_acceptance(
        strict_match=False,
        reference_validity={"status": "valid"},
        candidate_validity={"status": "valid"},
        semantic_contract={"status": "pass"},
        contract_mutations={"missing_bond": {"status": "pass"}},
    )

    assert result["acceptance_status"] == "fail"
    assert result["oracle"] == "none"


def test_invalid_reference_contract_cannot_pass_invalid_candidate_or_failed_control():
    common = {
        "strict_match": False,
        "reference_validity": {"status": "invalid"},
        "semantic_contract": {"status": "pass"},
        "contract_mutations": {"missing_bond": {"status": "pass"}},
    }
    invalid_candidate = _authored_export_acceptance(
        **common,
        candidate_validity={"status": "invalid"},
    )
    failed_control = _authored_export_acceptance(
        **{
            **common,
            "contract_mutations": {"missing_bond": {"status": "fail"}},
        },
        candidate_validity={"status": "valid"},
    )

    assert invalid_candidate["acceptance_status"] == "fail"
    assert failed_control["acceptance_status"] == "fail"
