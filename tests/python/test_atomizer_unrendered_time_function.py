from bionetgen.atomizer.bngModel import Function, bngModel


def _unrendered_function(definition: str) -> Function:
    function = Function()
    function.Id = "f()"
    function.definition = definition
    return function


def test_unrendered_function_definition_still_detects_time_symbol():
    model = bngModel()
    model.functions["f()"] = _unrendered_function("TIME_ + 1")

    model.check_for_time_function()

    assert model.add_time
    assert "time_" in model.molecules


def test_unrendered_function_without_time_does_not_add_clock():
    model = bngModel()
    model.functions["f()"] = _unrendered_function("k3_r + 1")

    model.check_for_time_function()

    assert not model.add_time
    assert "time_" not in model.molecules


def test_function_serialization_preserves_adjusted_definition():
    function = _unrendered_function("k3_r")

    assert str(function) == "f() = k3_r"
    assert function.adjusted_def == "k3_r"
