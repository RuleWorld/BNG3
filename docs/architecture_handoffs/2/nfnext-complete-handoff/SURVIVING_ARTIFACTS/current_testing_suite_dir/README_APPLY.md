# Applying this testing tranche

> Archived application instructions. The current repository already promotes
> selected contracts; see `docs/CURRENT_PROGRESS.md`.

Copy `nextgen/tests/future_contract/` and `nextgen/tests/meta/` into the NFnext
prototype. Add this opt-in stanza to `nextgen/CMakeLists.txt` if it is not
already present:

```cmake
option(NFNEXT_BUILD_FUTURE_CONTRACT_TESTS
    "Build RED executable specifications for not-yet-implemented NFnext architecture"
    OFF)
if(NFNEXT_BUILD_FUTURE_CONTRACT_TESTS)
    add_subdirectory(tests/future_contract)
endif()
```

Keep this option OFF in ordinary CI until a subsystem is being implemented.
When working TDD-style, enable it and build one contract target at a time.
