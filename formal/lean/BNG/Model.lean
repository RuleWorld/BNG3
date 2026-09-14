import BNG.Rule

namespace BNG

/-!
# The compiled model contract

This is the Lean analogue of the proposed completed `bng::compile::CompiledModel`.
It is intentionally a *semantic* model: names remain for diagnostics and
round-tripping, while executable relationships use typed IDs and structured
values.
-/

structure FunctionDecl where
  id : FunctionId
  name : String
  arguments : List String := []
  expression : Expr
  deriving Repr

inductive ObservableKind where
  | molecules
  | species
  | counter
  | custom (name : String)
  deriving Repr

structure ObservableDecl where
  id : ObservableId
  name : String
  kind : ObservableKind
  patterns : List Pattern := []
  deriving Repr

structure SeedDecl where
  id : SeedSpeciesId
  pattern : Pattern
  amount : Expr
  constant : Bool := false
  compartment : Option CompartmentId := none
  deriving Repr

structure EnergyFactorDecl where
  id : EnergyPatternId
  pattern : Pattern
  energy : Expr
  deriving Repr

/--
A population map is represented structurally enough that a backend need not
re-parse the source rule.  The exact population-conversion execution semantics
remain a future proof target.
-/
structure PopulationMapDecl where
  id : PopulationMapId
  particlePattern : Pattern
  populationType : MoleculeTypeId
  arguments : List String := []
  deriving Repr

structure ModelMetadata where
  name : String := ""
  version : String := ""
  substanceUnits : String := ""
  options : List (String × String) := []
  deriving Repr

structure CompiledModel where
  metadata : ModelMetadata :=
    { name := "", version := "", substanceUnits := "", options := [] }
  parameters : List ParameterDecl := []
  moleculeTypes : List MoleculeType := []
  compartments : List CompartmentDecl := []
  seeds : List SeedDecl := []
  observables : List ObservableDecl := []
  functions : List FunctionDecl := []
  energyFactors : List EnergyFactorDecl := []
  populationMaps : List PopulationMapDecl := []
  rules : List CompiledRule := []
  deriving Repr

/-- The pattern-validation view of a compiled model. -/
def CompiledModel.signature (m : CompiledModel) : Signature :=
  { moleculeTypes := m.moleculeTypes, compartments := m.compartments }

/-- The expression-reference namespace of a compiled model. -/
def CompiledModel.exprScope (m : CompiledModel) : ExprScope :=
  { parameters := m.parameters.map (fun p => p.id)
    observables := m.observables.map (fun o => o.id)
    functions := m.functions.map (fun f => f.id) }

/-- IDs must be unique inside each declaration namespace. -/
def CompiledModel.idsUnique (m : CompiledModel) : Bool :=
  allUnique (m.parameters.map (fun x => x.id)) &&
  allUnique (m.moleculeTypes.map (fun x => x.id)) &&
  allUnique (m.compartments.map (fun x => x.id)) &&
  allUnique (m.seeds.map (fun x => x.id)) &&
  allUnique (m.observables.map (fun x => x.id)) &&
  allUnique (m.functions.map (fun x => x.id)) &&
  allUnique (m.energyFactors.map (fun x => x.id)) &&
  allUnique (m.populationMaps.map (fun x => x.id)) &&
  allUnique (m.rules.map (fun x => x.id))

/-- Validate the declaration graph and every compiled semantic object. -/
def CompiledModel.wellFormed (m : CompiledModel) : Bool :=
  let sig := m.signature
  let scope := m.exprScope
  let parametersOK := m.parameters.all (fun p => p.expression.referencesValid scope && p.expression.hasNoLocals)
  let compartmentsOK := m.compartments.all (fun c =>
    c.size.referencesValid scope && c.size.hasNoLocals &&
    match c.parent with
    | none => true
    | some parent => sig.hasCompartment parent)
  let functionsOK := m.functions.all (fun f => f.expression.referencesValid scope && f.expression.localsValid f.arguments)
  let observablesOK := m.observables.all (fun o => o.patterns.all (fun p => p.wellFormed sig))
  let seedsOK := m.seeds.all (fun s =>
    s.pattern.wellFormed sig &&
    s.amount.referencesValid scope && s.amount.hasNoLocals &&
    match s.compartment with
    | none => true
    | some c => sig.hasCompartment c)
  let energyOK := m.energyFactors.all (fun e =>
    e.pattern.wellFormed sig && e.energy.referencesValid scope && e.energy.hasNoLocals)
  let populationOK := m.populationMaps.all (fun p =>
    p.particlePattern.wellFormed sig &&
    match sig.findMoleculeType? p.populationType with
    | none => false
    | some mt => mt.population)
  let rulesOK := m.rules.all (fun r =>
    r.forward.wellFormed sig scope &&
    match r.reverse with
    | none => true
    | some reverse => reverse.wellFormed sig scope)
  m.idsUnique && parametersOK && compartmentsOK && functionsOK &&
    observablesOK && seedsOK && energyOK && populationOK && rulesOK

/--
Simulation actions are intentionally a separate seam, matching the proposed
`Document = CompiledModel + SimulationProtocol` architecture.
-/
structure ProtocolAction where
  name : String
  arguments : List (String × String) := []
  deriving Repr

structure SimulationProtocol where
  actions : List ProtocolAction := []
  deriving Repr

structure Document where
  model : CompiledModel
  protocol : SimulationProtocol := { actions := [] }
  deriving Repr

end BNG
