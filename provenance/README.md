# Provenance

`upstreams.lock.yml` is the machine-readable source and oracle baseline. It is
written as JSON-compatible YAML so the repository can validate it with the
Python standard library.

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
