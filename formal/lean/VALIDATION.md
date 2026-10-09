# Validation record

## Pinned-toolchain results

The original audit baseline was `main` at
`e1836c3274e685996d5e86883761e00e98257e09` on 2026-10-07, using the pinned Lean
toolchain `leanprover/lean4:v4.33.1`. These counts remain historical baseline
evidence; the matcher theorem from PR #194 is now merged at
`c3b20f3e4a863300ac79dc9dfe71f0b406b6eda6`.

~~~text
lake build                         -> success, 36 jobs
lake env lean tests/Smoke.lean     -> success
lake env lean tests/Coverage.lean  -> success
scripts/static_validate.py         -> PASS, 37 Lean files
scripts/check_axiom_dependencies.sh -> AXIOM AUDIT PASS
scripts/check_nfnext_header_contract.py -> PASS
scripts/run_nfnext_contract.sh     -> PASS, 18/18 checks
scripts/check_harness_itself.sh    -> PASS, 32/32 mutation and malformed-input cases
production NFnext CTest            -> PASS, 2/2 tests (last run 2026-10-03)
~~~

The pinned Lean build, Smoke, Coverage, static/header checks, NFnext compiled
contract, axiom audit, and harness self-test were rerun locally for this record.
The production CTest result is retained from 2026-10-03 and was not rerun here.
The formal workflow runs the harness self-test on weekly scheduled and manual
runs, with a 20-minute step timeout; it does not run on every pull request.

The production CTest run includes architecture_nfnext_reference and
architecture_nfnext_bng_lowering_bridge. The bridge test parses a BNGL fixture,
constructs bng::compile::CompiledModel, then calls nfnext::lowerFromBioNetGen.
The separate test_nfnext.cpp instead round-trips a hand-built ModelIR through
ModelCache; it does not test the parser-to-lowering bridge.

The current MatchOnce implementation and its symmetric-dimer assertions pass
Coverage.lean. The test checks that two embeddings into one connected dimer
produce one channel event, while two matching molecules in separate complexes
remain two events. Earlier failure banners in that file described a defect
that is now fixed and have been removed.

## Merged matcher proof and open packing candidate — 2026-10-09

The matcher proof below is included in current `main` through merge commit
`c3b20f3e4a863300ac79dc9dfe71f0b406b6eda6`. The packing work remains in open
PR #198 and is candidate evidence rather than merged-main evidence.

