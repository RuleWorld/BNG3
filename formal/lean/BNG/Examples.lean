import Std
import BNG.Lowering

namespace BNG.Examples

open BNG

/-!
# A small worked example

Think of this as the semantic form of a BNGL rule like:

```
A(x~u) + B(y) -> A(x~p!1).B(y!1)  k
```

The point is not the biology.  The point is that after compilation there are
no names to resolve and no BNGL fragments for a simulator to reinterpret.
-/

-- Declaration IDs.
def mtA : MoleculeTypeId := ⟨0⟩
def mtB : MoleculeTypeId := ⟨1⟩
def cAx : ComponentTypeId := ⟨0⟩
def cBy : ComponentTypeId := ⟨1⟩
def sU : StateId := ⟨0⟩
def sP : StateId := ⟨1⟩
def kId : ParameterId := ⟨0⟩

def componentAx : ComponentType :=
  { id := cAx
    name := "x"
    states := [⟨sU, "u"⟩, ⟨sP, "p"⟩] }

def componentBy : ComponentType :=
  { id := cBy, name := "y" }

def moleculeA : MoleculeType :=
  { id := mtA, name := "A", components := [componentAx] }

def moleculeB : MoleculeType :=
  { id := mtB, name := "B", components := [componentBy] }

def reactantA : Pattern :=
  { molecules := [
      { occurrence := ⟨0⟩
        moleculeType := mtA
        sites := [
          { occurrence := ⟨0⟩
            component := cAx
            state := .exact sU }] }] }

def reactantB : Pattern :=
  { molecules := [
      { occurrence := ⟨0⟩
        moleculeType := mtB
        sites := [
          { occurrence := ⟨0⟩
            component := cBy }] }] }

def bond : PatternBond :=
  { group := ⟨0⟩
    a := { molecule := ⟨0⟩, site := ⟨0⟩ }
    b := { molecule := ⟨1⟩, site := ⟨0⟩ } }

def productComplex : Pattern :=
  { molecules := [
      { occurrence := ⟨0⟩
        moleculeType := mtA
        sites := [
          { occurrence := ⟨0⟩
            component := cAx
            state := .exact sP
            bonds := [.exact ⟨0⟩] }] },
      { occurrence := ⟨1⟩
        moleculeType := mtB
        sites := [
          { occurrence := ⟨0⟩
            component := cBy
            bonds := [.exact ⟨0⟩] }] }]
    bonds := [bond] }

-- Rule-level addresses.
def rA : RuleMoleculeEndpoint :=
  { side := .reactant, pattern := 0, molecule := ⟨0⟩ }
def rB : RuleMoleculeEndpoint :=
  { side := .reactant, pattern := 1, molecule := ⟨0⟩ }
def pA : RuleMoleculeEndpoint :=
  { side := .product, pattern := 0, molecule := ⟨0⟩ }
def pB : RuleMoleculeEndpoint :=
  { side := .product, pattern := 0, molecule := ⟨1⟩ }

def rx : ComponentTarget := .site { molecule := rA, site := ⟨0⟩ }
def ry : ComponentTarget := .site { molecule := rB, site := ⟨0⟩ }

def forward : RuleDirection :=
  { reactants := [reactantA, reactantB]
    products := [productComplex]
    rate := { expression := .parameter kId }
    mutations := [
      .changeState rx sP,
      .createBond rx ry]
    moleculeMap := [
      { reactant := rA, product := pA },
      { reactant := rB, product := pB }] }

def rule : CompiledRule :=
  { id := ⟨0⟩, name := "bind_and_phosphorylate", forward := forward }

def model : CompiledModel :=
  { metadata := { name := "Lean semantic example" }
    parameters := [
      { id := kId, name := "k", expression := .number 1.0, constantValue := some 1.0 }]
    moleculeTypes := [moleculeA, moleculeB]
    rules := [rule] }

/- This should evaluate to `true`. -/
#eval model.wellFormed

/- This should evaluate to `2`. -/
#eval productComplex.lower.nodes.length

/-- Deliberately invalid: state ID 99 was never declared for A.x. -/
def badPattern : Pattern :=
  { molecules := [
      { occurrence := ⟨0⟩
        moleculeType := mtA
        sites := [
          { occurrence := ⟨0⟩
            component := cAx
            state := .exact ⟨99⟩ }] }] }

