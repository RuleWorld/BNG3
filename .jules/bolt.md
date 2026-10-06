## 2024-10-25 - Avoid `deepcopy` for simple dict/list structures where possible
**Learning:** `resolveSCT.py` uses `deepcopy(self.database.dependencyGraph)` multiple times for storing SCT states. `dependencyGraph` is typically a dict mapping strings to lists of lists of strings (or similar relatively simple nested structures). `deepcopy` is known to be very slow in Python.
**Action:** Replace `deepcopy(dict_of_lists)` with a specialized shallow-ish copy function or dict comprehension when the exact structure and immutability of inner elements are known and controlled, but wait: `dependencyGraph` might be modified later. A custom `copy_dependency_graph(graph)` function that manually recreates the dict of lists can be 10x faster than `deepcopy`.

## 2024-10-25 - Pandas DataFrame creation in loops
**Learning:** Building pandas DataFrames by constructing them with repetitive lists of lists, and applying `np.asarray` inside loops is a known performance bottleneck in Python.
**Action:** `scan.py` was refactored in a previous step to avoid this. Check if there are other similar instances (like `compat/runner.py` or `display.py`).

## 2024-10-25 - Avoid `deepcopy` and `shallow_copy` on Molecule objects in atomizer
**Learning:** Python's `copy.copy` and `copy.deepcopy` are very slow for complex objects. The atomizer's Molecule classes (in `utils/structures.py` and `utils/smallStructures.py`) have a `.copy()` method that used `copy.copy(self)` (shallow copy). This is a bottleneck. We can optimize it by manually copying attributes using `type(self).__new__(type(self))` to avoid invoking `__init__` which can have side effects (like allocating random hashes or random IDs) that tests check against, and directly setting `__dict__` items.
**Action:** When a `.copy()` method relies on `copy.copy()` or `copy.deepcopy()`, investigate if constructing an empty object with `__new__` and directly copying attributes using `self.__dict__.items()` is faster while avoiding `__init__` side-effects.
