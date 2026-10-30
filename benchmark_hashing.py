import time
import random
from bionetgen.atomizer.atomizer.resolveSCT import SCTSolver
from tests.python.test_resolveSCT_hash_perf import OriginalSCTSolver

random.seed(42)
graphs = []
for _ in range(1000):
    graph = {}
    for i in range(20):
        key = f"K{i}"
        graph[key] = []
        for j in range(random.randint(0, 5)):
            sublist = [f"K{random.randint(0, 19)}" for _ in range(random.randint(1, 4))]
            graph[key].append(sublist)
    graphs.append(graph)

old = OriginalSCTSolver()
new = SCTSolver(None)

start = time.time()
for g in graphs:
    old.make_key_from_graph(g)
old_time = time.time() - start

start = time.time()
for g in graphs:
    new.make_key_from_graph(g)
new_time = time.time() - start

print(f"Old time: {old_time:.4f}s")
print(f"New time: {new_time:.4f}s")
print(f"Speedup: {old_time / new_time:.2f}x")
