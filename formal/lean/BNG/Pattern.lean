import BNG.Declarations

namespace BNG

/-!
# Semantic patterns

A BNGL pattern is a constrained molecular graph.  The important word is
*constrained*: `A(x)` does not mean the same thing as `A(x~p!1)`.

Two details from the current BNG3 grammar are deliberately preserved here even
though the sketch in the proposed migration was simpler:

1. A site can carry **multiple bond specifications** (`!0!1`).
2. A whole molecule can carry a bond wildcard (`!+` or `!?`).

A formal semantic IR should not silently lose either capability.
-/

inductive StateConstraint where
  /-- `~?` or an intentionally unconstrained state. -/
  | any
  /-- One exact allowed state. -/
  | exact (state : StateId)
  /-- A future/backend-friendly finite state set. -/
  | oneOf (states : List StateId)
  deriving Repr

/-- One bond requirement attached to a site. Empty list means unspecified. -/
inductive BondRequirement where
  /-- Explicitly free/unbound (`!-` or dot notation). -/
  | free
  /-- Bound to something, partner unspecified (`!+`). -/
  | bound
  /-- Either bound or unbound (`!?`). -/
  | any
  /-- Part of one exact numbered/named bond group. -/
  | exact (group : BondGroupId)
  deriving Repr, DecidableEq, BEq

/-- Molecule-level wildcard from forms such as `A(...)!+` and `A(...)!?`. -/
inductive MoleculeBondRequirement where
  | hasBond
  | any
  deriving Repr, DecidableEq, BEq

structure PatternSite where
  occurrence : PatternSiteId
  component : ComponentTypeId
  state : StateConstraint := .any
  bonds : List BondRequirement := []
  /-- `%tag` is retained as resolved mapping provenance until correspondence is compiled. -/
  label : Option String := none
  deriving Repr

structure PatternMolecule where
  occurrence : PatternMoleculeId
  moleculeType : MoleculeTypeId
  compartment : Option CompartmentId := none
  sites : List PatternSite := []
  moleculeBond : Option MoleculeBondRequirement := none
  deriving Repr

/-- A site endpoint is unambiguous only together with its molecule occurrence. -/
structure PatternEndpoint where
  molecule : PatternMoleculeId
  site : PatternSiteId
  deriving Repr, DecidableEq, BEq

structure PatternBond where
  group : BondGroupId
  a : PatternEndpoint
  b : PatternEndpoint
  deriving Repr, DecidableEq, BEq

structure Pattern where
  molecules : List PatternMolecule := []
  bonds : List PatternBond := []
  deriving Repr

/-- Find a molecule occurrence by its pattern-local ID. -/
def Pattern.findMolecule? (p : Pattern) (id : PatternMoleculeId) : Option PatternMolecule :=
  let rec go : List PatternMolecule → Option PatternMolecule
    | [] => none
    | x :: xs => if x.occurrence == id then some x else go xs
  go p.molecules

/-- Find a site occurrence inside one molecule occurrence. -/
def PatternMolecule.findSite? (m : PatternMolecule) (id : PatternSiteId) : Option PatternSite :=
  let rec go : List PatternSite → Option PatternSite
    | [] => none
    | x :: xs => if x.occurrence == id then some x else go xs
  go m.sites

/-- Does the endpoint name a site that actually occurs in this pattern? -/
def Pattern.hasEndpoint (p : Pattern) (e : PatternEndpoint) : Bool :=
  match p.findMolecule? e.molecule with
  | none => false
  | some m =>
      match m.findSite? e.site with
      | none => false
      | some _ => true

/-- Does this pattern define the exact bond group `g`? -/
def Pattern.hasBondGroup (p : Pattern) (g : BondGroupId) : Bool :=
  p.bonds.any (fun b => b.group == g)

/-- Is endpoint `e` actually attached to exact bond group `g`? -/
def Pattern.endpointUsesBond (p : Pattern) (e : PatternEndpoint) (g : BondGroupId) : Bool :=
  p.bonds.any (fun b =>
    (b.group == g) && ((b.a == e) || (b.b == e)))

/-- Does the endpoint explicitly declare that it participates in exact bond `g`? -/
def Pattern.endpointDeclaresBond (p : Pattern) (e : PatternEndpoint) (g : BondGroupId) : Bool :=
  match p.findMolecule? e.molecule with
  | none => false
  | some molecule =>
      match molecule.findSite? e.site with
      | none => false
      | some site => site.bonds.contains (.exact g)

/-- Validate a state constraint against one declared component type. -/
def stateConstraintValid (component : ComponentType) : StateConstraint → Bool
  | .any => true
  | .exact s => component.hasState s
  | .oneOf states =>
      match states with
      | [] => false
      | _ => states.all component.hasState

/--
Validate one molecule occurrence against the declaration signature.
This catches stale/wrong IDs before any simulator sees the pattern.
-/
def Pattern.moleculeWellFormed (p : Pattern) (sig : Signature) (m : PatternMolecule) : Bool :=
  match sig.findMoleculeType? m.moleculeType with
  | none => false
  | some mt =>
      let compartmentOK :=
        match m.compartment with
        | none => true
        | some c => sig.hasCompartment c
      let siteIdsOK := allUnique (m.sites.map (fun s => s.occurrence))
      let sitesOK := m.sites.all (fun site =>
        match mt.findComponent? site.component with
        | none => false
        | some component =>
            let stateOK := stateConstraintValid component site.state
            let endpoint : PatternEndpoint :=
              { molecule := m.occurrence, site := site.occurrence }
            let bondsOK := site.bonds.all (fun requirement =>
              match requirement with
              | .exact g => p.endpointUsesBond endpoint g
              | _ => true)
            stateOK && bondsOK)
      compartmentOK && siteIdsOK && sitesOK

/-- Executable well-formedness check for a semantic pattern. -/
def Pattern.wellFormed (p : Pattern) (sig : Signature) : Bool :=
  let moleculeIdsOK := allUnique (p.molecules.map (fun m => m.occurrence))
  let bondIdsOK := allUnique (p.bonds.map (fun b => b.group))
  let moleculesOK := p.molecules.all (p.moleculeWellFormed sig)
  let bondsOK := p.bonds.all (fun b =>
    (!(b.a == b.b)) &&
    p.hasEndpoint b.a && p.hasEndpoint b.b &&
    p.endpointDeclaresBond b.a b.group &&
    p.endpointDeclaresBond b.b b.group)
  moleculeIdsOK && bondIdsOK && moleculesOK && bondsOK

end BNG
