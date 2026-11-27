# User Guide

This guide walks through the BioNetGen 3 (BNG3) workflow: installing BNG3, loading or building BNGL models, inspecting and editing model components, running finite-network and network-free simulations, scanning parameters, computing sensitivities, exporting models, and importing SBML.

For support boundaries see the [Capability Guide](capabilities.md) (and traceable [Capability Union Inventory](CAPABILITY_UNION_INVENTORY.md)); for moving from BNG2 or PyBioNetGen see the [Migration Guide](migration_guide.md); for network-free engine choices see the [Network-Free Simulation Guide](network_free_simulation.md). Final policy is in [DECISIONS.md](DECISIONS.md) and live qualification records are in [CURRENT_PROGRESS.md](CURRENT_PROGRESS.md).

## 1. Install

> **Important:** The latest published BNG3 release is the **`v3.0.0a1`** pre-release on [GitHub Releases](https://github.com/RuleWorld/BNG3/releases/tag/v3.0.0a1). Running `pip install bionetgen` from PyPI currently installs legacy PyBioNetGen `0.8.7`, not BNG3.

Follow the verified platform wheel, standalone CLI archive, or source-checkout instructions in [README.md#installation](../README.md#installation). Confirm you have BNG3 active with:

```bash
bionetgen --version
```

Optional extras (`plotting`, `notebook`, `jax`, `full`, `legacy`) are listed in [README.md#installation](../README.md#installation).

## 2. Load Models

Save the self-contained `binding.bngl` model from [README.md#quickstart](../README.md#quickstart) (or use any `.bngl` file):

```python
import bionetgen

model = bionetgen.load("binding.bngl")
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

## 3. Inspect and Edit Model Components

The `BioNetGenModel` object exposes the parsed BNGL AST as Python objects:

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

Update parameter values in place with `model.set_parameter("k_on", 0.05)` (which re-evaluates dependent expressions and clears stale cached networks). You can also edit model topology atomically via `add_parameter`, `remove_parameter`, `add_compartment`, `add_molecule_type`, `add_seed_species`, `set_seed_species_amount`, `add_observable`, `add_reaction_rule`, and `add_function`—see the [API Reference](api_reference.md#class-bionetgenmodel).

## 4. Simulate

### ODE (Default)

```python
result = model.simulate(method="ode", t_end=10.0, n_steps=20)
```

### SSA (Finite-Network Stochastic)

```python
result = model.simulate(method="ssa", t_end=10.0, n_steps=20, seed=42)
```

### Network-Free (`nf` / `nfcore`)

```python
# Default Python network-free engine: NFnext (result.backend == "nfnext")
result = model.simulate(method="nf", t_end=10.0, n_steps=20, seed=42)

# Explicit embedded NFcore (result.backend == "nfsim"; supports equilibrate / traversal_limit)
result_nfcore = model.simulate(
    method="nfcore", t_end=10.0, n_steps=20, seed=42, traversal_limit=3
)
```

See [Network-Free Simulation (NFsim & NFnext)](network_free_simulation.md) for the complete engine decision table, BNGL action behavior, and seed comparison rules.

Network-based methods (`ode`, `ssa`, `pla`, `psa`) automatically generate the reaction network if needed. Pass `continue_simulation=True` to continue a native ODE/SSA or hybrid NF trajectory from the previous endpoint (optionally after changing a parameter with `set_parameter()`), and call `model.reset_simulation()` to discard continuation state.

### Batch SSA and GPU Backends

Run batched direct SSA ensembles through `model.simulate(method="ssa", batch_size=..., batch_gpu_backend=...)` or `model.simulate_batch_ssa(...)`, and inspect compiled/available routes via `bionetgen.gpu_backend_capabilities()`, `bionetgen.gpu_backends()`, and `bionetgen.default_gpu_backend()`.

- **Metal (Apple Silicon)** and **CUDA (NVIDIA)**: both backends implement finite-network batch SSA (`simulate_batch_ssa` / `simulate(method="ssa", batch_size=...)`) and network-free GPU SSA (`model.simulate_nfnext_gpu(..., backend=...)`), reported via `bionetgen.gpu_backend_capabilities()`.
- **Network-free GPU boundaries (fail-closed)**: in **`v3.0.0a1`**, `simulate_nfnext_gpu` covers single-site unary state-change models (`mode="unary"`). On **post-`v3.0.0a1` `main`**, `mode="graph"` additionally covers general graph SSA with binding/unbinding, molecule creation/destruction, complex deletion, dynamic rate functions, `Molecules`/`Species` observables, `TotalRate`, reactant `include_reactants`/`exclude_reactants` filters, and static energy-folded `Arrhenius` patterns across `TIER_NF` (PR `#1069`). Unsupported constructs (compartments, events, delays, population maps, barrier patterns / non-folded energy expressions, product filters, unbonded `SameComplex` constraints, multi-copy local scoping, or an unavailable/uncompiled device) raise an explicit refusal rather than approximating or silently falling back. Metal and CUDA require separate real-device qualification receipts (`scripts/ci/record_issue474_release.py`).

### Seeds and Reproducibility

Stochastic methods (`ssa`, `nf`, `nfcore`, `nfnext`) are reproducible for a given nonzero seed: the same model, same engine, and same nonzero seed produce the same trajectory, and the batch SSA pools (`_bionetgen_cpp.simulate_batch_ssa_cpu` and GPU batch kernels) derive each trajectory *b*'s seed deterministically from `(base_seed, b)` via SplitMix64 (`batchTrajectorySeed` in `cpp/engine/BatchSsa.hpp`), so adjacent base seeds decorrelate while one base seed determines a whole batch independently of worker count.

**`seed=0` is the exception and is not reproducible.** It means "use the system default", i.e. a fresh `std::random_device` draw, so two runs with `seed=0` differ. This is BNG2-compatible and is kept deliberately; it is not an error and it will not become a refusal. If you need reproducibility, pass an explicit non-zero seed. Do not assert reproducibility, or quote reproducibility as evidence, from a run that used `seed=0`.

`seed` applies to stochastic methods (`ssa`, `nf`, `nfcore`, `nfnext`) and random SBML event assignments in `ode`. `simulate_pla` and `simulate_psa` do not take a seed; `Model.simulate` accepts `seed` for API uniformity. The equivalents elsewhere are `--seed` on `bionetgen run` and the `seed` argument of `simulate_ssa`/`simulate_nf` BNGL actions; all of them use the same `0 = system default` rule.

## 5. Work With Results

```python
result = model.simulate(method="ode", t_end=10.0, n_steps=20)

print(result.backend)
print(result.time)
print(result.observable_names)
print(result.observables["AB"])

# Requires the plotting extra (pandas + matplotlib):
df = result.to_dataframe()
fig, ax = result.plot()
```

In notebooks, `model` and `result` render as HTML automatically via `_repr_html_()`.

## 6. Scan Parameters

### One-Dimensional Scan

```python
import numpy as np

scan = model.parameter_scan(
    parameter="k_on",
    values=np.logspace(-3, -1, 10),
    method="ode",
    t_end=10.0,
)

print(scan.final("AB"))
print(scan.at_time(5.0, "AB"))
frame = scan.to_dataframe()  # requires plotting extra
```

### Two-Dimensional Scan

```python
scan2d = model.parameter_scan_2d(
    parameter1="k_on",
    values1=np.logspace(-3, -1, 5),
    parameter2="k_off",
    values2=np.logspace(-2, 0, 5),
    method="ode",
    t_end=10.0,
)

scan2d.plot_heatmap("AB")  # requires plotting extra
```

## 7. Sensitivity Analysis

```python
sens = model.sensitivity_analysis(
    parameters=["k_on", "k_off"],
    observables=["AB"],
    method="ode",
    t_end=10.0,
    delta=0.01,
)

print(sens.matrix)
print(sens.rank("AB"))
```

## 8. Export Models, CRNs, and BNGIR

```python
model.write_xml("binding.xml")
model.write_bngl("binding_copy.bngl")
model.write_net("binding.net")
model.write_sbml("binding.sbml")
model.write_matlab("binding.m")
model.write_latex("binding.tex")
model.contact_map("contact_map.graphml")

# Portable Chemical Reaction Network JSON (species, complexes, reactions, stoichiometric matrix)
model.write_crn("binding_crn.json")

# Deterministic BNGIR v0.2 JSON & exact process semantic equality
ir_json = model.to_bngir()
```

Graph exports return the serialized text when no path is supplied:

```python
graphml = model.contact_map()
```

## 9. Import SBML

Requires the `full` extra (`python-libsbml`). See [ATOMIZER_LIMITATIONS.md](ATOMIZER_LIMITATIONS.md) for the exact scope record of SBML constructs supported vs. refused.

```python
import bionetgen

model = bionetgen.from_sbml("binding.sbml", atomize=True)
bngl_text = bionetgen.sbml_to_bngl("binding.sbml", atomize=True)
```

## 10. Build Models Programmatically

```python
from bionetgen.builder import ModelBuilder

builder = ModelBuilder("MyModel")
builder.add_parameter("k_on", 0.01)
builder.add_parameter("k_off", 0.1)
builder.add_molecule_type("A(b)")
builder.add_molecule_type("B(a)")
builder.add_seed_species("A(b)", 100)
builder.add_seed_species("B(a)", 100)
builder.add_observable("Molecules", "AB", "A(b!1).B(a!1)")
builder.add_rule("A(b) + B(a) -> A(b!1).B(a!1)", "k_on")
builder.add_rule("A(b!1).B(a!1) -> A(b) + B(a)", "k_off")

model = builder.build()
print(builder.to_bngl())
```

## 11. CLI

```bash
bionetgen check binding.bngl
bionetgen run binding.bngl --method ode --t-end 10 --n-steps 20 --output binding.tsv
bionetgen scan binding.bngl --parameter k_on --min 0.001 --max 0.1 --n-points 10
bionetgen sensitivity binding.bngl --parameter k_on --observable AB
bionetgen visualize binding.bngl --type contact_map -o contact_map.graphml
bionetgen export binding.bngl --format sbml --output binding.xml
```

See [CLI Reference](cli_reference.md) for all 12 `bionetgen` subcommands and the standalone `bng_cpp` / `NFsim` binaries.

## 12. Legacy Mode

If you need the legacy Perl-based behavior temporarily for Python API transition scripts, set:

```bash
export BIONETGEN_USE_PERL=1
export BNGPATH=/path/to/bng2
```

This applies to `bionetgen.run(path)` and `bionetgen.load(path).execute()` only (`bionetgen run MODEL` CLI is unavailable in this mode). See the [Migration Guide](migration_guide.md).
