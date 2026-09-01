"""Source-derived contracts for the Playground parameter-curation facade."""

from collections import OrderedDict

from bionetgen.atomizer.modern import (
    SBMLParameter,
    curateParameters,
    curate_parameters,
)
from bionetgen.atomizer.modern.helpers import logger


def test_curate_parameters_rewrites_nonfinite_values_and_standardizes_ids():
    parameters = OrderedDict(
        [
            ("kInf", SBMLParameter(id="kInf", value=float("inf"))),
            ("kNegInf", SBMLParameter(id="kNegInf", value=float("-inf"))),
            ("kNaN", SBMLParameter(id="kNaN", value=float("nan"))),
            ("time", SBMLParameter(id="time", value=2.5)),
        ]
    )

    logger.clear()
    curated = curate_parameters(parameters)

    assert list(curated) == ["kInf", "kNegInf", "kNaN", "time_id"]
    assert curated["kInf"] == "1e20"
    assert curated["kNegInf"] == "-1e20"
    assert curated["kNaN"] == "0"
    assert curated["time_id"] == "2.5"
    assert any(
        message.code == "BNW001" and "kNaN" in message.message
        for message in logger.getMessages()
    )
    logger.clear()


def test_curate_parameters_camel_case_alias_matches_snake_case():
    parameters = {"k": SBMLParameter(id="k", value=3)}

    assert curateParameters(parameters) == curate_parameters(parameters)
