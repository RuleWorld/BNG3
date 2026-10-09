# BNG3 Unification Spec — Agent Work-Orders + Validation Framework

> Historical design reference, reviewed 2026-10-07 at
> [main `e1836c32`](https://github.com/RuleWorld/BNG3/tree/e1836c3274e685996d5e86883761e00e98257e09).
> Issues #132–#186 own outstanding scope, dependencies and acceptance. Use the
> [convergence checklist](BNG3_CONVERGENCE_DONE_CHECKLIST.md) and
> [current progress](CURRENT_PROGRESS.md) for the task index and evidence
> boundaries. Do not start an old work order merely because it appears below.

The 2026-09-15 continuation strengthens WO-2 evidence by asserting direct
NFsim construction rather than
implicit XML fallback, and it adds a small WO-3/NFnext correspondence contract
from BNGL parsing through `CompiledModel` to `nfnext::lowerFromBioNetGen`.
These checks are intentionally bounded; unsupported population-map semantics
remain fail-closed and the full work-order completion contract remains open.

## What this is

BNG3 already merges three codebases structurally:

- `cpp/` = `bionetgen-master/src` (C++ port of BNG2) + embedded NFsim (`cpp/nfsim/` = `nfsim-master/src`) + pybind11 layer (`cpp/bindings/`).
- `python/bionetgen/` = PyBioNetGen + new unified API (`load`, `simulate`, `scan`, `sensitivity`, `builder`, `viz`, `sbml`) + **legacy modules still present** (`core/`, `modelapi/`, `network/`, `simulator/`).
- `legacy/perl/` = BNG2 Perl, kept as oracle.

The structural copy is done. What is **not** done: the three tools still each carry their own implementation of the same five operations. The merge is only finished when each operation has **one** implementation (a "master function") that every consumer calls, and that master is **proven** equivalent to the three originals it replaces.

The work orders below preserve the original consolidation design and its
validation requirements. Several implementation slices have since landed;
their old dependency lists and deletion plans do not replace the live issues.

Batch SSA PR [#26](https://github.com/RuleWorld/BNG3/pull/26) was merged on
2026-09-29 as `c2babc50acfc1141d13671389a18e91453977bea`. Historical entries
calling it open are not current PR state. CUDA device qualification remains
[#175](https://github.com/RuleWorld/BNG3/issues/175).

---

## Capability union (non-lossy constraint)

Dedup collapses redundant *implementations*, never *capabilities*. After unification the single tool must still expose the union:

- Simulation: `ode` (CVODE), `ssa`, `pla`, `psa` (from BNG2/Network3), `nf` (network-free, from NFsim).
- Construction: BNGL parse, `ModelBuilder`, SBML import via atomizer.
- Analysis: 1D/2D parameter scan, local sensitivity (finite diff).
- Export: BNGL, BNG-XML, .net, SBML, SBML-Multi, MATLAB/MEX, LaTeX, SSC, MDL, all graph writers (contact map, regulatory, rule-influence, reaction-network, ruleviz pattern/operation, process).

Any WO that removes a capability is wrong. The gate corpus exercises all of the above.

---

## The unification thesis — five master functions

| # | Operation | Redundant today | Master function | Delete from default path |
|---|-----------|-----------------|-----------------|--------------------------|
| 1 | Canonical graph labeling | One bundled nauty build now exists; [SpeciesGraph](../cpp/ast/SpeciesGraph.cpp) and [NFsim complex identity](../cpp/nfsim/NFcore/complex.cpp) still have separate graph encodings | Qualify a shared semantic graph-identity contract (#142) | Private canonicalization only after equivalence evidence |
| 2 | Parse → model | ANTLR4 (`cpp/parser/`); Perl `BNGModel`; PyBioNetGen `modelapi/bngparser.py`; NFsim XML re-parse (`NFinput::initializeFromXML`) | ANTLR4 BNGL → `ast::Model` is the only front door; NFsim consumes `ast::Model` directly | XML round-trip bridge; `python/bionetgen/modelapi/`, `network/networkparser.py` |
| 3 | Expression / rate-law eval | NFsim's ExprTk dependency has been removed; [its evaluator shim](../cpp/nfsim/NFfunction/nfsim_funcparser.h) uses the shared expression infrastructure | Qualify remaining rate-law/local-function contracts across backends (#143) | Remaining semantic duplication after parity |
| 4 | Simulate dispatch | `model.simulate()`; PyBioNetGen `simulator/{bngsimulator,librrsimulator}.py`; NFsim `main`; C++ `console/` | `model.simulate(method=...)` is the only public entry | `python/bionetgen/simulator/`, `core/main.py`, NFsim `main` build |
| 5 | I/O writers | `cpp/io/` (C++); Perl `BNGOutput`; PyBioNetGen writers | `cpp/io/` writers, exposed via `cpp/bindings/bind_io.cpp`, consumed by Python | Perl writers on default path; any Python re-implementation |

The earlier `blbr`/cBNGL over-count observations are historical reproductions,
not a current diagnosis of graph canonicalization. The current
[exception ledger](../tests/validation/reference_exclusions.json) is empty;
graph-identity unification remains a separate scientific correctness task (#142).

---

## Validation framework (the spine)

No master function lands without passing a differential test against the originals. Three oracles, one corpus, tiered gates.

### Oracles

- **Oracle-Perl** — `legacy/perl/BNG2.pl`. Source of truth for network generation (`.net`) and ODE/SSA trajectories (`.gdat`/`.cdat`). Invoke via subprocess; cache outputs as golden files so the Perl runtime is not on the hot path.
- **Oracle-NFsim** — independently build the pinned upstream NFsim source using
  [checkout_oracle.py](../scripts/ci/checkout_oracle.py) and the
  [source lock](../provenance/upstreams.lock.yml). The embedded BNG3 NFsim
  executable is not an independent oracle for BNG3.
- **Oracle-Golden** — committed reference outputs under `tests/validation/golden/`. Regression guard; regenerated only by an explicit, reviewed step, never silently.

### Corpus (tiers)

- **Tier-S (smoke, < 60 s):** `simple_system`, `gene_expr`, `michment`, `blbr`, `Motivating_example`, `Motivating_example_cBNGL`, `egfr_net`, `Repressilator`, `CaOscillate_Func`, `localfunc`. Runs on **every** commit to any WO.
- **Tier-P (parity, full):** the 512-model BNG2-compatible corpus (`bng2_compatible_models.txt`) plus everything in `models/`. Runs on WO completion and nightly. Sharded (mirror the existing 3-shard CI pattern).
- **Tier-NF (network-free):** `simple_system`, `tlbr/tlbr`, `fceRI_compendium`, `multisite_phos`, `motor`, plus all of `nfsim-master/test/`. Compared against Oracle-NFsim.

### Comparators + tolerances

- **Network (`.net`):** parse into `species` and `reactions` sections, canonicalize, compare as **sets**. Pass = exact set equality and equal counts. Extend the existing `scripts/validate.py` parser. (The blbr/cBNGL count mismatch is detected here.)
- **ODE trajectory:** align on time grid; pass = relative error ≤ `1e-6` (Linf and L2) vs Oracle-Perl CVODE. Implemented in `tests/validation/test_parity_ode.py` at `1e-6` against a pinned Perl oracle. `scripts/validate_trajectories.py` was removed: it skipped all 7 models and exited 0, and its `1e-3` tolerance was 1000× looser.
- **SSA / PLA / PSA trajectory:** not bit-comparable. Two checks: (a) **seeded determinism** — same seed twice = identical output; (b) **distributional** — ensemble mean of N≥200 runs within `mean ± 3·SE` of Oracle-Perl ensemble at each sampled time. New comparator `scripts/validate_stochastic.py`.
- **Network-free trajectory:** same seeded + distributional checks vs Oracle-NFsim. Implemented in `tests/validation/test_parity_nfsim.py` and the `nfsim-parity` CI job. `scripts/validate_nfsim.py` was removed: it never invoked NFsim with a model, and measured 0 passed / 2 failed.
- **Expression/rate-law:** [test_parity_rhs.py](../tests/validation/test_parity_rhs.py)
  consumes the frozen five-model expression tier, checks native coefficients
  before mass-action factors, and compares RHS at three times with `rtol=1e-9`
  and `atol=1e-12`. This is implemented bounded coverage, not all function-heavy
  models or automatic hosted execution; #143/#182 own the remaining contract
  and CI wiring.
- **Export formats:** [test_export_formats.py](../tests/validation/test_export_formats.py)
  covers XML well-formedness, SBML validity, NET round trips and SSC, MDL,
  MATLAB/MEX and LaTeX artifact contracts. Focused writer/API tests also exist.
  Artifact presence or well-formedness does not imply complete schema validity,
  semantic round trips or downstream execution; #163 owns those remaining gates.

### Harness layout (build in WO-0)

```
tests/validation/
  conftest.py            # fixtures: built bng_cpp path, perl oracle, nfsim oracle, corpus loader
  corpus.py              # resolves Tier-S / Tier-P / Tier-NF model lists from bng2_compatible_models.txt + models/
  oracle_perl.py         # run-or-load-golden wrapper around legacy/perl/BNG2.pl
  oracle_nfsim.py        # run wrapper around native NFsim binary
  compare.py             # net set-compare, trajectory rel-error, stochastic distributional, format checks
  golden/                # committed reference .net/.gdat (regen via scripts/regen_golden.py only)
  test_parity_net.py     # parametrized over corpus tier
  test_parity_ode.py
  test_parity_stochastic.py
  test_parity_nfsim.py
  test_parity_expressions.py
  test_export_formats.py
```

Each `test_*` is parametrized over a tier and `xfail`-marks known-broken models with a tracking reason, so a green run is honest about what is and isn't covered.

---

## Agent contract (read before any WO)

- **Read the tree, not memory.** Grep the repo before asserting state. If a thing is implemented and tested, do not mark it planned.
- **No regression.** A WO that turns a passing Tier-S model red is not done, even if its own target passes.
- **Two-round rule.** If a "defect" survives two targeted fixes, stop and question whether it is real (it may be an artifact — e.g. patch-encoding mojibake from UTF-16/CP437, not a source bug). Verify against the actual repo tree, never against a `.patch` file's text.
- **Surgical.** Prefer minimal diffs over rewrites. One WO = one master function + its deletions + its gate.
- **Report format:** what changed (files), which gate ran, pass/fail per tier, any new `xfail` with reason. No line counts, no changelogs.

---

## WO-0 — Validation harness + golden corpus

**Depends on:** nothing. **Blocks:** all.

**Build:** the `tests/validation/` layout above. Wire `oracle_perl.py` to `legacy/perl/BNG2.pl` and `oracle_nfsim.py` to the CMake `NFsim` target. `corpus.py` parses `bng2_compatible_models.txt` (decode it first — it is a non-UTF-8 tree dump; `iconv -f CP437` or tolerant read, then extract `*.bngl` paths) into the three tiers. Generalize `compare.py` from the six existing `scripts/validate_*.py`.

**Golden generation:** `scripts/regen_golden.py` runs Oracle-Perl over Tier-P, writes `.net`/`.gdat` into `tests/validation/golden/`. Reviewed, committed once. Never auto-regenerated by tests.

**Gate (self):** harness runs end-to-end on Tier-S against the exact `bng_cpp`
under review and produces a pass/strict-expected-failure report. The old `blbr`
exception is historical; the ledger at `e1836c32` contains zero exceptions.
Do not recreate an exclusion from this work order's earlier observations.

**Done:** `pytest tests/validation -m smoke` runs green except the two documented `xfail`s; `regen_golden.py` reproducible.

---

## WO-1 — One canonical labeling (fixes over-counting)

**Depends on:** WO-0. **Can run parallel with:** WO-3 (different code), but its gate is the strictest, so sequence it first.

**Scope:** `cpp/core/HNauty.hpp`, `cpp/core/PatternGraph.cpp`, `cpp/ast/SpeciesGraph.cpp`, `cpp/nfsim/NFcore/{complex,molecule,moleculeType}.cpp`, `cpp/CMakeLists.txt`.

**Master interface (new, in `cpp/core/`):**
```cpp
namespace bng::core {
// Deterministic canonical string for a molecular species graph.
// Single implementation; the only canonicalizer in the codebase.
std::string canonicalLabel(const SpeciesGraph& g);
}
```

**Work:**
1. Make `bng::core::canonicalLabel` the one path. `NetworkGenerator` species dedup calls it; NFsim complex identity calls it (replace NFsim's private nauty path). Resolve the `HNauty.hpp:640` "largest vs nauty canonical form" ambiguity against Perl `HNauty.pm` semantics — Perl is the oracle.
2. CMake: delete the second nauty build. `nfsim_core` links the single `nauty` target; drop `file(GLOB NFSIM_NAUTY_C ...)` and the `cpp/nfsim/nauty24/` include.
3. Investigate the over-count root cause in this unified path: suspect `SpeciesLabel`/`HNauty` option not applied and Perl `auto`/RuleGroup differences. The reaction merging happens in `RxnList::add`; confirm whether `blbr`/`cBNGL` over-count is duplicate reactions that should canonicalize to one.

**Deletes:** `cpp/nfsim/nauty24/` (entire dir), NFsim's bespoke canonicalization functions.

**Gate:** Tier-P **net parity** = exact set equality on **all 512 + `models/`**, with `blbr` now **passing** and its exception removed; `Motivating_example_cBNGL` remains passing. Tier-NF still passes (NFsim complex counting unchanged in behavior, only its labeler swapped). Tier-S green.

**Done:** one nauty in the build; one `canonicalLabel`; zero net-parity failures.

---

## WO-2 — NFsim consumes `ast::Model` directly (kill XML bridge)

**Depends on:** WO-0, WO-1. 

**Scope:** `cpp/bindings/bind_nfsim.cpp`, `cpp/nfsim/NFinput/`, new adapter in `cpp/nfsim/`.

**Today:** `bind_nfsim.cpp` does `XmlWriter::write(model)` → temp file → `NFinput::initializeFromXML`. Two data models, a serialize/parse round-trip, and a tempfile per run.

**Master:** an in-memory adapter `bng::nfsim::buildSystem(const ast::Model&) -> NFcore::System*` that constructs the NFsim `System` directly from `ast::Model` (molecule types, seed species, rules, observables, functions), bypassing XML. `bind_nfsim.cpp` calls the adapter.

**Migration safety:** keep `initializeFromXML` reachable behind a debug flag for one cycle so the gate can diff in-memory vs XML-bridge output, then delete the bridge from the default path.

**Deletes (after gate green):** XML-bridge call in `bind_nfsim.cpp`; tempfile machinery (`make_temp_xml_path`); XML re-parse on the simulate path.

**Gate:** Tier-NF trajectory parity, **two ways**: (a) in-memory adapter vs Oracle-NFsim (seeded + distributional); (b) in-memory adapter vs the old XML-bridge path (must be statistically identical). Function-bearing NF models (`localFunction`, `motor`, `TQSSA` from `nfsim-master/test/`) included. The current direct slice covers zero-argument composites and one-argument `%name::` molecule-scoped local rates; the full gate remains open until the remaining local-function, TFUN, and rate-law forms are mapped or explicitly governed.

**Done:** `method="nf"` runs with no XML serialization; parity holds both ways.

---

## WO-3 — One expression / rate-law evaluator

**Depends on:** WO-0. **Parallel with:** WO-1.

**Scope:** `cpp/ast/Expression.cpp`, `cpp/ast/Function.cpp`, `cpp/nfsim/NFfunction/`, `cpp/CMakeLists.txt`.

**Master:** `bng::ast::Expression` is the single evaluator. ODE RHS (`cpp/engine/OdeIntegrator.cpp`), SSA propensity, and NFsim local/global functions (`NFfunction/`) all evaluate through it. Provide a thin shim so NFsim's call sites get `bng::ast::Expression` values without exprtk.

**Deletes:** exprtk dependency and `NFSIM_USE_EXPRTK` from `cpp/CMakeLists.txt`; NFsim's exprtk function compilation.

**Gate:** `1e-9` ODE-RHS match on `localfunc`, `isingspin_localfcn`, `isingspin_energy`, `CaOscillate_Func`, all `test_tfun_*`; Tier-NF parity on `localFunction`/`motor` holds (now via the shared evaluator). Tier-S green.

**Done:** one expression engine; exprtk gone; numeric parity holds across ODE, SSA, and NF.

---

## WO-4 — One simulate dispatch + delete legacy Python sim/parse

**Depends on:** WO-0; benefits from WO-1..3 but can proceed once `model.simulate` is the proven path.

**Scope:** `python/bionetgen/model.py`, `python/bionetgen/__init__.py`, `python/bionetgen/cli.py`; legacy trees `python/bionetgen/{simulator,modelapi,network}/`, `python/bionetgen/core/main.py`, `python/bionetgen/core/tools/`.

**Master:** `BioNetGenModel.simulate(method ∈ {ode,ssa,pla,psa,nf}, ...)` is the only public simulation entry; `load()` the only loader; `parameter_scan`/`parameter_scan_2d`/`sensitivity_analysis` the only analysis entries. All route to C++ via bindings.

**Compat:** `BIONETGEN_USE_PERL=1` continues to route through `compat/legacy_runner.py` (subprocess Perl) — that is the *only* sanctioned legacy path and it stays. Everything else legacy goes.

**Deletes:** `python/bionetgen/simulator/` (subprocess + libRoadRunner wrappers), `python/bionetgen/modelapi/` (Python BNGL/XML parser, superseded by ANTLR4), `python/bionetgen/network/networkparser.py` (superseded by C++ `NetReader`), legacy Cement CLI `core/main.py` + `core/tools/cli.py`. Keep `core/exc.py`, `core/defaults.py`, `core/tools/{plot,result}.py` if the new API imports them; otherwise fold into `result.py`/`viz.py`.

**Gate:** new Python parity suite — for Tier-S, `load(m).simulate(method=...)` results match Oracle-Golden within the per-method tolerances above. **Import-absence test:** after deletion, `import bionetgen` must not import `modelapi`/`simulator`/`network.networkparser` (assert via `sys.modules`), and `BIONETGEN_USE_PERL=1` must still work. CLI commands (`run`, `scan`, `sensitivity`, `visualize`, `check`, `export`) all execute on Tier-S.

**Done:** one simulate path; legacy parse/sim trees gone; Perl compat intact.

---

## WO-5 — One I/O writer set via bindings

**Depends on:** WO-0.

**Scope:** `cpp/io/`, `cpp/bindings/bind_io.cpp`, `python/bionetgen/{model.py,viz.py,sbml.py}`.

**Master:** every export is a `cpp/io/` writer reached through `bind_io.cpp`; Python methods (`write_xml`, `write_bngl`, `write_sbml`, `write_matlab`, `write_latex`, `sbml_multi`, all graph exports) are thin wrappers. No Python re-implements a writer; Perl `BNGOutput` is off the default path.

**Deletes:** any duplicate Python writer logic; Perl writers from the default path (retained only under `BIONETGEN_USE_PERL=1`).

**Gate:** `test_export_formats` over Tier-S — BNG-XML schema-valid, SBML libsbml-valid (or well-formed), `.net` write→read→write idempotent, graph writers produce non-empty valid GraphML/DOT. Cross-check BNG-XML against Oracle-Perl XML structurally (element/attribute set equality, order-insensitive).

**Done:** single writer set; format gates green.

---

## WO-6 — Delete redundant trees

**Depends on:** WO-1..5 green (nothing references the deletions).

**Delete (verify zero references first via grep across `cpp/`, `python/`, `cpp/CMakeLists.txt`):**
- Duplicate nauty already removed in WO-1; confirm only `cpp/nauty/` remains.
- `legacy/perl/Network3` C ODE/SSA solvers — superseded by `cpp/engine/OdeIntegrator` (keep Perl `.pm` modules **only** as the Perl-compat oracle path).
- Redundant model copies: `models/` is canonical; remove duplicate model dirs that exist solely inside `cpp/nfsim/` test fixtures if they duplicate `models/` (keep NFsim-specific test inputs).
- Any `python/bionetgen/core/notebook.py` / legacy notebook wrapper if `_repr_html_` replaced it.

**Gate:** full build + Tier-P + Tier-NF green with the deletions applied. `grep` proves no dangling references.

**Done:** one copy of each asset; build and full parity unaffected.

---

## WO-7 — `AGENTS.md` + CI

**Depends on:** WO-0 (so CI has a harness to run).

**Create `AGENTS.md`** at repo root (BNG3 has none): build commands (`cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build`; `pip install -e .`), test commands (`pytest tests/validation -m smoke`, `... -m parity`, `ctest` for `tests/cpp/`), how to rebuild bindings, how to regenerate golden (`scripts/regen_golden.py`, reviewed), import conventions. Terse.

**CI:** GitHub Actions — Tier-S on every PR; Tier-P + Tier-NF sharded (3 shards) nightly and on release tags; `benchmarks/run_benchmarks.py` archived nightly. A PR is mergeable only if Tier-S is green and no previously-passing model regresses to `xfail`.

**Done:** `AGENTS.md` present and accurate; CI enforces the gates.

---

## Execution order

```
WO-0  (harness)            ── must land first
  ├─ WO-1  (canonical)     ── strictest gate; sequence before others touching the engine
  ├─ WO-3  (expressions)   ── parallel with WO-1
  ├─ WO-5  (I/O)           ── parallel
  └─ WO-7  (AGENTS+CI)     ── parallel
WO-2  (NFsim direct)       ── after WO-1
WO-4  (python dispatch)    ── after WO-1..3 proven
WO-6  (delete trees)       ── last; after WO-1..5 green
```

Parallelizable: {WO-1, WO-3, WO-5, WO-7} after WO-0, since they touch disjoint files. WO-2, WO-4, WO-6 are sequenced by dependency.

## Global done

- One nauty, one `canonicalLabel`, one `Expression`, one parse path, one `simulate`, one writer set.
- `blbr` and `Motivating_example_cBNGL` pass net parity.
- Tier-P net + ODE parity green across the full corpus; Tier-NF green vs native NFsim; expression parity to `1e-9`; export formats valid.
- Default path imports no legacy parse/sim; `BIONETGEN_USE_PERL=1` still works.
- `AGENTS.md` + CI enforce all of the above.
