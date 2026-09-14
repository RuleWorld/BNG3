import BNG

open BNG
open BNG.Examples

/-!
# Smoke checks

These `#eval`s are intentionally human-readable.  A successful run should show:

* the model and starting concrete mixture are well formed (`true`);
* the whole binding/phosphorylation rule has exactly one match (`1`);
* applying it phosphorylates A and creates the A-B bond (`true`, `true`).
-/

#eval model.wellFormed
#eval runtimeMixture.wellFormed model.signature
#eval (forward.matches runtimeMixture).length
#eval resultAIsPhosphorylated
#eval resultHasABBond

example (matched : RuleMatch) :
    forward.executeLoweredAt? runtimeMixture matched =
      forward.applyAt? runtimeMixture matched := by
  exact execute_lowered_rule_eq_reference forward runtimeMixture matched

/-! Additional source-level smoke probes for the expanded semantic layers. -/
#eval (forward.compileStructuralSemantics.mutations.length)
#eval (NFnextPacking.fromSignature model.signature).types.length
#eval nfnextUnsupportedReasons forward
#eval (forward.countedMatches runtimeMixture).length
#eval productComplex.instantiateSeed?.isSome

/-! Reaction-network edge smoke probe.  The starting pool contains A and B as
separate species; one closure step should be able to record an indexed A+B ->
A.B reaction and every resulting edge must refer to valid species indices. -/
def seedA : Mixture := runtimeMixture.restrictToMolecules [⟨0⟩]
def seedB : Mixture := runtimeMixture.restrictToMolecules [⟨1⟩]
def referenceReactionNetwork := model.referenceReactionNetwork 1 [seedA, seedB]
#eval referenceReactionNetwork.wellIndexed
#eval referenceReactionNetwork.reactions.length
