## $(date +%Y-%m-%d) - Optimize atomizer copying performance
**Learning:** Python's `copy.deepcopy()` in `python/bionetgen/atomizer` (Molecule, Species, Component, and basic lists/dicts) is a major performance bottleneck due to its overhead. The custom objects implement a `.copy()` method which is much faster and safe for shallow deep-copy equivalents.
**Action:** Replace `deepcopy()` with `.copy()` for Species, Molecule, and Component objects, and use explicit slice assignments `[:]` or direct standard library deepcopies via `copy.deepcopy` only when actually needed.
