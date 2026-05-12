# API Reference

## Module: `bionetgen`

### `bionetgen.load(path) → BioNetGenModel`

Load a BNGL model file.

**Parameters:**
- `path` (str | Path) — Path to the `.bngl` file.

**Returns:** `BioNetGenModel`

**Raises:** `_bionetgen_cpp.ParseError` if the file has syntax errors.

---

### `bionetgen.run(path, method="ode", t_end=100.0, n_steps=100, **kwargs) → SimResult`

Load a model and run simulation in one call.

**Parameters:**
- `path` (str | Path) — Path to the `.bngl` file.
- `method` (str) — `"ode"`, `"ssa"`, or `"nf"`.
- `t_end` (float) — End time.
- `n_steps` (int) — Number of output steps.
- `**kwargs` — Passed to `BioNetGenModel.simulate()`.

**Returns:** `SimResult`

---
# API Reference

This reference covers the high-level public API. For low-level extension details, see [python/bionetgen/_bionetgen_cpp.pyi](../python/bionetgen/_bionetgen_cpp.pyi).

## Module: `bionetgen`

### `load(path) -> BioNetGenModel`

Parse a BNGL file and return a model object.

### `run(path, method="ode", t_end=100.0, n_steps=100, **kwargs) -> SimResult`

Load a BNGL file and run a simulation in one call.

### `parameter_scan(model_or_path, parameter, *, values=None, min=None, max=None, n_points=None, log_scale=False, **kwargs) -> ScanResult`

Run a 1D parameter scan and return time-series results for each sampled value.

### `parameter_scan_2d(model_or_path, parameter1, values1, parameter2, values2, *, **kwargs) -> ScanResult2D`

Run a 2D parameter grid scan.

### `from_sbml(path, atomize=False, **options) -> BioNetGenModel`

Import SBML through the atomizer bridge and return a model.

### `sbml_to_bngl(path, atomize=False, **options) -> str`

Translate SBML to BNGL text.

### `ModelBuilder`

Build BNGL programmatically.

### `BioNetGenError`

Raised when SBML import fails or produces no usable BNGL output.

## Class: `BioNetGenModel`

High-level wrapper around the parsed C++ model.

### Properties

| Property | Description |
| --- | --- |
| `parameters` | Model parameters as `Parameter` objects |
| `molecule_types` | Molecule type definitions |
| `seed_species` | Seed species definitions |
| `observables` | Observable definitions |
| `reaction_rules` | Reaction rules |
| `functions` | User-defined functions |
| `compartments` | Compartment definitions |
| `actions` | Action block entries |
| `name` | Model name |
| `source_path` | Original BNGL file path when available |

### Methods

#### `get_parameter(name)`

Return a single parameter object by name.

#### `set_parameter(name, value)`

Set the numeric value of a parameter.

#### `generate_network(max_iter=100)`

Generate the reaction network, caching it on the model.

#### `simulate(method="ode", t_end=100.0, n_steps=100, ...) -> SimResult`

Run a simulation using one of the bundled engines.

#### `execute(verbose=False)`

Execute actions in the BNGL action block.

#### `parameter_scan(...) -> ScanResult`

Run a 1D scan.

#### `parameter_scan_2d(...) -> ScanResult2D`

Run a 2D scan.

#### `sensitivity_analysis(...) -> SensitivityResult`

Compute local normalized sensitivities.

#### `contact_map(path=None)`

Export a contact map graph.

#### `regulatory_graph(path=None)`

Export a regulatory graph.

#### `rule_influence_graph(path=None)`

Export a rule influence graph.

#### `reaction_network_graph(path=None)`

Export a reaction network graph.

#### `ruleviz_pattern(path=None)`

Export a rule pattern graph.

#### `ruleviz_operation(path=None)`

Export a rule operation graph.

#### `process_graph(path=None)`

Export a process graph.

#### `sbml_multi(path=None)`

Export SBML Multi.

#### `write_xml(path)` / `write_bngl(path)` / `write_net(path)` / `write_sbml(path)` / `write_matlab(path)` / `write_latex(path)`

Export the model to the requested format.

#### `_repr_html_()`

