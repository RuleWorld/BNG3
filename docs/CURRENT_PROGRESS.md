# BNG3 current progress

This table reports issue obligations and independently verified evidence. `3ef3ac00` is the documentation worktree base, not a claim that a listed check passed on current `main`. No issue-level release check artifacts were verified while preparing this snapshot.

| Issue | Intended check IDs | Current main SHA | Artifact links | Result / status | Outstanding obligations |
|---|---|---|---|---|---|
| [#137](https://github.com/RuleWorld/BNG3/issues/137) | `release-inventory`, `release-inventory-links`, `release-capability-coverage-137` | Not verified | None verified | Open | Inventory audit and exact-main check artifacts; see [inventory](CAPABILITY_UNION_INVENTORY.md). |
| [#179](https://github.com/RuleWorld/BNG3/issues/179) | Provenance gate identities in issue | Not verified | None verified | Open | Verify exact-main provenance acceptance receipts; see [upstream lock](../provenance/upstreams.lock.yml). |
| [#472](https://github.com/RuleWorld/BNG3/issues/472) | `release-docs-links`, `release-docs-decisions` | Not verified | None verified | In progress | Independent acceptance checks and main artifacts remain outstanding. |
| [#471](https://github.com/RuleWorld/BNG3/issues/471) | `release-oracle-independence`, `release-oracle-tamper`, `release-ci-topology` | Not verified | None verified | Open | Land checks and verify exact-main artifacts. |
| [#473](https://github.com/RuleWorld/BNG3/issues/473) | `release-jax-ode`, `release-jax-ssa`, `release-jax-install` | Not verified | None verified | Open | Implement and independently qualify each listed surface. |
| [#474](https://github.com/RuleWorld/BNG3/issues/474) | `release-cuda-device`, `release-cuda-performance` | Not verified | None verified | Open | Device and performance qualification with exact-main artifacts. |
| [#475](https://github.com/RuleWorld/BNG3/issues/475) | `release-delay-formats`, `release-delay-ode`, `release-delay-ssa` | Not verified | None verified | Open | Complete delayed-rule semantics and independent checks. |
| Other release issues | See [PLAN.md](PLAN.md) issue/package table and each issue body | Not verified here | None verified here | Open / unverified | Required issue checks and exact-main artifacts have not been audited for this table. |

Historical progress narratives are preserved in [the progress archive](archive/reports/CURRENT_PROGRESS_HISTORY.md). The full scope is the [capability inventory](CAPABILITY_UNION_INVENTORY.md); final maintainer decisions are in [DECISIONS.md](DECISIONS.md).
