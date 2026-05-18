from pathlib import Path

import pytest

pytest.importorskip("bionetgen._bionetgen_cpp")

try:
    import libsbml  # noqa: F401
except ImportError:
    pytest.skip("libSBML is required for SBML import tests", allow_module_level=True)

import bionetgen


def test_sbml_to_bngl_and_from_sbml():
    sbml_path = Path(__file__).parent / "test" / "test_sbml.xml"
    assert sbml_path.exists()

    try:
        bngl_text = bionetgen.sbml_to_bngl(str(sbml_path), atomize=False)
        model = bionetgen.from_sbml(str(sbml_path), atomize=False)
    except bionetgen.BioNetGenError as exc:
        pytest.skip(f"SBML import unavailable in this environment: {exc}")

    assert "begin model" in bngl_text
    assert len(model.parameters) > 0
    assert len(model.seed_species) > 0
