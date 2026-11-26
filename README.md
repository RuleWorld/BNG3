# BioNetGen 3

[![CI](https://github.com/RuleWorld/BNG3/actions/workflows/ci.yml/badge.svg)](https://github.com/RuleWorld/BNG3/actions/workflows/ci.yml)
[![Cross-tool parity](https://github.com/RuleWorld/BNG3/actions/workflows/parity.yml/badge.svg)](https://github.com/RuleWorld/BNG3/actions/workflows/parity.yml)
[![Pre-release](https://img.shields.io/github/v/release/RuleWorld/BNG3?include_prereleases&label=pre-release)](https://github.com/RuleWorld/BNG3/releases/tag/v3.0.0a1)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**BioNetGen 3 (BNG3)** is a unified, Python-first C++ platform for rule-based modeling and simulation of biochemical reaction systems. It is built for systems biologists, computational modelers, and tool developers who write models in the BioNetGen Language (BNGL) or import kinetic models from SBML and want in-process network generation, ODE/SSA/PLA/PSA simulation, network-free simulation, parameter scans, sensitivity analysis, and model export without requiring Perl.

> **Maturity & distribution status:** The latest published release is the **`v3.0.0a1` alpha pre-release** on [GitHub Releases](https://github.com/RuleWorld/BNG3/releases/tag/v3.0.0a1) (commit `8482215c`). BNG3 is **not yet published on PyPI**: running `pip install bionetgen` today resolves to legacy PyBioNetGen `0.8.7`. See [Installation](#installation) below for verified BNG3 install commands.

## How BNG3 Relates to BNG2, PyBioNetGen, and NFsim

BioNetGen 3 consolidates three historically separate RuleWorld projects into one C++/Python codebase ([maintainer decisions](docs/DECISIONS.md)):

- **BNG2 (`RuleWorld/bionetgen`):** The classic Perl + `run_network` BioNetGen implementation. BNG3 replaces the Perl parser, network generator, and action dispatcher with an in-process C++17 engine while validating network and action semantics against pinned BNG2.
- **PyBioNetGen (`RuleWorld/PyBioNetGen`):** The legacy Python wrapper around BNG2 (`bionetgen<3` on PyPI). BNG3 adopts the same `bionetgen` package name at version `3.x`, replaces subprocess orchestration with a native Python API (`bionetgen.load()`, `model.simulate()`, NumPy-backed `SimResult`), and retains scoped compatibility entry points for migration.
- **NFsim (`RuleWorld/NFsim`):** The rule-based network-free stochastic simulator. BNG3 ships both the embedded NFcore engine (plus a standalone `NFsim` binary in CLI archives) and the next-generation **NFnext** engine compiled directly from BNG3's semantic model.

## Installation

Choose the route that matches your workflow. Python `3.9`–`3.14` is supported for pre-built wheels; the default installation requires no Perl and no compiler.

### 1. Pre-built Python wheel (`v3.0.0a1` pre-release — recommended)

Download or install the matching wheel directly from the [`v3.0.0a1` GitHub Release](https://github.com/RuleWorld/BNG3/releases/tag/v3.0.0a1). Pre-built wheels are published for CPython **3.9, 3.10, 3.11, 3.12, 3.13, and 3.14** on:

| Platform | Wheel tag |
| --- | --- |
| Linux (x86_64, glibc >= 2.28) | `manylinux_2_27_x86_64.manylinux_2_28_x86_64` |
| macOS Apple Silicon (11.0+) | `macosx_11_0_arm64` |
| macOS Intel (11.0+) | `macosx_11_0_x86_64` |
| Windows (64-bit) | `win_amd64` |

*(Linux `aarch64`, `musllinux`, and 32-bit platforms do not have pre-built `v3.0.0a1` wheels; use the source install below.)*

Example for Python 3.12 on Linux x86_64 (replace `cp312-cp312` and the platform tag to match your interpreter):

```bash
python -m pip install \
  https://github.com/RuleWorld/BNG3/releases/download/v3.0.0a1/bionetgen-3.0.0a1-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
bionetgen --version
```

Example for Python 3.12 on macOS Apple Silicon:

```bash
python -m pip install \
  https://github.com/RuleWorld/BNG3/releases/download/v3.0.0a1/bionetgen-3.0.0a1-cp312-cp312-macosx_11_0_arm64.whl
bionetgen --version
```

> **Staying on PyBioNetGen vs. PyPI availability:** `pip install bionetgen` from PyPI currently installs legacy PyBioNetGen `0.8.7` (not BNG3). Pin `bionetgen<3` to stay on PyBioNetGen explicitly. Once BNG3 wheels are published to PyPI, pre-releases will be installable via `pip install --pre "bionetgen>=3.0.0a1"`.

**Optional extras** (append `[extra]` when installing from a local wheel path or source checkout, e.g. `pip install "bionetgen[plotting] @ <wheel-url>"`):

- `plotting` — `pandas` and `matplotlib` for `result.to_dataframe()`, `result.plot()`, and `bionetgen plot`
- `notebook` — `ipykernel` and `matplotlib` for running templates created by `bionetgen notebook`
- `jax` — `jax` and `jaxlib` for optional JAX CPU ODE/SSA backends
- `full` — adds `python-libsbml`, `sympy`, `networkx`, `seaborn`, `pyyaml`, `lxml`, `xmltodict`, and legacy CLI/Atomizer dependencies for SBML import (`from_sbml` / `bionetgen atomize`) and SymPy ODE export
- `legacy` — `cement`, `colorlog`, `pyparsing`, `pylru` for legacy PyBioNetGen compatibility modules

### 2. Standalone C++ CLI binaries (`v3.0.0a1` — no Python required)

Pre-built archives containing `bng_cpp` and `NFsim` are attached to the [`v3.0.0a1` GitHub Release](https://github.com/RuleWorld/BNG3/releases/tag/v3.0.0a1) for `linux-x86_64`, `macos-arm64`, `macos-x86_64`, and `windows-x86_64`:

```bash
curl -LO https://github.com/RuleWorld/BNG3/releases/download/v3.0.0a1/bionetgen-macos-arm64.tar.gz
tar xzf bionetgen-macos-arm64.tar.gz
./bionetgen-macos-arm64/bng_cpp --check binding.bngl
```

### 3. From source (`main` — includes post-`v3.0.0a1` changes)

Requires Python 3.9+, Git, CMake >= 3.15, and a C++17 compiler (GCC 12+, Clang 15+, or MSVC 2022+).

```bash
git clone https://github.com/RuleWorld/BNG3.git
cd BNG3
python -m pip install .
```

For contributors developing BNG3 locally (editable install and standalone C++ tests), see [docs/contributing.md](docs/contributing.md).

## Quickstart

Save this self-contained reversible binding model as `binding.bngl` in any working directory (no source checkout required):

```bngl
begin model
begin parameters
  k_on  0.01
  k_off 0.1
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 100
  B(a) 100
end seed species
begin observables
  Molecules AB     A(b!1).B(a!1)
  Molecules A_free A(b)
end observables
begin reaction rules
  bind: A(b) + B(a) <-> A(b!1).B(a!1) k_on, k_off
end reaction rules
end model
```

### CLI

```bash
bionetgen check binding.bngl
bionetgen run binding.bngl --method ode --t-end 10 --n-steps 20 --output binding.tsv
```

Expected output from `bionetgen check binding.bngl`:

```text
OK: .../binding.bngl
  Parameters:      2
  Molecule types:  2
  Seed species:    2
  Reaction rules:  1
  Observables:     2
  Actions:         0
```

`binding.tsv` contains 21 tab-separated rows (`time`, `AB`, `A_free`) starting at `AB = 0, A_free = 100` and approaching equilibrium (`AB ≈ 72.93, A_free ≈ 27.07` at `t = 10`).

### Python API

```python
import bionetgen

model = bionetgen.load("binding.bngl")
result = model.simulate(method="ode", t_end=10.0, n_steps=20)

print(f"backend={result.backend}, points={len(result.time)}")
print(f"AB(0)={result.observables['AB'][0]:.2f}, AB(10)={result.observables['AB'][-1]:.2f}")
```

Expected output:

```text
backend=native, points=21
AB(0)=0.00, AB(10)=72.93
```

With the `plotting` extra installed, call `result.plot()` or `result.to_dataframe()`. To run the same model network-free with NFnext, pass `method="nf", seed=42`.

## Documentation

| Topic | Document |
| --- | --- |
| Full documentation hub | [Documentation Index](docs/index.md) |
| Step-by-step tutorials | [User Guide](docs/user_guide.md) |
| What BNG3 supports & boundaries | [Capability Guide](docs/capabilities.md) |
| Moving from BNG2 or PyBioNetGen | [Migration Guide](docs/migration_guide.md) · [Detailed Change Reference](docs/bng2_migration_reference.md) |
| Choosing NFsim vs. NFnext | [Network-Free Simulation Guide](docs/network_free_simulation.md) |
| Command-line interface | [CLI Reference](docs/cli_reference.md) |
| Python classes & functions | [Python API Reference](docs/api_reference.md) |
| SBML import boundaries | [SBML Atomizer Limitations](docs/ATOMIZER_LIMITATIONS.md) |
| Architecture & contributors | [Architecture](docs/architecture.md) · [Contributing](docs/contributing.md) |

## What BNG3 Includes

- **BNGL parser and semantic compiler (`cpp/parser`, `cpp/compile`):** ANTLR4 C++ parser, symbol resolution, typed rate laws, rule modifiers, physical units ([docs/BNG3_UNITS.md](docs/BNG3_UNITS.md)), and fail-closed capability checks.
- **Finite-network engine (`cpp/engine`):** In-process C++ network generation (`bng_core` + single bundled `nauty`), SUNDIALS CVODE ODE solver, Gillespie SSA (single-trajectory and CPU/GPU batched ensembles), PLA, PSA, optional BNGsim adapter, and optional JAX CPU backends.
- **Network-free engines (`cpp/nfnext`, `cpp/nfsim`):** NFnext (default for Python `method="nf"`) compiled directly from `CompiledModel → NFIR`, plus embedded NFcore (`method="nfcore"` and BNGL `simulate_nf` actions). `BioNetGenModel.simulate_nfnext_gpu()` exposes an explicit, fail-closed GPU batch route (single-site unary state-change mode in `v3.0.0a1`; extended with `mode="graph"` on `main` for `TIER_NF`). It does not imply general NFnext GPU support across every BNGL construct; `bionetgen.gpu_backend_capabilities()` reports compiled routes and physical-device availability.
- **Analysis, visualization, and interchange:** 1D/2D parameter scans, local sensitivity analysis, programmatic `ModelBuilder` and runtime model topology edits, CRN JSON export (`to_crn()`), deterministic BNGIR v0.2 (`to_bngir()` / `semantic_equal()`), modern SBML Atomizer (`from_sbml()`), and exports to BNGL, `.net`, BNG-XML, SBML, SBML Multi, MATLAB, LaTeX, and GraphML.

## Validation, Benchmarks, and Maintainer Records

- **Scope & release policy:** [Capability Union Inventory (997 rows)](docs/CAPABILITY_UNION_INVENTORY.md) · [Machine-Readable Capability Matrix](provenance/capability-matrix.yml) · [Maintainer Decisions](docs/DECISIONS.md)
- **Live evidence & harness:** [Current Progress](docs/CURRENT_PROGRESS.md) · [CI Parity Gates](docs/CI_PARITY.md) · [Validation Harness](tests/validation/README.md) · [Convergence Checklist](docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md)
- **Benchmarks:** See [benchmarks/README.md](benchmarks/README.md) for CPU parse, network-generation, ODE, SSA, and Atomizer benchmark scripts and methodology, and [docs/GPU_BATCH_SSA_EVALUATION.md](docs/GPU_BATCH_SSA_EVALUATION.md) for hardware-attributed Metal GPU vs. CPU batched-SSA tables (e.g., `egfr_net` 10,000-trajectory batch on Apple M5 Pro Metal GPU vs. 15-core CPU).
- **Historical reports:** Archived under [docs/archive/reports/](docs/archive/reports/).

## Reporting Problems

Open an issue at [RuleWorld/BNG3/issues](https://github.com/RuleWorld/BNG3/issues). Include the output of `bionetgen info --detail` (or `bionetgen --version` and your commit/wheel filename), platform and Python version, a minimal `.bngl` or `.xml` reproducer, any random seed and backend selector used, and expected vs. observed output. See [docs/contributing.md#reporting-issues-and-disagreements](docs/contributing.md#reporting-issues-and-disagreements).

## Citation

If you use BioNetGen 3 in published work, please cite the foundational BioNetGen publications (and NFsim or Atomizer when using those capabilities):

- **BioNetGen 2.2:** Harris, L. A., Hogg, J. S., Tapia, J., Sekar, J. A. P., Gupta, S., Korsunsky, I., Arora, A., Barua, D., Sheehan, R. P., & Faeder, J. R. (2016). BioNetGen 2.2: advances in rule-based modeling. *Bioinformatics*, 32(21), 3366–3368. <https://doi.org/10.1093/bioinformatics/btw469>
- **BioNetGen methodology:** Faeder, J. R., Blinov, M. L., & Hlavacek, W. S. (2009). Rule-based modeling of biochemical systems with BioNetGen. *Methods in Molecular Biology*, 500, 113–167. <https://doi.org/10.1007/978-1-59745-525-1_5>
- **Original BioNetGen:** Blinov, M. L., Faeder, J. R., Goldstein, B., & Hlavacek, W. S. (2004). BioNetGen: software for rule-based modeling of signal transduction based on the interactions of molecular domains. *Bioinformatics*, 20(17), 3289–3291. <https://doi.org/10.1093/bioinformatics/bth378>
- **NFsim (network-free simulation):** Sneddon, M. W., Faeder, J. R., & Emonet, T. (2011). Efficient modeling, simulation and coarse-graining of biological complexity with NFsim. *Nature Methods*, 8(2), 177–183. <https://doi.org/10.1038/nmeth.1546>
- **Atomizer (SBML to BNGL):** Tapia, J.-J., & Faeder, J. R. (2013). The Atomizer: extracting implicit molecular structure from reaction network models. *Proceedings of ACM BCB '13*, 1–10. <https://doi.org/10.1145/2506583.2506688>

Also cite the specific BioNetGen 3 software release tag or commit SHA used (for example, `RuleWorld/BNG3 v3.0.0a1`).

## License

MIT License. See [LICENSE](LICENSE).
