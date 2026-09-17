import BNG.Operational

namespace BNG

/-!
# Declarative matcher specification

`Pattern.embeddingMatches` is executable code.  For a meaningful verification
story we also want a specification that says *what a match is* without simply
calling that Boolean function again.

This file deliberately separates the two.  Production matchers should
ultimately prove soundness and completeness against `EmbeddingSpec`.
-/

/-- Exactly one mapping entry exists for a pattern molecule occurrence. -/
def mapsExactlyOnce (e : Embedding) (id : PatternMoleculeId) : Prop :=
  (e.moleculeMap.filter (fun pair => pair.1 == id)).length = 1

/-- No two distinct pattern molecules share a concrete molecule. -/
def InjectiveEmbedding (e : Embedding) : Prop :=
  allUnique e.range = true

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
  e.domain.length = p.molecules.length ∧
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

def MatcherComplete (matcher : Pattern → Mixture → List Embedding) : Prop :=
  ∀ p mix e, EmbeddingSpec p mix e → e ∈ matcher p mix

/-- Reference matcher proof obligation. -/
def ReferenceMatcherCorrect : Prop :=
  MatcherSound Pattern.matches ∧ MatcherComplete Pattern.matches

end BNG
