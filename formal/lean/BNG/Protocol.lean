import BNG.Model

namespace BNG

/-!
# Typed simulation protocol

The semantic model and the commands that *use* it are different objects.
Keeping the protocol typed prevents backends from repeatedly parsing action
names and string-valued option dictionaries.

This is intentionally a semantic command vocabulary, not a CLI grammar.
Unsupported legacy actions remain explicit instead of becoming magic strings.
-/

inductive SimulationMethod where
  | ode
  | ssa
  | nf
  | pla
  | psa
  deriving Repr, DecidableEq, BEq

structure TimeCourseRequest where
  method : SimulationMethod
  tEnd : Float
  nSteps : Nat
  seed : Option Nat := none
  deriving Repr

inductive ExportKind where
  | bngl
  | net
  | sbml
  | sbmlMulti
  | bngir
  deriving Repr, DecidableEq, BEq

inductive TypedProtocolAction where
  | generateNetwork (maxIterations : Option Nat := none) (maxSpecies : Option Nat := none)
  | simulate (request : TimeCourseRequest)
  | setParameter (id : ParameterId) (value : Float)
  | setConcentration (species : Pattern) (value : Float)
  | parameterScan (id : ParameterId) (values : List Float) (request : TimeCourseRequest)
  | saveState (name : String)
  | resetState (name : Option String := none)
  | exportModel (kind : ExportKind) (path : String)
  | legacyUnsupported (name : String) (arguments : List (String × String))
  deriving Repr

structure TypedSimulationProtocol where
  actions : List TypedProtocolAction := []
  deriving Repr

/-- Commands whose meaning is deliberately not hidden in the legacy escape hatch. -/
def TypedProtocolAction.structurallySupported : TypedProtocolAction → Bool
  | .legacyUnsupported _ _ => false
  | _ => true

/-- A protocol is fully typed only when no legacy escape hatch remains. -/
def TypedSimulationProtocol.fullyTyped (p : TypedSimulationProtocol) : Bool :=
  p.actions.all TypedProtocolAction.structurallySupported

/-- A tiny bookkeeping state for protocol-level reference interpretation. -/
structure ProtocolState where
  time : Float := 0.0
  savedStates : List String := []
  exportedPaths : List String := []
  deriving Repr

/--
Reference bookkeeping effects.

Simulation itself belongs to the ODE/CTMC/NF semantics, so this interpreter
only records protocol-visible effects and rejects legacy-unsupported actions.
-/
def executeProtocolAction? (state : ProtocolState) : TypedProtocolAction → Option ProtocolState
  | .generateNetwork _ _ => some state
  | .simulate request => some { state with time := request.tEnd }
  | .setParameter _ _ => some state
  | .setConcentration _ _ => some state
  | .parameterScan _ _ request => some { state with time := request.tEnd }
  | .saveState name => some { state with savedStates := name :: state.savedStates }
  | .resetState _ => some { state with time := 0.0 }
  | .exportModel _ path => some { state with exportedPaths := path :: state.exportedPaths }
  | .legacyUnsupported _ _ => none

/-- Execute a typed protocol sequentially. -/
def executeProtocol? : List TypedProtocolAction → ProtocolState → Option ProtocolState
  | [], state => some state
  | action :: rest, state =>
      match executeProtocolAction? state action with
      | none => none
      | some next => executeProtocol? rest next

end BNG
