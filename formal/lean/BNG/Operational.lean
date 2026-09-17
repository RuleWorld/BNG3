import BNG.Graph

namespace BNG

/-!
# Executable pattern matching and rule application

This file is the first genuinely operational part of the formalization.
Previously we could say what a compiled BNGL pattern *contained*.  Here we say
what it **means to match that pattern against a concrete molecular mixture** and
what it **means to apply the compiled mutations of a rule**.

ELI15 picture:

```text
pattern:   A(x~u) + B(y)
                 │
                 │ find concrete molecules that satisfy the constraints
                 ▼
mixture:   A#7(x~u)   B#12(y)   C#20(...)
                 │
                 │ compiled mutations
                 ▼
result:    A#7(x~p!1).B#12(y!1)   C#20(...)
```

The implementation is intentionally brute-force and finite.  NFsim should use
fast indexes; the reference semantics should instead be obvious enough that we
can prove things about it.
-/

/--
A candidate graph embedding maps each molecule occurrence in one semantic
pattern to one concrete molecule instance in the mixture.
-/
structure Embedding where
  moleculeMap : List (PatternMoleculeId × MoleculeInstanceId) := []
  deriving Repr

/-- Look up the concrete molecule assigned to one pattern-local occurrence. -/
def Embedding.lookup? (e : Embedding) (id : PatternMoleculeId) : Option MoleculeInstanceId :=
  let rec go : List (PatternMoleculeId × MoleculeInstanceId) → Option MoleculeInstanceId
    | [] => none
    | pair :: rest =>
        if pair.1 == id then some pair.2 else go rest
  go e.moleculeMap

/-- Runtime molecule IDs selected by this embedding. -/
def Embedding.range (e : Embedding) : List MoleculeInstanceId :=
  e.moleculeMap.map Prod.snd

/-- Pattern occurrence IDs present in this embedding. -/
def Embedding.domain (e : Embedding) : List PatternMoleculeId :=
  e.moleculeMap.map Prod.fst

/-- Convert a pattern endpoint to a concrete endpoint under an embedding. -/
def Pattern.resolveEndpoint? (p : Pattern) (e : Embedding)
    (endpoint : PatternEndpoint) : Option ConcreteEndpoint :=
  match p.findMolecule? endpoint.molecule, e.lookup? endpoint.molecule with
  | some pm, some runtimeId =>
      match pm.findSite? endpoint.site with
      | none => none
      | some site => some { molecule := runtimeId, component := site.component }
  | _, _ => none

/-- Does a concrete site's internal state satisfy the pattern constraint? -/
def stateMatches (constraint : StateConstraint) (actual : Option StateId) : Bool :=
  match constraint with
  | .any => true
  | .exact wanted =>
      match actual with
      | some got => got == wanted
      | none => false
  | .oneOf allowed =>
      match actual with
      | some got => allowed.contains got
      | none => false

/--
Check one exact bond-group requirement.

The group ID is pattern-local.  We therefore look up the `PatternBond` carrying
that ID, resolve both endpoints through the embedding, and ask whether that
concrete edge exists in the mixture.
-/
def Pattern.exactBondMatches (p : Pattern) (mix : Mixture) (e : Embedding)
    (group : BondGroupId) : Bool :=
  match p.bonds.find? (fun bond => bond.group == group) with
  | none => false
  | some bond =>
      match p.resolveEndpoint? e bond.a, p.resolveEndpoint? e bond.b with
      | some a, some b => mix.hasBond a b
      | _, _ => false

/-- Check one site's bond predicates after its concrete endpoint is known. -/
def Pattern.siteBondsMatch (p : Pattern) (mix : Mixture) (e : Embedding)
    (actualEndpoint : ConcreteEndpoint) (requirements : List BondRequirement) : Bool :=
  requirements.all (fun requirement =>
    match requirement with
    | .free => mix.endpointFree actualEndpoint
    | .bound => mix.endpointBound actualEndpoint
    | .any => true
    | .exact group => p.exactBondMatches mix e group)

/-- Check all state/bond constraints on one pattern molecule occurrence. -/
def Pattern.sitesMatch (p : Pattern) (mix : Mixture) (e : Embedding)
    (pm : PatternMolecule) (actual : RuntimeMolecule) : Bool :=
  pm.sites.all (fun ps =>
    match actual.findSite? ps.component with
    | none => false
    | some site =>
        let endpoint : ConcreteEndpoint :=
          { molecule := actual.id, component := ps.component }
        stateMatches ps.state site.state && p.siteBondsMatch mix e endpoint ps.bonds)

