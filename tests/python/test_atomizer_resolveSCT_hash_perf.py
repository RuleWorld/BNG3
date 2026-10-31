import marshal
import functools
import random
import time
from copy import deepcopy

import pytest
from bionetgen.atomizer.atomizer.resolveSCT import SCTSolver


class OriginalSCTSolver:
    def make_key_from_graph(self, graph):
        hashable_tuples = []
        if len(graph) == 0:
            return marshal.dumps(hashable_tuples)
        tmpGraph = deepcopy(graph)
        all_elems = set(
            [item[0] for sublist in tmpGraph.values() for item in sublist if item]
        )
        for elem in all_elems:
            try:
                a = tmpGraph[elem]
            except KeyError:
                tmpGraph[elem] = []
        for key in sorted(tmpGraph):
            tmpGraph[key] = functools.reduce(
                lambda x, y: x + y, sorted(tmpGraph[key]), []
            )
        for key in sorted(tmpGraph):
            hashable_tuples.append((key, tuple(tmpGraph[key])))
        hashable_tuples = tuple(hashable_tuples)
        return hashable_tuples.__hash__()


@pytest.fixture(scope="module")
def original_solver():
    return OriginalSCTSolver()


@pytest.fixture(scope="module")
def optimized_solver():
    return SCTSolver(None)


def test_make_key_from_graph_empty(original_solver, optimized_solver):
    graph = {}
    graph_copy = deepcopy(graph)
    # Both serialize to an empty list representation under marshal
    assert (
        marshal.loads(original_solver.make_key_from_graph(graph))
        == marshal.loads(optimized_solver.make_key_from_graph(graph))
        == []
    )
    # The key generation is deterministic
    assert optimized_solver.make_key_from_graph(graph) == optimized_solver.make_key_from_graph(graph)
    assert graph == graph_copy


def test_make_key_from_graph_missing_nodes(original_solver, optimized_solver):
    # Graph where references 'C' and 'D' exist in sublists but aren't keys
    graph = {"A": [["B", "C"]], "B": [["D"]]}
    graph_copy = deepcopy(graph)
    assert original_solver.make_key_from_graph(
        graph
    ) == optimized_solver.make_key_from_graph(graph)
    assert graph == graph_copy


def test_make_key_from_graph_duplicate_dependencies(original_solver, optimized_solver):
    # Duplicate edge combinations
    graph = {"A": [["B", "C"], ["B", "C"], ["B"]], "B": [["C"], ["C"]]}
    graph_copy = deepcopy(graph)
    assert original_solver.make_key_from_graph(
        graph
    ) == optimized_solver.make_key_from_graph(graph)
    assert graph == graph_copy


def test_make_key_from_graph_insertion_order(original_solver, optimized_solver):
    # Dictionaries remember insertion order, sorting should eliminate differences
    graph1 = {"A": [["B"]], "B": [["C"]]}
    graph2 = {"B": [["C"]], "A": [["B"]]}

    hash1 = optimized_solver.make_key_from_graph(graph1)
    hash2 = optimized_solver.make_key_from_graph(graph2)
    assert hash1 == hash2
    assert hash1 == original_solver.make_key_from_graph(graph1)


def test_make_key_from_graph_randomized(original_solver, optimized_solver):
    random.seed(42)  # fixed seed
    for _ in range(100):
        graph = {}
        for i in range(10):
            if random.random() > 0.5:
                continue
            key = f"K{i}"
            graph[key] = []
            for j in range(random.randint(0, 3)):
                sublist = [
                    f"K{random.randint(0, 9)}" for _ in range(random.randint(1, 3))
                ]
                graph[key].append(sublist)

        graph_copy = deepcopy(graph)
        assert original_solver.make_key_from_graph(
            graph
        ) == optimized_solver.make_key_from_graph(graph)
        # Ensure immutability
        assert graph == graph_copy
