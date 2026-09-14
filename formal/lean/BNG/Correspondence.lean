import BNG.Rule

namespace BNG

/-!
# Cross-arrow correspondence inference

A BNGL rule writes two graphs around an arrow.  The compiler must decide which
molecule occurrences survive the arrow and which product components correspond
to reactant components.  That decision must happen **once** in the compiler.
NFsim, NFnext, network generation, writers, and analysis tools should consume
the resolved result rather than rediscovering it.

This module captures the deterministic compatibility policy used by current
BNG3 for the supported subset:

1. surviving molecules are paired left-to-right by molecule type and by the
   multiset of explicitly mentioned component types;
2. components with `%tag` labels are paired by matching label;
3. remaining components are paired left-to-right by component type;
4. unmatched reactant molecules are deletions;
5. unmatched product molecules are creations.

The policy is intentionally explicit.  If BNG3 later adopts a different rule,
this is one semantic function to change and revalidate.
-/

structure IndexedPatternMolecule where
  endpoint : RuleMoleculeEndpoint
  molecule : PatternMolecule
  deriving Repr

/-- Add rule-level addresses to every molecule in a list of top-level patterns. -/
def indexPatternMolecules (side : PatternSide) :
    Nat → List Pattern → List IndexedPatternMolecule
  | _, [] => []
  | patternIndex, p :: rest =>
      let here := p.molecules.map (fun molecule =>
        { endpoint := {
            side := side
            pattern := patternIndex
            molecule := molecule.occurrence }
          molecule := molecule })
      here ++ indexPatternMolecules side (patternIndex + 1) rest

/-- Count occurrences of one component type in a component list. -/
def componentCount (wanted : ComponentTypeId) : List ComponentTypeId → Nat
  | [] => 0
  | x :: xs => (if x == wanted then 1 else 0) + componentCount wanted xs

/-- Multiset equality specialized to resolved component IDs. -/
def componentMultisetEq (xs ys : List ComponentTypeId) : Bool :=
  xs.length == ys.length &&
    xs.all (fun x => componentCount x xs == componentCount x ys) &&
    ys.all (fun y => componentCount y xs == componentCount y ys)

/-- The compatibility key used to pair molecules across an arrow. -/
def moleculeCorrespondenceKeyEq (a b : PatternMolecule) : Bool :=
  a.moleculeType == b.moleculeType &&
    componentMultisetEq (a.sites.map (fun s => s.component))
      (b.sites.map (fun s => s.component))

/-- Remove and return the first product molecule compatible with `wanted`. -/
def takeCompatibleMolecule? (wanted : PatternMolecule) :
    List IndexedPatternMolecule → Option (IndexedPatternMolecule × List IndexedPatternMolecule)
  | [] => none
  | x :: xs =>
      if moleculeCorrespondenceKeyEq wanted x.molecule then
        some (x, xs)
      else
        match takeCompatibleMolecule? wanted xs with
        | none => none
        | some (found, rest) => some (found, x :: rest)

/--
Greedy left-to-right molecule correspondence.

The second result contains product molecules that were not consumed and are
therefore creations.
-/
def inferMoleculeMapAux :
    List IndexedPatternMolecule → List IndexedPatternMolecule →
      List MoleculeCorrespondence × List IndexedPatternMolecule
  | [], products => ([], products)
  | reactant :: rest, products =>
      match takeCompatibleMolecule? reactant.molecule products with
      | none => inferMoleculeMapAux rest products
      | some (product, remainingProducts) =>
          let tail := inferMoleculeMapAux rest remainingProducts
          ({ reactant := reactant.endpoint, product := product.endpoint } :: tail.1, tail.2)

/-- Infer surviving molecule pairs for a compiled direction. -/
def RuleDirection.inferMoleculeMap (d : RuleDirection) : List MoleculeCorrespondence :=
  let reactants := indexPatternMolecules .reactant 0 d.reactants
  let products := indexPatternMolecules .product 0 d.products
  (inferMoleculeMapAux reactants products).1

