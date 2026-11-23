"""Check the independent delay oracle against a method-of-steps solution."""

import os
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.ci.validate_published_biomodels import _simulate_and_compare

DELAY_SBML = """<sbml xmlns="http://www.sbml.org/sbml/level2/version4"
    level="2" version="4">
  <model id="method_of_steps">
    <listOfParameters>
      <parameter id="x" value="1" constant="false"/>
      <parameter id="obs_x" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="x">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><csymbol encoding="text"
            definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>
            <ci>x</ci><cn>1</cn></apply>
        </math>
      </rateRule>
      <assignmentRule variable="obs_x">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>x</ci></math>
      </assignmentRule>
    </listOfRules>
  </model>
</sbml>"""


@pytest.mark.parametrize("original_source", [True, False])
def test_independent_delay_oracle_scores_real_and_wrong_trajectories(
    original_source, tmp_path
):
    if not os.environ.get("BNG3_BIOMODELS_DELAY_PYTHON"):
        return
    output_path = tmp_path / "written.xml"
    output_path.write_text(DELAY_SBML, encoding="utf-8")
    times = np.linspace(0.0, 2.0, 9)
    expected = 1 + times + 0.5 * np.maximum(times - 1.0, 0.0) ** 2

    def compare(trajectory):
        def model_type(_):
            return SimpleNamespace(
                simulate=lambda **_: SimpleNamespace(
                    time=times, observables={"x": trajectory}
                )
            )

        return _simulate_and_compare(
            None,
            model_type,
            output_path,
            t_end=2.0,
            n_steps=8,
            rtol=1e-7,
            atol=1e-12,
            reference_model=DELAY_SBML if original_source else None,
            reference_selections={"x": "x"} if original_source else None,
        )

    result = compare(expected)
    assert result["passed"], result
    assert result["method_sbml"] == "sbmlsim-core CVODE"
    assert result["delay_oracle"]["version"] == "0.20.0"
    assert result["delay_oracle"]["converted_sbml_sha256"]
    assert not compare(1 + times)["passed"]
