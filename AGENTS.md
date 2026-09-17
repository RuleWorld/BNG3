# AGENTS.md

Instructions for coding agents working on **RuleWorld/BNG3**.

Keep this file durable. Current branches, pass counts, open gaps, and temporary work belong in issues, PRs, or `docs/CURRENT_PROGRESS.md`, not here.

## Goal

BNG3 is the modern BioNetGen implementation: one maintained C++/Python system for parsing BNGL, network generation, deterministic/stochastic simulation, NFsim integration, SBML import/export, and the Python API.

Correct semantics matter more than feature count.

A model that is explicitly unsupported is better than a model that silently runs with changed semantics.

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
- **akutuva21/nfsim** — newer NFsim development fork containing performance and energy-modeling work that may be relevant to BNG3. Treat it as a source input, not automatically authoritative over canonical NFsim behavior.
- **RuleWorld/PyBioNetGen** — existing Python-facing BioNetGen behavior and compatibility reference.
- **RuleWorld/bngplayground** — independent modern BNGL implementation and useful compatibility/reference corpus. It is not a replacement for canonical BioNetGen or NFsim as a semantic oracle.

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

Use the narrowest useful test while developing, then broaden validation according to the affected surface.

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
- inspect **akutuva21/nfsim** when newer energy/performance work is relevant;
- identify exact source commits when behavior depends on a specific fork revision;
- add focused parity tests;
- preserve deterministic seeds when comparing stochastic implementations;
- distinguish correctness changes from performance changes.

Performance improvements must preserve stochastic semantics unless an intentional behavior change is explicitly documented.

Do not use the embedded BNG3 NFsim implementation as its own parity oracle.

## Atomizer / SBML

The Atomizer should translate the subset of SBML whose semantics BNG3 can represent faithfully.

Do not aim for "all SBML" by approximation.

For every newly supported SBML class, answer:

```text
What does SBML require?
Can BNGL/BNG3 represent it exactly?
What transformation is being applied?
Under what conditions is that transformation valid?
What independent test demonstrates this?
```

Prefer explicit, narrow supported subclasses over broad but incorrect feature claims.

Examples:

- static expressions may be foldable;
- dynamic assignment rules require dynamic semantics;
- static integer stoichiometry differs from state-dependent/fractional stoichiometry;
- events, delays, algebraic rules, constraints, and SBML packages require their own semantics rather than parser-only support.

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
