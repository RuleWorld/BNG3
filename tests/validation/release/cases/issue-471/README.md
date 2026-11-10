# Issue #471 check package

This package supplies executable, fail-closed consumers for the issue's oracle
independence, tamper, and workflow-topology checks. It does not update the
capability matrix or claim support from an oracle declaration alone.

## Focused local command

```sh
python -m pytest -q tests/validation/release/cases/issue-471/test_issue471_checks.py
```

The oracle gate reads one JSON consumer receipt per capability ID from a
separate receipt directory. Each receipt binds the source and product to the
same full commit SHA, names the external/analytic oracle and its immutable
artifact digest, and records distinct producer output and downstream consumer
digests. A missing receipt, unresolved oracle origin, stale revision, mismatched
consumer inputs, or inventory status other than `implemented` fails the gate.
The gate reports the matrix status counts unchanged; it does not mutate or
promote them. Producer receipts alone cannot satisfy it.

```sh
python tests/validation/release/cases/issue-471/issue471_checks.py oracle \
  --root . --receipts "$RUNNER_TEMP/oracle-consumer-receipts" \
  --revision "$GITHUB_SHA" --report "$RUNNER_TEMP/oracle-independence.json"
```

The current matrix has 994 rows, with 986 `missing`, 7 `implemented`, and 1
`wrong`; 16 rows use the unresolved generic declaration “canonical source or
analytic specification as appropriate.” No fresh exact-revision consumer
receipts are supplied by this package, so `release-oracle-independence`
correctly remains `fail`. The remaining named declarations are inventory
metadata, not execution evidence.

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
