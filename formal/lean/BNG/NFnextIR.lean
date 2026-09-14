import BNG.MutationCompiler
import BNG.Capabilities
import BNG.Operational

namespace BNG

/-!
# Proof-friendly mirror of NFnext's generic IR boundary

Current NFnext C++ uses compact, type-local integers:

* molecule type = position/id in NFnext's molecule-type table;
* site = index inside that molecule type's site vector;
* state = index/value inside that site's state table.

Those numbers are **not** automatically equal to BNG3 semantic IDs.  This file
therefore inserts an explicit checked packing layer before the proof-friendly
NFnext representation.
-/

structure PackedType where value : Nat
  deriving Repr, DecidableEq, BEq
structure PackedSite where value : Nat
  deriving Repr, DecidableEq, BEq
structure PackedState where value : Nat
  deriving Repr, DecidableEq, BEq

structure PackedComponentKey where
  moleculeType : MoleculeTypeId
  component : ComponentTypeId
  deriving Repr, DecidableEq, BEq

structure PackedStateKey where
  moleculeType : MoleculeTypeId
  component : ComponentTypeId
  state : StateId
  deriving Repr, DecidableEq, BEq

structure NFnextPacking where
  types : List (MoleculeTypeId × PackedType) := []
  sites : List (PackedComponentKey × PackedSite) := []
  states : List (PackedStateKey × PackedState) := []
  deriving Repr

/-- Generic first-match association lookup. -/
def lookupAssoc? {α β : Type} [BEq α] (wanted : α) : List (α × β) → Option β
  | [] => none
  | x :: xs => if x.1 == wanted then some x.2 else lookupAssoc? wanted xs

def NFnextPacking.type? (p : NFnextPacking) (id : MoleculeTypeId) : Option PackedType :=
  lookupAssoc? id p.types

def NFnextPacking.site? (p : NFnextPacking) (mt : MoleculeTypeId)
    (id : ComponentTypeId) : Option PackedSite :=
  lookupAssoc? ({ moleculeType := mt, component := id } : PackedComponentKey) p.sites

def NFnextPacking.state? (p : NFnextPacking) (mt : MoleculeTypeId)
    (component : ComponentTypeId) (state : StateId) : Option PackedState :=
  lookupAssoc? ({ moleculeType := mt, component := component, state := state } : PackedStateKey) p.states

/-- Enumerate a declaration list with a compact zero-based index. -/
def enumerateWithNat {α : Type} : Nat → List α → List (α × Nat)
  | _, [] => []
  | n, x :: xs => (x, n) :: enumerateWithNat (n + 1) xs

/-- Build the exact local-index mapping implied by declaration order. -/
def NFnextPacking.fromSignature (sig : Signature) : NFnextPacking :=
  let types := enumerateWithNat 0 sig.moleculeTypes |>.map (fun pair => (pair.1.id, ⟨pair.2⟩))
  let sites := sig.moleculeTypes.flatMap (fun mt =>
    enumerateWithNat 0 mt.components |>.map (fun pair =>
      ({ moleculeType := mt.id, component := pair.1.id }, ⟨pair.2⟩)))
  let states := sig.moleculeTypes.flatMap (fun mt =>
    mt.components.flatMap (fun component =>
      enumerateWithNat 0 component.states |>.map (fun pair =>
        ({ moleculeType := mt.id, component := component.id, state := pair.1.id }, ⟨pair.2⟩))))
  { types := types, sites := sites, states := states }

inductive NFnextSiteConstraint where
  | state (site : PackedSite) (value : PackedState)
  | stateSet (site : PackedSite) (values : List PackedState)
  | free (site : PackedSite)
  | bound (site : PackedSite)
  deriving Repr

structure NFnextNode where
  moleculeType : PackedType
  constraints : List NFnextSiteConstraint := []
  deriving Repr

structure NFnextBond where
  firstNode : Nat
  firstSite : PackedSite
  secondNode : Nat
  secondSite : PackedSite
  deriving Repr

inductive NFnextMolecularity where
  | sameComplex (left right : Nat)
  | differentComplex (left right : Nat)
  deriving Repr

structure NFnextPattern where
  nodes : List NFnextNode := []
  bonds : List NFnextBond := []
  molecularity : List NFnextMolecularity := []
  deriving Repr

/-- Rule endpoint corresponding to each flattened NFnext node index. -/
structure FlattenedReactants where
  pattern : NFnextPattern
  nodeTable : List RuleMoleculeEndpoint
  deriving Repr

/-- Find a node index assigned to one semantic rule molecule endpoint. -/
def FlattenedReactants.nodeIndex? (flat : FlattenedReactants)
    (endpoint : RuleMoleculeEndpoint) : Option Nat :=
  let rec go : Nat → List RuleMoleculeEndpoint → Option Nat
    | _, [] => none
    | n, x :: xs => if x == endpoint then some n else go (n + 1) xs
  go 0 flat.nodeTable