Return HTML for notebook rendering.

## Class: `SimResult`

Simulation output container.

| Property | Description |
| --- | --- |
| `time` | Time points as a NumPy array |
| `observables` | Observable arrays keyed by name |
| `concentrations` | Species concentrations, when available |
| `n_steps` | Number of time points |
| `observable_names` | Observable name list |

### Methods

#### `to_dataframe() -> pandas.DataFrame`

Convert the result to a wide DataFrame.

#### `plot(observables=None, show=True, **kwargs)`

Plot observable time courses with matplotlib.

#### `_repr_html_()`

Return notebook HTML with an embedded plot.

## Class: `ScanResult`

1D scan output.

| Property | Description |
| --- | --- |
| `parameter_name` | Scanned parameter name |
| `parameter_values` | Scan grid values |
| `results` | List of `SimResult` objects |
| `observable_names` | Observable names |

### Methods

#### `final(observable)`

Return final values for one observable across the scan grid.

#### `at_time(t, observable)`

Return interpolated values at a given time point.

#### `to_dataframe()`

Convert to a long-form DataFrame.

#### `plot(observable, show=True, **kwargs)`

Plot final values versus the scanned parameter.

#### `_repr_html_()`

Return notebook HTML with an embedded scan plot.

## Class: `ScanResult2D`

2D scan output with the same shape conventions as `values1 x values2`.

### Methods

#### `final(observable)`

Return the final-value heatmap.

#### `at_time(t, observable)`

Return the time-slice heatmap.

#### `to_dataframe()`

Convert the grid to a long-form DataFrame.

#### `plot_heatmap(observable, show=True, **kwargs)`

Plot a heatmap with matplotlib.

#### `_repr_html_()`

Return notebook HTML with an embedded heatmap.

## Class: `SensitivityResult`

Sensitivity matrix container.

| Property | Description |
| --- | --- |
| `parameter_names` | Parameters in row order |
| `observable_names` | Observables in column order |
| `matrix` | Normalized sensitivity matrix |
| `baseline` | Baseline `SimResult` |

### Methods

#### `rank(observable)`

Rank parameters by absolute sensitivity for one observable.

#### `to_dataframe()`

Return the matrix as a DataFrame.

#### `plot(show=True, **kwargs)`

Plot the matrix as a heatmap.

## Class: `ModelBuilder`

Build BNGL programmatically.

### Methods

#### `add_parameter(name, value)`

Append a parameter definition.

#### `add_molecule_type(pattern)`

Append a molecule type definition.

#### `add_seed_species(pattern, amount, compartment=None)`

Append a seed species definition.

#### `add_observable(observable_type, name, pattern)`

Append an observable definition.

#### `add_rule(reaction, rate, label=None)`

Append a reaction rule.

#### `add_function(name, expression, args=None)`

Append a function definition.

#### `add_compartment(line)`

Append a raw compartment line.

#### `add_action(action)`

Append a raw action line.

#### `to_bngl()`

Return the assembled BNGL text.

#### `build()`

Parse the BNGL text with the C++ backend and return a `BioNetGenModel`.

## Module: `bionetgen.viz`

These functions return the serialized graph text and optionally write it to disk.

| Function | Description |
| --- | --- |
| `write_contact_map(model, path=None)` | Contact map graph export |
| `write_regulatory_graph(model, path=None)` | Regulatory graph export |
| `write_rule_influence_graph(model, path=None)` | Rule influence graph export |
| `write_reaction_network_graph(model, path=None)` | Reaction network graph export |
| `write_ruleviz_pattern(model, path=None)` | Rule pattern graph export |
| `write_ruleviz_operation(model, path=None)` | Rule operation graph export |
| `write_process_graph(model, path=None)` | Process graph export |
| `write_sbml_multi(model, path=None)` | SBML Multi export |

## Low-Level C++ Bindings

The `_bionetgen_cpp` module still exposes `parse_file`, `parse_string`, `generate_network`, `simulate_ode`, `simulate_ssa`, `simulate_nf`, and `io.*` helpers. The new `viz` submodule mirrors the graph exports used by the Python wrappers.
