# Cross-tool CI parity

Current branch state and unvalidated implementation changes are recorded in
[`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md). Historical hosted results only
apply to the exact SHA named with them.

BNG3 is the forward-development tree. BioNetGen, NFsim, and PyBioNetGen remain
external compatibility sources and independent oracles for CI; their runtime
trees are not copied into BNG3 by this workflow.

## Source-to-gate reconciliation

| Source framework | BNG3 gate | Reconciliation decision |
| --- | --- | --- |
| BioNetGen C++ build and CTest | `ci.yml:cpp-build` | Keep BNG3's CMake/Catch2 targets and platform matrix. |
| BioNetGen BNG2 validation | `parity.yml:bng2-parity` | Check out the locked BioNetGen source and compare BNG3 networks with its independent `BNG2.pl` using the graph-aware comparator. The legacy Cygwin bundle job is not a BNG3 runtime gate. |
| NFsim native build and `validate/validate.py` | `parity.yml:nfsim-parity` and scheduled `nfsim-source-validation` | Build NFsim from its locked source in a separate tree. Pull requests run direct/XML checks and a fixed-seed native comparison; scheduled runs execute the historical model validator. BNG3's embedded `NFsim` is never accepted as the oracle. |
| PyBioNetGen Python matrix, packaging, and formatting | `ci.yml:python-test`, `package-smoke`, `wheels`, `autofix.yml` | Use BNG3's modern package build and Python matrix. `pybionetgen-compat` anchors the source-derived public API contract to the locked PyBioNetGen source; the legacy `setup.py` asset downloader is not reused. |
| CI provenance and exact-head evidence | `parity.yml:oracle-lock` plus existing CI contract tests | Resolve full Git SHAs from `provenance/upstreams.lock.yml`, record them in step summaries, and preserve one run per exact PR head. |

The platform build matrix remains the fast cross-platform gate. External oracle
jobs are intentionally Linux-based where Perl and the historical NFsim validator
are reproducible; macOS and Windows continue to exercise BNG3's own C++ and
package paths. A platform-specific oracle disposition must be added here and to
the provenance/checklist before it is described as parity evidence.

## Full-corpus validation checkpoint — 2026-09-15

The PR and weekly BNG validation jobs invoke `scripts/validate.py` with strict
references and `tests/validation/validation_manifest.json`. The network corpus
uses committed independent BNG2 `.net` references; the six action-focused
fixtures (`ANx`, `hybrid_test`, `test_tfun`, `test_tfun_xml`,
`test_write_sbml_multi`, and `visualize`) use explicit output contracts in
`scripts/validate_actions.py`. The former reference-exclusion profiles are
closed and the full local run at semantic commit `78a1591` reports `71 passed,
0 failed, 0 errors, 0 skipped`. The exact final PR head
`ed4c59e028b2799a7b8025a8b37dccdc1dec0888` is covered by hosted CI run
[`34896645707`](https://github.com/RuleWorld/BNG3/actions/runs/34896645707),
with terminal-success C++, Python, full-corpus, package-smoke, and integration
jobs; the independent parity, Lean, CodeQL, and formatting runs are also
terminal-success. This closes the CI exclusion repair, not the broader
convergence, backend-equivalence, or release gates.

The preceding hosted PR head exposed a Windows/MSVC-only parser failure: the
legacy `NFinput.cpp` include path reached generated ANTLR visitor headers before
the translation-unit compatibility include, leaving the Windows SDK `constant`
macro active inside ANTLR. The generated parser, visitor, and base-visitor
headers now include `cpp/parser/antlr_compat.hpp` directly. The local native
rebuild is green, and the exact-head hosted Windows and package-matrix jobs
pass. The scheduled NFsim and release-only artifact/publish jobs are skipped
only when their event guards do not apply; they are not PR validation-test
exclusions.

## Reproducibility rules

- Oracle revisions must be full lowercase Git SHAs from the provenance lock.
- A checkout is detached at the locked revision and must be clean.
- `BNG3_CI_STRICT_ORACLES=1` turns missing engines and empty oracle output into
  failures in hosted parity jobs; broader parity jobs may retain explicit,
  classified setup skips, while the full-corpus `ci.yml` and weekly validation
  jobs are strict and must report zero skipped fixtures.
- Missing engines, missing output, comparison errors, and unexpected skips fail
  the claimed parity job; summaries include source revisions and executable
  digests where the runner already provides them.
- Changes to runtime functionality belong in the engine/API work; this CI port
  only adds orchestration, source-derived contracts, and comparison gates.
