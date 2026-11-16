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


theorem addProductsModuloIso_nil (pool : List Mixture) :
    addProductsModuloIso pool [] = pool := by
  simp [addProductsModuloIso]

theorem boundedNetworkClosure_zero (rules : List RuleDirection) (pool : List Mixture) :
    boundedNetworkClosure 0 rules pool = pool := by
  rfl

theorem networkGenerationStep_nil (pool : List Mixture) :
    networkGenerationStep [] pool = pool := by
  simp [networkGenerationStep]


theorem addProductsModuloIso_cons (p : Mixture) (ps pool : List Mixture) :
    addProductsModuloIso pool (p :: ps) =
      addProductsModuloIso (addSpeciesModuloIso pool p) ps := by
  simp [addProductsModuloIso, List.foldl]

/-- Exact bounded identity accumulation over a product list: every previously
known species representative remains in the pool. -/
theorem addProductsModuloIso_preserves_existing (products pool : List Mixture)
    (existing : Mixture) (hmem : existing ∈ pool) :
    existing ∈ addProductsModuloIso pool products := by
  induction products generalizing pool with
  | nil =>
      simpa [addProductsModuloIso_nil] using hmem
  | cons p ps ih =>
      rw [addProductsModuloIso_cons]
      have hstep : existing ∈ addSpeciesModuloIso pool p := by
        unfold addSpeciesModuloIso
        by_cases h : pool.any (fun e => e.isomorphicSpecies p) = true
        · simp [h, hmem]
        · simp [h, hmem]
      exact ih (addSpeciesModuloIso pool p) hstep

/-- Bounded accumulation bound: adding products modulo isomorphism cannot remove
representatives and adds at most one representative per product candidate. -/
theorem addProductsModuloIso_length_ge (products pool : List Mixture) :
    pool.length ≤ (addProductsModuloIso pool products).length := by
  induction products generalizing pool with
  | nil => simp [addProductsModuloIso_nil]
  | cons p ps ih =>
      rw [addProductsModuloIso_cons]
      exact Nat.le_trans (addSpeciesModuloIso_length_ge pool p) (ih _)

theorem addProductsModuloIso_length_le (products pool : List Mixture) :
    (addProductsModuloIso pool products).length ≤ pool.length + products.length := by
  induction products generalizing pool with
  | nil => simp [addProductsModuloIso_nil]
  | cons p ps ih =>
      rw [addProductsModuloIso_cons]
      have h1 := ih (addSpeciesModuloIso pool p)
      have h2 := addSpeciesModuloIso_length_le_succ pool p
      calc
        (addProductsModuloIso (addSpeciesModuloIso pool p) ps).length
            ≤ (addSpeciesModuloIso pool p).length + ps.length := h1
        _ ≤ (pool.length + 1) + ps.length := by
              exact Nat.add_le_add_right h2 _
        _ = pool.length + (p :: ps).length := by simp [Nat.add_left_comm, Nat.add_comm]

/-- A bounded network step never drops an existing species representative
(identity accumulation / monotone closure for the named supported class). -/
theorem networkGenerationStep_preserves_existing (rules : List RuleDirection)
    (pool : List Mixture) (existing : Mixture) (hmem : existing ∈ pool) :
    existing ∈ networkGenerationStep rules pool := by
  unfold networkGenerationStep
  induction rules generalizing pool with
  | nil =>
      simpa using hmem
  | cons r rs ih =>
      simp [List.foldl]
      exact ih (addProductsModuloIso pool (RuleDirection.networkProducts r pool))
        (addProductsModuloIso_preserves_existing _ _ _ hmem)

theorem networkGenerationStep_length_ge (rules : List RuleDirection) (pool : List Mixture) :
    pool.length ≤ (networkGenerationStep rules pool).length := by
  unfold networkGenerationStep
  suffices h : ∀ (rs : List RuleDirection) (p : List Mixture),
      p.length ≤ (rs.foldl (fun current rule =>
        addProductsModuloIso current (rule.networkProducts current)) p).length from
    h rules pool
  intro rs p
  induction rs generalizing p with
  | nil => simp
  | cons r rs ih =>
      simp [List.foldl]
      exact Nat.le_trans
        (addProductsModuloIso_length_ge (RuleDirection.networkProducts r p) p)
        (ih _)

/-- Exact bounded closure identity accumulation: no known species representative
is dropped across closure iterations (named supported class / reference oracle). -/
theorem boundedNetworkClosure_preserves_existing (fuel : Nat)
    (rules : List RuleDirection) (pool : List Mixture) (existing : Mixture)
    (hmem : existing ∈ pool) :
    existing ∈ boundedNetworkClosure fuel rules pool := by
  induction fuel generalizing pool with
  | zero =>
      simpa [boundedNetworkClosure] using hmem
  | succ n ih =>
      unfold boundedNetworkClosure
      by_cases hfix : (networkGenerationStep rules pool).length == pool.length
      · simp [hfix]
        exact networkGenerationStep_preserves_existing rules pool existing hmem
      · simp [hfix]
        exact ih (networkGenerationStep rules pool)
          (networkGenerationStep_preserves_existing rules pool existing hmem)

/-- Bounded closure never shrinks the species-pool representative count
(monotone accumulation for the named supported class/reference oracle). -/
theorem boundedNetworkClosure_length_ge (fuel : Nat)
    (rules : List RuleDirection) (pool : List Mixture) :
    pool.length ≤ (boundedNetworkClosure fuel rules pool).length := by
  induction fuel generalizing pool with
  | zero => simp [boundedNetworkClosure]
  | succ n ih =>
      unfold boundedNetworkClosure
      by_cases hfix : (networkGenerationStep rules pool).length == pool.length
      · simp [hfix]
        exact networkGenerationStep_length_ge rules pool
      · simp [hfix]
        exact Nat.le_trans (networkGenerationStep_length_ge rules pool) (ih _)

end BNG
