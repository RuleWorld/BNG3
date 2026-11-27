# Detailed BNG2 & PyBioNetGen → BNG3 Change Reference

This is the searchable, family-by-family reference of user-visible differences, unchanged compatibilities, and new additions when moving from **BNG2** or **PyBioNetGen** to **BioNetGen 3 (BNG3)**. For task-oriented recipes and a lab migration checklist, see the [Migration Guide](migration_guide.md).

## Declared Comparison Scope

| Reference / Target | Exact Revision / Version | Source Pin |
| --- | --- | --- |
| **BNG2 (`RuleWorld/bionetgen`)** | `740006ff3cfa0b6d5445e10367c9f2fcd0f75d67` (v2.9.5, on `main`); `9601746f8884ed19ab2acea49fe87fc4660ace46` (at `v3.0.0a1`) | [`provenance/upstreams.lock.yml`](../provenance/upstreams.lock.yml) |
| **NFsim (`RuleWorld/NFsim`)** | `d45b7d99cf1905199911a3187edbba585fad56ba` (v2.0.1 + `#160`, on `main`); `8c449bbccc4a0c54586ae562f46f4955e65fe876` (at `v3.0.0a1`) | [`provenance/upstreams.lock.yml`](../provenance/upstreams.lock.yml) |
| **PyBioNetGen (`RuleWorld/PyBioNetGen`)** | `28bf351a9bbfc197e19487c26dedda683716bb64` (v0.8.7 lineage) | [`provenance/upstreams.lock.yml`](../provenance/upstreams.lock.yml) |
| **BNG3 published pre-release** | `v3.0.0a1` (commit `8482215cf0117895f792b1be7d8cf14d2dcb1fcc`) | [GitHub Release `v3.0.0a1`](https://github.com/RuleWorld/BNG3/releases/tag/v3.0.0a1) |
| **BNG3 source `main`** | `9083291066a1cb60c8b4d94b53b38e19c584f899` | `origin/main` |

Behaviors added in the 23 commits between `v3.0.0a1` and `main` (`90832910`) are marked **(post-`v3.0.0a1` `main`)**.

---

## 1. Installation, Packaging & Dependencies

| Topic | Legacy Behavior (BNG2 / PyBioNetGen) | BNG3 Behavior | Impact | What to Do | Source / Evidence |
| --- | --- | --- | --- | --- | --- |
| PyPI `pip install bionetgen` | Installs PyBioNetGen `0.8.7` bundling Perl BNG2 + binaries | **`v3.0.0a1` is currently on GitHub Releases only** (PyPI still serves `0.8.7` until Trusted Publisher upload succeeds) | Running `pip install bionetgen` today does **not** install BNG3 | Install the matching wheel from [GitHub Releases `v3.0.0a1`](https://github.com/RuleWorld/BNG3/releases/tag/v3.0.0a1) or from a source checkout; pin `bionetgen<3` to stay on PyBioNetGen | PyPI JSON (`0.8.7`), Release run `45662137697` |
| Runtime dependencies | BNG2 requires Perl 5 + `run_network`/`NFsim` binaries; PyBioNetGen requires `cement`, `colorlog`, `pyparsing`, `pylru`, `xmltodict`, etc. | Core BNG3 requires only Python `>=3.9`, `numpy>=1.20`, `click>=8.0`, `packaging`, and the bundled `_bionetgen_cpp` C++17 extension; **no Perl required** | Faster startup, no subprocess/Perl environment fragility | Install optional extras (`plotting`, `notebook`, `jax`, `full`, `legacy`) only when needed | `pyproject.toml`, `README.md` |
| Plotting & DataFrames | PyBioNetGen installed plotting/SBML deps eagerly or via separate packages | `result.to_dataframe()`, `result.plot()`, and `bionetgen plot` require `bionetgen[plotting]` (`pandas`, `matplotlib`) | Calling `.plot()` / `.to_dataframe()` in a minimal wheel env raises `ImportError` | Install `bionetgen[plotting]` or `bionetgen[full]` | `pyproject.toml` |
| SBML & SymPy | PyBioNetGen bundled legacy Atomizer; `python-libsbml` required for SBML | `from_sbml()`, `sbml_to_bngl()`, `bionetgen atomize`, and `SympyOdes` require `bionetgen[full]` (`python-libsbml`, `sympy`, etc.) | Minimal install stays small; SBML/SymPy raise clear `ImportError` when absent | Install `bionetgen[full]` | `pyproject.toml`, `python/bionetgen/__init__.py` |
| Standalone non-Python binaries | BNG2 tarball (`BNG2.pl` + `bin/run_network` + `bin/NFsim`) | GitHub release CLI archives (`bionetgen-<platform>.tar.gz`) containing `bng_cpp` and `NFsim` | Pure C++ CLI execution without Python or Perl | Extract the platform archive and invoke `bng_cpp` or `NFsim` | `.github/workflows/release.yml` |

---

## 2. Executables, CLI Subcommands, Flags & Defaults

| Topic | Legacy Behavior | BNG3 Behavior | Impact | What to Do | Source / Evidence |
| --- | --- | --- | --- | --- | --- |
| Primary BNGL runner binary | `BNG2.pl [options] model.bngl` | `bng_cpp [options] model.bngl` (standalone C++) or `bionetgen execute model.bngl` (Python CLI) | Script invocations calling `BNG2.pl` must be updated | Replace `BNG2.pl model.bngl` with `bng_cpp model.bngl` or `bionetgen execute model.bngl` | `cpp/main.cpp`, `python/bionetgen/cli.py` |
| `BNG2.pl --outdir DIR` | Writes action outputs into `DIR` | `bionetgen run -i model.bngl -o DIR` works in `v3.0.0a1` and `main`; `bng_cpp --outdir DIR` / `--output_dir DIR` added **(post-`v3.0.0a1` `main`)** | `bng_cpp --outdir` is absent in `v3.0.0a1` archives | Use `bionetgen run -i model.bngl -o DIR` on `v3.0.0a1`, or `bng_cpp --outdir DIR` on `main` | `cpp/main.cpp`, PR `#1056` |
| `BNG2.pl --check` | Syntax check only | `bng_cpp --check model.bngl` and `bionetgen check model.bngl` | Unchanged semantics; `bionetgen check` prints block counts | Use either command | `cpp/main.cpp`, `python/bionetgen/cli.py` |
| `BNG2.pl --console` | Interactive BNG console | `bng_cpp --console` / `-i` (supported; cannot combine with `--parallel`) | Preserved in `bng_cpp` | Invoke `bng_cpp --console model.bngl` | `cpp/main.cpp` |
| Parallel multi-model CLI | Not built into `BNG2.pl` | **Addition:** `bng_cpp --parallel JOBS [--parallel-dir DIR] m1.bngl m2.bngl ...` runs models in isolated child processes | Safe concurrent batch runs | Use `--parallel N` on `bng_cpp` | `cpp/main.cpp` |
| `bionetgen` CLI framework | PyBioNetGen used Cement (`bionetgen.main`) with `-i/--input`, `-o/--output` | Click-based CLI (`bionetgen.cli:main`) with 12 subcommands: `run`, `execute`, `check`, `export`, `scan`, `sensitivity`, `visualize`, `atomize`, `plot`, `notebook`, `graphdiff`, `info`, plus global `--version` and `--require/-req` | Positional `bionetgen run MODEL` runs one modern simulation; `-i MODEL` preserves legacy action-runner behavior | Use `bionetgen run -i MODEL -o DIR` for legacy action scripts, or `bionetgen run MODEL -m ode` for single tabular output | `python/bionetgen/cli.py`, `docs/cli_reference.md` |
| PyBioNetGen `--sedml` flag | Commented out in upstream PyBioNetGen before release | Retired (`py.cli.option.sedml` retired per `DECISIONS.md` item 19) | None (not live upstream) | N/A | `docs/DECISIONS.md` item 19 |
| `bionetgen` CLI new subcommands | PyBioNetGen had `run`, `plot`, `info`, `notebook`, `visualize`, `graphdiff`, `atomize` | **Additions:** `check`, `execute`, `export`, `scan`, `sensitivity` | Direct CLI access to syntax checks, multi-format export, 1D scans, and sensitivities | See [CLI Reference](cli_reference.md) | `python/bionetgen/cli.py` |
| `bng_cpp --version` string | `BNG2.pl -v` printed `BioNetGen version 2.9.x` | Prints `bng_cpp version 3.0.0a1` **(post-`v3.0.0a1` `main`)** (`v3.0.0a1` release binaries printed hardcoded `4.0`) | Matches package version on `main` | Use `bionetgen --version` on `v3.0.0a1`, or `bng_cpp --version` on `main` | `cpp/main.cpp`, `CMakeLists.txt` |

---

## 3. BNGL Syntax, Blocks & Language Extensions

| Topic | Legacy Behavior (BNG2) | BNG3 Behavior | Impact | What to Do | Source / Evidence |
| --- | --- | --- | --- | --- | --- |
| Core BNGL blocks (`parameters`, `compartments`, `molecule types`, `seed species`, `observables`, `functions`, `energy patterns`, `population maps`, `reaction rules`, `actions`) | Parsed by Perl `BNGModel.pm` | Parsed by C++17 ANTLR4 grammar (`cpp/parser/BNGParser.g4`) into `ast::Model` and compiled into `CompiledModel` | **Unchanged compatibility** for standard BNGL; strict errors on unresolved symbols or malformed filters | Run `bionetgen check` on existing models | `CAPABILITY_UNION_INVENTORY.md` (`bngl.*`) |
| Expressions, builtins & operators (`mratio`, `_pi`, `_e`, `ln`, `exp`, `min`, `max`, `if`, `TFUN`, etc.) | Perl + `run_network` / `muParser` | Shared C++ expression evaluator; **(post-`v3.0.0a1` `main`)** matches BNG2 `mratio` Lentz continued fraction and `_pi()`/`_e()` calls | **Unchanged compatibility**; strict syntax errors on trailing tokens | No change needed for valid BNGL | `cpp/ast/Expression.cpp`, PR `#1032` |
| Physical units (`begin units`, `[unit]`) | Not in canonical BNG2 | **Addition:** dimensional checking and compartment/count-rate unit conversion | Enables unit-checked BNGL and CRN export | See [docs/BNG3_UNITS.md](BNG3_UNITS.md) | `cpp/units/`, `docs/BNG3_UNITS.md` |
| Nonequilibrium energy (`begin barrier patterns`, `driven_by(W)`) | Not in canonical BNG2 or NFsim | **Addition (experimental, gated off by default):** requires `BNG_NFSIM_GENERAL_ENERGY=1`; refused otherwise | Existing eBNGL models without barriers/work are unchanged | Set `BNG_NFSIM_GENERAL_ENERGY=1` only when intentionally using these extensions | `docs/nonequilibrium_energy.md`, `DECISIONS.md` item 16 |
| Delayed rules (`delay(...)`) | Not in canonical BNG2 | **Addition (bounded):** native ODE method-of-steps, delayed SSA, and BNGIR v0.2 representation | BNGsim and some exporters fail closed on delayed rules | Use native ODE/SSA backend | `provenance/capability-matrix.yml`, `#475` |
| Error reporting on malformed BNGL | Perl warnings or silent fallbacks in some edge cases | Strict `ParseError` / compile diagnostics with source context | Previously silently accepted typos may now error | Fix syntax issues flagged by `bionetgen check` | `cpp/parser/`, `cpp/compile/` |

---

## 4. BNGL Actions, Options & Side Effects

| Topic | Legacy Behavior (BNG2) | BNG3 Behavior | Impact | What to Do | Source / Evidence |
| --- | --- | --- | --- | --- | --- |
| `generate_network`, `simulate`, `simulate_ode`/`ssa`/`pla`/`psa`/`nf`, `setParameter`, `setConcentration`, `addConcentration`, `save*`/`reset*`, `setVolume`, `substanceUnits`, `quit`, `version` | Executed sequentially by `BNG2.pl` / `BNGAction.pm` | Executed in-process by `cpp/actions/ActionDispatch.cpp` | **Unchanged semantics** across the 71-model strict corpus and 231 `action.*` inventory rows | Existing action blocks run via `bng_cpp`, `bionetgen execute`, `bionetgen run -i`, or `model.execute()` | `cpp/actions/ActionDispatch.cpp`, `scripts/validate.py` |
| `prefix` / `suffix` on `write*` and `visualize` actions; `writeMfile_all`, `writeLaTeXfile` | Honored by BNG2 | Fixed across all `write*` and `visualize` actions **(post-`v3.0.0a1` `main`)** | `v3.0.0a1` had partial `prefix`/`suffix` gaps on some writers | Use `main` if your scripts rely on custom `prefix`/`suffix` or `writeMfile_all`/`writeLaTeXfile` | PR `#1050` |
| `bifurcate` continuation & `.scan` files | Carries state across continuation and writes per-observable `.scan` files | Aligned with BNG2 **(post-`v3.0.0a1` `main`)** | `v3.0.0a1` did not carry full `bifurcate` continuation state | Use `main` for `bifurcate` action workflows | PR `#1053` |
| `readModel` refresh, `setModelName`, `print_net`, `simulate_protocol`, `readNFspecies`, `readSBML`, `LPS`, `codename` | Supported in BNG2 | Completed in `ActionDispatch.cpp` **(post-`v3.0.0a1` `main`)** | Missing or incomplete in `v3.0.0a1` | Use `main` if your BNGL action block invokes these actions | PR `#1054` |
| `simulate_nf` with `sample_times` (omitted `t_end`) & `-rnf` | Defaults `t_end` to final `sample_times` entry; passes `-rnf` | `-rnf` wired in `v3.0.0a1` (`#1033`); `sample_times` default `t_end` fixed **(post-`v3.0.0a1` `main`)** | `v3.0.0a1` requires explicit `t_end` alongside `sample_times` in `simulate_nf` | Specify `t_end` explicitly on `v3.0.0a1` or upgrade to `main` | PR `#1033`, PR `#1056` |
| `simulate({method=>"nf"})` / `simulate_nf()` action backend | Invokes external `NFsim` binary | Executes embedded **NFcore** in-process (does not accept `method=>"nfcore"` or `method=>"nfnext"` in BNGL action blocks yet) | Unlike Python `model.simulate(method="nf")` (which uses NFnext), BNGL action blocks still use NFcore | Use Python `model.simulate(method="nf")` for NFnext; see [network_free_simulation.md](network_free_simulation.md) | `cpp/actions/ActionDispatch.cpp`, `docs/CURRENT_PROGRESS.md` |
| `setConcentration` in non-unit compartments | Updates species concentration (amount = concentration × volume) | Aligned with BNG2 and SBML concentration semantics | **Unchanged compatibility** | No change needed | `docs/SBML_CONFORMANCE_FINDINGS.md` |
| Kinetics exporters (`writeSBML`, `writeMfile`, `writeLatex`, `writeCppfile`, `writeMEXfile`, `writeSSC`, `writeMDL`) on energy models | BNG2 could emit literal `Arrhenius(...)` or drop energy terms | **Fail-closed:** rejected via `io::requireNoEnergySemantics()` unless model uses `.net`, BNGL, or BNG-XML | Prevents silent semantic loss | Export energy models to `.net`, BNGL, or BNG-XML only | `CHANGELOG.md`, `cpp/io/` |

---

## 5. Network Generation & Graph Identity

| Topic | Legacy Behavior (BNG2) | BNG3 Behavior | Impact | What to Do | Source / Evidence |
| --- | --- | --- | --- | --- | --- |
| Canonicalization & graph isomorphism | Perl `SpeciesGraph.pm` + BNG2 nauty | Shared C++ `bng_core` + single bundled `nauty` (shared by network generation and NFsim) | Species ordering/numbering in `.net` may differ from BNG2, while the generated graph-isomorphic species set, reactions, and statistical factors match | Compare networks graph-isomorphically (as `tests/validation/compare.py` does), not by raw line-by-line `diff` | `cpp/nauty/README.md`, `tests/validation/README.md` |
| `max_iter` default in Python | N/A (`generate_network` action defaults in BNG2) | `model.generate_network(max_iter=None)` reads `max_iter` from any `generate_network` action in the model, else defaults to C++ `max_iter=100` | Matches authored `generate_network({max_iter=>N})` when present | Pass explicit `max_iter=...` when overriding | `python/bionetgen/model.py:1057` |
| Rule execution & `ReactionRule` mutability | Perl stored state on rule objects | `ReactionRule` stores compiled metadata only; `NetworkGenerator` allocates per-run `ExecutionState` | Supports compile-once reuse and isolated parallel scans/ensembles | Safe to reuse loaded `BioNetGenModel` across scans | `docs/architecture.md` |

---

## 6. Finite-Network Solvers, Tolerances & Defaults

| Topic | Legacy Behavior (BNG2 / `run_network`) | BNG3 Behavior | Impact | What to Do | Source / Evidence |
| --- | --- | --- | --- | --- | --- |
| Default ODE solver | `run_network` SUNDIALS CVODE | In-process SUNDIALS 7.6.0 CVODE (`method="ode"`) | Same solver family; default Python tolerances are `rtol=1e-8`, `atol=1e-12`, `t_start=0.0`, `t_end=100.0`, `n_steps=100` | Pass explicit `rtol`, `atol`, `max_step`, `sparse=True` if matching custom BNG2 defaults (note BNG2 `simulate_ode` defaults to `atol=1e-8`, `rtol=1e-8`) | `python/bionetgen/model.py:1237` |
| Default `atol` difference | BNG2 `simulate_ode` default `atol` is `1e-8` | Python `model.simulate()` and `bionetgen run` default `atol` is `1e-12` (stricter) | Tighter numerical accuracy in Python/CLI by default | Pass `atol=1e-8` if reproducing BNG2's exact default tolerance | `python/bionetgen/model.py:1244`, `python/bionetgen/cli.py:182` |
| SSA / PLA / PSA | External `run_network` binary | In-process C++ Gillespie SSA, PLA, and PSA (`method="ssa"\|"pla"\|"psa"`) | **Unchanged model semantics**; PLA accepts `pla_config`, PSA accepts `psa_poplevel` (default `100.0`) | Note `seed` is forwarded to `ssa`/`nf`/`ode` (random SBML events), not to `pla`/`psa` in Python `model.simulate()` | `python/bionetgen/model.py:1784-1816` |
| Continuation (`continue=>1`) | Preserved state across sequential `simulate` actions in one `BNG2.pl` run | Preserved in BNGL action blocks AND available in Python via `model.simulate(..., continue_simulation=True)` and `model.reset_simulation()` | Changing a parameter with `set_parameter()` between continued stages updates rates while keeping live state | Pass `continue_simulation=True` for staged Python protocols; call `reset_simulation()` to restart cleanly | `python/bionetgen/model.py:364,1281` |
| Batched direct SSA (CPU / GPU) | Not in BNG2 | **Addition:** `model.simulate_batch_ssa(...)` and `model.simulate(method="ssa", batch_size=N)` on multi-core CPU, Apple Metal, or NVIDIA CUDA | Orders-of-magnitude speedup for large fixed-network mass-action ensembles; fails closed on functional/`TotalRate` models | Inspect `bionetgen.gpu_backend_capabilities()` before requesting GPU | `docs/GPU_BATCH_SSA_EVALUATION.md`, `python/bionetgen/model.py:1143` |
| Optional BNGsim & JAX backends | PyBioNetGen had Python `simulator="bngsim"` bridge; no JAX | Native solvers are default; `backend="bngsim"` requires `-DBUILD_BNGSIM_ADAPTER=ON`; `bionetgen[jax]` provides separate `jax_ode`/`jax_ssa` modules | Unsupported models fail closed with explicit blockers | See [ADR 0003](adr/0003-bngsim-canonical-finite-backend.md) and [bngsim-migration-status.md](bngsim-migration-status.md) | `python/bionetgen/model.py:1573`, `docs/DECISIONS.md` |

---

## 7. Random Seeds & Reproducibility

| Topic | Legacy Behavior | BNG3 Behavior | Impact | What to Do | Source / Evidence |
| --- | --- | --- | --- | --- | --- |
| `seed=0` (default) | System/clock-seeded (non-reproducible) | **`seed=0` draws from `std::random_device` (non-reproducible)**—kept intentionally for BNG2 compatibility | Two runs with `seed=0` will differ | Always pass an explicit nonzero integer `seed` for reproducible SSA/NF runs | `docs/user_guide.md#seeds-and-reproducibility` |
| Nonzero `seed` within one engine | Reproducible for fixed seed | Reproducible for fixed nonzero `seed` in native SSA, NFcore, and NFnext | Same model + same engine + same nonzero seed → identical trajectory | Record engine name (`result.backend`), BNG3 version/SHA, and `seed` | `docs/user_guide.md` |
| Batched SSA seeding (`base_seed`) | N/A | Trajectory `b` derives its seed deterministically from `(base_seed, b)` via SplitMix64 (CPU) or disjoint PCG32 streams (GPU) | Independent of CPU worker thread count; GPU and CPU use different PRNGs so cross-device parity is **statistical**, not pathwise | Validate GPU vs. CPU batches with mean/variance/KS/chi-square tests | `cpp/engine/BatchSsa.hpp`, `docs/GPU_BATCH_SSA_EVALUATION.md` |
| Cross-engine stochastic parity (BNG3 vs. BNG2 / NFsim) | Single-engine runs | Same seed is **pathwise** only when construction and draw order match (e.g., direct NFcore vs. aligned native NFsim); **statistical** (ensemble distribution) for NFnext vs. NFsim or GPU vs. CPU; **invariant-only** for conservation/support checks | Do not expect identical single trajectories when switching from NFsim/NFcore to NFnext | Compare ensembles over fixed nonzero seed ranges | `AGENTS.md`, `docs/network_free_simulation.md` |

---

## 8. Outputs, File Naming & Working-Directory Behavior

| Topic | Legacy Behavior | BNG3 Behavior | Impact | What to Do | Source / Evidence |
| --- | --- | --- | --- | --- | --- |
| Python simulation return value | PyBioNetGen `bionetgen.run(path)` wrote `.net`/`.gdat`/`.cdat` into cwd (or `out=`) and returned `BNGResult` | `model.simulate()` and `bionetgen.run(path)` (no `out=`) run in memory, write **no files**, and return `SimResult` (`result.time`, `result.observables`, `result.concentrations`, `result.backend`) | Scripts parsing `.gdat` from cwd after `bionetgen.run(path)` will see no files unless updated | Pass `out="dir"` (or `out=None`) to keep the file-runner `BNGResult` contract, or migrate to `SimResult` | `python/bionetgen/__init__.py:74` |
| CLI `bionetgen run MODEL` output | PyBioNetGen `bionetgen run -i MODEL -o DIR` wrote BNG2 files in `DIR` | Positional `bionetgen run MODEL [-o FILE]` writes a single tab-separated `.tsv` file (or prints summary); `bionetgen run -i MODEL [-o DIR]` executes actions into `DIR` | Different output format between positional and `-i` forms | Use `-i MODEL -o DIR` when expecting `.gdat`/`.cdat`/`.net` files | `python/bionetgen/cli.py:140-224` |
| Working-directory side effects | `BNG2.pl` wrote files to cwd unless `--outdir` was given | `bionetgen.load()` and `model.simulate()` do not write to cwd; `model.execute()` / `bionetgen execute` / `bng_cpp` write action outputs relative to cwd (or `--outdir` on `main`) | Safer in-memory workflows; explicit file creation when executing actions | Use `bionetgen run -i MODEL -o DIR` or `bng_cpp --outdir DIR` (`main`) to isolate action outputs | `cpp/actions/ActionDispatch.cpp`, `python/bionetgen/cli.py` |
| `n_steps` vs. `n_points` | BNG2 actions use `n_steps` (producing `n_steps + 1` rows); PyBioNetGen `run(..., n_points=N)` uses `N` points | In `bionetgen.run(..., out=..., n_points=N)`, `N` points means `N - 1` steps plus endpoints; in `modelapi.runner.run`, `n_points` retains the pinned `n_points + 1` convention | Off-by-one trap if mixing `n_steps` and `n_points` | Prefer `n_steps` on `model.simulate()` and `bionetgen.run()` | `docs/migration_guide.md`, `python/bionetgen/compat/runner.py` |

---

## 9. Python API, Return Objects, Exceptions & Replaced/Retained Modules

| Topic | Legacy Behavior (PyBioNetGen `28bf351a`) | BNG3 Behavior | Impact | What to Do | Source / Evidence |
| --- | --- | --- | --- | --- | --- |
| Loading models | `bionetgen.bngmodel(path)` (parses via BNG2 XML or BNGL) | Recommended: `bionetgen.load(path) -> BioNetGenModel` (C++ AST). Legacy `bionetgen.bngmodel` remains lazily exported for compatibility | `BioNetGenModel` exposes typed C++ objects (`parameters`, `molecule_types`, `seed_species`, `observables`, `reaction_rules`, `functions`, `compartments`, `actions`) | Migrate to `bionetgen.load()`; keep `bngmodel` only for transition scripts | `python/bionetgen/__init__.py`, `python/bionetgen/model.py` |
| Programmatic model construction & editing | Direct manipulation of `bngmodel` block objects | **Additions:** `bionetgen.ModelBuilder` AND atomic runtime topology edits on `BioNetGenModel` (`add_parameter`, `remove_parameter`, `add_compartment`, `remove_compartment`, `add_molecule_type`, `remove_molecule_type`, `add_seed_species`, `remove_seed_species`, `set_seed_species_amount`, `move_species_to_compartment`, `add_observable`, `remove_observable`, `add_reaction_rule`, `remove_reaction_rule`, `add_function`, `remove_function`) | Re-parses and validates atomically; discards stale network cache while keeping `set_parameter()` overrides | Prefer `ModelBuilder` or `BioNetGenModel` edit methods over `bngmodel` internals | `python/bionetgen/model.py:446-1055`, `python/bionetgen/builder.py` |
| CRN & BNGIR APIs | Not in PyBioNetGen | **Additions:** `model.species`, `model.complexes`, `model.reactions`, `model.stoichiometric_matrix`, `model.to_crn()`, `model.write_crn()`, plus `to_bngir()`, `from_bngir()`, `semantic_equal()`, `EqualityUndecided` | Machine-readable CRN and lossless JSON IR v0.2 | See [API Reference](api_reference.md) | `python/bionetgen/model.py`, `python/bionetgen/bngir.py` |
| `model.actions` structure | Parsed dict/list on `bngmodel` | Structured list of C++ action objects (`action.name`, `action.arguments`) | Scripts indexing `model.actions` as a dict will fail | Read `.name` and `.arguments` on each action object | `python/bionetgen/model.py` |
| Exceptions | `BNGError`, `BNGFormatError`, `BNGSimError`, `BNGVersionError` | All retained in `bionetgen.core.exc`; plus `_bionetgen_cpp.ParseError` (syntax errors), `bionetgen.BioNetGenError` (SBML import errors), `bionetgen.EqualityUndecided` (BNGIR), and standard `ValueError`/`TypeError`/`RuntimeError`/`NotImplementedError`/`subprocess.TimeoutExpired` | Clearer, fail-closed error hierarchy | Catch `BioNetGenError` for SBML and `ValueError`/`RuntimeError` for invalid options or unsupported backends | `python/bionetgen/__init__.py`, `python/bionetgen/core/exc.py` |
| `bionetgen.network.network.Network` | Pure-Python `.net` reader/writer | Retained for `.net` inspection/editing | **Unchanged import path** | Works on `.net` files exported by `model.write_net()` or `bionetgen export -f net` | `python/bionetgen/network/network.py` |
| `bionetgen.sim_getter` & `CSimulator` | `sim_getter(..., sim_type="libRR"\|"cpy")`, `CSimulator` compile-to-C | Retained; `libRR` requires separately installed `libroadrunner`; `CSimulator` requires C compiler + legacy toolchain | Optional compatibility only | Prefer `model.simulate(method="ode")` for native C++ CVODE | `python/bionetgen/simulator/` |
| `bionetgen.core.tools.bngsim_*` | PyBioNetGen Python helper-process BNGsim bridge | Aligned signatures **(post-`v3.0.0a1` `main`, PR `#1051`)**; file-runner still rejects `simulator="bngsim"` | Do not confuse Python `bngsim` bridge with BNG3 native `backend="bngsim"` | Use `model.simulate(..., backend="bngsim")` in a BNGsim-enabled build | `docs/migration_guide.md`, PR `#1051` |
| PySB adapter | Not part of core PyBioNetGen | Not exposed in BNG3 | None unless relying on external wrappers | Export BNGL/SBML as needed | `docs/migration_guide.md` |

---

## 10. Network-Free Execution (NFsim & NFnext)

See the full **[Network-Free Simulation Guide](network_free_simulation.md)** for the engine decision table and roadmap.

| Topic | Legacy Behavior (BNG2 + NFsim) | BNG3 Behavior | Impact | What to Do | Source / Evidence |
| --- | --- | --- | --- | --- | --- |
| Python `model.simulate(method="nf")` | Wrote BNG-XML and launched external `NFsim` subprocess | Routes to **NFnext** (`result.backend == "nfnext"`) compiled directly from `CompiledModel → NFIR` (no XML) | Faster, in-process, zero XML overhead; rejects NFcore-only `equilibrate` and `traversal_limit` options | Use `method="nf"` by default; pass `method="nfcore"` when needing `equilibrate`, `traversal_limit`, or NFcore parity | `python/bionetgen/model.py:1350,1520`, `DECISIONS.md` item 4 |
| BNGL action `simulate_nf` / `simulate({method=>"nf"})` | Launched external `NFsim` via XML | Runs embedded **NFcore** directly from AST/CompiledModel (`construction_path="direct"`); XML fallback is opt-in (`BNG_NFSIM_ALLOW_XML_FALLBACK=1`) | Preserves NFcore options (`utl`, `equilibrate`, `rnf`); fails closed instead of silently falling back to XML | Set `BNG_NFSIM_ALLOW_XML_FALLBACK=1` only if debugging legacy XML fallback | `cpp/actions/ActionDispatch.cpp`, `docs/architecture.md` |
| Standalone `NFsim` CLI | `RuleWorld/NFsim` binary | Shipped in BNG3 CLI archives; **(post-`v3.0.0a1` `main`)** adds `-i` initial simulation time flag and upstream `v2.0.1` + `#160` sync | Drop-in CLI compatibility for `-xml` and `-rnf` workflows | Use `-i` on `main` builds when starting at nonzero `t_start` | `cpp/nfsim/NFsim.cpp`, PR `#1047`, PR `#1052` |
| `TotalRate` on local functions / `FunctionProduct` / `MM` / `Arrhenius` | Rejected by upstream NFsim (`afad408606`) | Rejected in BNG3 NFsim (`#1028`, included in `v3.0.0a1`) | Matches upstream NFsim semantics | Remove `TotalRate` from those rate-law forms | PR `#1028` |
| NFnext GPU (`simulate_nfnext_gpu`) | Not in NFsim | **Addition (bounded, fail-closed):** unary state-change mode in `v3.0.0a1`; `mode="graph"` for `TIER_NF` on Metal & CUDA **(post-`v3.0.0a1` `main`)** | No silent CPU fallback; explicit diagnostics on unsupported constructs | Check `bionetgen.gpu_backend_capabilities()` | `python/bionetgen/model.py:1077`, PR `#1040` |

---

## 11. SBML Import/Export & Atomizer

| Topic | Legacy Behavior (BNG2 / PyBioNetGen) | BNG3 Behavior | Impact | What to Do | Source / Evidence |
| --- | --- | --- | --- | --- | --- |
| SBML import engine | PyBioNetGen legacy Atomizer (`sbmlTranslator.py`) | Modern Python Atomizer is the default for `bionetgen.from_sbml()`, `sbml_to_bngl()`, and `bionetgen atomize`; legacy-specific flags (`--convention-file`, `--naming-conventions`, `--user-structures`, `--obs-map-file`, `--bionetgen-analysis`, `--isomorphism-check`, `--log-level`) automatically select `atomizer_backend="legacy"` | Much broader SBML L3 Core, `comp`, events, rules, and Multi support; explicit refusals instead of silent approximations | Install `bionetgen[full]`; see [ATOMIZER_LIMITATIONS.md](ATOMIZER_LIMITATIONS.md) for the exact refusal taxonomy | `python/bionetgen/cli.py:550-562`, `docs/capabilities.md` |
| Unsupported SBML packages (`fbc`, `qual`, `spatial`) | Legacy Atomizer could produce invalid or misleading BNGL | **Fail-closed:** explicitly refused with diagnostics naming the package (`DECISIONS.md` item 12) | Prevents invalid kinetic models from constraint/logical/spatial SBML | Use a domain-specific solver for FBC/qual/spatial models | `docs/DECISIONS.md` item 12, `docs/ATOMIZER_LIMITATIONS.md` |
| SBML export | `writeSBML()` / `writeSBMLMulti()` actions | Available as both BNGL actions and Python/CLI methods (`model.write_sbml()`, `model.sbml_multi()`, `bionetgen export -f sbml`) | Direct Python and CLI access without editing action blocks | Fails closed on energy/barrier/driven models | `python/bionetgen/model.py:1876`, `python/bionetgen/cli.py:260` |

---

## 12. Optional Legacy Perl Mode & Platform Differences

| Topic | Legacy Behavior | BNG3 Behavior | Impact | What to Do | Source / Evidence |
| --- | --- | --- | --- | --- | --- |
| `BIONETGEN_USE_PERL=1` | Default in PyBioNetGen | Opt-in transition aid: routes Python `bionetgen.run(path)` and `bionetgen.load(path).execute()` to Perl BNG2 (located via `BNGPATH`). `bionetgen run MODEL` CLI is unavailable in this mode | Lets labs compare or bridge legacy scripts temporarily | Unset `BIONETGEN_USE_PERL` once validated on native BNG3 | `python/bionetgen/__init__.py:10`, `docs/cli_reference.md` |
| Supported platforms & wheels | BNG2 shipped platform Perl/binary bundles; Windows often relied on Cygwin/Strawberry Perl | Native C++17 wheels for CPython 3.9–3.14 on Linux x86_64 (`manylinux_2_28`, glibc >= 2.28), macOS arm64 (11.0+), macOS x86_64 (11.0+), and Windows `win_amd64` (native MSVC, no Cygwin); standalone CLI archives for the same 4 targets | Native Windows execution without Perl or Cygwin; Linux aarch64 and musllinux require building from source | Check platform table in [README.md#installation](../README.md#installation) | `.github/workflows/release.yml`, `v3.0.0a1` assets |
| GPU platform availability | None | Apple Metal on macOS arm64; NVIDIA CUDA only when built with CUDA toolkit on a CUDA-capable host | Metal and CUDA have separate device qualification; neither qualifies the other | Query `bionetgen.gpu_backend_capabilities()` at runtime | `docs/DECISIONS.md` item 17, `python/bionetgen/__init__.py:29` |
