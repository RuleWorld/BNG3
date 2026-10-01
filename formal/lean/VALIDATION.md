# Validation record

## Validation performed in this environment

From `formal/lean/` at `main` = `9f840a5`, 2026-09-30, with the pinned
`leanprover/lean4:v4.33.1` toolchain present (`lean --version` reports
`4.33.1`):

```bash
./scripts/validate_all.sh
```

Result — note that this **exits 1, by design**, not because the kernel is
unavailable any more:

```text
== static validation ==
STATIC VALIDATION PASSED (37 Lean files checked)
== NFnext header contract ==
NFNEXT HEADER CONTRACT PASS
== NFnext compiled contract ==
NFNEXT CONTRACT PASS: 18/18 checks
== Lean kernel build ==
Build completed successfully (36 jobs).
== Lean test: tests/Smoke.lean ==        (exit 0)
== Lean test: tests/Coverage.lean ==     (exit 1: the three [FAILS TODAY] assertions)
```

Two consequences of that exit status, both load-bearing:

- The three `Coverage.lean` errors are the deliberate gate described below.
  They are the only errors present; the file's own banner states the expected
  count as "3 errors ... and NO others", and that is what a run produces.
- `scripts/validate_all.sh` runs under `set -euo pipefail`, so it stops at
  `Coverage.lean` and the **axiom dependency audit never runs locally**. In CI
  it is a separate workflow step (`.github/workflows/formal.yml`), so it does
  run there. Do not read a local `validate_all.sh` pass/fail as evidence about
  axiom hygiene.

The current continuation adds a bounded production-boundary contract to the
normal architecture tests. Lean and C++ independently use
`A(x~u) + B(y) -> A(x~p!1).B(y!1) k`; the C++ side crosses BNGL parsing,
`bng::compile::CompiledModel`, and `nfnext::lowerFromBioNetGen`, checking
distinct-reactant molecularity, a state update, and a new bond. This is
correspondence evidence for one NFnext slice, not complete kernel verification
or backend equivalence.

### Static Lean checks

`static_validate.py` checks:

- all local `import BNG.*` targets exist;
- comments/strings/delimiters are structurally balanced;
- no `sorry`, `admit`, or `axiom` proof placeholders occur in code;
- required semantic modules are present.

These checks do **not** type-check Lean.

### Real NFnext C++ checks

`run_nfnext_contract.sh` compiles a temporary binary directly against the
repository's current:

- `nfir.cpp`;
- `generic_state.cpp`;
- `generic_matcher.cpp`;
- `transformation.cpp`;
- `validator.cpp`.

The fixture currently checks 18 matcher/transformation properties including:

- exact state and state-set matching;
- explicit free-site matching;
- same- and different-complex molecularity;
- exact bonds;
- interchangeable-node automorphism behavior;
- indirect `connected_to`;
- SetState;
- AddBond / DeleteBond;
- CreateMolecule;
- AddBondExistingToCreated;
- AddBondCreated;
- DestroyMolecule;
- DestroyComplex;
- initial states on created molecules.

The binary is built in a temporary directory and removed automatically.

### Header-drift check

`check_nfnext_header_contract.py` verifies that the C++ NFnext vocabulary
mirrored by Lean still contains the expected PatternIR and TransformationIR
constructors/fields.

## Scope of the kernel claim

Earlier revisions of this file recorded that the environment lacked `lean`,
`lake`, and `elan`, so the source was "not kernel-verified here". That is no
longer the state of `main`: the pinned toolchain is installed, `lake build`
succeeds (36 jobs), and `tests/Smoke.lean` passes. The kernel claim is now
measured, and its limits are stated here so that "machine-checked" is not read
as covering more than it does.

What `lake build` does **not** cover:

- `lakefile.lean` declares `lean_lib BNG where roots := #[`BNG]`, so the
  library only. `tests/Smoke.lean` and `tests/Coverage.lean` are not compiled
  by it and must be named explicitly — which is why `formal.yml` has a
  dedicated step per file rather than relying on `lake build`.
- `native_decide` reduces through the compiled evaluator and does not consult
  the kernel. Several assertions in `tests/` are `native_decide`; they are
  regression guards, not kernel proofs. `scripts/check_axiom_dependencies.sh`
  measures this rather than asserting it, failing on any axiom that is neither
  one of Lean's three standard ones nor a declared `native_decide` extension.

No theorem in this repository should be advertised as machine-checked unless
`lake build` succeeds under the pinned `leanprover/lean4:v4.33.1` toolchain,
and a claim about `tests/` additionally requires that file to have been run.

Pull requests run the pinned hosted gate in
[`../../.github/workflows/formal.yml`](../../.github/workflows/formal.yml).
That job installs `leanprover/lean4:v4.33.1`, runs the static and NFnext
contract checks, executes `lake build`, then runs `Smoke.lean`,
`Coverage.lean`, and the axiom audit as separate steps — so, unlike the local
`validate_all.sh`, the audit is not skipped when `Coverage.lean` fails. A local
green static/contract result is not a substitute for that kernel check.


### Latest semantic additions

- `Propensity.lean` separates per-match kinetic constants from TotalRate channel rates.
- `ReactionNetwork.lean` records canonical reaction edges over the graph-isomorphic species pool.
- `BNGIR.lean` models the BNGIR envelope header: format tag, decode acceptance
  of exactly versions 0.1/0.2, and the fail-closed feature gate; roundtrip and
  refusal theorems are exercised by `tests/Smoke.lean`.
- `CXX_MIGRATION_BLOCKERS.md` records why full production C++ refinement is not yet claimable.