- Merged matcher correctness: PR [#194](https://github.com/RuleWorld/BNG3/pull/194),
  candidate head `c5fafad022ff831374e669e4ce90ac6cf3102086`, merged on
  2026-10-09. Its hosted Lean run
  [37725570914](https://github.com/RuleWorld/BNG3/actions/runs/37725570914)
  passed. On that candidate, `python3 scripts/static_validate.py` checked 39
  Lean files,
  `lake build` completed 38 jobs, `lake env lean tests/Smoke.lean` and
  `lake env lean tests/Coverage.lean` passed, and
  `scripts/check_axiom_dependencies.sh` reported `AXIOM AUDIT PASS`.
  `BNG.referenceMatcher_correct` quantifies over every Lean `Pattern`,
  `Mixture`, and embedding: emitted results satisfy `EmbeddingSpec`, and every
  embedding satisfying that spec has a same-mapping emitted result. Completeness
  compares mappings by per-pattern-node lookup, and the spec requires the exact
  duplicate-free occurrence domain. There is no well-formed-input premise;
  the general proof adds no `sorry`, `admit`, or new axiom. Its audited
  dependencies are `[propext, Classical.choice, Quot.sound]`. This is a theorem
  about the Lean reference matcher, not production C++ matcher correctness.
- Bounded NFnext packing: PR [#198](https://github.com/RuleWorld/BNG3/pull/198),
  head `5cc1fd576a0d4aff7a75ee8a10af2d827e979ebd`, passed hosted Lean/NFnext run
  [37786454166](https://github.com/RuleWorld/BNG3/actions/runs/37786454166),
  and its exact-head [CI run 37786454220](https://github.com/RuleWorld/BNG3/actions/runs/37786454220)
  passed the C++ matrix, ASan, and integration checks. The production preflight
  checks declaration-order IDs and
  NFIR v5 field widths; the parser-to-lowering bridge exercises the bounded
  molecule-rule graph case and rejects component index 65,536. This is not a
  general proof of C++ pattern, rate, bond, or transformation refinement. The
  [candidate CXX mapping](https://github.com/RuleWorld/BNG3/blob/5cc1fd576a0d4aff7a75ee8a10af2d827e979ebd/formal/lean/CXX_MAPPING.md#issue-166-production-declaration-to-nfnext-id-packing)
  records the complete bounded surface.

The matcher/specification `#print axioms` entries from PR #194 are present in
the merged main audit script. PR #198 adds separate
`NFnextPacking.fromSignature_*` entries on its candidate branch; preserve them
when synchronizing that PR. PR #198 remains open as of this record.

## Trust and evidence categories

| Evidence category | What it establishes | Boundary |
| --- | --- | --- |
| General Lean theorem | A proposition is proved for the quantified Lean reference-model values in its statement. | Its explicit hypotheses and feature gates remain assumptions of the result; it is not a production C++ refinement theorem unless that correspondence is separately stated and proved. |
| Kernel-reduced proof (`rfl` / `decide`) | Lean's kernel checks the proof term, subject to the dependencies shown by `#print axioms`. | The accepted standard axioms (`propext`, `Classical.choice`, `Quot.sound`) remain part of Lean's trust base. |
| `native_decide` fixture | The compiled evaluator checks a concrete fixture and the assertion is run as an executable regression. | It depends on a per-declaration kernel-opaque axiom, so it is not kernel-reduced proof evidence. The allowlist and axiom audit make this use explicit. |
| Native C++ test | A compiled implementation passed the assertions exercised by that test binary. | It is finite executable evidence, not a Lean proof or a general refinement result. |
| Explicit theorem assumptions | The named hypotheses and predicates delimit the cases covered by a theorem, such as `supportedOperationalSubset` and match validity. | They are proof obligations at the theorem boundary, not evidence that unsupported cases satisfy the theorem. |

## Kernel and executable-check boundaries

The default Lake target compiles BNG/** only. Smoke.lean and Coverage.lean are
separate commands and must be invoked explicitly. A successful lake build alone
does not establish that either test file passes.

Assertions proved with rfl or decide are kernel-reduced. Most concrete fixture
assertions use native_decide, which evaluates through Lean's compiled evaluator
and introduces a kernel-opaque per-declaration axiom. Those assertions are
executable regression checks, not kernel-reduced proofs. The named theorem
nfnextBridgeContract_holds is also a worked fixture assertion using
native_decide.

check_axiom_dependencies.sh audits the named library declarations listed in
that script. The measured dependencies are:

- No axioms: BNG.source_text_is_not_semantics, BNG.source_irrelevance_again,
  BNG.rule_side_roundtrip, BNG.PatternSide.flip_involutive,
  BNG.pattern_lowering_keeps_bonds, and BNG.lower_preserves_bond_count.
- propext only: BNG.pattern_lowering_keeps_nodes,
  BNG.rule_lowering_keeps_edits, BNG.lower_preserves_molecule_count,
  BNG.lower_preserves_mutation_count, BNG.backend_one_edit_refines_semantics,
  BNG.execute_lowered_mutation_eq_reference, BNG.connectedFrom_empty,
  BNG.empty_molecule_observable_zero, BNG.structural_roundtrip, and
  BNG.compileStructuralSemantics_deterministic.
- propext and Quot.sound: BNG.backend_edit_program_refines_semantics,
  BNG.backend_rule_step_refines_semantics,
  BNG.execute_lowered_program_eq_reference,
  BNG.execute_lowered_rule_eq_reference, and
  BNG.Examples.example_lowered_step_equals_semantic_step.
- BNG.Examples.nfnextBridgeContract_holds depends on propext,
  Classical.choice, Quot.sound, and its allowlisted
  nfnextBridgeContract_holds._native.native_decide.ax_1_1 extension.

Anonymous native_decide examples in Smoke.lean and Coverage.lean are not
individually listed in that audit; their tactic use is checked textually, not
by per-example #print axioms.

The lowering equalities have a broader quantifier than the fixture checks, but
their boundary remains the Lean reference model:

- execute_lowered_mutation_eq_reference is proved for every mutation,
  environment, and mixture. It equates the Lean lowered-action interpreter
  with Lean's semantic applyMutation function.
- execute_lowered_program_eq_reference covers every finite mutation list,
  environment, and mixture, with the same two Lean interpreters.
- execute_lowered_rule_eq_reference equates the two Lean rule-step functions
  for any direction, mixture, and supplied candidate match. Both are gated by
  supportedOperationalSubset and match validity. That subset requires empty
  filters, local scopes, and modifiers. In particular, this theorem does not
  prove MatchOnce behavior, discover matches, or execute production C++.

nfnextBridgeContract_holds checks one concrete lowering fixture. The native
C++ bridge CTest checks the same BNGL example through the production parser,
CompiledModel, and NFnext lowering implementation. These independent checks do
not form a general Lean-to-C++ refinement theorem.

## NFnext and hybrid checks

run_nfnext_contract.sh builds its temporary C++ contract executable against
the current NFnext implementation and passes 18 matcher/transformation checks.
The production CMake tests separately pass the reference and parser-to-lowering
bridge cases.

The Hybrid.lean definitions describe a conservative reference conversion that
requires an embedding to cover an entire connected complex. This is executable
Lean reference behavior, not a proof of equivalence to a population simulator.
The native hybrid-model-generator tests pass 21 assertions in two cases, but
they test BNGL model generation. PopulationMap.hpp explicitly limits current
support to parsing and storage; population-based simulation refinement is not
executed. HybridModelGenerator.cpp also reports that compartments are not
supported by this generator.

## Static and header checks

static_validate.py checks imports, balanced syntax delimiters, required modules,
and prohibited proof placeholders. It does not type-check Lean.

check_nfnext_header_contract.py pins ordered enum members, selected NFnext
vocabulary, the connected_to and interchangeable field declarations, and
correspondence with Lean's operation ordering. This catches header drift but
does not prove runtime semantic equivalence.

See CXX_MAPPING.md and CXX_MIGRATION_BLOCKERS.md for the remaining production
C++ correspondence boundary.
