
## 2024-05-18 - Replacing Deepcopy in Atomizer

**Learning:** `copy.deepcopy()` is incredibly expensive in Python due to overhead. The `bionetgen/atomizer` used it heavily in mapping dictionaries, but `Species` objects natively implement a `.copy()` method that provides equivalent deep-copy behavior at a fraction of the cost. The same principle applies to dictionaries of `Counter` objects where comprehensions like `{k: v.copy() for k, v in d.items()}` easily outperform deepcopy.

**Action:** Whenever deepcopying complex structures or custom classes in Python within loops, always check if the class implements its own `.copy()` method or construct custom deepcopy logic (e.g. dict comprehensions + `.copy()`) to bypass the generalized `copy.deepcopy()` overhead.
