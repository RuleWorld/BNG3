"""Source-derived contracts for the Playground atomizer helper surface."""

from __future__ import annotations


def test_playground_helpers_counter_and_default_dict_contract():
    from bionetgen.atomizer.modern import Counter, DefaultDict

    counts = Counter(["A", "A", "B"])
    assert counts.getCount("A") == 2
    assert counts.getCount("missing") == 0
    assert counts.mostCommon(1) == [("A", 2)]
    assert counts.total() == 3
    assert sorted(counts.elements()) == ["A", "A", "B"]

    counts.subtract(["A", "C"])
    assert counts.getCount("A") == 1
    assert counts.getCount("C") == -1

    values = DefaultDict(list)
    values.get("species").append("A")
    assert values.get("species") == ["A"]
    assert values.get("new") == []
    assert "new" in values


def test_playground_helpers_string_and_math_contract():
    from bionetgen.atomizer.modern import (
        cleanParameterValue,
        convertMathFunction,
        levenshtein,
        similarity,
        standardizeName,
    )

    assert levenshtein("kitten", "sitting") == 3
    assert similarity("same", "same") == 1
    assert standardizeName("1 alpha-beta") == "_1_alpha_beta"
    assert convertMathFunction("pow(a, b)") == "((a)^(b))"
    assert convertMathFunction("sqrt(x)") == "((x)^(1/2))"
    assert convertMathFunction("root(2, x)") == "((x)^(1/(2)))"
    assert convertMathFunction("log(10, x)") == "(ln(x)/ln(10))"
    assert convertMathFunction("log(x)") == "ln(x)"
    assert convertMathFunction("log10(x)") == "(ln(x)/ln(10))"
    assert convertMathFunction("gt(a, b) and not(c)") == "(a > b) && (!c)"
    assert convertMathFunction("ceil(x)") == (
        "min(rint((x)+0.5),rint((x)+1))"
    )
    assert cleanParameterValue("Infinity NaN 1E-3 Vmax_2E1") == (
        "1e20 0 1e-3 Vmax_2E1"
    )


def test_playground_rate_rule_prefix_contract():
    from bionetgen.atomizer.modern.rate_rule_constants import (
        RATE_RULE_META_PREFIX,
        SYNTH_RATE_RULE_SPECIES_PREFIX,
    )

    assert RATE_RULE_META_PREFIX == "__rate_rule__"
    assert SYNTH_RATE_RULE_SPECIES_PREFIX == "__rate_rule_state__"


def test_playground_helper_logger_has_source_level_filtering():
    from bionetgen.atomizer.modern import logger

    logger.clear()
    logger.setLevel("DEBUG")
    logger.setQuietMode(True)
    try:
        logger.debug("DBG001", "debug message")
        logger.error("ERR001", "error message")
        messages = logger.getMessages()
        assert [(item.level, item.code) for item in messages] == [
            ("DEBUG", "DBG001"),
            ("ERROR", "ERR001"),
        ]
        assert logger.hasErrors()
    finally:
        logger.clear()
        logger.setLevel("WARNING")
        logger.setQuietMode(False)
