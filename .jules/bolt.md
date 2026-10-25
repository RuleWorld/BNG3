
## 2023-10-27 - O(N^2) difflib calls in loop
**Learning:** Calling `difflib.SequenceMatcher(None, x, y).ratio()` is computationally expensive. Computing it twice consecutively in a loop instead of assigning it to a variable is a massive codebase anti-pattern that drastically inflates execution time for species comparison.
**Action:** Always assign expensive comparisons (like regex matches, difflib ratios) to a local cache variable if the result needs to be both evaluated in an `if` condition and assigned.

## 2023-10-27 - O(N) Set Lookups for Sequence Matching
**Learning:** `sum(1 for item in left if item in right)` when both `left` and `right` are lists results in $O(N \times M)$ complexity.
**Action:** When calculating overlaps of items between lists, convert the lookup target to a `set` first for $O(1)$ membership checking.
