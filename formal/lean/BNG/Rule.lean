import BNG.Pattern

namespace BNG

/-!
# Compiled reaction rules

This module is where formalization pays for itself as a design exercise.
A rule is not only "reactant text + product text".  Once names are resolved,
BNG3 still needs an explicit account of:

* which molecule/site occurrences correspond across the arrow,
* what state/bond/molecule edits happen,
* compartment transport,
* local-function scope,
* include/exclude filters, and
* modifiers such as `DeleteMolecules` and `MoveConnected`.

The current C++ `ReactionRule` computes several of these facts internally.
The target compiler IR should own them so backends do not independently infer
the same semantics.
-/

inductive PatternSide where
  | reactant
  | product
  deriving Repr, DecidableEq, BEq

/-- Reversing twice gets us back where we started. -/
def PatternSide.flip : PatternSide → PatternSide
  | .reactant => .product
  | .product => .reactant

theorem PatternSide.flip_involutive (s : PatternSide) : s.flip.flip = s := by
  cases s <;> rfl

/-- Address one molecule occurrence in one top-level rule pattern. -/
structure RuleMoleculeEndpoint where
  side : PatternSide
  pattern : Nat
  molecule : PatternMoleculeId
  deriving Repr, DecidableEq, BEq

/-- Address one explicitly mentioned site occurrence. -/
structure RuleSiteEndpoint where
  molecule : RuleMoleculeEndpoint
  site : PatternSiteId
  deriving Repr, DecidableEq, BEq

/--
Some legal BNGL rules constrain a component only on the product side, even
though that component was omitted from the reactant pattern.  Therefore a
mutation target cannot always require a reactant-side `PatternSiteId`.
-/
inductive ComponentTarget where
  | site (endpoint : RuleSiteEndpoint)
  | byType (molecule : RuleMoleculeEndpoint) (component : ComponentTypeId)
  deriving Repr, DecidableEq, BEq

structure MoleculeCorrespondence where
  reactant : RuleMoleculeEndpoint
  product : RuleMoleculeEndpoint
  deriving Repr, DecidableEq, BEq

structure ComponentCorrespondence where
  reactant : ComponentTarget
  product : ComponentTarget
  deriving Repr, DecidableEq, BEq

/-- The resolved molecule that supplies `%x::` local-function context. -/
structure LocalScopeBinding where
  name : String
  molecule : RuleMoleculeEndpoint
  deriving Repr

/--
Atomic semantic edits.  `clearBonds` and `moveCompartment` are included because
current BNG3 behavior requires them even though a minimal five-operation sketch
does not capture every legal rule.
-/
inductive Mutation where
  | changeState (target : ComponentTarget) (newState : StateId)
  | createBond (a b : ComponentTarget)
  | deleteBond (a b : ComponentTarget)
  | clearBonds (target : ComponentTarget)
  | createMolecule (target : RuleMoleculeEndpoint)
  | deleteMolecule (target : RuleMoleculeEndpoint)
  | moveCompartment (target : RuleMoleculeEndpoint) (destination : CompartmentId)
  deriving Repr

inductive Modifier where
  | deleteMolecules
  | moveConnected
  | matchOnce
  | totalRate
  | priority (value : Expr)
  deriving Repr

inductive FilterMode where
  | include
  | exclude
  deriving Repr, DecidableEq, BEq

structure RuleFilter where
  mode : FilterMode
  side : PatternSide
  /-- 0-based top-level pattern index, matching the proposed compile-layer convention. -/
  patternIndex : Nat
  patterns : List Pattern
  deriving Repr

structure RuleDirection where
  reactants : List Pattern := []
  products : List Pattern := []
  rate : RateLaw
  mutations : List Mutation := []
  modifiers : List Modifier := []
  filters : List RuleFilter := []
  moleculeMap : List MoleculeCorrespondence := []
  componentMap : List ComponentCorrespondence := []
  localScopes : List LocalScopeBinding := []
  deriving Repr

structure CompiledRule where
  id : ReactionRuleId
  name : String
  forward : RuleDirection
  /-- Reversible BNGL is compiled once here, not independently by each backend. -/
  reverse : Option RuleDirection := none
  deriving Repr

/-- Select a top-level reactant/product pattern. -/
def RuleDirection.patternAt? (d : RuleDirection) (side : PatternSide) (index : Nat) : Option Pattern :=
  match side with
  | .reactant => listGet? d.reactants index
  | .product => listGet? d.products index

/-- Resolve a rule-level molecule endpoint into the actual pattern molecule. -/
def RuleDirection.moleculeAt? (d : RuleDirection) (e : RuleMoleculeEndpoint) : Option PatternMolecule :=
  match d.patternAt? e.side e.pattern with
  | none => none
  | some p => p.findMolecule? e.molecule

