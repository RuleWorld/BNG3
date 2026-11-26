# Migration Guide: Moving from BNG2 or PyBioNetGen to BNG3

BioNetGen 3 (BNG3) replaces the separate Perl BNG2, standalone NFsim, and PyBioNetGen wrapper workflows with one in-process C++17 engine and Python interface. This guide is task-oriented and treats **BNG2 (`BNG2.pl` / BNGL action files)** and **PyBioNetGen (`bionetgen<3`)** as two distinct migration paths.

For the complete, searchable family-by-family table of every user-visible change (executables, CLI flags, BNGL syntax, actions, solvers, seeds, outputs, Python objects, NFsim, SBML, and platforms), see the **[Detailed BNG2 & PyBioNetGen Change Reference](bng2_migration_reference.md)**. For support boundaries, see the [Capability Guide](capabilities.md); for network-free engine selection, see [Network-Free Simulation (NFsim & NFnext)](network_free_simulation.md).

## Comparison Scope & Pinned Versions

| Software | `v3.0.0a1` pre-release (`8482215c`) | Source `main` (`90832910`) |
| --- | --- | --- |
| **BNG2 (`RuleWorld/bionetgen`)** | `9601746f8884ed19ab2acea49fe87fc4660ace46` | `740006ff3cfa0b6d5445e10367c9f2fcd0f75d67` (BioNetGen 2.9.5) |
| **NFsim (`RuleWorld/NFsim`)** | `8c449bbccc4a0c54586ae562f46f4955e65fe876` | `d45b7d99cf1905199911a3187edbba585fad56ba` (NFsim v2.0.1 + `#160`) |
| **PyBioNetGen (`RuleWorld/PyBioNetGen`)** | `28bf351a9bbfc197e19487c26dedda683716bb64` (v0.8.7 lineage) | `28bf351a9bbfc197e19487c26dedda683716bb64` (v0.8.7 lineage) |

All pins are recorded in [`provenance/upstreams.lock.yml`](../provenance/upstreams.lock.yml), release scope in [CAPABILITY_UNION_INVENTORY.md](CAPABILITY_UNION_INVENTORY.md), policy in [DECISIONS.md](DECISIONS.md), and live qualification evidence in [CURRENT_PROGRESS.md](CURRENT_PROGRESS.md). Changes landed on `main` after `v3.0.0a1` are labeled **(post-`v3.0.0a1` `main`)**.

---

## Install And Choose A Backend

BNG3 and PyBioNetGen share the Python distribution name `bionetgen`:

