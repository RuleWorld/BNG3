# AGENTS.md

Instructions for coding agents working on **RuleWorld/BNG3**.

Keep this file durable. Current branches, pass counts, open gaps, and temporary work belong in issues, PRs, or `docs/CURRENT_PROGRESS.md`, not here.

## Goal

BNG3 is the modern BioNetGen implementation: one maintained C++/Python system for parsing BNGL, network generation, deterministic/stochastic simulation, NFsim integration, SBML import/export, and the Python API.

Correct semantics matter more than feature count.

The first release implements the complete capability inventory in `docs/CAPABILITY_UNION_INVENTORY.md`, including canonical BNG2, canonical NFsim, PyBioNetGen and BNG3 additions. Optional installs do not reduce support. During implementation, report missing semantics explicitly rather than silently changing them; implement and qualify every required row before release.

`docs/DECISIONS.md` records final maintainer decisions. Apply them without requesting the same decision again. Every issue closes when all its listed acceptance checks pass on `main`; record the commit and artifacts. No additional closure approval is required.

## Read before changing code

Inspect the repository and current branch before reasoning from memory:

```bash
git status
git branch --show-current
git log -5 --oneline
rg <relevant-symbol-or-feature>
```

Read existing implementation and tests before adding new abstractions.

Use installed engineering skills when relevant, especially:

- source-driven development
- debugging/error recovery
- doubt-driven development
- test-driven development
- incremental implementation
- code review
- code simplification
- performance optimization
- Git/CI workflows

Skills supplement these rules; they do not override them.

## Related repositories

Know which repository answers which question.

- **RuleWorld/BNG3** — target implementation. Change code here.
- **RuleWorld/bionetgen** — canonical BioNetGen / BNG2 behavior and historical implementation. Use it to understand established BNGL semantics and compatibility.
- **RuleWorld/nfsim** — canonical NFsim reference implementation.
- **RuleWorld/PyBioNetGen** — existing Python-facing BioNetGen behavior and compatibility reference.

Also use authoritative upstream specifications and independent implementations where appropriate, especially:

- SBML specifications
- official SBML Test Suite
- published BioModels
- libRoadRunner for independent SBML simulation comparison

Do not copy another repository wholesale. Identify the behavior needed, understand it, then implement the smallest appropriate version in BNG3.

## GitHub workflow

Use the local **GitHub CLI (`gh`)** for GitHub work.

Prefer:

```bash
gh pr view
gh pr diff
gh pr checks
gh run list
gh run view
gh issue view
gh api
```

Use `git` for local history/diffs and `gh` for GitHub state.

Do **not** rely on the ChatGPT GitHub connector, GitHub MCP, or a cached web view when `gh` is available. Repository-local `git` + authenticated `gh` are the authoritative workflow.

Before modifying GitHub state, confirm repository, branch, and current SHA.

Never overwrite unrelated worktree changes.

## KISS

Prefer the simplest implementation that preserves the required semantics.

- Solve the demonstrated problem, not hypothetical future problems.
- Reuse existing parser, IR, writer, engine, and validation abstractions.
- Do not create parallel frameworks for one feature.
- Do not generalize from one failing BioModel.
- Do not add indirection without a concrete need.
- Do not rewrite working subsystems unless the existing design prevents the required behavior.
- Keep diffs surgical.
- Remove obsolete compatibility code when it is genuinely superseded and tested.
- Do not optimize for line count, feature count, or headline pass count.

When two designs are equally correct, choose the simpler one.

## Semantic correctness

Treat support as a semantic claim.

These are **not equivalent**:

```text
parses
≠ converts
≠ emits valid BNGL/SBML
≠ runs
≠ round-trips
≠ reproduces source behavior
```

A feature is supported only to the extent that its relevant semantics are preserved.

When translating between SBML, BNGL, internal IR, generated networks, or NFsim:

1. establish the source semantics;
2. determine whether BNG3 can represent them;
3. implement the smallest semantics-preserving lowering;
4. test the individual behavior;
5. compare against an independent oracle when possible.

If semantics cannot be preserved, return an explicit unsupported result.

Never turn an unsupported construct into a nominally supported approximation merely to increase coverage.

