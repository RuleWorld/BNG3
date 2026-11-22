# Migration Guide

BioNetGen 3 provides an in-process Python API backed by C++. The
[capability inventory](CAPABILITY_UNION_INVENTORY.md) defines release scope.
See [current progress](CURRENT_PROGRESS.md) for qualification evidence and
[the maintainer decisions](DECISIONS.md) for release policy.

## Install And Choose A Backend

BNG3 and PyBioNetGen share the distribution name `bionetgen`. To stay on
PyBioNetGen during the transition, install `bionetgen<3` in a separate
environment. To evaluate BNG3, install an identified pre-release wheel or
run `python -m pip install .` from a BNG3 checkout. Once BNG3 is published
as a stable release, the standard install command is `pip install bionetgen`.
Check the resolved version with `bionetgen --version`.

| Backend | Selection and qualification |
| --- | --- |
| Native finite-network | The default for `ode`, `ssa`, `pla`, and `psa`. |
| NFnext | The default for `method="nf"` (promoted in #832 after the full pinned-native NFsim and NFcore corpus parity passed; see [#149](https://github.com/RuleWorld/BNG3/issues/149) and `docs/DECISIONS.md` item 4). `method="nfnext"` remains explicitly selectable. |
| NFcore | Still selectable explicitly with `method="nfcore"` through the common backend interface. |
| BNGsim | Optional finite-network backend selected with `backend="bngsim"` in a build that includes the adapter. See [ADR 0003](adr/0003-bngsim-canonical-finite-backend.md). |
| JAX CPU | The `jax` extra installs the dependencies for the separate [JAX ODE](../python/bionetgen/jax_ode.py) and [JAX SSA](../python/bionetgen/jax_ssa.py). See [#473](https://github.com/RuleWorld/BNG3/issues/473) for the qualified surface. |
| Metal and CUDA | Actual device qualification is tracked separately in [#474](https://github.com/RuleWorld/BNG3/issues/474). |

Install the `plotting` extra for plotting and dataframe access, `notebook`
for a notebook kernel, and `full` for the SBML and SymPy integrations.


## Compatibility Overview

| Task | PyBioNetGen / BNG2 | BioNetGen 3 |
| --- | --- | --- |
| Load model | `bng = bionetgen.bngmodel("m.bngl")` | `model = bionetgen.load("m.bngl")` |
| Simulate | `bionetgen.run("m.bngl")` | `model.simulate(method="ode")` |
| Read observables | Parse `.gdat` or `.cdat` output | `result.observables["X"]` |
| Parameter scan | Loop over `bionetgen.run()` calls | `model.parameter_scan(...)` |
| Sensitivity analysis | Manual finite differences | `model.sensitivity_analysis(...)` |
| NFSim | External NFSim binary | `model.simulate(method="nf")` |
| Access parameters | XML-parsed dicts | `model.parameters` list of objects |
| Export SBML | `writesbml` action | `model.write_sbml("out.xml")` |
| Build models | Hand-written BNGL only | `ModelBuilder` API |
| Import SBML | Atomizer CLI | `bionetgen.from_sbml("model.xml")` |

The compatibility file runner supports `simulator="auto"`, `"native"`, and
`"subprocess"`. A non-`None` `timeout`, or an explicit subprocess selection,
runs the same native parser and executor in a separate process. The deadline
includes worker startup and native execution; expiry raises
`subprocess.TimeoutExpired`. Declared actions, method/time overrides, and
output-point normalization use the same common runner in both routes.
`timeout=None` with the default simulator keeps direct execution.

## Python and CLI Run Contracts

`bionetgen.run()` supports two explicit call styles. With no output argument
specified, it uses the modern in-memory API and returns a `SimResult`; its
default method is ODE with `t_end=100` and `n_steps=100`. The modern method and
grid can also be positional: `bionetgen.run("model.bngl", "ssa", 20, 200)`.
The dispatcher uses `*args` plus keyword-only `method`, `t_end`, and `n_steps`
so it can preserve legacy positional output-directory calls. An explicit
`None`, a path-like second positional argument, or a string that is not one of
`ode`, `ssa`, `nf`, `pla`, or `psa`, selects the file runner and returns
`BNGResult`; use `out=` when a directory's string name could be mistaken for a
method. After a positional output path, remaining positionals retain the
PyBioNetGen order: `suppress`,
`timeout`, `simulator`, `format`, `method`, `t_span`, and `n_points`.
Timeouts use the bounded native worker described above. Invalid keyword
methods raise `ValueError`, and duplicate positional/keyword values raise
`TypeError`.

```python
# Modern single-simulation result, defaulting to ODE, 0..100, 100 steps.
result = bionetgen.run("model.bngl")

# Legacy action workflow and its .xml, .net, .gdat and .cdat outputs.
files = bionetgen.run("model.bngl", out="results")
```

In the file runner, an explicit `method=` selects one modern simulation and
writes one `.gdat` result. Time-only options preserve the model's declared
actions, ordering, and non-simulation side effects. The same absolute
`t_start`/`t_end` and step count are applied to each direct simulation action;
`t_span=(start, end)` sets both times, and `n_points=N` means `N-1` steps plus
both endpoints. A lone time or step option changes only that part of each
action's existing grid. This is the BNG3 compatibility contract; it does not
claim PyBioNetGen parity for time-grid forwarding. Combining a time override
with an action's `sample_times` or truthy `continue` option raises
`NotImplementedError` before the output directory is created. Solver-specific
options such as `rtol`, `atol`, `seed`, `pla_config`, and `psa_poplevel` require
an explicit modern `method=` override; action-preserving calls reject them
rather than dropping them.

The CLI keeps the same distinction. `bionetgen run MODEL --method ssa ...` writes a
tab-separated table for one selected simulation. `bionetgen run --input MODEL`
executes the model's actions into an output directory; explicit time options
modify the action grid while preserving actions. Supplying `--method` with
`--input` opts into a single modern simulation; solver-specific options are
accepted there. The five modern methods
(`ode`, `ssa`, `nf`, `pla`, and `psa`) are contract-tested through the Python
API and positional-model CLI. The notebook command clears saved execution
outputs from its templates. Its model-specific example uses
`bionetgen.load(...).simulate()` and `SimResult.plot()`; the built-in example
uses the file-runner result's `gdats` mapping. Install `bionetgen[notebook]`
for an IPython kernel and Matplotlib before running either template in a
Jupyter frontend. The frontend itself is not included in that extra.

The maintained integration surface includes `from_sbml` and `sbml_to_bngl`,
the optional SymPy ODE export, and the legacy
`sim_getter(..., sim_type="libRR")` adapter. SBML import and SymPy ODE export
require `python-libsbml` and `sympy`, respectively; both are included in
`bionetgen[full]`. The RoadRunner adapter remains optional. Install its
separate PyPI dependency with `python -m pip install libroadrunner` (the
import module is named `roadrunner`); when that module is absent, the adapter
raises an `ImportError` that names the dependency. `sim_getter` accepts SBML
through either `model_file` or `model_str`; `.simulate(...)` returns
RoadRunner's time-course matrix. The file-runner rejects
`simulator="bngsim"`; BNG3's `backend="bngsim"` belongs to its separate native
finite-network API and does not reproduce PyBioNetGen's optional Python
`bngsim` routing contract. BNG3 does not expose a PySB adapter.

## Before And After

Save the BNGL in [Parameter Scans](#parameter-scans) as `model.bngl` and
run these examples from its directory.

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

The mass-action law for `A() -> 0` is `A(t) = A0 * exp(-k * t)`. With
`A0 = 100` and `t_end = 2.0`, the requested rates `0.1` and `1.0` give the
endpoints `100 * exp(-0.2) ≈ 81.873075` and `100 * exp(-2) ≈ 13.533528`.
`ScanResult.parameter_values` records the rate used by each simulation in
request order, `parameter_name` names the scanned parameter, and `final()`
returns one endpoint per value in that same order.

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

The old workflow looped over `bionetgen.run()` calls, edited the parameter and
parsed one output file per rate. BNG3 applies each value to the named parameter
directly and the result keeps the value-to-endpoint association. This example
is executed verbatim by `tests/python/test_migration_guide_installed_example.py`
against the installed wheel. Cross-package trajectory equivalence is not
claimed; see the compatibility limits below.

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

## PyBioNetGen API Differences

The migration reference is PyBioNetGen revision
`28bf351a9bbfc197e19487c26dedda683716bb64`, the accepted pin in
[`provenance/upstreams.lock.yml`](../provenance/upstreams.lock.yml). The mapping
below separates workflows exercised by BNG3 tests from replacements and
unqualified areas. The tests verify BNG3 behavior; they do not establish that
the same models produce the same trajectories or side effects in both packages.

| Common workflow | BNG3 entry point | Evidence and limit |
| --- | --- | --- |
| Load a BNGL file and simulate it | `bionetgen.load(path).simulate(...)` | Executable migration example in `tests/python/test_migration_workflows.py`; tested on the BNG3 engine. |
| Run a single simulation from a file | `bionetgen.run(path, method=..., t_end=..., n_steps=...)` | `tests/python/test_compatibility_contract.py` exercises supported methods, results, and dispatch. The modern API returns `SimResult`, not the old file result. |
| Run declared model actions into an output directory | `bionetgen.run(path, out=...)` | BNG3 compatibility tests exercise generated `.xml`, `.net`, `.gdat`, and `.cdat` outputs and action preservation. This uses BNG3's in-process runner; it does not promise PyBioNetGen backend or time-grid parity. |
| Inspect simulation results | `SimResult.time`, `.observables`, `.to_dataframe()` | The migration workflow test checks the documented fields and dataframe shape. |
| Scan a parameter | `model.parameter_scan(...)` | The installed-example test executes the guide's two-rate decay scan and checks its analytic endpoints; cross-package scan equivalence is not established. |
| Build a model in Python | `ModelBuilder` | A construction and simulation smoke test exists; full equivalence to direct edits of PyBioNetGen's block model is not established. |
| Import SBML | `bionetgen.from_sbml(path, atomize=True)` | The migration test covers one simple SBML model. It is not evidence for all SBML Core or package semantics; see the SBML qualification records. |
| Use the command line | `bionetgen run`, `bionetgen check`, `bionetgen export`, and other BNG3 commands | The migration test checks CLI version/help, and compatibility tests cover notebook generation. The old CLI option inventory is not fully mapped or parity-tested. |

CI's `pybionetgen-compat` job checks selected root exports and runner parameters
from the locked source, then runs `tests/python/test_compatibility_contract.py`
against the installed BNG3 package. `tests/python/test_migration_workflows.py`
executes the examples above against BNG3. The wheel job also runs
`tests/python/test_migration_guide_installed_example.py`, which executes
the examples in this guide against the installed package and console script.
It checks the decay trajectory, scan endpoints, sensitivity, and interchange
behavior for the example model. These checks do not import both
packages and compare all 4.7 inventory rows, do not validate every legacy
module or CLI option, and do not qualify every workflow listed here as
source-semantic parity.

The pinned PyBioNetGen `run` accepts `simulator`, `format`, `method`, `t_span`,
and `n_points`. Its `simulator="bngsim"` and `simulator="subprocess"` choices
select distinct upstream routes. BNG3's `bionetgen.run(path, out=...)` is a
separate compatibility entry point: it supports `simulator="auto"`,
`"native"`, and `"subprocess"` with BNGL input. Non-`None` timeouts are enforced
through a native worker; the PyBioNetGen Python `bngsim` route remains
unimplemented. An explicit `method` requests
one BNG3 simulation; time-grid-only overrides preserve declared direct
simulation actions subject to the limits above. These BNG3 contracts are tested
locally, but have not been differentially checked against the pinned runner.

For single-simulation overrides, modelapi.runner.run also accepts an explicit
subprocess selection or a timeout. It returns the same SimResult fields,
including concentrations, exported functions, array dtypes, and backend
metadata, through the native worker. Its n_points value retains the pinned
modelapi step-count convention (n_points + 1 output rows). An explicit out
with these overrides remains unsupported.

The run command accepts --log, --timeout, and --no-bngsim for both positional
models and --input workflows. These controls use the same native worker;
--no-bngsim selects native execution in a separate process. A positional model
still requests one simulation and writes a single output file, while --input
preserves declared actions and writes a result directory. --format bngl is
accepted; other input formats require conversion first. Logs retain worker
output and error diagnostics, including partial output on a timeout.

Other API boundaries:

- PyBioNetGen's BNGsim helper, bridge, and parameter-scan modules do not have
  module-for-module replacements. `BioNetGenModel.simulate` exposes a BNGsim
  backend, while `model.parameter_scan` does not expose a backend selector.
  The legacy compatibility runner does not route via PyBioNetGen's
  `simulator="bngsim"` choice. These are distinct workflows and their parity
  remains unqualified.
- The legacy `bionetgen.simulator.csimulator` classes are available for
  import. The compile-to-C workflow requires a C compiler and the legacy
  toolchain. The `sim_getter` convenience API selects the RoadRunner
  adapter. Use `model.simulate()` for the native BNG3 defaults.
- The legacy `bionetgen.network.network.Network` class reads and writes
  `.net` files for inspection and editing. The migration example exercises
  one exported network. Full installed differential coverage remains part
  of [#171](https://github.com/RuleWorld/BNG3/issues/171).
- `BNGFormatError` and `BNGSimError` are available in `bionetgen.core.exc`.

## Removed Dependencies

The default path no longer depends on:

- Perl
- cement
- distutils
- pyparsing
- pylru

Optional legacy compatibility still exists behind `BIONETGEN_USE_PERL=1`, but the new API does not require it.

## Breaking Changes

- `bngmodel()` is replaced by `load()` as the recommended model-loading API.
- Single-simulation calls return in-memory `SimResult` objects; the action-preserving
  file runner continues to write files and returns a compatibility-style `BNGResult`.
- `model.actions` is a structured list of action objects, not a parsed dict.
- `execute()` is now a method on `BioNetGenModel`.
- The default simulation path is C++-backed and synchronous.
- Notebook rendering uses `_repr_html_()` rather than a custom notebook wrapper.

## Migration Checklist

1. Replace `bngmodel(path)` with `load(path)`.
2. Replace subprocess-based simulations with `model.simulate()`.
3. Replace `.gdat` parsing with `SimResult` accessors.
4. Replace scan loops with `model.parameter_scan()`.
5. Replace manual SBML translation with `from_sbml()`.
6. Replace hand-written BNGL assembly with `ModelBuilder` where practical.

## Notes On Legacy Mode

If you must keep the old Perl workflow for a while, set:

```bash
export BIONETGEN_USE_PERL=1
```

This is a transition aid, not the recommended long-term path.


## Repository Maintenance

The [maintainer decision](DECISIONS.md) designates
[RuleWorld/BNG3](https://github.com/RuleWorld/BNG3) as the successor to the
BioNetGen, NFsim, and PyBioNetGen repositories. Report BNG3 bugs and submit
changes in BNG3. At the transition, the predecessor repositories retire from
maintenance. Their source history remains available and their accepted
revisions remain pinned as independent references in
[`provenance/upstreams.lock.yml`](../provenance/upstreams.lock.yml).
