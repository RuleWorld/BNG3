## 2024-05-24 - Variable Length Arrays in Vectorized Pandas Conversions
**Learning:** When vectorizing list comprehensions for Pandas DataFrames (like `ScanResult` converting variable-length simulation time trajectories), assuming all nested lists are identical in length will cause index/broadcast errors. Simulation outputs may terminate early due to integration errors.
**Action:** Use an array of lengths (`[len(arr) for arr in lists]`) to `np.repeat` instead of a single `num_points` scalar.
