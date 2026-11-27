# What BioNetGen 3 Supports (Capability Guide)

This guide gives a task-oriented view of what BioNetGen 3 (BNG3) supports, which backend or optional extra each workflow uses, and where current boundaries sit. It summarizes—and links directly to—the traceable 997-row [Capability Union Inventory](CAPABILITY_UNION_INVENTORY.md) and [machine-readable capability matrix](../provenance/capability-matrix.yml) rather than maintaining a second row-by-row ledger by hand.

## Release Target and Provenance

Support claims below distinguish the **published pre-release** from **source `main`**:

| Target | Revision / Version | Pinned Upstream Oracles |
| --- | --- | --- |
| **Published pre-release** | `v3.0.0a1` (`8482215c`, GitHub Releases) | `RuleWorld/bionetgen@9601746f`, `RuleWorld/NFsim@8c449bbc`, `RuleWorld/PyBioNetGen@28bf351a` |
| **Source checkout (`main`)** | `9d6d5321` (`origin/main`) | `RuleWorld/bionetgen@740006ff` (v2.9.5), `RuleWorld/NFsim@d45b7d99` (v2.0.1 + #160), `RuleWorld/PyBioNetGen@28bf351a` (v0.8.7 lineage) |

Authoritative source pins and oracle digests live in [`provenance/upstreams.lock.yml`](../provenance/upstreams.lock.yml); release policies live in [Maintainer Decisions](DECISIONS.md). Features added after `v3.0.0a1` are marked **(post-`v3.0.0a1` `main`)** below.

### How Support Levels Are Classified

- **Default:** Included in the standard BNG3 wheel/binary and selected automatically without extra installs or flags.
- **Explicit backend or extra:** Supported when selected via an argument, environment variable, build flag, or optional Python extra (`plotting`, `notebook`, `jax`, `full`, `legacy`).
- **Bounded qualification:** Supported and verified within an explicitly documented model class, hardware target, or corpus slice; unsupported constructs fail closed rather than approximating.
- **Experimental / opt-in:** Gated behind an explicit environment variable (e.g., `BNG_NFSIM_GENERAL_ENERGY`) because canonical upstream tools do not implement the construct.
- **Explicitly refused / unsupported:** Out of scope or not yet lowered; BNG3 reports a diagnostic naming the construct instead of silently approximating it.

---

## 1. Writing and Executing BNGL Models & Actions

| Capability | Entry Point | Support Level | Scope, Boundaries & Traceability |
| --- | --- | --- | --- |
| Core BNGL model blocks (`parameters`, `molecule types`, `seed species`, `observables`, `reaction rules`, `functions`, `compartments`, `energy patterns`, `population maps`) | `bionetgen.load()`, `bionetgen check`, `bng_cpp` | **Default** | Parsed in-process by C++17 ANTLR4 (`cpp/parser/`) and compiled into `CompiledModel`. Covers `bngl.*` (79 rows), `builtin.*` (30 rows), `operator.*` (17 rows), `option.*` (14 rows) in [CAPABILITY_UNION_INVENTORY.md](CAPABILITY_UNION_INVENTORY.md). |
| Rate laws (`Ele`, mass action, `Function`, `FunctionProduct`, `MM`, `Sat`, `Hill`, `Arrhenius`, `TFUN` inline/file, `TotalRate`) & rule modifiers (`DeleteMolecules`, `MoveConnected`, `MatchOnce`, `include_reactants`, `exclude_reactants`, `include_products`, `exclude_products`) | BNGL rules & actions | **Default** | Shared compiled rate-law and rule-plan machinery (`cpp/compile/CompiledRateLaw.hpp`, `cpp/engine/NetworkRulePlan.cpp`). Verified against pinned BNG2 and native NFsim (`bngl.*`, #139, #143). Note: NFsim rejects `TotalRate` on local functions, `FunctionProduct`, `MM`, and `Arrhenius` matching upstream NFsim. |
| BNGL actions (`generate_network`, `simulate`, `simulate_ode`/`ssa`/`pla`/`psa`/`nf`, `parameter_scan`, `bifurcate`, `setParameter`, `setConcentration`, `addConcentration`, `save*`/`reset*`, `setVolume`, `substanceUnits`, `readModel`, `readNetwork`, `readSBML`, `write*`, `visualize`, `quit`, `version`, `codename`) | `model.execute()`, `bionetgen execute`, `bionetgen run -i`, `bng_cpp` | **Default** | Covers 231 `action.*` rows (#140, #163). **(Post-`v3.0.0a1` `main`):** `prefix`/`suffix` honored across all `write*` and `visualize` actions, `writeMfile_all`/`writeLaTeXfile`, `bifurcate` continuation + per-observable `.scan` files, `readModel` refresh, `setModelName`, `print_net`, `simulate_protocol`, `readNFspecies`, `readSBML`, LPS, and `codename`. |
| Physical units (`begin units`, `[unit]` annotations) | BNGL models & CRN export | **Default** (network/ODE); **Bounded** (NFsim) | Dimensional checking and count-rate conversion are documented in [BNG3_UNITS.md](BNG3_UNITS.md). Unconvertible unit systems fail closed. |
| Nonequilibrium energy extensions (`begin barrier patterns`, `driven_by(W)`) | BNGL rules + `BNG_NFSIM_GENERAL_ENERGY=1` | **Experimental / opt-in** | `energy.barriers` and `energy.reservoirs` (#177). Refused by default unless `BNG_NFSIM_GENERAL_ENERGY=1` is set; kinetics exporters (SBML, MATLAB, LaTeX, C++, etc.) fail closed on energy models. Verified against analytic detailed-balance and King-Altman NESS laws; see [nonequilibrium_energy.md](nonequilibrium_energy.md). |
| Delayed rules (`delay(...)`) | Native ODE/SSA & BNGIR v0.2 | **Bounded qualification** | Method-of-steps ODE and delayed-jump SSA in native C++; BNGsim and some exporters fail closed (`requireNoDelayedSemantics`). See #475. |

---

## 2. Network Generation & Finite-Network Simulation

| Capability | Entry Point | Backend / Extra | Support Level | Scope, Boundaries & Traceability |
| --- | --- | --- | --- | --- |
| Reaction network generation | `model.generate_network()`, `generate_network` action | Native C++ (`bng_core` + single `nauty`) | **Default** | Graph-isomorphism-aware canonical species and statistical factors. Verified on the 71-model strict BNG2 validation corpus (`scripts/validate.py --strict-references`) and cross-tool parity (`ci.yml`, `parity.yml`). |
| Deterministic ODE (`cvode`) | `model.simulate(method="ode")`, `bionetgen run -m ode` | Native SUNDIALS CVODE | **Default** | Supports `rtol`, `atol`, `max_step`, `sparse`, `steady_state`, `steady_state_tol`, `stop_if`, `sample_times`, `continue_simulation`, SBML algebraic rules (native IDA), and native dynamic events (`ADR 0004`). |
| Direct Gillespie SSA | `model.simulate(method="ssa")`, `bionetgen run -m ssa` | Native C++ SSA | **Default** | Reproducible for explicit nonzero `seed`; `seed=0` draws from `std::random_device`. Supports `stop_if`, `sample_times`, `max_sim_steps`, `output_step_interval`, `continue_simulation`. |
| Partitioned Leaping (PLA) & Partial-Scaling (PSA) | `model.simulate(method="pla"\|"psa")` | Native C++ | **Default** | Accepts `pla_config` (PLA) and `psa_poplevel` (PSA). `seed` is not forwarded to `simulate_pla`/`simulate_psa` in the current Python wrapper. |
| Batched direct SSA (CPU thread pool) | `model.simulate_batch_ssa(backend="cpu")` or `model.simulate(method="ssa", batch_size=N)` | Native C++ thread pool | **Default** | Deterministic per-trajectory SplitMix64 seeding from `(base_seed, trajectory_id)` independent of thread count. |
| Batched direct SSA (GPU: Metal / CUDA) | `model.simulate_batch_ssa(backend="metal"\|"cuda"\|"auto")` | Apple Metal (macOS arm64) / NVIDIA CUDA (Linux/Windows CUDA builds) | **Bounded qualification** | Fixed pre-generated networks: mass-action in `v3.0.0a1`, extended on **(post-`v3.0.0a1` `main`, PR `#1069`)** with `TotalRate`, absolute-flux, and a 26-opcode functional-rate VM on Metal & CUDA; rejects unsupported rate laws and non-finite/negative rates fail-closed (`backend.gpu`, #474). Qualified separately on actual Apple Silicon Metal and NVIDIA CUDA hardware; see [GPU_BATCH_SSA_EVALUATION.md](GPU_BATCH_SSA_EVALUATION.md). |
| Optional BNGsim finite backend | `model.simulate(method="ode"\|"ssa"\|"psa", backend="bngsim")` or `BIONETGEN_FINITE_BACKEND=bngsim` | CMake `-DBUILD_BNGSIM_ADAPTER=ON` | **Explicit backend** | Optional build-time adapter against pinned `lanl/bngsim@3295c4d3` (`v0.18.0`, `backend.bngsim`, #144, [ADR 0003](adr/0003-bngsim-canonical-finite-backend.md)). Supports ODE, SSA, PSA (`poplevel > 1`), authored `TotalRate`, static 2D/3D compartments, and supported `bng3_events`. Not compiled into default PyPI/GitHub wheels; rejects dynamic/event-resized compartments, `distrib_*`/delayed events, energy/barrier/driven rules, population maps, PLA, protocols, and non-reference rates fail-closed ([bngsim-migration-status.md](bngsim-migration-status.md)). |
| Optional JAX CPU ODE / SSA | `bionetgen.jax_ode`, `bionetgen.jax_ssa` | Extra: `bionetgen[jax]` | **Explicit extra / bounded** | Separate CPU JAX modules (`backend.jax`, #473). Supports mass-action and time-dependent ODEs with autodiff gradients and first-order SSA; rejects observable-dependent functional rates fail-closed. |

---

## 3. Network-Free Simulation

See the dedicated [Network-Free Simulation Guide (NFsim & NFnext)](network_free_simulation.md) for the complete decision table, seed semantics, and roadmap.

| Engine / Route | Entry Point | Support Level | Scope, Boundaries & Traceability |
| --- | --- | --- | --- |
| **NFnext (CPU)** | `model.simulate(method="nf")` (default in Python), `model.simulate(method="nfnext")`, `bionetgen run -m nf` | **Default** (Python & `bionetgen run`) | Compiled directly from `CompiledModel → NFIR` (no XML). Promoted after passing full `TIER_NF` (`simple_system`, `localfunc`, `motor`, `tlbr`, 32 seeds) parity against pinned native NFsim (`nfnext.full`, #147–#149, `DECISIONS.md` item 4). Rejects NFcore-only `equilibrate` and `traversal_limit` options; unsupported population-map or time-dependent energy shapes fail closed. |
| **Embedded NFcore** | `model.simulate(method="nfcore")`; BNGL action blocks `simulate_nf` / `simulate({method=>"nf"})` | **Explicit selector** (Python) / **Default** (BNGL actions) | Direct AST/CompiledModel construction (`construction_path="direct"`), with opt-in XML fallback (`BNG_NFSIM_ALLOW_XML_FALLBACK=1`). Supports `equilibrate` and `traversal_limit` (`-utl`). Verified against pinned native NFsim (`nfsim.*`, `nf.option.*`, #146). |
| **Standalone `NFsim` CLI** | `NFsim -xml model.xml ...` or `-rnf script.rnf` (in CLI release archives) | **Default** (CLI archive) | Embedded NFcore exposed with classic NFsim CLI flags (`nf.option.*`, 43 rows). **(Post-`v3.0.0a1` `main`):** adds `-i` initial time flag and upstream NFsim `v2.0.1` + `#160` sync. |
| **Hybrid particle–population (HPP)** | `generate_hybrid_model` / population maps in NFcore & supported NFnext shapes | **Bounded qualification** | `hybrid.execution` (#150). Verified for conversion, dimer, cycle, protocol, and bounded compartment/dynamic-rate models; unsupported map shapes fail closed. |
| **NFnext GPU** | `model.simulate_nfnext_gpu(..., backend="metal"\|"cuda", mode=...)` | **Bounded qualification** | Explicit opt-in, no CPU fallback. In **`v3.0.0a1`**: single-molecule, single-stateful-site, static elementary state-change models only (`mode="unary"`). **(Post-`v3.0.0a1` `main`):** adds `mode="graph"` for `TIER_NF` graph SSA on Apple Metal and NVIDIA CUDA (#474), expanded in PR `#1069` with `TotalRate`, reactant `include_reactants`/`exclude_reactants` filters, and static energy-folded `Arrhenius` patterns; still rejects compartments, events, delays, population maps, barrier patterns / non-folded energy expressions, product filters, unbonded `SameComplex` constraints, and multi-copy local scoping fail-closed. |

---

## 4. Python API, Interchange, Analysis & CLI Workflows

| Capability | Entry Point | Support Level | Scope, Boundaries & Traceability |
| --- | --- | --- | --- |
| Modern Python API (`load`, `run`, `BioNetGenModel`, `SimResult`, runtime topology edits, `ModelBuilder`) | `import bionetgen` | **Default** | In-process C++ bindings (`_bionetgen_cpp`), NumPy arrays, Jupyter `_repr_html_()`. Covers `py.*` (385 rows, #171). |
| Parameter scans (1D/2D) & local sensitivities | `model.parameter_scan()`, `parameter_scan_2d()`, `sensitivity_analysis()`, `bionetgen scan`, `bionetgen sensitivity` | **Default** (core); `plotting` extra for DataFrames/plots | Serial or isolated multi-process (`parallel=N`) execution. |
| Chemical Reaction Network (CRN) API | `model.species`, `model.complexes`, `model.reactions`, `model.stoichiometric_matrix`, `model.to_crn()`, `model.write_crn()` | **Default** | `crn.api` (#170). Portable JSON consumed by independent formal tools such as `crnt-lean`. |
| BNGIR JSON interchange & exact semantic equality | `bionetgen.to_bngir()`, `from_bngir()`, `semantic_equal()` | **Default** (v0.2) | `bngir.v02`, `bngir.native`, `bngir.equality` (#153–#156). v0.2 is the public default; `semantic_equal` compares process models up to consistent renaming and raises `EqualityUndecided` when undecidable rather than returning `False`. |
| Export & visualization formats | `model.write_bngl()`, `write_net()`, `write_xml()`, `write_sbml()`, `sbml_multi()`, `write_matlab()`, `write_latex()`, `contact_map()`, `regulatory_graph()`, `rule_influence_graph()`, `reaction_network_graph()`, `ruleviz_pattern()`, `ruleviz_operation()`, `process_graph()`, `bionetgen export`, `bionetgen visualize` | **Default** | Covers `io.*` and `action.write*` (#163). Kinetics exporters fail closed on energy/barrier/driven models (`io::requireNoEnergySemantics`). |
| Unified Click CLI & standalone `bng_cpp` | `bionetgen` (12 subcommands), `bng_cpp` | **Default** | See [CLI Reference](cli_reference.md). **(Post-`v3.0.0a1` `main`):** `bng_cpp --outdir` / `--output_dir` added. |
| PyBioNetGen compatibility API & optional Perl fallback | `bionetgen.run(path, out=...)`, `bionetgen.bngmodel`, `bionetgen.network.network.Network`, `bionetgen.sim_getter`, `BIONETGEN_USE_PERL=1` | **Explicit / scoped compatibility** | `pybionetgen.api-cli-atomizer` (#171–#172). `bionetgen[legacy]` provides Cement/pyparsing/pylru if legacy internals are used; `libroadrunner` is installed separately for `sim_getter(..., sim_type="libRR")`. PySB adapter is not provided. See [Migration Guide](migration_guide.md). |

---

## 5. SBML Import & Atomizer

For SBML translation, **parsing, representability, conversion, structural round trip, execution, and agreement with source behavior are distinct stages**—a model that parses or converts is not claimed to reproduce source behavior until an independent oracle confirms it.

### Authoritative Classification Vocabulary

| Status | Meaning |
| --- | --- |
| `passed` | Converted, executed, and agreed with the independent reference (official SBML Test Suite reference or libRoadRunner on the original SBML). |
| `unsupported` | Refused explicitly with a named diagnostic because the model uses a construct BNG3 cannot represent faithfully (not a silent approximation). |
| `not_comparable` / harness limit | Model converted cleanly, but a pointwise comparison could not be made (e.g., random event-execution order draw, undefined `t=0` observable, or ensemble budget). Not an Atomizer refusal. |
| `failed` | Model converted or executed and **disagreed** with the source semantics (a defect). |
| `timeout` | Exceeded the per-model validation time budget. |
| `not_tested` / `not-applicable` | No official time-course reference exists (e.g., FBC steady-state cases) or the stage did not run. |

### SBML Scope & Measured Evidence

Requires `bionetgen[full]` (specifically `python-libsbml`). Entry points: `bionetgen.from_sbml(path, atomize=...)`, `bionetgen.sbml_to_bngl(...)`, `bionetgen atomize`.

- **SBML Level 3 Core & `comp` (129 rows: `sbml.core.*`, `sbml.comp.*`; #159, #160):**
  - Supports reactions, kinetic laws, compartments (including dynamic volumes via rate/assignment rules), initial assignments, assignment/rate rules, bounded linear algebraic rules, fast reactions reducible to pseudo-steady state (L3V1), events (fixed-time, state-triggered root finding, priorities, persistent/initialValue semantics, delays), and hierarchical `comp` flattening.
  - **Measured official SBML Test Suite (`3.5.0` @ `cf38585f`, 1,923 cases; recorded at `d6f26cc9` in [`provenance/sbml-campaign/expectations.json`](../provenance/sbml-campaign/expectations.json)):**
    - Conversion: **1,823 passed / 100 unsupported**
    - Official reference comparison: **1,805 passed / 117 unsupported / 1 failed** (`stochastic/00003`; see [SBML_CONFORMANCE_FINDINGS.md](SBML_CONFORMANCE_FINDINGS.md))
    - Structural round trip: **1,828 passed / 95 not_tested**
  - Exact refusal taxonomy (Atomizer vs. harness vs. not-applicable) is generated directly from the manifest in [ATOMIZER_LIMITATIONS.md](ATOMIZER_LIMITATIONS.md).
- **SBML Multi (`sbml.multi.*`, 45 rows; #161):**
  - Structured species-type, feature/state, binding-site, and rule reconstruction with fail-closed diagnostics for unsupported nested compartment-reference placements.
- **Curated BioModels (`BIOMD*`, 1,096 records: 1,075 declared SBML, 10 archives, 11 non-SBML; [`provenance/curated-biomodels-corpus-inventory.json`](../provenance/curated-biomodels-corpus-inventory.json)):**
  - Atomized mode snapshot (compared against libRoadRunner CVODE at `t_end=1.0`): **785 passed / 117 unsupported / 11 unsupported_format / 174 timeout / 9 failed**. See [CURATED_BIOMODELS_CORPUS.md](CURATED_BIOMODELS_CORPUS.md) for flat vs. atomized mode details and open failures.
- **Other SBML Level 3 packages (`DECISIONS.md` item 12):**
  - **Refused by policy (out of kinetic BNGL scope):** `fbc` (flux-balance optimization—34 official suite cases), `qual` (logical models without reaction rates), and `spatial` (geometry/PDE/spatial-particle models). Each emits a named diagnostic rather than a nominal import.
  - **Target import / preserved metadata:** `distrib` (selected event draws implemented), `arrays`, `dyn`, and metadata preservation for `layout`, `render`, and `groups`. Dedicated row-by-row matrix entries for these packages remain tracked under #137.

---

## 6. Platforms & Distribution Boundaries

| Surface | Linux x86_64 | Linux aarch64 | macOS arm64 | macOS x86_64 | Windows x86_64 | Other (`musllinux`, 32-bit) |
| --- | --- | --- | --- | --- | --- | --- |
| Python wheels (CPython 3.9–3.14) | Yes (`manylinux_2_28`) | **(Post-`v3.0.0a1` `main`):** Yes (`manylinux_2_28_aarch64`); `v3.0.0a1`: build from source | Yes (`macosx_11_0`) | Yes (`macosx_11_0`) | Yes (`win_amd64`) | Build from source |
| CLI archives (`bng_cpp` + `NFsim`) | Yes | **(Post-`v3.0.0a1` `main`):** Yes (`bionetgen-linux-aarch64`); `v3.0.0a1`: build from source | Yes | Yes | Yes | Build from source |
| Native CPU solvers & NFnext / NFcore | Yes | Yes | Yes | Yes | Yes | Source build |
| GPU batch SSA & NFnext GPU | CUDA (CUDA source build + NVIDIA GPU) | CPU only | Metal (Apple Silicon) | CPU only | CUDA (CUDA source build + NVIDIA GPU) | CPU only |
| Optional `bngsim` backend | Source build (`-DBUILD_BNGSIM_ADAPTER=ON`) | Source build | Source build | Source build | Source build | Source build |

---

## 7. Known Inventory and CI Discrepancies (Reconciliation Audit)

To prevent stale or conflicting claims, the following discrepancies between the inventory, prose docs, and CI runs are recorded explicitly as of `main` (`9d6d5321`):

1. **Matrix promotion vs. `v3.0.0a1` tag:** On `main` (`9d6d5321`), all 997 rows in [`provenance/capability-matrix.yml`](../provenance/capability-matrix.yml) and [CAPABILITY_UNION_INVENTORY.md](CAPABILITY_UNION_INVENTORY.md) are marked `implemented` (promoted via PRs `#1048` and `#1059`). At the published `v3.0.0a1` tag (`8482215c`), the same 997-row matrix recorded `92 implemented / 172 partial / 732 unassessed / 1 deferred`—and 35 post-tag commits landed real behavioral additions (BNG2 2.9.5 and NFsim v2.0.1 syncs, native Linux `aarch64` wheels/CLI, NFnext GPU graph mode + `TotalRate`/filters/Arrhenius, explicit BNGL action `nfnext`/`nfcore` routing, SSA native SBML events & piecewise L3V1 fast reactions, clean-install CLI/compat fixes, `bng_cpp --outdir`, `NFsim -i`, action and PyBioNetGen signature fixes). Do not extrapolate post-tag `main` rows back to `v3.0.0a1`.
2. **Decision 12 SBML package rows:** As noted in [CAPABILITY_UNION_INVENTORY.md](CAPABILITY_UNION_INVENTORY.md), `distrib`, `arrays`, `dyn`, `layout`, `render`, `groups`, `fbc`, `qual`, and `spatial` do not yet have dedicated rows in the 997-row matrix; their status is governed by `DECISIONS.md` item 12 and `ATOMIZER_LIMITATIONS.md`.
3. **Scheduled `Cross-tool parity` status:** The earlier `90832910` scheduled `Cross-tool parity` failures (`45833971282`) — direct-path `TFUN` breakpoints (`test_tfun_validation`), Tier-P timeout budgets, and scheduled NFsim/libRoadRunner oracle wiring — were resolved by PRs `#1061`, `#1062`, and `#1070`, and verified green in scheduled run `46011111253` on `9d6d5321`.
4. **PyPI distribution status:** The `v3.0.0a1` Release workflow (`45662137697`) succeeded for qualification, all 24 wheels, sdist, all 4 CLI archives, and GitHub Release publication, but failed in `Publish to PyPI` due to a missing PyPI Trusted Publisher configuration (`invalid-publisher`). Until that is configured and a release is uploaded, PyPI serves only `bionetgen 0.8.7` (PyBioNetGen).
