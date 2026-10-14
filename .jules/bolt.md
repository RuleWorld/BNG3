## 2025-02-23 - Python copy.copy() bottleneck in Molecule instantiation
**Learning:** Using `copy.copy()` is very slow in Python and should be avoided in tight loops involving custom classes. Direct object instantiation bypassing `__init__` via `__class__.__new__(__class__)` paired with `__dict__.copy()` is significantly faster and safer.
**Action:** Replace `copy.copy()` and `copy.deepcopy()` in heavy numerical or graph data structures with optimized `__new__` and dictionary/list comprehensions for nested copies.
