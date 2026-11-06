# Golden bundles

Current branch status is in
[`../../docs/CURRENT_PROGRESS.md`](../../docs/CURRENT_PROGRESS.md). A golden
bundle is evidence only for the exact source, oracle, and artifact digests in
its manifest.

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

Use `status: "candidate"` until the bundle itself has completed provenance
and independent scientific review. Source-lock approval was recorded in
`docs/DECISIONS.md` on 2026-10-27, but that approval does **not** promote any
golden bundle automatically. `status: "approved"` requires the accepted source
lock, locked oracle artifacts and compiler images, and review of this bundle's
model/output digests and acceptance choices; the validator rejects a manifest
that claims less.

Do not hand-edit generated output or infer an ensemble from one trajectory.
Generate a bundle with the reviewed regeneration workflow, validate it in a
clean environment, and commit the manifest and outputs together. An accepted
source lock is necessary but not sufficient evidence that a particular golden
bundle has been generated, reviewed, and approved.
