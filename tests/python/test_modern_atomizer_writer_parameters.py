"""Source-derived contracts for the Playground parameter-curation facade."""

from collections import OrderedDict

from bionetgen.atomizer.modern import (
    SBMLCompartment,
    SBMLFunctionDefinition,
    SBMLModel,
    SBMLParameter,
    SBMLRule,
    curateParameters,
    curate_parameters,
    write_functions,
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


def test_write_functions_can_retain_parameterized_definitions_on_request():
    """Mirror Playground writeFunctions(..., keepParameterized=true)."""

    model = SBMLModel(
        id="parameterized",
        function_definitions={
            "f": SBMLFunctionDefinition(id="f", arguments=["x"], math="x + 1")
        },
    )

    assert write_functions(model) == []
    assert write_functions(model, keep_parameterized=True) == [
        "f(_farg0_x) = _farg0_x + 1"
    ]


def test_write_functions_maps_compartment_references_in_function_bodies():
    """Mirror Playground mapCompartments for definitions and assignment rules."""

    model = SBMLModel(
        id="compartment-functions",
        compartments={"cytosol": SBMLCompartment(id="cytosol", size=2)},
        parameters={"k": SBMLParameter(id="k", value=3)},
        function_definitions={
            "rate": SBMLFunctionDefinition(id="rate", math="cytosol * k")
        },
        rules=[SBMLRule(type="assignment", variable="flux", math="cytosol * k")],
    )

    assert write_functions(model) == [
        "rate() = __compartment_cytosol__ * k",
        "flux() = __compartment_cytosol__ * 3",
    ]


def test_write_functions_orders_assignment_rules_by_dependencies():
    """Mirror Playground's stable topological ordering of assignment rules."""

    model = SBMLModel(
        id="ordered-rules",
        rules=[
            SBMLRule(type="assignment", variable="downstream", math="upstream + 1"),
            SBMLRule(type="assignment", variable="upstream", math="2"),
        ],
    )

    assert write_functions(model) == [
        "upstream() = 2",
        "downstream() = upstream + 1",
    ]
