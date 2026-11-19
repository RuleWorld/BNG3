"""Detector: NET export is a lossy consumer for native SBML events (#163/#1059).

The BNG2 ``.net`` grammar contains only parameters, species, reactions and
groups; it has no trigger, event or event-assignment construct.  A product that
silently wrote a ``.net`` file for a model with native events would therefore
lose the event semantics without any diagnostic.  BNG3 fails closed instead.

This is a detector-only contract: it records the explicit refusal, the
representability evidence from a real ``.net`` artifact, and the fact that the
event survives SBML -> BNGL lowering (so the loss is confined to NET export).
No product file is changed.
"""

from __future__ import annotations

import libsbml

from _extdep import require_extension

require_extension()

import bionetgen
from bionetgen.atomizer.modern import Atomizer

_PLAIN_BNGL = """begin model
begin parameters
 k 1
end parameters
begin molecule types
 A()
end molecule types
begin seed species
 A() 10
end seed species
begin observables
 Molecules X A()
end observables
begin reaction rules
 A() -> 0 k
end reaction rules
end model
"""

_EVENT_BNGL = """begin model
begin parameters
 k 1
end parameters
begin molecule types
 A()
end molecule types
begin seed species
 A() 10
end seed species
begin observables
 Molecules X A()
end observables
begin reaction rules
 A() -> 0 k
end reaction rules
begin bng3_events version 1
 event "reset"
 trigger: X <= 5
 initial_value: false
 persistent: true
 use_values_from_trigger_time: true
 assignment: X = 1
 end event
end bng3_events
end model
"""

# A state-dependent trigger on a bimolecular system has no closed-form
# crossing time, so the Atomizer routes it to the native bng3_events runtime
# instead of folding it into a fixed schedule of BNGL actions.
_SBML_WITH_EVENT = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="native_event">
    <listOfCompartments>
      <compartment id="C" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="S2" compartment="C" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="S3" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" value="0.75" constant="true"/>
      <parameter id="k2" value="0.25" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="consume" reversible="false">
        <listOfReactants>
          <speciesReference species="S1" constant="true"/>
          <speciesReference species="S2" stoichiometry="2" constant="true"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="S3" constant="true"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
      <reaction id="release" reversible="false">
        <listOfReactants><speciesReference species="S3" constant="true"/></listOfReactants>
        <listOfProducts>
          <speciesReference species="S1" constant="true"/>
          <speciesReference species="S2" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k2</ci><ci>S3</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="reset" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><lt/><ci>S1</ci><cn>0.75</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="S2">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>
"""


def _load(tmp_path, name: str, text: str):
    path = tmp_path / f"{name}.bngl"
    path.write_text(text, encoding="utf-8")
    return bionetgen.load(str(path))


def test_net_export_refuses_native_events_without_writing_a_partial_file(tmp_path):
    model = _load(tmp_path, "event_model", _EVENT_BNGL)
    out = tmp_path / "event.net"
    try:
        model.write_net(str(out))
    except RuntimeError as exc:
        assert "NET export does not preserve native events" in str(exc)
    else:
        raise AssertionError("NET export silently accepted a model with native events")
    # Fail closed: no artifact that could be mistaken for a complete export.
    assert not out.exists()


def test_real_net_artifact_has_no_event_vocabulary(tmp_path):
    model = _load(tmp_path, "plain_model", _PLAIN_BNGL)
    out = tmp_path / "plain.net"
    model.write_net(str(out))
    text = out.read_text(encoding="utf-8").lower()
    # Positive control: the export really produced a network.
    assert "begin species" in text and "begin reactions" in text
    # Representability limit: none of the event constructs can be expressed.
    for token in ("trigger", "event", "assignment", "delay", "priority"):
        assert token not in text, f".net unexpectedly contains {token!r}"


def test_source_event_survives_sbml_to_bngl_lowering(tmp_path):
    """The loss is specific to NET export, not to SBML -> BNGL lowering."""
    document = libsbml.readSBMLFromString(_SBML_WITH_EVENT)
    errors = [
        document.getError(i).getMessage()
        for i in range(document.getNumErrors())
        if document.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors, errors
    assert document.getModel().getNumEvents() == 1

    translated = Atomizer(atomize=False, quiet_mode=True).atomize(_SBML_WITH_EVENT)
    assert translated.success, translated.error
    assert "begin bng3_events version 1" in translated.bngl
    assert "trigger:" in translated.bngl

    # The same preserved event is then refused by the NET consumer.
    model = _load(tmp_path, "lowered_model", translated.bngl)
    out = tmp_path / "lowered.net"
    try:
        model.write_net(str(out))
    except RuntimeError as exc:
        assert "NET export does not preserve native events" in str(exc)
    else:
        raise AssertionError("NET export silently dropped a lowered SBML event")
    assert not out.exists()
