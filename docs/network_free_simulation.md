# Network-Free Simulation Guide: NFsim, NFcore, and NFnext

Network-free stochastic simulation tracks individual molecule instances and bonds rather than enumerating the full reaction network first. Use it when combinatorial complexity (multi-site phosphorylation, polymerization, oligomerization, or scaffold assembly) makes finite network generation (`ode`, `ssa`, `pla`, `psa`) prohibitively large or infinite.

BioNetGen 3 includes two in-process network-free engines—**NFnext** and embedded **NFcore**—and ships a standalone **`NFsim`** CLI binary in its release archives. This guide explains how they relate, which one runs by default at each entry point, how to verify which backend executed, and what comes next.

---

## 1. The Four Network-Free Surfaces Explained

| Name | What It Is | Input Pipeline | Role in BNG3 |
| --- | --- | --- | --- |
| **Upstream standalone `RuleWorld/NFsim`** | The independent upstream C++ project (`v2.0.1` + `#160` @ `d45b7d99` on `main`; `8c449bbc` at `v3.0.0a1`) | BNG-XML (`.xml`) or `.rnf` script | **Independent validation oracle only.** Built from its locked checkout in CI; BNG3's embedded engines are never treated as their own parity oracle. |
| **Bundled `NFsim` CLI binary** | Standalone executable shipped inside BNG3 CLI release archives (`bionetgen-<platform>.tar.gz`) | BNG-XML (`.xml`) or `.rnf` script | Drop-in CLI execution for existing `-xml` / `-rnf` workflows without Python. Backed by BNG3's embedded NFcore (`cpp/nfsim/`). |
| **Embedded NFcore** | The classic NFsim core embedded in `_bionetgen_cpp` and `bng_cpp` (`cpp/nfsim/`) | **Direct construction** from AST/`CompiledModel` (`construction_path="direct"`) by default; optional in-memory XML fallback (`BNG_NFSIM_ALLOW_XML_FALLBACK=1`) | Selected explicitly in Python via `method="nfcore"` (reports `result.backend == "nfsim"`). Also executed by BNGL action blocks (`simulate_nf()` and `simulate({method=>"nf"})`). |
| **NFnext** | BNG3's next-generation network-free engine (`cpp/nfnext/`) | Direct lowering **`CompiledModel → NFIR`** (no XML serialization) | Selected automatically by Python `model.simulate(method="nf")`, `bionetgen.run(..., method="nf")`, and `bionetgen run MODEL -m nf`, or explicitly via `method="nfnext"` (reports `result.backend == "nfnext"`). Also provides an explicit, fail-closed GPU batch path (`model.simulate_nfnext_gpu()`). |

> **What happened to `NFcore2`?** `NFcore2` was an earlier prototype that was unlinked from the default build, consolidated into NFnext per [Maintainer Decisions](DECISIONS.md) item 4 (`#149`), and archived under `legacy/nfcore2/` (test-only `BUILD_TESTS=ON`). Passing `method="nfcore2"` raises a `ValueError` directing you to `method="nf"` / `"nfnext"` or `method="nfcore"`. The active pattern-lowering helper `NFcore2::lowerPatternToNFsim` lives in `cpp/nfsim/NFinput/nfsim_pattern_lowering.{hh,cpp}` for NFcore input.

### Construction Paths and Why They Matter

- **NFnext (`CompiledModel → NFIR`):** Never writes or reads BNG-XML. Lowering validates every construct up front and fails closed with a diagnostic if an unsupported feature is encountered.
- **Embedded NFcore (`direct` vs. `in-memory-xml` vs. XML file):**
  - By default, embedded NFcore builds `NFcore::System` directly in memory (`NFinput::buildSystemFromAst()` / `NFinput_fromCompiled.cpp`) and reports `construction_path="direct"`.
  - Direct construction is **fail-closed**: unsupported constructs raise an error rather than silently dropping semantics.
  - Only if you explicitly set `BNG_NFSIM_ALLOW_XML_FALLBACK=1` (or `BNG_NFSIM_FORCE_XML=1`) does NFcore fall back to serializing BNG-XML in memory (`construction_path="in-memory-xml"`). Set `BNG_NFSIM_REQUIRE_DIRECT=1` to forbid XML fallback even if allowed elsewhere.
  - Standalone `NFsim -xml model.xml` reads an XML file from disk (matching upstream NFsim CLI semantics).

---

## 2. Engine Decision Table

This table reflects what a **`v3.0.0a1`** user sees, with post-tag **`main`** (`90832910`) additions clearly marked.

