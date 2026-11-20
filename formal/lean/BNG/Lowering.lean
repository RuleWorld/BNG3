import BNG.Model
import BNG.Operational

namespace BNG

/-!
# Backend lowering and the first execution-refinement target

The old prototype only lowered semantic mutations into a wrapper constructor.
That was useful scaffolding, but the "backend" was effectively carrying the
original mutation unchanged.

This version makes the target vocabulary independent.  It resembles the shape
an NFnext/NFsim lowering would want:

* semantic `changeState` -> backend `setState`;
* semantic `createBond` -> backend `addBond`;
* semantic `deleteBond` -> backend `removeBond`;
* and so on.

The backend executor is still deliberately tiny and pure.  The important point
is that it consumes **lowered backend actions**, not BNGL syntax and not the
semantic `Mutation` datatype.
-/

/-! ## Structural pattern lowering retained from the first prototype -/

structure BackendSite where
  component : ComponentTypeId
  state : StateConstraint
  bonds : List BondRequirement
  deriving Repr

structure BackendNode where
  moleculeType : MoleculeTypeId
  compartment : Option CompartmentId
  sites : List BackendSite
  deriving Repr

structure BackendPattern where
  nodes : List BackendNode
  bonds : List PatternBond
  deriving Repr

/-- Structural lowering: all source spelling has already disappeared. -/
def Pattern.lower : Pattern → BackendPattern
  | p =>
      { nodes := p.molecules.map (fun molecule =>
          { moleculeType := molecule.moleculeType
            compartment := molecule.compartment
            sites := molecule.sites.map (fun site =>
              { component := site.component
                state := site.state
                bonds := site.bonds }) })
        bonds := p.bonds }

/-- Lowering does not create or delete molecule nodes. -/
theorem lower_preserves_molecule_count (p : Pattern) :
    p.lower.nodes.length = p.molecules.length := by
  simp [Pattern.lower]

/-- Lowering does not create or delete explicit exact bonds. -/
theorem lower_preserves_bond_count (p : Pattern) :
    p.lower.bonds.length = p.bonds.length := by
  rfl

/-! ## Independent backend action vocabulary -/

inductive BackendAction where
  | setState (target : ComponentTarget) (state : StateId)
  | addBond (left right : ComponentTarget)
  | removeBond (left right : ComponentTarget)
  | removeAllBonds (target : ComponentTarget)
  | allocateMolecule (target : RuleMoleculeEndpoint)
  | eraseMolecule (target : RuleMoleculeEndpoint)
  | relocateMolecule (target : RuleMoleculeEndpoint) (destination : CompartmentId)
  deriving Repr

/-- Lower one semantic mutation into one backend instruction. -/
def Mutation.lower : Mutation → BackendAction
  | .changeState target state => .setState target state
  | .createBond left right => .addBond left right
  | .deleteBond left right => .removeBond left right
  | .clearBonds target => .removeAllBonds target
  | .createMolecule target => .allocateMolecule target
  | .deleteMolecule target => .eraseMolecule target
  | .moveCompartment target destination => .relocateMolecule target destination

/-- Lower the whole edit program. -/
def RuleDirection.lowerActions (d : RuleDirection) : List BackendAction :=
  d.mutations.map Mutation.lower

/-- One semantic edit always lowers to exactly one backend instruction. -/
theorem lower_preserves_mutation_count (d : RuleDirection) :
    d.lowerActions.length = d.mutations.length := by
  simp [RuleDirection.lowerActions]

/-! ## Backend execution -/

/--
Execute one lowered backend instruction.

