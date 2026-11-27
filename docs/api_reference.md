# Python API Reference

This reference documents the public Python API exported by `bionetgen` (`python/bionetgen/__init__.py` and `python/bionetgen/model.py`). For low-level C++ pybind11 signatures, see [`python/bionetgen/_bionetgen_cpp.pyi`](../python/bionetgen/_bionetgen_cpp.pyi).

For support boundaries see the [Capability Guide](capabilities.md) (and [CAPABILITY_UNION_INVENTORY.md](CAPABILITY_UNION_INVENTORY.md)); final policy is in [DECISIONS.md](DECISIONS.md) and live evidence is in [CURRENT_PROGRESS.md](CURRENT_PROGRESS.md).

---

## Module: `bionetgen`

### Core Functions & Classes

#### `bionetgen.load(path) -> BioNetGenModel`

Parse a `.bngl` file with the C++ parser and return a `BioNetGenModel`.

- **Parameters:** `path` (`str | Path`)
- **Raises:** `_bionetgen_cpp.ParseError` on syntax errors.

#### `bionetgen.run(path, *args, method=..., t_end=..., n_steps=..., **kwargs)`

Supports two explicit contracts:

1. **Modern in-memory simulation (default when no output directory is passed):** returns `SimResult`. Defaults to `method="ode"`, `t_end=100.0`, `n_steps=100`. Supported methods in top-level `run()` are `"ode"`, `"ssa"`, `"nf"`, `"pla"`, and `"psa"` (use `model.simulate(method="nfcore")` or `"nfnext"` for explicit NF backend selection). Positional shorthand is supported: `bionetgen.run("model.bngl", "ssa", 20, 200)`.
2. **PyBioNetGen file-runner contract:** pass `out=directory`, an explicit `None`, or a non-method path-like second positional argument. Executes declared BNGL actions and returns `BNGResult`. Positionals after the output path follow PyBioNetGen order: `suppress`, `timeout`, `simulator`, `format`, `method`, `t_span`, `n_points`. Non-`None` `timeout` or `simulator="subprocess"` uses the bounded native subprocess worker (`subprocess.TimeoutExpired` on expiry). Invalid keyword methods raise `ValueError`; duplicate positional/keyword arguments raise `TypeError`.

#### `bionetgen.parameter_scan(model_or_path, parameter, *, values=None, min=None, max=None, n_points=None, log_scale=False, **kwargs) -> ScanResult`

Run a 1D parameter scan (accepts `parallel=N` for isolated multi-process execution).

#### `bionetgen.parameter_scan_2d(model_or_path, parameter1, values1, parameter2, values2, *, **kwargs) -> ScanResult2D`

Run a 2D parameter grid scan.

#### `bionetgen.sensitivity_analysis(model_or_path, parameters=None, observables=None, *, **kwargs) -> SensitivityResult`

Compute local normalized sensitivities via central finite differences (`delta=0.01` default).

#### `bionetgen.from_sbml(path, atomize=False, **options) -> BioNetGenModel`

Import an SBML file through the Atomizer bridge (requires `bionetgen[full]` / `python-libsbml`). Raises `BioNetGenError` on import failure.

#### `bionetgen.sbml_to_bngl(path, atomize=False, **options) -> str`

Translate an SBML file to BNGL text (requires `bionetgen[full]` / `python-libsbml`).

#### `bionetgen.to_bngir(model, *, provenance=None, version="0.2") -> str` / `bionetgen.from_bngir(text_or_dict) -> BioNetGenModel`

Serialize and deserialize models as deterministic BNGIR JSON (`"0.2"` is the default structural format; `"0.1"` is retained for wire compatibility).

#### `bionetgen.semantic_equal(model_a, model_b, ...) -> bool`

Exact process-level semantic equality up to consistent molecule/site/state renaming. Raises `bionetgen.EqualityUndecided` when equivalence cannot be decided rather than returning `False`.

#### GPU Introspection Helpers

- `bionetgen.gpu_backend_capabilities() -> list[dict]` — Reports compiled GPU routes (`finite_batch_ssa`, `nfnext_unary_state_change`, and on post-`v3.0.0a1` `main`, `nfnext_graph_corpus`) and physical-device availability.
- `bionetgen.gpu_backends() -> list[dict]` — Finite-network batched-SSA GPU backend compilation and availability.
- `bionetgen.default_gpu_backend() -> str` — Default available finite-network batched-SSA GPU backend (`"metal"`, `"cuda"`, or `"none"`).

#### Exceptions & Metadata

- `bionetgen.__version__` — Package version string (`"3.0.0a1"`).
- `bionetgen.BioNetGenError` — Raised when SBML import fails or yields no usable BNGL.
- `bionetgen.EqualityUndecided` — Raised by `semantic_equal()` when exact equivalence is undecided.
- `bionetgen.core.exc` — Exposes `BNGError`, `BNGFormatError`, `BNGSimError`, `BNGVersionError`.

#### Lazy Compatibility Exports

