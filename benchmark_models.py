import time
import os
import sys
import gc

sys.path.insert(0, os.path.abspath("python"))

from bionetgen.atomizer.atomizeTool import AtomizeTool
import tracemalloc

# Run on tests/python/models/Motivating_example.bngl or simple ones? AtomizeTool takes sbml.
# Let's just use the python atomizer's test model to get a measurement as requested.
from tests.python.test_modern_atomizer_sbml_parity import (
    _quadratic_species_difference_multi_delay_model,
)
from bionetgen.atomizer.modern import Atomizer

tracemalloc.start()
model = _quadratic_species_difference_multi_delay_model(rank_two=True)
start = time.time()
for _ in range(50):
    Atomizer(quiet_mode=True, t_end=4, n_steps=40).atomize(model)
t = time.time() - start
current, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

print(f"Atomizing synthetic model 50 times took {t:.4f}s")
print(f"Peak memory: {peak / 10**6:.2f} MB")