/-- Resolve one semantic pattern site into compact NFnext constraints. -/
def lowerNFnextSiteConstraints? (packing : NFnextPacking) (mt : MoleculeTypeId)
    (site : PatternSite) : Option (List NFnextSiteConstraint) :=
  match packing.site? mt site.component with
  | none => none
  | some packedSite =>
      let stateConstraints? : Option (List NFnextSiteConstraint) :=
        match site.state with
        | .any => some []
        | .exact state =>
            (packing.state? mt site.component state).map (fun packed => [.state packedSite packed])
        | .oneOf states =>
            let rec packStates : List StateId → Option (List PackedState)
              | [] => some []
              | s :: rest =>
                  match packing.state? mt site.component s, packStates rest with
                  | some packed, some tail => some (packed :: tail)
                  | _, _ => none
            (packStates states).map (fun values => [.stateSet packedSite values])
      let bondConstraints := site.bonds.flatMap (fun req =>
        match req with
        | .free => [.free packedSite]
        | .bound => [.bound packedSite]
        | .any => []
        | .exact _ => [])
      stateConstraints?.map (fun states => states ++ bondConstraints)

/-- Resolve one semantic molecule to one NFnext node. -/
def lowerNFnextNode? (packing : NFnextPacking) (m : PatternMolecule) : Option NFnextNode :=
  match packing.type? m.moleculeType with
  | none => none
  | some packedType =>
      let rec lowerSites : List PatternSite → Option (List NFnextSiteConstraint)
        | [] => some []
        | site :: rest =>
            match lowerNFnextSiteConstraints? packing m.moleculeType site, lowerSites rest with
            | some here, some tail => some (here ++ tail)
            | _, _ => none
      (lowerSites m.sites).map (fun constraints =>
        { moleculeType := packedType, constraints := constraints })

/-- Add pairwise SameComplex constraints among node indices in one top-level pattern. -/
def pairwiseSameComplex : List Nat → List NFnextMolecularity
  | [] => []
  | x :: xs => xs.map (fun y => .sameComplex x y) ++ pairwiseSameComplex xs

/-- Add pairwise DifferentComplex constraints across two top-level reactants. -/
def crossDifferentComplex (xs ys : List Nat) : List NFnextMolecularity :=
  xs.flatMap (fun x => ys.map (fun y => .differentComplex x y))

/--
Flatten all reactants into the one node table expected by generic NFnext.
The function fails rather than dropping an un-packable semantic ID.
-/
def RuleDirection.flattenReactantsNFnext? (d : RuleDirection)
    (packing : NFnextPacking) : Option FlattenedReactants :=
  let rec lowerPatterns : Nat → Nat → List Pattern →
      Option (List NFnextNode × List RuleMoleculeEndpoint × List (List Nat))
    | _, _, [] => some ([], [], [])
    | patternIndex, nodeBase, p :: rest =>
        let rec lowerMolecules : List PatternMolecule → Option (List NFnextNode)
          | [] => some []
          | m :: ms =>
              match lowerNFnextNode? packing m, lowerMolecules ms with
              | some head, some tail => some (head :: tail)
              | _, _ => none
        match lowerMolecules p.molecules,
          lowerPatterns (patternIndex + 1) (nodeBase + p.molecules.length) rest with
        | some hereNodes, some (tailNodes, tailTable, tailGroups) =>
            let hereTable := p.molecules.map (fun m =>
              { side := PatternSide.reactant, pattern := patternIndex, molecule := m.occurrence })
            let hereIndices := (enumerateWithNat nodeBase p.molecules).map (fun pair => pair.2)
            some (hereNodes ++ tailNodes, hereTable ++ tailTable, hereIndices :: tailGroups)
        | _, _ => none
  match lowerPatterns 0 0 d.reactants with
  | none => none
  | some (nodes, table, groups) =>
      let same := groups.flatMap pairwiseSameComplex
      let rec different : List (List Nat) → List NFnextMolecularity
        | [] => []
        | g :: rest => rest.flatMap (crossDifferentComplex g) ++ different rest
      some { pattern := { nodes := nodes, molecularity := same ++ different groups, bonds := [] }, nodeTable := table }

end BNG

namespace BNG

/-! ## Exact-bond and transformation lowering -/

/-- Compact site index for one explicit rule-site endpoint. -/
def RuleDirection.packedSiteFor? (d : RuleDirection) (packing : NFnextPacking)
    (endpoint : RuleSiteEndpoint) : Option PackedSite :=
  match d.moleculeAt? endpoint.molecule with
  | none => none
  | some molecule =>
      match molecule.findSite? endpoint.site with
      | none => none
      | some site => packing.site? molecule.moleculeType site.component

