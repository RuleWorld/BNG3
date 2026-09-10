## 2024-06-25 - Copying structures
**Learning:** In python/bionetgen/atomizer/utils/structures.py, the standard `deepcopy` is used extensively for `copy` operations of `Molecule`, `Species`, and `Component` classes. This leads to slow performance due to how python's deepcopy handles things internally, checking for memoized state and taking care of loops and other objects.
**Action:** Use list comprehensions and explicit `list()` conversions for lists rather than `deepcopy` for those structures. This reduced a test from ~1.687s to ~0.596s.