| Entry Point | Default Engine | Explicit Alternative | Prerequisites / Build Flags | Platforms | Refusal / Fallback Behavior |
| --- | --- | --- | --- | --- | --- |
| `model.simulate(method="nf")` | **NFnext** (`backend="nfnext"`) | `method="nfnext"` or `method="nfcore"` (`backend="nfsim"`) | Default BNG3 wheel/build | Linux, macOS, Windows | Fail-closed; rejects NFcore-only `equilibrate`/`traversal_limit` and `backend="bngsim"`; does **not** silently fall back to NFcore or XML |
| `bionetgen.run(path, method="nf")` | **NFnext** (`backend="nfnext"`) | Load model and call `model.simulate(method="nfcore")` | Default BNG3 wheel/build | Linux, macOS, Windows | Fail-closed (`bionetgen.run` accepts `ode`, `ssa`, `nf`, `pla`, `psa` only) |
| `bionetgen run MODEL -m nf` | **NFnext** | Use Python `model.simulate(method="nfcore")` or BNGL action `simulate_nf` | Default BNG3 wheel/build | Linux, macOS, Windows | Fail-closed |
| `model.simulate(method="nfcore")` | **NFcore** (`backend="nfsim"`) | `method="nf"` / `"nfnext"` | Default BNG3 wheel/build | Linux, macOS, Windows | Direct construction fails closed unless `BNG_NFSIM_ALLOW_XML_FALLBACK=1` is set |
| BNGL action `simulate_nf()` or `simulate({method=>"nf"})` via `bng_cpp` / `bionetgen execute` / `model.execute()` | **NFcore** (direct) | None inside BNGL actions yet (`method=>"nfcore"` / `"nfnext"` are not accepted in BNGL actions) | Default wheel or CLI archive | Linux, macOS, Windows | Direct construction fails closed unless `BNG_NFSIM_ALLOW_XML_FALLBACK=1`; supports `utl`, `equilibrate`, `rnf` |
| Standalone `NFsim -xml FILE` / `-rnf FILE` | **NFcore** (XML/RNF) | N/A | CLI release archive or `-DBUILD_NFSIM_CLI=ON` | Linux x86_64, macOS arm64/x86_64, Windows x86_64 | Classic NFsim CLI; **(post-`v3.0.0a1` `main`)** adds `-i <time>` initial start time flag |
| `model.simulate_nfnext_gpu(sample_times, ...)` | **NFnext GPU** (`backend="metal"` default arg) | `backend="metal"` or `backend="cuda"`; `mode="unary"` or `mode="graph"` **(post-`v3.0.0a1` `main`)** | Compiled Metal (macOS arm64) or CUDA build + physical GPU | macOS arm64 (Metal); CUDA hosts (source build) | **Strict fail-closed, zero CPU fallback:** raises if device/route is unavailable or model uses unsupported constructs |

**Quick rule of thumb:**

- Start with **`model.simulate(method="nf", seed=...)`** (NFnext) for Python workflows—it is fast, XML-free, and verified on the full `TIER_NF` corpus.
- Switch to **`model.simulate(method="nfcore", seed=...)`** if you need NFsim's `equilibrate` phase, an explicit `traversal_limit` (`-utl`), or direct comparison against classic NFsim internals.
- Use **`bng_cpp` / `bionetgen execute`** for existing BNGL action files with `simulate_nf`, or the bundled **`NFsim`** binary for existing `.xml` / `.rnf` pipelines.
- Use **`model.simulate_nfnext_gpu()`** only for large fixed-shape ensembles on qualified Apple Metal or NVIDIA CUDA hardware after checking `bionetgen.gpu_backend_capabilities()`.

---

## 3. Verified Examples & Confirming Which Backend Ran

Save the following reversible binding model as `nf_binding.bngl`:

```bngl
begin model
begin parameters
  k_on  0.01
  k_off 0.1
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 100
  B(a) 100
end seed species
begin observables
  Molecules AB     A(b!1).B(a!1)
  Molecules A_free A(b)
end observables
begin reaction rules
  bind: A(b) + B(a) <-> A(b!1).B(a!1) k_on, k_off
end reaction rules
end model
```

### Standard Python Network-Free Workflow (NFnext)

```python
import bionetgen

model = bionetgen.load("nf_binding.bngl")

# Default for method="nf" in Python: NFnext
result = model.simulate(method="nf", t_end=10.0, n_steps=20, seed=42)
assert result.backend == "nfnext"
print("Backend:", result.backend)
print("Final AB:", result.observables["AB"][-1])
```

