import BNG.Operational

namespace BNG

/-!
# Declarative matcher specification

`Pattern.embeddingMatches` is executable code.  For a meaningful verification
story we also want a specification that says *what a match is* without simply
calling that Boolean function again.

This file deliberately separates the two. `BNG.MatcherCorrectness` proves
soundness and completeness for the Lean reference enumerator against
`EmbeddingSpec`; native backends need their own correspondence proofs.
-/

/-- Exactly one mapping entry exists for a pattern molecule occurrence. -/
def mapsExactlyOnce (e : Embedding) (id : PatternMoleculeId) : Prop :=
  (e.moleculeMap.filter (fun pair => pair.1 == id)).length = 1

/-- No two distinct pattern molecules share a concrete molecule. -/
def InjectiveEmbedding (e : Embedding) : Prop :=
  allUnique e.range = true

/--
The embedding domain is exactly the pattern occurrence domain, independent of
association-list order. Requiring a duplicate-free domain, the same cardinality,
and the same members is equivalent to an exact permutation of the occurrence
IDs when a permutation exists. In particular, repeated pattern occurrence IDs
cannot be paired with unrelated mapping keys.
-/
def ExactEmbeddingDomain (p : Pattern) (e : Embedding) : Prop :=
  e.domain.Nodup ∧
  e.domain.length = p.molecules.length ∧
  p.molecules.map (fun pm => pm.occurrence) ⊆ e.domain ∧
  e.domain ⊆ p.molecules.map (fun pm => pm.occurrence)

/-- The concrete molecule selected for `pm` satisfies its local constraints. -/
def MoleculeSatisfies (p : Pattern) (mix : Mixture) (e : Embedding)
    (pm : PatternMolecule) : Prop :=
  ∃ runtimeId actual,
    e.lookup? pm.occurrence = some runtimeId ∧
    mix.findMolecule? runtimeId = some actual ∧
    actual.moleculeType = pm.moleculeType ∧
    (match pm.compartment with
      | none => True
      | some wanted => actual.compartment = some wanted) ∧
    moleculeBondMatches mix actual.id pm.moleculeBond = true ∧
    p.sitesMatch mix e pm actual = true

/-- Every explicit exact pattern bond exists after applying the embedding. -/
def ExplicitBondsSatisfy (p : Pattern) (mix : Mixture) (e : Embedding) : Prop :=
  ∀ bond, bond ∈ p.bonds →
    ∃ a b,
      p.resolveEndpoint? e bond.a = some a ∧
      p.resolveEndpoint? e bond.b = some b ∧
      mix.hasBond a b = true

/-- All molecules in one top-level BNGL pattern are in one connected complex. -/
def OneComplexEmbedding (mix : Mixture) (e : Embedding) : Prop :=
  ∀ a, a ∈ e.range → ∀ b, b ∈ e.range → mix.sameComplex a b = true

/-- Independent proposition-level meaning of one pattern embedding. -/
def EmbeddingSpec (p : Pattern) (mix : Mixture) (e : Embedding) : Prop :=
  (∀ pm, pm ∈ p.molecules → mapsExactlyOnce e pm.occurrence) ∧
  ExactEmbeddingDomain p e ∧
  InjectiveEmbedding e ∧
  (∀ pm, pm ∈ p.molecules → MoleculeSatisfies p mix e pm) ∧
  ExplicitBondsSatisfy p mix e ∧
  OneComplexEmbedding mix e

/--
The two theorem statements a production matcher owes us.

They are definitions rather than assumed axioms: downstream formal work cannot
pretend these properties are already established.
-/
def MatcherSound (matcher : Pattern → Mixture → List Embedding) : Prop :=
  ∀ p mix e, e ∈ matcher p mix → EmbeddingSpec p mix e

/-- Two embeddings describe the same assignment on every pattern node. -/
def SamePatternMapping (p : Pattern) (left right : Embedding) : Prop :=
  ∀ pm, pm ∈ p.molecules →
    left.lookup? pm.occurrence = right.lookup? pm.occurrence

def MatcherComplete (matcher : Pattern → Mixture → List Embedding) : Prop :=
  ∀ p mix e, EmbeddingSpec p mix e →
    ∃ emitted, emitted ∈ matcher p mix ∧ SamePatternMapping p e emitted

/-- Reference matcher proof obligation. -/
def ReferenceMatcherCorrect : Prop :=
  MatcherSound Pattern.matches ∧ MatcherComplete Pattern.matches

end BNG
