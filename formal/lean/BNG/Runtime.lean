import BNG.Rule

namespace BNG

/-!
# Concrete molecular mixtures

The earlier files describe **patterns** such as `A(x~p!1).B(y!1)`.  A pattern is
not a cell or a simulated system; it is a query over a concrete molecular graph.

This file introduces the concrete graph that the query is matched against.
Think of it as a deliberately tiny, mathematical version of the state carried
by a network-free simulator:

* every molecule instance has a unique runtime ID;
* every site has a component type and an optional internal state;
* bonds are explicit undirected edges between concrete sites;
* a mixture is just a finite collection of molecule instances plus bonds.

This is intentionally simpler than NFsim.  It is a **reference semantics**, not
an optimized data structure.
-/

/-- Identity of one concrete molecule instance in a simulated mixture. -/
structure MoleculeInstanceId where
  value : Nat
  deriving Repr, DecidableEq, BEq

/-- A concrete site is addressed by molecule identity + resolved component type. -/
structure ConcreteEndpoint where
  molecule : MoleculeInstanceId
  component : ComponentTypeId
  deriving Repr, DecidableEq, BEq

/--
A concrete site's state.

`none` means "this component has no selected internal state".  Components with
state alphabets normally carry `some stateId`; state-less binding sites can
legitimately remain `none`.
-/
structure RuntimeSite where
  component : ComponentTypeId
  state : Option StateId := none
  deriving Repr, DecidableEq, BEq

structure RuntimeMolecule where
  id : MoleculeInstanceId
  moleculeType : MoleculeTypeId
  compartment : Option CompartmentId := none
  sites : List RuntimeSite := []
  deriving Repr

/-- One undirected concrete bond.  `(a,b)` and `(b,a)` mean the same edge. -/
structure RuntimeBond where
  a : ConcreteEndpoint
  b : ConcreteEndpoint
  deriving Repr

/--
A finite molecular mixture.

`nextMoleculeId` is the allocator cursor used by molecule-creation rules.  A
well-formed mixture keeps all existing molecule IDs below this cursor.
-/
structure Mixture where
  nextMoleculeId : MoleculeInstanceId := ⟨0⟩
  molecules : List RuntimeMolecule := []
  bonds : List RuntimeBond := []
  deriving Repr

/-- Find a concrete molecule by runtime identity. -/
def Mixture.findMolecule? (mix : Mixture) (id : MoleculeInstanceId) : Option RuntimeMolecule :=
  let rec go : List RuntimeMolecule → Option RuntimeMolecule
    | [] => none
    | m :: rest => if m.id == id then some m else go rest
  go mix.molecules

/-- Find one concrete component/site on a runtime molecule. -/
def RuntimeMolecule.findSite? (m : RuntimeMolecule) (component : ComponentTypeId) : Option RuntimeSite :=
  let rec go : List RuntimeSite → Option RuntimeSite
    | [] => none
    | s :: rest => if s.component == component then some s else go rest
  go m.sites

/-- Does a concrete endpoint actually exist in the mixture? -/
def Mixture.hasEndpoint (mix : Mixture) (e : ConcreteEndpoint) : Bool :=
  match mix.findMolecule? e.molecule with
  | none => false
  | some m =>
      match m.findSite? e.component with
      | none => false
      | some _ => true

/-- Equality of an undirected bond, ignoring endpoint order. -/
def RuntimeBond.sameUndirected (x y : RuntimeBond) : Bool :=
  ((x.a == y.a) && (x.b == y.b)) || ((x.a == y.b) && (x.b == y.a))

/-- Is the exact undirected edge present? -/
def Mixture.hasBond (mix : Mixture) (a b : ConcreteEndpoint) : Bool :=
  mix.bonds.any (fun edge => edge.sameUndirected { a := a, b := b })

/-- Does this endpoint participate in at least one bond? -/
def Mixture.endpointBound (mix : Mixture) (e : ConcreteEndpoint) : Bool :=
  mix.bonds.any (fun edge => (edge.a == e) || (edge.b == e))

/-- Is this endpoint completely free of bonds? -/
def Mixture.endpointFree (mix : Mixture) (e : ConcreteEndpoint) : Bool :=
  !(mix.endpointBound e)

/-- Does this molecule participate in any bond through any component? -/
def Mixture.moleculeHasBond (mix : Mixture) (id : MoleculeInstanceId) : Bool :=
  mix.bonds.any (fun edge => (edge.a.molecule == id) || (edge.b.molecule == id))

