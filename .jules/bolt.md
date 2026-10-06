## 2023-10-25 - Caching dynamically compiled regexes in loops
**Learning:** In string generation and manipulation methods, loops dynamically building `re.subn(rf"\b{re.escape(name)}\(\)")` add significant overhead.
**Action:** By keeping a local module-level dictionary to cache precompiled `re.Pattern` objects for dynamic regex strings, we can dramatically speed up the repetitive replacement steps without adding complexity.
