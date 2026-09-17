import BNG.Filters

namespace BNG

/-!
# Extended rule-step semantics

The original `applyAt?` intentionally proved a small local graph-edit subset.
This module extends the *reference* semantics with modifier-sensitive connected
operations, filters, and product validation.  It is a correctness oracle; no
claim is made that current NFsim/NFnext already refines all of it.
-/

/-- Does a rule direction request connected-component deletion? -/
def RuleDirection.hasDeleteMolecules (d : RuleDirection) : Bool :=
  d.modifiers.any (fun modifier =>
    match modifier with | .deleteMolecules => true | _ => false)

/-- Does a rule direction request connected-component transport? -/
def RuleDirection.hasMoveConnected (d : RuleDirection) : Bool :=
  d.modifiers.any (fun modifier =>
    match modifier with | .moveConnected => true | _ => false)

/-- Modifier-aware version of one semantic mutation. -/
def RuleDirection.applyMutationExtended (d : RuleDirection) (mutation : Mutation)
    (env : ExecutionEnv) (mix : Mixture) : Option (Mixture × ExecutionEnv) :=
  match mutation with
  | .deleteMolecule target =>
      match d.resolveMolecule? env target with
      | none => none
      | some id =>
          let result :=
            if d.hasDeleteMolecules then mix.deleteComplex? id else mix.deleteMolecule? id
          result.map (fun next => (next, env))
  | .moveCompartment target destination =>
      match d.resolveMolecule? env target with
      | none => none
      | some id =>
          let result :=
            if d.hasMoveConnected then mix.moveComplex? id destination
            else mix.moveMolecule? id destination
          result.map (fun next => (next, env))
  | other => d.applyMutation other env mix

/-- Sequential modifier-aware mutation execution. -/
def RuleDirection.applyMutationsExtended (d : RuleDirection) :
    List Mutation → ExecutionEnv → Mixture → Option (Mixture × ExecutionEnv)
  | [], env, mix => some (mix, env)
  | mutation :: rest, env, mix =>
      match d.applyMutationExtended mutation env mix with
      | none => none
      | some (next, env') => d.applyMutationsExtended rest env' next

/-- Build the concrete embedding implied by resolved product-side identities. -/
def RuleDirection.productEmbedding? (d : RuleDirection) (env : ExecutionEnv)
    (patternIndex : Nat) : Option Embedding :=
  match listGet? d.products patternIndex with
  | none => none
  | some p =>
      let rec go : List PatternMolecule → Option (List (PatternMoleculeId × MoleculeInstanceId))
        | [] => some []
        | molecule :: rest =>
            let endpoint : RuleMoleculeEndpoint := {
              side := .product, pattern := patternIndex, molecule := molecule.occurrence }
            match d.resolveMolecule? env endpoint, go rest with
            | some runtimeId, some tail => some ((molecule.occurrence, runtimeId) :: tail)
            | _, _ => none
      (go p.molecules).map (fun moleculeMap => { moleculeMap := moleculeMap })

/-- Every top-level product pattern matches the post-state under resolved identities. -/
def RuleDirection.productPatternsMatch (d : RuleDirection) (mix : Mixture)
    (env : ExecutionEnv) : Bool :=
  let rec go : Nat → List Pattern → Bool
    | _, [] => true
    | index, p :: rest =>
        match d.productEmbedding? env index with
        | none => false
        | some embedding => p.embeddingMatches mix embedding && go (index + 1) rest
  go 0 d.products

/-- Distinct top-level products (`+`) must end in distinct complexes. -/
def RuleDirection.productMolecularityValid (d : RuleDirection) (mix : Mixture)
    (env : ExecutionEnv) : Bool :=
  let embeddings :=
    let rec collect : Nat → List Pattern → Option (List Embedding)
      | _, [] => some []
      | index, _ :: rest =>
          match d.productEmbedding? env index, collect (index + 1) rest with
          | some e, some tail => some (e :: tail)
          | _, _ => none
    collect 0 d.products
  match embeddings with
  | none => false
  | some es =>
      let rec separated : List Embedding → Bool
        | [] => true
        | first :: rest =>
            let distinct := rest.all (fun other =>
              first.range.all (fun a => other.range.all (fun b => !(mix.sameComplex a b))))
            distinct && separated rest
      separated es

/--
Full reference step for the currently represented structural/filter semantics.

Order matters:

1. validate candidate reactant match;
2. evaluate reactant filters;
3. execute compiled mutations with connected modifiers;
4. require the declared product patterns/molecularity to actually hold;
5. evaluate product filters on the resulting complexes.
-/
def RuleDirection.applyAtExtended? (d : RuleDirection) (mix : Mixture)
    (matched : RuleMatch) : Option Mixture :=
  if !(d.ruleMatchValid mix matched && d.reactantFiltersPass mix matched) then none
  else
    match d.applyMutationsExtended d.mutations { matched := matched } mix with
    | none => none
    | some (result, env) =>
        if d.productPatternsMatch result env &&
           d.productMolecularityValid result env &&
           d.productFiltersPass result env
        then some result
        else none

/-- Enumerate all structurally/filter-valid rule outcomes. -/
def RuleDirection.extendedSuccessors (d : RuleDirection) (mix : Mixture) : List Mixture :=
  d.matches mix |>.filterMap (fun matched => d.applyAtExtended? mix matched)

end BNG
