import BNG.Network

namespace BNG

/-!
# Reference reaction-network edges

`Network.lean` answers the first question a network generator has to answer:

> "Which species exist after repeatedly applying the rules?"

That is not quite enough to describe a reaction network.  A reaction network
also remembers **which reactant species produced which product species through
which rule direction**.

This module records that information explicitly.

The implementation is intentionally slow and simple.  Runtime molecule IDs are
never used as species identities: reactants/products are converted to stable
indices in a species pool using the graph-isomorphism oracle from
`Species.lean`.

ELI15 picture:

```text
species pool
   0: A
   1: B
   2: A.B

reaction edge
   rule 7, forward
   [0, 1]  --->  [2]
```

The edge says *what happened*; the species pool says *what the numbered things
mean*.
-/

/-- Which compiled direction produced a network reaction. -/
inductive RuleDirectionKind where
  | forward
  | reverse
  deriving Repr, DecidableEq, BEq

/--
A reaction edge over a canonical species pool.

`reactants` and `products` contain species-pool indices.  Multiplicity is kept:
for `2 A -> A2`, the reactant list is `[iA, iA]`, not just `[iA]`.
-/
structure NetworkReaction where
  rule : ReactionRuleId
  direction : RuleDirectionKind
  reactants : List Nat
  products : List Nat
  deriving Repr, DecidableEq, BEq

/-- Find the first species-pool entry graph-isomorphic to `candidate`. -/
def speciesIndex? (pool : List Mixture) (candidate : Mixture) : Option Nat :=
  let rec go : Nat -> List Mixture -> Option Nat
    | _, [] => none
    | i, species :: rest =>
        if species.isomorphicSpecies candidate then some i
        else go (i + 1) rest
  go 0 pool

/-- Resolve a list of concrete species into species-pool indices. -/
def speciesIndices? (pool : List Mixture) (species : List Mixture) : Option (List Nat) :=
  species.mapM (speciesIndex? pool)

/--
One concrete firing result before species indices are assigned.

Keeping this intermediate object makes the two correctness questions separate:

1. did the rule fire correctly on these concrete reactants?
2. did canonical species indexing preserve the resulting chemistry?
-/
structure ConcreteNetworkReaction where
  reactants : List Mixture
  products : List Mixture
  deriving Repr

/--
Enumerate concrete reactions for one compiled direction from a species pool.

This uses the exact same pool-combination policy as `networkProducts`:
one selected species per top-level reactant, cloned into disjoint complexes,
then matched/fired using the extended reference semantics.
-/
def RuleDirection.concreteNetworkReactions (d : RuleDirection)
    (pool : List Mixture) : List ConcreteNetworkReaction :=
  let arity := d.reactants.length
  chooseSpeciesTuples arity pool |>.flatMap (fun selected =>
    let reactantMix := disjointReactantMixture selected
    d.extendedSuccessors reactantMix |>.map (fun result =>
      { reactants := selected
        products := result.complexes }))

/--
Canonicalize one concrete firing into an indexed `NetworkReaction`.

The function fails rather than inventing a species identity if either a
reactant or product is absent from the supplied canonical pool.
-/
def ConcreteNetworkReaction.canonicalize? (rule : ReactionRuleId)
    (direction : RuleDirectionKind) (pool : List Mixture)
    (rxn : ConcreteNetworkReaction) : Option NetworkReaction := do
  let reactants <- speciesIndices? pool rxn.reactants
  let products <- speciesIndices? pool rxn.products
  pure { rule, direction, reactants, products }

/-- Add one reaction if an identical indexed edge is not already present. -/
def addReactionUnique (reactions : List NetworkReaction)
    (reaction : NetworkReaction) : List NetworkReaction :=
  if reactions.contains reaction then reactions else reactions ++ [reaction]

/-- Deduplicate a reaction list without changing first-seen order. -/
def deduplicateReactions (reactions : List NetworkReaction) : List NetworkReaction :=
  reactions.foldl addReactionUnique []

/-- Enumerate canonical network edges for one compiled rule. -/
def CompiledRule.networkReactions (rule : CompiledRule)
    (pool : List Mixture) : List NetworkReaction :=
  let forward := rule.forward.concreteNetworkReactions pool |>.filterMap (fun rxn =>
    rxn.canonicalize? rule.id RuleDirectionKind.forward pool)
  let reverse := match rule.reverse with
    | none => []
    | some d => d.concreteNetworkReactions pool |>.filterMap (fun rxn =>
        rxn.canonicalize? rule.id RuleDirectionKind.reverse pool)
  deduplicateReactions (forward ++ reverse)

/--
A finite reference network contains both canonical species and canonical
reaction edges.
-/
structure ReferenceReactionNetwork where
  species : List Mixture
  reactions : List NetworkReaction
  deriving Repr

/--
Build a bounded reference reaction network.

First close the species pool for `iterations` steps.  Then enumerate every
forward/reverse rule direction against that closed pool and record indexed
reaction edges.  This is intentionally correctness-first rather than fast.
-/
def CompiledModel.referenceReactionNetwork (model : CompiledModel)
    (iterations : Nat) (seedSpecies : List Mixture) : ReferenceReactionNetwork :=
  let pool := model.referenceNetwork iterations seedSpecies
  let reactions := model.rules.flatMap (fun rule => rule.networkReactions pool)
  { species := pool, reactions := deduplicateReactions reactions }

/-- Every indexed reactant/product of a well-indexed reaction lies in the pool. -/
def NetworkReaction.indicesInBounds (reaction : NetworkReaction)
    (pool : List Mixture) : Bool :=
  reaction.reactants.all (fun i => decide (i < pool.length)) &&
  reaction.products.all (fun i => decide (i < pool.length))

/-- Executable sanity check for a whole reference reaction network. -/
def ReferenceReactionNetwork.wellIndexed (network : ReferenceReactionNetwork) : Bool :=
  network.reactions.all (fun reaction => reaction.indicesInBounds network.species)

end BNG
