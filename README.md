# BioNetGen 3

BioNetGen 3 is a Python-first, in-process rule-based modeling platform for biochemical reaction systems. It parses BNGL directly in C++, simulates with the bundled backend, and exposes models, results, scans, and exports as ordinary Python objects.

The repository is under active convergence work. The live implementation and
verification state is recorded in [`docs/CURRENT_PROGRESS.md`](docs/CURRENT_PROGRESS.md);
the convergence checklist remains the authority for release completion.

## What Is Novel In BNG3

BNG3 is a redesign of the BioNetGen user and execution layers around a
Python-first, in-process architecture. It is more than a new command name:
the semantic model, graph algorithms, network-free engine, numerical solvers,
analysis APIs, and interoperability layers are being separated into explicit
components with typed contracts between them. BNG2 remains an important
compatibility and semantic reference while BNG3 converges on this architecture.

| Concern | BNG2 / legacy workflow | BNG3 direction |
| --- | --- | --- |
| User interface | Perl actions, generated files, and PyBioNetGen subprocess orchestration | Python objects, a synchronous API, and a unified CLI |
| Model representation | Parser and action state coupled to legacy execution paths | C++ AST plus a reusable semantic compile stage with typed symbols and diagnostics |
| Network simulation | External or file-oriented solver workflows | In-process C++ network generation, ODE, SSA, and result objects backed by NumPy |
| Network-free simulation | NFSim integration commonly treated as a separate executable path | Direct NFcore construction from the canonical AST, with explicit compatibility fallbacks and fail-closed unsupported cases |
| Rule matching and graphs | Mature legacy graph machinery exposed through older seams | Shared BNGcore graph operations and explicit pattern-lowering boundaries for each backend |
| Analysis | Manual output-file parsing and repeated command invocation | First-class scans, sensitivities, observable access, data frames, and graph exports |
| Interoperability | XML and action-based bridges | Versioned BNGIR, typed import/export boundaries, and structured SBML Multi metadata |
| Validation | Distributed regression scripts and implicit assumptions | Architecture contracts, provenance manifests, parity gates, and an auditable convergence checklist |

The implementation is intentionally staged. The new architecture does not
claim that every BNG2 feature has parity yet; unsupported or unproven paths
are reported explicitly rather than silently changing model semantics. See
[`docs/CURRENT_PROGRESS.md`](docs/CURRENT_PROGRESS.md) for the live evidence
and [`docs/migration_guide.md`](docs/migration_guide.md) for API changes.

## The Individual BNG3 Parts

- **Python API and CLI** — `bionetgen.load()`, model/result objects, scans,
  sensitivities, visualization, and command-line workflows provide the primary
  user surface.
- **Parser and semantic compiler** — the C++ BNGL parser produces the AST;
  symbol resolution, typed expressions, capabilities, and pattern descriptors
  form the reusable semantic boundary between source text and execution.
- **BNGcore graph layer** — canonicalization, graph matching, pattern
  lowering, and graph exports are shared by network and network-free paths.
- **Network engine** — native reaction-network generation, ODE, SSA, CVODE,
  isolated batch execution, and file/API exporters are available through the
  in-process C++ backend.
- **NFcore2 / NFSim path** — the direct network-free adapter maps canonical
  model constructs into NFcore, including molecule mappings, observables,
  functions, energy metadata, and rule execution semantics.
- **NFnext** — the next-generation surface defines NFIR, rule families,
  dependency scheduling, generic matching, transformations, validation,
  caching, replay, and batched trajectories as independently testable seams.
- **Atomizer and SBML Multi** — SBML import and structured Multi metadata are
  handled in the modern Python atomizer, with unsupported or ambiguous forms
  kept explicit until independent execution evidence exists.
- **Analysis and visualization** — results expose NumPy/data-frame access,
  parameter scans, local sensitivities, contact/regulatory/rule-influence
  graphs, and notebook-friendly representations.
- **Compatibility and provenance** — legacy APIs and XML routes remain as
  scoped transition aids, while schemas, architecture-contract manifests,
  validation inventories, and documentation record what is implemented,
  qualified, or still future work.

The architecture and data flow are described in
[`docs/architecture.md`](docs/architecture.md). The release boundary is
tracked separately in
[`docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md`](docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md).

## Install

```bash
pip install bionetgen
```

No Perl runtime is required for the default workflow.

## Quickstart

