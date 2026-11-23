"""Sound inequivalence certificates for zero-argument functions.

Expected outcomes are derived from the equality contract in
``docs/design/semantic-equal-design.md``: function interpretations are part of
F, so a parameter assignment where they differ decides inequality.
"""

import pytest

import bionetgen
from bionetgen.bngir import EqualityUndecided
from bionetgen.model import _cpp


def _model(body: str):
    return bionetgen.BioNetGenModel(
        _cpp.parse_string(
            "begin model\n"
            "begin parameters\n  k 1\nend parameters\n"
            "begin molecule types\n  A()\n  B()\nend molecule types\n"
            "begin seed species\n  A() 1\nend seed species\n"
            "begin functions\n  f() = " + body + "\nend functions\n"
            "begin reaction rules\n  A() -> B() f()\nend reaction rules\n"
            "end model\n"
        )
    )


def test_rational_function_counterexample_decides_inequality():
    assert bionetgen.semantic_equal(_model("k"), _model("2*k")) is False


def test_identical_functions_remain_equal():
    assert bionetgen.semantic_equal(_model("k"), _model("k")) is True


def test_outside_rational_subset_remains_undecided():
    with pytest.raises(EqualityUndecided):
        bionetgen.semantic_equal(_model("sin(k)"), _model("exp(k)"))