### Explicit Embedded NFcore Workflow

```python
import bionetgen

model = bionetgen.load("nf_binding.bngl")

# Explicit NFcore with NFsim-specific options (equilibrate, traversal_limit)
result_nfcore = model.simulate(
    method="nfcore",
    t_end=10.0,
    n_steps=20,
    seed=42,
    equilibrate=1.0,
    traversal_limit=3,
)
assert result_nfcore.backend == "nfsim"
print("Backend:", result_nfcore.backend)
print("Final AB:", result_nfcore.observables["AB"][-1])
```

### Standalone `NFsim` CLI Workflow (XML Input)

```bash
bionetgen export nf_binding.bngl --format xml --output nf_binding.xml
./bionetgen-macos-arm64/NFsim -xml nf_binding.xml -sim 10 -oSteps 20 -seed 42 -o nf_binding_nf.gdat
```

### NFnext GPU Workflow (Bounded, Fail-Closed)

First inspect what GPU routes are compiled and physically available on your machine:

```python
import bionetgen

caps = bionetgen.gpu_backend_capabilities()
print(caps)
```

In **`v3.0.0a1`**, `model.simulate_nfnext_gpu()` supports only single-molecule-type, single-stateful-site, static elementary state-change models (`mode="unary"`). Save `two_state.bngl`:

```bngl
begin model
begin parameters
  kf 0.5
  kr 0.25
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin observables
  Molecules AP A(s~P)
end observables
begin reaction rules
  A(s~U) <-> A(s~P) kf, kr
end reaction rules
end model
```

Then run a 256-trajectory Metal batch (requires macOS Apple Silicon; on a CUDA source build with an NVIDIA GPU pass `backend="cuda"`):

```python
import bionetgen

model = bionetgen.load("two_state.bngl")
gpu_res = model.simulate_nfnext_gpu(
    [0.0, 1.0, 2.0, 5.0],
    seed=42,
    batch_size=256,
    backend="metal",
)
print("Backend:", gpu_res.backend, "shape:", gpu_res.observables["AP"].shape)
print("Ensemble mean AP:", gpu_res.observables["AP"].mean(axis=0))
```

**(Post-`v3.0.0a1` `main` only):** Pass `mode="graph"` to `model.simulate_nfnext_gpu(..., mode="graph", backend="metal"|"cuda")` for general graph SSA across `TIER_NF` (binding/unbinding, molecule creation/deletion, complex deletion, dynamic rate functions, and `Molecules`/`Species` observables). Unsupported constructs (compartments, events, delays, energy patterns, population maps, rule filters, unbonded `SameComplex` constraints, multi-copy local scoping, or an unavailable device) raise an explicit error with zero CPU fallback.

### Confirming Which Backend Ran

1. **In Python:** inspect `result.backend` (`"nfnext"` for NFnext, `"nfsim"` for embedded NFcore, `"metal"`/`"cuda"` on `GpuBatchSimResult`).
2. **To forbid XML fallback in NFcore:** run with `BNG_NFSIM_REQUIRE_DIRECT=1` in your environment.
3. **For GPU availability:** inspect `bionetgen.gpu_backend_capabilities()`, which distinguishes compiled routes (`finite_batch_ssa`, `nfnext_unary_state_change`, and on `main`, `nfnext_graph_corpus`) from whether a physical GPU is present on the host.

---

## 4. Semantic Support, Evidence, Seeds & Known Limitations

### Major Semantic Families & Current Evidence

