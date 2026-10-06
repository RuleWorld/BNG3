import time
import copy

class Molecule:
    def __init__(self, name):
        self.name = name
    def copy(self):
        return Molecule(self.name)

class Species:
    def __init__(self):
        self.molecules = [Molecule("M1"), Molecule("M2")]
    def copy(self):
        s = Species()
        s.molecules = [m.copy() for m in self.molecules]
        return s

def run_benchmark():
    translator = {"A": Species(), "B": Species()}

    t0 = time.time()
    for _ in range(50000):
        newTranslator = {}
        for k in translator:
            newTranslator[k] = copy.deepcopy(translator[k])
    t1 = time.time()

    t2 = time.time()
    for _ in range(50000):
        newTranslator = {}
        for k in translator:
            newTranslator[k] = translator[k].copy()
    t3 = time.time()

    print(f"Deepcopy: {t1-t0}s")
    print(f"Custom copy: {t3-t2}s")

run_benchmark()