/-- Does a molecule-level `!+` / `!?` requirement hold? -/
def moleculeBondMatches (mix : Mixture) (id : MoleculeInstanceId) :
    Option MoleculeBondRequirement → Bool
  | none => true
  | some .any => true
  | some .hasBond => mix.moleculeHasBond id

/--
Check whether a *candidate* embedding really is a match.

This is the semantic heart of pattern matching.  It checks:

1. every pattern molecule has exactly one mapping entry;
2. two pattern molecules cannot map to the same concrete molecule;
3. molecule types agree;
4. explicit compartments agree;
5. all mentioned site-state and bond constraints hold;
6. explicit pattern bonds exist in the concrete graph.
-/
def Pattern.embeddingMatches (p : Pattern) (mix : Mixture) (e : Embedding) : Bool :=
  let expectedDomain := p.molecules.map (fun m => m.occurrence)
  let domainOK :=
    allUnique e.domain &&
    e.domain.length == expectedDomain.length &&
    allContained expectedDomain e.domain &&
    allContained e.domain expectedDomain
  let injective := allUnique e.range
  let moleculesOK := p.molecules.all (fun pm =>
    match e.lookup? pm.occurrence with
    | none => false
    | some runtimeId =>
        match mix.findMolecule? runtimeId with
        | none => false
        | some actual =>
            let typeOK := actual.moleculeType == pm.moleculeType
            let compartmentOK :=
              match pm.compartment with
              | none => true
              | some wanted => actual.compartment == some wanted
            typeOK && compartmentOK &&
              moleculeBondMatches mix actual.id pm.moleculeBond &&
              p.sitesMatch mix e pm actual)
  let explicitBondsOK := p.bonds.all (fun bond =>
    match p.resolveEndpoint? e bond.a, p.resolveEndpoint? e bond.b with
    | some a, some b => mix.hasBond a b
    | _, _ => false)
  let sameComplexOK := e.range.all (fun a => e.range.all (fun b => mix.sameComplex a b))
  domainOK && injective && moleculesOK && explicitBondsOK && sameComplexOK

/--
Generate every raw molecule assignment for the pattern.

This intentionally starts broad (every pattern molecule can choose every
concrete molecule) and lets `embeddingMatches` reject wrong types, reused
molecules, states, bonds, etc.  It is exponentially slow and therefore ideal as
a tiny reference oracle but terrible as a production matcher.
-/
def Pattern.candidateEmbeddings (p : Pattern) (mix : Mixture) : List Embedding :=
  let rec build : List PatternMolecule → List Embedding
    | [] => [{ moleculeMap := [] }]
    | pm :: rest =>
        let tails := build rest
        mix.molecules.flatMap (fun actual =>
          tails.map (fun tail =>
            { moleculeMap := (pm.occurrence, actual.id) :: tail.moleculeMap }))
  build p.molecules

/-- Enumerate all valid embeddings of one semantic pattern in the mixture. -/
def Pattern.matches (p : Pattern) (mix : Mixture) : List Embedding :=
  p.candidateEmbeddings mix |>.filter (fun e => p.embeddingMatches mix e)

/--
A whole rule has one embedding per top-level reactant pattern.
The list index is therefore the reactant pattern index used by
`RuleMoleculeEndpoint.pattern`.
-/
structure RuleMatch where
  embeddings : List Embedding := []
  deriving Repr

/-- All concrete molecule IDs consumed by this candidate rule match. -/
def RuleMatch.moleculeIds (m : RuleMatch) : List MoleculeInstanceId :=
  m.embeddings.flatMap Embedding.range

/-- Retrieve the embedding for one top-level reactant pattern. -/
def RuleMatch.embeddingAt? (m : RuleMatch) (index : Nat) : Option Embedding :=
  listGet? m.embeddings index

/-- Check one candidate whole-rule match against the reactant pattern list. -/
def RuleDirection.ruleMatchValid (d : RuleDirection) (mix : Mixture) (m : RuleMatch) : Bool :=
  let lengthOK := m.embeddings.length == d.reactants.length
  let noOverlap := allUnique m.moleculeIds
  let rec pairsMatch : List Pattern → List Embedding → Bool
    | [], [] => true
    | p :: ps, e :: es => p.embeddingMatches mix e && pairsMatch ps es
    | _, _ => false
  let rec distinctComplexes : List Embedding → Bool
    | [] => true
    | e :: rest =>
        let separate := rest.all (fun other =>
          e.range.all (fun a => other.range.all (fun b => !(mix.sameComplex a b))))
        separate && distinctComplexes rest
  lengthOK && noOverlap && pairsMatch d.reactants m.embeddings && distinctComplexes m.embeddings

