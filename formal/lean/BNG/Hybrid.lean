import BNG.Operational
import BNG.Model

namespace BNG

/-!
# Safe particle → population conversion

Hybrid particle/population simulation is semantically dangerous if a
population map is allowed to match only a subgraph of a larger complex.  The
reference rule here is conservative:

> a particle pattern may collapse into a population count only when one of its
> embeddings covers **exactly one entire connected complex**.

That prevents a map for `A(x)` from silently consuming the A molecule inside
`A(x!1).B(y!1)` while leaving B behind.
-/

structure PopulationCount where
  moleculeType : MoleculeTypeId
  count : Nat
  deriving Repr, DecidableEq, BEq

structure HybridMixture where
  particles : Mixture
  populations : List PopulationCount := []
  deriving Repr

/-- Does this embedding cover the entire connected complex it touches? -/
def embeddingCoversWholeComplex (mix : Mixture) (e : Embedding) : Bool :=
  match e.range with
  | [] => false
  | first :: _ => sameMoleculeIdSet e.range (mix.connectedFrom first)

/-- Whole-complex matches eligible for particle→population conversion. -/
def PopulationMapDecl.convertibleMatches (decl : PopulationMapDecl)
    (mix : Mixture) : List Embedding :=
  decl.particlePattern.matches mix |>.filter (embeddingCoversWholeComplex mix)

/-- Increment one population counter or insert a new one. -/
def incrementPopulation : MoleculeTypeId → List PopulationCount → List PopulationCount
  | wanted, [] => [{ moleculeType := wanted, count := 1 }]
  | wanted, x :: xs =>
      if x.moleculeType == wanted then { x with count := x.count + 1 } :: xs
      else x :: incrementPopulation wanted xs

/-- Convert one exact whole-complex embedding. -/
def PopulationMapDecl.convertAt? (decl : PopulationMapDecl)
    (hybrid : HybridMixture) (embedding : Embedding) : Option HybridMixture :=
  if !(decl.particlePattern.embeddingMatches hybrid.particles embedding &&
       embeddingCoversWholeComplex hybrid.particles embedding) then none
  else
    match embedding.range with
    | [] => none
    | first :: _ =>
        match hybrid.particles.deleteComplex? first with
        | none => none
        | some particles' =>
            some {
              particles := particles'
              populations := incrementPopulation decl.populationType hybrid.populations }

/--
Safety property encoded directly in the API: partial-complex embeddings cannot
be converted because `convertAt?` checks `embeddingCoversWholeComplex` first.
-/
def PopulationMapDecl.safeConversionOnly (decl : PopulationMapDecl)
    (hybrid : HybridMixture) (embedding : Embedding) : Bool :=
  match decl.convertAt? hybrid embedding with
  | none => true
  | some _ => embeddingCoversWholeComplex hybrid.particles embedding

end BNG
