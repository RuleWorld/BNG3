# Issue acceptance dashboard

Candidate: `12dace48a92bd70d08f2f76bebb7dac3d6206b60`. No automatic closure. Campaigns are plans only.

| Rank | Issue | Obligation outcomes | Next concrete obligations |
| --- | --- | --- | --- |

## Closed issues with unverified acceptance

These closures need evidence reconciliation; missing current evidence does not by itself establish a product defect or invalidate historical results.
- #176: issue:176:acceptance:1, issue:176:acceptance:2. Reconcile the closure against the complete live contract.

Ranking (live OPEN issues only; inactive evidence is retained below): confirmed failing obligations, shared selected-family impact, then remaining obligations. Counts are not completion percentages.

## Evidence audit

- {'report': 0, 'status': 'UNVERIFIABLE', 'source': {'revision': '12dace48a92bd70d08f2f76bebb7dac3d6206b60', 'dirty': True}}

## #176 (CLOSED)

{'confirmed_failures': 0, 'remaining': 6, 'shared_issues': 0}. Confirmed failing obligations first, then shared selected-family impact, then concrete remaining obligations; decisions and unmapped scope remain blocking.

- `issue:176:reconcile-the-old-plan-with-implemented-cpu-work-and-current-wor` **NOT_TESTED**: Reconcile the old plan with implemented CPU work and current workload profiles; distinguish network SSA from network-free execution.. Checks: workload-profile:family:plan-reconciliation=NOT_TESTED, workload-profile:family:environment-record=NOT_TESTED, workload-profile:conversion:network-ssa-timing=NOT_TESTED, workload-profile:conversion:network-free-timing=NOT_TESTED, workload-profile:conversion:execution-mode-comparison=NOT_TESTED, workload-profile:dimerization:network-ssa-timing=NOT_TESTED, workload-profile:dimerization:network-free-timing=NOT_TESTED, workload-profile:dimerization:execution-mode-comparison=NOT_TESTED, workload-profile:conversion:aa-control=NOT_TESTED, workload-profile:dimerization:aa-control=NOT_TESTED. Decisions: []. Unmapped: ['The reconciliation reads the recorded plan document and probes the implemented surface item by item; an item the build does not implement is recorded as absent, and the maintainer decides what that means for the roadmap.', "The measured profile covers two bounded generated model classes on one host; the numbers are machine-specific and are not a portable speed claim, and the plan's own model classes remain unqualified.", "The A/A control refuses a timing when the host's repeatability spread exceeds the limit, so a noisy host produces no timing result instead of an unreliable one.", 'Producer/consumer boundary and feature combinations require review; issue-level test references are relevance only.', 'Live issue body differs from reviewed scope; reconcile before demonstrating acceptance.'].
- `issue:176:qualify-retained-ensemble-isolation-scope-and-pursue-device-kern` **NOT_TESTED**: Qualify retained ensemble/isolation scope and pursue device kernels only for measured supported classes with independent parity.. Checks: workload-profile:family:execution-mode-distinction=NOT_TESTED, workload-profile:family:ensemble-qualification=NOT_TESTED, workload-profile:family:device-kernel-qualification=NOT_TESTED. Decisions: []. Unmapped: ['The reconciliation reads the recorded plan document and probes the implemented surface item by item; an item the build does not implement is recorded as absent, and the maintainer decides what that means for the roadmap.', "The measured profile covers two bounded generated model classes on one host; the numbers are machine-specific and are not a portable speed claim, and the plan's own model classes remain unqualified.", "The A/A control refuses a timing when the host's repeatability spread exceeds the limit, so a noisy host produces no timing result instead of an unreliable one.", 'Producer/consumer boundary and feature combinations require review; issue-level test references are relevance only.', 'Live issue body differs from reviewed scope; reconcile before demonstrating acceptance.'].
- `issue:176:closure-record` **NOT_TESTED**: Record implementation or disposition, exact revision, validation commands and results, and remaining limits.. Checks: qualification:issue:176:closure-record=NOT_TESTED. Decisions: []. Unmapped: ['Missing required qualification ID: qualification:issue:176:closure-record.', 'Producer/consumer boundary and feature combinations require review; issue-level test references are relevance only.', 'Live issue body differs from reviewed scope; reconcile before demonstrating acceptance.'].
- `issue:176:live-acceptance:release-nf-ensemble` **NOT_TESTED**: `release-nf-ensemble`: CPU concurrency/RNG isolation and native NFsim distribution checks pass with fixed run budgets and error control.. Checks: release-nf-ensemble=NOT_TESTED. Decisions: []. Unmapped: [].
- `issue:176:live-acceptance:release-nf-gpu` **NOT_TESTED**: `release-nf-gpu`: actual GPU kernels execute the network-free corpus with independent law checks and recorded performance.. Checks: release-nf-gpu=NOT_TESTED. Decisions: []. Unmapped: ['Live issue body differs from reviewed scope; reconcile before demonstrating acceptance.'].
- `issue:176:live-acceptance:release-capability-coverage-176` **NOT_TESTED**: `release-capability-coverage-176`: all CPU/ensemble work clauses execute through production entry points with independently checked outputs and measured startup, memory and throughput on main. GPU row backend.gpu and release-nf-gpu are owned by #474.. Checks: release-capability-coverage-176=NOT_TESTED. Decisions: []. Unmapped: [].

## Bounded campaign plans


Strict approval blockers: 0; stale reconciliation references: 0.
Reconciliation test references are source evidence, not proof of current execution. See issue-queue.json for named claims and upstream observations.
