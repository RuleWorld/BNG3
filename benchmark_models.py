import time
import os
import sys
import gc

sys.path.insert(0, os.path.abspath("python"))

import tracemalloc
from bionetgen.atomizer.atomizeTool import AtomizeTool
from bionetgen.atomizer.modern import Atomizer
from tests.python.test_modern_atomizer_sbml_parity import (
    _quadratic_species_difference_multi_delay_model,
)

tracemalloc.start()
model = _quadratic_species_difference_multi_delay_model(rank_two=True)
start = time.time()
bngl_outputs = []
for _ in range(50):
    result = Atomizer(quiet_mode=True, t_end=4, n_steps=40).atomize(model)
    bngl_outputs.append(result.bngl)
t = time.time() - start
current, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

print(f"Atomizing synthetic model 50 times took {t:.4f}s")
print(f"Peak memory: {peak / 10**6:.2f} MB")
# Sanity check we produced identical models in loop
assert all(b == bngl_outputs[0] for b in bngl_outputs)
