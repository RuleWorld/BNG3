import BNG.Expression

namespace BNG

/-!
# Model declarations

These types correspond to the pieces that the proposed `CompiledModel` should
own directly: parameters, molecule/component/state declarations, compartments,
and the namespace needed by resolved expressions.
-/

structure StateDecl where
  id : StateId
  name : String
  deriving Repr, DecidableEq

structure ComponentType where
  id : ComponentTypeId
  name : String
  states : List StateDecl := []
  deriving Repr

structure MoleculeType where
  id : MoleculeTypeId
  name : String
  population : Bool := false
  components : List ComponentType := []
  deriving Repr

structure ParameterDecl where
  id : ParameterId
  name : String
  expression : Expr
  constantValue : Option Float := none
  deriving Repr

structure CompartmentDecl where
  id : CompartmentId
  name : String
  dimension : Nat
  size : Expr
  parent : Option CompartmentId := none
  deriving Repr

/-- The declaration subset required to validate patterns. -/
structure Signature where
  moleculeTypes : List MoleculeType := []
  compartments : List CompartmentDecl := []
  deriving Repr

/-- The declaration IDs that a resolved expression is allowed to reference. -/
structure ExprScope where
  parameters : List ParameterId := []
  observables : List ObservableId := []
  functions : List FunctionId := []
  deriving Repr

/-- Lookup helpers are explicit and deterministic; no string resolution occurs here. -/
def Signature.findMoleculeType? (s : Signature) (id : MoleculeTypeId) : Option MoleculeType :=
  let rec go : List MoleculeType → Option MoleculeType
    | [] => none
    | x :: xs => if x.id == id then some x else go xs
  go s.moleculeTypes


def MoleculeType.findComponent? (m : MoleculeType) (id : ComponentTypeId) : Option ComponentType :=
  let rec go : List ComponentType → Option ComponentType
    | [] => none
    | x :: xs => if x.id == id then some x else go xs
  go m.components


def ComponentType.hasState (c : ComponentType) (id : StateId) : Bool :=
  c.states.any (fun s => s.id == id)


def Signature.hasCompartment (s : Signature) (id : CompartmentId) : Bool :=
  s.compartments.any (fun c => c.id == id)


def ExprScope.contains (s : ExprScope) : SymbolRef → Bool
  | .parameter id => s.parameters.contains id
  | .observable id => s.observables.contains id
  | .function id => s.functions.contains id

/-- A resolved expression is valid when every typed global reference exists. -/
def Expr.referencesValid (e : Expr) (scope : ExprScope) : Bool :=
  e.references.all scope.contains

end BNG
