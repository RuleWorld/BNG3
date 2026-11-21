# NFnext dynamic-rate runtime completion plan

Scope: the open gap recorded in `docs/CAPABILITY_UNION_INVENTORY.md` and
`docs/CURRENT_PROGRESS.md` for issues #147, #148, #149 and #150.

> **Status note (post-#832):** `method="nf"` now defaults to NFnext; NFcore
> remains explicitly selectable. The statements below describe the increment as
> it was recorded and are retained for history, not as the current default.
>
> NFnext has made concrete progress and NFcore remains the default. Dynamic
> energy expressions and dynamic population-map rates can be represented in
> NFIR, but their runtime coverage and full independent NFsim parity remain
> open.

This plan sequences the work so that semantics are established before support
is claimed, per `AGENTS.md`. It does **not** promote NFnext to the default
backend: `docs/DECISIONS.md` item 4 keeps NFcore as production/default until
the full native corpus passes.

## Current, verified state (baseline on `main` @ b5e1ea60)

- `lowerFromBioNetGen` preserves dynamic energy expressions and dynamic
  population-map rates as source text in `NFIR` (PRs #754 / #753) and emits
  warnings. Those commits add representation and a refusal assertion only.
- `executeFromBioNetGen` refuses every population map, and refuses
  energy-modulated Arrhenius rule forms whose expansion is not fully static.
- **Defect found:** `energyFactorValue()` in `cpp/nfnext/src/from_bng.cpp`
  returns `0.0` for a dynamic energy expression. The static Arrhenius expansion
  therefore folds a dynamic energy contribution to zero instead of evaluating
  it at runtime. This is a silent semantic approximation, not a refusal.
- Baseline CTest targets `architecture_nfnext_{bng_lowering_bridge,
  execution_boundary,population_hybrid,compartment_rate}` all pass before any
  change.

## Staged plan

### Stage 1 — Dynamic energy runtime semantics (completed 2026-11-19)

Status: implemented; `architecture_nfnext_bng_lowering_bridge` passes with the
new lowering/analytic regression and the full local CTest suite (830 tests)
passes. The long-running Stage 3/4 qualification is still required before any
release or default-promotion claim.

1. Define the runtime meaning: for an energy-modulated state change the signed
   energy delta `ΔG(state)` is the coefficient of the matched energy-pattern
   centre state multiplied by that pattern's energy expression, evaluated
   against the current observable values. The propensity is the existing
   Arrhenius form `exp(-(Ea + B + phi_eff*ΔG(state) + work_term))`.
2. Replace the silent zero fold with an NFIR `Function` rate expression built
   from `observableRateExpression()` for every dynamic energy pattern, reusing
   the observable-dependent function evaluator already qualified for dynamic
   observable rates (#746). Static energy patterns keep the existing folded
   Elementary path, so no current model changes behavior.
3. Keep fail-closed: an energy expression that cannot be resolved to NFIR
   arithmetic remains an error; barrier/reservoir work that is not statically
   evaluable remains refused (no independent oracle exists for it).
4. Add focused regressions: a lowering invariant (dynamic energy yields a
   Function rate with observable dependency, not a zero Elementary rate), and
   an execution check against an analytic law (first-event rate and detailed
   balance), plus a static-energy regression proving no behavior change.

### Stage 2 — Dynamic population-map rates (implemented 2026-11-19)

Status: the supported simple shape executes (synthesized map rules with runtime
observable re-evaluation) with independent pure-death analytic checks and a
wired hosted-CI case. Unsupported shapes still fail closed. Pinned-native NFsim
parity and full release acceptance remain in Stage 3/4.

1. Establish the hybrid lowering boundary: dynamic population-map rates are
   consumed by `generate_hybrid_model`, not by the raw `population maps`
   block. Execution of `hybrid.execution` is #150 and depends on the whole
   conversion/conservation semantics.
2. Extend `executeFromBioNetGen` to execute lowered hybrid models whose mapped
   rates resolve to observable/population-count expressions, while continuing
   to refuse un-lowered maps. Add conservation and analytic mass-action checks.
3. Explicitly unsupported forms stay refused with a named diagnostic.

### Stage 3 — Independent parity and evidence
- Analytic laws (detailed balance, mass-action mean) for each new executor.
- Native pinned NFsim / BNG2 differential comparison where a canonical oracle
  exists; barrier/reservoir extensions use analytic invariants only, per
  DECISIONS item 16. For the dynamic population-map law a valid independent
  native encoding was built (pinned BNG2 XML of an equivalent `k*U` degradation
  law, with the documented `U()` → `U` spelling translation) and passed a
  512-seed law comparison. Observable-dependent energy is outside the pinned
  native oracle by construction (`evaluateEnergyExpression` binds parameters
  only), so its analytic law is the valid oracle and native parity is recorded
  `NOT_TESTED`.
- Wire the focused checks into the existing architecture-contract CTest spine
  and record exact-revision evidence; do not count a structural check as an
  execution check.

### Stage 4 — Qualification and promotion (separate, not in this increment)
- Full pinned-native corpus + NFcore comparison for every network-free row
  (#148/#149) on `main`, including seeds, observables, functions, protocol and
  output initialization.
- Only after that gate: switch `method="nf"` to NFnext, keep NFcore selectable,
  retire NFcore2 from the default build (#149). NFcore remains the default
  throughout this increment.

## Hosted exact-main gate (remaining, not executable from an uncommitted tree)

Local work above is evidence for the product semantics, not issue closure.
`AGENTS.md` requires a single-issue snapshot whose live body is `CLOSED`, plus
exact-main consuming reports, for:

```bash
python -m tests.validation.issue_queue --require-closed-acceptance \
  --issues-json <single-issue snapshot> --revision <exact main SHA> ...
```

The two new cases are wired as separate steps of the hosted `BNG3 vs
independent NFsim` lane (`.github/workflows/parity.yml`), so once these changes
are published at a `main` SHA they will produce the dynamic-energy analytic
artifact and the dynamic-map analytic + pinned-native artifacts. Until a hosted
run at that exact SHA exists, no `release-*` identity can be promoted, the
issues cannot be closed, and NFcore remains the default per DECISIONS item 4.
Publishing to `main` (or opening/merging a PR) is a maintainer action; it was
not performed from this session.

## Non-goals for this increment
- Retiring NFcore, changing the default backend, or claiming `nfnext.full`
  execution coverage.
- Treating refusal controls or representational tests as support evidence.
- Adding approximations for semantics whose oracle is unresolved.