/-- Lower all exact bonds in one top-level reactant pattern. -/
def lowerPatternExactBonds? (d : RuleDirection) (packing : NFnextPacking)
    (flat : FlattenedReactants) (patternIndex : Nat) (p : Pattern) : Option (List NFnextBond) :=
  let rec go : List PatternBond → Option (List NFnextBond)
    | [] => some []
    | bond :: rest =>
        let leftMol : RuleMoleculeEndpoint :=
          { side := .reactant, pattern := patternIndex, molecule := bond.a.molecule }
        let rightMol : RuleMoleculeEndpoint :=
          { side := .reactant, pattern := patternIndex, molecule := bond.b.molecule }
        let leftSite : RuleSiteEndpoint := { molecule := leftMol, site := bond.a.site }
        let rightSite : RuleSiteEndpoint := { molecule := rightMol, site := bond.b.site }
        match flat.nodeIndex? leftMol, flat.nodeIndex? rightMol,
          d.packedSiteFor? packing leftSite, d.packedSiteFor? packing rightSite, go rest with
        | some ln, some rn, some ls, some rs, some tail =>
            some ({ firstNode := ln, firstSite := ls, secondNode := rn, secondSite := rs } :: tail)
        | _, _, _, _, _ => none
  go p.bonds

/-- Fill exact bonds after the node/molecularity flattening pass. -/
def RuleDirection.flattenReactantsNFnextWithBonds? (d : RuleDirection)
    (packing : NFnextPacking) : Option FlattenedReactants :=
  match d.flattenReactantsNFnext? packing with
  | none => none
  | some flat =>
      let rec collect : Nat → List Pattern → Option (List NFnextBond)
        | _, [] => some []
        | index, p :: rest =>
            match lowerPatternExactBonds? d packing flat index p, collect (index + 1) rest with
            | some here, some tail => some (here ++ tail)
            | _, _ => none
      match collect 0 d.reactants with
      | none => none
      | some bonds => some { flat with pattern := { flat.pattern with bonds := bonds } }

inductive NFnextTransformOp where
  | setState (node : Nat) (site : PackedSite) (state : PackedState)
  | addBond (first : Nat) (firstSite : PackedSite) (second : Nat) (secondSite : PackedSite)
  | deleteBond (first : Nat) (firstSite : PackedSite) (second : Nat) (secondSite : PackedSite)
  | createMolecule (created : Nat) (moleculeType : PackedType)
      (initialStates : List (PackedSite × PackedState))
  | addBondExistingToCreated (existing : Nat) (existingSite : PackedSite)
      (created : Nat) (createdSite : PackedSite)
  | addBondCreated (first : Nat) (firstSite : PackedSite)
      (second : Nat) (secondSite : PackedSite)
  | destroyMolecule (node : Nat)
  | destroyComplex (node : Nat)
  deriving Repr

structure NFnextTransformation where
  ops : List NFnextTransformOp := []
  deriving Repr

/-- Created-molecule ID assigned by NFnext lowering. -/
structure CreatedEndpoint where
  endpoint : RuleMoleculeEndpoint
  created : Nat
  deriving Repr

/-- Assign compact creation IDs in mutation-program order. -/
def creationTable : Nat → List Mutation → List CreatedEndpoint
  | _, [] => []
  | next, .createMolecule endpoint :: rest =>
      { endpoint := endpoint, created := next } :: creationTable (next + 1) rest
  | next, _ :: rest => creationTable next rest

/-- Lookup one product molecule in the creation table. -/
def createdIdFor? (table : List CreatedEndpoint) (endpoint : RuleMoleculeEndpoint) : Option Nat :=
  (table.find? (fun item => item.endpoint == endpoint)).map (fun item => item.created)

/-- Map a product endpoint for a surviving molecule back to its reactant endpoint. -/
def RuleDirection.reactantMoleculeFor? (d : RuleDirection)
    (endpoint : RuleMoleculeEndpoint) : Option RuleMoleculeEndpoint :=
  match endpoint.side with
  | .reactant => some endpoint
  | .product => d.productSource? endpoint

/-- Existing NFnext node for a semantic molecule endpoint, if the molecule is not newly created. -/
def RuleDirection.existingNodeFor? (d : RuleDirection) (flat : FlattenedReactants)
    (endpoint : RuleMoleculeEndpoint) : Option Nat :=
  match d.reactantMoleculeFor? endpoint with
  | none => none
  | some reactant => flat.nodeIndex? reactant

/-- Semantic molecule type and component for any component target. -/
def componentTargetContext? (d : RuleDirection) (target : ComponentTarget) : Option (MoleculeTypeId × ComponentTypeId) :=
  d.componentContext? target

/-- Compact NFnext site index for a semantic component target. -/
def RuleDirection.packedTargetSite? (d : RuleDirection) (packing : NFnextPacking)
    (target : ComponentTarget) : Option PackedSite :=
  match componentTargetContext? d target with
  | none => none
  | some (mt, component) => packing.site? mt component

