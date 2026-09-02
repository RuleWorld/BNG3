"""Source-derived contracts for the Playground atomization-core facade."""

from bionetgen.atomizer.modern import (
    addToDependencyGraph,
    add_to_dependency_graph,
    analyze_naming_conventions,
    defineEditDistanceMatrix,
    findLongestSubstring,
    topological_sort,
)
from bionetgen.atomizer.modern.helpers import logger


def test_dependency_graph_insertion_is_unique_and_accepts_scalar_or_list():
    graph = {}

    addToDependencyGraph(graph, "complex", ["A", "B", "A"])
    add_to_dependency_graph(graph, "complex", "B")

    assert graph == {"complex": ["A", "B"]}


def test_edit_distance_result_keeps_full_matrix_and_legacy_two_value_unpacking():
    result = defineEditDistanceMatrix(["A", "A_P", "far"], 2)

    assert result.matrix == [[0, 2, 3], [2, 0, 3], [3, 3, 0]]
    assert result.pairs == [("A", "A_P")]
    assert result.differences == [["+ _", "+ P"]]

    pairs, differences = result
    assert pairs == result.pairs
    assert differences == result.differences


def test_longest_substring_alias_matches_playground_name():
    assert findLongestSubstring("abc", "zbcx") == "bc"


def test_playground_topological_sort_reports_dependency_cycles():
    logger.clear()
    logger.setLevel("WARNING")
    logger.setQuietMode(True)
    try:
        sorted_species = topological_sort(
            ["A", "B", "C"],
            {"A": {"B"}, "B": {"A"}, "C": {"A"}},
        )
        warnings = logger.getMessagesByLevel("WARNING")
    finally:
        logger.clear()
        logger.setQuietMode(False)

    assert sorted_species == ["B", "A", "C"]
    assert len(warnings) == 1
    assert warnings[0].code == "DEP001"
    assert "A -> B -> A" in warnings[0].message


def test_playground_naming_analysis_reports_summary():
    logger.clear()
    logger.setLevel("INFO")
    logger.setQuietMode(True)
    try:
        analyze_naming_conventions(["A", "A_P"])
        messages = logger.getMessagesByLevel("INFO")
    finally:
        logger.clear()
        logger.setQuietMode(False)

    assert len(messages) == 1
    assert messages[0].code == "NAM001"
    assert messages[0].message == "Naming analysis: 1 similar pairs, 1 classifications"
