import BNG.Correspondence

namespace BNG

/-!
# Deriving a mutation program from resolved correspondence

Once molecule/component correspondence is known, the compiler can convert a
rule arrow into explicit graph edits.  This is the crucial compiler boundary:
backends receive `Mutation`s and never compare reactant text to product text.

This module covers the structural core:

* molecule creation/deletion;
* state changes on mapped or product-only components;
* explicit exact-bond creation/deletion;
* bond clearing requested by product-side `free` on a component omitted from
  the reactant side;
* direct compartment movement of mapped molecules.

`DeleteMolecules` and `MoveConnected` remain rule modifiers because they alter
how deletion/transport expands over connected complexes.
-/

/-- Read an exact target state if the product specifies one unambiguously. -/
def StateConstraint.exactState? : StateConstraint → Option StateId
  | .exact s => some s
  | .oneOf [s] => some s
  | _ => none

/-- Retrieve the pattern site addressed by a site-valued component target. -/
def RuleDirection.siteAtTarget? (d : RuleDirection) : ComponentTarget → Option PatternSite
  | .byType _ _ => none
  | .site endpoint =>
      match d.moleculeAt? endpoint.molecule with
      | none => none
      | some molecule => molecule.findSite? endpoint.site

/-- Find the reactant component corresponding to a product component. -/
def reactantTargetForProduct? (mapping : List ComponentCorrespondence)
    (product : ComponentTarget) : Option ComponentTarget :=
  match mapping.find? (fun pair => pair.product == product) with
  | none => none
  | some pair => some pair.reactant

/-- Compare an unordered semantic bond pair. -/
def sameTargetBond (a1 b1 a2 b2 : ComponentTarget) : Bool :=
  ((a1 == a2) && (b1 == b2)) || ((a1 == b2) && (b1 == a2))

structure TargetBond where
  a : ComponentTarget
  b : ComponentTarget
  deriving Repr

/-- Undirected target-bond equality. -/
def TargetBond.same (x y : TargetBond) : Bool :=
  sameTargetBond x.a x.b y.a y.b

/-- Turn exact bonds in one top-level pattern into rule-level targets. -/
def indexedPatternBonds (side : PatternSide) (patternIndex : Nat) (p : Pattern) : List TargetBond :=
  p.bonds.map (fun bond =>
    { a := .site {
        molecule := { side := side, pattern := patternIndex, molecule := bond.a.molecule }
        site := bond.a.site }
      b := .site {
        molecule := { side := side, pattern := patternIndex, molecule := bond.b.molecule }
        site := bond.b.site } })

/-- Collect exact bonds from all top-level patterns. -/
def indexedRuleBonds (side : PatternSide) : Nat → List Pattern → List TargetBond
  | _, [] => []
  | index, p :: rest => indexedPatternBonds side index p ++ indexedRuleBonds side (index + 1) rest

/-- Translate a product component back to its reactant identity when it survived. -/
def normalizeProductTarget (mapping : List ComponentCorrespondence)
    (target : ComponentTarget) : ComponentTarget :=
  match reactantTargetForProduct? mapping target with
  | some reactant => reactant
  | none => target

/-- Normalize product-side bonds into the identity space used for mutation comparison. -/
def normalizeProductBond (mapping : List ComponentCorrespondence) (bond : TargetBond) : TargetBond :=
  { a := normalizeProductTarget mapping bond.a
    b := normalizeProductTarget mapping bond.b }

/-- Does a semantically identical undirected bond occur in a list? -/
def targetBondMember (wanted : TargetBond) (xs : List TargetBond) : Bool :=
  xs.any (fun x => x.same wanted)

/-- A simpler syntactic equality test for before/after exact state constraints. -/
def sameExactStateConstraint (a b : StateConstraint) : Bool :=
  match a.exactState?, b.exactState? with
  | none, none => true
  | some x, some y => x == y
  | _, _ => false

/--
State mutations implied by mapped components, using only exact product states.

