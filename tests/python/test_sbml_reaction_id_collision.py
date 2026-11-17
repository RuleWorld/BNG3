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
