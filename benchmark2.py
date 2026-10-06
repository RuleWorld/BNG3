import time
import copy
from collections import defaultdict, Counter

def run_counter_dict_benchmark():
    # simulate sbml2bngl.py
    d = {("A", "b"): Counter({"x": 2, "y": 1}), ("B", "c"): Counter({"z": 3}), ("C", "d"): Counter({"w": 1})}

    t0 = time.time()
    for _ in range(100000):
        d1 = copy.deepcopy(d)
        d2 = copy.deepcopy(d)
    t1 = time.time()

    t2 = time.time()
    for _ in range(100000):
        d1 = {k: v.copy() for k, v in d.items()}
        d2 = {k: v.copy() for k, v in d.items()}
    t3 = time.time()

    print(f"Deepcopy: {t1-t0}s")
    print(f"Dict comp with copy: {t3-t2}s")

run_counter_dict_benchmark()
