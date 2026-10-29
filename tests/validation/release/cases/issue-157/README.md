# Issue 157 dynamic-event acceptance

`test_dynamic_threshold.py` isolates the failed trigger shape in official SBML
Test Suite case `semantic/00966`: a recurring `time - reset >= 0.01` event
increments a discrete counter, and a second event fires when
`floor(ticks / 16) >= 1`. The official source model has two equal-priority
increment events; that random execution order makes its single official
reference trajectory unsuitable for pointwise conformance. This reduced model
uses one increment per period and checks the independent analytic schedule:
8 events at `t=0.085`, then 16 events and `complete=1` at `t=0.165`.

The first test validates the authored SBML source with libSBML and checks its
sampled trajectory with libRoadRunner. The native tests run a manually lowered
BNGL `bng3_events` model through the public API. A control containing only the
recurring `time - reset` trigger checks that root independently; the second
adds the floor trigger and checks that it fires after the sixteenth discrete
update. These tests isolate native event execution and do not test Atomizer's
translation. The floor-trigger test is expected to fail on current source at
the root-surface guard because `floor(ticks / 16)` is not recognized as a
dynamic trigger side.

Run from the repository root after the SBML dependency preflight has installed
NumPy, pytest, libSBML, libRoadRunner and this worktree's freshly built native
extension:

```sh
PYTHONPATH=python:build/cpp python -m pytest -q \
  tests/validation/release/cases/issue-157/test_dynamic_threshold.py
```

The full official suite and issue acceptance remain CI work. This directory is
not yet discovered by a CI workflow; wire this command into the issue-157
acceptance job when that lane is added.
