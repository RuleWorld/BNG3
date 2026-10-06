## 2024-05-14 - String operations vs Regex in Hot Loops
**Learning:** In string-heavy parsing logic like `curateString` in `python/bionetgen/atomizer/atomizer/analyzeSBML.py`, `re.sub` is a massive bottleneck. Precompiling regex isn't always possible when patterns are generated dynamically (like with variable `difference`), but simple string operations (`startswith`, `endswith`, `replace`) are roughly 3x faster than non-precompiled `re.sub`.
**Action:** Always check if a regex replacement can be replaced by native string operations, especially when dynamic string patterns are used.

## 2024-05-14 - `difflib.SequenceMatcher` callback overhead
**Learning:** `difflib.SequenceMatcher` accepts an `isjunk` callback (often implemented as a lambda) to ignore certain characters during matching. This callback runs on every character comparison, leading to massive overhead.
**Action:** Instead of using an `isjunk` callback to ignore characters (like underscores), remove the characters manually (`string.replace("_", "")`) before calling `SequenceMatcher`. This runs considerably faster. Add early returns for exact matches or empty strings to further improve performance.