Loaded on demand so optional dependencies stay optional: `bngmodel`, `BNGResult`, `sim_getter`, `defaults`, `SympyOdes`, `export_sympy_odes`, `extract_odes_from_mexfile`, `BNGSIM_AVAILABLE`, `BNGSIM_VERSION`.

---

## Class: `BioNetGenModel`

High-level wrapper around the parsed C++ `Model`.

### Inspection Properties

| Property | Type / Description |
| --- | --- |
| `name` | `str` — Model name |
| `source_path` | `Optional[str]` — Source `.bngl` path when loaded from disk |
| `parameters` | `list` — Parameter definitions (`name`, `value`, `expression`) |
| `molecule_types` | `list` — Molecule type definitions |
| `seed_species` | `list` — Seed species definitions from the BNGL block |
| `observables` | `list` — Observable definitions |
| `reaction_rules` | `list` — Reaction rules |
| `functions` | `list` — User-defined functions |
| `compartments` | `list` — Compartment definitions |
| `actions` | `list` — Structured action objects (`name`, `arguments`) |
| `species` | `tuple[CRNSpecies, ...]` — Generated network species (lazily calls `generate_network()`) |
| `complexes` | `tuple[CRNComplex, ...]` — Unique reactant/product multisets of species indices |
| `reactions` | `tuple[CRNReaction, ...]` — Generated reactions with `reactant_complex`, `product_complex`, and `CRNRateLaw` |
| `stoichiometric_matrix` | `np.ndarray` (`int64`, shape `(len(species), len(reactions))`) — Dense stoichiometry matrix `N[s, r]` |

### Parameter & Topology Editing Methods

- `get_parameter(name)` — Return a read-only parameter object by name.
- `set_parameter(name, value)` — Set a numeric parameter value, re-evaluate dependent expressions, and invalidate stale network caches (while preserving continuation state when `continue_simulation=True` is used next).
- Atomic topology edits (regenerate BNGL, re-parse, validate, preserve `set_parameter` overrides, and discard stale network/continuation caches; raise `ValueError` without mutating the model on invalid edits):
  - `add_parameter(name, value)` / `remove_parameter(name)`
  - `add_compartment(name, dimension, volume, parent=None)` / `remove_compartment(name)`
  - `add_molecule_type(definition)` / `remove_molecule_type(name_or_definition)`
  - `add_seed_species(pattern, amount, compartment=None, constant=False)` / `remove_seed_species(pattern, compartment=None)` / `set_seed_species_amount(pattern, amount, compartment=None)` / `move_species_to_compartment(pattern, compartment, from_compartment=None)`
  - `add_observable(name, pattern, obs_type="Molecules")` / `remove_observable(name)`
  - `add_reaction_rule(definition, name=None)` / `remove_reaction_rule(name_or_label)`
  - `add_function(definition, name=None)` / `remove_function(name)`

### Simulation & Execution Methods

#### `generate_network(max_iter=None) -> GeneratedNetwork`

Generate and cache the reaction network. When `max_iter=None`, honors `max_iter` from any `generate_network` action in the model, otherwise uses the C++ default (`100`).

#### `simulate(...) -> SimResult`

```python
model.simulate(
    method="ode",               # "ode", "ssa", "nf" (NFnext), "nfnext", "nfcore", "pla", "psa"
    t_end=100.0,
    n_steps=100,
    t_start=0.0,
    rtol=1e-8,                  # ODE only
    atol=1e-12,                 # ODE only
    seed=0,                     # 0 = non-reproducible system default; nonzero = reproducible
    pla_config="",              # PLA only
    psa_poplevel=100.0,         # PSA only
    verbose=False,
    max_step=0.0,               # ODE only (0 disables limit)
    steady_state=False,         # ODE only
    steady_state_tol=None,      # ODE only (defaults to atol)
    stop_if="",                 # ODE/SSA only
    sample_times=None,          # Strictly increasing times in [t_start, t_end]
    max_sim_steps=0,            # SSA/NF event limit (0 = unlimited for SSA; 1_000_000 default for NFnext)
    output_step_interval=0,     # SSA only
    sparse=False,               # ODE sparse CVODE linear solver
    check_product_scale=0.0,    # ODE warning threshold
    equilibrate=0.0,            # NFcore only (method="nfcore")
    traversal_limit=-1,         # NFcore only (-1 = auto, >=0 = NFsim -utl)
    backend=None,               # Finite solvers: None/"auto", "native", or "bngsim"
    continue_simulation=False,  # Continue last native ODE/SSA or hybrid NF state
    population_threshold=0,     # Hybrid NF population threshold
    batch_size=0,               # SSA batched ensemble size (>0 for method="ssa" only)
    batch_gpu_preferred=True,
    batch_gpu_backend="auto",
)
```

#### `reset_simulation() -> None`

Discard cached network and continuation state so the next run starts from model seeds.

#### `simulate_batch_ssa(*, batch_size=1000, t_end=10.0, n_steps=10, t_start=0.0, base_seed=42, max_sim_steps=0, backend="auto", threads=0) -> dict`