/-- Resolve a component target to `(molecule type, component type)`. -/
def RuleDirection.componentContext? (d : RuleDirection) (target : ComponentTarget) : Option (MoleculeTypeId × ComponentTypeId) :=
  match target with
  | .byType molecule component =>
      match d.moleculeAt? molecule with
      | none => none
      | some m => some (m.moleculeType, component)
  | .site endpoint =>
      match d.moleculeAt? endpoint.molecule with
      | none => none
      | some m =>
          match m.findSite? endpoint.site with
          | none => none
          | some s => some (m.moleculeType, s.component)

/-- Does a declaration signature know the exact component named by a rule target? -/
def RuleDirection.componentTargetValid (d : RuleDirection) (sig : Signature) (target : ComponentTarget) : Bool :=
  match d.componentContext? target with
  | none => false
  | some (moleculeType, componentType) =>
      match sig.findMoleculeType? moleculeType with
      | none => false
      | some mt =>
          match mt.findComponent? componentType with
          | none => false
          | some _ => true

/-- Validate a new state against the target component's declaration. -/
def RuleDirection.stateValidForTarget
    (d : RuleDirection) (sig : Signature) (target : ComponentTarget) (state : StateId) : Bool :=
  match d.componentContext? target with
  | none => false
  | some (moleculeType, componentType) =>
      match sig.findMoleculeType? moleculeType with
      | none => false
      | some mt =>
          match mt.findComponent? componentType with
          | none => false
          | some component => component.hasState state

/-- Is a rule-level molecule endpoint real? -/
def RuleDirection.moleculeEndpointValid (d : RuleDirection) (e : RuleMoleculeEndpoint) : Bool :=
  match d.moleculeAt? e with
  | none => false
  | some _ => true

/-- Validate a single semantic mutation. -/
def RuleDirection.mutationWellFormed (d : RuleDirection) (sig : Signature) : Mutation → Bool
  | .changeState target state =>
      d.componentTargetValid sig target && d.stateValidForTarget sig target state
  | .createBond a b => d.componentTargetValid sig a && d.componentTargetValid sig b
  | .deleteBond a b => d.componentTargetValid sig a && d.componentTargetValid sig b
  | .clearBonds target => d.componentTargetValid sig target
  | .createMolecule target =>
      (target.side == PatternSide.product) && d.moleculeEndpointValid target
  | .deleteMolecule target =>
      (target.side == PatternSide.reactant) && d.moleculeEndpointValid target
  | .moveCompartment target destination =>
      d.moleculeEndpointValid target && sig.hasCompartment destination

/-- Validate resolved cross-arrow molecule correspondence. -/
def RuleDirection.moleculeCorrespondenceWellFormed (d : RuleDirection) (m : MoleculeCorrespondence) : Bool :=
  (m.reactant.side == PatternSide.reactant) &&
  (m.product.side == PatternSide.product) &&
  d.moleculeEndpointValid m.reactant &&
  d.moleculeEndpointValid m.product

/-- Validate resolved cross-arrow component correspondence. -/
def RuleDirection.componentCorrespondenceWellFormed
    (d : RuleDirection) (sig : Signature) (m : ComponentCorrespondence) : Bool :=
  d.componentTargetValid sig m.reactant && d.componentTargetValid sig m.product

/-- Validate one compiled direction, independent of any simulator. -/
def RuleDirection.wellFormed (d : RuleDirection) (sig : Signature) (scope : ExprScope) : Bool :=
  let reactantsOK := d.reactants.all (fun p => p.wellFormed sig)
  let productsOK := d.products.all (fun p => p.wellFormed sig)
  let rateOK := d.rate.expression.referencesValid scope &&
    d.rate.expression.localsValid (d.localScopes.map (fun binding => binding.name))
  let mutationsOK := d.mutations.all (d.mutationWellFormed sig)
  let modifiersOK := d.modifiers.all (fun modifier =>
    match modifier with
    | .priority value => value.referencesValid scope && value.hasNoLocals
    | _ => true)
  let mapsOK :=
    d.moleculeMap.all d.moleculeCorrespondenceWellFormed &&
    d.componentMap.all (d.componentCorrespondenceWellFormed sig)
  let scopesOK := d.localScopes.all (fun binding =>
    (binding.molecule.side == PatternSide.reactant) &&
    d.moleculeEndpointValid binding.molecule)
  let filtersOK := d.filters.all (fun filter =>
    match d.patternAt? filter.side filter.patternIndex with
    | none => false
    | some _ => filter.patterns.all (fun p => p.wellFormed sig))
  reactantsOK && productsOK && rateOK && mutationsOK && modifiersOK && mapsOK && scopesOK && filtersOK

end BNG
