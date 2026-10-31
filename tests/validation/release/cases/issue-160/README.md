# Issue 160: diagnostic controls for required Core/comp semantics

This directory retains diagnostic, historical-triage and lowering controls related to [issue #160](https://github.com/RuleWorld/BNG3/issues/160). A passing pytest result here is not release acceptance or proof of supported execution.

## Goal and Decisions

Issue #160 requires every one of its 117 assigned Core/comp inventory rows, including assignment/rate/algebraic rules, delays, constraints, conversion factors, dynamic stoichiometry, MathML and the full comp hierarchy. The controls here sample three families; they do not narrow that scope:
- **Fast reactions** (SBML Level 3 Version 1 Core Sec. 4.11; SBML Level 2 Sec. 4.13)
- **General algebraic rules** (SBML Level 3 Version 2 Core Sec. 4.9.2)
- **State-dependent delays** (SBML Level 3 Version 2 Core Sec. 3.4.6)

Every translation must preserve source semantics exactly:
- `release-sbml-core-comp`: Assigned Core/comp rows pass official expected values, independent flattening, or analytic checks.
- `release-sbml-source-fidelity`: No valid required construct is omitted, frozen dynamically, approximated, or reported as successful execution after refusal.
- `release-capability-coverage-160`: All 117 assigned inventory cases execute against their row's named independent oracle and pass on main. Missing cases, refusals of valid required input, timeouts and harness errors cannot count as passes.

The existing `provenance/issue-obligations.json` registry declares these three checks and the 117 `release-capability[ID]` checks independently of test execution. Each requires the exact source revision, subject digest and an independent oracle revision/artifact digest under `references.sbml` (the official suite, independent flattening, or analytic derivation named by the row). Missing identities remain evidence gaps. The assessor checks identity presence; the receipt producer must verify pinned oracle identity and consumed artifact digests. The synthetic negative receipts here test rejection only and establish no product or artifact provenance. They require supported execution; no diagnostic or historical pytest pass can discharge them. This directory does not produce those execution receipts. The negative control independently validates a required L3V1 fast-reaction input with libSBML and verifies that its loss diagnostic remains an evidence gap in the existing obligation assessor.

The decisions in `docs/DECISIONS.md` preserve the full required scope. Fast-reaction, general algebraic-rule and delay-history implementation remains separate product work. Refusal diagnostics remain useful controls, never exclusions from release requirements.

## Historical triage (not current qualification)

The dated `provenance/sbml-campaign/current-2026-10-22.json` snapshot records these nine illustrative cases. Assertions against it check historical data only. Current outcomes require exact-revision hosted execution; the table is neither a complete denominator nor a current pass claim.

| Case ID | Feature Family | Reason Signature | Causes | Historical context / diagnostic boundary |
|---|---|---|---|---|
| `semantic/00987` | Fast Reactions | `fast-reaction:no-fast-equilibrium-solve` | `fast_reactions` | Event sets rate constant of fast reaction; steady state moves discontinuously. Refused with explicit loss diagnostic. |
| `semantic/00988` | Fast Reactions | `events:state-trigger-not-schedulable` | `events`, `fast_reactions`, `mathml` | Event with state trigger sets fast reaction rate constant. Refused at event scheduling boundary. |
| `semantic/01398` | Fast Reactions | `fast-reaction:no-fast-equilibrium-solve` | `events`, `fast_reactions`, `stoichiometry` | Event changes reaction stoichiometry in fast reaction. Variable stoichiometry prevents fast equilibrium solve. |
| `semantic/01568` | Fast Reactions | `fast-reaction:no-fast-equilibrium-solve` | `fast_reactions` | Fast reaction rate constant follows a continuous rate rule. Refused with explicit loss diagnostic. |
| `semantic/01570` | Fast Reactions | `fast-reaction:no-fast-equilibrium-solve` | `fast_reactions` | Fast reaction rate constant follows a continuous assignment rule. Refused with explicit loss diagnostic. |
| `semantic/00761` | Algebraic Rules | `events:untranslated` | `algebraic_rules`, `constraints`, `events` | Linear species algebraic constraint `(1+k3)*S1 - T = 0`. Subset lowering is tested separately; the snapshot records unsupported conversion and does not establish current execution. |
| `semantic/01575` | Algebraic Rules | `events:state-trigger-not-schedulable` | `events`, `mathml` | Linear algebraic rule over rate-ruled parameters (`k1 - k2 = 0`) with persistent delayed event. The snapshot records unsupported conversion; no current execution is established by these controls. |
| `semantic/00985` | Delay History | `sbml-writer:unrepresentable-function` | `mathml` | Rate rule contains `delay(x, tau)`. Emits explicit diagnostic identifying unrepresentable delay function. |
| `semantic/01142` | Delay History | `sbml-writer:unrepresentable-function` | `mathml` | Assignment rule contains `delay(x, tau)`. Emits explicit diagnostic identifying unrepresentable delay function. |

## Running diagnostic controls

The parity workflow runs these controls with their negative acceptance guard. Run locally from repository root:

```sh
PYTHONPATH=python:. python -m pytest -q \
  --confcutdir=tests/validation/release/cases/issue-160 \
  tests/validation/release/cases/issue-160/test_sbml_semantic_families.py
```
