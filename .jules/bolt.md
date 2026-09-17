## 2024-05-18 - Avoid deepcopy on Molecule/Species/Component
**Learning:** Python's copy.deepcopy() in python/bionetgen/atomizer (Molecule, Species, Component) is a known performance bottleneck but is strictly necessary for correctness. Replacing it with shallow copies causes mutated shared state and random segfaults (e.g., in libsbml consistency checks). Do not attempt to optimize out deepcopy in these structures.
**Action:** Focus on other optimizations instead of removing deepcopy from atomizer classes.
## 2024-05-18 - scan.py dataframe optimization
**Learning:** When building pandas DataFrames from results (e.g., in scan.py), avoid repeatedly casting lists to numpy arrays (e.g., `np.asarray`) inside nested loops. Instead, pre-compute vectorized column arrays or columnar dictionaries outside the loop to prevent O(N^2) overhead.
**Action:** Use `np.concatenate` or vector ops for dataframe creation.
## 2024-05-18 - core.py deepcopy
**Learning:** Replaced deepcopy in core.py with manual instantiation to improve performance but found it causes memory leaks and corruption
**Action:** Revert changes
