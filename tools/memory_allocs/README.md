# Allocation-counting harness (`tools/memory_allocs/`)

Two standalone programs. Neither is wired into CMake and neither links the
Catch2 test tree; both are compiled by hand against a configured build tree.

## `mem_bench.cpp` — counts allocations in a BNG3 code path

Replaces the global `operator new` / `operator new[]` (plain, `nothrow`, and
`align_val_t` forms) with counting wrappers, then drives
`engine::NetworkGenerator::generateNative()` — or, with `MEMBENCH_PHASE=obs`,
`engine::ObservableProjection::weights()` over every species of an already-built
network — and reports:

- process-**total** allocation count and bytes for the measured window,
- the largest single allocation,
- the number of distinct allocation sites recorded,
- per-site counts with a 4-deep return-address chain, symbolized via
  `dladdr` + `abi::__cxa_demangle`,
- a file/namespace-level bucket per site, which is the trustworthy number.

### Build and run

```bash
# from a configured build tree (e.g. build/ with -DBUILD_TESTS=ON)
LIBS=$(awk '/^  LINK_LIBRARIES = /{sub(/^  LINK_LIBRARIES = /,"");print;exit}' build.ninja)

c++ -O1 -g -DNDEBUG -std=gnu++17 -arch arm64 \
  -I../cpp -I../cpp/parser -I../cpp/parser/generated \
  -I_deps/antlr4_runtime-src/runtime/Cpp/runtime/src \
  -I_deps/sundials-src/include -I_deps/sundials-build/include \
  -I../cpp/nfsim/NFinput/TinyXML \
  ../tools/memory_allocs/mem_bench.cpp -o /tmp/mem_bench \
  cpp/libbng_engine.a cpp/libbng_parser.a cpp/libbng_compile.a \
  cpp/libbng_core.a cpp/libbng_ast.a cpp/libbng_units.a \
  cpp/libbng_finite_backend.a cpp/libbng_nfcore2.a cpp/libbng_nfnext.a \
  $LIBS

/tmp/mem_bench models/tlbr.bngl 3 5          # <model> <max_iter> <reps>
MEMBENCH_PHASE=obs MEMBENCH_OBSREPS=20 \
  /tmp/mem_bench models/performance_test_models/egfr_net.bngl 5 1   # observables
MEMBENCH_SHOW=400 /tmp/mem_bench models/blbr.bngl 20 1               # all sites
```

To measure **another worktree's** change, link against that worktree's
archived `.a` files instead of `cpp/*.a` above. The counter must be compiled
*into* the binary under test; interposing `malloc` via
`DYLD_INSERT_LIBRARIES` / `DYLD_INTERPOSE` does **not** work against these
binaries (`Mach-O thin (arm64)`, `flags=0x20002(adhoc,linker-signed)`, two-level
namespace) and silently reports zero allocations.

## `mvec_bench.cpp` — population benchmark for the M-matrix allocation strategy

A standalone reproduction of the allocation pattern at
`cpp/core/Ullmann.cpp:83` (`UllmannBase::initialize_M_vec`), comparing four
strategies for building the same `std::vector<std::map<Node*, std::vector<Node*>*>>`
shape. No production code is linked.

```bash
c++ -O2 -std=gnu++17 -arch arm64 tools/memory_allocs/mvec_bench.cpp -o /tmp/mvec_bench
/tmp/mvec_bench <levels> <nodes> <reps>     # e.g. 12 6 10
```

## Two properties a reader must know before trusting a number

**1. The site table cannot under-count silently.** It is a fixed 8192-slot
open-addressing table over a static array that performs **no allocation**
(`operator new` is what is being counted; an allocating counter recurses
infinitely and dies with SIGSEGV — the first version of this harness used a
`std::map` for the table and crashed at startup). On overflow the harness
prints `WARNING site table full: N allocations unattributed` and increments a
collision counter. Observed peak occupancy across every fixture and rep
reported in the PR is 236 sites = **2.9%** of capacity.

**2. Per-site attribution is keyed by return address and is not stable across
processes.** The address moves with ASLR, so per-site numbers are a
*within-one-process diagnostic only*. The process-**total** count and byte
figures are keying-independent and are the fitness signal.

## Resolution floor, measured not assumed

Totals are **not** bit-reproducible, and I corrected my own earlier claim of
"deterministic, min==max" after measuring it properly.

| fixture | n | min | median | max | IQR | full range |
|---|---|---|---|---|---|---|
| `models/tlbr.bngl` max_iter=3 | 40 | 160,325 | 184,186 | 185,541 | **1.82%** | 13.69% |
| `models/blbr.bngl` max_iter=20 | 10 | 864,551 | - | 884,610 | - | **2.37%** |
| `models/isingspin_localfcn.bngl` max_iter=5 | 5 | 7,740,781 | 7,740,781 | 7,740,781 | **0.00%** |

The distribution on `tlbr` is **not** Gaussian: the bulk sits in 181k-185k
(IQR 1.82%) with a rare left tail near 160k, which is why the full range is
13.69% while the IQR is 1.82%. The site count is 222 in every run including the
outliers, and the harness printed no `WARNING site table full` in any of 20
consecutive runs, so **the tail is a property of the measured code, not of the
counter's table**. Generated output is identical across all runs
(19 species / 29 reactions every time), so the variance is in how many
allocations the isomorphism search performs, not in what it produces.

`isingspin_localfcn` is exactly reproducible across 5 in-process reps and 4
separate processes, which is the control: the instrument itself does not
introduce variance when the code path is stable.

**Practical rule.** Use the **median and IQR**, not min/max: a delta smaller
than ~2% on `tlbr`/`blbr` is not resolvable and must be reported as "within
measurement noise". Any A/B must interleave both arms in one session, >= 7
runs per arm, and compare medians.