"""Compartment-volume inequality certificates.

Expected outcomes are derived from the SBML/BNGL volume scaling law: a
bimolecular propensity scales with compartment volume, a unimolecular one
does not.
"""

import bionetgen
from bionetgen.bngir import EqualityUndecided
from bionetgen.model import _cpp


def _model(volume: float, bimolecular: bool):
    rule = (
        "A()@cell + A()@cell -> B()@cell k" if bimolecular else "A()@cell -> B()@cell k"
    )
    return bionetgen.BioNetGenModel(
        _cpp.parse_string(
            "begin model\n"
            "begin parameters\n  k 1\nend parameters\n"
            f"begin compartments\n  cell 3 {volume}\nend compartments\n"
            "begin molecule types\n  A()\n  B()\nend molecule types\n"
            "begin seed species\n  A()@cell 10\nend seed species\n"
            f"begin reaction rules\n  {rule}\nend reaction rules\n"
            "end model\n"
        )
    )


def test_bimolecular_volume_difference_is_decided():
    assert bionetgen.semantic_equal(_model(2, True), _model(4, True)) is False


def test_unimolecular_volume_difference_stays_undecided():
    try:
        bionetgen.semantic_equal(_model(2, False), _model(4, False))
    except EqualityUndecided:
        pass
    else:
        raise AssertionError("volume should not scale a unimolecular propensity")
