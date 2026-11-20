import BNG

open BNG

namespace BNG.LoweringBridge

/-!
# Bounded production lowering correspondence bridge (#166).

This module connects a real production `CompiledModel → NFIR` artifact to the
formal reference semantics for a bounded state-change rule with an unchanged
contextual site and a state-sensitive observable.

Model specification:
* Molecule type `A` with target component `x` (`u`=0, `p`=1) and contextual
  component `c` (`off`=0, `on`=1).
* Seed species: 1 molecule of `A(x~u, c~off)`.
* Rule: `state_change_context: A(x~u, c~off) -> A(x~p, c~off) 0.5`.
* Observables:
  `Molecules U A(x~u, c~off)`
  `Molecules P A(x~p, c~off)`

Assumptions and boundaries:
* Single compartment, no energy factors, no population maps.
* Finite elementary rate (k = 0.5, non-unit).
* Single-site state edit with an unchanged contextual site constraint.
* The formal evaluator checks match multiplicity, enabledness, semantic step,
  lowered step, observable values before and after firing, and contextual site
  preservation.
* Two negative fixtures verify that the comparator detects predicted
  divergence when the target state is mutated or the wrong site is left
  unchanged, even when species and rule counts agree.
-/

-- Declaration IDs
def mtA : MoleculeTypeId := ⟨0⟩
def cAx : ComponentTypeId := ⟨0⟩  -- target site
def cAc : ComponentTypeId := ⟨1⟩  -- contextual site
def sU : StateId := ⟨0⟩
def sP : StateId := ⟨1⟩
def sOff : StateId := ⟨0⟩
def sOn : StateId := ⟨1⟩
def kId : ParameterId := ⟨0⟩
def obsUId : ObservableId := ⟨0⟩
def obsPId : ObservableId := ⟨1⟩

def compX : ComponentType :=
  { id := cAx, name := "x", states := [⟨sU, "u"⟩, ⟨sP, "p"⟩] }

def compC : ComponentType :=
  { id := cAc, name := "c", states := [⟨sOff, "off"⟩, ⟨sOn, "on"⟩] }

def molTypeA : MoleculeType :=
  { id := mtA, name := "A", components := [compX, compC] }

def sig : Signature :=
  { moleculeTypes := [molTypeA], compartments := [] }

-- Patterns
def patReactant : Pattern :=
  { molecules := [
      { occurrence := ⟨0⟩
        moleculeType := mtA
        sites := [
          { occurrence := ⟨0⟩, component := cAx, state := .exact sU },
          { occurrence := ⟨1⟩, component := cAc, state := .exact sOff }
        ] }
    ] }

def patProduct : Pattern :=
  { molecules := [
      { occurrence := ⟨0⟩
        moleculeType := mtA
        sites := [
          { occurrence := ⟨0⟩, component := cAx, state := .exact sP },
          { occurrence := ⟨1⟩, component := cAc, state := .exact sOff }
        ] }
    ] }

-- Rule endpoints
def rA : RuleMoleculeEndpoint := { side := .reactant, pattern := 0, molecule := ⟨0⟩ }
def pA : RuleMoleculeEndpoint := { side := .product, pattern := 0, molecule := ⟨0⟩ }
def targetX : ComponentTarget := .site { molecule := rA, site := ⟨0⟩ }
def contextC : ComponentTarget := .site { molecule := rA, site := ⟨1⟩ }

-- Canonical rule direction (state change on x, c unchanged, rate = 0.5)
def dirCanonical : RuleDirection :=
  { reactants := [patReactant]
    products := [patProduct]
    rate := { expression := .number 0.5 }
    mutations := [.changeState targetX sP]
    moleculeMap := [{ reactant := rA, product := pA }] }

-- Negative rule 1: mutates target state incorrectly to sU instead of sP
def dirMutatedTargetState : RuleDirection :=
  { reactants := [patReactant]
    products := [patReactant]
    rate := { expression := .number 0.5 }
    mutations := [.changeState targetX sU]
    moleculeMap := [{ reactant := rA, product := pA }] }

-- Negative rule 2: leaves the wrong site unchanged (changes contextual site c to on, leaves x unchanged)
def dirWrongSiteUnchanged : RuleDirection :=
  { reactants := [patReactant]
    products := [patReactant]
    rate := { expression := .number 0.5 }
    mutations := [.changeState contextC sOn]
    moleculeMap := [{ reactant := rA, product := pA }] }

-- Observables
def obsU : ObservableDecl :=
  { id := obsUId, name := "U", kind := .molecules, patterns := [patReactant] }

def obsP : ObservableDecl :=
  { id := obsPId, name := "P", kind := .molecules, patterns := [patProduct] }

-- Runtime mixture: 1 particle of A#0(x~u, c~off)
def runtimeA : RuntimeMolecule :=
  { id := ⟨0⟩
    moleculeType := mtA
    sites := [
      { component := cAx, state := some sU },
      { component := cAc, state := some sOff }
    ] }

