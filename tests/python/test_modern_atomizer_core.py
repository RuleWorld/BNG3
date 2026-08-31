"""Source-derived contracts for the Playground atomization-core facade."""

from bionetgen.atomizer.modern import (
    addToDependencyGraph,
    add_to_dependency_graph,
    defineEditDistanceMatrix,
    findLongestSubstring,
)


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
