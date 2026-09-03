"""Source-derived contracts for Playground writer rate helpers."""

from bionetgen.atomizer.modern import (
    ReversibleRateSplit,
    SBMLFunctionDefinition,
    inlineSBMLFunctions,
    inline_sbml_functions,
    splitReversibleRate,
    split_reversible_rate,
)


def test_inline_sbml_functions_substitutes_formals_simultaneously():
    definitions = {
        "f": SBMLFunctionDefinition(id="f", arguments=["x", "y"], math="x + y"),
    }

    result = inline_sbml_functions("f(y, 2)", definitions)

    assert result == "((y) + (2))"
    assert inlineSBMLFunctions("f(1, g(2))", definitions) == "((1) + (g(2)))"


def test_inline_sbml_functions_expands_nested_calls_and_keeps_unknown_calls():
    definitions = {
        "outer": SBMLFunctionDefinition(
            id="outer", arguments=["value"], math="inner(value)"
        ),
        "inner": SBMLFunctionDefinition(id="inner", arguments=["x"], math="x^2"),
    }

    assert inline_sbml_functions("outer(a) + missing(a)", definitions) == (
        "((((a))^2)) + missing(a)"
    )


def test_split_reversible_rate_returns_reference_shaped_forward_and_reverse_laws():
    result = splitReversibleRate("(kf*A - kr*B)")

    assert isinstance(result, ReversibleRateSplit)
    assert result.success is True
    assert result.forward_rate == "kf*A"
    assert result.reverse_rate == "kr*B"
    assert result.forwardRate == result.forward_rate
    assert result.reverseRate == result.reverse_rate


def test_split_reversible_rate_rejects_one_sided_and_preserves_original_input():
    result = split_reversible_rate("  kf*A  ")

    assert result == ReversibleRateSplit(False, "  kf*A  ", "0")


def test_playground_writer_facade_exports_reference_function_names():
    import bionetgen.atomizer.modern as modern

    assert modern.bnglFunction is modern.bngl_function
    assert modern.generateBNGL is modern.generate_bngl
