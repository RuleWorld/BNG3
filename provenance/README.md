# Provenance

The live branch and current qualification state are summarized in
[`../docs/CURRENT_PROGRESS.md`](../docs/CURRENT_PROGRESS.md). Provenance
records remain pending until their stated maintainer and oracle gates are met.

Historical migration reports and snapshot metadata are grouped under
[`../docs/archive/reports/ir-migration-2026-09-14/`](../docs/archive/reports/ir-migration-2026-09-14/).
Patch snapshots are not repository inputs; once their changes are applied,
the source tree, tests, and machine-readable provenance records are canonical.

`upstreams.lock.yml` is the machine-readable source and oracle baseline. It is
written as JSON-compatible YAML so the repository can validate it with the
Python standard library.

The 2026-09-23 snapshot refreshes the observed RuleWorld heads for BioNetGen,
NFsim, and PyBioNetGen. Each observed range is reconciled commit by commit in
[`reconciliation/`](reconciliation/) and summarized in
[`../docs/UPSTREAM_RECONCILIATION_2026-09-23.md`](../docs/UPSTREAM_RECONCILIATION_2026-09-23.md).
The starting revisions in those ledgers are the previously locked source
revisions; the cutoffs are the newly observed source heads. This refresh does
not approve those cutoffs. The baseline remains pending maintainer approval,
and ledger owners remain explicitly unassigned. Empty `tests` arrays mean
this reconciliation pass makes no test-execution claim.

The current continuation uses the locked native oracle revisions and keeps
missing engines, missing outputs, and unsupported population-map semantics
fail-closed. Hosted source, artifact, and check details are valid only for the
exact SHA reported by `gh` for that PR.

The initial document deliberately has `pending-maintainer-approval` status.
The integration plan records observed revisions, but maintainers have not yet
chosen the import cutoffs, oracle recipes, immutable build images, or owners.
Do not change the status to `approved` until those decisions are recorded.

Validate structure during development:

```bash
python scripts/validate_provenance.py
```

Use the strict gate for a source-update or release qualification:

```bash
python scripts/validate_provenance.py --require-approved
```

The strict gate additionally requires accepted source revisions, locked oracle
recipes and artifact digests, compiler image digests, and a Python lock-file
digest.

The 2026-10-08 candidate refresh is recorded in
[`approvals/2026-10-08/source-verification.json`](approvals/2026-10-08/source-verification.json).
It verifies all nine immutable commit objects, refreshes the destination
reference to the audited BNG3 main revision, and preserves the other source
cutoffs. `remote-commit` evidence means the commit is reachable upstream; it
does not assert that an old branch name still exists or that the cutoff has
been approved. Historical Rasi and Playground branch names no longer resolve.

A locked Python dependency file must be repository-relative, readable, and
match its recorded SHA-256 byte for byte. A syntactically valid digest cannot
substitute for a missing or changed file. The candidate records remain pending
until the actual source, recipe, compiler-image and dependency decisions are
approved.

The adjacent [oracle receipt](approvals/2026-10-08/oracle-verification.json)
records fresh, clean pinned BNG2 and NFsim builds and the committed decay smoke
inputs/outputs. BNG2's analytic ODE check and NFsim's single seeded trajectory
are distinct checks; they do not establish distributional parity. The
[Linux dependency evidence](dependencies/python-3.12-linux-x86_64-manylinux_2_28-full-dev-jax.evidence.md)
records resolution, wheel hashes, and an immutable compiler-image manifest.
Linux execution and other platform qualification remain unperformed.
`--require-approved` deliberately still reports the 14 pending decisions.
Issue #179 requires release-gate wiring after those decisions; this candidate
does not substitute observations for approval or claim that issue complete.

## Golden bundles

Provenance-complete golden bundles use the schema in
`schemas/golden-manifest.schema.json`. Validate a candidate or approved bundle
with:

```bash
python scripts/validate_golden_manifest.py \
  --manifest provenance/golden/<bundle>/manifest.json
```

The validator checks every referenced byte and rejects an `approved` bundle
until the source lock, oracle artifacts, and immutable compiler images are
actually locked.

## Reconciliation ledgers

Create one ledger per reconciliation source under `provenance/reconciliation/`
and validate it explicitly:

```bash
python scripts/validate_provenance.py \
  --ledger provenance/reconciliation/bionetgen.yml
```

Each ledger must conform to
`schemas/reconciliation-ledger.schema.json`. The source's represented revision,
chosen cutoff, and owner are required; each source commit then receives exactly
one classification, rationale, reviewer, and test list. Do not create an empty
ledger with guessed revisions or owners merely to satisfy the shape.