/-- Brute-force enumeration of complete, non-overlapping reactant matches. -/
def RuleDirection.matches (d : RuleDirection) (mix : Mixture) : List RuleMatch :=
  let rec combine : List Pattern → List RuleMatch
    | [] => [{ embeddings := [] }]
    | p :: rest =>
        let tails := combine rest
        p.matches mix |>.flatMap (fun here =>
          tails.map (fun tail => { embeddings := here :: tail.embeddings }))
  combine d.reactants |>.filter (fun candidate => d.ruleMatchValid mix candidate)

/-! ## Resolving compiled rule addresses into concrete runtime addresses -/

/--
Execution environment created from a `RuleMatch`.

Product-side molecules that correspond to existing reactants are resolved
through `RuleDirection.moleculeMap`.  Truly new product molecules are recorded
in `created` as `.createMolecule` mutations allocate fresh IDs.
-/
structure ExecutionEnv where
  matched : RuleMatch
  created : List (RuleMoleculeEndpoint × MoleculeInstanceId) := []
  deriving Repr

/-- Look up a newly-created product molecule. -/
def ExecutionEnv.findCreated? (env : ExecutionEnv) (endpoint : RuleMoleculeEndpoint) :
    Option MoleculeInstanceId :=
  let rec go : List (RuleMoleculeEndpoint × MoleculeInstanceId) → Option MoleculeInstanceId
    | [] => none
    | pair :: rest => if pair.1 == endpoint then some pair.2 else go rest
  go env.created

/-- Resolve a reactant-side rule molecule endpoint through the selected match. -/
def ExecutionEnv.resolveReactant? (env : ExecutionEnv) (endpoint : RuleMoleculeEndpoint) :
    Option MoleculeInstanceId :=
  if !(endpoint.side == PatternSide.reactant) then none
  else
    match env.matched.embeddingAt? endpoint.pattern with
    | none => none
    | some embedding => embedding.lookup? endpoint.molecule

/-- Find the reactant endpoint corresponding to one product endpoint. -/
def RuleDirection.productSource? (d : RuleDirection) (product : RuleMoleculeEndpoint) :
    Option RuleMoleculeEndpoint :=
  let rec go : List MoleculeCorrespondence → Option RuleMoleculeEndpoint
    | [] => none
    | item :: rest => if item.product == product then some item.reactant else go rest
  go d.moleculeMap

/-- Resolve either side of the compiled arrow to a concrete molecule ID. -/
def RuleDirection.resolveMolecule? (d : RuleDirection) (env : ExecutionEnv)
    (endpoint : RuleMoleculeEndpoint) : Option MoleculeInstanceId :=
  match endpoint.side with
  | .reactant => env.resolveReactant? endpoint
  | .product =>
      match env.findCreated? endpoint with
      | some id => some id
      | none =>
          match d.productSource? endpoint with
          | none => none
          | some reactant => env.resolveReactant? reactant

/-- Resolve a compiled component target to one concrete site endpoint. -/
def RuleDirection.resolveComponent? (d : RuleDirection) (env : ExecutionEnv)
    (mix : Mixture) (target : ComponentTarget) : Option ConcreteEndpoint :=
  match d.componentContext? target with
  | none => none
  | some (_, component) =>
      let moleculeEndpoint :=
        match target with
        | .site site => site.molecule
        | .byType molecule _ => molecule
      match d.resolveMolecule? env moleculeEndpoint with
      | none => none
      | some runtimeId =>
          let concrete : ConcreteEndpoint :=
            { molecule := runtimeId, component := component }
          if mix.hasEndpoint concrete then some concrete else none

/-! ## Mutation execution -/

/--
Turn a product-pattern site constraint into a concrete initial state.

For creation we need one actual state, not a set of possibilities.  Therefore
`oneOf [s]` is constructible but `oneOf [s1,s2]` is not yet supported.  `.any`
creates a state-less/unselected runtime site.
-/
def initialState? : StateConstraint → Option (Option StateId)
  | .any => some none
  | .exact state => some (some state)
  | .oneOf [state] => some (some state)
  | .oneOf _ => none

