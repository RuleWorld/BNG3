# BioNetGen 3 Documentation

For the live implementation snapshot and current validation status, start with
[`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md). The convergence checklist is the
release-completion authority.

## Overview

BioNetGen 3 is a unified platform for rule-based modeling of biochemical systems. It combines three previously separate tools into a single Python package with a compiled C++ backend:

- **BioNetGen C++ Engine** — BNGL parser, network generator, ODE/SSA simulators
- **NFSim** — Network-free stochastic simulator for large/infinite state spaces
- **Python Interface** — High-level API, CLI, plotting, and SBML atomizer

## Installation

```bash
pip install bionetgen
```

No Perl runtime required. No subprocess calls. Everything runs in-process.

### Requirements

- Python 3.9+
- NumPy 1.20+
- A C++17 compiler (only for building from source)

### From Source

```bash
git clone <repo-url>
cd BNG3
pip install -e .
```

## Quick Start

```python
import bionetgen

# Load a BNGL model
model = bionetgen.load("model.bngl")

# Inspect model components
print(f"Parameters: {len(model.parameters)}")
print(f"Rules: {len(model.reaction_rules)}")
print(f"Species: {len(model.seed_species)}")

# Run ODE simulation
result = model.simulate(method="ode", t_end=100, n_steps=200)

# Plot observables
result.plot()

# Get as pandas DataFrame
df = result.to_dataframe()
```

## Table of Contents

- [User Guide](user_guide.md) — Getting started, tutorials, examples
- [API Reference](api_reference.md) — Complete Python API documentation
- [CLI Reference](cli_reference.md) — Command-line interface
- [Migration Guide](migration_guide.md) — Migrating from PyBioNetGen 1.x/2.x
- [Architecture](architecture.md) — Internal design and C++ backend
- [Contributing](contributing.md) — Development setup and guidelines
