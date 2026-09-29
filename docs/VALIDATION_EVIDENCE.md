# BNG3 validation evidence

**What this is.** The single place to answer *what is actually verified, and by
what*. The detailed history lives in
[`BNG3_CONVERGENCE_DONE_CHECKLIST.md`](BNG3_CONVERGENCE_DONE_CHECKLIST.md) (a
reverse-chronological log, in which an unchecked box describes what was true
when it was written — see its own preamble at `:12-19`) and the reasoning lives
in [`docs/adr/`](adr/). Those two disagree with the code in places. This file
records the current truth and nothing else.

**Tree state described:** `main` at `ccde363`.

**Rule for this file.** Every claim below carries a `file:line` or a commit. A
claim with neither does not belong here. Where a measurement is missing this
file says *missing* rather than estimating one, and where a framing turns out to
be wrong §5 says so. Short SHAs are the first seven characters of the commit as
recorded by `git log`; resolve with `git rev-parse <sha>`.

---

## 1. What is a real gate today

A gate is a job that runs and can fail. All of the following are on pull requests
to `main` and pushes to `main`/`develop` (`.github/workflows/ci.yml:3-9`).

| Gate | Where | What it asserts |
|---|---|---|
| Lint & policy | `ci.yml:26-71` | Black and Ruff clean over `python/ tests/python/ scripts/`; `scripts/validate_provenance.py` (non-strict), `scripts/validate_corpus_manifest.py`, `scripts/generate_corpus_manifest.py --check`; every committed `provenance/golden/**/manifest.json` validates; the validation exception budget is ≤ 1; `tests/test_ci_contract.py` passes. |
| C++ matrix | `ci.yml:77-164` | Builds and `ctest`s on ubuntu-22.04/gcc-12, ubuntu-22.04/clang-15, macos-14/clang-arm64, windows-2022/MSVC. Four independent compilers, one shared test suite. |
| C++ ASan | `ci.yml:168-216` | Same suite under `-fsanitize=address`, gcc-12 Debug. |
| Batch SSA CPU reference parity | `ci.yml:302-355` | Builds the Python extension, asserts `_bionetgen_cpp*` exists, then runs `tests/test_batch_ssa_statistical_parity.py --mode cpu`: exact (non-statistical) conservation identities and seed reproducibility on four models, plus a Chi-square and moment test of `isomerization` against the closed form `Binomial(20, 1/6)`. No accelerator needed. |
| Validation corpus | `ci.yml:359-402` | ubuntu/macOS/Windows: `scripts/validate.py --bng-cpp … --strict-references --validation-manifest tests/validation/validation_manifest.json`. Compares typed networks through `tests.validation.compare` — graph-aware, not section counts. |
| BNGL corpus parse inventory | `ci.yml:406-466` | `bng_cpp --check` over every `models/*.bngl`; fails only if zero models are discovered. The job states it is parser acceptance only and **does not run NFsim**. |
| Python matrix | `ci.yml:471-545` | 3 OS × Python 3.9–3.14: builds and installs the wheel, then `test_sbml_import.py` in its own invocation and the rest of `tests/python/` with coverage. |
| Integration | `ci.yml:549-604` | `tests/python -k atomizer`, `-k model`, and a real CLI smoke (`bionetgen check`, `bionetgen run --method ode`). |
| Package smoke / wheels / sdist / publish / docker | `ci.yml:607-806` | Clean-venv sdist install and import; cibuildwheel matrix that runs `tests/python/test_cpp_backend.py` plus the console script inside each wheel; PyPI publish and GHCR image. |
| Source lock | `parity.yml:29-48` | `scripts/ci/checkout_oracle.py --validate-only`; non-strict provenance; CI-contract tests. |
| BNG3 vs BNG2 networks | `parity.yml:50-95` | Five named models compared against a *locked* BNG2 checkout via `scripts/cross_validate.py`. |
| BNG3 vs independent NFsim | `parity.yml:97-181` | Builds the locked NFsim oracle, then `tests/validation/test_parity_nfsim.py -m "nf and not slow"`, plus two targeted `-k` selections. This is the only `tests/validation/` module any job runs. |
| PyBioNetGen compatibility | `parity.yml:219-…` | `scripts/ci/check_pybionetgen_compat.py` against a locked checkout. |
| Lean kernel | `formal.yml:19-…` | Pinned Lean 4.33.1 kernel check and the NFnext contracts. |
| Weekly (`bng-validation`, `nfsim-execution-smoke`, `python-full`, `benchmarks`, `cross-validation`) | `weekly.yml:16, 69, 141, 162, 196` | Sunday-only; the same `validate.py` corpus and the Perl cross-validation. Not a per-PR signal. |

