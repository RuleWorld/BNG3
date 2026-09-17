# Contributing

Read [`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md) before using historical
handoff counts or branch names. The current pass batches implementation work
and performs verification at the end of the pass.

## Development Setup

### Prerequisites

- Python 3.9+
- CMake 3.14+
- C++17 compiler (GCC 12+, Clang 15+, MSVC 2022+)
- Git

### Clone and Build

```bash
git clone <repo-url>
cd BNG3

# Build C++ only (fast iteration on C++ code)
cmake -B build -DBUILD_PYTHON_BINDINGS=OFF -DBUILD_CLI=ON -DBUILD_TESTS=ON
cmake --build build -j$(nproc)

# Run C++ tests
ctest --test-dir build --output-on-failure

# Build Python package (editable install)
pip install -e . -v
```

### Running Tests

```bash
# C++ tests
cmake --build build --target test

# Python tests
pytest tests/python/ -v

# Validation (C++ vs reference .net files)
python scripts/validate.py
```

## Repository Structure

```
BNG3/
├── cpp/                 # All C++ source code
│   ├── ast/             # Model AST
│   ├── core/            # Graph operations
│   ├── engine/          # Simulators
│   ├── io/              # I/O writers
│   ├── parser/          # ANTLR4 parser
│   ├── actions/         # Action dispatch
│   ├── console/         # Interactive console
│   ├── nauty/           # Graph isomorphism
│   ├── nfsim/           # NFSim engine
│   └── bindings/        # pybind11 bindings
├── python/bionetgen/    # Python package
├── tests/
│   ├── cpp/             # Catch2 tests
│   ├── python/          # pytest tests
│   └── validation/      # Reference output files
├── docs/                # Documentation
├── models/              # Example models
└── legacy/              # Retained legacy code
```

## Adding a New I/O Writer

1. Create `cpp/io/MyWriter.hpp` and `cpp/io/MyWriter.cpp`
2. Add the `.cpp` file to `bng_engine` sources in `cpp/CMakeLists.txt`
3. Expose via pybind11 in `cpp/bindings/bind_io.cpp`
4. Add Python wrapper method in `python/bionetgen/model.py`
5. Add CLI subcommand option in `python/bionetgen/cli.py`
6. Write tests in `tests/python/test_cpp_backend.py`

## Adding a New Simulation Method

1. Implement in `cpp/engine/` (new class or extend OdeIntegrator)
2. Wire into `ActionDispatch.cpp` if callable from BNGL actions
3. Add pybind11 binding in `cpp/bindings/bind_engine.cpp`
4. Add `method` case in `BioNetGenModel.simulate()` in `model.py`
5. Add tests with known analytical solutions

## Code Style

### C++
- C++17 standard
- Namespaces: `bng::ast`, `bng::engine`, `bng::io`, `bng::actions`, `bng::parser`
- Headers: `#pragma once`
- Naming: `PascalCase` for classes, `camelCase` for methods/variables

### Python
- PEP 8
- Type hints on all public functions
- Docstrings: NumPy style

## Pull Request Process

1. Create a feature branch from `main`
2. Ensure all C++ and Python tests pass
3. Run validation suite if touching parser/engine code
4. Update documentation for user-facing changes
5. Submit PR with description of what changed and why
