# Issue #152 Release Case Package: Energy, Rasi and Protocol Capabilities

**Closure audit (2026-11-14): incomplete acceptance.** Five canonical source-linked fixtures run BNG3; motor/TQSSA have bounded analytic checks and others have initial-state/invariant checks. real_model_fixtures.py runs only the product, not a pinned native-NFsim comparison for each canonical fixture. Three fixture families have no trajectory law beyond invariants. test_energy_protocols.py Ising checks conservation; theoretical affinity arithmetic is separate from product rates. This does not establish the complete canonical behavior required by release-energy-protocols. See docs/CURRENT_PROGRESS.md for the assessed revision and retained evidence.

This package validates the release acceptance criteria and obligations for **Issue #152** ("C07: Reconcile newer NFsim energy, Rasi and protocol capabilities") under maintainer Decisions 4 and 16 (`docs/DECISIONS.md`).

## Overview and Reconciled Scope

Issue #152 addresses the qualification and reconciliation of newer NFsim capabilities across energy-based rules, source-linked real-model fixtures, and protocol executions:

1. **Source Behavior Review & Reconciliation**:
   - Reconciles upstream NFsim cutoff revisions (`9b00d42f734dcc3e695205600f12cae5b44d1daa` through `a6f9fa945c9d6e1e122e789c952260112c93f157`) documented in `provenance/reconciliation/nfsim.yml`.
   - Classifies absolute start time, time functions, observable-dependent propensity refreshes, and unsupported controls as incorporated or explicitly excluded.
2. **Source-Linked Real-Model Fixture Corpus**:
   - Five real-model families vendored byte-identically from canonical NFsim at pinned revision `9b00d42f734dcc3e695205600f12cae5b44d1daa`:
     - `rna-uorf` (`test/RNA/rna_synthesis3.bngl`): multi-step transcript synthesis with conservation of nucleotide/complex pools.
     - `motor` (`test/motor/motor.bngl`): flagellar motor phosphorylation switch with closed two-state Markov chain analytic solution.
     - `tqssa` (`test/TQSSA/gk_simple.bngl`): Goldbeter-Koshland zero-order ultrasensitivity with exact mass-action algebraic steady-state root.
     - `fceri` (`models/fceRI_compendium/fceri_ji.bngl`): high-affinity IgE receptor signaling complex with ligand and receptor conservation laws.
     - `multisite-protocol` (`test/il2/il2.bngl`): interleukin-2 receptor complex formation with multi-chain stoichiometric conservation.
   - Every vendored model is verified against its source SHA256 digest in `tests/validation/fixtures/nfsim/SOURCES.json`.
3. **Canonical Energy Constructs**:
   - Validates eBNGL Arrhenius rate laws, energy pattern evaluation, and detailed balance on canonical systems (`isingspin_energy.bngl`, literal conjunction energy patterns).
4. **Nonequilibrium Energy Additions & Protocols**:
   - Verifies transition-state barriers and driving chemical work ($W$) under protocol execution (equilibration protocols, parameter scans across driving work, NESS currents).
   - Verifies cycle affinity $A = \sum W_i$ and Kolmogorov cycle criteria.
   - Enforces fail-closed refusal when experimental gate `BNG_NFSIM_GENERAL_ENERGY` is disabled.

## Acceptance Checks

1. `release-energy-protocols`:
   - Executes the source-linked real-model fixture corpus with native NFsim.
   - Verifies exact invariant preservation across all 5 families (`rna-uorf`, `motor`, `tqssa`, `fceri`, `multisite-protocol`).
   - Verifies closed-form analytic solutions for the flagellar motor two-state chain and TQSSA mass-action steady state.
   - Verifies canonical Ising spin energy pattern execution.
2. `release-extension-protocols`:
   - Verifies nonequilibrium extensions (barriers and reservoirs) under multi-stage protocol execution.
   - Tests parameter scans across driving work $W$, verifying monotonic shift of nonequilibrium steady-state observables and positive entropy production / cycle affinity.
   - Verifies detailed balance preservation with transition barriers and cycle affinity departure under driving chemical work.
3. `release-obligation-152`:
   - Verifies contract schema validity, closure records, and full obligation coverage.
   - Verifies negative containment: models with barrier patterns or driving reservoirs fail closed when `BNG_NFSIM_GENERAL_ENERGY` is unset.
   - Verifies upstream reconciliation records in `provenance/reconciliation/nfsim.yml`.