/-- Convert listed product sites into concrete sites for a newly-created molecule. -/
def instantiateSites? : List PatternSite → Option (List RuntimeSite)
  | [] => some []
  | site :: rest =>
      match initialState? site.state, instantiateSites? rest with
      | some state, some tail =>
          some ({ component := site.component, state := state } :: tail)
      | _, _ => none

/-- Instantiate the semantic product molecule named by a creation mutation. -/
def RuleDirection.instantiateMolecule? (d : RuleDirection) (target : RuleMoleculeEndpoint)
    (id : MoleculeInstanceId) : Option RuntimeMolecule :=
  if !(target.side == PatternSide.product) then none
  else
    match d.moleculeAt? target with
    | none => none
    | some productMolecule =>
        match instantiateSites? productMolecule.sites with
        | none => none
        | some sites =>
            some {
              id := id
              moleculeType := productMolecule.moleculeType
              compartment := productMolecule.compartment
              sites := sites }

/--
Apply one semantic mutation.

Failures are explicit (`none`).  A compiled backend should not silently turn an
invalid edit into a no-op.  This makes the reference semantics useful for
parity testing.
-/
def RuleDirection.applyMutation (d : RuleDirection) (mutation : Mutation)
    (env : ExecutionEnv) (mix : Mixture) : Option (Mixture × ExecutionEnv) :=
  match mutation with
  | .changeState target newState =>
      match d.resolveComponent? env mix target with
      | none => none
      | some endpoint =>
          match mix.setState? endpoint newState with
          | none => none
          | some mix' => some (mix', env)
  | .createBond left right =>
      match d.resolveComponent? env mix left, d.resolveComponent? env mix right with
      | some a, some b =>
          match mix.addBond? a b with
          | none => none
          | some mix' => some (mix', env)
      | _, _ => none
  | .deleteBond left right =>
      match d.resolveComponent? env mix left, d.resolveComponent? env mix right with
      | some a, some b =>
          match mix.removeBond? a b with
          | none => none
          | some mix' => some (mix', env)
      | _, _ => none
  | .clearBonds target =>
      match d.resolveComponent? env mix target with
      | none => none
      | some endpoint => some (mix.clearBonds endpoint, env)
  | .createMolecule target =>
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
  | .deleteMolecule target =>
      match d.resolveMolecule? env target with
      | none => none
      | some id =>
          match mix.deleteMolecule? id with
          | none => none
          | some mix' => some (mix', env)
  | .moveCompartment target destination =>
      match d.resolveMolecule? env target with
      | none => none
      | some id =>
          match mix.moveMolecule? id destination with
          | none => none
          | some mix' => some (mix', env)

/-- Sequentially execute the compiled mutation list. -/
def RuleDirection.applyMutations (d : RuleDirection) :
    List Mutation → ExecutionEnv → Mixture → Option (Mixture × ExecutionEnv)
  | [], env, mix => some (mix, env)
  | mutation :: rest, env, mix =>
      match d.applyMutation mutation env mix with
      | none => none
      | some (mix', env') => d.applyMutations rest env' mix'

/--
Feature gate for the theorem-backed subset.

Filters and several modifiers affect *which match/rate* is legal rather than the
local graph edit itself.  They are intentionally outside this first refinement
theorem.  `matchOnce`, `totalRate`, and `priority` are scheduling/rate concerns;
`deleteMolecules` and `moveConnected` change graph-edit semantics.
-/
def RuleDirection.supportedOperationalSubset (d : RuleDirection) : Bool :=
  d.filters.isEmpty && d.localScopes.isEmpty && d.modifiers.isEmpty

/--
Apply a rule direction to a user-supplied whole-rule match.

This is the public reference step for the current supported subset.  It first
checks that the rule feature set is covered and that the candidate really
matches the reactants, then executes the compiled mutations.
-/
def RuleDirection.applyAt? (d : RuleDirection) (mix : Mixture) (matched : RuleMatch) :
    Option Mixture :=
  if !(d.supportedOperationalSubset && d.ruleMatchValid mix matched) then none
  else
    match d.applyMutations d.mutations { matched := matched } mix with
    | none => none
    | some (mix', _) => some mix'

/-- Apply the direction at every currently valid match (reference oracle). -/
def RuleDirection.successors (d : RuleDirection) (mix : Mixture) : List Mixture :=
  d.matches mix |>.filterMap (fun matched => d.applyAt? mix matched)

end BNG
