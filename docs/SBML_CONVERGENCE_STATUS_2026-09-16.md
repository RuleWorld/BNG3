# BNG3 SBML convergence status

Date: 2026-09-16

Status: active and bounded; not release-ready.

## Scope

This checkpoint covers the current BNG3 branch after the primary-remote fast-forward check. The implementation targets SBML Level 3 Version 2 Core and SBML Level 3 Multi Version 1 Release 2. The authoritative specifications are the [SBML Level 3 Version 2 Core specification](https://sbml.org/documents/specifications/level-3/version-2/core/) and the [SBML Multi Version 1 Release 2 specification](https://sbml.org/specifications/sbml-level-3/version-1/multi/sbml-multi-version-1-release-2.pdf).

The implementation batch adds source-level handling for model and element `metaid`, SBO terms, notes, raw annotations, MIRIAM qualifier spelling/resources, package namespace/required declarations, and package element counts. These fields remain separate from executable kinetic state. The modern BNGL writer emits a compact source-metadata classification comment when such metadata is present; it does not claim that ordinary executable BNGL preserves arbitrary SBML metadata. Inline finite BNGL table functions are lowered to SBML Core MathML piecewise expressions, including endpoint clamping and step/linear behavior.

## Evidence

Commands were run from the authoritative isolated checkout at `/private/tmp/bng3-material-gap-completion`.

- `cmake --build build -j2`: passed.
- `ctest --test-dir build --output-on-failure`: 313/313 tests passed.
- `PYTHONPATH=python:build/cpp /opt/anaconda3/bin/python -m pytest -q tests/python --override-ini addopts=''`: 409 passed, 28 skipped.
- `PYTHONPATH=python:build/cpp /opt/anaconda3/bin/python -m pytest -q tests/validation --override-ini addopts=''`: 84 passed, 117 skipped.
- The full SBML Test Suite report is `/private/tmp/bng3-sbml-suite-current.json`: all 1,923 pinned cases were selected; 752 passed, 1,171 were explicitly unsupported, 0 failed, and 0 timed out. The report is an import/round-trip gate, not a claim of numerical SBML Test Suite conformance.
- The full two-mode curated BioModels report is `/private/tmp/bng3-curated-biomodels-current.json`: all 1,096 inventory records were selected; 489 SBML-path records passed, 468 SBML records were explicitly unsupported, 40 failed, and 86 timed out. The inventory completeness check matched 1,096 records, 1,075 declared SBML records, and 21 non-SBML records.
- The comparable current flat-only report is `/private/tmp/bng3-curated-biomodels-flat-current.json`: all 1,096 inventory records were selected; 580 SBML-path records passed, 468 SBML records were explicitly unsupported, 32 failed, and 3 timed out. The failures are dominated by the configured direct CVODE/libRoadRunner observable comparison; the import, writer, reimport, and native count stages passed for the affected records before simulation was classified as failed.

The broad curated report is evidence about current surface and performance limits, not release evidence. In the two-mode report, several additional failures are atomized-model parser failures while the flat mode completed for those records; the remaining failures and timeouts require separate triage. The report intentionally keeps these outcomes visible instead of silently treating them as passes.

The independent NFsim oracle was not available in this environment (`NFSIM_BIN` was unset), so NFsim-dependent Multi parity remains skipped. LibSBML validation and the native C++ writer/reader checks were exercised where the harness reached them.

## Checklist

- [x] Pull/check current primary-remote state before implementation.
- [x] Compare the authoritative BNG3 checkout with the saved mapping and dirty reference checkout without modifying unrelated work.
- [x] Verify the current official SBML Core and SBML-Multi specification targets.
- [x] Finish and persist a bounded feature inventory with per-feature support classification.
- [x] Implement bounded parser, metadata, units, Multi, writer, and table-function batches.
- [x] Add focused parser, metadata, Multi, writer, validation, and round-trip regression coverage.
- [x] Rerun the pinned 1,923-case SBML Test Suite import/round-trip gate.
- [x] Rerun the pinned 1,096-record curated BioModels inventory in flat and atomized modes.
- [x] Run the full available C++ and Python test gates.
- [ ] Triage the remaining curated failures/timeouts and expand supported SBML/Multi surface.
- [ ] Review the final diff and create the local checkpoint commit.
- [x] Persist this status document.
- [ ] Publish changes or update hosted review state; no push was performed in this checkpoint.

The goal remains open. Broad unsupported semantics, curated failures/timeouts, and the unavailable independent NFsim oracle are material blockers to convergence claims.
