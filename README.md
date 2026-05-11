# BioNetGen 3

BioNetGen 3 is a unified rule-based modeling platform for biochemical reaction networks. It combines the BioNetGen language (BNGL) parser, a high-performance C++ simulation engine, the NFSim network-free simulator, and a Python interface (PyBioNetGen) into a single installable package. The platform supports deterministic (ODE), stochastic (SSA), and network-free simulation of rule-based models without requiring external Perl or subprocess dependencies.

## Installation

```bash
pip install bionetgen
```

### From source (requires CMake)

```bash
git clone <repo-url>
cd BNG3
pip install -e .
```

This will invoke scikit-build-core to compile the C++ backend automatically.

### Building the C++ engine only

```bash
cmake -B build -DBUILD_PYTHON_BINDINGS=OFF -DBUILD_CLI=ON
cmake --build build
./build/cpp/bng_cpp model.bngl
```

## Quick Start

```python
import bionetgen

# Load a model from a BNGL file
model = bionetgen.load("model.bngl")

# Simulate using ODE integration
result = model.simulate(method="ode", t_end=100, n_steps=200)

# Plot the results
result.plot()

# Access raw data as NumPy arrays
print(result.time)
print(result.observables)
df = result.to_dataframe()
```

## CLI

```bash
# Run a simulation
bionetgen run model.bngl --method ode --t-end 100

# Check syntax
bionetgen check model.bngl

# Export to other formats
bionetgen export model.bngl --format sbml --output model.xml
```

## Architecture

- **C++ Backend** (`cpp/`): ANTLR4 parser, AST, network generation, ODE/SSA simulation, NFSim engine
- **Python Frontend** (`python/bionetgen/`): High-level API, CLI, plotting, atomizer
- **pybind11 Bindings** (`cpp/bindings/`): Zero-copy bridge between C++ and Python

## Simulation Methods

- `"ode"` -- Deterministic ODE integration (CVODE/SUNDIALS)
- `"ssa"` -- Stochastic simulation algorithm
- `"nf"` -- Network-free simulation (NFSim engine)

## Development Setup

```bash
# Clone the repository
git clone <repo-url>
cd BNG3

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Build C++ with debug symbols
cmake -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
ctest --test-dir build
```

## Documentation

See [docs/](docs/) for detailed documentation, including:

- [Migration Guide](docs/migration_guide.md) -- upgrading from PyBioNetGen 1.x/2.x

## License

MIT -- see [LICENSE](LICENSE) for details.