### Static versus dynamic lowering

Be especially careful when lowering SBML constructs.

A constant expression that can be proven static may often be folded.

A state-dependent rule, assignment, stoichiometry, delay, event, algebraic relation, conversion factor, or package feature must not be treated as static unless that equivalence is established.

Do not infer representability merely because generated BNGL is syntactically valid.

## Debugging

Reproduce before modifying.

For a mismatch, first classify the likely layer:

```text
source model/specification
parser
IR
lowering/Atomizer
writer/export
network generation
ODE/SSA backend
NFsim
numerical solver
independent oracle
validation harness
performance/timeout
```

Then reduce the problem to the smallest useful reproducer.

Do not initially "fix" a discrepancy by changing:

- tolerances
- simulation horizons
- retry counts
- exclusions
- skips
- expected outputs
- unsupported guards

Those may be changed only after the cause is understood.

Every confirmed defect should get a focused regression test.

If two targeted fixes fail, reassess the diagnosis before making a third.

## Validation

Prefer CI for builds, broad suites, platform matrices, and corpus campaigns. Keep local testing to focused one-off harness checks or reduced reproducers when useful; do not routinely rebuild or rerun broad suites locally. Wire the affected surface into CI and state which evidence is local versus hosted.

### Build

```bash
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
```

For the Python package:

```bash
pip install -e .
```

### Core tests

```bash
ctest --test-dir build --output-on-failure

PYTHONPATH=python:build/cpp \
python -m pytest -q tests/python
```

Run focused tests first while iterating.

### Semantic/parity tests

For changes affecting established BioNetGen behavior, compare against **RuleWorld/bionetgen / BNG2** where applicable.

For NFsim changes, compare against an independently built native NFsim from the relevant pinned source.

For SBML/Atomizer changes, use:

1. focused regression cases;
2. round-trip checks where meaningful;
3. independent simulation comparison with libRoadRunner;
4. official SBML Test Suite;
5. curated BioModels.

A BNG3-generated artifact is not an independent oracle for BNG3.

### Interpreting corpus results

Classify results separately:

```text
passed
unsupported
failed
timed out
invalid source
```

Do not combine unsupported with failure.

A larger pass count is not automatically progress. If new support changes:

```text
654 pass / 429 unsupported / 0 fail
```

into something like:

```text
777 pass / 299 unsupported / 5 fail / 2 timeout
```

triage the newly admitted failures before claiming the expanded surface is correct.

Corpus tests discover cases. They do not define semantics.

## NFsim

BNG3 embeds NFsim behavior but must remain independently checkable against native NFsim.

For NFsim-related work:

- inspect **RuleWorld/nfsim**;
- identify exact source commits when behavior depends on a specific fork revision;
- add focused parity tests;
- preserve deterministic seeds when comparing stochastic implementations;
- distinguish correctness changes from performance changes.

Performance improvements must preserve stochastic semantics unless an intentional behavior change is explicitly documented.

Do not use the embedded BNG3 NFsim implementation as its own parity oracle.

## Atomizer / SBML

The Atomizer implements all SBML Level 3 Core, Multi and comp constructs, including events, delays, assignment/rate/algebraic rules, fast reactions and hierarchical composition. The fbc package is not imported because it describes flux-balance optimization rather than kinetic simulation. Other package decisions are recorded in `docs/DECISIONS.md` and the capability inventory.

For each construct, establish the source specification, implement an exact representation and execution in BNGL/BNG3, state the transformation conditions and add independent semantic tests. Extend the compiled model and engine where necessary. Do not substitute static values for dynamic rules, delays, stoichiometry, event assignments or compartment sizes. A diagnostic for valid required input identifies work to complete; it is not release acceptance.

Use official SBML expected results, independent source simulation, and analytic laws where no simulator supplies the needed oracle. Parsing, conversion and valid output alone do not prove preserved execution.

## Performance

Measure before optimizing.

For performance work:

1. establish a representative benchmark;
2. profile;
3. identify the bottleneck;
4. make one meaningful change;
5. rerun correctness tests;
6. rerun the benchmark.

Prefer algorithmic/data-structure improvements over micro-optimizations.