- **Stay on PyBioNetGen in an existing environment:** pin `pip install "bionetgen<3"`. Today on PyPI, `pip install bionetgen` still resolves to legacy PyBioNetGen `0.8.7` because `v3.0.0a1` is currently distributed via GitHub Releases rather than PyPI.
- **Install BNG3 `v3.0.0a1` in a separate environment:** install the matching pre-built wheel from [GitHub Releases (`v3.0.0a1`)](https://github.com/RuleWorld/BNG3/releases/tag/v3.0.0a1), download the standalone CLI archive (`bng_cpp` + `NFsim`), or run `python -m pip install .` from a BNG3 checkout. See [README.md#installation](../README.md#installation) for exact platform wheel URLs.
- **Verify which package is active:** run `bionetgen --version` (`3.0.0a1` for BNG3 vs. `0.8.x` for PyBioNetGen).

| Backend | Selection and qualification |
| --- | --- |
| Native finite-network | The default for `ode`, `ssa`, `pla`, and `psa`. |
| NFnext | The default for `method="nf"` (promoted in #832 after the full pinned-native NFsim and NFcore corpus parity passed; see [#149](https://github.com/RuleWorld/BNG3/issues/149) and `docs/DECISIONS.md` item 4). `method="nfnext"` remains explicitly selectable. |
| NFcore | Still selectable explicitly with `method="nfcore"` through the common backend interface. |
| BNGsim | Optional finite-network backend selected with `backend="bngsim"` in a build that includes the adapter (`-DBUILD_BNGSIM_ADAPTER=ON`). See [ADR 0003](adr/0003-bngsim-canonical-finite-backend.md). |
| JAX CPU | The `jax` extra installs the dependencies for the separate [JAX ODE](../python/bionetgen/jax_ode.py) and [JAX SSA](../python/bionetgen/jax_ssa.py). See [#473](https://github.com/RuleWorld/BNG3/issues/473) for the qualified surface. |
| Metal and CUDA | Actual device qualification is tracked separately in [#474](https://github.com/RuleWorld/BNG3/issues/474) (`backend.gpu`; Metal and CUDA qualified separately for finite batch SSA and bounded NFnext GPU). |

The method names in this table apply to Python's `model.simulate()`. In native BNGL action files (`model.execute()`, `bionetgen execute`, `bng_cpp`), `simulate({method=>"nf"})` and `simulate_nf()` currently execute NFcore. See [Network-Free Simulation (NFsim & NFnext)](network_free_simulation.md).

Install the `plotting` extra for `to_dataframe()` and plotting, `notebook` for a notebook kernel, `jax` for JAX CPU solvers, `legacy` for legacy Cement/pyparsing/pylru modules, and `full` for SBML (`python-libsbml`) and SymPy integrations.

---

## Two Migration Tracks at a Glance

### Track A: Migrating from BNG2 (`BNG2.pl` and BNGL Action Files)

Most `.bngl` model files parse and run without modification. The main changes are executable names, default execution style, and explicit diagnostics:

| BNG2 (`BNG2.pl`) | BNG3 Equivalent | Key Difference |
| --- | --- | --- |
| `BNG2.pl model.bngl` | `bng_cpp model.bngl` or `bionetgen execute model.bngl` | In-process C++17 parser, network generator, and solvers; no Perl required. |
| `BNG2.pl --outdir out model.bngl` | `bng_cpp --outdir out model.bngl` **(post-`v3.0.0a1` `main`)** or `bionetgen run -i model.bngl -o out` | `bionetgen run -i ... -o out` works in both `v3.0.0a1` and `main`; `bng_cpp --outdir` was added after `v3.0.0a1`. |
| `BNG2.pl --check model.bngl` | `bng_cpp --check model.bngl` or `bionetgen check model.bngl` | Parses and validates syntax/blocks without running actions. |
| `BNG2.pl --xml model.bngl` | `bionetgen export model.bngl -f xml -o model.xml` | Explicit format and output path. |
| `NFsim -xml model.xml -sim 10 -oSteps 20` | `NFsim -xml model.xml -sim 10 -oSteps 20` (bundled CLI archive) or `model.simulate(method="nf", t_end=10, n_steps=20)` | Bundled `NFsim` binary retains classic flags; Python `method="nf"` runs NFnext directly from `CompiledModel` without XML. |
| Action-driven parameter scans (`parameter_scan`, `bifurcate`) | Still run via `bng_cpp` / `bionetgen execute`, or use `model.parameter_scan(...)` / `bionetgen scan` | Python/CLI scans return structured arrays/CSVs directly without manual `.scan` file parsing. |

### Track B: Migrating from PyBioNetGen (`bionetgen<3`)

| Task | PyBioNetGen (`0.8.x`) | BioNetGen 3 (`3.x`) |
| --- | --- | --- |
| Load model | `bng = bionetgen.bngmodel("m.bngl")` | `model = bionetgen.load("m.bngl")` |
| Simulate (in-memory) | `res = bionetgen.run("m.bngl")` (wrote files, returned `BNGResult`) | `result = model.simulate(method="ode")` or `bionetgen.run("m.bngl")` (returns `SimResult`) |
| Run declared BNGL actions to disk | `res = bionetgen.run("m.bngl", out="results")` | `files = bionetgen.run("m.bngl", out="results")` (returns `BNGResult`) |
| Read observables | `res[0]["AB"]` / parse `.gdat` | `result.observables["AB"]` (NumPy array) |
| Parameter scan | Loop over `bionetgen.run()` calls | `model.parameter_scan(...)` / `model.parameter_scan_2d(...)` |
| Sensitivity analysis | Manual finite differences | `model.sensitivity_analysis(...)` |
| NFsim | External NFsim binary via subprocess | `model.simulate(method="nf")` (NFnext) or `method="nfcore"` |
| Access parameters | XML-parsed dicts on `bngmodel` | `model.parameters` list of typed objects (`get_parameter` / `set_parameter`) |
| Edit model topology | Mutate `bngmodel` blocks | `model.add_parameter`, `add_reaction_rule`, `set_seed_species_amount`, etc., or `ModelBuilder` |
| Export SBML | `writeSBML()` action | `model.write_sbml("out.xml")` / `bionetgen export` |
| Import SBML | `bionetgen atomize` CLI | `bionetgen.from_sbml("model.xml", atomize=True)` or `bionetgen atomize` |

---

## Python and CLI Run Contracts

`bionetgen.run()` supports two explicit call styles. With no output argument specified, it uses the modern in-memory API and returns a `SimResult`; its default method is ODE with `t_end=100` and `n_steps=100`. The modern method and grid can also be positional: `bionetgen.run("model.bngl", "ssa", 20, 200)`. The dispatcher uses `*args` plus keyword-only `method`, `t_end`, and `n_steps` so it can preserve legacy positional output-directory calls. An explicit `None`, a path-like second positional argument, or a string that is not one of `ode`, `ssa`, `nf`, `pla`, or `psa`, selects the file runner and returns `BNGResult`; use `out=` when a directory's string name could be mistaken for a method. After a positional output path, remaining positionals retain the PyBioNetGen order: `suppress`, `timeout`, `simulator`, `format`, `method`, `t_span`, and `n_points`. Invalid keyword methods raise `ValueError`, and duplicate positional/keyword values raise `TypeError`.

```python
# Modern single-simulation result, defaulting to ODE, 0..100, 100 steps.
result = bionetgen.run("model.bngl")

# Legacy action workflow and its .xml, .net, .gdat and .cdat outputs.
files = bionetgen.run("model.bngl", out="results")
```

The compatibility file runner supports `simulator="auto"`, `"native"`, and `"subprocess"`. A non-`None` `timeout`, or an explicit subprocess selection, runs the same native parser and executor in a separate process; expiry raises `subprocess.TimeoutExpired`. `timeout=None` with the default simulator keeps direct in-process execution.

In the file runner, an explicit `method=` selects one modern simulation and writes one `.gdat` result. Time-only options preserve the model's declared actions, ordering, and non-simulation side effects: `t_start`/`t_end` and step count apply to each direct simulation action (`t_span=(start, end)` sets both times, and `n_points=N` means `N-1` steps plus both endpoints). Combining a time override with an action's `sample_times` or truthy `continue` option raises `NotImplementedError` before the output directory is created. Solver-specific options (`rtol`, `atol`, `seed`, `pla_config`, `psa_poplevel`) require an explicit modern `method=` override; action-preserving calls reject them rather than dropping them.

The CLI keeps the same distinction:

- `bionetgen run MODEL --method ssa ...` writes a tab-separated table for one selected simulation.
- `bionetgen run --input MODEL -o DIR` executes the model's declared actions into an output directory (`DIR`); explicit time options modify the action grid while preserving actions. Supplying `--method` with `--input` opts into a single modern simulation.
- `--log`, `--timeout`, and `--no-bngsim` are supported on both positional `MODEL` and `--input` workflows using the bounded native worker (`--format bngl` is accepted; other formats require conversion first).

The maintained integration surface also includes `from_sbml` and `sbml_to_bngl` (requires `python-libsbml`), optional SymPy ODE export (`sympy`), and the legacy `sim_getter(..., sim_type="libRR")` adapter (`python -m pip install libroadrunner`; import module `roadrunner`). The file runner rejects `simulator="bngsim"` (use `model.simulate(..., backend="bngsim")` instead). BNG3 does not expose a PySB adapter.

---

## Tested Workflow Migration Recipes

### Recipe 1: Migrating a BNG2 Action-File Workflow (`BNG2.pl` → BNG3)

Suppose your lab currently runs an action-bearing `.bngl` file (`decay_actions.bngl`):

```bngl
begin model
begin parameters
  k 0.1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules A_total A()
end observables
begin reaction rules
  decay: A() -> 0 k
end reaction rules
end model

begin actions
  generate_network({overwrite=>1})
  simulate({method=>"ode",t_end=>2,n_steps=>10})
end actions
```

**Before (BNG2):**

```bash
BNG2.pl --outdir bng2_out decay_actions.bngl
# Inspect bng2_out/decay_actions.net and bng2_out/decay_actions.gdat
```

**After (BNG3 — preserve `.net`/`.gdat`/`.cdat` files):**

```bash
# Works in v3.0.0a1 and main:
bionetgen run --input decay_actions.bngl --output bng3_out

# Or with standalone C++ binary (no Python needed; --outdir added post-v3.0.0a1 on main):
bng_cpp --outdir bng3_out decay_actions.bngl
```

**After (BNG3 — modern Python API, no intermediate files):**

```python
import bionetgen

model = bionetgen.load("decay_actions.bngl")
result = model.simulate(method="ode", t_end=2.0, n_steps=10)
print(result.time[-1], result.observables["A_total"][-1])
# Analytic law: 100 * exp(-0.1 * 2) = 81.87307531
```

### Recipe 2: Migrating a PyBioNetGen File-Output Script (`BNGResult` → `SimResult`)

**Before (PyBioNetGen `0.8.x` — relies on `bionetgen.run()` returning `BNGResult` and writing `.gdat`):**

```python
import bionetgen

res = bionetgen.run("decay_actions.bngl", out="pybng_out")
gdat = res[0]  # numpy structured array loaded from decay_actions.gdat
print(gdat["time"][-1], gdat["A_total"][-1])
```

**After (BNG3 — minimal-diff transition keeping `BNGResult` and `.gdat` files):**

```python
import bionetgen

# Pass out= (or a positional directory) to keep the BNGResult file-runner contract:
res = bionetgen.run("decay_actions.bngl", out="bng3_out")
gdat = res[0]  # also accessible via res.gdats["decay_actions"]
print(gdat["time"][-1], gdat["A_total"][-1])
```

**After (BNG3 — recommended in-memory `SimResult` API):**

```python
import bionetgen

result = bionetgen.run("decay_actions.bngl", method="ode", t_end=2.0, n_steps=10)
print(result.time[-1], result.observables["A_total"][-1])
```

### Recipe 3: Migrating a Network-Free Workflow & Understanding Seed Comparisons

**Before (BNG2 + standalone NFsim):**

```bash
BNG2.pl --xml model.bngl
NFsim -xml model.xml -sim 2.0 -oSteps 10 -seed 172 -o model_nf.gdat
```

**After (BNG3 — Python API, NFnext default vs. explicit NFcore):**

```python
import bionetgen

model = bionetgen.load("model.bngl")

# Default Python network-free engine: NFnext (compiled directly from CompiledModel, no XML)
res_nfnext = model.simulate(method="nf", t_end=2.0, n_steps=10, seed=172)
print(res_nfnext.backend, res_nfnext.observables["A_total"][-1])  # backend == "nfnext"

# Explicit embedded NFcore (supports NFsim-specific equilibrate and traversal_limit / -utl)
res_nfcore = model.simulate(method="nfcore", t_end=2.0, n_steps=10, seed=172, traversal_limit=3)
print(res_nfcore.backend, res_nfcore.observables["A_total"][-1])  # backend == "nfsim"
```

**How to compare stochastic outputs across engines:**

- **Same engine, same nonzero seed:** Pathwise identical (`res1 == res2`). Never use `seed=0` for reproducibility—`seed=0` draws from `std::random_device` in both BNG2/NFsim and BNG3.
- **Direct NFcore (`method="nfcore"`) vs. pinned standalone `NFsim`:** Pathwise comparison with the same seed is valid only when model construction and reaction-channel draw ordering match (for example, single-channel or aligned direct/XML models).
- **NFnext (`method="nf"`) vs. NFcore or standalone `NFsim`:** NFnext uses its own compiled NFIR rule representation and RNG stream ordering, so identical seeds do **not** produce identical sample paths. Validate agreement **statistically** over an ensemble of independent nonzero seeds (comparing observable means, confidence bands, and empirical CDFs/KS or chi-square tests) alongside exact conservation/stoichiometric **invariants**.

---

## Before And After (Verified Installed-Wheel Snippets)

Save the BNGL in [Parameter Scans](#parameter-scans) as `model.bngl` and run these examples from its directory. Every snippet in this section is executed verbatim by `tests/python/test_migration_guide_installed_example.py` against the installed wheel.

### Load A Model

```python
# Old
from bionetgen import bngmodel
model = bngmodel("model.bngl")

# New
import bionetgen
model = bionetgen.load("model.bngl")
```

### Run A Simulation

```python
# Old
from bionetgen import run
run("model.bngl")

# New
import bionetgen
result = bionetgen.load("model.bngl").simulate(method="ode", t_end=2.0)
```

### Inspect Results

```python
import bionetgen

model = bionetgen.load("model.bngl")
result = model.simulate(method="ode", t_end=2.0)

print(result.time)
print(result.observables["A_total"])
print(result.to_dataframe().head())
```

### Parameter Scans

Save this one-species decay model as `model.bngl`:

```bngl
begin model
begin parameters
  k 0.1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules A_total A()
end observables
begin reaction rules
  decay: A() -> 0 k
end reaction rules
end model
```

The mass-action law for `A() -> 0` is `A(t) = A0 * exp(-k * t)`. With `A0 = 100` and `t_end = 2.0`, the requested rates `0.1` and `1.0` give the endpoints `100 * exp(-0.2) ≈ 81.873075` and `100 * exp(-2) ≈ 13.533528`. `ScanResult.parameter_values` records the rate used by each simulation in request order, `parameter_name` names the scanned parameter, and `final()` returns one endpoint per value in that same order.

```python
import bionetgen

model = bionetgen.load("model.bngl")
scan = model.parameter_scan(
    parameter="k",
    values=[0.1, 1.0],
    method="ode",
    t_end=2.0,
)
print(scan.parameter_name, scan.parameter_values)
print(scan.final("A_total"))
```

The old workflow looped over `bionetgen.run()` calls, edited the parameter and parsed one output file per rate. BNG3 applies each value to the named parameter directly and the result keeps the value-to-endpoint association.

### Sensitivity Analysis

```python
import bionetgen

model = bionetgen.load("model.bngl")
sensitivity = model.sensitivity_analysis(
    parameters=["k"], observables=["A_total"], method="ode", t_end=2.0
)
print(sensitivity.matrix)
```

### Run Network-Free

```python
import bionetgen

model = bionetgen.load("model.bngl")
result = model.simulate(method="nf", t_end=2.0, n_steps=10, seed=172)
```

### Access Parameters

```python
import bionetgen

model = bionetgen.load("model.bngl")
values = {parameter.name: parameter.value for parameter in model.parameters}
print(values)
```

### SBML Export

```python
import bionetgen

model = bionetgen.load("model.bngl")
model.write_sbml("model.xml")
```

### SBML Import

With the `full` extra installed, use the `model.xml` from SBML Export.

```python
import bionetgen

model = bionetgen.from_sbml("model.xml", atomize=True)
result = model.simulate(method="ode", t_end=2.0)
```

### Programmatic Model Building

```python
from bionetgen.builder import ModelBuilder

builder = ModelBuilder("MyModel")
builder.add_parameter("k_on", 1.0)
builder.add_parameter("k_off", 0.1)
builder.add_molecule_type("A(b)")
builder.add_molecule_type("B(a)")
builder.add_seed_species("A(b)", 100)
builder.add_seed_species("B(a)", 200)
builder.add_observable("Molecules", "AB", "A(b!1).B(a!1)")
builder.add_rule("A(b) + B(a) -> A(b!1).B(a!1)", "k_on")
builder.add_rule("A(b!1).B(a!1) -> A(b) + B(a)", "k_off")

model = builder.build()
```

### Command Line

```bash
bionetgen check model.bngl
bionetgen run model.bngl --method ode --t-end 2 --n-steps 10 --output decay.tsv
bionetgen export model.bngl --format net --output decay.net
```

### Inspect A NET File

Run the command-line export above first.

```python
from bionetgen.network.network import Network

network = Network("decay.net")
network.write_model("decay_copy.net")
```

---

## PyBioNetGen Compatibility Boundaries

The migration reference is PyBioNetGen `28bf351a9bbfc197e19487c26dedda683716bb64` ([`provenance/upstreams.lock.yml`](../provenance/upstreams.lock.yml)). For the complete symbol-by-symbol breakdown, see [Detailed BNG2 & PyBioNetGen Change Reference](bng2_migration_reference.md).

- **Retained compatibility modules:** `bionetgen.bngmodel`, `bionetgen.BNGResult`, `bionetgen.network.network.Network`, `bionetgen.sim_getter` (RoadRunner via optional `libroadrunner`), `bionetgen.simulator.csimulator`, `bionetgen.core.exc` (`BNGError`, `BNGFormatError`, `BNGSimError`), and lazy SymPy helpers (`SympyOdes`, `export_sympy_odes`, `extract_odes_from_mexfile`) remain importable.
- **`modelapi.runner.run`:** Accepts `simulator`, `format`, `method`, `t_span`, `n_points`, and `timeout` (using the native worker for subprocess/timeout); retains PyBioNetGen's `n_points + 1` output row convention for single-simulation overrides.
- **BNGsim differences:** PyBioNetGen's Python `simulator="bngsim"` routing and `bngsim_parameter_scan` helpers are not reproduced by the file runner. Use `model.simulate(..., backend="bngsim")` in a build with `-DBUILD_BNGSIM_ADAPTER=ON`.
- **Removed default dependencies:** Perl, `cement`, `distutils`, `pyparsing`, and `pylru` are no longer required for the default path (`cement`/`colorlog`/`pyparsing`/`pylru` are in the optional `bionetgen[legacy]` extra).
- **Optional Perl fallback:** Setting `BIONETGEN_USE_PERL=1` (with `BNGPATH` pointing to a BNG2 installation) routes Python `bionetgen.run(path)` and `bionetgen.load(path).execute()` through Perl as a temporary transition aid. `bionetgen run MODEL` CLI is unavailable in that mode.

---

## Practical Lab Migration Checklist

Before switching routine production or publication jobs from BNG2 / PyBioNetGen to BNG3:

1. **Pin and preserve your legacy environment.** Create a separate environment for BNG3 instead of upgrading in place. Pin `bionetgen<3` (e.g., `bionetgen==0.8.7`) and record your existing `BNG2.pl` and `NFsim` versions/paths so you can always reproduce legacy outputs.
2. **Select 3–5 representative lab models.** Pick models covering the features your group relies on: finite network generation (compartments, functions, `TotalRate`, `DeleteMolecules`), ODE/SSA continuations (`continue=>1`, `setParameter`, `setConcentration`), parameter scans, network-free models, and any SBML imports or MATLAB/SBML exports.
3. **Verify syntax and generated networks first.** Run `bionetgen check model.bngl` and compare generated `.net` files (`bionetgen export model.bngl -f net -o bng3.net`) against BNG2 `.net` output (checking species count, reaction count, statistical factors, and observable groups—remember canonical species ordering may differ while the graph-isomorphic network matches).
4. **Compare deterministic trajectories (ODE).** Run your legacy pipeline and BNG3 on the exact same `t_start`, `t_end`, `n_steps`/`sample_times`, `rtol`, and `atol`. Check maximum relative and absolute observable differences across the full time grid.
5. **Compare stochastic / network-free models with the right criterion.**
   - Pass explicit nonzero seeds (`seed != 0`).
   - Use **ensemble statistical comparison** (mean, variance, empirical CDF across e.g. 50–200+ seeds) when comparing BNG3 NFnext (`method="nf"`) against standalone NFsim or BNG2 SSA.
   - If you rely on NFsim-specific `-utl` or `equilibrate`, test `method="nfcore"` with `traversal_limit` / `equilibrate`.
6. **Audit script contracts and working directories.**
   - Check every `bionetgen.run(path)` call: add `out="results_dir"` if your script expects `.gdat`/`.cdat` files and `BNGResult`, or migrate to `SimResult` (`result.time`, `result.observables[...]`).
   - Check output file naming (`prefix`/`suffix` and `--outdir`) and note any features that require `main` vs. `v3.0.0a1`.
7. **Isolate any discrepancy before changing tolerances.** Reduce to the smallest `.bngl` reproducer, confirm whether the difference is in parsing, `.net` generation, solver defaults, or seed semantics, and open an issue on [RuleWorld/BNG3/issues](https://github.com/RuleWorld/BNG3/issues) with both outputs attached.

---

## Repository Maintenance

Per [Maintainer Decisions](DECISIONS.md), [RuleWorld/BNG3](https://github.com/RuleWorld/BNG3) is the successor to `RuleWorld/bionetgen`, `RuleWorld/NFsim`, and `RuleWorld/PyBioNetGen`. Report BNG3 bugs and submit changes in `RuleWorld/BNG3`. The predecessor repositories remain pinned as independent reference oracles in [`provenance/upstreams.lock.yml`](../provenance/upstreams.lock.yml).
