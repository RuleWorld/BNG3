"""Severity of the unrecognised-SBML-package diagnostic.

A declared Level 3 package whose elements all sit inside a core
``<annotation>`` container carries no kinetic structure, so the atomized model
is complete and the diagnostic must not be a simulation limitation.  A package
element outside ``<annotation>`` is real structure this importer does not
model, and stays ``dropped``.
"""

from __future__ import annotations

import pytest

from bionetgen.atomizer.modern import SBMLParser

_ANNOTATION_BODY = """
    <listOfParameters>
      <parameter id="k" value="0.5" constant="true">
{annotation}      </parameter>
    </listOfParameters>"""


def _annotation_sbml(prefix: str, uri: str, element: str) -> str:
    """Core model whose only package element is inside ``<annotation>``."""
    annotation = (
        f"        <annotation>\n"
        f"          <{prefix}:{element} "
        f'xmlns:{prefix}="{uri}"/>\n'
        f"        </annotation>\n"
    )
    return f"""<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:{prefix}="{uri}"
      level="3" version="1">
  <model id="annotated">
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialAmount="2"
               hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math>
        </kineticLaw>
      </reaction>
    </listOfReactions>{_ANNOTATION_BODY.format(annotation=annotation)}  </model>
</sbml>"""


FBAM_URI = "http://www.sbml.org/sbml/level3/version1/fbam/version2"
SBO_URI = "http://www.sbml.org/sbml/level3/version1/sbo/version2"
TOPOLOGY_URI = "http://www.sbml.org/sbml/level3/version1/topology/version1"
REQ_URI = "http://www.sbml.org/sbml/level3/version1/req/version1"
SPATIAL_URI = "http://www.sbml.org/sbml/level3/version1/spatial/version1"


def _fbam_sbml() -> str:
    return _annotation_sbml("fbam", FBAM_URI, "Entity")


def _sbo_sbml() -> str:
    return _annotation_sbml("sbo", SBO_URI, "Term")


def _topology_sbml() -> str:
    return f"""<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:topology="{TOPOLOGY_URI}"
      level="3" version="1">
  <model id="semantic">
    <topology:interaction id="link1" sboTerm="FMA:0000000"/>
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialAmount="2"
               hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math>
        </kineticLaw>
      </reaction>
    </listOfReactions>{_ANNOTATION_BODY.format(annotation="")}  </model>
</sbml>"""


def _package_warning(model, package: str):
    return next(
        record
        for record in model.import_warnings
        if record["category"] == f"package:{package}"
    )


def test_fbam_annotation_namespace_is_not_a_simulation_limitation():
    model = SBMLParser().parse(_fbam_sbml())

    assert model.reactions, "the core kinetic model must still atomize"
    warning = _package_warning(model, "fbam")
    assert warning["severity"] != "dropped"
    assert warning["severity"] == "info"
    assert "does not affect the mathematical model" in warning["message"]


def test_sbo_annotation_namespace_is_not_a_simulation_limitation():
    model = SBMLParser().parse(_sbo_sbml())

    assert model.reactions
    warning = _package_warning(model, "sbo")
    assert warning["severity"] == "info"


def test_top_level_package_element_stays_dropped():
    model = SBMLParser().parse(_topology_sbml())

    warning = _package_warning(model, "topology")
    assert warning["severity"] == "dropped"
    assert "missing from the atomized model" in warning["message"]


def test_package_with_both_annotation_and_top_level_elements_stays_dropped():
    sbml = _topology_sbml().replace(
        '<topology:interaction id="link1" sboTerm="FMA:0000000"/>',
        '<topology:interaction id="link1" sboTerm="FMA:0000000"/>\n'
        "    <listOfParameters>\n"
        '      <parameter id="k" value="0.5" constant="true">\n'
        "        <annotation>\n"
        f'          <topology:interaction xmlns:topology="{TOPOLOGY_URI}"'
        ' id="link2" sboTerm="FMA:0000000"/>\n'
        "        </annotation>\n"
        "      </parameter>\n"
        "    </listOfParameters>",
    )
    model = SBMLParser().parse(sbml)

    warning = _package_warning(model, "topology")
    assert warning["severity"] == "dropped"
    assert warning["count"] == 2


def test_required_attribute_does_not_choose_the_severity():
    """``:required="true"`` on an annotation-only namespace is not a defect."""
    sbml = _fbam_sbml().replace(
        'level="3" version="1">', 'level="3" version="1" fbam:required="true">'
    )
    model = SBMLParser().parse(sbml)

    assert _package_warning(model, "fbam")["severity"] == "info"


def test_required_false_semantic_package_is_still_dropped():
    sbml = _topology_sbml().replace(
        'level="3" version="1">', 'level="3" version="1" topology:required="false">'
    )
    model = SBMLParser().parse(sbml)

    assert _package_warning(model, "topology")["severity"] == "dropped"


def _req_sbml(
    req_markup: str,
    spatial_declaration: str = "",
    spatial_reaction_attributes: str = "",
) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:req="{REQ_URI}" level="3" version="1" req:required="false"
      {spatial_declaration}>
  <model id="req_boundary">
    <listOfCompartments><compartment id="cell" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies><species id="A" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="true"/></listOfSpecies>
    <listOfParameters><parameter id="k" value="0.5" constant="true"/></listOfParameters>
    <listOfReactions><reaction id="R1" reversible="false" fast="false" {spatial_reaction_attributes}>
      <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
      <kineticLaw>
        <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math>
        {req_markup}
      </kineticLaw>
    </reaction></listOfReactions>
  </model>
</sbml>"""


def test_req_changed_math_fails_closed_on_math_bearing_sbase():
    sbml = _req_sbml(
        "<req:listOfChangedMaths>"
        f'<req:changedMath changedBy="{SPATIAL_URI}" '
        'viableWithoutChange="false"/>'
        "</req:listOfChangedMaths>",
        spatial_declaration=(f'xmlns:spatial="{SPATIAL_URI}" spatial:required="true"'),
        spatial_reaction_attributes='spatial:isLocal="false"',
    )
    libsbml = pytest.importorskip("libsbml")
    document = libsbml.readSBMLFromString(sbml)
    errors = [document.getError(index) for index in range(document.getNumErrors())]
    # libSBML 5.21 lacks this retired package plugin. Its only diagnostic is
    # the expected package-unavailable warning; the Core document is valid.
    assert [error.getErrorId() for error in errors] == [99108]
    assert errors[0].getSeverity() == libsbml.LIBSBML_SEV_WARNING

    with pytest.raises(ValueError, match=r"req.*changedMath"):
        SBMLParser().parse(sbml)


def test_req_namespace_without_changed_math_remains_informational():
    model = SBMLParser().parse(_req_sbml(""))

    assert model.reactions
    assert _package_warning(model, "req")["severity"] == "info"


def test_req_marker_markup_inside_annotation_is_not_treated_as_package_content():
    annotation = (
        "<annotation><req:listOfChangedMaths>"
        f'<req:changedMath changedBy="{SPATIAL_URI}" '
        'viableWithoutChange="false"/>'
        "</req:listOfChangedMaths></annotation>"
    )
    model = SBMLParser().parse(_req_sbml(annotation))

    assert model.reactions
    assert _package_warning(model, "req")["severity"] == "info"