/-- Update exactly one runtime molecule, failing if the molecule does not exist. -/
def Mixture.modifyMolecule? (mix : Mixture) (id : MoleculeInstanceId)
    (f : RuntimeMolecule → Option RuntimeMolecule) : Option Mixture :=
  let rec go : List RuntimeMolecule → Option (List RuntimeMolecule)
    | [] => none
    | m :: rest =>
        if m.id == id then
          match f m with
          | none => none
          | some m' => some (m' :: rest)
        else
          match go rest with
          | none => none
          | some rest' => some (m :: rest')
  match go mix.molecules with
  | none => none
  | some molecules' => some { mix with molecules := molecules' }

/-- Update exactly one site state on one molecule. -/
def Mixture.setState? (mix : Mixture) (e : ConcreteEndpoint) (newState : StateId) : Option Mixture :=
  mix.modifyMolecule? e.molecule (fun m =>
    let rec go : List RuntimeSite → Option (List RuntimeSite)
      | [] => none
      | s :: rest =>
          if s.component == e.component then
            some ({ s with state := some newState } :: rest)
          else
            match go rest with
            | none => none
            | some rest' => some (s :: rest')
    match go m.sites with
    | none => none
    | some sites' => some { m with sites := sites' })

/-- Move one molecule to a different compartment. -/
def Mixture.moveMolecule? (mix : Mixture) (id : MoleculeInstanceId)
    (destination : CompartmentId) : Option Mixture :=
  mix.modifyMolecule? id (fun m => some { m with compartment := some destination })

/-- Add an exact bond. Duplicate edges and self-bonds are rejected. -/
def Mixture.addBond? (mix : Mixture) (a b : ConcreteEndpoint) : Option Mixture :=
  if a == b then none
  else if !(mix.hasEndpoint a && mix.hasEndpoint b) then none
  else if mix.hasBond a b then none
  else some { mix with bonds := { a := a, b := b } :: mix.bonds }

/-- Remove one exact undirected bond; fail if that edge was not present. -/
def Mixture.removeBond? (mix : Mixture) (a b : ConcreteEndpoint) : Option Mixture :=
  let target : RuntimeBond := { a := a, b := b }
  if !(mix.hasBond a b) then none
  else
    some { mix with bonds := mix.bonds.filter (fun edge => !(edge.sameUndirected target)) }

/-- Remove every bond incident on one concrete site. -/
def Mixture.clearBonds (mix : Mixture) (e : ConcreteEndpoint) : Mixture :=
  { mix with bonds := mix.bonds.filter (fun edge => !((edge.a == e) || (edge.b == e))) }

/-- Delete one molecule and every bond incident on it. -/
def Mixture.deleteMolecule? (mix : Mixture) (id : MoleculeInstanceId) : Option Mixture :=
  match mix.findMolecule? id with
  | none => none
  | some _ =>
      some {
        mix with
        molecules := mix.molecules.filter (fun m => !(m.id == id))
        bonds := mix.bonds.filter (fun edge =>
          !((edge.a.molecule == id) || (edge.b.molecule == id))) }

/--
Check one concrete molecule against the declaration signature.

The runtime representation is allowed to be *sparse* in this first semantics:
not every declared component must be materialized, but every materialized site
must be declared and every selected state must be legal for that component.
-/
def RuntimeMolecule.wellFormed (m : RuntimeMolecule) (sig : Signature) : Bool :=
  match sig.findMoleculeType? m.moleculeType with
  | none => false
  | some mt =>
      let compartmentOK :=
        match m.compartment with
        | none => true
        | some c => sig.hasCompartment c
      let siteIdsOK := allUnique (m.sites.map (fun s => s.component))
      let sitesOK := m.sites.all (fun site =>
        match mt.findComponent? site.component with
        | none => false
        | some component =>
            match site.state with
            | none => true
            | some state => component.hasState state)
      compartmentOK && siteIdsOK && sitesOK

/-- Executable structural validity check for a concrete mixture. -/
def Mixture.wellFormed (mix : Mixture) (sig : Signature) : Bool :=
  let idsUnique := allUnique (mix.molecules.map (fun m => m.id))
  let idsBelowCursor := mix.molecules.all (fun m => decide (m.id.value < mix.nextMoleculeId.value))
  let moleculesOK := mix.molecules.all (fun m => m.wellFormed sig)
  let bondsOK := mix.bonds.all (fun edge =>
    (!(edge.a == edge.b)) && mix.hasEndpoint edge.a && mix.hasEndpoint edge.b)
  let bondsUnique :=
    let rec go : List RuntimeBond → Bool
      | [] => true
      | edge :: rest =>
          (!(rest.any (fun other => edge.sameUndirected other))) && go rest
    go mix.bonds
  idsUnique && idsBelowCursor && moleculesOK && bondsOK && bondsUnique

end BNG
