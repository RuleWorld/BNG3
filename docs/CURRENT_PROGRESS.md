# BNG3 current progress

**Refreshed:** 2026-10-09 UTC against RuleWorld/BNG3 main
`dd23c2679ead1335d6aeefa47835f850e154256c`. Semantic convergence and release
qualification remain incomplete. The authoritative backlog is issues
[#132–#186](BNG3_CONVERGENCE_DONE_CHECKLIST.md).
After the closure audit, 50 of 55 remain open; #134, #136, #145, #165 and #169
are closed. #135 remains open until the documentation PR merges.

The [convergence checklist](BNG3_CONVERGENCE_DONE_CHECKLIST.md) maps all 55 tasks
one-to-one. Each linked issue owns its acceptance criteria, dependencies,
assignment and detailed evidence; unassigned work has no implied review owner.
The [repository audit](REPOSITORY_AUDIT_2026-10-07.md) is a dated source snapshot,
not today's task status. Immutable historical
[progress](https://github.com/RuleWorld/BNG3/blob/e1836c3274e685996d5e86883761e00e98257e09/docs/CURRENT_PROGRESS.md)
and [checklist](https://github.com/RuleWorld/BNG3/blob/e1836c3274e685996d5e86883761e00e98257e09/docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md)
retain the earlier reports.

## Integrated acceptance slices

These changes are merged. A bounded repair does not close its broader issue.

| Issues | Merged PRs | Supported scope and remaining boundary |
| --- | --- | --- |
| #140 | #207 | Compile-owned numeric `generate_network.max_iter`; other protocol options and `max_agg` remain open. |
| #141/#142 | #203/#211 | Worker package/native identity, graph-cache race repairs, compartmental seed association and exact species identity. Broader isolation and separate backend graph encodings remain open. |
| #144/#145 | #200/#214 | One fail-closed BNGsim lowerability boundary with adapter ON/OFF agreement; selected steady-state controls forwarded, unqualified controls refused. No default backend promotion. #145 is closed. |
| #138/#163 | #196/#197 | Compile-owned unit metadata, energy export guards and version-aware SBML units. Broader runtime migration and format qualification remain open. |
| #146 | #210/#215 | Whole-species deletion, named-molecule deletion, unsupported conditional refusal, pending waits and output clocks. Strict native `-oSteps` endpoint parity remains red; broader NFsim qualification remains open. |
| #153–#155 | #209/#212/#213/#217 | Narrow parser-free native BNGIR v0.2 import, boolean-reference rejection, strict root envelopes and formatting. Full round trips and unqualified structural families remain open. |
| #136 | #189 | Corrected stale architecture/validation claims; historical reports remain historical. Closed after scoped review. |
| #165/#166 | #194/#198 | All-input Lean reference matcher and bounded packing theorems/native guards. #165 closed; general production lowering correspondence remains open under #166. |
| #169 | #192 | Explicit proof trust accounting, Smoke/Coverage/axiom gates and scheduled/manual mutation harness. Closed after scoped review. |
| #182 | #199/#216 | Numerical/expression/export CI wiring and source-selected harness isolation. Full scientific acceptance remains open. |

PR #205 integrated the Rasi translation performance port separately. The shared
checkout remains on `perf/nfsim-rasi-translation-port-v2` at `07ea87d3`, with its
unrelated untracked audit file preserved; work proceeds in isolated checkouts.
Only root may merge reviewed, qualified PRs or close satisfied issues. Release
publication remains unauthorized.

## Evidence and limits

Main `dd23c267` completed hosted snapshot: 46 successful check runs and two
skipped, with no failures or nonterminal checks. The
[CI run](https://github.com/RuleWorld/BNG3/actions/runs/37946645248) completed successfully.
[Cross-tool parity](https://github.com/RuleWorld/BNG3/actions/runs/37946645282),
[Lean](https://github.com/RuleWorld/BNG3/actions/runs/37946645272),
[CodeQL](https://github.com/RuleWorld/BNG3/actions/runs/37946645337) and
[formatting](https://github.com/RuleWorld/BNG3/actions/runs/37946645369) completed.
Queued, skipped and historical checks do not qualify a changed candidate.
CUDA compile/no-toolkit lanes provide no NVIDIA-device evidence.

The prior local integration checkout `c8777694` has tree
`68f9ca805f08d3a7c69e67597451954b581ad016`, identical to main `dd23c267`.
Its installed runtime receipt executed source `88c8435d` before the later
proof/CI-only merge: 178 passes and two existing xfails, with verified package,
model, scan, BNGIR and native-extension paths/hashes. Wheel SHA-256
`83915318fba251d926a471e5481d75edcdb8ae54a1eb04c7854278daf3bb7e41`;
native extension SHA-256
`586af3a574afdbbf005c2a753ff61df05858dba0f902bb34b77e13abb1376a21`.
That adapter-ON wheel required the external pinned BNGsim dylib through
`DYLD_LIBRARY_PATH`; it does not establish self-contained packaging. These are
prior combined-tree receipts, not a fresh exact-head run of every current PR.

The closure timeline audit found no accepted disposition for #146 or #154.
Both were reopened with the unmet criteria and bounded merged evidence:
[#146 disposition](https://github.com/RuleWorld/BNG3/issues/146#issuecomment-6089843989)
and [#154 disposition](https://github.com/RuleWorld/BNG3/issues/154#issuecomment-6089844484).
The issue bodies' full acceptance criteria remain binding.

## Candidates under review

| Issues | PR / observed head | Qualification boundary |
| --- | --- | --- |
| #132 | #130 `2f05ce2e` | Constant/dynamic assignment and XML changes; integrate without losing #210 whole-deletion bond suppression. |
| #133/#173 | #190 `694ecd1b`, stacked #191 `47e4b306` | Static-subset JAX ODE; SSA explicitly unavailable. Both candidates were synchronized with main to incorporate the formatting repair behind #190's prior failures. Local Black/Ruff and 59 CI contracts pass; fresh installed JAX and hosted qualification remain pending. Adaptive integration and functional/time-dependent rates remain unsupported. |
| #134 | #128 `2cf7f6eb`, stacked #204 `dd75fe28` | Review together: #204 repairs #128's actual pyparsing 3.0.9 molecule-list regression. Closed review issue does not imply integration. |
| #137 | #195 `e530328e` | Inventory proposal; policy and review owners remain unapproved. |
| #143 | #201 `d4019f96` | ODE rate dependency classification; cross-backend scope and propensity work remains open. |
| #171/#172 | #193 `4056205f`, stacked #208 `7a776c63` | Public compatibility and defaults without optional Cement. Installed evidence predates latest main; combined qualification is being refreshed. #193's numerical parity identity job failed; #208 has no reported checks. Neither slice retires all legacy paths. |
| #179 | #202 `78543775` | Substantiated provenance proposal; 14 approval decisions remain pending and strict validation intentionally fails. |
| #183 | #206 `13344aa4` | Budgeted pinned SSTS CI. Pushed receipt `c5a4803e` records 32/1,923 selected cases: round-trip/RoadRunner 32 pass; official 31 pass/one unsupported. The exact-head hosted integrated rerun is in progress. Full-suite flags remain false; no broad #159 completion. |
| #174 | #188 `9456b290`, #218 `65e8ef09` | Other-author performance candidates; green checks alone do not establish correctness or a measured gain. #218 checks were still running. |
| #135 | #187 | Existing documentation ledger; refreshed after live-state and disposition audit, awaiting review/merge. |

The #147 deletion slice is committed as `5519cec7` in [PR #219](https://github.com/RuleWorld/BNG3/pull/219),
based on `dd23c267`. Both runtime regressions fail on old lowering and pass with
the fix; root reran 14 NFnext/architecture contracts successfully after building
the omitted targets. The bridge assertions remain active in Release. Adversarial
review found a missing same-complex matcher constraint for molecules within a
BNGL pattern; the repair is in progress and merge is blocked. Independent pinned
BNG2 network products distinguish whole-species from named-molecule deletion.
The native NFsim terminal-output claim is being corrected: unchanged rows at
the stated seed/horizon do not establish a post-event state. Hosted checks are
pending. Production `ActionIR` execution is not connected;
the tests adapt the emitted deletion actions to the existing graph runtime.
It reuses `wholeSpeciesDeletions`/`DestroyComplex`, retains `DeleteMolecules`,
and suppresses premature bond deletion. This is a bounded repair, not full
#147/#148 completion or a production formal correspondence theorem.

## Unchanged stop conditions

- Frozen `michment` SSA: 10/306 points outside three pooled standard errors,
  worst |z| about 9.3449 at ScT. Fresh pinned BNG2 reproduced all 200 golden
  files. Preserve seeds, horizons, tolerances, exclusions and goldens while
  investigating source/harness/output/RNG behavior.
- NFsim strict pinned native `-oSteps`: final-row mismatch on four deletion
  fixtures remains red. Supplemental `-oTimes` agreement and passing unchanged
  distributional checks are separate evidence; receipts remain under
  `tests/validation/evidence/`.
- Reference pins: BNG2 `9601746f8884ed19ab2acea49fe87fc4660ace46`;
  NFsim `9b00d42f734dcc3e695205600f12cae5b44d1daa`. BNG3-generated artifacts
  cannot serve as independent oracles for BNG3.
- #165 proves the Lean reference matcher, including exact embedding domains
  and mapping equality independent of association-list order. No `sorry`,
  new axiom or hidden premise; #166 production lowering remains unproved.
- Full curated BioModels #162 remains stopped until explicitly authorized.
  CUDA #175 requires actual NVIDIA hardware. #195 policy/owners and #202's
  14 approval decisions remain unresolved.

Continue existing candidates and actual issue dependencies. Finish the narrow
NFnext, compatibility and SSTS checkpoints before selecting the prepared
#140 `max_agg` slice; establish direct Python and BNG2 product-versus-seed
behavior before changing defaults. Keep acceptance criteria and detailed
receipts in the existing issues rather than introducing another roadmap.
