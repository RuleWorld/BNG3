import time
import copy
from collections import Counter

def run_dict_benchmark():
    # simulate sbml2bngl.py
    d = {("A", "b"): 2, ("B", "c"): 3, ("C", "d"): 1}

    t0 = time.time()
    for _ in range(100000):
        d1 = copy.deepcopy(d)
        d2 = copy.deepcopy(d)
    t1 = time.time()

    t2 = time.time()
    for _ in range(100000):
        d1 = d.copy()
        d2 = d.copy()
    t3 = time.time()

    print(f"Deepcopy: {t1-t0}s")
    print(f"Dict copy: {t3-t2}s")

run_dict_benchmark()
