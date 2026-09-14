import BNG.Source

namespace BNG

/-!
# Resolved expression IR

This is the semantic replacement for carrying executable rate-law strings into
backends.  The parser can accept many textual spellings; after compilation we
want only explicit operators and typed references.

We intentionally do **not** define floating-point evaluation here yet.  BNG3
already has several special rate-law conventions, local functions, tables, and
backend-specific numerical details.  The first useful formal boundary is to
prove that name resolution and operator selection are finished before a model
leaves the compiler layer.
-/

inductive UnaryOp where
  | positive
  | negate
  | logicalNot
  deriving Repr, DecidableEq, BEq

inductive BinaryOp where
  | add | subtract | multiply | divide | modulo | power
  | less | lessEqual | greater | greaterEqual | equal | notEqual
  | logicalAnd | logicalOr | logicalXor
  deriving Repr, DecidableEq, BEq

/-- Built-ins are constructors, not strings that a backend must dispatch on. -/
inductive Builtin where
  | abs | acos | acosh | asin | asinh | atan | atanh
  | avg | ceil | cos | cosh | exp | floor
  | ln | log10 | log2 | max | min | rint | sin | sinh | sqrt | sum | tan | tanh
  | ifThenElse
  | sat | michaelisMenten | hill | arrhenius | mratio | tfun
  | functionProduct | hybrid | pi | euler
  deriving Repr, DecidableEq, BEq

/--
Only the globally resolved declaration classes that can occur in an expression.
A local name remains textual because it is lexical, not a global declaration.
-/
inductive SymbolRef where
  | parameter (id : ParameterId)
  | observable (id : ObservableId)
  | function (id : FunctionId)
  deriving Repr, DecidableEq, BEq

/--
A resolved BNGL expression.

`Float` is used only as a syntax-level numeric payload here.  The formalization
currently reasons about expression *structure and references*, not IEEE-754
numerical accuracy.
-/
inductive Expr where
  | number (value : Float)
  | parameter (id : ParameterId)
  | observable (id : ObservableId)
  | functionCall (id : FunctionId) (arguments : List Expr)
  | localRef (name : String)
  | time
  | unary (op : UnaryOp) (argument : Expr)
  | binary (op : BinaryOp) (left right : Expr)
  | builtinCall (fn : Builtin) (arguments : List Expr)
  | tableFunction (method : String) (arguments : List Expr)
  deriving Repr

/-- Collect all global declaration references used by an expression. -/
def Expr.references : Expr → List SymbolRef
  | .number _ => []
  | .parameter id => [SymbolRef.parameter id]
  | .observable id => [SymbolRef.observable id]
  | .functionCall id args =>
      SymbolRef.function id :: args.flatMap Expr.references
  | .localRef _ => []
  | .time => []
  | .unary _ x => x.references
  | .binary _ left right => left.references ++ right.references
  | .builtinCall _ args => args.flatMap Expr.references
  | .tableFunction _ args => args.flatMap Expr.references


/-- Collect lexical/local references such as local-function scope variables. -/
def Expr.localReferences : Expr → List String
  | .number _ => []
  | .parameter _ => []
  | .observable _ => []
  | .functionCall _ args => args.flatMap Expr.localReferences
  | .localRef name => [name]
  | .time => []
  | .unary _ x => x.localReferences
  | .binary _ left right => left.localReferences ++ right.localReferences
  | .builtinCall _ args => args.flatMap Expr.localReferences
  | .tableFunction _ args => args.flatMap Expr.localReferences

/-- True when every lexical reference is allowed in the current scope. -/
def Expr.localsValid (e : Expr) (allowed : List String) : Bool :=
  e.localReferences.all (fun name => allowed.contains name)

/-- Expressions outside a lexical scope should contain no local references. -/
def Expr.hasNoLocals (e : Expr) : Bool :=
  match e.localReferences with
  | [] => true
  | _ => false

inductive RateLawKind where
  | expression
  | arrheniusEnergy
  | saturation
  | michaelisMenten
  | hill
  | functionProduct
  | hybrid
  deriving Repr, DecidableEq, BEq

structure RateLaw where
  kind : RateLawKind := .expression
  expression : Expr
  deriving Repr

end BNG
