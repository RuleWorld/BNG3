import time
import copy

def run_analyze_benchmark():
    differences = ["A", "B", "C", "D", "E"]

    t0 = time.time()
    for _ in range(100000):
        diff_copy = copy.deepcopy(differences)
    t1 = time.time()

    t2 = time.time()
    for _ in range(100000):
        diff_copy = list(differences)
    t3 = time.time()

    print(f"Deepcopy list: {t1-t0}s")
    print(f"List comp: {t3-t2}s")

run_analyze_benchmark()