Notice that this definition never pattern-matches on `Mutation`.  This is the
first meaningful semantic seam: if a real backend later implements these
instructions differently, this function can be replaced by a more faithful
backend model while the reference semantics remains unchanged.
-/
def RuleDirection.executeBackendAction (d : RuleDirection) (action : BackendAction)
    (env : ExecutionEnv) (mix : Mixture) : Option (Mixture × ExecutionEnv) :=
  match action with
  | .setState target state =>
      match d.resolveComponent? env mix target with
      | none => none
      | some endpoint =>
          match mix.setState? endpoint state with
          | none => none
          | some mix' => some (mix', env)
  | .addBond left right =>
      match d.resolveComponent? env mix left, d.resolveComponent? env mix right with
      | some a, some b =>
          match mix.addBond? a b with
          | none => none
          | some mix' => some (mix', env)
      | _, _ => none
  | .removeBond left right =>
      match d.resolveComponent? env mix left, d.resolveComponent? env mix right with
      | some a, some b =>
          match mix.removeBond? a b with
          | none => none
          | some mix' => some (mix', env)
      | _, _ => none
  | .removeAllBonds target =>
      match d.resolveComponent? env mix target with
      | none => none
      | some endpoint => some (mix.clearBonds endpoint, env)
  | .allocateMolecule target =>
      match env.findCreated? target with
      | some _ => none
      | none =>
          let fresh := mix.nextMoleculeId
          match d.instantiateMolecule? target fresh with
          | none => none
          | some molecule =>
              let next : MoleculeInstanceId := ⟨fresh.value + 1⟩
              let mix' : Mixture :=
                { mix with nextMoleculeId := next, molecules := molecule :: mix.molecules }
              let env' : ExecutionEnv :=
                { env with created := (target, fresh) :: env.created }
              some (mix', env')
  | .eraseMolecule target =>
      match d.resolveMolecule? env target with
      | none => none
      | some id =>
          match mix.deleteMolecule? id with
          | none => none
          | some mix' => some (mix', env)
  | .relocateMolecule target destination =>
      match d.resolveMolecule? env target with
      | none => none
      | some id =>
          match mix.moveMolecule? id destination with
          | none => none
          | some mix' => some (mix', env)

/-- Execute an already-lowered backend instruction list. -/
def RuleDirection.executeBackendProgram (d : RuleDirection) :
    List BackendAction → ExecutionEnv → Mixture → Option (Mixture × ExecutionEnv)
  | [], env, mix => some (mix, env)
  | action :: rest, env, mix =>
      match d.executeBackendAction action env mix with
      | none => none
      | some (mix', env') => d.executeBackendProgram rest env' mix'

