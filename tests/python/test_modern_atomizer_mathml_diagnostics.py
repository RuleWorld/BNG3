"""Governed diagnostics for MathML operators with no BNGL equivalent.

``_mathml_to_formula`` passes an unknown ``<apply>`` operator through as a
function call of the same name.  BNGL's builtin table (27 names) does not
contain those names, so the generated expression cannot be evaluated.  The
parser has to say so instead of emitting a model that looks translatable.
"""

from __future__ import annotations

from bionetgen.atomizer.modern import SBMLParser

MATHML_NS = "http://www.w3.org/1998/Math/MathML"


def _model_with_kinetic_math(math_body: str) -> str:
    return f"""<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="mathml_case">
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.5" constant="true"/>
      <parameter id="x" value="2" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="{MATHML_NS}">{math_body}</math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""


def _mathml_warnings(math_body: str):
    return [
        record
        for record in SBMLParser()
        .parse(_model_with_kinetic_math(math_body))
        .import_warnings
        if record["category"] == "mathml"
    ]


def test_extended_trigonometric_operator_is_reported():
    warnings = _mathml_warnings(
        "<apply><times/><ci>k</ci><apply><arcsec/><ci>x</ci></apply></apply>"
    )

    assert [
        warning["message"] for warning in warnings if "arcsec" in warning["message"]
    ]
    assert all(warning["severity"] == "approximated" for warning in warnings)


def test_log_with_explicit_base_is_reported():
    warnings = _mathml_warnings(
        "<apply><log/><logbase/><cn>2</cn><apply><ln/><ci>x</ci></apply></apply>"
    )

    assert [warning["message"] for warning in warnings if "log" in warning["message"]]


def test_supported_operators_are_not_reported():
    body = (
        "<apply><times/><ci>k</ci>"
        "<apply><plus/>"
        "<apply><arctanh/><ci>x</ci></apply>"
        "<apply><log/><logbase><cn>10</cn></logbase><ci>x</ci></apply>"
        "</apply></apply>"
    )

    assert _mathml_warnings(body) == []
    model = SBMLParser().parse(_model_with_kinetic_math(body))
    assert model.reactions["R1"].kinetic_law.math == "k * (atanh(x) + log10(x))"


def test_mathml_hyperbolic_arc_names_map_onto_bngl_builtins():
    for mathml_name, bngl_name in (
        ("arcsinh", "asinh"),
        ("arccosh", "acosh"),
        ("arctanh", "atanh"),
    ):
        model = SBMLParser().parse(
            _model_with_kinetic_math(
                f"<apply><plus/><apply><{mathml_name}/><ci>x</ci></apply>"
                f"<ci>k</ci></apply>"
            )
        )

        assert model.reactions["R1"].kinetic_law.math == f"{bngl_name}(x) + k"
        assert not [
            record for record in model.import_warnings if record["category"] == "mathml"
        ]
