# Issue #147: Extend NFnext Lowering for Approved Unsupported Semantic Families

## Overview

This case establishes the independent release qualification for **Issue #147 (C02)**:
"Extend NFnext lowering for approved unsupported semantic families."

BNG3 provides an execution-oriented rule-based model representation (NFIR) and lowering engine:
1. **Production Translation Path**: `compile::CompiledModel` to `nfnext::ModelIR` (NFIR) via `nfnext::lowerFromBioNetGen` (`cpp/nfnext/src/from_bng.cpp`).
2. **Fail-Closed Semantic Boundaries**: Semantic constructs are lowered with complete lossless semantics or refused explicitly by name (`BngLoweringSeverity::Error`), never silently approximated.
3. **Execution Prototype**: Unary site-state rules with static elementary rates, integer seed populations, and unary `Molecules` observables execute via `nfnext::executeFromBioNetGen`.

## Candidate Semantic Families (7 Slices)

| Family | Status | Lowering Boundary | Execution Boundary | Reference Oracle |
|---|---|---|---|---|
| `unary-site-state` | **Supported** | Lowers to elementary `RuleIR` with `PredicateIR` and `ActionIR::SetSiteState` | Executes exact Poisson jumps | Pure-death Markov law: $\mathbb{E}[U(t)] = N_0 e^{-kt}$, within $4.0\sigma$ |
| `dynamic-rates` | **Refused** | Refused by name (`dynamic rate`) | Refused by name | Source construct detection |
| `filters` | **Refused** | Refused by name (`filter`) | Refused by name | Source construct detection |
| `modifiers` | **Refused** | Refused by name (`modifier`) | Refused by name | Source construct detection |
| `compartments` | **Refused** | Refused by name (`compartment`) | Refused by name | Source construct detection |
| `population-maps` | **Refused** | Refused by name (`population map`) | Refused by name | Source construct detection |
| `energy` | **Refused** | Refused by name (`energy pattern`) | Refused by name | Source construct detection |

## Acceptance Checks

- `release-nfir-lowering`: every network-free inventory row lowers with complete semantics and validated IDs.
- `release-nfir-roundtrip`: independently authored canonical model facts agree with NFIR and native NFsim input facts.
- `release-obligation-147`: each task above has its named check result, source/oracle identity and main commit recorded. All 21 family slice checks (representation, executor, and independent-reference across all 7 families) pass with explicit failure reporting for negative controls.
