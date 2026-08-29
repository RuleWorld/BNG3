# Golden bundles

Golden outputs are content-addressed scientific evidence, not ordinary test
fixtures. A bundle is publishable only when its manifest records the model and
corpus digests, RuleHub revision, independent oracle revision and artifact,
compiler/dependency/platform details, immutable build image, execution command,
method, seeds, time grid, tolerances, comparator version, and output digests.

The manifest contract is
[`schemas/golden-manifest.schema.json`](../schemas/golden-manifest.schema.json)
and the dependency-free validator is:

```bash
python scripts/validate_golden_manifest.py \
  --manifest provenance/golden/<bundle>/manifest.json
```

Use `status: "candidate"` while `provenance/upstreams.lock.yml` is pending.
`status: "approved"` is reserved for a maintainer-approved source lock with
locked oracle artifacts and compiler images; the validator rejects an approved
manifest that claims less.

Do not hand-edit generated output or infer an ensemble from one trajectory.
Generate a bundle with the reviewed regeneration workflow, validate it in a
clean environment, and commit the manifest and outputs together. No approved
golden bundle is present until the oracle build recipes and acceptance choices
in the source lock have been decided.
