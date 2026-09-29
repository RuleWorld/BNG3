"""Tokenizer runs for a raw SBML id that carries a hyphen.

``standardize_name`` runs on a raw SBML id only at emission, so a delay whose
MathML is a single ``<ci> A-B </ci>`` reaches event analysis in its source
spelling.  The formula tokenizer has to keep that id whole: split, the delay is
read as the difference ``A - B`` and the event is scheduled at a fabricated
time.  A genuine difference arrives spaced (``A - B``) because the MathML
reader serialises ``<minus>`` with surrounding spaces, so the two never
collide.
"""

import sys
from xml.etree import ElementTree

import pytest

sys.path.insert(0, "python")

MML = 'xmlns="http://www.w3.org/1998/Math/MathML"'

# ``A`` and ``B`` are distinct declared species and ``A-B`` is a third one.  The
# values are chosen so the declared id and the difference ``A - B`` can never
# agree, which is what makes a misread detectable at all.
SPECIES_VALUES = {"A": 5.0, "B": 1.0, "A-B": 0.25}


def _fold(expression):
    from bionetgen.atomizer.modern.events import fold_numeric

    return fold_numeric(expression, SPECIES_VALUES.get)


def test_hyphenated_id_is_folded_as_one_declared_symbol():
    """``A-B`` is the species ``A-B``; it is not the difference ``A - B``."""

    assert _fold("A-B") == pytest.approx(0.25)


def test_spaced_difference_is_still_a_difference():
    """``A - B`` keeps its arithmetic meaning -- the two spellings differ."""

    assert _fold("A - B") == pytest.approx(4.0)


def test_id_run_stops_at_the_operator_before_it():
    """``2*A-B`` is ``2 * (A-B)``; a run cannot start at the ``2``."""

    assert _fold("2*A-B") == pytest.approx(0.5)


def test_unresolvable_hyphen_run_refuses_rather_than_subtracting():
    """With no ``A-B`` declared the run is not silently read as ``A - B``."""

    from bionetgen.atomizer.modern.events import fold_numeric

    def resolve(identifier):
        return {"A": 5.0, "B": 1.0}.get(identifier)

    assert fold_numeric("A-B", resolve) is None


def test_mathml_product_of_two_and_a_hyphenated_id_stays_a_product():
    """The reader emits ``2 * A-B``; that is twice the species, not ``2A - B``."""

    from bionetgen.atomizer.modern.parser import _mathml_to_formula

    math = ElementTree.fromstring(
        f"<math {MML}><apply><times/><cn>2</cn><ci>A-B</ci></apply></math>"
    )

    assert _mathml_to_formula(math) == "2 * A-B"
    assert _fold("2 * A-B") == pytest.approx(0.5)


def _hyphen_delay_sbml(delay_math):
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="hyphen_delay">
        <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="c" initialAmount="5" hasOnlySubstanceUnits="false" constant="true"/>
          <species id="B" compartment="c" initialAmount="2" hasOnlySubstanceUnits="false" constant="true"/>
          <species id="A-B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="false" constant="false"/>
        </listOfSpecies>
        <listOfReactions><reaction id="produce" reversible="false">
          <listOfProducts><speciesReference species="A-B" stoichiometry="1"/></listOfProducts>
          <kineticLaw><math {MML}><cn>0.1</cn></math></kineticLaw>
        </reaction></listOfReactions>
        <listOfParameters><parameter id="out" value="0" constant="false"/></listOfParameters>
        <listOfEvents><event id="tick">
          <trigger initialValue="true" persistent="true"><math {MML}>
            <apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply>
          </math></trigger>
          <delay><math {MML}>{delay_math}</math></delay>
          <listOfEventAssignments>
            <eventAssignment variable="out"><math {MML}><cn>7</cn></math></eventAssignment>
          </listOfEventAssignments>
        </event></listOfEvents>
      </model>
    </sbml>"""


def _atomize(delay_math):
    from bionetgen.atomizer.modern import Atomizer

    result = Atomizer(quiet_mode=True).atomize(_hyphen_delay_sbml(delay_math))
    assert result.success, result.error
    return result.bngl


def test_hyphenated_id_delay_is_not_scheduled_at_a_fabricated_time():
    """The live defect: ``A-B`` folded to ``5 - 2 == 3`` and fired at ``1 + 3``.

    ``A-B`` is a species with its own trajectory, so the delay is not a
    compile-time constant and the event must be left untranslated.
    """

    bngl = _atomize("<ci> A-B </ci>")

    assert "t_end=>4" not in bngl
    assert "begin actions" not in bngl
    assert "event tick" in bngl


def test_spaced_difference_delay_still_lowers_to_its_arithmetic_value():
    """``<minus>`` of two constant species is a real difference and lowers."""

    bngl = _atomize("<apply><minus/><ci>A</ci><ci>B</ci></apply>")

    assert "t_end=>4" in bngl
