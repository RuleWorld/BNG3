import BNG.Model
import BNG.Observables

namespace BNG

/-!
# Partial expression and rate evaluation

The formal IR already removes operator strings.  This module adds numerical
meaning for the conservative arithmetic core while explicitly returning
`none` for operations whose exact BNGL/backend convention has not yet been
specified.

That is intentional: unsupported numerical semantics should fail loudly rather
than inherit whichever C++ helper happens to be called by one backend.
-/

structure ParameterValue where
  id : ParameterId
  value : Float
  deriving Repr

structure ObservableValue where
  id : ObservableId
  value : Float
  deriving Repr

structure LocalValue where
  name : String
  value : Float
  deriving Repr

structure EvalEnv where
  parameters : List ParameterValue := []
  observables : List ObservableValue := []
  locals : List LocalValue := []
  time : Float := 0.0
  deriving Repr

/-- Typed value lookup helpers. -/
def EvalEnv.parameter? (env : EvalEnv) (id : ParameterId) : Option Float :=
  (env.parameters.find? (fun x => x.id == id)).map (fun x => x.value)

def EvalEnv.observable? (env : EvalEnv) (id : ObservableId) : Option Float :=
  (env.observables.find? (fun x => x.id == id)).map (fun x => x.value)

def EvalEnv.local? (env : EvalEnv) (name : String) : Option Float :=
  (env.locals.find? (fun x => x.name == name)).map (fun x => x.value)

/-- Replace lexical/local bindings for a function body. -/
def EvalEnv.withLocals (env : EvalEnv) (bindings : List LocalValue) : EvalEnv :=
  { env with locals := bindings }

/-- Pair function formal names with already-evaluated arguments. -/
def bindFunctionArguments : List String → List Float → Option (List LocalValue)
  | [], [] => some []
  | name :: names, value :: values =>
      (bindFunctionArguments names values).map (fun rest =>
        { name := name, value := value } :: rest)
  | _, _ => none

/-- Lookup a compiled function declaration. -/
def CompiledModel.functionById? (model : CompiledModel) (id : FunctionId) : Option FunctionDecl :=
  model.functions.find? (fun f => f.id == id)

/-
Fuel-bounded evaluator.  Fuel is consumed only by function-call nesting; normal
expression recursion follows the finite syntax tree directly.
-/
mutual
  partial def evalExprFuel (model : CompiledModel) (env : EvalEnv) : Nat → Expr → Option Float
    | _, .number value => some value
    | _, .parameter id => env.parameter? id
    | _, .observable id => env.observable? id
    | _, .localRef name => env.local? name
    | _, .time => some env.time
    | fuel, .unary op argument =>
        match evalExprFuel model env fuel argument with
        | none => none
        | some value =>
            match op with
            | .positive => some value
            | .negate => some (-value)
            | .logicalNot => none
    | fuel, .binary op left right =>
        match evalExprFuel model env fuel left, evalExprFuel model env fuel right with
        | some l, some r =>
            match op with
            | .add => some (l + r)
            | .subtract => some (l - r)
            | .multiply => some (l * r)
            | .divide => some (l / r)
            | _ => none
        | _, _ => none
    | 0, .functionCall _ _ => none
    | fuel + 1, .functionCall id arguments =>
        match model.functionById? id, evalExprListFuel model env fuel arguments with
        | some fn, some values =>
            match bindFunctionArguments fn.arguments values with
            | none => none
            | some bindings => evalExprFuel model (env.withLocals bindings) fuel fn.expression
        | _, _ => none
    | _, .builtinCall _ _ => none
    | _, .tableFunction _ _ => none

  partial def evalExprListFuel (model : CompiledModel) (env : EvalEnv) (fuel : Nat) :
      List Expr → Option (List Float)
    | [] => some []
    | x :: xs =>
        match evalExprFuel model env fuel x, evalExprListFuel model env fuel xs with
        | some head, some tail => some (head :: tail)
        | _, _ => none
end

/-- Default evaluator budget tied to number of declared functions. -/
def evalExpr? (model : CompiledModel) (env : EvalEnv) (expression : Expr) : Option Float :=
  evalExprFuel model env (model.functions.length + 1) expression

/--
Conservative rate evaluation.

Only plain resolved-expression rate laws use this core evaluator.  Special
BNGL kinetic conventions remain separate proof obligations.
-/
def RateLaw.evaluateCore? (model : CompiledModel) (env : EvalEnv) (rate : RateLaw) : Option Float :=
  match rate.kind with
  | .expression => evalExpr? model env rate.expression
  | _ => none


end BNG
