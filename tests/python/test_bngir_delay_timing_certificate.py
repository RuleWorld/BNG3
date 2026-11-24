"""Delayed versus immediate completion is a decisive process difference."""

import bionetgen
from bionetgen.model import _cpp


def _model(delayed: bool):
    rule = "A() -> B() k delay=tau" if delayed else "A() -> B() k"
    return bionetgen.BioNetGenModel(
        _cpp.parse_string(
            "begin model\n"
            "begin parameters\n  k 1\n  tau 2\nend parameters\n"
            "begin molecule types\n  A()\n  B()\nend molecule types\n"
            "begin seed species\n  A() 10\nend seed species\n"
            f"begin reaction rules\n  {rule}\nend reaction rules\n"
            "end model\n"
        )
    )


def test_delayed_completion_is_not_equal_to_immediate_completion():
    assert bionetgen.semantic_equal(_model(True), _model(False)) is False