For stochastic engines, report throughput together with parity/reproducibility evidence.

Do not trade correctness for benchmark numbers.

## Python and C++ boundaries

Keep responsibilities clear.

- C++ owns performance-critical model representation and simulation machinery.
- Python owns user-facing APIs, orchestration, translation utilities, and tooling where appropriate.
- Avoid duplicating core semantics independently in Python and C++.
- pybind11 bindings should expose the native implementation rather than recreate it.

The normal Python entry point is:

```python
import bionetgen
```

Legacy code is reference/compatibility material, not the preferred implementation path.

## Changes and commits

Before editing:

```bash
git status --short
git diff
```

Preserve unrelated changes.

Before a checkpoint:

```bash
git diff --check
git status
```

Run the tests appropriate to the changed surface.

Do not claim something is complete because local tests happen to be green. State exactly what was tested.

Commit meaningful checkpoints rather than leaving large validated bodies of work only in temporary worktrees.

Do not create changelogs, migration reports, benchmark reports, or new design documents unless they are actually needed or requested.

## Documentation

Keep documentation factual and current.

Do not place temporary branch state or today's test counts in `AGENTS.md`.

Use:

- `AGENTS.md` — durable working rules
- `docs/CURRENT_PROGRESS.md` — current implementation/validation state
- issues/PRs — scoped work and discussion
- archive/history documents — historical provenance only

When documentation disagrees with code or tests, inspect the implementation and current Git history before deciding which is stale.

## Cross-component integration regressions

Use generated, reusable regression cases to detect semantic integration defects across the full maintained system: Python APIs and orchestration, Atomizer/SBML lowering, the native BNG3 engine, BNG2 compatibility, PyBioNetGen compatibility, and NFsim. Integration failures are evidence for investigation; do not bundle product repairs into validation-only work.

Python validation tooling may prepare, run, compare, classify, and preserve evidence for a case. Semantic implementation remains in the component that owns the behavior, normally C++ for native engine semantics and Python for API, orchestration, or translation behavior. Keep those roles clear in findings and patches.

Prefer broad generated or parameterized regression coverage in CI so regressions are repeatable and shared across contributors. Use local checks to validate the harness or a narrowly reduced reproducer; do not replace the CI matrix with one-off local cases. Preserve each stage boundary and classify unsupported, invalid input, timeout, harness error, and semantic failure separately.

Use an isolated worktree and branch for sustained integration-validation work. Commit coherent checkpoints after review and appropriate focused validation; do not mix regression detection with a product fix unless the user explicitly asks for both. Delegation is optional. When using subagents in this repository, use the number of Luna agents set in the Phase 2 plan, with no further delegation, unless the user explicitly authorizes a different model or scale.

Issue mappings identify the required work. An issue closes when all named acceptance checks pass on `main`; a file reference alone does not prove a check ran. Declare required semantic check identities independently of process execution, consume exported artifacts in the intended downstream component, and retain bounded replay packets. Do not count a producer artifact as a successful consumer check. Reject stale, conflicting, dirty, or unverifiable revision evidence when assembling a current issue queue; the approvals and scope decisions recorded in `docs/DECISIONS.md` are final and satisfy those obligations. Do not request them again or add a separate closure approval.

Equal stochastic seeds establish pathwise parity only when construction and draw ordering are comparable. Otherwise use a justified distributional comparison, or label invariant-only checks with their narrower scope; deterministic ODE agreement and conservation do not establish stochastic equivalence.

Validate generated source models independently before scoring refusal or loss diagnostics. Diagnostic-only and rejection controls must never count as supported scientific execution. Stochastic ensemble checks need an independent source law or oracle, fixed recorded seed/run budgets, explicit statistical error control, and claims limited to the distributions or marginals actually checked.

## Definition of done

A change is done when:

- the intended semantics are understood;
- the implementation is as simple as practical;
- focused regression tests pass;
- existing relevant tests still pass;
- independent parity evidence is used when available;
- unsupported behavior remains explicitly unsupported rather than approximated;
- no unrelated changes were damaged;
- the result is described without overstating what was validated.

Correct, simple, testable, maintainable.
