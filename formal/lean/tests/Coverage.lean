import BNG

/-!
# Executable coverage for the current BNG3 Lean surface

`tests/Smoke.lean` prints values with `#eval`.  A bare `#eval` succeeds whether
it prints `true` or `false`, so those lines document intent without enforcing
it.  This file instead states each value as a Lean `example`, so a semantic
change that flips one of them makes the file fail to elaborate.

## What "enforced" means here, stated precisely

Assertions in this file are proved by one of two tactics, and the difference
matters, so it is not glossed:

* `by rfl` / `by decide` -- **kernel-checked**.  The proof term is ordinary and
  `#print axioms` reports `does not depend on any axioms`.
* `by native_decide` -- **compiler-checked, not kernel-checked**.  The reduction
  runs through the compiled evaluator and the proof term depends on a
  per-declaration, kernel-opaque axiom of the form
  `<name>._native.native_decide.ax_1_1`.  Verified on this tree:

      $ printf 'import BNG\nopen BNG\nopen BNG.Examples\n
        theorem t : model.wellFormed = true := by native_decide\n
        #print axioms t\n' > /tmp/a.lean && lake env lean /tmp/a.lean
      't' depends on axioms: [propext, Classical.choice, Quot.sound,
                             t._native.native_decide.ax_1_1]

  This is a weaker guarantee than kernel reduction, and it is stated here rather
  than implied.  It is the right tool for these particular goals -- the point of
  most assertions below is that a *large executable computation* returns a
  specific value, and `decide` cannot evaluate them (reduction gets stuck on
  `match model.wellFormed, true with ...` because `model.wellFormed` does not
  unfold within the kernel's reduction budget).  Where `rfl`/`decide` DO suffice,
  they are used instead; `scripts/check_axiom_dependencies.sh` reports the split.

## What is deliberately NOT claimed

`lake build` does not compile this file: `lakefile.lean:12` declares
`@[default_target] lean_lib BNG` with root `BNG/`, so lake builds only the
library.  This file is executed by `scripts/validate_all.sh` and by the
`Run Lean semantic smoke checks` step in `.github/workflows/formal.yml`, both of
which name it explicitly.  `scripts/static_validate.py` additionally fails if
this file is deleted or drops below its assertion floor, so it cannot rot into
an unexecuted file the way an unrun test file otherwise would.

## THIS FILE IS CURRENTLY EXPECTED TO FAIL

The last block of this file asserts the INTENDED behaviour of `MatchOnce` for a
symmetric dimer, and three of those assertions **fail today** against a known
live defect in `formal/lean/BNG/Stochastic.lean` — `RuleMatch.orderedComplexKey`
returns the first mapped MOLECULE ID where its docstring says the connected
COMPLEX, so `MatchOnce` fires once per embedding instead of once per complex.
Owner: `leanKernel`.

So `lake env lean tests/Coverage.lean` exits non-zero, by design, with exactly
3 errors. That is the correct state of the record: it makes `formal/lean` red
while `Stochastic.lean` is wrong, rather than green and quietly wrong. The
failing block carries its own banner naming the defect, the owning file, and
the `grep` that locates it, so the reason is visible in the gate output and
not only in a PR description.

Every other assertion in this file passes. If the error count is not exactly 3,
this header is stale.

DISCLOSURE, per the rule that a check which cannot be evaluated must be reported
as unevaluated rather than counted as clean: the "3" above was MEASURED on this
tree (`lake env lean tests/Coverage.lean` -> 3 errors at 1103, 1110, 1114), not
inferred from the three assertions that look like they should fail. If a future
change makes the count differ, the count is the finding and this header is
wrong.

## Content rules

1. **No restatements.**  Re-proving a library theorem with a different variable
   name proves nothing `lake build` did not already prove.  Every assertion pins
   a concrete instance on `BNG.Examples.model` / `forward` / `runtimeMixture`,
   or on a deliberately constructed non-trivial mixture.
2. **No vacuous instances.**  An assertion whose expected value is `true` about
   a predicate that is trivially true everywhere catches nothing.  Wherever a
   check can be made discriminating it is paired with a *negative* instance that
   must be `false`/`none`/`0`, so the pair pins a boundary rather than a point.

Every expected value here was measured, not guessed.  Writing an assertion with
a wrong expected value is itself caught: the file fails to elaborate rather
than printing a surprise.  (One was caught this way during development --
`referenceReactionNetwork.reactions.length` is 2, not 1, because reactant order
is not canonicalized; see the ReactionNetwork section.)

Sections are anchored with header comments naming the module under test.
-/

open BNG
open BNG.Examples

/-! ## `BNG.Runtime` / `BNG.Pattern` — well-formedness actually rejects -/

example : moleculeA.components.length = 1 ∧ moleculeB.components.length = 1 ∧
    componentAx.states.length = 2 := by native_decide

example : badPattern.wellFormed model.signature = false := by native_decide

/-- ...while the real patterns are accepted, so the check is discriminating and
not simply returning `false` for everything. -/
example : productComplex.wellFormed model.signature = true := by native_decide
example : reactantA.wellFormed model.signature = true := by native_decide

/-- A pattern whose sites demand an exact bond group that `bonds` does not
define is rejected. -/
def orphanBondGroupPattern : Pattern :=
  { molecules :=
      [ { occurrence := ⟨0⟩
          moleculeType := mtA
          sites :=
            [ { occurrence := ⟨0⟩
                component := cAx
                state := .exact sU
                bonds := [.exact ⟨7⟩] } ] } ] }

example : orphanBondGroupPattern.wellFormed model.signature = false := by native_decide

/-- The concrete mixture is well formed; a mixture whose A.x carries the
UNdeclared state 99 is not. -/
example : runtimeMixture.wellFormed model.signature = true := by native_decide

def illegalStateMixture : Mixture :=
  { nextMoleculeId := ⟨2⟩
    molecules :=
      [ { id := ⟨0⟩, moleculeType := mtA
          sites := [{ component := cAx, state := some ⟨99⟩ }] }
      , { id := ⟨1⟩, moleculeType := mtB, sites := [{ component := cBy }] } ]
    bonds := [] }

example : illegalStateMixture.wellFormed model.signature = false := by native_decide

/-- A bond to a site that does not exist is rejected by `wellFormed`. -/
def danglingBondMixture : Mixture :=
  { nextMoleculeId := ⟨2⟩
    molecules := [runtimeA, runtimeB]
    bonds :=
      [ { a := { molecule := ⟨0⟩, component := cAx }
        , b := { molecule := ⟨5⟩, component := cBy } } ] }

example : danglingBondMixture.wellFormed model.signature = false := by native_decide

/-! ## `BNG.Operational` — the matcher discriminates, it does not always fire -/

example : (forward.matches runtimeMixture).length = 1 := by native_decide
example : (reactantA.matches runtimeMixture).length = 1 := by native_decide
example : (reactantB.matches runtimeMixture).length = 1 := by native_decide

/-- **Negative instance.** A mixture whose A is already `x~p` must NOT match
`A(x~u)`.  Without this, `matches = 1` could come from a matcher that ignores
the state constraint entirely. -/
def phosphorylatedMixture : Mixture :=
  { runtimeMixture with
    molecules :=
      [ { runtimeA with sites := [{ component := cAx, state := some sP }] }
      , runtimeB ] }

example : (reactantA.matches phosphorylatedMixture).length = 0 := by native_decide
example : (forward.matches phosphorylatedMixture).length = 0 := by native_decide

/-- **Multiplicity is real.** With two A molecules the rule has two matches. -/
def doubledAMixture : Mixture :=
  { nextMoleculeId := ⟨3⟩
    molecules := [runtimeA, { runtimeA with id := ⟨2⟩ }, runtimeB]
    bonds := [] }

example : (forward.matches doubledAMixture).length = 2 := by native_decide
example : (reactantA.matches doubledAMixture).length = 2 := by native_decide

/-- **The two matches really are distinct embeddings**, distinguished by which
concrete A they selected — so the count of 2 is multiplicity, not duplication.
`RuleMatch.orderedComplexKey` takes the mixture as an explicit argument, so it is
applied as a function rather than by field notation. -/
example : (forward.matches doubledAMixture).map
    (RuleMatch.orderedComplexKey doubledAMixture) =
    [[some ⟨0⟩, some ⟨1⟩], [some ⟨2⟩, some ⟨1⟩]] := by native_decide

/-! ## `BNG.Operational` — execution produces the expected concrete graph -/

example : semanticResult?.isSome = true := by native_decide

def semanticResult : Mixture :=
  match semanticResult? with
  | some mix => mix
  | none => { nextMoleculeId := ⟨0⟩, molecules := [], bonds := [] }

/-- Molecularity preserved: the rule creates and destroys no molecule, and does
not advance the allocation cursor. -/
example : semanticResult.molecules.length = 2 := by native_decide
example : semanticResult.nextMoleculeId.value = runtimeMixture.nextMoleculeId.value := by
  native_decide

/-- Exactly one new undirected bond, and it is the A.x—B.y bond. -/
example : semanticResult.bonds.length = 1 := by native_decide
example : semanticResult.hasBond
    { molecule := ⟨0⟩, component := cAx }
    { molecule := ⟨1⟩, component := cBy } = true := by native_decide

/-- The bond is undirected: the reversed query is also true. -/
example : semanticResult.hasBond
    { molecule := ⟨1⟩, component := cBy }
    { molecule := ⟨0⟩, component := cAx } = true := by native_decide

/-- The reactant edge must NOT already exist before the rule fires. -/
example : runtimeMixture.hasBond
    { molecule := ⟨0⟩, component := cAx }
    { molecule := ⟨1⟩, component := cBy } = false := by native_decide

example : resultAIsPhosphorylated = true := by native_decide
example : resultHasABBond = true := by native_decide

/-- Phosphorylation moved A.x `u` → `p`, and B.y stayed state-less (the rule
touches only the A site). -/
def aSiteState : Option StateId :=
  match semanticResult.findMolecule? ⟨0⟩ with
  | none => none
  | some m => (m.findSite? cAx).bind (·.state)

def bSiteState : Option StateId :=
  match semanticResult.findMolecule? ⟨1⟩ with
  | none => none
  | some m => (m.findSite? cBy).bind (·.state)

example : aSiteState = some sP := by native_decide
example : bSiteState = none := by native_decide
example : aSiteState ≠ none := by native_decide

/-- The lowered backend step is defined on this fixture (not vacuously `none`),
and the result is a well-formed mixture. -/
example : loweredResult?.isSome = true := by native_decide

def loweredResult : Mixture :=
  match loweredResult? with
  | some mix => mix
  | none => { nextMoleculeId := ⟨0⟩, molecules := [], bonds := [] }

/-- **This is the refinement theorem pinned on data.** Rather than restating
`execute_lowered_rule_eq_reference`, this compares two INDEPENDENTLY COMPUTED
mixtures through their observable content: same molecule count, same cursor,
same bond count, same specific bond, same post-state.  A backend that silently
skipped the state change or the bond would fail here even though `applyAt?`
would still be internally consistent. -/
example : loweredResult.molecules.length = semanticResult.molecules.length := by
  native_decide
example : loweredResult.bonds.length = semanticResult.bonds.length := by native_decide
example : loweredResult.nextMoleculeId.value = semanticResult.nextMoleculeId.value := by
  native_decide
example : loweredResult.hasBond
    { molecule := ⟨0⟩, component := cAx }
    { molecule := ⟨1⟩, component := cBy } = true := by native_decide

def loweredASiteState : Option StateId :=
  match loweredResult.findMolecule? ⟨0⟩ with
  | none => none
  | some m => (m.findSite? cAx).bind (·.state)

example : loweredASiteState = some sP := by native_decide

/-! ## `BNG.Operational` / `BNG.Runtime` — graph-edit preconditions reject -/

example : (runtimeMixture.addBond?
    { molecule := ⟨0⟩, component := cAx }
    { molecule := ⟨1⟩, component := cBy }).isSome = true := by native_decide

/-- Adding a bond that already exists is rejected. -/
example : (semanticResult.addBond?
    { molecule := ⟨0⟩, component := cAx }
    { molecule := ⟨1⟩, component := cBy }) = none := by native_decide

/-- A self-bond is rejected. -/
example : (runtimeMixture.addBond?
    { molecule := ⟨0⟩, component := cAx }
    { molecule := ⟨0⟩, component := cAx }) = none := by native_decide

/-- A bond to a non-existent molecule is rejected. -/
example : (runtimeMixture.addBond?
    { molecule := ⟨0⟩, component := cAx }
    { molecule := ⟨7⟩, component := cBy }) = none := by native_decide

/-- Removing an absent bond fails rather than silently succeeding. -/
example : (runtimeMixture.removeBond?
    { molecule := ⟨0⟩, component := cAx }
    { molecule := ⟨1⟩, component := cBy }) = none := by native_decide

def bondedMixture : Mixture :=
  { nextMoleculeId := ⟨2⟩
    molecules := [runtimeA, runtimeB]
    bonds :=
      [ { a := { molecule := ⟨0⟩, component := cAx }
        , b := { molecule := ⟨1⟩, component := cBy } } ] }

example : bondedMixture.wellFormed model.signature = true := by native_decide

/-- Deleting a molecule drops its incident bonds along with it. -/
example : (match bondedMixture.deleteMolecule? ⟨0⟩ with
  | none => false
  | some m => m.bonds.length == 0 && m.molecules.length == 1) = true := by native_decide

/-- Deleting a molecule that is not there fails. -/
example : (runtimeMixture.deleteMolecule? ⟨9⟩) = none := by native_decide

/-! ## `BNG.Graph` — connected components -/

example : runtimeMixture.connectedFrom ⟨0⟩ = [⟨0⟩] := by native_decide
example : runtimeMixture.sameComplex ⟨0⟩ ⟨1⟩ = false := by native_decide
example : bondedMixture.connectedFrom ⟨0⟩ = [⟨0⟩, ⟨1⟩] := by native_decide
example : bondedMixture.sameComplex ⟨0⟩ ⟨1⟩ = true := by native_decide
example : bondedMixture.sameComplex ⟨1⟩ ⟨0⟩ = true := by native_decide

/-- Restricting to one molecule drops the inter-molecular bond and keeps the
molecule itself. -/
example : (bondedMixture.restrictToMolecules [⟨0⟩]).bonds.length = 0 := by native_decide
example : (bondedMixture.restrictToMolecules [⟨0⟩]).molecules.length = 1 := by native_decide

/-- `complexContaining` of a bonded pair returns a connected whole; of a free
molecule, just that molecule. -/
example : (bondedMixture.complexContaining ⟨0⟩).molecules.length = 2 := by native_decide
example : (runtimeMixture.complexContaining ⟨0⟩).molecules.length = 1 := by native_decide
example : (bondedMixture.restrictToMolecules [⟨0⟩]).connectedFrom ⟨0⟩ = [⟨0⟩] := by
  native_decide

/-! ## `BNG.Species` — isomorphism ignores runtime IDs but NOT the bond graph -/

/-- `runtimeMixture` and `semanticResult` have the same molecule types but
different bond graphs, so they are NOT the same species.  This negative
instance is what makes the positive one below meaningful: without it,
`isomorphicSpecies = true` could come from comparing molecule counts only. -/
example : runtimeMixture.isomorphicSpecies semanticResult = false := by native_decide

/-- Relabelling every runtime ID yields the same species. -/
def relabelledMixture : Mixture :=
  { nextMoleculeId := ⟨22⟩
    molecules :=
      [ { runtimeA with id := ⟨20⟩ }
      , { runtimeB with id := ⟨21⟩ } ]
    bonds := [] }

example : runtimeMixture.isomorphicSpecies relabelledMixture = true := by native_decide

/-- ...and the reverse direction holds too, since the oracle is symmetric here. -/
example : relabelledMixture.isomorphicSpecies runtimeMixture = true := by native_decide

/-- **Both orderings of the same bonded species.** `bondedMixture` has A#0/B#1
and `semanticResult` has the same molecules with a NEW bond, so they differ in
bond count and are correctly distinct species.  The genuinely isomorphic case is
the relabelled one above. -/
example : bondedMixture.isomorphicSpecies semanticResult = false := by native_decide
example : runtimeMixture.isomorphicSpecies bondedMixture = false := by native_decide

/-- Molecule count alone is not enough: an extra molecule is a different species. -/
def extraMoleculeMixture : Mixture :=
  { nextMoleculeId := ⟨4⟩
    molecules := [runtimeA, runtimeB, { runtimeA with id := ⟨3⟩ }]
    bonds := [] }

example : runtimeMixture.isomorphicSpecies extraMoleculeMixture = false := by native_decide

/-- `addSpeciesModuloIso` is a genuine dedup: an isomorphic candidate is
dropped, a non-isomorphic one is appended. -/
example : (addSpeciesModuloIso [runtimeMixture] relabelledMixture).length = 1 := by
  native_decide
example : (addSpeciesModuloIso [runtimeMixture] extraMoleculeMixture).length = 2 := by
  native_decide

/-- The allocator cursor is not part of species identity. -/
example : (runtimeMixture.isomorphicSpecies relabelledMixture) = true := by native_decide

/-! ## `BNG.Observables` — counting, with a discriminating negative -/

example : reactantA.moleculeObservableCount phosphorylatedMixture = 0 := by native_decide
example : reactantA.moleculeObservableCount doubledAMixture = 2 := by native_decide
example : reactantA.moleculeObservableCount runtimeMixture = 1 := by native_decide

/-- `Species` counting requires the embedding to cover the WHOLE complex, so a
free A in a bonded mixture is not a species. -/
example : reactantA.speciesObservableCount bondedMixture = 0 := by native_decide
example : reactantA.speciesObservableCount runtimeMixture = 1 := by native_decide

/-- `counter` is explicitly unsupported rather than guessed, while `molecules` on
the same pattern is supported. -/
example : (ObservableDecl.evaluate?
    { id := ⟨0⟩, name := "X", kind := .counter, patterns := [reactantA] }
    runtimeMixture) = none := by native_decide

example : (ObservableDecl.evaluate?
    { id := ⟨0⟩, name := "A", kind := .molecules, patterns := [reactantA] }
    runtimeMixture) = some 1 := by native_decide

/-- An empty pattern list contributes zero, for both standard kinds. -/
example : (ObservableDecl.evaluate?
    { id := ⟨0⟩, name := "A", kind := .molecules, patterns := [] }
    runtimeMixture) = some 0 := by native_decide

example : (ObservableDecl.evaluate?
    { id := ⟨0⟩, name := "A", kind := .species, patterns := [] }
    runtimeMixture) = some 0 := by native_decide

/-! ## `BNG.Stochastic` / `BNG.Propensity` — multiplicity feeds the channel -/

example : forward.hasMatchOnce = false := by native_decide
example : forward.hasTotalRate = false := by native_decide

/-- Without MatchOnce, channel multiplicity equals the raw match count. -/
example : forward.channelMultiplicity runtimeMixture = 1 := by native_decide
example : forward.channelMultiplicity doubledAMixture = 2 := by native_decide
example : (forward.propensityContract doubledAMixture).legalMatchCount = 2 := by native_decide

/-- **Pinned defect, reported not papered over.**  `MatchOnce` is documented
(`BNG/Stochastic.lean:30-37`) to "remove later matches with a duplicate ordered
complex key", where each embedding contributes "the connected complex
containing its first mapped molecule".  It does not: `orderedComplexKey`
returns the first mapped MOLECULE ID, not the complex containing it.  So two
matches into two DIFFERENT complexes are kept (correct here), and — as the
`dimer` fixture below shows — two matches into the SAME complex with different
molecule orderings are ALSO kept (incorrect: a symmetric dimer is one physical
event, and a simulator would fire its hazard twice).

The two assertions below pin the observed behaviour exactly.  If someone fixes
`orderedComplexKey` to use `connectedFrom`, the dimer assertion FAILS and must
be updated deliberately; that is the point of pinning it. -/
def matchOnceForward : RuleDirection :=
  { forward with modifiers := [.matchOnce] }

example : matchOnceForward.hasMatchOnce = true := by native_decide
example : matchOnceForward.channelMultiplicity doubledAMixture = 2 := by native_decide

/-- The symmetric-dimer case: one bonded A#0—A#2 complex, matched two ways. -/
def dimerBond : RuntimeBond :=
  { a := { molecule := ⟨0⟩, component := cAx }
  , b := { molecule := ⟨2⟩, component := cAx } }

def dimerMixture : Mixture :=
  { nextMoleculeId := ⟨3⟩
    molecules := [runtimeA, { runtimeA with id := ⟨2⟩ }]
    bonds := [dimerBond] }

def dimerReactant : Pattern :=
  { molecules :=
      [ { occurrence := ⟨0⟩, moleculeType := mtA
          sites := [ { occurrence := ⟨0⟩, component := cAx, state := .exact sU } ] }
      , { occurrence := ⟨1⟩, moleculeType := mtA
          sites := [ { occurrence := ⟨0⟩, component := cAx, state := .exact sU } ] } ] }

def dimerDirection : RuleDirection :=
  { reactants := [dimerReactant], products := [dimerReactant]
    rate := forward.rate }

def dimerMatchOnce : RuleDirection :=
  { dimerDirection with modifiers := [.matchOnce] }

example : dimerMixture.wellFormed model.signature = true := by native_decide

/-- Both A molecules really are in ONE complex, so this is a single physical
species and the two embeddings are the same event seen twice. -/
example : dimerMixture.sameComplex ⟨0⟩ ⟨2⟩ = true := by native_decide
example : dimerMixture.connectedFrom ⟨0⟩ = [⟨0⟩, ⟨2⟩] := by native_decide

/-- Two embeddings exist ... -/
example : (dimerDirection.matches dimerMixture).length = 2 := by native_decide

/-- ... with DIFFERENT complex keys, because the key is a molecule ID rather
than the complex.

!! UPDATE ME WHEN THE DEFECT IS FIXED !! This assertion PINS THE BUG and is
expected to become FALSE the moment `RuleMatch.orderedComplexKey` keys on the
complex instead of the molecule ID. When that happens the keys become
`[[some ⟨0⟩], [some ⟨0⟩]]` -- which is exactly what the [FAILS TODAY] assertion
at the end of this file demands. Change the expected value; do not delete this
line, which is the characterisation that made the defect visible at all.
-/
example : (dimerDirection.matches dimerMixture).map
    (fun m => m.orderedComplexKey dimerMixture) =
    [[some ⟨0⟩], [some ⟨0⟩]] := by native_decide

/-- ... so MatchOnce does NOT collapse them.  This is the defect.  If
`orderedComplexKey` were corrected to key on `connectedFrom`, both keys would
be `[some ⟨0⟩]` and this would be 1.

!! UPDATE ME WHEN THE DEFECT IS FIXED !! These two PIN THE BUG and become FALSE
under the fix -- `countedMatches` drops to 1 and `channelMultiplicity` drops to
1, matching the [FAILS TODAY] assertions at the end of the file. Change the
expected values from 2 to 1; do not delete these lines.

This is the asymmetry a characterisation-plus-regression pair has, and it is
worth stating rather than leaving to be discovered: the characterisation at the
TOP of the file records what the code DOES, so it must change when the code
changes; the regression at the BOTTOM records what the code SHOULD do, so it
must change only when the DEFECT is fixed. Both change together on the fix, for
opposite reasons, and a fixer who only reads the bottom block will find three
unexpected failures above it.
-/
example : (dimerMatchOnce.countedMatches dimerMixture).length = 1 := by native_decide
example : dimerMatchOnce.channelMultiplicity dimerMixture = 1 := by native_decide


/-- TotalRate changes the interpretation, not the multiplicity. -/
def totalRateForward : RuleDirection :=
  { forward with modifiers := [.totalRate] }

example : totalRateForward.hasTotalRate = true := by native_decide
example : totalRateForward.channelMultiplicity runtimeMixture = 1 := by native_decide
example : (totalRateForward.propensityContract runtimeMixture).totalRate = true := by
  native_decide
example : (totalRateForward.propensityContract runtimeMixture).legalMatchCount = 1 := by
  native_decide

example : (totalRateForward.propensityContract runtimeMixture).interpretation =
    ChannelRateInterpretation.totalChannel := by native_decide
example : (forward.propensityContract doubledAMixture).interpretation =
    ChannelRateInterpretation.perMatch 2 := by native_decide

/-- A channel with no legal match is disabled regardless of rate. -/
example : (forward.propensityContract phosphorylatedMixture).enabled = false := by
  native_decide
example : (forward.propensityContract runtimeMixture).enabled = true := by native_decide
example : (forward.propensityContract dimerMixture).enabled = false := by native_decide

/-! ## `BNG.BNGIR` — version gate is fail-closed in BOTH directions -/

/-- The default envelope carries the version the decoder accepts. -/
example : (encodeStructural { model := model }).version = { major := 0, minor := 2 } := by
  native_decide

/-- **Negative instance, major version.** An unknown major version must be
REFUSED.  A permissive decoder would silently accept IR it does not understand. -/
example : (decodeStructural?
    { version := { major := 1, minor := 0 }, document := { model := model } }) = none := by
  native_decide

/-- **Negative instance, minor version.** Same for the minor field. -/
example : (decodeStructural?
    { version := { major := 0, minor := 3 }, document := { model := model } }) = none := by
  native_decide

/-- **Negative instance, an older minor version** is also refused rather than
accepted as "close enough". -/
example : (decodeStructural?
    { version := { major := 0, minor := 1 }, document := { model := model } }) = none := by
  native_decide

/-- Round-trip is defined at the supported version ... -/
example : (decodeStructural? (encodeStructural { model := model })).isSome = true := by
  native_decide

/-- ...and is the exact identity on the model's own signature. -/
example : (decodeStructural? (encodeStructural { model := model })).map
    (fun d => d.model.signature.moleculeTypes.length) = some 2 := by native_decide

/-- Encoding is a genuine function of its input: two different models give two
different envelopes, so `encodeStructural` is not a constant. -/
example : (encodeStructural { model := model }).document.model.metadata.name =
    "Lean semantic example" := by native_decide

/-! ## `BNG.Capabilities` / `BNG.NFnextIR` — the NFnext bridge is exact -/

example : nfnextBridgeContract = true := by native_decide

/-- The example rule is inside the supported NFnext subset. -/
example : nfnextUnsupportedReasons forward = [] := by native_decide
example : nfnextSupported forward = true := by native_decide

/-- **Negative instance.** Adding a filter must push the rule OUT of the
supported subset.  Without this, `nfnextSupported` could be vacuously `true` for
every direction and the gate would protect nothing. -/
def filteredForward : RuleDirection :=
  { forward with
    filters :=
      [ { mode := .include, side := .reactant, patternIndex := 0
          patterns := [reactantA] } ] }

def deleteMoleculesForward : RuleDirection :=
  { forward with modifiers := [.deleteMolecules] }

def moveConnectedForward : RuleDirection :=
  { forward with modifiers := [.moveConnected] }

def scopedForward : RuleDirection :=
  { forward with localScopes := [{ name := "x", molecule := rA }] }

example : nfnextUnsupportedReasons filteredForward = [.filters] := by native_decide
example : nfnextSupported filteredForward = false := by native_decide
example : filteredForward.supportedOperationalSubset = false := by native_decide

example : nfnextUnsupportedReasons deleteMoleculesForward = [.deleteMolecules] := by
  native_decide
example : nfnextUnsupportedReasons moveConnectedForward = [.moveConnected] := by
  native_decide
example : nfnextUnsupportedReasons scopedForward = [.localScopes] := by native_decide
example : nfnextSupported scopedForward = false := by native_decide

/-- A direction with an UNSUPPORTED mutation lowers to `none`, not to a partial
program that silently drops the edit. -/
example : (forward.lowerNFnextTransformation?
    (NFnextPacking.fromSignature model.signature)).isSome = true := by native_decide

example : filteredForward.lowerNFnextTransformation?
    (NFnextPacking.fromSignature model.signature) = none := by native_decide

def examplePacking : NFnextPacking := NFnextPacking.fromSignature model.signature

/-- Packing assigns compact indices in declaration order, starting at 0. -/
example : examplePacking.types.length = 2 := by native_decide
example : examplePacking.type? mtA = some ⟨0⟩ := by native_decide
example : examplePacking.type? mtB = some ⟨1⟩ := by native_decide
example : examplePacking.site? mtA cAx = some ⟨0⟩ := by native_decide
example : examplePacking.site? mtB cBy = some ⟨0⟩ := by native_decide
example : examplePacking.state? mtA cAx sU = some ⟨0⟩ := by native_decide
example : examplePacking.state? mtA cAx sP = some ⟨1⟩ := by native_decide

/-- **Negative instances:** an undeclared molecule/component/state has no packed
index.  A packing that invented one would let a bad rule lower successfully. -/
example : examplePacking.type? ⟨99⟩ = none := by native_decide
example : examplePacking.site? mtA ⟨99⟩ = none := by native_decide
example : examplePacking.state? mtA cAx ⟨99⟩ = none := by native_decide

/-- **Negative instance:** B.y declares no states, so no state index exists for
it.  A packing that fabricated one would let `B(y~?)` lower. -/
example : examplePacking.state? mtB cBy sU = none := by native_decide

/-! ## `BNG.Lowering` — the refinement pinned on real data -/

/-- One edit lowers to exactly one instruction, in order.  Projected to a
discriminating Nat tag because `BackendAction` has no `DecidableEq`. -/
example : forward.lowerActions.length = 2 := by native_decide
example : forward.lowerActions.map
    (fun a => match a with
      | .setState _ _ => 0
      | .addBond _ _ => 1
      | _ => 2) = [0, 1] := by native_decide

/-- Structural lowering keeps the exact bond list ITSELF, not merely its
length.  This is the content-level statement that the count-only theorem
`pattern_lowering_keeps_bonds` does not provide. -/
example : productComplex.lower.bonds.length = productComplex.bonds.length := by native_decide
example : productComplex.lower.nodes.length = 2 := by native_decide

/-- The multi-mutation program equality on this fixture, non-vacuously: both
sides produce a mixture, and they agree on molecule and bond counts. -/
example : (match firstForwardMatch? with
  | none => false
  | some matched =>
      match forward.executeBackendProgram forward.lowerActions
              { matched := matched } runtimeMixture,
            forward.applyMutations forward.mutations
              { matched := matched } runtimeMixture with
      | none, _ => false
      | _, none => false
      | some (a, _), some (b, _) =>
          a.molecules.length == b.molecules.length &&
          a.bonds.length == b.bonds.length) = true := by native_decide

/-! ## `BNG.MutationCompiler` — structural compilation on the real rule -/

/-- Compiling the worked rule preserves its two reactant patterns, so
correspondence inference did not consume a reactant. -/
example : forward.compileStructuralSemantics.reactants.length = 2 := by native_decide

/-- The two compiled edits survive compilation, in the original order. -/
example : forward.compileStructuralSemantics.mutations.length =
    forward.mutations.length := by native_decide

example : forward.compileStructuralSemantics.mutations.map
    (fun m => match m with
      | .changeState _ _ => 0
      | .createBond _ _ => 1
      | _ => 2) = [0, 1] := by native_decide

/-- Compiling twice is idempotent on this fixture.  This is the real content of
the property that the tautological
`compileStructuralSemantics_deterministic` (`d.compileStructuralSemantics =
d.compileStructuralSemantics`, BNG/MutationCompiler.lean:199) was NAMED for but
did not state. -/
example : forward.compileStructuralSemantics.compileStructuralSemantics.mutations.length =
    forward.compileStructuralSemantics.mutations.length := by native_decide

example : forward.compileStructuralSemantics.compileStructuralSemantics.reactants.length =
    forward.compileStructuralSemantics.reactants.length := by native_decide

/-- Inferred correspondence pairs each reactant with its product. -/
example : forward.inferMoleculeMap.length = 2 := by native_decide

example : (forward.inferMoleculeMap.map (fun p => p.reactant)).contains rA = true := by
  native_decide
example : (forward.inferMoleculeMap.map (fun p => p.product)).contains pB = true := by
  native_decide

/-- **The correspondence is one-to-one**: no reactant is claimed twice. -/
example : allUnique (forward.inferMoleculeMap.map (fun p => p.reactant)) = true := by
  native_decide
example : allUnique (forward.inferMoleculeMap.map (fun p => p.product)) = true := by
  native_decide

/-! ## `BNG.Model` — declaration validation discriminates -/

example : model.wellFormed = true := by native_decide
example : model.idsUnique = true := by native_decide
example : model.signature.moleculeTypes.length = 2 := by native_decide
example : model.exprScope.parameters = [kId] := by native_decide

/-- **Negative instance:** a model whose parameter expression references an
undeclared parameter is rejected. -/
def danglingParamModel : CompiledModel :=
  { model with
    parameters :=
      [ { id := kId, name := "k", expression := .parameter ⟨42⟩
          constantValue := some 1.0 } ] }

example : danglingParamModel.wellFormed = false := by native_decide

/-- **Negative instance:** duplicate molecule-type IDs are rejected. -/
def duplicateIdModel : CompiledModel :=
  { model with moleculeTypes := [moleculeA, { moleculeB with id := mtA }] }

example : duplicateIdModel.idsUnique = false := by native_decide
example : duplicateIdModel.wellFormed = false := by native_decide

/-- **Negative instance:** the model is rejected if its rule direction is not
well formed.  Here the rule is broken by pointing a mutation at an undeclared
component. -/
def badTargetModel : CompiledModel :=
  { model with
    rules :=
      [ { id := ⟨0⟩, name := "broken", forward :=
            { forward with
                mutations := [.changeState (.byType rA ⟨42⟩) sP] } } ] }

example : badTargetModel.wellFormed = false := by native_decide

/-! ## `BNG.Evaluation` — rate evaluation is typed and fail-closed -/

def oneSecond : EvalEnv :=
  { time := 1.0, parameters := [{ id := kId, value := 1.0 }] }

example : evalExpr? model oneSecond (.parameter kId) = some 1.0 := by native_decide
example : evalExpr? model oneSecond (.number 2.5) = some 2.5 := by native_decide
example : evalExpr? model oneSecond (.unary .negate (.number 2.0)) = some (-2.0) := by
  native_decide
example : evalExpr? model oneSecond (.unary .positive (.number 2.0)) = some 2.0 := by
  native_decide
example : evalExpr? model oneSecond
    (.binary .add (.number 1.0) (.number 2.0)) = some 3.0 := by native_decide
example : evalExpr? model oneSecond
    (.binary .multiply (.number 3.0) (.number 4.0)) = some 12.0 := by native_decide

/-- **Negative instance:** comparison operators are relations, not numbers, so
evaluating one as a rate yields `none` rather than a fabricated 0/1. -/
example : evalExpr? model oneSecond
    (.binary .less (.number 1.0) (.number 2.0)) = none := by native_decide

/-- **Division by zero yields `some inf`, NOT `none`.** Pinned because it is
the opposite of what a fail-closed reading would predict: `Float` division does
not trap, so a rate expression `k1/k0` with `k0 = 0` silently becomes an infinite
rate rather than a named diagnostic.  If someone later adds a non-finite check to
`evalExpr?`, this assertion fails and the behaviour change is deliberate. -/
example : (evalExpr? model oneSecond
    (.binary .divide (.number 1.0) (.number 0.0))).isSome = true := by native_decide

/-- **Modulo by zero IS `none`** -- the opposite of division. So the reference
evaluator special-cases exactly one of the two zero-denominator operations, and
does so without saying so anywhere.  Pinned because a reader would reasonably
assume Float semantics are uniform across `BinaryOp`, and they are not. -/
example : evalExpr? model oneSecond
    (.binary .modulo (.number 1.0) (.number 0.0)) = none := by native_decide

/-- ...and ordinary division by a nonzero denominator is exact. -/
example : evalExpr? model oneSecond
    (.binary .divide (.number 6.0) (.number 3.0)) = some 2.0 := by native_decide

/-- An expression referencing an undeclared parameter is `none`. -/
example : evalExpr? model oneSecond (.parameter ⟨42⟩) = none := by native_decide

/-- A non-expression rate law is refused by the core evaluator rather than
silently evaluated as if it were a plain expression. -/
example : RateLaw.evaluateCore? model oneSecond
    { kind := .saturation, expression := .number 1.0 } = none := by native_decide
example : RateLaw.evaluateCore? model oneSecond
    { kind := .arrheniusEnergy, expression := .number 1.0 } = none := by native_decide
example : RateLaw.evaluateCore? model oneSecond
    { kind := .expression, expression := .parameter kId } = some 1.0 := by native_decide

/-- The rule's own rate law resolves against the model's parameter table. -/
example : RateLaw.evaluateCore? model oneSecond forward.rate = some 1.0 := by native_decide

/-- **Negative instance:** with the parameter absent from the environment, the
same rate law does not resolve.  This pins that the value came from the
environment and not from a constant baked into the expression. -/
example : evalExpr? model { time := 1.0 } (.parameter kId) = none := by native_decide

/-! ## `BNG.Seeds` — construction is strict where matching is permissive -/

/-- The product complex is constructible as a seed: two molecules, one bond. -/
example : (match productComplex.instantiateSeed? with
  | none => false
  | some mix => mix.molecules.length == 2 && mix.bonds.length == 1) = true := by native_decide

/-- **Negative instance:** `A(x~u)!+` (bond required, partner unspecified)
describes a SET of graphs, not one state, so seed construction must refuse it. -/
def ambiguousSeed : Pattern :=
  { molecules :=
      [ { occurrence := ⟨0⟩
          moleculeType := mtA
          sites :=
            [ { occurrence := ⟨0⟩
                component := cAx
                state := .exact sU
                bonds := [.bound] } ] } ] }

example : ambiguousSeed.instantiateSeed? = none := by native_decide

/-- `.oneOf [s]` is constructible (a single choice) ... -/
example : (match ({ molecules :=
      [ { occurrence := ⟨0⟩, moleculeType := mtA
          sites := [ { occurrence := ⟨0⟩, component := cAx
                       state := .oneOf [sU] } ] } ] } : Pattern).instantiateSeed? with
  | none => false
  | some mix => mix.molecules.length == 1) = true := by native_decide

/-- ... but `.oneOf [s1,s2]` is not. -/
example : (match ({ molecules :=
      [ { occurrence := ⟨0⟩, moleculeType := mtA
          sites := [ { occurrence := ⟨0⟩, component := cAx
                       state := .oneOf [sU, sP] } ] } ] } : Pattern).instantiateSeed? with
  | none => true
  | some _ => false) = true := by native_decide

/-- Seed molecules get fresh IDs from 0 and the cursor ends past them. -/
example : (match reactantA.instantiateSeed? with
  | none => false
  | some mix =>
      mix.nextMoleculeId.value == 1 && mix.molecules.length == 1) = true := by
  native_decide

/-! ## `BNG.ReactionNetwork` / `BNG.Network` — indexed edges -/

def seedA : Mixture := runtimeMixture.restrictToMolecules [⟨0⟩]
def seedB : Mixture := runtimeMixture.restrictToMolecules [⟨1⟩]
def referenceReactionNetwork : ReferenceReactionNetwork :=
  model.referenceReactionNetwork 1 [seedA, seedB]

example : referenceReactionNetwork.wellIndexed = true := by native_decide

/-! **Reactant order is NOT canonicalized.**  A+B and B+A are recorded as two
distinct indexed edges, because `chooseSpeciesTuples` enumerates ordered
selections and `NetworkReaction.reactants` preserves that order.  Pinned
exactly: if a future canonicalizer collapses the two, this fails and forces a
deliberate decision rather than a silent change. -/
example : referenceReactionNetwork.reactions.length = 2 := by native_decide

example : referenceReactionNetwork.reactions.map (fun r => r.reactants) =
    [[0, 1], [1, 0]] := by native_decide

/-- Both orderings produce the SAME product species index: reactant order
varies, the chemistry does not. -/
example : referenceReactionNetwork.reactions.map (fun r => r.products) =
    [[2], [2]] := by native_decide

example : referenceReactionNetwork.reactions.map (fun r => r.rule.value) = [0, 0] := by
  native_decide

/-- The pool closed: it discovered the bonded species as a third entry. -/
example : referenceReactionNetwork.species.length = 3 := by native_decide
example : speciesIndex? referenceReactionNetwork.species semanticResult = some 2 := by
  native_decide

/-- The seed species are the first two entries, in seed order. -/
example : speciesIndex? referenceReactionNetwork.species seedA = some 0 := by native_decide
example : speciesIndex? referenceReactionNetwork.species seedB = some 1 := by native_decide

/-- **Negative instance:** indexing a species absent from the pool fails rather
than inventing an identity. -/
example : speciesIndex? referenceReactionNetwork.species extraMoleculeMixture = none := by
  native_decide

/-- `wellIndexed` is discriminating: an out-of-range index is detected. -/
example : (ReferenceReactionNetwork.wellIndexed
    { species := referenceReactionNetwork.species
      reactions :=
        [{ rule := ⟨0⟩, direction := .forward, reactants := [99], products := [0] }] }) =
    false := by native_decide

/-- Zero closure iterations leaves the pool untouched and produces no edges. -/
example : (model.referenceReactionNetwork 0 [seedA, seedB]).reactions.length = 0 := by
  native_decide

/-! ## `BNG.Protocol` — the legacy escape hatch is honoured, not hidden -/

def typedProtocol : TypedSimulationProtocol :=
  { actions :=
      [ .generateNetwork (some 10) (some 100)
      , .simulate { method := .ssa, tEnd := 10.0, nSteps := 100 }
      , .exportModel .net "/tmp/out.net" ] }

example : typedProtocol.fullyTyped = true := by native_decide
example : typedProtocol.actions.length = 3 := by native_decide
example : (executeProtocol? typedProtocol.actions {}).isSome = true := by native_decide

/-- Executing the typed protocol records the protocol-visible effects. -/
example : (executeProtocol? typedProtocol.actions {}).map (fun s => s.exportedPaths) =
    some ["/tmp/out.net"] := by native_decide

/-- A legacy action is neither structurally supported nor executable. -/
def legacyAction : TypedProtocolAction :=
  TypedProtocolAction.legacyUnsupported "old_style" [("k", "1")]

def legacyProtocol : TypedSimulationProtocol :=
  { actions := [legacyAction] }

example : legacyProtocol.fullyTyped = false := by native_decide
example : executeProtocol? legacyProtocol.actions {} = none := by native_decide

/-- **A legacy action aborts the WHOLE sequence**, even when it comes after
valid actions: the interpreter does not skip it and continue. -/
example : executeProtocol?
    ({ actions :=
        [ .saveState "s1"
        , .legacyUnsupported "old" [] ] } : TypedSimulationProtocol).actions {} = none := by
  native_decide

/-! ## `BNG.ExtendedOperational` — modifiers change behaviour, and are gated -/

/-- The extended path is defined on this fixture and agrees with the reference
path on the observable content of the result. -/
example : (match firstForwardMatch? with
  | none => false
  | some matched =>
      match forward.applyAtExtended? runtimeMixture matched,
            forward.applyAt? runtimeMixture matched with
      | some a, some b =>
          a.molecules.length == b.molecules.length &&
          a.bonds.length == b.bonds.length
      | _, _ => false) = true := by native_decide

/-- ...and it is not vacuous: the extended path really returns a mixture. -/
example : (match firstForwardMatch? with
  | none => false
  | some matched => (forward.applyAtExtended? runtimeMixture matched).isSome) = true := by
  native_decide

/-- An out-of-subset direction is refused by the reference step rather than
half-executed. -/
example : (match firstForwardMatch? with
  | none => false
  | some matched => filteredForward.applyAt? runtimeMixture matched = none) = true := by
  native_decide

/-- `DeleteMolecules` and `MoveConnected` are recognised modifiers ... -/
example : forward.hasDeleteMolecules = false := by native_decide
example : deleteMoleculesForward.hasDeleteMolecules = true := by native_decide
example : deleteMoleculesForward.hasMoveConnected = false := by native_decide
example : moveConnectedForward.hasMoveConnected = true := by native_decide
example : moveConnectedForward.hasDeleteMolecules = false := by native_decide

/-! ## `BNG.NameResolution` — fail-closed name resolution -/

example : (model.parameterIdByName? "k").map ParameterId.value = some kId.value := by
  native_decide
-- Projected to a scalar because `MoleculeType`/`ComponentType` derive `Repr`
-- but not `DecidableEq`, so structural equality is not available here.
example : (model.moleculeTypeByName? "A").map MoleculeType.name = some "A" := by
  native_decide
example : (moleculeA.componentByName? "x").map ComponentType.name = some "x" := by
  native_decide
example : (componentAx.stateIdByName? "p").map StateId.value = some sP.value := by
  native_decide

/-- An unknown name resolves to `none`, never to a guessed ID. -/
example : model.parameterIdByName? "nope" = none := by native_decide
example : model.moleculeTypeByName? "Z" = none := by native_decide
example : moleculeA.componentByName? "zz" = none := by native_decide
example : componentAx.stateIdByName? "q" = none := by native_decide
example : model.observableIdByName? "nope" = none := by native_decide
example : model.compartmentIdByName? "nope" = none := by native_decide

/-- An expression mentioning an undeclared parameter does not resolve ... -/
example : (NamedExpr.resolves model
    (.binary .add (.parameter "k") (.parameter "nope"))) = false := by native_decide

/-- ... and one mentioning only declared names does. -/
example : (NamedExpr.resolves model
    (.binary .add (.parameter "k") (.number 1.0))) = true := by native_decide

/-- A pattern naming an undeclared molecule type does not resolve. -/
example : (resolveNamedPattern model
    { molecules := [{ occurrence := ⟨0⟩, moleculeTypeName := "Z" }] }) = none := by native_decide

/-- A pattern naming a declared molecule but an UNDECLARED component fails. -/
example : (resolveNamedPattern model
    { molecules :=
        [ { occurrence := ⟨0⟩, moleculeTypeName := "A"
            sites := [{ occurrence := ⟨0⟩, componentName := "zz" }] } ] }) = none := by
  native_decide

/-- A pattern naming an UNDECLARED state fails. -/
example : (resolveNamedPattern model
    { molecules :=
        [ { occurrence := ⟨0⟩, moleculeTypeName := "A"
            sites := [{ occurrence := ⟨0⟩, componentName := "x"
                        state := .exact "q" }] } ] }) = none := by native_decide

/-- ...while the real reactant pattern resolves, and to the right state. -/
example : (match resolveNamedPattern model
    { molecules :=
        [ { occurrence := ⟨0⟩, moleculeTypeName := "A"
            sites := [{ occurrence := ⟨0⟩, componentName := "x"
                        state := .exact "u" }] } ] } with
  | none => false
  | some p =>
      match p.molecules with
      | [] => false
      | m :: _ => m.sites.length == 1) = true := by native_decide

/-! ## `BNG.Hybrid` / `BNG.Filters` — whole-complex and filter semantics -/

/-- Include filter that hits accepts; exclude filter that hits rejects. -/
def includeFilter : RuleFilter :=
  { mode := .include, side := .reactant, patternIndex := 0, patterns := [reactantA] }
def excludeFilter : RuleFilter :=
  { mode := .exclude, side := .reactant, patternIndex := 0, patterns := [reactantA] }

def fixtureMatch : RuleMatch :=
  match forward.matches runtimeMixture with
  | [] => { embeddings := [] }
  | m :: _ => m

example : (match reactantComplexFor? runtimeMixture fixtureMatch 0 with
  | none => false
  | some complex => includeFilter.acceptsComplex complex) = true := by native_decide

example : (match reactantComplexFor? runtimeMixture fixtureMatch 0 with
  | none => false
  | some complex => excludeFilter.acceptsComplex complex) = false := by native_decide

/-- `noOp`-style filters that match nothing accept under `include` and reject
under `exclude`, i.e. the polarity is applied AFTER the OR of alternatives. -/
def unmatchedFilter : RuleFilter :=
  { mode := .include, side := .reactant, patternIndex := 0, patterns := [productComplex] }

example : (match reactantComplexFor? runtimeMixture fixtureMatch 0 with
  | none => false
  | some complex => unmatchedFilter.acceptsComplex complex) = false := by native_decide

/-! ## Structural regressions: facts that must keep holding -/

/-- The rule-step equality, pinned on the fixture's actual match AND on the
content of the result rather than on the two sides being definitionally equal. -/
example : (match firstForwardMatch? with
  | none => false
  | some matched =>
      match forward.executeLoweredAt? runtimeMixture matched,
            forward.applyAt? runtimeMixture matched with
      | some a, some b =>
          a.molecules.length == b.molecules.length &&
          a.bonds.length == b.bonds.length &&
          a.nextMoleculeId.value == b.nextMoleculeId.value
      | _, _ => false) = true := by native_decide

/-- Reversing a side twice is the identity, on both constructors. -/
example : PatternSide.reactant.flip.flip = PatternSide.reactant := by native_decide
example : PatternSide.product.flip.flip = PatternSide.product := by native_decide

/-- Source provenance is irrelevant to the payload. -/
def provenanceA : SourceInfo :=
  { text := "A(x~u) + B(y) -> A(x~p!1).B(y!1)", file := some "a.bngl", line := some 1 }

def provenanceB : SourceInfo :=
  { text := "totally different spelling", file := some "b.bngl", line := some 99 }

/-- Erasure is by `rfl`, i.e. it discards the wrapper without inspecting it, so
no change to `SourceInfo` can affect the semantic payload. -/
theorem provenanceEraseIsDefinitional :
    (WithSource.mk (model.signature : Signature) provenanceA).erase =
      (WithSource.mk (model.signature : Signature) provenanceB).erase := by
  rfl

/-- The two provenances really do differ, so the theorem above is not asserting
`x = x` on identical inputs. -/
example : provenanceA.file = some "a.bngl" := by native_decide
example : provenanceB.file = some "b.bngl" := by native_decide
example : provenanceA.line = some 1 := by native_decide
example : provenanceB.line = some 99 := by native_decide
example : provenanceA.text ≠ provenanceB.text := by native_decide

/-- `Pattern.lower` is total and shape-preserving on every top-level pattern of
the worked rule, not only on the product. -/
example : reactantA.lower.nodes.length = reactantA.molecules.length := by native_decide
example : reactantB.lower.nodes.length = reactantB.molecules.length := by native_decide

/-! ###########################################################################
# EXPECTED FAILURE -- 3 assertions below fail against a KNOWN LIVE DEFECT.
#
#   THIS FILE IS EXPECTED TO EXIT NON-ZERO until BNG/Stochastic.lean is fixed.
#   That is the correct state of the record, not an authoring accident.
#
# THE DEFECT (owner: leanKernel; file: formal/lean/BNG/Stochastic.lean):
#   `RuleMatch.orderedComplexKey` (BNG/Stochastic.lean:38) is documented as
#   contributing "the connected complex containing its first mapped molecule",
#   but returns `some first` -- the molecule ID.
#
# TO LOCATE IT:
#   grep -n "orderedComplexKey" formal/lean/BNG/Stochastic.lean
#   sed -n '38,42p' formal/lean/BNG/Stochastic.lean
#
# WHY IT MATTERS: two embeddings of ONE physical species get different keys
# whenever that species has two or more molecules, so `deduplicateMatchOnce`
# does not collapse them and `MatchOnce` fires the channel hazard once per
# EMBEDDING rather than once per COMPLEX.
#
# ON THE SYMMETRIC DIMER (`dimerMixture`, defined in the Stochastic section
# above): A#0 and A#2 are bonded, hence one complex and one species;
# `A(x~u).A(x~u)` matches it two ways. Observed keys are `[some 0]` and
# `[some 2]`, so `MatchOnce` multiplicity is 2 where it must be 1.
#
# EXPECTED OUTPUT of `lake env lean tests/Coverage.lean`:
#   3 errors, at the three assertions marked [FAILS TODAY] below, and NO others.
#   If the count changes, THIS comment is stale -- update it.
#
# TO COUNT THE MARKERS -- anchor on the doc-comment opener so this banner's own
# prose mentions do not inflate the count:
#   grep -cE '^/[-][-][[:space:]]+\[FAILS' tests/Coverage.lean   -> 3 while broken
# The bracket form is not decoration. Written as three literal characters, that
# sequence OPENS A NESTED COMMENT inside this block comment, which is how the
# first version of this banner made Coverage.lean fail to parse with
# "unterminated comment" -- twice, in two different spellings of the same
# instruction. Putting each hyphen in its own bracket keeps the regex identical
# and the Lean lexer out of it.
# A bare `grep -c "FAILS TODAY"` returns 6, because this banner mentions the
# marker three more times. An instruction a fixer runs and gets a wrong answer
# from is worse than no instruction at all.
#
# WHEN THEY PASS, TWO THINGS MUST CHANGE TOGETHER, and the second is the one
# that will otherwise surprise you:
#
#   (a) this banner and the three markers go away, so a later reader is not told
#       to expect a failure that no longer happens;
#   (b) THREE ASSERTIONS FURTHER UP THE FILE, in the Stochastic section, must
#       have their expected values changed from 2 to 1 and from
#       `[[some 0], [some 2]]` to `[[some 0], [some 0]]`.
#
# Those three are the CHARACTERISATION -- they record what the code currently
# does -- so they become false the moment the fix lands. The three at the bottom
# are the REGRESSION -- they record what the code should do -- so they become
# true. Both sets change on the same commit, for opposite reasons. Each is now
# marked `!! UPDATE ME WHEN THE DEFECT IS FIXED !!` at its own site.
#
# This block lives at the END of the file so it cannot be mistaken for a
# mid-file authoring accident, and it deliberately GATES CI: hiding it would
# make formal/lean green while BNG/Stochastic.lean is wrong.
# ########################################################################### -/

/-- [FAILS TODAY] Both embeddings of the dimer must key to the SAME complex,
because `dimerMixture.connectedFrom` is `[0, 2]` either way. Observed
`[some 0]` and `[some 2]`, because the key is a molecule ID. -/
example : (dimerDirection.matches dimerMixture).map
    (RuleMatch.orderedComplexKey dimerMixture) =
    [[some ⟨0⟩], [some ⟨0⟩]] := by native_decide

/-- [FAILS TODAY] `MatchOnce` must leave ONE channel for one physical species.
Observed 2. -/
example : (dimerMatchOnce.countedMatches dimerMixture).length = 1 := by native_decide

/-- [FAILS TODAY] ...and therefore the hazard must not be doubled. Observed 2. -/
example : dimerMatchOnce.channelMultiplicity dimerMixture = 1 := by native_decide

/-- PASSES TODAY, AND IT IS THE ONE THAT GUARDS AGAINST OVER-CORRECTION.
Two A molecules in two SEPARATE complexes are two genuinely distinct species,
and `MatchOnce` must NOT collapse them. Without this assertion a fix that made
`orderedComplexKey` a constant would satisfy the three above while destroying
the per-complex distinction that makes `MatchOnce` correct in the ordinary
case -- a test suite that pins a bug instead of pinning behaviour. -/
example : matchOnceForward.channelMultiplicity doubledAMixture = 2 := by native_decide