This version is intentionally independent of runtime `stateMatches`: it compares
resolved rule constraints rather than pretending a pattern constraint is a
runtime state.
-/
def RuleDirection.inferStateMutations (d : RuleDirection)
    (componentMap : List ComponentCorrespondence) : List Mutation :=
  componentMap.filterMap (fun pair =>
    match d.siteAtTarget? pair.reactant, d.siteAtTarget? pair.product with
    | some before, some after =>
        match after.state.exactState? with
        | none => none
        | some wanted =>
            if sameExactStateConstraint before.state after.state then none
            else some (.changeState pair.reactant wanted)
    | _, _ => none)

/-- Product sites not consumed by explicit component correspondence. -/
def unmatchedProductSites (product : IndexedPatternMolecule)
    (componentMap : List ComponentCorrespondence) : List PatternSite :=
  product.molecule.sites.filter (fun site =>
    let target : ComponentTarget := .site {
      molecule := product.endpoint, site := site.occurrence }
    !(componentMap.any (fun pair => pair.product == target)))

/-- Is the product explicitly asking for a free component? -/
def asksForFreeBond (site : PatternSite) : Bool :=
  site.bonds.any (fun req =>
    match req with
    | .free => true
    | _ => false)

/--
Edits for components that only appear on the product side.

Because there is no reactant `PatternSiteId`, these use `.byType` targets.
-/
def RuleDirection.inferProductOnlySiteMutations (d : RuleDirection)
    (moleculeMap : List MoleculeCorrespondence)
    (componentMap : List ComponentCorrespondence) : List Mutation :=
  let productItems := indexPatternMolecules .product 0 d.products
  moleculeMap.flatMap (fun pair =>
    match indexedMoleculeAt? productItems pair.product with
    | none => []
    | some product =>
        unmatchedProductSites product componentMap |>.flatMap (fun site =>
          let target : ComponentTarget := .byType pair.reactant site.component
          let stateEdit :=
            match site.state.exactState? with
            | none => []
            | some state => [.changeState target state]
          let bondEdit := if asksForFreeBond site then [.clearBonds target] else []
          stateEdit ++ bondEdit))

/-- Direct compartment changes for surviving molecules. -/
def RuleDirection.inferCompartmentMutations (d : RuleDirection)
    (moleculeMap : List MoleculeCorrespondence) : List Mutation :=
  moleculeMap.filterMap (fun pair =>
    match d.moleculeAt? pair.reactant, d.moleculeAt? pair.product with
    | some before, some after =>
        match after.compartment with
        | none => none
        | some destination =>
            if before.compartment == some destination then none
            else some (.moveCompartment pair.reactant destination)
    | _, _ => none)

/-- Exact-bond additions/removals after cross-arrow identity normalization. -/
def RuleDirection.inferBondMutations (d : RuleDirection)
    (componentMap : List ComponentCorrespondence) : List Mutation :=
  let before := indexedRuleBonds .reactant 0 d.reactants
  let after := indexedRuleBonds .product 0 d.products |>.map (normalizeProductBond componentMap)
  let deletions := before.filterMap (fun bond =>
    if targetBondMember bond after then none else some (.deleteBond bond.a bond.b))
  let creations := after.filterMap (fun bond =>
    if targetBondMember bond before then none else some (.createBond bond.a bond.b))
  deletions ++ creations

/--
Compile the structural mutation program and correspondence tables together.

The ordering is deliberate: create molecules before operations that may target
new product molecules, apply local edits, then delete disappearing molecules.
-/
def RuleDirection.compileStructuralSemantics (d : RuleDirection) : RuleDirection :=
  let correspondence := d.inferCorrespondence
  let moleculeMap := correspondence.1
  let componentMap := correspondence.2
  let creations := d.inferredCreatedMolecules moleculeMap |>.map Mutation.createMolecule
  let deletions := d.inferredDeletedMolecules moleculeMap |>.map Mutation.deleteMolecule
  let states := d.inferStateMutations componentMap
  let productOnly := d.inferProductOnlySiteMutations moleculeMap componentMap
  let bonds := d.inferBondMutations componentMap
  let moves := d.inferCompartmentMutations moleculeMap
  { d with
    moleculeMap := moleculeMap
    componentMap := componentMap
    mutations := creations ++ states ++ productOnly ++ bonds ++ moves ++ deletions }

/-- Structural compilation is deterministic by construction. -/
theorem compileStructuralSemantics_deterministic (d : RuleDirection) :
    d.compileStructuralSemantics = d.compileStructuralSemantics := by
  rfl

end BNG
