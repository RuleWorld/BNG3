"""Severity of the unrecognised-SBML-package diagnostic.

A declared Level 3 package whose elements all sit inside a core
``<annotation>`` container carries no kinetic structure, so the atomized model
is complete and the diagnostic must not be a simulation limitation.  A package
element outside ``<annotation>`` is real structure this importer does not
model, and stays ``dropped``.
"""

from __future__ import annotations

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