/-- Find the indexed molecule carrying one rule-level endpoint. -/
def indexedMoleculeAt? (items : List IndexedPatternMolecule)
    (endpoint : RuleMoleculeEndpoint) : Option IndexedPatternMolecule :=
  items.find? (fun x => x.endpoint == endpoint)

structure IndexedPatternSite where
  target : ComponentTarget
  site : PatternSite
  deriving Repr

/-- Attach a semantic component target to each explicitly mentioned site. -/
def indexedSites (molecule : RuleMoleculeEndpoint) (m : PatternMolecule) : List IndexedPatternSite :=
  m.sites.map (fun site =>
    { target := .site { molecule := molecule, site := site.occurrence }, site := site })

/--
A tagged component only matches the same tag.  An untagged component matches by
component identity.  This keeps tags semantically meaningful instead of merely
preserving them as source text.
-/
def componentCandidateEq (a b : PatternSite) : Bool :=
  match a.label, b.label with
  | some x, some y => x == y
  | some _, none => false
  | none, some _ => false
  | none, none => a.component == b.component

/-- Remove and return the first compatible product component. -/
def takeCompatibleSite? (wanted : PatternSite) :
    List IndexedPatternSite → Option (IndexedPatternSite × List IndexedPatternSite)
  | [] => none
  | x :: xs =>
      if componentCandidateEq wanted x.site then some (x, xs)
      else
        match takeCompatibleSite? wanted xs with
        | none => none
        | some (found, rest) => some (found, x :: rest)

/-- Pair components inside one already-paired molecule. -/
def inferComponentPairsAux :
    List IndexedPatternSite → List IndexedPatternSite → List ComponentCorrespondence
  | [], _ => []
  | reactant :: rest, products =>
      match takeCompatibleSite? reactant.site products with
      | none => inferComponentPairsAux rest products
      | some (product, remainingProducts) =>
          { reactant := reactant.target, product := product.target } ::
            inferComponentPairsAux rest remainingProducts

/-- Infer all explicit component correspondences from a molecule map. -/
def RuleDirection.inferComponentMapFrom (d : RuleDirection)
    (moleculeMap : List MoleculeCorrespondence) : List ComponentCorrespondence :=
  let reactantItems := indexPatternMolecules .reactant 0 d.reactants
  let productItems := indexPatternMolecules .product 0 d.products
  moleculeMap.flatMap (fun pair =>
    match indexedMoleculeAt? reactantItems pair.reactant,
      indexedMoleculeAt? productItems pair.product with
    | some r, some p =>
        inferComponentPairsAux (indexedSites pair.reactant r.molecule)
          (indexedSites pair.product p.molecule)
    | _, _ => [])

/-- Infer both correspondence tables together. -/
def RuleDirection.inferCorrespondence (d : RuleDirection) :
    List MoleculeCorrespondence × List ComponentCorrespondence :=
  let molecules := d.inferMoleculeMap
  (molecules, d.inferComponentMapFrom molecules)

/-- Is one rule-level molecule endpoint already paired in this map? -/
def moleculeMappedOnSide (side : PatternSide) (endpoint : RuleMoleculeEndpoint)
    (mapping : List MoleculeCorrespondence) : Bool :=
  mapping.any (fun pair =>
    match side with
    | .reactant => pair.reactant == endpoint
    | .product => pair.product == endpoint)

/-- Product molecule endpoints not represented by a correspondence are creations. -/
def RuleDirection.inferredCreatedMolecules (d : RuleDirection)
    (mapping : List MoleculeCorrespondence) : List RuleMoleculeEndpoint :=
  indexPatternMolecules .product 0 d.products
    |>.map (fun x => x.endpoint)
    |>.filter (fun endpoint => !(moleculeMappedOnSide .product endpoint mapping))

/-- Reactant molecule endpoints not represented by a correspondence are deletions. -/
def RuleDirection.inferredDeletedMolecules (d : RuleDirection)
    (mapping : List MoleculeCorrespondence) : List RuleMoleculeEndpoint :=
  indexPatternMolecules .reactant 0 d.reactants
    |>.map (fun x => x.endpoint)
    |>.filter (fun endpoint => !(moleculeMappedOnSide .reactant endpoint mapping))

end BNG
