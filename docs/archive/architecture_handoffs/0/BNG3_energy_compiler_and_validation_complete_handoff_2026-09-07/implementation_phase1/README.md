# BNG3 energy compiler — phase 1 implementation bundle

> Archived implementation bundle. Current integration status is recorded in
> `docs/CURRENT_PROGRESS.md`; this file describes its source checkpoint.

Prepared against:

- repository: `RuleWorld/BNG3`
- PR: `#2` (`codex/bng3-integration-foundations`)
- exact head: `3bc7b4ff131f8927421bc8eae170e3b248b75318`

## Implemented

This patch introduces the first execution-facing compiler layer without changing
BNGL/eBNGL syntax or replacing the existing NFsim compatibility fallback.

- `compile::CompiledModel`: immutable compiled metadata suitable for sharing
  across execution backends/trajectories. It records compiled rules and a
  normalized energy-factor catalog (source pattern, structural fingerprint,
  energy expression).
- `compile::CompiledRule`: converts the existing
  `ast::ReactionRule::TransformOp` graph edits into conservative mutation
  signatures and affected-component metadata.
- `compile::CompiledRateLaw`: classifies existing rate expressions, including a
  typed `ArrheniusEnergy` representation, while retaining the original AST
  expression and arguments.
- `compile::energy::EnergyDeltaPlan`: backend-neutral representation of
  constant or factorized local free-energy changes, conjunctive context masks,
  signed terms, Arrhenius factors, and small precomputed factor tables.
- `EnergyFunction::compileBindingDeltaPlan`: moves compact binding semantics
  into `EnergyDeltaPlan`. The existing `EnergyBindingContext` is reconstructed
  from the plan, so `EnergyRxnClass` behavior remains the compatibility path.
- `EnergyFunction::compileStateChangeDeltaPlan`: compiles signed state-change
  free-energy terms but does not switch runtime execution yet.
- reaction-center inverted indexes: binding and state-change relevance queries
  no longer scan the complete energy-pattern list for every rule.
- focused Catch2 tests for the plan algebra, binding bridge, signed state-change
  plan, typed Arrhenius classification, and compiled rule mutations.
- architecture note: `docs/BNG3_ENERGY_COMPILER_PLAN.md`.

## Deliberately not changed in this patch

The patch does **not** bypass the existing parity gates. In particular:

- materialized Sekar expansion remains the fallback for unsupported topology;
- state-change execution still uses the existing materialized path;
- mixed-reactant/same-type compact binding restrictions remain enforced by the
  current NFsim lowering;
- barrier patterns, reservoirs/driven-rule syntax, indexed/parametric BNGL rule
  syntax, ordered-polymer storage, and batch-trajectory APIs are not introduced
  here.

Those are follow-on semantic/runtime changes and should land only after this
compiler seam passes the independent BNG2/NFsim oracle gates required by the
branch's `AGENTS.md`.

## Local validation performed in this session

Because the execution VM could not resolve `github.com` and the GitHub app had
read but not write access, the complete BNG3 checkout could not be cloned or
mutated from this session. The following checks were still performed:

- exact PR #2 source files and tests were inspected through the connected
  GitHub repository;
- all new standalone C++ compiler objects compiled with GCC 14 using
  `-std=c++17 -Wall -Wextra -Werror -pedantic`;
- the energy-index implementation compiled and ran under the same warning gate;
- the energy-plan compatibility bridge compiled in isolation against matching
  NFsim data-structure contracts;
- the unified patch passed `git apply --check` on a synthetic preimage built
  from the exact changed source contexts;
- the applied result passed `git diff --check`.

This is not a substitute for BNG3's full CTest/Tier-NF oracle validation.

## Apply

From a clean checkout at the exact PR head:

```bash
git switch codex/bng3-integration-foundations
git rev-parse HEAD
# must be 3bc7b4ff131f8927421bc8eae170e3b248b75318

/path/to/this/bundle/apply.sh
```

Or directly:

```bash
git apply --check bng3_energy_compiler_phase1.patch
git apply bng3_energy_compiler_phase1.patch
git diff --check
```

Then run the repository's full convergence and NFsim parity gates before
committing or merging.
