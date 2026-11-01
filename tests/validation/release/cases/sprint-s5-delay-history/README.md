# Nonconstant SBML delay/history detector

This three-case source family tests `y = delay(x, z/2)` with a time-varying
state clock `dz/dt = 1`, `z(0)=0`, and nonconstant `x`, `dx/dt = k`, `x(0)=1`.
The delay is therefore state-dependent and nonnegative on `[0, 2]`, but is not
in #548's subset where the delayed value is proven constant over the requested
interval.

The `ordinary` case keeps `k=1`, giving `x(t)=1+t` and `y(t)=1+t/2`. The
`boundary` case changes `k` from 1 to 3 at `t=0.5`; `y` reads the history at
`t=0` with zero lag and crosses the event history at `t=1`. The interaction
case uses the same event and continues one trajectory over `[0,0.4]`,
`[0.4,0.8]`, `[0.8,1.2]`, and `[1.2,2]`. Its exact laws are recorded in
`case_contract.py`; in particular, after the event, `x(t)=1.5+3(t-0.5)` and
`y(t)=1.5t` for `t>1`.

`q = delay(k, z/2)` in the boundary and interaction cases exposes the exact
history jump. The SBML event changes `k` instantaneously at `t=0.5`; at the
event time the model output is the value after all simultaneous event
assignments, so `q(1)=3`, while `q(t)=1` for `t<1`. `y` stays continuous at
`t=1` but changes slope there. The zero-duration sample at `t=0` is defined
without querying negative-time history.

## Source basis

The expectations are derived from the raw equations, independently of BNG3.
SBML L3V2 Core Release 2 §3.4.6 defines `delay(x,d)` as `x` evaluated `d`
before the current time, allows any first-argument form, and requires a
nonnegative numerical duration. Section 3.4.8 specifies how initial values and
rules extend over pre-simulation time; these fixtures avoid that domain because
`t-z/2=t/2 >= 0`. Section 4.12.7 defines trigger transitions and event
execution; event assignments are instantaneous, and output at an event time is
the value at the end of processing simultaneous events.

Specification: [SBML Level 3 Version 2 Core Release 2](https://sbml.org/specifications/sbml-level-3/version-2/core/release-2/sbml-level-3-version-2-release-2-core.pdf)
(§3.4.6, §3.4.8, §4.12.7). The validation harness first checks each raw file
with libSBML. It then runs raw-source libRoadRunner as a secondary independent
oracle and separately runs the BNG3 Atomizer/native public path where the
candidate build is available. A source-oracle limitation is reported
independently from a BNG3 result.

## Local replay on the assessed base

The focused replay used product source `9c6fd7ee0862405d08217703a280e56da74de206`,
libSBML 5.21.1, libRoadRunner 2.10.0, Python 3.14.6, and the exact command
below. Source validation, the closed-form reference self-check, and Atomizer
lowering passed for all three cases. Raw-source libRoadRunner returned
`ORACLE_UNAVAILABLE` for all three because it reports that the `delay(x, z/2)`
DDE form is unsupported. This local environment lacks the compiled
`_bionetgen_cpp` extension, so native public execution, output comparison, and
the interaction continuation are `NOT_TESTED`; each overall scientific verdict
is `MISSING_EVIDENCE`. These are harness results, not a BNG3 pass or product
failure. Raw source hashes and full per-stage replay receipts are retained in
the S5 outbox for this run.

| Case | Raw SBML SHA-256 | Source | Analytic law | Atomizer | libRoadRunner | Native execution / output / continuation | Overall |
|---|---|---|---|---|---|---|---|
| ordinary | `f9e266f7c51fd2ed29c1d169f3b2aa1b6be7418e45f6b1395cf86371d44d09da` | PASS | PASS | PASS | ORACLE_UNAVAILABLE | NOT_TESTED | MISSING_EVIDENCE |
| boundary | `5dadfcc942a95fb0882aa55490b187066ac8c970ddc667b8a6fc1be05237a2d5` | PASS | PASS | PASS | ORACLE_UNAVAILABLE | NOT_TESTED | MISSING_EVIDENCE |
| interaction | `d227f409bf6680512ca6252d63b1fa4f82ea612fdccc74b7969365825a53de09` | PASS | PASS | PASS | ORACLE_UNAVAILABLE | NOT_TESTED | MISSING_EVIDENCE |

Run the focused detector from the repository root:

```sh
PYTHONPATH=python:. python -m pytest -q \
  --confcutdir=tests/validation/release/cases/sprint-s5-delay-history \
  tests/validation/release/cases/sprint-s5-delay-history/test_delay_history.py
```

To capture raw source, emitted BNGL, outputs, stage verdicts, commands, and
digests in the sprint outbox, run:

```sh
PYTHONPATH=python:. python \
  tests/validation/release/cases/sprint-s5-delay-history/replay.py \
  --out /tmp/bng3-sprint-20261101-coordination/outbox/S5/replay
```
