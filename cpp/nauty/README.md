# cpp/nauty — the single bundled nauty build

Nauty v2.4 is an open-source package used for canonical graph labeling.
Upstream: <http://cs.anu.edu.au/~bdm/nauty/>

The pristine upstream distribution is retained under `nauty24/` for provenance.
It is **not** compiled: the `nauty` CMake target globs `nauty/*.c` only
(non-recursive), so the compiled set is exactly the five files in this
directory.

## Consumers

One target, `nauty`, is linked by both sides of the platform:

- `bng_core` — `cpp/core/PatternGraph.cpp` (species/pattern canonical labeling)
- `nfsim_core` — `cpp/nfsim/NFcore/complex.cpp` (NFsim complex identity)

Before the WO-1b unification there were two independent builds of the same
upstream library — `cpp/nauty/` and `cpp/nfsim/nauty24/` — linked into every
binary. `cpp/nfsim/nauty24/` has been removed.

## The `nset` patch

The compiled sources carry one deliberate deviation from upstream: the typedef
`set` is renamed to `nset`.

Upstream nauty defines `typedef setword set;` at global scope. NFsim's C++
translation units use `using namespace std;`, so the unqualified name collides
with `std::set` and fails to compile on stricter toolchains (originally
observed on Xcode/OSX; also a hazard for MSVC and newer libstdc++). The rename
was introduced in the NFsim copy and is now the only variant in the tree.

BNG-side code never referenced the `set` typedef — `PatternGraph.cpp` uses only
`setword`, `graph`, `SG_DECL`, `nauty_check`, and `nauty()` — so adopting the
patched variant required no change to `cpp/core`.

The merged headers also keep the NFsim copy's MSVC guard:

```c
#ifdef _MSC_VER
#define HAVE_UNISTD_H    0
#define HAVE_SYSTYPES_H  0
#else
#define HAVE_UNISTD_H    1
#define HAVE_SYSTYPES_H  1
#endif
```

The former `cpp/nauty/` copy declared `HAVE_SYSTYPES_H 1` unconditionally,
which is wrong under MSVC. Unifying on the NFsim variant fixes that as a side
effect.

## Do not re-fork

If a consumer needs different canonicalization *semantics*, add a wrapper in
`cpp/core` rather than a second nauty build. Two builds of the same C library
in one binary produce duplicate mutable global state (nauty keeps static
workspace and `DYNALLSTAT` buffers at file scope) and duplicate symbols that
the linker resolves silently.
