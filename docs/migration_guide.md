# Migration Guide

## Migrating from PyBioNetGen 1.x / 2.x

BioNetGen 3 replaces the subprocess-based architecture with in-process C++ execution. Most user-facing APIs have been redesigned for clarity.

### Key Changes

| PyBioNetGen 2.x | BioNetGen 3 | Notes |
|------------------|-------------|-------|
| `import bionetgen; bionetgen.run(path)` | `import bionetgen; bionetgen.run(path)` | Same name, different return type |
| `bngmodel(path)` | `bionetgen.load(path)` | New name, returns `BioNetGenModel` |
| `model.actions` dict | `model.actions` list of `Action` | Structured objects |
| Requires Perl + BNG2.pl | No external dependencies | C++ engine built-in |
| `subprocess.run(["perl", ...])` | Direct C++ call | 10-100x faster startup |
| `BNGCLI(path).run()` | `model.execute()` | No subprocess |
| CSimulator (ctypes) | C++ OdeIntegrator | CVODE in-process |
| libRoadRunner optional | Still available via `libroadrunner` | Unchanged |

### Loading Models

```python
# Before (PyBioNetGen 2.x)
from bionetgen import bngmodel
model = bngmodel("model.bngl")
print(model.parameters)  # OrderedDict from XML

# After (BioNetGen 3)
import bionetgen
model = bionetgen.load("model.bngl")
print(model.parameters)  # List[Parameter] from C++ AST
```

### Running Simulations

```python
# Before (PyBioNetGen 2.x)
from bionetgen import run
run("model.bngl")  # writes .gdat file, returns BNGResult

# After (BioNetGen 3)
import bionetgen
result = bionetgen.run("model.bngl", method="ode", t_end=100)
result.time          # numpy array
result.observables   # dict of numpy arrays
result.plot()        # matplotlib plot
```

### CLI Changes

```bash
# Before
bionetgen run model.bngl          # cement framework
bionetgen plot model.gdat

# After
bionetgen run model.bngl -m ode   # click framework
bionetgen check model.bngl        # new: syntax check
bionetgen export model.bngl -f sbml -o out.xml  # new: export
```

### Atomizer

The SBML atomizer is still available:

```python
# The atomizer module is unchanged
from bionetgen.atomizer import atomizeTool
```

### Backward Compatibility Mode

If you need the old Perl-based behavior temporarily:

```bash
export BIONETGEN_USE_PERL=1
export BNGPATH=/path/to/BNG2.pl/directory
```

This activates the legacy subprocess path. Set this while migrating scripts that depend on exact file output formats.

### What's Removed

- **Cement CLI framework** — replaced by Click
- **CSimulator** — replaced by C++ OdeIntegrator (CVODE)
- **subprocess calls to Perl** — replaced by in-process C++
- **Bundled BNG2.pl binaries** — no longer needed
- **XML parsing pipeline** — C++ parses BNGL directly
- **`bngmodel` class** — replaced by `BioNetGenModel`

### What's New

- **C++ backend** — all simulation runs in-process via compiled C++ engine (no Perl, no subprocess)
- **Direct simulation** — call `model.simulate()` to run ODE/SSA/NF without writing intermediate files
- **Network generation API** — `model.generate_network()` expands rules into a reaction network programmatically
- **In-process parsing** — ANTLR4-based BNGL parser, no file I/O for model loading
- **Type-safe model access** — proper Python objects, not dicts
- **Network-free simulation** — `method="nf"` without subprocess
- **NumPy-native results** — arrays instead of file parsing
- **Syntax checking** — `bionetgen check` validates without running
- **Format export** — direct SBML/MATLAB/LaTeX export from Python

### Network Generation API

```python
import bionetgen

model = bionetgen.load("model.bngl")

# Generate the reaction network (expand rules into species/reactions)
network = model.generate_network(max_iter=100, max_stoich={"A": 10})

print(network.species)     # List of generated species
print(network.reactions)   # List of generated reactions

# Simulate on the generated network
result = network.simulate(method="ode", t_end=50)
```
