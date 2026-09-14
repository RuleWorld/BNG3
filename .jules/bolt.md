## 2026-09-14 - Python deepcopy optimization failure in Atomizer

**Learning:** `copy.deepcopy()` in the `Atomizer` structures (`Species`, `Molecule`, `Component`) is a major performance bottleneck but attempting to replace it with shallow copies/list comprehensions causes mutating shared state and random segfaults in `libsbml` serialization when tested (e.g. `test_cpp_sbml_multi_writer_roundtrip_is_libsbml_consistent`). The complexity of the `Atomizer` object graph necessitates full deep copies.

**Action:** Do not attempt to optimize out `copy.deepcopy` for `Atomizer` structures unless structurally refactoring the entire graph to be immutable.
