# Validation record

## Validation performed in this environment

From `BNG3-main/formal/lean/`:

```bash
./scripts/validate_all.sh
```

Current result:

```text
STATIC VALIDATION PASSED (36 Lean files checked)
NFNEXT HEADER CONTRACT PASS
NFNEXT CONTRACT PASS: 18/18 checks
LEAN KERNEL CHECK SKIPPED: lake is not installed
```

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

## Missing kernel validation

The environment does not contain `lean`, `lake`, or `elan`, and external binary
installation is not available through the shell environment. Therefore the
Lean source remains **not kernel-verified here**.

The mandatory external gate is:

```bash
cd formal/lean
lake build
lake env lean tests/Smoke.lean
```

No theorem in this repository should be advertised as machine-checked until
that command succeeds under the pinned `leanprover/lean4:v4.33.1` toolchain.


### Latest semantic additions

- `Propensity.lean` separates per-match kinetic constants from TotalRate channel rates.
- `ReactionNetwork.lean` records canonical reaction edges over the graph-isomorphic species pool.
- `CXX_MIGRATION_BLOCKERS.md` records why full production C++ refinement is not yet claimable.
