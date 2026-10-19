# Issue #141 acceptance receipt

**Disposition:** incomplete; closure eligible: **false**. This packet qualifies lifecycle behavior and records a native cleanup defect. It makes no product repair. A public compiled-model handle or compile-once reuse is still absent: native ODE/SSA constructs a new `OdeIntegrator` per call. Cached `GeneratedNetwork` reuse is not compiled-model reuse.

**Revision identity:** implementation base `9af03d79d48c7488a1ffe98ced270053b27478bd`; qualification checkpoint `aae3bfcebae5addfa28d107d6c57a004c231bdd7`. The latter changes tests/workflow only. The publishing commit adds this receipt only; hosted checks must match the final PR head. Issue body SHA-256: `2b06a72fc9ead82926823a598c880478973e48e5343d6bf5b7ed3a19fcac48c4`.

The issue's three acceptance criteria remain unverified as whole criteria:

1. Repeated/concurrent instantiation, independent RNG/cache/solver ownership, and exception cleanup: prior reset, seeded-repeat, and construction-isolation slices are demonstrated. The current bounded lifecycle/source-control report is diagnostic only because its native binary lineage is unverified. The new native late-failure test exists but was not built locally; its exact-head ASan/LSan run is pending.
2. Parameter-only reuse and topology/compartment invalidation against fresh compilation: source controls matched fresh results in the diagnostic binary. `set_parameter` currently clears the generated-network cache; no public topology mutation API is available. Neither establishes compiled-model reuse or topology invalidation. Those scopes remain incomplete/unsupported at the public API boundary.
3. Implementation/disposition, exact revision, commands/results, and limits: recorded here and in the JSON receipt, with exact-head native evidence pending.

The source-confirmed exception path is `stop_if='if(time > 0, missing_name, 0)'`: lazy `if` evaluation succeeds at `t=0`, then raises after CVODE allocation. The exception bypasses normal CVODE cleanup. The focused C++ regression is `OdeIntegrator recovers after late stop condition failure` in `tests/cpp/test_ode_options.cpp`; the existing ASan workflow now selects it with leak detection enabled. No exact-head LSan result is available yet. A separate installed binary (SHA-256 `3c17f1a145ab56dca0c5cf0bd0da21997dee93b8c03cbf2a20c8d8b26c9d53af`, lineage **UNVERIFIED**) showed peak RSS increasing from 47,923,200 to 60,751,872 bytes over 1,001 late failures; early-failure and valid controls remained nearly flat. This is diagnostic corroboration, not exact-head leak proof.

The focused local command reported **110 passed**:

```text
python -m pytest -q tests/validation/test_integrated_protocol.py tests/validation/test_integrated_wiring.py tests/validation/test_acceptance_queue.py tests/test_ci_contract.py tests/validation/test_parity_workflow_wiring.py
```

Black target py312, Ruff, and diff checks passed for changed files. The provenance structural validator passed with its baseline pending-approval warning. The new C++ regression was not built locally. A known unrelated baseline Black failure in `tests/python/test_atomizer_copy_regressions.py` is owned by PRs #310/#311; it is separate from this receipt. No broad suite or local native build is claimed.

The bounded source-control worker recorded 8 PASS and 1 UNSUPPORTED check; all are **diagnostic only**. The run used the same implementation base while qualification edits were uncommitted, and its native binary lineage is unverified. The dimerization control recorded two lifecycle checks with no first differences under the same limitation. Topology-unavailable evidence is not successful invalidation. These reports do not establish supported scientific execution, exact-head semantic parity, or closure.

Related PR snapshots remain open and were captured before this receipt was written. Snapshot files were timestamped 2026-10-19 23:39:06–09 UTC; this receipt reconciles them at **2026-10-19T23:42:19Z**, without claiming a new GitHub refresh. PR #310 owns native BNGIR/multi-pattern and NFsim normalization (head `58ea3e6f6041ed4a0d548ebb92e1de3f21dfe433`; 9 success, 12 queued, 1 skipped). PR #311 owns reporting/oracle/release qualification (head `684af43846d99175707a42912dc6d1b547aeb074`; 16 queued). PR #312 owns the dimension diagnostic (head `6c94f3d369dcb84721dc063a70ddb2e1982adc97`; 16 queued). Per-PR JSON and run snapshots, paths, and hashes are retained in `docs/packet4-141-acceptance.json`.

Remaining limits include exact-head native/LSan execution; mutation concurrent with simulation; independent native NFsim lifecycle/oracle checks; general cache checks under ThreadSanitizer; stochastic distributional parity; and other solver/features. The named obligations and their evidence states are preserved individually in the JSON receipt. No obligation is upgraded from diagnostic evidence, API unavailability, or an unexecuted test.

The JSON retains the complete minimal BNGL/Python reproducer, exact-head PR run/check snapshots, and source pointers for integrator/RNG/cache/scan ownership. Prior demonstrated slices come from the [existing release audit](https://github.com/RuleWorld/BNG3/blob/684af43846d99175707a42912dc6d1b547aeb074/docs/release-audit-2026-10-19.json), not this diagnostic execution. All 13 full `qualification:issue:141:*` check identities remain `NOT_TESTED`; source assessment and narrower prior slices do not fill those missing checks. Numeric volume-parameter mutation has diagnostic coverage; structural compartment editing remains unsupported.