/- This should evaluate to `false`. -/
#eval badPattern.wellFormed model.signature

/--
Concrete NFnext lowering contract mirrored by the production C++ boundary test
in `tests/architecture_contracts/nfnext/test_nfnext.cpp`.  Both start from the
same biological rule shown at the top of this file.  The C++ side crosses
BNGL parser → `bng::compile::CompiledModel` → `nfnext::lowerFromBioNetGen`;
this side checks the proof-friendly typed lowering independently.
-/
def nfnextBridgeContract : Bool :=
  let packing := NFnextPacking.fromSignature model.signature
  match forward.lowerNFnextTransformation? packing with
  | none => false
  | some (flat, transform) =>
      flat.pattern.nodes.length == 2 &&
      match flat.pattern.molecularity, transform.ops with
      | [.differentComplex 0 1],
        [.setState 0 site state, .addBond 0 leftSite 1 rightSite] =>
          site.value == 0 && state.value == 1 &&
          leftSite.value == 0 && rightSite.value == 0
      | _, _ => false

/-- The typed reference lowers the bridge fixture to the expected NFnext shape. -/
theorem nfnextBridgeContract_holds : nfnextBridgeContract = true := by
  native_decide

end BNG.Examples

namespace BNG.Examples

open BNG

/-! ## Operational example: actually match and execute the compiled rule -/

/-- Concrete A molecule: A#0(x~u). -/
def runtimeA : RuntimeMolecule :=
  { id := ⟨0⟩
    moleculeType := mtA
    sites := [{ component := cAx, state := some sU }] }

/-- Concrete B molecule: B#1(y). -/
def runtimeB : RuntimeMolecule :=
  { id := ⟨1⟩
    moleculeType := mtB
    sites := [{ component := cBy }] }

/-- The starting mixture has exactly the two unbound reactants. -/
def runtimeMixture : Mixture :=
  { nextMoleculeId := ⟨2⟩
    molecules := [runtimeA, runtimeB] }

/- The concrete starting graph is structurally valid. -/
#eval runtimeMixture.wellFormed model.signature

/- A(x~u) finds one embedding: the concrete A#0 molecule. -/
#eval reactantA.matches runtimeMixture

/- B(y) likewise finds B#1. -/
#eval reactantB.matches runtimeMixture

/- The whole rule has one non-overlapping reactant match. -/
#eval forward.matches runtimeMixture

/-- Convenience: select the unique match in this tiny fixture. -/
def firstForwardMatch? : Option RuleMatch :=
  listGet? (forward.matches runtimeMixture) 0

/-- Execute the semantic rule at the selected match. -/
def semanticResult? : Option Mixture :=
  match firstForwardMatch? with
  | none => none
  | some matched => forward.applyAt? runtimeMixture matched

/-- Execute the independently-lowered backend action program at the same match. -/
def loweredResult? : Option Mixture :=
  match firstForwardMatch? with
  | none => none
  | some matched => forward.executeLoweredAt? runtimeMixture matched

/--
The resulting A.x state should be `p`.  This helper avoids requiring a giant
`DecidableEq` instance for the whole mixture just to inspect one biological
fact.
-/
def resultAIsPhosphorylated : Bool :=
  match semanticResult? with
  | none => false
  | some mix =>
      match mix.findMolecule? ⟨0⟩ with
      | none => false
      | some molecule =>
          match molecule.findSite? cAx with
          | none => false
          | some site => site.state == some sP

/-- The resulting A.x and B.y sites should be explicitly bonded. -/
def resultHasABBond : Bool :=
  match semanticResult? with
  | none => false
  | some mix =>
      mix.hasBond
        { molecule := ⟨0⟩, component := cAx }
        { molecule := ⟨1⟩, component := cBy }

#eval resultAIsPhosphorylated
#eval resultHasABBond

/--
The general refinement theorem is proved in `BNG.Lowering`; this concrete
example demonstrates the intended result shape for a human reader.
-/
theorem example_lowered_step_equals_semantic_step (matched : RuleMatch) :
    forward.executeLoweredAt? runtimeMixture matched =
      forward.applyAt? runtimeMixture matched := by
  exact execute_lowered_rule_eq_reference forward runtimeMixture matched

end BNG.Examples
