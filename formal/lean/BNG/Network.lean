import BNG.Species
import BNG.Model
import BNG.ExtendedOperational

namespace BNG

/-!
# Bounded reference network generation

A generated reaction network is a closure over a **pool of species**, not a
trajectory from one seed.  For a bimolecular rule `A + B -> A.B`, the generator
must combine A and B from separate pool entries before matching the rule.

This implementation is deliberately exponential and suitable only as a small
correctness oracle.
-/

/-- Shift every runtime molecule ID in a mixture by a constant offset. -/
def shiftMoleculeId (offset : Nat) (id : MoleculeInstanceId) : MoleculeInstanceId :=
  ⟨id.value + offset⟩

def shiftEndpoint (offset : Nat) (e : ConcreteEndpoint) : ConcreteEndpoint :=
  { e with molecule := shiftMoleculeId offset e.molecule }

/-- Clone one species into a disjoint runtime-ID range. -/
def Mixture.shiftIds (mix : Mixture) (offset : Nat) : Mixture :=
  { nextMoleculeId := ⟨mix.nextMoleculeId.value + offset⟩
    molecules := mix.molecules.map (fun m =>
      { m with id := shiftMoleculeId offset m.id })
    bonds := mix.bonds.map (fun edge =>
      { a := shiftEndpoint offset edge.a, b := shiftEndpoint offset edge.b }) }

/-- Disjoint union of two mixtures whose runtime-ID ranges are already separate. -/
def Mixture.disjointAppend (left right : Mixture) : Mixture :=
  { nextMoleculeId := ⟨Nat.max left.nextMoleculeId.value right.nextMoleculeId.value⟩
    molecules := left.molecules ++ right.molecules
    bonds := left.bonds ++ right.bonds }

/-- Clone selected species into one disjoint reactant mixture. -/
def disjointReactantMixture : List Mixture → Mixture
  | [] => { nextMoleculeId := ⟨0⟩, molecules := [], bonds := [] }
  | species :: rest =>
      let tail := disjointReactantMixture rest
      let shifted := species.shiftIds tail.nextMoleculeId.value
      tail.disjointAppend shifted

/-- All ordered selections of length `n`, allowing repeated species types/copies. -/
def chooseSpeciesTuples : Nat → List Mixture → List (List Mixture)
  | 0, _ => [[]]
  | n + 1, pool =>
      pool.flatMap (fun species =>
        (chooseSpeciesTuples n pool).map (fun tail => species :: tail))

/-- Split a mixture into complete connected complexes. -/
def Mixture.complexes (mix : Mixture) : List Mixture :=
  let rec go : Nat → Mixture → List Mixture
    | 0, _ => []
    | fuel + 1, current =>
        match current.molecules with
        | [] => []
        | first :: _ =>
            let ids := current.connectedFrom first.id
            let complex := current.restrictToMolecules ids
            let remainder : Mixture := {
              current with
              molecules := current.molecules.filter (fun m => !(ids.contains m.id))
              bonds := current.bonds.filter (fun edge =>
                !(ids.contains edge.a.molecule) && !(ids.contains edge.b.molecule)) }
            complex :: go fuel remainder
  go mix.molecules.length mix

/-- Add many product complexes modulo graph isomorphism. -/
def addProductsModuloIso (pool : List Mixture) (products : List Mixture) : List Mixture :=
  products.foldl addSpeciesModuloIso pool

/-- Product species reachable by one rule from the current species pool. -/
def RuleDirection.networkProducts (d : RuleDirection) (pool : List Mixture) : List Mixture :=
  let arity := d.reactants.length
  chooseSpeciesTuples arity pool |>.flatMap (fun selected =>
    let reactantMix := disjointReactantMixture selected
    d.extendedSuccessors reactantMix |>.flatMap Mixture.complexes)

/-- One closure iteration over all compiled rules/directions. -/
def networkGenerationStep (rules : List RuleDirection) (pool : List Mixture) : List Mixture :=
  rules.foldl (fun current rule =>
    addProductsModuloIso current (rule.networkProducts current)) pool

/-- Bounded species-pool closure. -/
def boundedNetworkClosure : Nat → List RuleDirection → List Mixture → List Mixture
  | 0, _, pool => pool
  | n + 1, rules, pool =>
      let next := networkGenerationStep rules pool
      if next.length == pool.length then next
      else boundedNetworkClosure n rules next

/-- Expand forward and reverse compiled directions uniformly. -/
def CompiledRule.directions (rule : CompiledRule) : List RuleDirection :=
  match rule.reverse with
  | none => [rule.forward]
  | some reverse => [rule.forward, reverse]

/-- Bounded reference network generation for a compiled model. -/
def CompiledModel.referenceNetwork (model : CompiledModel) (iterations : Nat)
    (seedSpecies : List Mixture) : List Mixture :=
  let directions := model.rules.flatMap CompiledRule.directions
  boundedNetworkClosure iterations directions seedSpecies

end BNG
