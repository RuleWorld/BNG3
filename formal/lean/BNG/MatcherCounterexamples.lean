import BNG.MatcherSpec

namespace BNG.MatcherCounterexamples

/-!
Historical counterexamples for the contracts that preceded the approved
mapping-equivalence and exact-domain repairs. The current theorems below keep
these witnesses explicit without treating the superseded contracts as current.
-/

def molecule0 : PatternMolecule :=
  { occurrence := ⟨0⟩, moleculeType := ⟨0⟩ }

def molecule1 : PatternMolecule :=
  { occurrence := ⟨1⟩, moleculeType := ⟨0⟩ }

def pattern : Pattern := { molecules := [molecule0, molecule1] }

def actual0 : RuntimeMolecule :=
  { id := ⟨0⟩, moleculeType := ⟨0⟩, sites := [{ component := ⟨0⟩ }] }

def actual1 : RuntimeMolecule :=
  { id := ⟨1⟩, moleculeType := ⟨0⟩, sites := [{ component := ⟨0⟩ }] }

def mixture : Mixture :=
  { nextMoleculeId := ⟨2⟩
    molecules := [actual0, actual1]
    bonds := [{ a := { molecule := ⟨0⟩, component := ⟨0⟩ },
                b := { molecule := ⟨1⟩, component := ⟨0⟩ } }] }

def signature : Signature :=
  { moleculeTypes := [{ id := ⟨0⟩, name := "A", components := [{ id := ⟨0⟩, name := "x" }] }] }

/-- Same assignment as `[(0,0),(1,1)]`, stored in the opposite order. -/
def reversedEmbedding : Embedding :=
  { moleculeMap := [(⟨1⟩, ⟨1⟩), (⟨0⟩, ⟨0⟩)] }

/-- The ordering counterexample is a well-formed pattern and mixture. -/
theorem ordering_fixture_wellFormed :
    pattern.wellFormed signature = true ∧ mixture.wellFormed signature = true := by
  decide

/-- All executable constraints accept the permuted assignment. -/
theorem reversed_embedding_matches :
    pattern.embeddingMatches mixture reversedEmbedding = true := by
  rfl

/-- Enumeration cannot emit this ordering of the same valid assignment. -/
theorem reversed_embedding_not_enumerated :
    reversedEmbedding ∉ pattern.matches mixture := by
  change reversedEmbedding ∉
    [{ moleculeMap := [(⟨0⟩, ⟨0⟩), (⟨1⟩, ⟨1⟩)] },
     { moleculeMap := [(⟨0⟩, ⟨1⟩), (⟨1⟩, ⟨0⟩)] }]
  simp [reversedEmbedding, Embedding.mk.injEq]

/-- The independent specification has no mapping-order requirement. -/
theorem reversed_embedding_spec : EmbeddingSpec pattern mixture reversedEmbedding := by
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_⟩
  · intro pm h
    change pm ∈ [molecule0, molecule1] at h
    simp only [List.mem_cons, List.not_mem_nil, or_false] at h
    rcases h with rfl | rfl <;> rfl
  · refine ⟨?_, rfl, ?_, ?_⟩
    · simp [Embedding.domain, reversedEmbedding]
    · intro (id : PatternMoleculeId)
      simp [Embedding.domain, reversedEmbedding, pattern, molecule0, molecule1,
        or_comm]
    · intro (id : PatternMoleculeId)
      simp [Embedding.domain, reversedEmbedding, pattern, molecule0, molecule1,
        or_comm]
  · rfl
  · intro pm h
    change pm ∈ [molecule0, molecule1] at h
    simp only [List.mem_cons, List.not_mem_nil, or_false] at h
    rcases h with rfl | rfl
    · exact ⟨⟨0⟩, actual0, rfl, rfl, rfl, True.intro, rfl, rfl⟩
    · exact ⟨⟨1⟩, actual1, rfl, rfl, rfl, True.intro, rfl, rfl⟩
  · intro bond h
    exact False.elim (List.not_mem_nil h)
  · intro a ha b hb
    change a ∈ [⟨1⟩, ⟨0⟩] at ha
    change b ∈ [⟨1⟩, ⟨0⟩] at hb
    simp only [List.mem_cons, List.not_mem_nil, or_false] at ha hb
    rcases ha with rfl | rfl <;> rcases hb with rfl | rfl <;> rfl

/-- The superseded literal-membership completeness predicate. -/
def MatcherCompleteByLiteralMembership
    (matcher : Pattern → Mixture → List Embedding) : Prop :=
  ∀ p mix e, EmbeddingSpec p mix e → e ∈ matcher p mix