/-- Molecule endpoint carried by either shape of component target. -/
def componentTargetMolecule : ComponentTarget → RuleMoleculeEndpoint
  | .site endpoint => endpoint.molecule
  | .byType molecule _ => molecule

/-- Existing node or created ID for one component target. -/
inductive NFnextTargetLocation where
  | existing (node : Nat)
  | created (id : Nat)
  deriving Repr

/-- Resolve where NFnext will find one semantic target molecule. -/
def RuleDirection.nfnextTargetLocation? (d : RuleDirection) (flat : FlattenedReactants)
    (created : List CreatedEndpoint) (target : ComponentTarget) : Option NFnextTargetLocation :=
  let molecule := componentTargetMolecule target
  match d.existingNodeFor? flat molecule with
  | some node => some (.existing node)
  | none => (createdIdFor? created molecule).map NFnextTargetLocation.created

/-- Exact initial states explicitly carried by a newly-created product molecule. -/
def RuleDirection.createdInitialStates? (d : RuleDirection) (packing : NFnextPacking)
    (endpoint : RuleMoleculeEndpoint) : Option (List (PackedSite × PackedState)) :=
  match d.moleculeAt? endpoint with
  | none => none
  | some molecule =>
      let rec go : List PatternSite → Option (List (PackedSite × PackedState))
        | [] => some []
        | site :: rest =>
            match site.state.exactState? with
            | none => go rest
            | some state =>
                match packing.site? molecule.moleculeType site.component,
                  packing.state? molecule.moleculeType site.component state, go rest with
                | some packedSite, some packedState, some tail =>
                    some ((packedSite, packedState) :: tail)
                | _, _, _ => none
      go molecule.sites

/-- Lower one semantic mutation into zero or one generic NFnext operation. -/
def RuleDirection.lowerMutationNFnext? (d : RuleDirection) (packing : NFnextPacking)
    (flat : FlattenedReactants) (created : List CreatedEndpoint) : Mutation → Option NFnextTransformOp
  | .changeState target newState =>
      match d.nfnextTargetLocation? flat created target,
        componentTargetContext? d target,
        d.packedTargetSite? packing target with
      | some (.existing node), some (mt, component), some site =>
          (packing.state? mt component newState).map (fun state => .setState node site state)
      | _, _, _ => none
  | .createBond left right =>
      match d.nfnextTargetLocation? flat created left,
        d.nfnextTargetLocation? flat created right,
        d.packedTargetSite? packing left,
        d.packedTargetSite? packing right with
      | some (.existing a), some (.existing b), some sa, some sb =>
          some (.addBond a sa b sb)
      | some (.existing a), some (.created b), some sa, some sb =>
          some (.addBondExistingToCreated a sa b sb)
      | some (.created a), some (.existing b), some sa, some sb =>
          some (.addBondExistingToCreated b sb a sa)
      | some (.created a), some (.created b), some sa, some sb =>
          some (.addBondCreated a sa b sb)
      | _, _, _, _ => none
  | .deleteBond left right =>
      match d.nfnextTargetLocation? flat created left,
        d.nfnextTargetLocation? flat created right,
        d.packedTargetSite? packing left,
        d.packedTargetSite? packing right with
      | some (.existing a), some (.existing b), some sa, some sb =>
          some (.deleteBond a sa b sb)
      | _, _, _, _ => none
  | .createMolecule endpoint =>
      match createdIdFor? created endpoint, d.moleculeAt? endpoint with
      | some createdId, some molecule =>
          match packing.type? molecule.moleculeType, d.createdInitialStates? packing endpoint with
          | some packedType, some states => some (.createMolecule createdId packedType states)
          | _, _ => none
      | _, _ => none
  | .deleteMolecule endpoint =>
      (d.existingNodeFor? flat endpoint).map NFnextTransformOp.destroyMolecule
  | .clearBonds _ => none
  | .moveCompartment _ _ => none

/-- Lower the complete supported graph-edit program. -/
def RuleDirection.lowerNFnextTransformation? (d : RuleDirection)
    (packing : NFnextPacking) : Option (FlattenedReactants × NFnextTransformation) :=
  if !(nfnextSupported d) then none
  else
    match d.flattenReactantsNFnextWithBonds? packing with
    | none => none
    | some flat =>
        let created := creationTable 0 d.mutations
        let rec go : List Mutation → Option (List NFnextTransformOp)
          | [] => some []
          | mutation :: rest =>
              match d.lowerMutationNFnext? packing flat created mutation, go rest with
              | some op, some tail => some (op :: tail)
              | _, _ => none
        match go d.mutations with
        | none => none
        | some ops => some (flat, { ops := ops })

end BNG
