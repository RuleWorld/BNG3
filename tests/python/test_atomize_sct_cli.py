"""``--write-scts`` / ``--write-sct-graphs`` emit real SCT artifacts."""

import json

from click.testing import CliRunner

from bionetgen.cli import main

SOURCE = "tests/fixtures/sbml_test_suite_reaction_rate/01385-sbml-l3v2.xml"


def test_write_scts_creates_json_and_graphml(tmp_path):
    bngl = tmp_path / "model.bngl"
    result = CliRunner().invoke(
        main,
        [
            "atomize",
            "--input-file",
            SOURCE,
            "--output-file",
            str(bngl),
            "--write-scts",
            "--write-sct-graphs",
        ],
    )
    assert result.exit_code == 0, result.output
    assert bngl.is_file()
    sct_json = tmp_path / "01385-sbml-l3v2_scts.json"
    assert sct_json.is_file()
    payload = json.loads(sct_json.read_text())
    assert "01_binding_sct" in payload
    assert "S1" in payload["01_binding_sct"]
    assert (tmp_path / "01385-sbml-l3v2_01_binding_sct.graphml").is_file()
