import time
import copy

def run_sct_benchmark():
    # simulate deepcopy vs dict comp in resolveSCT.py and analyzeSBML.py

    # dependencyGraph in resolveSCT is a dict of lists of lists of strings
    dependencyGraph = {
        "A": [["a1", "b1"], ["a2", "b2"]],
        "B": [["c1"], ["c2", "d2"]],
        "C": [["e1"]]
    }

    t0 = time.time()
    for _ in range(100000):
        dg_copy = copy.deepcopy(dependencyGraph)
    t1 = time.time()

    t2 = time.time()
    for _ in range(100000):
        dg_copy = {k: [list(y) for y in v] for k, v in dependencyGraph.items()}
    t3 = time.time()

    print(f"Deepcopy graph: {t1-t0}s")
    print(f"Dict comp graph: {t3-t2}s")

run_sct_benchmark()
