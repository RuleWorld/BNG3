# Issue 475: Delayed-rule semantics across formats and engines

**Closure audit (2026-11-14): incomplete acceptance.** Existing native ODE method-of-steps, continuation and BNGIR delayed-rule tests remain useful. New SSA wrapper calls continuation examples rather than an independent delayed-jump distribution comparison. The SBML formats case conditionally parses then checks only file existence; it does not export/reimport/execute. BngsimAdapter still invokes requireNoDelayedSemantics; complete applicable backend/format behavior is unfinished. See docs/CURRENT_PROGRESS.md for the assessed revision and retained evidence.

This directory defines the release acceptance contract and qualification tests for Issue #475.

## Coverage
- `release-delay-ode`: Analytic DDE histories and method-of-steps exact solutions agree with native ODE execution across intervals, prehistory, and discontinuities.
- `release-delay-ssa`: Independent delayed jump-process reference verifies initiation/completion and NonConsuming distributions, continuation across runs, and queue state recovery.
- `release-delay-formats`: Lossless roundtrip of delayed rules in both BNGIR versions (v0.1 and v0.2), SBML Level 3 Version 2 `<csymbol>` delay and rateOf exports and re-imports through actual consumers.
- `release-capability-coverage-475`: Full capability matrix and issue obligation crosswalk verification.
