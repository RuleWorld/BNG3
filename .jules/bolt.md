## BioNetGen3 Journal
## 2024-05-02 - Python Object Copy Performance
**Learning:** Using `copy.deepcopy()` for primitive lists (like lists of strings/ints for bonds/states) in frequent operations (like `Component.copy` and `Species.copy`) introduces a massive overhead. Additionally, repeated calls to expensive serialization functions like `molecule.to_string()` inside tight loops (like sort keys) drastically degrades performance.
**Action:** Use explicit list creation (e.g. `list(self.bonds)`) instead of `copy.deepcopy()` for properties known to hold only primitives. Cache expensive computations, such as `to_string()`, in variables when they are needed multiple times within a tight loop (e.g. inside a `key` lambda function for `sort`).