Two harness properties that make the above stronger than it looks:

- **A missing oracle is a failure, not a skip.** `tests.validation.strict.require_oracle`
  fails the test when `BNG3_CI_STRICT_ORACLES=1` (`tests/validation/strict.py:10-18`),
  and only skips otherwise. That variable is set in `parity.yml:24` **and nowhere
  else** — the `validation` job in `ci.yml` does not set it.
- **The comparators are graph-aware.** `compare.py` canonicalises species to a
  graph-isomorphism-invariant form (`compare.py:731-737`), resolves rate tokens
  to values rather than strings (`compare.py:107-132`), and returns
  `NetDiff`/`TrajDiff`/`EnsembleDiff` verdicts (`compare.py:1032, 1326, 1417`).

### Gates that exist in the tree but run nowhere

Being able to run is not being run. None of these is invoked by any workflow:

- `scripts/validate_ratelaws.py`, `scripts/validate_actions.py`,
  `scripts/validate_sbml.py`, `scripts/check_localfunc_rates.py`.
  `validate_actions.py` is still described in the convergence checklist as
  reporting "6/6 action contracts" — that is a local run, not a CI result.
- Every module in `tests/validation/` **except** `test_parity_nfsim.py`:
  `test_parity_net.py`, `test_parity_ode.py`, `test_parity_stochastic.py`,
  `test_parity_expressions.py`, `test_compare_net.py`, `test_provenance.py`,
  `test_corpus_manifest.py`, `test_golden_manifest.py`,
  `test_exception_ledger.py`, `test_harness_paths.py`,
  `test_reference_fixtures.py`, `test_export_formats.py`,
  `test_published_biomodels_manifest.py`. They are run by the commands in §4.

### A gate that can pass without doing anything

`cpp-cuda` detects `nvcc` and gates every subsequent step on
`steps.cuda.outputs.available == 'true'`; on a runner without the CUDA toolkit
the job emits a warning and finishes green having compiled nothing. That is a
reasonable design and a real trap to read as evidence. The same is true, more
mildly, of `corpus-parse`, which only fails on an empty corpus.

---

## 2. What is NOT verified

These are open. None of them is covered by anything in §1.

1. **The pinned SBML Test Suite result (1,744 passed / 179 unsupported / 0 failed
   / 0 timed out) cannot be re-derived from this repository.** The number is
   quoted in the convergence checklist and in `CURRENT_PROGRESS.md`. Its
   provenance audit is recorded in the checklist:
   - The suite is not in `provenance/upstreams.lock.yml`; there is no `suite`
     key at all.
   - It is not an oracle: `scripts/ci/oracle_sources.py:19` lists exactly
     `("bionetgen", "nfsim", "pybionetgen")`.
   - The runner does not verify what it is handed: `--suite-dir` is required
     (`scripts/ci/validate_sbml_test_suite.py:997`) and the report records
     `git -C <suite-dir> rev-parse HEAD` verbatim (`:1021-1024`, `:1100`)
     without comparing it to any lock.
   - No CI job runs it and no report is committed; the cited artifact is under
     `/private/tmp`.
   - **What it measured, precisely:** the runner's own docstring says it "is an
     import/round-trip gate, not a claim of numerical SBML Test Suite simulation
     conformance" (`scripts/ci/validate_sbml_test_suite.py:8-9`) — import, SBML
     write, reimport, native-reader species/reaction counts, plus a
     BNG3-CVODE-versus-libRoadRunner comparison. It is **not** conformance
     against the suite's expected numeric outputs.
   - libRoadRunner is installed by no workflow, so even the comparison half
     cannot be reproduced without local setup.

   Treat every suite-derived count in this repository as one machine's
   historical observation.

