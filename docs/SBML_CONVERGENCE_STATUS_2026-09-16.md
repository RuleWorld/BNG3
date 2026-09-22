# BNG3 SBML convergence status

Date: 2026-09-16

Status: active and bounded; not release-ready.

## Scope

This checkpoint covers the current BNG3 branch after the primary-remote fast-forward check. The implementation targets SBML Level 3 Version 2 Core and SBML Level 3 Multi Version 1 Release 2. The authoritative specifications are the [SBML Level 3 Version 2 Core specification](https://sbml.org/documents/specifications/level-3/version-2/core/) and the [SBML Multi Version 1 Release 2 specification](https://sbml.org/specifications/sbml-level-3/version-1/multi/sbml-multi-version-1-release-2.pdf).

The implementation batch adds source-level handling for model and element `metaid`, SBO terms, notes, raw annotations, MIRIAM qualifier spelling/resources, package namespace/required declarations, and package element counts. These fields remain separate from executable kinetic state. The modern BNGL writer emits a compact source-metadata classification comment, while the public modern `from_sbml(...).write_sbml(...)` path and the C++ writer's optional payload channel preserve the source metadata as a namespaced, base64 SBML annotation. COMBINE extraction now retains the actual manifest member and normalized manifest content entries on the extraction/result objects; SED-ML execution remains outside this kinetic path. Inline finite BNGL table functions are lowered to SBML Core MathML piecewise expressions, including endpoint clamping and step/linear behavior. The C++ writer and native reader also canonicalize BNGL inverse-trigonometric names to the SBML `arcsin`/`arccos`/`arctan` family (and hyperbolic variants), fixing three formerly unsupported suite cases.

The current checkpoint also lowers SBML Core's `factorial` operator end to end. The C++ evaluator accepts only non-negative integer arguments and reports double-precision overflow explicitly; the typed compiler, BNGL visitor, C++ SBML writer/native reader, and modern Atomizer diagnostics use the same supported boundary. SBML `e-notation` numbers are likewise treated as exact supported MathML rather than as unspecified rationals.

Fixed-time, constant-valued SBML events are lowered to explicit BNGL action
phases; state-dependent or non-constant events remain fail-closed.

The corpus gates now treat both `dropped` and semantic `approximated` warnings as
unsupported. Informational unit-scale notes remain non-blocking because the
parser preserves the source numeric scale. This prevents a rendered but
non-equivalent translation from being reported as a numerical pass.

## Evidence

The post-change summary below supersedes the older detailed cause figures retained later in this section for comparison.

The post-change suite cause summary is authoritative in `/private/tmp/bng3-sbml-suite-post-factorial.json`: unsupported records have 1/2/3/4 causes with cardinalities 705/445/79/6; the largest pairwise intersections are algebraic-rules+constraints (117), events+no-state (74), `comp`+no-state (64), events+`distrib` (61), and constraints+stoichiometry (40). The proposed `{events, MathML, local scope, species assignment, constraints}` projection touches 836 unsupported records, with 455 target-only and 381 retaining another cause.

Commands were run from the authoritative isolated checkout at `/private/tmp/bng3-material-gap-completion`.

- `cmake --build build -j2`: passed.
- `ctest --test-dir build --output-on-failure`: 315/315 tests passed.
- `PYTHONPATH=python:build/cpp /opt/anaconda3/bin/python -m pytest -q tests/python --override-ini addopts=''`: 420 passed, 28 skipped.
- `PYTHONPATH=python:build/cpp /opt/anaconda3/bin/python -m pytest -q tests/validation --override-ini addopts=''`: 84 passed, 117 skipped.
- Focused event-lowering, warning-merge, metadata, inverse-trigonometric, and unsupported-report-contract tests: 11 passed; the earlier focused metadata/COMBINE command also passed 16 tests.
- Post-change Core MathML evidence: all 12 previously diagnostic-only e-notation cases (`semantic/00085`, `00185`, `00332`, `00338`-`00342`, `01017`, `01665`, `01722`, `01777`) pass their selected semantic checks without the false rational warning. SBML factorial cases `semantic/00028` and `semantic/00269` pass XML validation, modern reimport, native C++ reader count checks, and BNG3-vs-libRoadRunner CVODE comparison; `semantic/00173` reaches the same stages but remains a real failed discontinuous rate-rule comparison at the `ceil` threshold.
- The post-change full SBML Test Suite report is `/private/tmp/bng3-sbml-suite-post-factorial.json` (schema 3): all 1,923 pinned cases were selected; 687 passed, 1,235 were explicitly unsupported, 1 failed, and 0 timed out. Of the 688 cases reaching export/reimport, 597 carried source metadata and all 597 payloads matched exactly; 91 had no source metadata. The report is an import/round-trip gate, not a claim of numerical SBML Test Suite conformance.
- The suite report records `unsupported_causes` and exact `category/id` references. Cause counts are non-exclusive: events 505, no-state variables 254, stoichiometry 217, MathML 164, constraints 151, species assignment rules 133, `comp` 125, algebraic rules 118, `distrib` 61, conversion factors 55, fast reactions 35, `fbc` 34, local scope 21, negative rates 17, and reaction-participant edge cases 9. The largest pairwise intersections are algebraic-rules+constraints 117, events+no-state 74, `comp`+no-state 64, events+`distrib` 61, and events+MathML 44. Stoichiometry splits into 188 dynamic/`stoichiometryMath`, 23 constant noninteger, and 6 constant negative records.
- A cause-set projection for the proposed `{events, MathML, local scope, species assignment, constraints}` work is not a support claim: those labels touch 864 suite records, but only 470 are target-only and 386 retain at least one other cause. In curated SBML, the same set touches 399 of 461 unsupported records; 378 are target-only and 62 retain other causes. These are upper bounds because implementing a label may reveal additional semantic or backend requirements.
- The earlier two-mode curated BioModels report `/private/tmp/bng3-curated-biomodels-metadata-current.json` predates the semantic-gate correction and is retained only as historical context. A post-change full two-mode refresh was started with the same 1,096-record inventory and isolated workers but did not reach a terminal report within the bounded run; no post-change two-mode result is claimed here.
- The final comparable flat-only report is `/private/tmp/bng3-curated-biomodels-flat-final-audited.json` (schema 4): all 1,096 inventory records were selected; 591 SBML-path records passed, 459 SBML records were explicitly unsupported, 31 failed, and 2 timed out. The remaining 11 records are non-SBML or archive-format-only records. Of the 604 source-bearing flat runs reaching export/reimport, all 604 payloads matched exactly. The report records exact BioModels IDs under `unsupported_causes`, `unsupported_subcauses`, and pairwise intersection summaries. Its SBML-only unsupported causes are species assignment rules 213, events 93, local scope 91, MathML 64, stoichiometry 55, constraints 18, other 18, fast reactions 5, conversion factors 1, negative rates 1, and no-state variables 1; stoichiometry splits into 52 constant noninteger, 2 dynamic/`stoichiometryMath`, and 1 integer-above-expansion-limit record. The failures are dominated by the configured direct CVODE/libRoadRunner observable comparison; the import, writer, reimport, and native count stages passed for the affected records before simulation was classified as failed.

The broad curated report is evidence about current surface and performance limits, not release evidence. In the two-mode report, several additional failures are atomized-model parser failures while the flat mode completed for those records; the remaining failures and timeouts require separate triage. The report intentionally keeps these outcomes visible instead of silently treating them as passes.

The independent NFsim oracle was not available in this environment (`NFSIM_BIN` was unset), so NFsim-dependent Multi parity remains skipped. LibSBML validation and the native C++ writer/reader checks were exercised where the harness reached them.

## Checklist

- [x] Pull/check current primary-remote state before implementation.
- [x] Compare the authoritative BNG3 checkout with the saved mapping and dirty reference checkout without modifying unrelated work.
- [x] Verify the current official SBML Core and SBML-Multi specification targets.
- [x] Finish and persist a bounded feature inventory with per-feature support classification.
- [x] Implement bounded parser, metadata, units, Multi, writer, and table-function batches.
- [x] Add focused parser, metadata, Multi, writer, validation, and round-trip regression coverage.
- [x] Rerun the pinned 1,923-case SBML Test Suite import/round-trip gate after the factorial/e-notation changes; the post-change report is recorded above.
- [x] Add exact integer-domain factorial support across the modern Atomizer, typed C++ compiler, BNGL parser, C++ SBML writer/native reader, evaluator, and validator markers; targeted Core evidence is recorded above.
- [x] Correct the MathML `e-notation` diagnostic classification without changing its exact numeric lowering; all 12 targeted suite cases pass their selected semantic checks.
- [ ] Complete a post-gate rerun of the pinned 1,096-record curated BioModels inventory in flat and atomized modes; the fresh flat-only run is complete, while the isolated two-mode refresh remains nonterminal.
- [x] Run the full available C++ and Python test gates.
- [ ] Triage the remaining curated failures/timeouts and expand supported SBML/Multi surface.
- [ ] Review the final diff and create the local checkpoint commit.
- [x] Persist this status document.
- [ ] Publish changes or update hosted review state; no push was performed in this checkpoint.

The goal remains open. Broad unsupported semantics, curated failures/timeouts, and the unavailable independent NFsim oracle are material blockers to convergence claims.
