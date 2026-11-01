"""SBML Core constraints are valid only while their MathML remains true."""

from bionetgen.atomizer.modern import Atomizer, SBMLParser


def _model(constraint_math: str) -> str:
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
      level="3" version="2">
  <model id="constraint_fixture">
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies><species id="A" compartment="c" initialAmount="1"
      hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/></listOfSpecies>
    <listOfConstraints><constraint><math xmlns="http://www.w3.org/1998/Math/MathML">
      {constraint_math}
    </math></constraint></listOfConstraints>
  </model>
</sbml>"""


def _constraint_warning(model):
    return next(
        warning for warning in model.import_warnings if warning.category == "constraint"
    )


def test_always_true_constraint_is_safe_to_flatten_and_execute():
    model = SBMLParser().parse(_model("<true/>"))

    assert not any(w.category == "constraint" for w in model.import_warnings)
    result = Atomizer(quiet_mode=True).atomize(_model("<true/>"))
    assert result.success


def test_constant_relational_constraint_is_folded_exactly():
    model = SBMLParser().parse(_model("<apply><lt/><cn>1</cn><cn>2</cn></apply>"))

    assert not any(w.category == "constraint" for w in model.import_warnings)


def test_rational_constant_is_compared_without_rounding_or_integer_truncation():
    model = SBMLParser().parse(
        _model('<apply><gt/><cn type="rational">1<sep/>2</cn>' "<cn>0.75</cn></apply>")
    )

    warning = _constraint_warning(model)
    assert warning.severity == "dropped"
    assert "false at t=0" in warning.message


def test_e_notation_constant_is_folded_exactly():
    model = SBMLParser().parse(
        _model(
            '<apply><lt/><cn type="e-notation">5<sep/>-1</cn>' "<cn>0.75</cn></apply>"
        )
    )

    assert not any(w.category == "constraint" for w in model.import_warnings)


def test_always_false_constraint_is_rejected_as_invalid_source_state():
    model = SBMLParser().parse(_model("<false/>"))

    warning = _constraint_warning(model)
    assert warning.severity == "dropped"
    assert "false at t=0" in warning.message
    result = Atomizer(quiet_mode=True).atomize(_model("<false/>"))
    assert not result.success


def test_state_dependent_constraint_is_explicitly_unsupported_for_execution():
    model = SBMLParser().parse(_model("<apply><gt/><ci>A</ci><cn>0</cn></apply>"))

    warning = _constraint_warning(model)
    assert warning.severity == "dropped"
    assert "state-dependent" in warning.message
    result = Atomizer(quiet_mode=True).atomize(
        _model("<apply><gt/><ci>A</ci><cn>0</cn></apply>")
    )
    assert not result.success
