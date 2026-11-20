# Issue 181 — scoped release-case evidence

`contract.json` declares the named check identities from the live body of #181
and the obligation IDs from `provenance/issue-obligations.json`. Declaring them
does **not** establish that they pass.

## Currently qualified slice: resumable tier-S per-case artifacts

This contributes to `release-corpus-results` only for the locked tier-S shard.
It does not claim `release-corpus-coverage` or `release-obligation-181`.

Supported selection and replay (real case IDs; tier-S is the 10 locked IDs in
`provenance/corpus/selection.json`):

```sh
python -m tests.validation.conformance --tier smoke --corpus-tier s \
  --bng-cpp build/cpp/bng_cpp --bng2-root "$ORACLE_BIONETGEN" \
  --bng2-network-sha256 "$BNG2_NETWORK_SHA256" --report-dir "$REPORT_DIR"

# Withhold models/localfunc/case-result.json, then resume the same selection:
python -m tests.validation.conformance --tier smoke --corpus-tier s --resume \
  --bng-cpp build/cpp/bng_cpp --bng2-root "$ORACLE_BIONETGEN" \
  --bng2-network-sha256 "$BNG2_NETWORK_SHA256" --report-dir "$REPORT_DIR"
```

Focused regression: `tests/validation/test_corpus_resume.py` (real locked IDs
`michment` and `simple_system`; invocation records and verdict rows, not
filename presence). Binary-free replay:
`scripts/ci/replay_corpus_shard_resume.py`.

Exact-revision observations recorded in the worktree used for this slice:

| Item | Value |
| --- | --- |
| Product revision | `51c4502f4caf485e15b42525c18249391057cf0f` |
| Candidate SHA (built `bng_cpp`) | `7bd6c46c4c9661adb0abf90432ba266ffbc1f77d5817cfb825354bc98d70dcfc` |
| BNG2 source pin | `9601746f8884ed19ab2acea49fe87fc4660ace46` |
| Independently built `run_network` | `337f437a7216d6b87218fdc980fdbaae6e036c5ef6def30f6cf81aa1b8bcddf8` |
| Clean tier-S | `PASS=569 / FAIL=0 / NOT_TESTED=1 / HARNESS_ERROR=0` |
| Resume with `localfunc` artifact withheld | 9 reused, 1 executed; identical outcome counts and per-case scientific rows |
| Stale control | copied artifact with altered candidate SHA -> `stale-discarded-and-executed` |

Evidence packets: `/tmp/bng3-corpus-replay.TG7Hc8/tier-s-resume-evidence.json`,
`/tmp/bng3-corpus-replay.TG7Hc8/real-run-evidence.json` and
`/tmp/bng3-corpus-replay.TG7Hc8/evidence/replay.json`.

## Remaining obligations

- `release-corpus-coverage`: complete inventory-row coverage and exact
  source/case identities for all tier families. Tier-X and Tier-B are empty and
  their RuleHub selectors/budgets remain a maintainer decision; they are
  reported as empty, not silently populated.
- `release-corpus-results`: independently checked results and resumable
  per-case artifacts for all release cases, beyond this tier-S shard.
- `release-obligation-181`: exact-main named check receipts, source/oracle
  identities and commit for every named obligation above.
