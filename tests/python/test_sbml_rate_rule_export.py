"""Rate-rule states must not also participate in SBML reactions (20610)."""

import libsbml
import numpy as np
import pytest
import roadrunner
from _extdep import require_extension

from bionetgen.atomizer.modern import Atomizer

cpp = require_extension()


def _source(ordinary_reaction):
    reactions = (
        """<listOfReactions><reaction id="transfer" reversible="false">
      <listOfReactants><speciesReference species="Y" stoichiometry="1" constant="true"/></listOfReactants>
      <listOfProducts><speciesReference species="Z" stoichiometry="1" constant="true"/></listOfProducts>
      <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
        <apply><times/><cn>0.5</cn><ci>Y</ci></apply>
      </math></kineticLaw>
    </reaction></listOfReactions>"""
        if ordinary_reaction
        else ""
    )
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
      level="3" version="2"><model id="rate_rule_state">
      <listOfCompartments><compartment id="cell" size="1" constant="true"/></listOfCompartments>
      <listOfSpecies>
        <species id="X" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
        <species id="Y" compartment="cell" initialAmount="3" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
        <species id="Z" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      </listOfSpecies>
      <listOfRules><rateRule variable="X">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><minus/><ci>X</ci></apply></math>
      </rateRule></listOfRules>
      {reactions}
    </model></sbml>"""


def _validated_document(text):
    document = libsbml.readSBMLFromString(text)
    document.checkConsistency()
    errors = [
        (document.getError(i).getErrorId(), document.getError(i).getMessage())
        for i in range(document.getNumErrors())
        if document.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors
    return document


@pytest.mark.parametrize(
    "ordinary_reaction", [False, True], ids=["rate-rule-only", "mixed"]
)
def test_rate_rule_export_is_valid_and_preserves_source_execution(
    tmp_path, ordinary_reaction
):
    source = _source(ordinary_reaction)
    _validated_document(source)
    oracle = roadrunner.RoadRunner(source)
    oracle.integrator.setValue("relative_tolerance", 1e-9)
    oracle.integrator.setValue("absolute_tolerance", 1e-12)
    expected = oracle.simulate(0, 2, 21, selections=["time", "X", "Y", "Z"])
    np.testing.assert_allclose(expected[:, 1], 2 * np.exp(-expected[:, 0]), rtol=1e-7)
    result = Atomizer(atomize=False, quiet_mode=True).atomize(source)
    assert result.success, result.error
    model = cpp.parse_string(result.bngl)
    network = cpp.generate_network(model, max_iter=5)
    output = tmp_path / "rate.xml"
    cpp.io.write_sbml(model, network, str(output))
    written_document = _validated_document(output.read_text())
    written = written_document.getModel()
    rate_rules = [r for r in written.getListOfRules() if r.isRate()]
    assert len(rate_rules) == 1
    target = rate_rules[0].getVariable()
    assert written.getNumReactions() == int(ordinary_reaction)
    for reaction in written.getListOfReactions():
        participants = list(reaction.getListOfReactants()) + list(
            reaction.getListOfProducts()
        )
        assert all(p.getSpecies() != target for p in participants)
    consumer = roadrunner.RoadRunner(output.read_text())
    consumer.integrator.setValue("relative_tolerance", 1e-9)
    consumer.integrator.setValue("absolute_tolerance", 1e-12)
    actual = consumer.simulate(0, 2, 21, selections=["time", "X", "Y", "Z"])
    np.testing.assert_allclose(actual, expected, rtol=2e-6, atol=1e-8)
