"""Regression tests for a compartment size that a rule determines at t=0.

SBML Level 3 Version 2 Core (Sec. 4.8.5, *Compartment*) says that a
compartment's ``size`` attribute sets its initial size, and that "if the
compartment's attribute ``constant`` has the value ``false``, the size value
may be overridden by an InitialAssignment or changed by an AssignmentRule or
AlgebraicRule, and in addition, for simulation time *t* > 0, it may also be
changed by a RateRule or Event".

An assignment rule therefore determines the compartment's size at *every*
time, including ``t = 0``, and the ``size`` attribute is ignored.  A species
whose initial value is a concentration has an *amount* of
``concentration * size``, so the seed of such a species has to use the
assignment rule's value and not the ignored attribute.

The official SBML Test Suite case ``semantic/01121`` checks exactly this: its
compartment ``comp2`` declares ``size="2"`` but an assignment rule sets it to
``k4``, which is 1 at ``t = 0``.
"""

from __future__ import annotations

import re

from bionetgen.atomizer.modern import Atomizer

_MODEL = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="compartment_rule_size">
    <listOfCompartments>
      <compartment id="comp" spatialDimensions="3" size="5" constant="false"/>
      <compartment id="comp2" spatialDimensions="3" size="2" constant="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="comp" initialAmount="1"
               hasOnlySubstanceUnits="false" constant="false"/>
      <species id="S2" compartment="comp2" initialConcentration="3"
               hasOnlySubstanceUnits="false" constant="false"/>
      <species id="S3" compartment="comp2" initialAmount="4"
               hasOnlySubstanceUnits="true" boundaryCondition="true"
               constant="false"/>
      <species id="S4" compartment="comp2" initialConcentration="2"
               hasOnlySubstanceUnits="true" constant="true"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k4" value="1" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="comp">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn> 1 </cn></math>
      </rateRule>
      <assignmentRule variable="comp2">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><ci> k4 </ci></math>
      </assignmentRule>
      <rateRule variable="k4">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><ci> time </ci></math>
      </rateRule>
    </listOfRules>
  </model>
</sbml>"""


def _atomize() -> str:
    result = Atomizer(atomize=False, quiet_mode=True).atomize(_MODEL)
    assert result.success, result.error
    return result.bngl


def _seed_amount(bngl: str, pattern: str) -> float:
    match = re.search(rf"^\s*{re.escape(pattern)}\s+(\S+)\s*$", bngl, re.MULTILINE)
    assert match is not None, f"no seed for {pattern} in\n{bngl}"
    return float(match.group(1))


def test_assignment_rule_replaces_the_ignored_size_attribute_at_t0():
    """The official reference first row for ``semantic/01121``.

    ``S2`` starts at a concentration of 3 in ``comp2``, whose size is 1 at
    ``t = 0`` because the assignment rule ``comp2 = k4`` overrides the
    declared ``size="2"``.
    """

    bngl = _atomize()

    assert _seed_amount(bngl, "@comp2:M_S2()") == 3.0
    assert _seed_amount(bngl, "@comp2:$M_S4()") == 2.0
    # ``comp`` keeps its declared size: a rate rule starts from the
    # attribute value and only changes the derivative.
    assert _seed_amount(bngl, "@comp:M_S1()") == 1.0


def test_assignment_ruled_compartment_size_is_not_the_declared_attribute():
    bngl = _atomize()

    assert "@comp2:M_S2() 6" not in bngl
    assert "@comp2:$M_S4() 4" not in bngl