/-- Literal association-list membership is incomplete, even on valid inputs. -/
theorem reference_matcher_not_complete_by_literal_membership :
    ¬ MatcherCompleteByLiteralMembership Pattern.matches := by
  intro complete
  exact reversed_embedding_not_enumerated (complete pattern mixture reversedEmbedding
    reversed_embedding_spec)

/-- Historical literal-membership correctness is false for the same reason. -/
theorem reference_matcher_not_correct_by_literal_membership :
    ¬ (MatcherSound Pattern.matches ∧ MatcherCompleteByLiteralMembership Pattern.matches) := by
  intro correct
  exact reference_matcher_not_complete_by_literal_membership correct.2

/-- Duplicate occurrence IDs expose a separate missing domain invariant. -/
def duplicateOccurrencePattern : Pattern := { molecules := [molecule0, molecule0] }

def extraEntryEmbedding : Embedding :=
  { moleculeMap := [(⟨0⟩, ⟨0⟩), (⟨1⟩, ⟨1⟩)] }

/-- This second witness is intentionally outside the well-formed pattern domain. -/
theorem duplicate_occurrences_not_wellFormed :
    duplicateOccurrencePattern.wellFormed signature = false := by
  rfl

/-- The pre-repair specification, retained to document its ghost-key gap. -/
def HistoricalEmbeddingSpec (p : Pattern) (mix : Mixture) (e : Embedding) : Prop :=
  (∀ pm, pm ∈ p.molecules → mapsExactlyOnce e pm.occurrence) ∧
  e.domain.length = p.molecules.length ∧
  InjectiveEmbedding e ∧
  (∀ pm, pm ∈ p.molecules → MoleculeSatisfies p mix e pm) ∧
  ExplicitBondsSatisfy p mix e ∧
  OneComplexEmbedding mix e

/-- A duplicate pattern occurrence made the old specification admit a ghost key. -/
theorem extra_entry_embedding_historical_spec :
    HistoricalEmbeddingSpec duplicateOccurrencePattern mixture extraEntryEmbedding := by
  refine ⟨?_, rfl, ?_, ?_, ?_, ?_⟩
  · intro pm h
    change pm ∈ [molecule0, molecule0] at h
    simp only [List.mem_cons, List.not_mem_nil, or_false, or_self] at h
    subst pm
    rfl
  · rfl
  · intro pm h
    change pm ∈ [molecule0, molecule0] at h
    simp only [List.mem_cons, List.not_mem_nil, or_false, or_self] at h
    subst pm
    exact ⟨⟨0⟩, actual0, rfl, rfl, rfl, True.intro, rfl, rfl⟩
  · intro bond h
    exact False.elim (List.not_mem_nil h)
  · intro a ha b hb
    change a ∈ [⟨0⟩, ⟨1⟩] at ha
    change b ∈ [⟨0⟩, ⟨1⟩] at hb
    simp only [List.mem_cons, List.not_mem_nil, or_false] at ha hb
    rcases ha with rfl | rfl <;> rcases hb with rfl | rfl <;> rfl

/-- The executable domain check rejects the extra mapping key. -/
theorem extra_entry_embedding_rejected :
    duplicateOccurrencePattern.embeddingMatches mixture extraEntryEmbedding = false := by
  rfl

/-- The repaired exact-domain clause rejects the old ghost-key witness. -/
theorem extra_entry_embedding_not_in_current_spec :
    ¬ EmbeddingSpec duplicateOccurrencePattern mixture extraEntryEmbedding := by
  intro hspec
  have hdomain : ExactEmbeddingDomain duplicateOccurrencePattern extraEntryEmbedding :=
    hspec.2.1
  have hghostDomain : (⟨1⟩ : PatternMoleculeId) ∈ extraEntryEmbedding.domain := by
    change (⟨1⟩ : PatternMoleculeId) ∈ [⟨0⟩, ⟨1⟩]
    simp
  have hghostPattern := hdomain.2.2.2 hghostDomain
  simp [duplicateOccurrencePattern, molecule0] at hghostPattern

/-- The old specification/validator mismatch is preserved as historical evidence. -/
theorem historical_spec_not_equivalent_to_validator :
    ¬ (∀ p mix e, p.embeddingMatches mix e = true ↔ HistoricalEmbeddingSpec p mix e) := by
  intro equivalent
  have accepted := (equivalent duplicateOccurrencePattern mixture extraEntryEmbedding).mpr
    extra_entry_embedding_historical_spec
  rw [extra_entry_embedding_rejected] at accepted
  contradiction

end BNG.MatcherCounterexamples
