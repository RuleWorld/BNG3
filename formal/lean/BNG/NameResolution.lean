import BNG.Model

namespace BNG

/-!
# Parser-facing names → semantic IDs

The parser necessarily starts with text.  The compiler boundary should be the
last place where those names have executable meaning.  This module gives the
formal side a small, deterministic name-resolution layer for declarations and
expressions.

Backends should never call these functions.
-/

/-- Resolve declaration names in the compiled model namespace. -/
def CompiledModel.parameterIdByName? (m : CompiledModel) (name : String) : Option ParameterId :=
  (m.parameters.find? (fun p => p.name == name)).map (fun p => p.id)

def CompiledModel.observableIdByName? (m : CompiledModel) (name : String) : Option ObservableId :=
  (m.observables.find? (fun o => o.name == name)).map (fun o => o.id)

def CompiledModel.functionIdByName? (m : CompiledModel) (name : String) : Option FunctionId :=
  (m.functions.find? (fun f => f.name == name)).map (fun f => f.id)

def CompiledModel.moleculeTypeByName? (m : CompiledModel) (name : String) : Option MoleculeType :=
  m.moleculeTypes.find? (fun mt => mt.name == name)

def CompiledModel.compartmentIdByName? (m : CompiledModel) (name : String) : Option CompartmentId :=
  (m.compartments.find? (fun c => c.name == name)).map (fun c => c.id)

def MoleculeType.componentByName? (m : MoleculeType) (name : String) : Option ComponentType :=
  m.components.find? (fun c => c.name == name)

def ComponentType.stateIdByName? (c : ComponentType) (name : String) : Option StateId :=
  (c.states.find? (fun s => s.name == name)).map (fun s => s.id)

/-- Parser-facing expression vocabulary before global names are resolved. -/
inductive NamedExpr where
  | number (value : Float)
  | parameter (name : String)
  | observable (name : String)
  | functionCall (name : String) (arguments : List NamedExpr)
  | localRef (name : String)
  | time
  | unary (op : UnaryOp) (argument : NamedExpr)
  | binary (op : BinaryOp) (left right : NamedExpr)
  | builtinCall (fn : Builtin) (arguments : List NamedExpr)
  | tableFunction (method : String) (arguments : List NamedExpr)
  deriving Repr

/- Resolve every global symbol into its typed semantic ID. -/
mutual
  partial def resolveNamedExpr (model : CompiledModel) : NamedExpr → Option Expr
    | .number value => some (.number value)
    | .parameter name => (model.parameterIdByName? name).map Expr.parameter
    | .observable name => (model.observableIdByName? name).map Expr.observable
    | .functionCall name arguments =>
        match model.functionIdByName? name, resolveNamedExprList model arguments with
        | some id, some args => some (.functionCall id args)
        | _, _ => none
    | .localRef name => some (.localRef name)
    | .time => some .time
    | .unary op argument =>
        (resolveNamedExpr model argument).map (Expr.unary op)
    | .binary op left right =>
        match resolveNamedExpr model left, resolveNamedExpr model right with
        | some l, some r => some (.binary op l r)
        | _, _ => none
    | .builtinCall fn arguments =>
        (resolveNamedExprList model arguments).map (Expr.builtinCall fn)
    | .tableFunction method arguments =>
        (resolveNamedExprList model arguments).map (Expr.tableFunction method)

  partial def resolveNamedExprList (model : CompiledModel) : List NamedExpr → Option (List Expr)
    | [] => some []
    | x :: xs =>
        match resolveNamedExpr model x, resolveNamedExprList model xs with
        | some head, some tail => some (head :: tail)
        | _, _ => none
end

/-- A failed global name lookup is an explicit compiler failure, not a backend fallback. -/
def NamedExpr.resolves (model : CompiledModel) (source : NamedExpr) : Bool :=
  (resolveNamedExpr model source).isSome

end BNG

namespace BNG

/-! ## Pattern name resolution -/

inductive NamedStateConstraint where
  | any
  | exact (name : String)
  | oneOf (names : List String)
  deriving Repr

structure NamedPatternSite where
  occurrence : PatternSiteId
  componentName : String
  state : NamedStateConstraint := .any
  bonds : List BondRequirement := []
  label : Option String := none
  deriving Repr

structure NamedPatternMolecule where
  occurrence : PatternMoleculeId
  moleculeTypeName : String
  compartmentName : Option String := none
  sites : List NamedPatternSite := []
  moleculeBond : Option MoleculeBondRequirement := none
  deriving Repr

structure NamedPattern where
  molecules : List NamedPatternMolecule := []
  /-- Bond endpoints/groups are parser-assigned occurrence IDs and need no name resolution. -/
  bonds : List PatternBond := []
  deriving Repr

/-- Resolve a finite list of state names against one component declaration. -/
def resolveStateNames (component : ComponentType) : List String → Option (List StateId)
  | [] => some []
  | name :: rest =>
      match component.stateIdByName? name, resolveStateNames component rest with
      | some id, some ids => some (id :: ids)
      | _, _ => none

/-- Resolve one parser-facing state constraint. -/
def resolveStateConstraint (component : ComponentType) : NamedStateConstraint → Option StateConstraint
  | .any => some .any
  | .exact name => (component.stateIdByName? name).map StateConstraint.exact
  | .oneOf names => (resolveStateNames component names).map StateConstraint.oneOf

/-- Resolve all explicitly mentioned components of one named molecule. -/
def resolveNamedSites (moleculeType : MoleculeType) : List NamedPatternSite → Option (List PatternSite)
  | [] => some []
  | source :: rest =>
      match moleculeType.componentByName? source.componentName with
      | none => none
      | some component =>
          match resolveStateConstraint component source.state, resolveNamedSites moleculeType rest with
          | some state, some tail =>
              some ({ occurrence := source.occurrence
                      component := component.id
                      state := state
                      bonds := source.bonds
                      label := source.label } :: tail)
          | _, _ => none

/-- Resolve one molecule occurrence. -/
def resolveNamedMolecule (model : CompiledModel) (source : NamedPatternMolecule) : Option PatternMolecule :=
  match model.moleculeTypeByName? source.moleculeTypeName with
  | none => none
  | some moleculeType =>
      let compartment? : Option (Option CompartmentId) :=
        match source.compartmentName with
        | none => some none
        | some name => (model.compartmentIdByName? name).map some
      match compartment?, resolveNamedSites moleculeType source.sites with
      | some compartment, some sites =>
          some { occurrence := source.occurrence
                 moleculeType := moleculeType.id
                 compartment := compartment
                 sites := sites
                 moleculeBond := source.moleculeBond }
      | _, _ => none

/-- Resolve a molecule list atomically. -/
def resolveNamedMolecules (model : CompiledModel) :
    List NamedPatternMolecule → Option (List PatternMolecule)
  | [] => some []
  | source :: rest =>
      match resolveNamedMolecule model source, resolveNamedMolecules model rest with
      | some head, some tail => some (head :: tail)
      | _, _ => none

/-- Resolve all semantic names in one parser-facing pattern. -/
def resolveNamedPattern (model : CompiledModel) (source : NamedPattern) : Option Pattern :=
  match resolveNamedMolecules model source.molecules with
  | none => none
  | some molecules => some { molecules := molecules, bonds := source.bonds }

end BNG
