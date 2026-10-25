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

# Full validation corpus: independent .net references plus action contracts
python scripts/validate.py --bng-cpp build/cpp/bng_cpp --strict-references \
  --validation-manifest tests/validation/validation_manifest.json
python scripts/validate_actions.py --bng-cpp build/cpp/bng_cpp
```

### Fast CI feedback

CI runs lint, workflow structure, and harness contracts before native builds.
Integration and selector collection then gate the full 3 OS × 6 Python matrix.
A failing PR matrix cancels its remaining siblings; pytest and CTest stop at
first failure, and CTest rejects an empty selection. Results uploaded with
`always()` retain the executed prefix; an aborted run is not full-suite evidence.

New pushes cancel superseded runs of the same PR across CI, parity, SBML,
Lean, CodeQL, and formatting workflows. Main, scheduled, and manual runs each
use their run ID, so dispatching a qualification run preserves it even when
another run targets the same revision. Dispatch a workflow at a pinned ref
when evidence for an older revision is needed.

Run the build-free framework checks with their small dependency set:

```bash
python -m pip install pytest numpy pyyaml
python -m pytest tests/test_ci_contract.py tests/test_ci_fast_feedback.py \
  tests/test_workflow_guard_selftests.py -q --maxfail=1
python -m pytest tests/test_workflow_contract.py -q --maxfail=1 \
  -k 'not test_workflow_pytest_selector_collects_at_least_one_test'
```

Full selector reachability runs in the installed-package integration job,
where native and optional collection dependencies exist. Each collection
subprocess has a 120-second budget. Guard self-tests inject duplicate YAML
keys, invalid dependencies, gate bypasses, empty selections, collection errors,
and timeouts. These validate the testing framework, not scientific behavior.

Dependency downloads are cached; native binaries still build from the current
checkout. Python 3.9 pins libSBML 5.21.1 wheels on all platforms because 5.21.2
has no Python 3.9 wheels. Binary-only installation fails promptly if a wheel
is unavailable instead of starting a long source build.

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
