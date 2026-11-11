# Issue #471 check package

This package supplies executable, fail-closed consumers for the issue's oracle
independence, tamper, and workflow-topology checks. It does not update the
capability matrix or claim support from an oracle declaration alone.

## Focused local command

```sh
python -m pytest -q tests/validation/release/cases/issue-471/test_issue471_checks.py
```

The oracle gate reads one schema-version-2 JSON receipt per capability ID and
three actual files beneath a separate artifact root: the producer output, the
oracle expectation, and the downstream consumer output. Receipt paths must be
safe relative paths without symlinks; the verifier hashes each file and checks
the recorded digest. It then runs its owned byte-equality comparator over the
consumer and oracle bytes and records the comparator implementation digest.
Receipt claims such as `result: pass` or `comparison: pass` do not exist in or
control this schema. A missing file, stale revision, unresolved oracle origin,
mismatched digest, consumer input mismatch, unequal output, or matrix status
other than `implemented` fails the gate. The verifier independently checks
matrix IDs against `docs/CAPABILITY_UNION_INVENTORY.md`; an empty or mismatched
inventory fails closed. It preserves source status counts and does not promote
them. Without `--artifacts`, the report is explicitly `DECLARATION_ONLY` and
cannot count any grounded execution rows.

```sh
python tests/validation/release/cases/issue-471/issue471_checks.py oracle \
  --root . --receipts "$RUNNER_TEMP/oracle-consumer-receipts" \
  --artifacts "$RUNNER_TEMP/oracle-consumer-artifacts" \
  --revision "$GITHUB_SHA" --report "$RUNNER_TEMP/oracle-independence.json"
```

The current matrix has 994 rows, with 986 `missing`, 7 `implemented`, and 1
`wrong`; 16 rows use the unresolved generic declaration “canonical source or
analytic specification as appropriate.” No fresh exact-revision consumer
receipts are supplied by this package, so `release-oracle-independence`
correctly remains `fail`. The remaining named declarations are inventory
metadata, not execution evidence.

The current byte-equality comparator is a bounded exact-output contract.
Numeric or tolerance-based cases need an explicitly owned comparator extension
rather than a receipt assertion.

The tamper tests exercise existing base-revision policy functions against
negative Git fixtures: product code mixed with existing expected data, a
fixture-name reference in product code, and a surviving non-equivalent mutant.
They do not replace execution of the curated product mutant set or its
scheduled exact-main score artifact.

```sh
python tests/validation/release/cases/issue-471/issue471_checks.py topology \
  --workflow .github/workflows/parity.yml \
  --report "$RUNNER_TEMP/ci-topology.json"
```

The topology check verifies that the independent BNG2, native NFsim, and
PyBioNetGen parity jobs share only the oracle-lock prerequisite and that
artifact uploads in the parity workflow use `always()`. Its negative fixture
proves that an accidental dependency edge or success-only artifact upload
fails. On the current base, it reports the success-only upload of the final
`release-obligation-142` consumer receipt. These tests do not rewire CI; the
workflow owner must add the package to the exact-main gate and arrange for the
receipt consumer to run after, and separately from, the producer jobs.