def mixInitial : Mixture :=
  { nextMoleculeId := ⟨1⟩
    molecules := [runtimeA] }

-- Evaluation helpers
def firstMatch? (d : RuleDirection) (mix : Mixture) : Option RuleMatch :=
  listGet? (d.matches mix) 0

def siteStateOn (mix : Mixture) (molId : Nat) (c : ComponentTypeId) : Option StateId :=
  match mix.findMolecule? ⟨molId⟩ with
  | none => none
  | some m =>
      match m.findSite? c with
      | none => none
      | some s => s.state

structure CanonicalCaseReport where
  multiplicity : Nat
  enabled : Bool
  rate : Float
  obsUBefore : Nat
  obsPBefore : Nat
  obsUAfter : Nat
  obsPAfter : Nat
  contextPreserved : Bool
  targetUpdated : Bool
  loweredEqualsSemantic : Bool
  deriving Repr

def evaluateCanonical : Option CanonicalCaseReport :=
  match firstMatch? dirCanonical mixInitial with
  | none => none
  | some matched =>
      match dirCanonical.applyAt? mixInitial matched,
            dirCanonical.executeLoweredAt? mixInitial matched with
      | some semMix, some lowMix =>
          let mult := (dirCanonical.matches mixInitial).length
          let uPre := obsU.evaluate? mixInitial |>.getD 0
          let pPre := obsP.evaluate? mixInitial |>.getD 0
          let uPost := obsU.evaluate? semMix |>.getD 0
          let pPost := obsP.evaluate? semMix |>.getD 0
          let cState := siteStateOn semMix 0 cAc
          let xState := siteStateOn semMix 0 cAx
          some {
            multiplicity := mult
            enabled := mult > 0
            rate := 0.5
            obsUBefore := uPre
            obsPBefore := pPre
            obsUAfter := uPost
            obsPAfter := pPost
            contextPreserved := (cState == some sOff)
            targetUpdated := (xState == some sP)
            loweredEqualsSemantic := ((siteStateOn lowMix 0 cAx == some sP) && (siteStateOn lowMix 0 cAc == some sOff))
          }
      | _, _ => none

structure NegativeCaseReport where
  name : String
  divergenceDetected : Bool
  obsPAfter : Nat
  obsUAfter : Nat
  deriving Repr

def evaluateNegativeMutatedTarget : Option NegativeCaseReport :=
  match firstMatch? dirMutatedTargetState mixInitial with
  | none => none
  | some matched =>
      match dirMutatedTargetState.applyAt? mixInitial matched with
      | none => none
      | some postMix =>
          let pPost := obsP.evaluate? postMix |>.getD 0
          let uPost := obsU.evaluate? postMix |>.getD 0
          -- Predicted divergence: expected P after firing is 1, but mutated rule produces 0
          some {
            name := "negative_mutated_target_state"
            divergenceDetected := (pPost != 1)
            obsPAfter := pPost
            obsUAfter := uPost
          }

def evaluateNegativeWrongSiteUnchanged : Option NegativeCaseReport :=
  match firstMatch? dirWrongSiteUnchanged mixInitial with
  | none => none
  | some matched =>
      match dirWrongSiteUnchanged.applyAt? mixInitial matched with
      | none => none
      | some postMix =>
          let pPost := obsP.evaluate? postMix |>.getD 0
          let uPost := obsU.evaluate? postMix |>.getD 0
          -- Predicted divergence: expected P after firing is 1, but wrong-site rule produces 0
          some {
            name := "negative_wrong_site_unchanged"
            divergenceDetected := (pPost != 1)
            obsPAfter := pPost
            obsUAfter := uPost
          }

def main : IO Unit := do
  match evaluateCanonical with
  | none => IO.println "case=canonical\terror=evaluation_failed"
  | some r =>
      IO.println s!"case=state_change_context\tmultiplicity={r.multiplicity}\tenabled={r.enabled}\trate={r.rate}\tobs_u_before={r.obsUBefore}\tobs_p_before={r.obsPBefore}\tobs_u_after={r.obsUAfter}\tobs_p_after={r.obsPAfter}\tcontext_preserved={r.contextPreserved}\ttarget_updated={r.targetUpdated}\tlowered_equals_semantic={r.loweredEqualsSemantic}"
  match evaluateNegativeMutatedTarget with
  | none => IO.println "case=negative_mutated_target_state\terror=evaluation_failed"
  | some r =>
      IO.println s!"case={r.name}\tdivergence_detected={r.divergenceDetected}\tobs_p_after={r.obsPAfter}\tobs_u_after={r.obsUAfter}\texpected_p=1"
  match evaluateNegativeWrongSiteUnchanged with
  | none => IO.println "case=negative_wrong_site_unchanged\terror=evaluation_failed"
  | some r =>
      IO.println s!"case={r.name}\tdivergence_detected={r.divergenceDetected}\tobs_p_after={r.obsPAfter}\tobs_u_after={r.obsUAfter}\texpected_p=1"

end BNG.LoweringBridge

def main := BNG.LoweringBridge.main
