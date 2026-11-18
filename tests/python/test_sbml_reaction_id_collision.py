"""Exported SBML reaction ids must not collide with model-wide parameter ids.

SBML has a single identifier namespace for species, parameters and reactions.
BNG3 generates R1, R2, ... for network reactions; a source parameter with the
same spelling previously produced libSBML error 10301 on the written document.
Regression case abstracted from the flat/atomized BioModels campaign where
parameters R5/R7 collided with reactions R5/R7 (BIOMD0000000174).
"""

import libsbml
import pytest
from _extdep import require_extension

from bionetgen.model import BioNetGenModel

cpp = require_extension()

SOURCE = """begin model
begin parameters
  R1 1
  R2 2
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> 0 R1
  A() -> 0 R2
end reaction rules
end model
"""


def _export(tmp_path):
    model = BioNetGenModel(cpp.parse_string(SOURCE))
    network = model.generate_network()
    path = tmp_path / "export.xml"
    cpp.io.write_sbml(model._model, network, str(path))
    return path


def test_exported_reaction_ids_are_valid_sbml(tmp_path):
    path = _export(tmp_path)
    document = libsbml.readSBMLFromFile(str(path))
    document.checkConsistency()
    errors = [
        (document.getError(i).getErrorId(), document.getError(i).getMessage())
        for i in range(document.getNumErrors())
        if document.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors, errors


def test_reaction_ids_do_not_reuse_parameter_ids(tmp_path):
    path = _export(tmp_path)
    document = libsbml.readSBMLFromFile(str(path))
    model = document.getModel()
    parameter_ids = {
        model.getParameter(i).getId() for i in range(model.getNumParameters())
    }
    reaction_ids = {
        model.getReaction(i).getId() for i in range(model.getNumReactions())
    }
    assert not (parameter_ids & reaction_ids), (parameter_ids, reaction_ids)


def test_reaction_ids_do_not_reuse_observable_ids(tmp_path):
    # Atomizer translations of SBML species produce observable-derived
    # parameters named after the source species (e.g. R5/R7 in
    # BIOMD0000000174). Those observable ids share the SBML model-wide
    # namespace with generated reactions; a reaction R<n> must not reuse one.
    source = """begin model
begin parameters
  k1 1
  k2 2
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules R2 A()
end observables
begin reaction rules
  A() -> 0 k1
  A() -> 0 k2
end reaction rules
end model
"""
    model = BioNetGenModel(cpp.parse_string(source))
    network = model.generate_network()
    path = tmp_path / "observable.xml"
    cpp.io.write_sbml(model._model, network, str(path))
    document = libsbml.readSBMLFromFile(str(path))
    document.checkConsistency()
    errors = [
        (document.getError(i).getErrorId(), document.getError(i).getMessage())
        for i in range(document.getNumErrors())
        if document.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors, errors
    m = document.getModel()
    observable_ids = {m.getRule(i).getVariable() for i in range(m.getNumRules())}
    reaction_ids = {m.getReaction(i).getId() for i in range(m.getNumReactions())}
    assert not (observable_ids & reaction_ids), (observable_ids, reaction_ids)


def test_reserved_split_reaction_suffix_is_not_reused(tmp_path):
    # A delayed consuming reaction appends _init/_complete to its id. A source
    # parameter carrying one of those spellings must force a different base.
    source = SOURCE.replace("  R2 2", "  R2 2\n  R1_init 3")
    model = BioNetGenModel(cpp.parse_string(source))
    network = model.generate_network()
    path = tmp_path / "suffix.xml"
    cpp.io.write_sbml(model._model, network, str(path))
    document = libsbml.readSBMLFromFile(str(path))
    document.checkConsistency()
    errors = [
        document.getError(i).getMessage()
        for i in range(document.getNumErrors())
        if document.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors, errors
    ids = {
        document.getModel().getReaction(i).getId()
        for i in range(document.getModel().getNumReactions())
    }
    assert "R1" not in ids, ids
