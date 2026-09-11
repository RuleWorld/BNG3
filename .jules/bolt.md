## 2024-03-24 - Python `copy.deepcopy` Performance Bottleneck
**Learning:** `copy.deepcopy()` is a major performance bottleneck in `python/bionetgen/atomizer` when copying small structures like `Molecule`, `Species`, and `Component`.
**Action:** Replace `copy.deepcopy()` with explicit list comprehensions and shallow `list()` copies where appropriate (e.g. for simple types like `self.bonds` and `self.states`).
