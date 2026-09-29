"""Regression tests for the cross-engine Atomizer benchmark workers."""

from pathlib import Path
import subprocess

import benchmarks.benchmark_atomizer_cross_engine as benchmark
from benchmarks.benchmark_atomizer_cross_engine import run_atomizer


def test_modern_benchmark_worker_resolves_external_comp_source(tmp_path: Path):
    parent_path = tmp_path / "parent.xml"
    child_path = tmp_path / "child.xml"
    child_path.write_text(
        """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
            level="3" version="2">
          <model id="childModel">
            <listOfCompartments>
              <compartment id="cell" size="1" constant="true"/>
            </listOfCompartments>
            <listOfSpecies>
              <species id="A" compartment="cell" initialAmount="2"
                       hasOnlySubstanceUnits="true" boundaryCondition="false"
                       constant="false"/>
            </listOfSpecies>
            <listOfReactions>
              <reaction id="synthesis" reversible="false">
                <listOfProducts>
                  <speciesReference species="A" stoichiometry="1" constant="true"/>
                </listOfProducts>
                <kineticLaw>
                  <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
                </kineticLaw>
              </reaction>
            </listOfReactions>
          </model>
        </sbml>""",
        encoding="utf-8",
    )
    parent_path.write_text(
        """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
            xmlns:comp="http://www.sbml.org/sbml/level3/version1/comp/version1"
            level="3" version="2" comp:required="true">
          <model id="parent">
            <comp:listOfSubmodels>
              <comp:submodel comp:id="child" comp:modelRef="childModel"/>
            </comp:listOfSubmodels>
          </model>
          <comp:listOfExternalModelDefinitions>
            <comp:externalModelDefinition comp:id="childModel"
                                          comp:source="child.xml"
                                          comp:modelRef="childModel"/>
          </comp:listOfExternalModelDefinitions>
        </sbml>""",
        encoding="utf-8",
    )
    output_path = tmp_path / "converted.bngl"

    result = run_atomizer(
        source=parent_path,
        mode="flat",
        output=output_path,
        metadata=tmp_path / "metadata.json",
        implementation="bng3_modern",
        pybionetgen_root=tmp_path,
    )

    assert result["status"] == "ok", result
    bngl = output_path.read_text(encoding="utf-8")
    assert "child__A()" in bngl
    assert "child__synthesis" in bngl


def test_legacy_worker_imports_atomizer_from_requested_checkout(tmp_path: Path):
    checkout = tmp_path / "pybionetgen"
    package = checkout / "bionetgen"
    atomizer = package / "atomizer"
    atomizer.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (atomizer / "__init__.py").write_text("", encoding="utf-8")
    (atomizer / "atomizeTool.py").write_text(
        """
from pathlib import Path

class AtomizeTool:
    def __init__(self, input_file, options_dict):
        self.options = options_dict

    def run(self):
        Path(self.options['output']).write_text('begin model\\nend model\\n')
        return self
""",
        encoding="utf-8",
    )
    source = tmp_path / "source.xml"
    source.write_text("<sbml/>", encoding="utf-8")
    output = tmp_path / "output.bngl"

    result = run_atomizer(
        source=source,
        mode="flat",
        output=output,
        metadata=tmp_path / "metadata.json",
        implementation="pybionetgen_legacy",
        pybionetgen_root=checkout,
    )

    assert result["status"] == "ok", result
    assert result["atomizer_module_path"] == str(
        (atomizer / "atomizeTool.py").resolve()
    )


def test_network_benchmark_does_not_execute_atomizer_actions(
    monkeypatch, tmp_path: Path
):
    bngl = tmp_path / "model.bngl"
    bngl.write_text(
        "begin model\nend model\n\n"
        "begin actions\n"
        'simulate({method=>"ode", t_end=>25})\n'
        'setConcentration("X()", "50")\n'
        "end actions\n",
        encoding="utf-8",
    )
    observed_inputs = []

    def fake_bng2(command, **_kwargs):
        input_path = Path(command[-1])
        observed_inputs.append(input_path.read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="stop")

    monkeypatch.setattr(benchmark.subprocess, "run", fake_bng2)

    result = benchmark.run_network(
        bngl=bngl,
        out_dir=tmp_path / "bng2",
        engine="bng2",
        bng2_perl=tmp_path / "BNG2.pl",
        timeout=1,
    )

    exported_input = observed_inputs[0]
    assert result["status"] == "error"
    assert exported_input.count("begin actions") == 1
    assert "simulate(" not in exported_input
    assert "setConcentration(" not in exported_input
    assert "generate_network({overwrite=>1})" in exported_input