| Semantic Family | NFnext (CPU) | Embedded NFcore | Primary Independent Evidence |
| --- | --- | --- | --- |
| Elementary binding/unbinding, state changes, synthesis/deletion, `DeleteMolecules` | Supported | Supported | Full `TIER_NF` corpus (`simple_system`, `localfunc`, `motor`, `tlbr`, 32 seeds) vs. pinned native NFsim (`#148`, `#149`, run `44814871639` / `44880029171`) |
| `Molecules` & `Species` observables (with automorphism multiplicity) | Supported | Supported | `TIER_NF` parity (`#142`, `#146`, `#148`) |
| Dynamic global & local functional rates (`Function`, `FunctionProduct`, `MM`, `Sat`, `Hill`, `TFUN`) | Supported (FunctionVM) | Supported | `localfunc` in `TIER_NF` + `#143`/`#147` cases; note NFsim rejects `TotalRate` on local functions, `FunctionProduct`, `MM`, and `Arrhenius` (`#1028`) |
| Rule modifiers & filters (`MatchOnce`, `TotalRate`, `MoveConnected`, `include_*`, `exclude_*`) | Supported | Supported | `#147` lowering/execution checks and `#146` NFcore parity |
| Compartments & transport | Supported | Supported | `#147`/`#151` compartment & count-rate tests; note native NFsim XML normalization documented in `tests/validation/README.md` |
| Static & dynamic energy patterns (`Arrhenius`) | Supported (static folded + observable-dependent dynamic Function rates); time-dependent energy fails closed | Supported (static); native NFsim binds parameters only | Analytic detailed-balance checks (`#147`, `architecture_nfnext_bng_lowering_bridge`) |
| Nonequilibrium barriers & `driven_by(W)` | Opt-in (`BNG_NFSIM_GENERAL_ENERGY=1`) | Opt-in (`BNG_NFSIM_GENERAL_ENERGY=1`) | Analytic detailed-balance and King-Altman NESS laws (`#177`, [nonequilibrium_energy.md](nonequilibrium_energy.md)) |
| Hybrid particle–population (population maps) | Supported for simple lowerable map shapes; unsupported shapes fail closed | Supported via `generate_hybrid_model` (HPP) | `#147`/`#150` pure-death analytic, Gillespie SSA, and 512-seed pinned-native NFsim checks |
| NFsim `equilibrate` & `-utl` (`traversal_limit`) | Not supported (raises `ValueError`) | Supported (`equilibrate`, `traversal_limit`) | `#146`, `python/bionetgen/model.py:1407-1410` |
| `.rnf` protocol scripts | Not supported | Supported (`simulate_nf` `-rnf` and standalone `NFsim -rnf`) | PR `#1033`, `cpp/nfsim/NFinput/rnfRunner.cpp` |

### Seed Semantics, Parity vs. Performance

- **`seed=0` is never reproducible** (draws from `std::random_device` on every engine). Always specify an explicit nonzero seed (`seed=42`, etc.) for repeatable trajectories.
- **Same engine, same nonzero seed:** deterministic and pathwise identical.
- **NFnext vs. NFcore / standalone NFsim:** different internal rule representations and RNG consumption orders mean identical seeds do **not** give identical single trajectories. Compare **ensemble distributions** (observable means with pooled standard errors, empirical CDFs / KS tests, and exact conservation invariants) across independent nonzero seed ranges.
- **Performance vs. parity:** Per `AGENTS.md` and `DECISIONS.md` item 8, throughput gains never justify altering stochastic semantics; every NFnext/GPU kernel change must pass statistical parity against an independent law or pinned native NFsim.
- **GPU hardware qualification (`#474`):** Metal and CUDA are qualified independently—Apple Silicon Metal results do not qualify CUDA, and vice versa. On `main` (`755f8396`), `#474` recorded actual-device qualification on Apple Silicon Metal and NVIDIA TITAN V CUDA for finite batch SSA and bounded NFnext GPU (`mode="unary"` and `mode="graph"` on `TIER_NF`).

### Known Limitations & Open Diagnostics

- **BNGL action files still invoke NFcore:** `simulate({method=>"nf"})` and `simulate_nf()` inside BNGL action blocks dispatch to NFcore rather than NFnext and do not yet accept `method=>"nfcore"` or `method=>"nfnext"`.
- **Scheduled `Cross-tool parity` diagnostic:** On `main` (`90832910`), the push-triggered `Cross-tool parity` run (`45812432511`) passed, while the scheduled `Cross-tool parity` run (`45833971282`) failed in the scheduled-only `Measure Tier-P direct/XML outcomes (scheduled)` step and `Conformance findings` timeout. Track those diagnostics before claiming full Tier-P parity across every historical model.
- **GPU construct boundaries:** `simulate_nfnext_gpu` rejects compartments, events, delays, energy patterns, population maps, rule filters, unbonded `SameComplex` constraints, and multi-copy local scoping fail-closed. In `v3.0.0a1`, it is further restricted to single-site unary state-change models.

### How to Reproduce and Report a Network-Free Disagreement

1. Confirm which backend ran (`result.backend`) and record `bionetgen --version` (or Git commit SHA).
2. Run the same model with an explicit nonzero seed ensemble (e.g., 32–200 seeds) on both `method="nf"` (NFnext) and `method="nfcore"` (and, if available, standalone `NFsim -xml`).
3. Check whether the disagreement is:
   - a **single-seed difference across different engines** (expected unless construction and draw order match—verify ensemble means/CDFs instead),
   - a **conservation / invariant violation**, or
   - a **statistically significant distributional divergence** (or a crash/unexpected refusal).
