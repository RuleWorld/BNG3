# Issue acceptance dashboard

Candidate: `641a2e144a4ce8cc8cf20305fd289288477c6524`. No automatic closure. Campaigns are plans only.

| Rank | Issue | Obligation outcomes | Next concrete obligations |
| --- | --- | --- | --- |

## Closed issues with unverified acceptance

These closures need evidence reconciliation; missing current evidence does not by itself establish a product defect or invalidate historical results.
- #474: issue:474:acceptance:3, issue:474:acceptance:4, issue:474:acceptance:5, issue:474:acceptance:6. Reconcile the closure against the complete live contract.

Ranking (live OPEN issues only; inactive evidence is retained below): confirmed failing obligations, shared selected-family impact, then remaining obligations. Counts are not completion percentages.

## Evidence audit


## #474 (CLOSED)

{'confirmed_failures': 0, 'remaining': 4, 'shared_issues': 0}. Confirmed failing obligations first, then shared selected-family impact, then concrete remaining obligations; decisions and unmapped scope remain blocking.

- `issue:474:live-acceptance:release-cuda-device` **NOT_TESTED**: `release-cuda-device`: actual CUDA kernels execute with recorded NVIDIA device/toolchain/source identity and independent scientific/RNG checks.. Checks: release-cuda-device=NOT_TESTED. Decisions: []. Unmapped: [].
- `issue:474:live-acceptance:release-cuda-performance` **NOT_TESTED**: `release-cuda-performance`: reproducible CUDA measurements include CPU/native references, transfer/crossover costs and correctness evidence.. Checks: release-cuda-performance=NOT_TESTED. Decisions: []. Unmapped: [].
- `issue:474:live-acceptance:release-metal-device` **DEMONSTRATED**: `release-metal-device`: actual Metal kernels execute with recorded Apple device/toolchain/source identity and independent scientific/RNG checks.. Checks: release-metal-device=PASS. Decisions: []. Unmapped: [].
- `issue:474:live-acceptance:release-metal-performance` **DEMONSTRATED**: `release-metal-performance`: reproducible Metal measurements include CPU/native references, transfer/crossover costs and correctness evidence.. Checks: release-metal-performance=PASS. Decisions: []. Unmapped: [].
- `issue:474:live-acceptance:release-nf-gpu` **NOT_TESTED**: `release-nf-gpu`: actual network-free GPU execution matches independent source laws and pinned native NFsim across the required corpus; report Metal and CUDA separately. Transferred unchanged in intent from #176.. Checks: release-nf-gpu=NOT_TESTED. Decisions: []. Unmapped: [].
- `issue:474:live-acceptance:release-capability-coverage-474` **NOT_TESTED**: `release-capability-coverage-474`: backend.gpu is covered by actual backend-specific executions and consuming receipts; missing hardware, refusals, compilation and fallback cannot count as passes.. Checks: release-capability-coverage-474=NOT_TESTED. Decisions: []. Unmapped: [].

## Bounded campaign plans


Strict approval blockers: 0; stale reconciliation references: 0.
Reconciliation test references are source evidence, not proof of current execution. See issue-queue.json for named claims and upstream observations.