Run finite-network batched direct SSA on GPU (`"metal"`, `"cuda"`, `"auto"`) or CPU thread pool (`"cpu"` / `"none"`). Explicit `"metal"`/`"cuda"` fail closed if unavailable.

#### `simulate_nfnext_gpu(sample_times, *, seed=0, batch_size=1024, backend="metal", max_events=1_000_000, max_particles=1_000_000, mode="unary") -> GpuBatchSimResult`

Run an explicit, fail-closed network-free GPU batch with no CPU fallback. `mode="graph"` is available on **post-`v3.0.0a1` `main`**; `v3.0.0a1` supports single-site unary state-change models only (`mode` parameter added post-`v3.0.0a1`). See [Network-Free Simulation](network_free_simulation.md).

#### `execute(verbose=False) -> None`

Execute all actions in the BNGL model's action block.

#### `parameter_scan(...) -> ScanResult` / `parameter_scan_2d(...) -> ScanResult2D` / `sensitivity_analysis(...) -> SensitivityResult`

Bound convenience wrappers around the top-level analysis functions.

### Export & Visualization Methods

- **In-memory serialization:** `to_bngl() -> str`, `to_xml() -> str`, `to_bngir(*, provenance=None, version="0.2") -> str`, `to_crn() -> dict`
- **File writers:** `write_bngl(path)` (aliases: `save(path)`, `write_model(path)`), `write_xml(path)`, `write_net(path)`, `write_sbml(path)`, `write_matlab(path)`, `write_latex(path)`, `write_crn(path)`
- **Graph & Multi exports** (return serialized text, and also write to disk if `path` is given): `contact_map(path=None)`, `regulatory_graph(path=None)`, `rule_influence_graph(path=None)`, `reaction_network_graph(path=None)`, `ruleviz_pattern(path=None)`, `ruleviz_operation(path=None)`, `process_graph(path=None)`, `sbml_multi(path=None)`
- **Notebook display:** `_repr_html_()`

---

## Result & Builder Classes

### `SimResult`

| Property / Method | Description |
| --- | --- |
| `time` | 1D NumPy array of output time points |
| `observables` | `dict[str, np.ndarray]` keyed by observable name |
| `concentrations` | Species concentration matrix (2D NumPy array) when available |
| `observable_names` | List of observable names |
| `n_steps` | Number of time points |
| `backend` | `str` — Executed backend (`"native"`, `"bngsim"`, `"nfnext"`, `"nfsim"`) |
| `to_dataframe()` | Wide `pandas.DataFrame` (requires `bionetgen[plotting]`) |
| `plot(observables=None, show=True, **kwargs)` | Matplotlib time-course plot (requires `bionetgen[plotting]`) |
| `_repr_html_()` | Notebook HTML representation |

### `GpuBatchSimResult`

Returned by `model.simulate_nfnext_gpu()`. Exposes `time`, `observables` (arrays of shape `(batch_size, len(sample_times))`), `observable_names`, `batch_size`, and `backend` (`"metal"` or `"cuda"`).

### `ScanResult` & `ScanResult2D`

- `ScanResult`: `parameter_name`, `parameter_values`, `results` (`list[SimResult]`), `observable_names`; methods `final(observable)`, `at_time(t, observable)`, `to_dataframe()`, `plot(observable, show=True, **kwargs)`, `_repr_html_()`.
- `ScanResult2D`: 2D grid (`values1 x values2`); methods `final(observable)`, `at_time(t, observable)`, `to_dataframe()`, `plot_heatmap(observable, show=True, **kwargs)`, `_repr_html_()`.

### `SensitivityResult`

Properties: `parameter_names`, `observable_names`, `matrix` (normalized sensitivity matrix), `baseline` (`SimResult`). Methods: `rank(observable)`, `to_dataframe()`, `plot(show=True, **kwargs)`.

### `ModelBuilder`

Programmatic BNGL construction (`from bionetgen import ModelBuilder` or `from bionetgen.builder import ModelBuilder`): `add_parameter(name, value)`, `add_molecule_type(pattern)`, `add_seed_species(pattern, amount, compartment=None)`, `add_observable(observable_type, name, pattern)`, `add_rule(reaction, rate, label=None)`, `add_function(name, expression, args=None)`, `add_compartment(line)`, `add_action(action)`, `to_bngl() -> str`, `build() -> BioNetGenModel`.

### CRN Record Types

Immutable dataclasses exported at top level: `CRNSpecies(index, name)`, `CRNComplex(index, species)`, `CRNRateLaw(type, expression, factor, rule_name, parameters, functions, observables, parameter_units)`, `CRNReaction(index, label, reactants, products, reactant_complex, product_complex, rate_law)`.

---

## Module: `bionetgen.viz`

Standalone graph export functions (return serialized text and optionally write to `path`): `write_contact_map`, `write_regulatory_graph`, `write_rule_influence_graph`, `write_reaction_network_graph`, `write_ruleviz_pattern`, `write_ruleviz_operation`, `write_process_graph`, `write_sbml_multi`.