4. Reduce to the smallest `.bngl` file that reproduces the issue and file it at [RuleWorld/BNG3/issues](https://github.com/RuleWorld/BNG3/issues) with the model, seed(s), backend names, expected vs. observed summary statistics, and `bionetgen info --detail`.

---

## 5. What Comes Next for NFnext and NFsim

Grounded in [Maintainer Decisions](DECISIONS.md), the historical [NFnext Dynamic-Rate Runtime Plan](archive/plans/NFNEXT_DYNAMIC_RUNTIME_PLAN.md), the [NFsim Performance Plan](archive/plans/NFSIM_GPU_PERF_PLAN.md), and current `main` (`90832910`), here is the clear separation between what has shipped, what is on `main`, and what remains planned:

- **Shipped in `v3.0.0a1` (`8482215c`):**
  - NFnext promoted as the Python `method="nf"` default (`#832`, `#149`) after passing `TIER_NF` parity (`#148`), including dynamic observable rates, dynamic energy expressions, and simple dynamic population-map rates (`#147`).
  - Embedded NFcore retained as `method="nfcore"` (direct construction by default) and as the BNGL action-block backend (`simulate_nf` / `simulate({method=>"nf"})`).
  - NFcore2 unlinked from the default build (`#660`).
  - Fail-closed `simulate_nfnext_gpu` unary state-change Metal route.
- **Added on `main` after `v3.0.0a1` (`8482215c..90832910`):**
  - Upstream `RuleWorld/NFsim` sync through `d45b7d99` (`v2.0.1` + `#160`, PR `#1047`) and `-i` initial start time CLI flag (PR `#1052`).
  - `simulate_nfnext_gpu(..., mode="graph")` for Metal and CUDA across `TIER_NF` (PRs `#1040`, `#1041`, `#1044`) with separate real-device Apple Silicon Metal and NVIDIA TITAN V CUDA receipts (`#474`).
- **Planned next milestones (not yet shipped):**
  1. **Action-block routing & parity:** Extend BNGL action dispatch (`simulate_nf` / `simulate({method=>"nf"})`) to support explicit NFnext/NFcore selection once NFnext covers the remaining action-level options (`equilibrate`, `utl`, `.rnf` interoperability, and Tier-P scheduled corpus diagnostics).
  2. **General hybrid & population-map coverage:** Broaden NFnext's executable population-map and dynamic-threshold coverage beyond the currently lowerable simple shapes without relaxing fail-closed diagnostics (`#150`).
  3. **CPU ensemble & specialized rule-family throughput:** Expand compile-once/many-trajectory CPU ensembles and rule-family / scaffold / polymer optimizations (`DECISIONS.md` NFnext consolidation step 5; [NFSIM_GPU_PERF_PLAN.md](archive/plans/NFSIM_GPU_PERF_PLAN.md)).
  4. **GPU scope expansion:** Any widening of `simulate_nfnext_gpu` beyond its documented `mode="unary"` / `mode="graph"` (`TIER_NF`) boundaries requires separate fail-closed lowering plus actual-device statistical parity receipts for each GPU backend (Metal and CUDA independently).
  5. **Criteria for any future default change:** No backend default changes (such as switching BNGL action `simulate_nf` from NFcore to NFnext, or promoting any GPU route) without exact-main independent parity against pinned native NFsim and analytic laws across the affected corpus, zero silent fallbacks, and updated user documentation.

### Related Technical & Historical Documents

- [Architecture Overview](architecture.md) — C++ libraries, `CompiledModel`, NFcore, and NFnext seams
- [Maintainer Decisions](DECISIONS.md) — Final policies (items 4, 5, 7, 8, 16, 17)
- [NFnext Dynamic-Rate Runtime Plan](archive/plans/NFNEXT_DYNAMIC_RUNTIME_PLAN.md) — Historical staged plan for dynamic energy & population maps
- [NFsim Performance Plan](archive/plans/NFSIM_GPU_PERF_PLAN.md) — Historical CPU/ensemble/GPU performance design
- [GPU Batch SSA Evaluation](GPU_BATCH_SSA_EVALUATION.md) — Finite-network Metal/CUDA batch SSA evaluation and hardware measurements
- [Nonequilibrium Energy](nonequilibrium_energy.md) — Experimental barrier patterns and driven reservoirs