2. **The 1e-9 expression-vector/RHS gate is unimplemented.**
   `tests/validation/corpus.py:56-57` declares `TIER_EXPR` with the requirement
   "RHS must match the oracle to 1e-9", and
   `tests/validation/test_parity_expressions.py:3-5` says outright: "The direct
   expression-vector/RHS gate remains open." See §5.2 for the exact scope.

3. **`provenance/golden/` has no approved bundle.** The directory contains only
   `README.md`, which states: "No approved golden bundle is present until the
   oracle build recipes and acceptance choices in the source lock have been
   decided." The lint job is written to tolerate this and prints
   "No golden bundle manifests committed" when the directory is empty.

4. **The reconciliation ledgers carry no test evidence.** Every entry in
   `provenance/reconciliation/bionetgen.yml`, `nfsim.yml` and `pybionetgen.yml`
   has `"tests": []`, and each carries
   `"reviewer": "Codex technical reconciliation; maintainer review pending"`.
   The ledgers are a classification record, not evidence that anything was
   verified.

5. **There is no `CODEOWNERS` file.** The requirement is unmet, and the
   convergence checklist records it as an open box rather than claiming one
   exists.

6. **The strict provenance gate is not wired into any job, and it currently
   fails.** `python scripts/validate_provenance.py --require-approved` was
   measured at **13 errors** at `d04f648` — baseline, 8 sources, 2 oracles,
   compiler images, Python lock. Only the non-strict call runs; no workflow
   passes `--require-approved`, so those errors cannot fail any job.
   *(Not re-run when this file was written. Re-run the command in §4 for
   today's number.)*

---

## 3. What this session found and fixed

Commits are in the order they landed. **Read the "class" column.** A large part
of this work deliberately changed *nothing* about any model, and calling that a
fix would be the exact error this document exists to prevent.

| # | Fix | Commit | Class | Before → after, and the evidence |
|---|---|---|---|---|
| 1 | **Identifier collisions** | `d04f648` | **Hardening — no model change** | Distinct SBML SIds that `standardize_name` maps to one BNGL spelling (e.g. `A-B` and `A_B`) merged species and rewrote a reaction; now a governed `identifier`/`dropped` warning (`writer.py`). |
| 2 | **Silent missing-`kineticLaw` rate** | `d04f648` | **Hardening — no model change** | A reaction with no MathML was given rate `1` by an *environment-tunable* fallback and still produced a network; now a governed `missingMath` record. |
| 3 | **MathML operator names** | `d04f648`, extended by `e15ef58` | **Hardening for the arc names; behaviour change for the reciprocals** | `arcsinh`/`arccosh`/`arctanh` lowered to functions BNGL does not have (BNGL spells them `asinh`/`acosh`/`atanh`); the writer had the map, the parser did not. `sech`/`csch`/`coth` were a separate defect: an unknown name becomes a bare identifier, so they reached the engine as a symbol rather than a call. `e15ef58` rewrote them onto `sinh`/`cosh` and deleted two tests that had pinned false behaviour. |
| 4 | **Undeclared SBML packages** | `d04f648` | **Hardening — no model change** | A document declaring an L3 package outside the eleven the parser knew produced no diagnostic at all; now a catch-all records it as dropped. |
| 5 | **Collision diagnostic narrowed to what actually corrupts** | `e775d13` | **Hardening — no model change** | It fired on namespaces that are disambiguated at emission and therefore survive intact. Only namespaces whose generated spelling becomes a *declaration* report now, so a correct model keeps its numerical claim; both directions are pinned. |
| 6 | **A parameter that reads `time` was frozen at t=0** | `3d5e6dc` | **Behaviour change (ODE)** | A parameter whose expression reads `time` was memoized at first evaluation — t=0, during model construction — leaving a time-dependent decay rate stuck at zero for the whole run. `t` is now threaded into evaluation and such a parameter is not memoized. Failing-first test in `tests/cpp/test_ode_options.cpp`. |
| 7 | **Parameter alias chains** | `e3af431` | **Behaviour change (Atomizer)** | The alias map was applied as a chain of renames. Because one parameter's canonical id can be another's alias *key* (`k-1` and `k_1` both standardize to `k_1`), a rate law could be rewritten to the wrong parameter's value. Resolution is now a single simultaneous rewrite. |
| 8 | **`writeSSCcfg` wrote the wrong artifact** | `1a3091e` (tests in `c6a4132`) | **Behaviour change (export)** | BNG2's `writeSSC` emits a complete `.rxn` program while `writeSSCcfg` emits a `.cfg` holding the parameter block alone. BNG3 emitted the full program at the `.cfg` path — the wrong file at the wrong path. `SscWriter::writeConfig` now writes the parameter block and is explicitly not derived from `write()`. |
| 9 | **Seed site state resolved by discovery index** | `75b22a7` | **Behaviour change (NFsim)** | The seed builder used an offset into the Atomizer's *discovery order* as the NFsim state value; NFsim's value is an offset into the molecule type's own state table. `ANx` declares `RD(...,m~2)` before any observable mentions `m~0`, so every seed receptor was built in state 0. The state is now bound by name, and the two construction routes must agree at `rtol=atol=0`. The strict-xfail tuple `_KNOWN_SEED_STATE_ORDER_DIVERGENCES` is **empty** because the divergence is gone, not because the check was dropped. |
| 10 | **Raw-id tokenizer family** | `6dc41b6`, `2370586`, `ccde363` | **Two behaviour changes and one no-op refactor** | An SBML id with a character outside `[A-Za-z0-9_]` is stored **raw** and standardized only at emission, so an identifier-shaped token cannot spell it. `6dc41b6` stops raw hyphenated ids leaking into emitted rate text; `2370586` routes assignment-rule bodies through the id pre-pass, which that loop was bypassing. `ccde363` routes three pre-filter sites through the whole-id-run helper and **changes no output**. |

**On items 1–5, stated precisely.** The group fixed in `d04f648` is hardening with
*no model change whatsoever*, and this was measured rather than asserted: both
trees were run side by side over every SBML input reachable in this repository
(216 documents × 4 option modes = 864 runs) and **non-comment BNGL bytes changed
in 0 of 864**; 7 of 216 documents gained appended `# [dropped]` comment lines;
0 lines were removed anywhere. Of the five new code paths, only `missingMath`
fires on any pre-existing input; `identifier` and `package:` fire only on the
commit's own new tests; `arcsinh` and `logbase` fire on **no** document in the
corpus and are covered by fragment-level tests only. That measurement is itself
explicitly *not* evidence about the SBML Test Suite.

**Where a number is missing, this file says so.** The failing-first regression
test named in each row is the record of the defect. No before/after *count* is
recorded anywhere in the tree for items 5–10; the commit subjects and the test
docstrings are the evidence. For `ccde363` in particular, "no behaviour change"
is the author's claim in the commit subject and the absence of a new test file —
it is not a measurement, and no document in this repository measures it.

**Also landed this session, outside the table:** `2b80cd4` (the GPU batch-SSA
path returned a truncated species grid, causing a SIGSEGV through `bng_cpp`),
`969dedd` (annotation namespaces cost a correct model its numerical claim),
`d19aad7` (SSTS event refusals are sub-classified, and a prefix-matching bug that
discarded every event refusal reason is fixed), `c51a062` and `28c4b92`
(spelled-out comparison operators recognised in all 17 trigger resolvers),
`25a8a86` (three validators deleted, one fixed), `1bfe567` (ADR 0001's
validation sentence corrected), and documentation commits.

`25a8a86` removed `scripts/validate_trajectories.py`,
`scripts/validate_io_roundtrip.py` and `scripts/validate_nfsim.py`. The reasons,
with the measured state on `main` at `25a8a86`:

| Removed | Measured, with a correct absolute `--bng-cpp` | Why |
|---|---|---|
| `validate_trajectories.py` | 0 passed, 0 failed, **7 skipped, exit 0** | Its reference `.gdat` directory does not exist, so it "succeeds" having tested nothing; its `1e-3` tolerance is 1000× looser than the `1e-6` gate in `tests/validation/test_parity_ode.py`, which implements the intent against a pinned Perl oracle. |
| `validate_io_roundtrip.py` | **0 passed, 4 failed** | Claims write→read→write but runs the same BNGL twice and diffs raw text, so any deterministic writer defect reproduces identically in both outputs. The intent is implemented by `test_export_formats.py::test_net_roundtrip_idempotent`, which performs the real round trip. |
| `validate_nfsim.py` | **0 passed, 2 failed** | Never invokes NFsim with a model; the optional comparison passes only the `.bngl` via `-xml`. Covered by `test_parity_nfsim.py` plus the `nfsim-parity` job. |

All five of these scripts also defaulted to `build/bng_cpp`, which does not exist
here, so four of them failed before doing any work until the default was fixed.

---

## 4. How to check a claim yourself

**Warning first: "CI is green" is not currently an available signal on this
repository.** On 2026-09-29 every workflow run queued for hours without a job
starting, including for the head carrying the fixes above. Both `ci.yml:10-14`
and `parity.yml:13-16` were changed to stop a later push from cancelling an
in-flight run for the preceding head, which is the mechanism by which runs go
missing. Read the run yourself for the exact SHA; do not infer a status from a
prior head.

Locally, the full command set recorded in the convergence checklist:

```bash
# --- policy / contract gates (exactly what `lint` runs) ---
python scripts/validate_provenance.py            # the call CI makes
python scripts/validate_corpus_manifest.py
python scripts/generate_corpus_manifest.py --check
python -m tests.validation.exception_ledger --max-exceptions 1
python -m pytest tests/test_ci_contract.py -q

# --- the strict provenance gate, which NO job runs (see §2.6) ---
python scripts/validate_provenance.py --require-approved

# --- C++ build and suites ---
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTS=ON \
      -DBUILD_PYTHON_BINDINGS=OFF -DBUILD_CLI=ON -DBUILD_NFSIM_CLI=OFF
cmake --build build
ctest --test-dir build --output-on-failure

# --- reference validation corpus (what the `validation` job runs) ---
python scripts/validate.py --bng-cpp build/cpp/bng_cpp --strict-references \
    --validation-manifest tests/validation/validation_manifest.json --verbose

# --- tiered validation harness (LOCAL ONLY; not a CI job) ---
PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini \
    tests/validation -m "nf and not slow" --bng-cpp build/cpp/bng_cpp
# add BNG3_CI_STRICT_ORACLES=1 to turn a missing oracle into a failure

# --- batch SSA CPU reference (what `batch-ssa-cpu-reference` runs) ---
python tests/test_batch_ssa_statistical_parity.py --mode cpu

# --- Python suite ---
python -m pytest tests/python -q
```

Two habits that keep this file from going stale:

- **A proposed fix that does not reproduce must not be applied.** One audit
  ranked a defect "worst" in this session; running it showed the fail-closed path
  already held. That is why §2 records open items rather than an action list.
- **A missing diagnostic is worse than a crash.** Items 1, 2 and 4 in §3 were
  all cases where the code produced a plausible-looking *model* instead of
  refusing one.

---

## 5. Where earlier framings were wrong

Recorded because the acceptance criterion for this file is that it must not
become the next stale artifact.

1. **"No `CODEOWNERS` exists despite the checklist asserting one."** The
   checklist does not assert one exists; it lists ownership as an *open* box. The
   tree has no `CODEOWNERS` and the requirement is unmet. The brief and the
   checklist agree.
2. **"`TIER_EXPR` is consumed by no test" is nearly right, and the difference
   matters.** `corpus.tier_expr()` *is* asserted —
   `tests/validation/test_corpus_manifest.py:45` requires it to equal
   `provenance/corpus/selection.json`'s `expr` tier — and `TIER_EXPR` feeds
   `scripts/generate_corpus_manifest.py:59` and `scripts/regen_golden.py:83`.
   What is true is narrower and is the one that matters: **no test parametrizes
   over the tier's models.** The nearest test,
   `tests/validation/test_parity_expressions.py:17-20`, hardcodes its own
   three-model list and compares parsed network/rate text — it is not an
   expression-vector comparison at 1e-9 either. The 1e-9 requirement exists only
   as a comment.
3. **"`tests/validation/` is a real gate" overstates it.** Exactly one module of
   that directory — `test_parity_nfsim.py` — is wired into CI. The other
   thirteen run only via the commands in §4.
4. **The `cpp-cuda` job can report success having tested nothing** (§1, last
   paragraph). Worth knowing before quoting a green `cpp-cuda`.
5. **The validation exception budget is 1, not 0** (`ci.yml:68`). One exception
   is currently approved; that is a live tolerance, not a closed ledger.

---

*Maintained as an index, not a log. When §1, §2 or §3 becomes wrong, correct
this file in the same commit that changes the code — the checklist will keep the
history either way.*
