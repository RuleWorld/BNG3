# NFsim next-generation engine: first executable tranche

This directory is an additive prototype intended to sit beside the optimized
`perf/rasi-translation-optimization` NFsim engine. The old engine remains the
semantic oracle. The purpose of this tranche is to implement the architectural
changes that remove scaling dimensions instead of merely optimizing the legacy
object graph.

## Implemented now

1. **NFIR**: a compact intermediate representation for molecule types, primitive
   predicates/actions, expanded rules, parameterized rule families, dependency
   indices, backend hints and model fingerprints.
2. **Rule-family collapsing**: conservative recognition of consecutive indexed
   rules (`elongate_1 ... elongate_N`) with identical structural shape. Such a
   sequence is represented as one `RuleFamilyIR` plus indexed rates.
3. **Dependency indexing**: primitive pattern features map directly to affected
   rule-family IDs, carrying forward the dependency-aware update principle from
   the optimized NFsim branch.
4. **Backend selection contract**: NFIR models can select `Reference`, `Generic`
   or `Lattice`; a conservative lattice-compatibility gate is implemented.
5. **Integer/generational particle identity**: `ParticleArena` replaces pointer
   identity in the new engine core and rejects stale handles after slot reuse.
6. **Contiguous hot fields**: type, position, generation and liveness live in
   separate arrays rather than per-molecule heap objects.
7. **Native genome lattice**: occupancy is stored by coordinate. Hops update only
   the local neighborhood rather than scanning all expanded position-specific
   rules.
8. **Hierarchical propensity selection**: a Fenwick tree supports O(log N)
   weighted event selection and O(log N) local propensity repair.
9. **Counter-based RNG**: random numbers are a pure function of seed, trajectory
   ID and counter, making results independent of CPU thread scheduling.
10. **Batched trajectories**: deterministic multi-thread trajectory execution is
    implemented with an atomic work queue.
11. **Compiled-model cache foundation**: stable NFIR format/version, fingerprint
    and cache serialization are present.
12. **Default-build isolation**: the prototype uses C++17 but is outside legacy
    `src/`, so the existing C++11 NFsim build remains untouched unless the new
    target is explicitly enabled.

## Deliberately not claimed complete

This is not yet a drop-in replacement for every BNGL/NFsim semantic feature.
The missing integration work is explicit:

- adapter from NFsim's parsed XML/runtime structures into NFIR;
- full generic graph backend for arbitrary complexes, symmetry and local
  functions;
- exact translation of every transformation type into primitive NFIR actions;
- observable compiler beyond the NFIR contract;
- byte-for-byte reference differential runner wired to the old NFsim executable;
- persistent cache invalidation keyed by complete source XML/parser semantics;
- optional SIMD/GPU execution after the CPU representation stabilizes.

Those pieces should be added behind differential gates rather than guessed at.

## Scaling difference

Legacy optimized path:

```
N expanded rules -> sparse candidate filtering -> compiled matching -> event
```

NFnext lattice path:

```
N position-expanded rules -> 1 parameterized family -> local coordinate kernel
```

For a translational elongation family, an event changes only the origin,
destination, and neighboring eligibility entries. The work therefore scales
with the local mutation neighborhood rather than the number of genomic rules.

## Build standalone

```bash
cmake -S nextgen -B build-nextgen -DCMAKE_BUILD_TYPE=Release
cmake --build build-nextgen -j
ctest --test-dir build-nextgen --output-on-failure
```

## Integration into optimized NFsim root CMake

Add an opt-in target to the root `CMakeLists.txt`:

```cmake
option(NFSIM_BUILD_NEXTGEN "Build experimental NFIR/lattice engine" OFF)
if(NFSIM_BUILD_NEXTGEN)
    add_subdirectory(nextgen)
endif()
```

The default remains OFF until an NFsim->NFIR adapter and fixed-seed differential
suite are in place.
