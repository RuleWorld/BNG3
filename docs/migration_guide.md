# Migration Guide

BioNetGen 3 replaces the subprocess-based PyBioNetGen/BNG2 workflow with an in-process Python API backed by C++.

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

## Before And After

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
result = bionetgen.load("model.bngl").simulate(method="ode", t_end=100)
```

### Inspect Results

```python
model = bionetgen.load("model.bngl")
result = model.simulate(method="ode", t_end=100)

print(result.time)
print(result.observables["AB"])
print(result.to_dataframe().head())
```

### Parameter Scans

```python
import numpy as np

model = bionetgen.load("model.bngl")
scan = model.parameter_scan(
	parameter="k_on",
	values=np.logspace(-2, 2, 50),
	method="ode",
	t_end=100,
)
print(scan.final("AB"))
```

### SBML Import

```python
model = bionetgen.from_sbml("model.xml", atomize=True)
result = model.simulate(method="ode", t_end=100)
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

## Removed Dependencies

The default path no longer depends on:

- Perl
- cement
- distutils
- pyparsing
- pylru

Optional legacy compatibility still exists behind `BIONETGEN_USE_PERL=1`, but the new API does not require it.

## Breaking Changes

- `bngmodel()` is replaced by `load()`.
- Results are in-memory objects instead of flat files.
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
