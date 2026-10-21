"""Regression tests for the SBML ``time`` csymbol next to a symbol named ``time``.

SBML Level 3 Version 2 Core defines the ``time`` csymbol in the MathML
namespace (Sec. 3.4.6, *Use of csymbol elements in MathML expressions in
SBML*): it denotes "the current simulation time".  A
model may still declare a parameter whose ``id`` is ``time`` -- Sec. 3.1.7
(*Type SId*) reserves no identifiers, and the csymbol's name lives in the MathML
namespace, not in the model's symbol namespace.

The two must stay distinguishable.  The official SBML Test Suite cases
``semantic/01820`` and ``semantic/01821`` exist to check exactly this: their
initial assignment ``a = time`` reads the *parameter* named ``time`` (value
10), while their initial assignment ``d = <csymbol .../symbols/time>`` reads
the *simulation time*, which is 0 when the initial values are established
(Sec. 3.4.8, *Initial conditions and special considerations*, and Sec. 3.4.7,
*Simulation time*).
"""

from __future__ import annotations

import re

from bionetgen.atomizer.modern import Atomizer

_MODEL = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="time_symbol">
    <listOfParameters>
      <parameter id="time" value="10" constant="true"/>
      <parameter id="Time" value="11" constant="true"/>
      <parameter id="TIME" value="12" constant="true"/>
      <parameter id="a" constant="true"/>
      <parameter id="b" constant="true"/>
      <parameter id="c" constant="true"/>
      <parameter id="d" constant="true"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="a">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><ci> time </ci></math>
      </initialAssignment>
      <initialAssignment symbol="b">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><ci> Time </ci></math>
      </initialAssignment>
      <initialAssignment symbol="c">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><ci> TIME </ci></math>
      </initialAssignment>
      <initialAssignment symbol="d">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <csymbol encoding="text"
                   definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol>
        </math>
      </initialAssignment>
    </listOfInitialAssignments>
  </model>
</sbml>"""


def _atomize() -> str:
    result = Atomizer(atomize=False, quiet_mode=True).atomize(_MODEL)
    assert result.success, result.error
    return result.bngl


def _parameter(bngl: str, name: str) -> float:
    match = re.search(rf"^\s*{re.escape(name)}\s+(\S+)\s*$", bngl, re.MULTILINE)
    assert match is not None, f"no parameter {name} in\n{bngl}"
    return float(match.group(1))


def test_csymbol_time_is_the_simulation_time_not_the_parameter():
    """The official reference for ``semantic/01821``.

    ``d`` is assigned the ``time`` csymbol, so it takes the simulation time,
    which is 0 while the initial values are established.  It must not take the
    value 10 of the parameter that happens to be named ``time``.
    """

    bngl = _atomize()

    assert _parameter(bngl, "d") == 0.0


def test_csymbol_time_reference_reads_the_parameter_named_time():
    """``a = time`` reads the model's parameter, not the csymbol."""

    bngl = _atomize()

    assert _parameter(bngl, "a") == 10.0
    assert _parameter(bngl, "b") == 11.0
    assert _parameter(bngl, "c") == 12.0
