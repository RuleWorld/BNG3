import time
import os
import sys
import gc

sys.path.insert(0, os.path.abspath("python"))

import tracemalloc
from bionetgen.atomizer.atomizeTool import AtomizeTool
import bionetgen.atomizer.libsbml2bngl
from collections import OrderedDict

# Define the models to benchmark
models = [
    "tests/python/models/mass_action_probe_order.sbml",
    "tests/python/models/scaled_compartment_3_92_picolitre.sbml",
    "tests/python/models/nonreactant_species_rate.sbml",
]

tracemalloc.start()
start = time.time()
for m in models:
    try:
        AtomizeTool(input_file=m).run()
    except Exception as e:
        # Ignore unsupported functions inside these models
        pass

t = time.time() - start
current, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

print(f"Atomizing 3 legacy SBML models took {t:.4f}s")
print(f"Peak memory: {peak / 10**6:.2f} MB")
