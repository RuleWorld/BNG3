# User Guide

This guide walks through the new BNG3 workflow from loading a BNGL file to scanning parameters, importing SBML, and building models programmatically.

## 1. Install

```bash
pip install bionetgen
```

If you are working from source, use `pip install -e .` in the repository root.

## 2. Load Models

```python
import bionetgen

model = bionetgen.load("path/to/model.bngl")
print(model.name)
```

You can also parse BNGL text directly with the C++ extension:

```python
import bionetgen._bionetgen_cpp as _cpp

model_obj = _cpp.parse_string("""
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A(b)
end molecule types
begin seed species
    A(b) 100
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    A(b) -> 0 k
end reaction rules
end model
""")
```

## 3. Inspect Model Components

The model object exposes the BNGL AST as Python objects:

```python
for parameter in model.parameters:
    print(parameter.name, parameter.value, parameter.expression)

for molecule_type in model.molecule_types:
    print(molecule_type.name)
    for component in molecule_type.components:
        print("  ", component.name, component.allowed_states)

for rule in model.reaction_rules:
    print(rule.label, rule.reactant_patterns, rule.product_patterns, rule.rates)

for observable in model.observables:
    print(observable.name, observable.type, observable.patterns)

for seed in model.seed_species:
    print(seed.pattern, seed.amount)
```

## 4. Simulate

### ODE

```python
result = model.simulate(method="ode", t_end=100.0, n_steps=200)
```

### SSA

```python
result = model.simulate(method="ssa", t_end=100.0, n_steps=200, seed=42)
```

### NFSim

```python
result = model.simulate(method="nf", t_end=100.0, n_steps=200, seed=42)
```

Network-based methods (`ode`, `ssa`, `pla`, `psa`) automatically generate the network if needed.

## 5. Work With Results

```python
result = model.simulate(method="ode", t_end=100)

print(result.time)
print(result.observable_names)
print(result.observables["AB"])

df = result.to_dataframe()
fig, ax = result.plot()
```

In notebooks, `model` and `result` render as HTML automatically via `_repr_html_()`.

## 6. Scan Parameters

### One-dimensional scan

```python
import numpy as np

scan = model.parameter_scan(
    parameter="k_on",
    values=np.logspace(-2, 2, 20),
    method="ode",
    t_end=100,
)

print(scan.final("AB"))
print(scan.at_time(50, "AB"))
frame = scan.to_dataframe()
```

### Two-dimensional scan

```python
scan2d = model.parameter_scan_2d(
    parameter1="k_on",
    values1=np.logspace(-2, 2, 10),
    parameter2="k_off",
    values2=np.logspace(-3, 1, 10),
    method="ode",
    t_end=100,
)

scan2d.plot_heatmap("AB")
```

## 7. Sensitivity Analysis

```python
sens = model.sensitivity_analysis(
    parameters=["k_on", "k_off"],
    observables=["AB"],
    method="ode",
    t_end=100,
    delta=0.01,
)

print(sens.matrix)
print(sens.rank("AB"))
```

## 8. Export Models

```python
model.write_xml("model.xml")
model.write_bngl("model_copy.bngl")
model.write_net("model.net")
model.write_sbml("model.sbml")
model.write_matlab("model.m")
model.write_latex("model.tex")
model.contact_map("contact_map.graphml")
```

Graph exports are also available as string-returning methods when no path is supplied:

```python
graphml = model.contact_map()
```

## 9. Import SBML

```python
import bionetgen

model = bionetgen.from_sbml("tests/python/test/test_sbml.xml")
bngl_text = bionetgen.sbml_to_bngl("tests/python/test/test_sbml.xml")
```

If atomization is needed, pass `atomize=True`.

## 10. Build Models Programmatically

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
print(builder.to_bngl())
```

## 11. CLI

```bash
bionetgen run model.bngl --method ode --t-end 100
bionetgen scan model.bngl --parameter k_on --min 0.01 --max 100 --n-points 50
bionetgen sensitivity model.bngl --parameter k_on --observable AB
bionetgen visualize model.bngl --type contact_map -o contact_map.graphml
bionetgen check model.bngl
bionetgen export model.bngl --format sbml --output model.xml
```

See [docs/cli_reference.md](cli_reference.md) for the full command reference.

## 12. Legacy Mode

If you need the old Perl-based behavior temporarily, set:

```bash
export BIONETGEN_USE_PERL=1
```

This is only for compatibility with old scripts.
