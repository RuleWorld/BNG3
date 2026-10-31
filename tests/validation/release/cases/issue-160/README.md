# Issue 160: Disposition unsupported SBML semantics by feature class

This directory provides the acceptance qualification suite and evidence mapping for **Issue #160 (E04: Disposition unsupported SBML semantics by feature class)**.

## Goal and Decisions

Issue #160 covers SBML Level 3 Core and comp semantics, specifically focusing on remaining semantic families:
- **Fast reactions** (SBML Level 3 Version 1 Core Sec. 4.11; SBML Level 2 Sec. 4.13)
- **General algebraic rules** (SBML Level 3 Version 2 Core Sec. 4.9.2)
- **State-dependent delays** (SBML Level 3 Version 2 Core Sec. 3.4.6)

Every translation must preserve source semantics exactly:
- `release-sbml-core-comp`: Assigned Core/comp rows pass official expected values, independent flattening, or analytic checks.
- `release-sbml-source-fidelity`: No valid required construct is omitted, frozen dynamically, approximated, or reported as successful execution after refusal.
- `release-capability-coverage-160`: All assigned inventory cases execute against their row's named independent oracle or emit maintained explicit exclusions with structured loss diagnostics.

## Triage and Case Ranking from Campaign Evidence

Analysis of `provenance/sbml-campaign/current-2026-10-22.json` and `docs/ATOMIZER_LIMITATIONS.md` identifies 9 key official SBML Test Suite cases spanning these families:

| Case ID | Feature Family | Reason Signature | Causes | BNG3 Behavior & Disposition |
|---|---|---|---|---|
| `semantic/00987` | Fast Reactions | `fast-reaction:no-fast-equilibrium-solve` | `fast_reactions` | Event sets rate constant of fast reaction; steady state moves discontinuously. Refused with explicit loss diagnostic. |
| `semantic/00988` | Fast Reactions | `events:state-trigger-not-schedulable` | `events`, `fast_reactions`, `mathml` | Event with state trigger sets fast reaction rate constant. Refused at event scheduling boundary. |
| `semantic/01398` | Fast Reactions | `fast-reaction:no-fast-equilibrium-solve` | `events`, `fast_reactions`, `stoichiometry` | Event changes reaction stoichiometry in fast reaction. Variable stoichiometry prevents fast equilibrium solve. |
| `semantic/01568` | Fast Reactions | `fast-reaction:no-fast-equilibrium-solve` | `fast_reactions` | Fast reaction rate constant follows a continuous rate rule. Refused with explicit loss diagnostic. |
| `semantic/01570` | Fast Reactions | `fast-reaction:no-fast-equilibrium-solve` | `fast_reactions` | Fast reaction rate constant follows a continuous assignment rule. Refused with explicit loss diagnostic. |
| `semantic/00761` | Algebraic Rules | `events:untranslated` | `algebraic_rules`, `constraints`, `events` | Linear species algebraic constraint `(1+k3)*S1 - T = 0`. Solved exactly to an assignment rule by `_lower_simple_algebraic_parameters`; passes official conformance test. |
| `semantic/01575` | Algebraic Rules | `events:state-trigger-not-schedulable` | `events`, `mathml` | Linear algebraic rule over rate-ruled parameters (`k1 - k2 = 0`) with persistent delayed event. Passes official reference with delayed reset. |
| `semantic/00985` | Delay History | `sbml-writer:unrepresentable-function` | `mathml` | Rate rule contains `delay(x, tau)`. Emits explicit diagnostic identifying unrepresentable delay function. |
| `semantic/01142` | Delay History | `sbml-writer:unrepresentable-function` | `mathml` | Assignment rule contains `delay(x, tau)`. Emits explicit diagnostic identifying unrepresentable delay function. |

## Running Acceptance Checks

Run the issue-160 validation suite from repository root:

```sh
PYTHONPATH=python:build/cpp python -m pytest -q \
  tests/validation/release/cases/issue-160/test_sbml_semantic_families.py
```