```python
import bionetgen

model = bionetgen.load("models/simple_system.bngl")
result = model.simulate(method="ode", t_end=100)
result.plot()
```

## Highlights

- C++ backend for parsing, network generation, ODE simulation, SSA, NFSim, PLA, and PSA.
- Parameter scanning in 1D and 2D, with serial or isolated parallel execution.
- Local sensitivity analysis with finite differences.
- Jupyter-friendly HTML reprs for models, simulation results, and scan results.
- SBML import through the atomizer bridge.
- Programmatic model construction without hand-writing BNGL.
- Direct export to BNGL, XML, SBML, MATLAB, LaTeX, and graph visualizations.

## Migration From PyBioNetGen

If you are upgrading from PyBioNetGen or BNG2, start with [docs/migration_guide.md](docs/migration_guide.md).

Key differences:

- `bionetgen.load()` replaces `bngmodel()`.
- `model.simulate()` replaces subprocess-based `bionetgen.run()` workflows.
- Results are NumPy-backed objects instead of `.gdat` files.
- Parameter scans and sensitivity analysis are first-class APIs.
- Perl, cement, distutils, pyparsing, and pylru are no longer required for the default path.

## Performance

Benchmark data is generated by `benchmarks/run_benchmarks.py` and archived by nightly CI.

| Model | C++ Parse | C++ Generate | C++ Simulate | Perl Total | 100-pt Scan |
| --- | --- | --- | --- | --- | --- |
| simple_system | see benchmark artifact | see benchmark artifact | see benchmark artifact | see benchmark artifact | see benchmark artifact |
| egfr_net | see benchmark artifact | see benchmark artifact | see benchmark artifact | see benchmark artifact | see benchmark artifact |
| fceri_ji | see benchmark artifact | see benchmark artifact | see benchmark artifact | see benchmark artifact | see benchmark artifact |

## API Overview

The primary object is `model`.

| Method | Purpose |
| --- | --- |
| `model.simulate(...)` | Run ODE, SSA, NFSim, PLA, or PSA simulation |
| `model.generate_network(...)` | Expand the rule set into a reaction network |
| `model.parameter_scan(...)` | Scan one parameter across a value range |
| `model.parameter_scan_2d(...)` | Scan two parameters on a grid |
| `model.sensitivity_analysis(...)` | Compute normalized local sensitivities |
| `model.contact_map(...)` | Export a contact map graph |
| `model.regulatory_graph(...)` | Export a regulatory graph |
| `model.rule_influence_graph(...)` | Export a rule influence graph |
| `model.reaction_network_graph(...)` | Export a reaction network graph |
| `model.ruleviz_pattern(...)` | Export a rule pattern graph |
| `model.ruleviz_operation(...)` | Export a rule operation graph |
| `model.process_graph(...)` | Export a process graph |
| `model.sbml_multi(...)` | Export SBML Multi |
| `model.write_xml(...)` | Export BioNetGen XML |
| `model.write_bngl(...)` | Export BNGL text |
| `model.write_sbml(...)` | Export SBML from the generated network |
| `model.write_matlab(...)` | Export MATLAB code |
| `model.write_latex(...)` | Export LaTeX output |

Top-level helpers:

```python
import bionetgen

model = bionetgen.load("models/simple_system.bngl")
scan = bionetgen.parameter_scan(model, parameter="k", min=0.01, max=10, n_points=20)
model2 = bionetgen.from_sbml("tests/python/test/test_sbml.xml")
builder = bionetgen.ModelBuilder("MyModel")
```

## CLI

```bash
bionetgen run MODEL.bngl --method ode --t-end 100
bionetgen scan MODEL.bngl --parameter k_on --min 0.01 --max 100 --n-points 50
bionetgen sensitivity MODEL.bngl --parameter k_on --observable AB
bionetgen visualize MODEL.bngl --type contact_map -o output.graphml
bionetgen check MODEL.bngl
bionetgen export MODEL.bngl --format sbml --output model.xml
```

See [docs/cli_reference.md](docs/cli_reference.md) for the full command reference.

## Build From Source

```bash
git clone <repo-url>
cd BNG3
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
pip install -e .
```

If you only want the Python package, `pip install -e .` is usually enough; the build system compiles the extension as needed.

## Citation

Please cite BioNetGen when using the platform in publications. See [docs/index.md](docs/index.md) and the project website for current citation information.

## License

MIT. See [LICENSE](LICENSE).
