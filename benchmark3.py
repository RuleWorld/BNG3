import time
import copy

def run_list_benchmark():
    ruleList = [["A", "B", "C"], ["D"]]

    t0 = time.time()
    for _ in range(100000):
        tmp = copy.deepcopy(ruleList)
    t1 = time.time()

    t2 = time.time()
    for _ in range(100000):
        tmp = [list(x) for x in ruleList]
    t3 = time.time()

    print(f"Deepcopy list: {t1-t0}s")
    print(f"List comp: {t3-t2}s")

run_list_benchmark()