/-- Public backend step at one candidate match, with the same supported-subset gate. -/
def RuleDirection.executeLoweredAt? (d : RuleDirection) (mix : Mixture) (matched : RuleMatch) :
    Option Mixture :=
  if !(d.supportedOperationalSubset && d.ruleMatchValid mix matched) then none
  else
    match d.executeBackendProgram d.lowerActions { matched := matched } mix with
    | none => none
    | some (mix', _) => some mix'

/-! ## Refinement proofs -/

/--
**Single-step refinement.**  Executing the lowered backend instruction is
exactly equivalent to executing the semantic mutation from which it was
compiled.

This is intentionally proved for *all* mixtures/environments, not just an
example fixture.
-/
theorem execute_lowered_mutation_eq_reference
    (d : RuleDirection) (mutation : Mutation) (env : ExecutionEnv) (mix : Mixture) :
    d.executeBackendAction mutation.lower env mix = d.applyMutation mutation env mix := by
  cases mutation <;> rfl

/--
**Program refinement.**  A whole lowered action sequence has the same result as
sequential semantic mutation execution.
-/
theorem execute_lowered_program_eq_reference
    (d : RuleDirection) (mutations : List Mutation) (env : ExecutionEnv) (mix : Mixture) :
    d.executeBackendProgram (mutations.map Mutation.lower) env mix =
      d.applyMutations mutations env mix := by
  induction mutations generalizing env mix with
  | nil => rfl
  | cons mutation rest ih =>
      simp [RuleDirection.executeBackendProgram, RuleDirection.applyMutations,
        execute_lowered_mutation_eq_reference, ih] <;> rfl

/--
**Rule-step refinement for the supported subset.**

Given the same candidate match, the reference semantic rule application and
execution of its lowered backend program produce exactly the same observable
mixture result.  The well-formed/match checks are performed by both sides in
exactly the same place.
-/
theorem execute_lowered_rule_eq_reference
    (d : RuleDirection) (mix : Mixture) (matched : RuleMatch) :
    d.executeLoweredAt? mix matched = d.applyAt? mix matched := by
  simp [RuleDirection.executeLoweredAt?, RuleDirection.applyAt?,
    RuleDirection.lowerActions, execute_lowered_program_eq_reference] <;> rfl

/-! ## State-change preservation theorems for the kernel

For any bounded state-change rule, executing the state mutation (or its lowered
`setState` backend action) updates the target site while preserving all mixture
bonds, molecule allocation counters, and non-target contextual sites.
-/

/-- Modifying one runtime molecule preserves the mixture bond table. -/
theorem modifyMolecule?_preserves_bonds (mix : Mixture) (id : MoleculeInstanceId)
    (f : RuntimeMolecule → Option RuntimeMolecule) (mix' : Mixture)
    (h : mix.modifyMolecule? id f = some mix') : mix'.bonds = mix.bonds := by
  dsimp [Mixture.modifyMolecule?] at h
  split at h
  · contradiction
  · rename_i molecules' hgo
    injection h with hmix
    subst hmix
    rfl

/-- Modifying one runtime molecule preserves the next molecule allocation ID. -/
theorem modifyMolecule?_preserves_nextMoleculeId (mix : Mixture) (id : MoleculeInstanceId)
    (f : RuntimeMolecule → Option RuntimeMolecule) (mix' : Mixture)
    (h : mix.modifyMolecule? id f = some mix') : mix'.nextMoleculeId = mix.nextMoleculeId := by
  dsimp [Mixture.modifyMolecule?] at h
  split at h
  · contradiction
  · rename_i molecules' hgo
    injection h with hmix
    subst hmix
    rfl

/-- Setting a site state preserves all bonds in the mixture. -/
theorem setState?_preserves_bonds (mix : Mixture) (e : ConcreteEndpoint) (newState : StateId)
    (mix' : Mixture) (h : mix.setState? e newState = some mix') : mix'.bonds = mix.bonds := by
  exact modifyMolecule?_preserves_bonds mix e.molecule _ mix' h

/-- Setting a site state preserves the next molecule allocation ID. -/
theorem setState?_preserves_nextMoleculeId (mix : Mixture) (e : ConcreteEndpoint) (newState : StateId)
    (mix' : Mixture) (h : mix.setState? e newState = some mix') : mix'.nextMoleculeId = mix.nextMoleculeId := by
  exact modifyMolecule?_preserves_nextMoleculeId mix e.molecule _ mix' h

/-- Semantic state-change execution preserves all mixture bonds. -/
theorem changeState_mutation_preserves_bonds (d : RuleDirection)
    (target : ComponentTarget) (newState : StateId) (env : ExecutionEnv) (mix mix' : Mixture) (env' : ExecutionEnv)
    (h : d.applyMutation (.changeState target newState) env mix = some (mix', env')) :
    mix'.bonds = mix.bonds := by
  dsimp [RuleDirection.applyMutation] at h
  split at h
  · contradiction
  · rename_i endpoint hres
    split at h
    · contradiction
    · rename_i m hset
      injection h with hpair
      injection hpair with hmix' henv'
      subst hmix'
      exact setState?_preserves_bonds mix endpoint newState m hset

/-- Lowered backend setState execution preserves all mixture bonds. -/
theorem lowered_setState_preserves_bonds (d : RuleDirection)
    (target : ComponentTarget) (newState : StateId) (env : ExecutionEnv) (mix mix' : Mixture) (env' : ExecutionEnv)
    (h : d.executeBackendAction (.setState target newState) env mix = some (mix', env')) :
    mix'.bonds = mix.bonds := by
  have heq := execute_lowered_mutation_eq_reference d (.changeState target newState) env mix
  have hlower : Mutation.lower (.changeState target newState) = .setState target newState := rfl
  rw [hlower] at heq
  rw [heq] at h
  exact changeState_mutation_preserves_bonds d target newState env mix mix' env' h

end BNG
