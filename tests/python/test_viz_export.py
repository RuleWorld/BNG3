from pathlib import Path

import pytest

pytest.importorskip("bionetgen._bionetgen_cpp")

import bionetgen


def test_visualization_exports(tmp_path):
    model_path = Path(__file__).parent / "viz" / "test.bngl"
    model = bionetgen.load(str(model_path))

    exports = {
        "contact_map": model.contact_map,
        "regulatory_graph": model.regulatory_graph,
        "rule_influence_graph": model.rule_influence_graph,
        "reaction_network_graph": model.reaction_network_graph,
        "ruleviz_pattern": model.ruleviz_pattern,
        "ruleviz_operation": model.ruleviz_operation,
        "process_graph": model.process_graph,
        "sbml_multi": model.sbml_multi,
    }

    for name, export in exports.items():
        path = tmp_path / f"{name}.xml"
        content = export(str(path))
        assert path.exists()
        assert len(content.strip()) > 0
        assert (
            content.lstrip().startswith("graph [")
            or "<sbml" in content
            or content.lstrip().startswith("<?xml")
        )


def test_contact_map_string_export():
    model_path = Path(__file__).parent / "viz" / "test.bngl"
    model = bionetgen.load(str(model_path))
    content = model.contact_map()
    assert content.lstrip().startswith("graph [")
