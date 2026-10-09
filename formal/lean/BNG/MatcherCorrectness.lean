import BNG.MatcherSpec

namespace BNG

private instance : LawfulBEq PatternMoleculeId where
  eq_of_beq {a b} h := by
    cases a with
    | mk a =>
      cases b with
      | mk b =>
        change BNG.instBEqPatternMoleculeId.beq ⟨a⟩ ⟨b⟩ = true at h
        simp only [BNG.instBEqPatternMoleculeId.beq] at h
        exact congrArg PatternMoleculeId.mk (beq_iff_eq.mp h)
  rfl {a} := by
    cases a with
    | mk a =>
        change BNG.instBEqPatternMoleculeId.beq ⟨a⟩ ⟨a⟩ = true
        simp only [BNG.instBEqPatternMoleculeId.beq]
        exact beq_iff_eq.mpr rfl

private instance : LawfulBEq MoleculeInstanceId where
  eq_of_beq {a b} h := by
    cases a with
    | mk a =>
      cases b with
      | mk b =>
        change BNG.instBEqMoleculeInstanceId.beq ⟨a⟩ ⟨b⟩ = true at h
        simp only [BNG.instBEqMoleculeInstanceId.beq] at h
        exact congrArg MoleculeInstanceId.mk (beq_iff_eq.mp h)
  rfl {a} := by
    cases a with
    | mk a =>
        change BNG.instBEqMoleculeInstanceId.beq ⟨a⟩ ⟨a⟩ = true
        simp only [BNG.instBEqMoleculeInstanceId.beq]
        exact beq_iff_eq.mpr rfl

private instance : LawfulBEq MoleculeTypeId where
  eq_of_beq {a b} h := by
    cases a with
    | mk a =>
      cases b with
      | mk b =>
        change BNG.instBEqMoleculeTypeId.beq ⟨a⟩ ⟨b⟩ = true at h
        simp only [BNG.instBEqMoleculeTypeId.beq] at h
        exact congrArg MoleculeTypeId.mk (beq_iff_eq.mp h)
  rfl {a} := by
    cases a with
    | mk a =>
        change BNG.instBEqMoleculeTypeId.beq ⟨a⟩ ⟨a⟩ = true
        simp only [BNG.instBEqMoleculeTypeId.beq]
        exact beq_iff_eq.mpr rfl

private instance : LawfulBEq CompartmentId where
  eq_of_beq {a b} h := by
    cases a with
    | mk a =>
      cases b with
      | mk b =>
        change BNG.instBEqCompartmentId.beq ⟨a⟩ ⟨b⟩ = true at h
        simp only [BNG.instBEqCompartmentId.beq] at h
        exact congrArg CompartmentId.mk (beq_iff_eq.mp h)
  rfl {a} := by
    cases a with
    | mk a =>
        change BNG.instBEqCompartmentId.beq ⟨a⟩ ⟨a⟩ = true
        simp only [BNG.instBEqCompartmentId.beq]
        exact beq_iff_eq.mpr rfl

private theorem allUnique_eq_true_iff_nodup {α : Type} [BEq α] [LawfulBEq α]
    (xs : List α) : allUnique xs = true ↔ xs.Nodup := by
  induction xs with
  | nil => simp [allUnique]
  | cons x xs ih =>
    simp [allUnique, ih, List.nodup_cons]

private theorem allContained_eq_true_iff_subset {α : Type} [BEq α] [LawfulBEq α]
    (xs ys : List α) : allContained xs ys = true ↔ xs ⊆ ys := by
  simp [allContained, List.all_eq_true]
  rfl

private theorem perm_of_nodup_subset_length {α : Type}
    (xs ys : List α) (hxs : xs.Nodup) (hxy : xs ⊆ ys)
    (hlen : xs.length = ys.length) : xs.Perm ys := by
  classical
  induction xs generalizing ys with
  | nil =>
    have hempty : ys = [] := List.length_eq_zero_iff.mp hlen.symm
    subst ys
    exact List.Perm.refl []
  | cons x xs ih =>
    rcases List.nodup_cons.mp hxs with ⟨hxnot, hxsNodup⟩
    have hxys : x ∈ ys := hxy (by simp)
    have hxsSub : xs ⊆ ys.erase x := by
      intro y hy
      have hyne : y ≠ x := by
        intro h
        exact hxnot (h ▸ hy)
      exact (List.mem_erase_of_ne hyne).2 (hxy (List.mem_cons_of_mem x hy))
    have hpos : 1 ≤ ys.length := Nat.succ_le_iff.mpr (List.length_pos_of_mem hxys)
    have hlenErase : (ys.erase x).length + 1 = ys.length := by
      rw [List.length_erase_of_mem hxys]
      exact Nat.sub_add_cancel hpos
    have hlenLeft : xs.length + 1 = ys.length := by
      simpa only [List.length_cons] using hlen
    have hlen' : xs.length = (ys.erase x).length :=
      Nat.add_right_cancel (hlenLeft.trans hlenErase.symm)
    exact (List.Perm.cons x (ih (ys.erase x) hxsNodup hxsSub hlen')).trans
      (List.perm_cons_erase hxys).symm

theorem exactEmbeddingDomain_iff_nodup_and_perm
    (p : Pattern) (e : Embedding) :
    ExactEmbeddingDomain p e ↔
      e.domain.Nodup ∧ e.domain.Perm (p.molecules.map (fun pm => pm.occurrence)) := by
  constructor
  · intro h
    refine ⟨h.1, ?_⟩
    apply perm_of_nodup_subset_length e.domain
      (p.molecules.map (fun pm => pm.occurrence)) h.1 h.2.2.2
    simpa using h.2.1
  · rintro ⟨hnodup, hperm⟩
    refine ⟨hnodup, ?_, ?_, ?_⟩
    · simpa using hperm.length_eq
    · exact hperm.symm.subset
    · exact hperm.subset

private theorem embeddingDomainCheck_eq_true_iff_exact
    (p : Pattern) (e : Embedding) :
    (allUnique e.domain &&
      (e.domain.length == (p.molecules.map (fun pm => pm.occurrence)).length) &&
      allContained (p.molecules.map (fun pm => pm.occurrence)) e.domain &&
      allContained e.domain (p.molecules.map (fun pm => pm.occurrence))) = true ↔
      ExactEmbeddingDomain p e := by
  have hUnique := allUnique_eq_true_iff_nodup e.domain
  have hExpectedContained := allContained_eq_true_iff_subset
    (p.molecules.map (fun pm => pm.occurrence)) e.domain
  have hActualContained := allContained_eq_true_iff_subset
    e.domain (p.molecules.map (fun pm => pm.occurrence))
  simp [ExactEmbeddingDomain, hUnique, hExpectedContained,
    hActualContained, and_assoc]

private theorem domainFilterLength_eq_mappingFilterLength
    (e : Embedding) (id : PatternMoleculeId) :
    (e.domain.filter (fun key => key == id)).length =
    (e.moleculeMap.filter (fun pair => pair.1 == id)).length := by
  simp [Embedding.domain, List.filter_map]
  rfl

private theorem mapsExactlyOnce_of_domainNodup_mem
    (e : Embedding) (id : PatternMoleculeId)
    (hnodup : e.domain.Nodup) (hmem : id ∈ e.domain) :
    mapsExactlyOnce e id := by
  have hcount : List.count id e.domain = 1 := by
    rw [List.Nodup.count hnodup]
    simp [hmem]
  unfold mapsExactlyOnce
  calc
    (e.moleculeMap.filter (fun pair => pair.1 == id)).length =
        (e.domain.filter (fun key => key == id)).length :=
      (domainFilterLength_eq_mappingFilterLength e id).symm
    _ = List.count id e.domain := (List.count_eq_length_filter).symm
    _ = 1 := hcount

private theorem exactDomain_mapsExactlyOnce
    (p : Pattern) (e : Embedding) (pm : PatternMolecule)
    (hdomain : ExactEmbeddingDomain p e) (hpm : pm ∈ p.molecules) :
  mapsExactlyOnce e pm.occurrence := by
  apply mapsExactlyOnce_of_domainNodup_mem e pm.occurrence hdomain.1
  exact hdomain.2.2.1 (List.mem_map.mpr ⟨pm, hpm, rfl⟩)

private theorem moleculeChecks_eq_true_iff
    (p : Pattern) (mix : Mixture) (e : Embedding) :
    p.molecules.all (fun pm =>
      match e.lookup? pm.occurrence with
      | none => false
      | some runtimeId =>
        match mix.findMolecule? runtimeId with
        | none => false
        | some actual =>
          (actual.moleculeType == pm.moleculeType &&
            (match pm.compartment with
              | none => true
              | some wanted => actual.compartment == some wanted)) &&
            moleculeBondMatches mix actual.id pm.moleculeBond &&
            p.sitesMatch mix e pm actual) = true ↔
    ∀ pm, pm ∈ p.molecules → MoleculeSatisfies p mix e pm := by
  constructor
  · intro h pm hpm
    have hcheck := (List.all_eq_true.mp h) pm hpm
    unfold MoleculeSatisfies
    cases hlookup : e.lookup? pm.occurrence with
    | none =>
      simp only [hlookup] at hcheck
      cases hcheck
    | some runtimeId =>
      cases hfind : mix.findMolecule? runtimeId with
      | none =>
        simp only [hlookup, hfind] at hcheck
        cases hcheck
      | some actual =>
        simp only [hlookup, hfind] at hcheck
        rcases Bool.and_eq_true_iff.mp hcheck with ⟨hprefix, hsites⟩
        rcases Bool.and_eq_true_iff.mp hprefix with ⟨hprefix, hbond⟩
        rcases Bool.and_eq_true_iff.mp hprefix with ⟨htypeBool, hcompartmentBool⟩
        have htype := beq_iff_eq.mp htypeBool
        cases hCompartment : pm.compartment with
        | none =>
          simp only [hCompartment] at hcompartmentBool
          exact ⟨runtimeId, actual, rfl, hfind, htype, True.intro,
            hbond, hsites⟩
        | some wanted =>
          simp only [hCompartment] at hcompartmentBool
          have hcompartment := beq_iff_eq.mp hcompartmentBool
          exact ⟨runtimeId, actual, rfl, hfind, htype, hcompartment,
            hbond, hsites⟩
  · intro h
    apply List.all_eq_true.mpr
    intro pm hpm
    obtain ⟨runtimeId, actual, hlookup, hfind, htype, hcompartment, hbond, hsites⟩ := h pm hpm
    have htypeBool := beq_iff_eq.mpr htype
    cases hCompartment : pm.compartment with
    | none =>
      simp only [hlookup, hfind, Bool.and_eq_true]
      exact ⟨⟨⟨htypeBool, True.intro⟩, hbond⟩, hsites⟩
    | some wanted =>
      have hcompartmentEq : actual.compartment = some wanted := by
        simpa only [hCompartment] using hcompartment
      have hcompartmentBool : (actual.compartment == some wanted) = true :=
        beq_iff_eq.mpr hcompartmentEq
      simp only [hlookup, hfind, Bool.and_eq_true]
      exact ⟨⟨⟨htypeBool, hcompartmentBool⟩, hbond⟩, hsites⟩

/-- The explicit bond validator agrees with its proposition-level condition. -/
private theorem explicitBondsCheck_eq_true_iff
    (p : Pattern) (mix : Mixture) (e : Embedding) :
    p.bonds.all (fun bond =>
      match p.resolveEndpoint? e bond.a, p.resolveEndpoint? e bond.b with
      | some a, some b => mix.hasBond a b
      | _, _ => false) = true ↔ ExplicitBondsSatisfy p mix e := by
  constructor
  · intro h bond hmem
    have hcheck := (List.all_eq_true.mp h) bond hmem
    cases ha : p.resolveEndpoint? e bond.a with
    | none => simp [ha] at hcheck
    | some a =>
      cases hb : p.resolveEndpoint? e bond.b with
      | none => simp [ha, hb] at hcheck
      | some b =>
        simp only [ha, hb] at hcheck
        exact ⟨a, b, rfl, rfl, hcheck⟩
  · intro h
    apply List.all_eq_true.mpr
    intro bond hmem
    obtain ⟨a, b, ha, hb, hbond⟩ := h bond hmem
    simp [ha, hb, hbond]

/-- The pairwise range validator agrees with the one-complex condition. -/
private theorem sameComplexCheck_eq_true_iff
    (mix : Mixture) (e : Embedding) :
    e.range.all (fun a => e.range.all (fun b => mix.sameComplex a b)) = true ↔
      OneComplexEmbedding mix e := by
  unfold OneComplexEmbedding
  simp only [List.all_eq_true]

/-- The executable candidate validator agrees with the independent predicate. -/
theorem embeddingMatches_iff_EmbeddingSpec
    (p : Pattern) (mix : Mixture) (e : Embedding) :
    p.embeddingMatches mix e = true ↔ EmbeddingSpec p mix e := by
  let expectedDomain := p.molecules.map (fun m => m.occurrence)
  let domainCheck := allUnique e.domain &&
    e.domain.length == expectedDomain.length &&
    allContained expectedDomain e.domain &&
    allContained e.domain expectedDomain
  let injectiveCheck := allUnique e.range
  let moleculeCheck := p.molecules.all (fun pm =>
    match e.lookup? pm.occurrence with
    | none => false
    | some runtimeId =>
      match mix.findMolecule? runtimeId with
      | none => false
      | some actual =>
        (actual.moleculeType == pm.moleculeType &&
          (match pm.compartment with
          | none => true
          | some wanted => actual.compartment == some wanted)) &&
          moleculeBondMatches mix actual.id pm.moleculeBond &&
          p.sitesMatch mix e pm actual)
  let bondCheck := p.bonds.all (fun bond =>
    match p.resolveEndpoint? e bond.a, p.resolveEndpoint? e bond.b with
    | some a, some b => mix.hasBond a b
    | _, _ => false)
  let complexCheck := e.range.all (fun a =>
    e.range.all (fun b => mix.sameComplex a b))
  change ((((domainCheck && injectiveCheck) && moleculeCheck) && bondCheck) &&
    complexCheck) = true ↔ EmbeddingSpec p mix e
  constructor
  · intro h
    rcases Bool.and_eq_true_iff.mp h with ⟨hprefix, hcomplex⟩
    rcases Bool.and_eq_true_iff.mp hprefix with ⟨hprefix, hbonds⟩
    rcases Bool.and_eq_true_iff.mp hprefix with ⟨hprefix, hmolecules⟩
    rcases Bool.and_eq_true_iff.mp hprefix with ⟨hdomain, hinjective⟩
    have hdomain' := embeddingDomainCheck_eq_true_iff_exact p e |>.mp hdomain
    have hinjective' : InjectiveEmbedding e := by
      change allUnique e.range = true
      exact hinjective
    have hmolecules' := moleculeChecks_eq_true_iff p mix e |>.mp hmolecules
    have hbonds' := explicitBondsCheck_eq_true_iff p mix e |>.mp hbonds
    have hcomplex' := sameComplexCheck_eq_true_iff mix e |>.mp hcomplex
    refine ⟨?_, hdomain', hinjective', hmolecules', hbonds', hcomplex'⟩
    intro pm hpm
    exact exactDomain_mapsExactlyOnce p e pm hdomain' hpm
  · rintro ⟨hmaps, hdomain, hinjective, hmolecules, hbonds, hcomplex⟩
    have hdomain' := embeddingDomainCheck_eq_true_iff_exact p e |>.mpr hdomain
    have hinjective' : allUnique e.range = true := by
      change allUnique e.range = true at hinjective
      exact hinjective
    have hmolecules' := moleculeChecks_eq_true_iff p mix e |>.mpr hmolecules
    have hbonds' := explicitBondsCheck_eq_true_iff p mix e |>.mpr hbonds
    have hcomplex' := sameComplexCheck_eq_true_iff mix e |>.mpr hcomplex
    have hdomInjective : (domainCheck && injectiveCheck) = true := by
      exact Bool.and_eq_true_iff.mpr ⟨hdomain', hinjective'⟩
    have hwithMolecules :
        ((domainCheck && injectiveCheck) && moleculeCheck) = true := by
      exact Bool.and_eq_true_iff.mpr ⟨hdomInjective, hmolecules'⟩
    have hwithBonds :
        (((domainCheck && injectiveCheck) && moleculeCheck) && bondCheck) = true := by
      exact Bool.and_eq_true_iff.mpr ⟨hwithMolecules, hbonds'⟩
    exact Bool.and_eq_true_iff.mpr ⟨hwithBonds, hcomplex'⟩

private def candidateBuild (mix : Mixture) : List PatternMolecule → List Embedding
  | [] => [{ moleculeMap := [] }]
  | pm :: rest =>
      mix.molecules.flatMap (fun actual =>
        (candidateBuild mix rest).map (fun tail =>
          { moleculeMap := (pm.occurrence, actual.id) :: tail.moleculeMap }))

private theorem candidateEmbeddings_eq_candidateBuild (p : Pattern) (mix : Mixture) :
    p.candidateEmbeddings mix = candidateBuild mix p.molecules := by
  unfold Pattern.candidateEmbeddings
  cases p with
  | mk nodes bonds =>
    induction nodes with
    | nil => rw [Pattern.candidateEmbeddings.build.eq_1, candidateBuild]
    | cons pm rest ih =>
      rw [Pattern.candidateEmbeddings.build.eq_2, candidateBuild, ih]

private theorem candidateBuild_has_mapping
    (mix : Mixture) :
    ∀ (nodes : List PatternMolecule) (f : PatternMolecule → MoleculeInstanceId),
      (nodes.map (fun pm => pm.occurrence)).Nodup →
      (∀ pm, pm ∈ nodes → ∃ actual, actual ∈ mix.molecules ∧ actual.id = f pm) →
      ∃ candidate, candidate ∈ candidateBuild mix nodes ∧
        candidate.moleculeMap = nodes.map (fun pm => (pm.occurrence, f pm)) := by
  intro nodes
  induction nodes with
  | nil =>
    intro f _ _
    refine ⟨({ moleculeMap := [] } : Embedding), ?_, ?_⟩
    · simp [candidateBuild]
    · rfl
  | cons pm rest ih =>
    intro f hNodup hChoices
    simp only [List.map_cons, List.nodup_cons] at hNodup
    rcases hNodup with ⟨hpmNotInRest, hRestNodup⟩
    obtain ⟨actual, hActualMem, hActualId⟩ := hChoices pm (by simp)
    obtain ⟨tail, hTailMem, hTailMap⟩ :=
      ih f hRestNodup (fun pm' hpm' => hChoices pm' (List.mem_cons_of_mem pm hpm'))
    refine ⟨({ moleculeMap := (pm.occurrence, actual.id) :: tail.moleculeMap } : Embedding), ?_, ?_⟩
    · change ({ moleculeMap := (pm.occurrence, actual.id) :: tail.moleculeMap } : Embedding) ∈
        mix.molecules.flatMap (fun chosen =>
          (candidateBuild mix rest).map (fun restCandidate =>
            ({ moleculeMap := (pm.occurrence, chosen.id) :: restCandidate.moleculeMap } : Embedding)))
      apply List.mem_flatMap.mpr
      refine ⟨actual, hActualMem, ?_⟩
      apply List.mem_map.mpr
      exact ⟨tail, hTailMem, rfl⟩
    · simp only [List.map_cons]
      rw [hActualId, hTailMap]

private theorem lookup_eq_of_mem_map_nodup
    (pairs : List (PatternMoleculeId × MoleculeInstanceId))
    (id : PatternMoleculeId) (value : MoleculeInstanceId)
    (hnodup : (pairs.map Prod.fst).Nodup) (hmem : (id, value) ∈ pairs) :
    ({ moleculeMap := pairs } : Embedding).lookup? id = some value := by
  induction pairs with
  | nil => cases hmem
  | cons pair rest ih =>
    cases pair with
    | mk key pairValue =>
      simp only [List.map_cons, List.nodup_cons] at hnodup
      rcases List.mem_cons.mp hmem with heq | htail
      · have heq' := Prod.mk.inj heq
        rcases heq' with ⟨rfl, rfl⟩
        change Embedding.lookup?.go id ((id, value) :: rest) = some value
        rw [Embedding.lookup?.go.eq_2]
        simp
      · have hkeyNe : key ≠ id := by
          intro heq
          apply hnodup.1
          apply List.mem_map.mpr
          exact ⟨(id, value), htail, by simp [heq]⟩
        have hkeyBeq : (key == id) = false := by
          cases hbeq : (key == id) with
          | false => rfl
          | true => exact False.elim (hkeyNe (beq_iff_eq.mp hbeq))
        have htailLookup := ih hnodup.2 htail
        change Embedding.lookup?.go id rest = some value at htailLookup
        change Embedding.lookup?.go id ((key, pairValue) :: rest) = some value
        rw [Embedding.lookup?.go.eq_2, hkeyBeq]
        exact htailLookup

private theorem moleculeMap_nodup_of_domain_nodup
    (pairs : List (PatternMoleculeId × MoleculeInstanceId))
    (h : (pairs.map Prod.fst).Nodup) : pairs.Nodup := by
  induction pairs with
  | nil => simp
  | cons pair rest ih =>
    simp only [List.map_cons, List.nodup_cons] at h
    apply List.nodup_cons.mpr
    refine ⟨?_, ih h.2⟩
    intro hmem
    apply h.1
    exact List.mem_map.mpr ⟨pair, hmem, rfl⟩

private theorem findMolecule?_eq_find?
    (mix : Mixture) (id : MoleculeInstanceId) :
    mix.findMolecule? id = mix.molecules.find? (fun actual => actual.id == id) := by
  cases mix with
  | mk nextMoleculeId molecules bonds =>
    induction molecules with
    | nil =>
      change Mixture.findMolecule?.go id [] = none
      exact Mixture.findMolecule?.go.eq_1 id
    | cons actual rest ih =>
      change Mixture.findMolecule?.go id (actual :: rest) =
        List.find? (fun item => item.id == id) (actual :: rest)
      rw [Mixture.findMolecule?.go.eq_2, List.find?_cons]
      by_cases h : (actual.id == id) = true
      · simp [h]
      · simp [h]
        exact ih

private theorem findMolecule_mem
    (mix : Mixture) (id : MoleculeInstanceId) (actual : RuntimeMolecule)
    (h : mix.findMolecule? id = some actual) : actual ∈ mix.molecules := by
  rw [findMolecule?_eq_find?] at h
  exact List.mem_of_find?_eq_some h

private theorem findMolecule_id
    (mix : Mixture) (id : MoleculeInstanceId) (actual : RuntimeMolecule)
    (h : mix.findMolecule? id = some actual) : actual.id = id := by
  rw [findMolecule?_eq_find?] at h
  have htest : (actual.id == id) = true :=
    List.find?_some (p := fun item : RuntimeMolecule => item.id == id) h
  exact beq_iff_eq.mp htest

private theorem sourceMap_perm_of_canonical
    (p : Pattern) (e : Embedding) (f : PatternMolecule → MoleculeInstanceId)
    (hdomain : ExactEmbeddingDomain p e)
    (hlookup : ∀ pm, pm ∈ p.molecules →
      e.lookup? pm.occurrence = some (f pm)) :
    e.moleculeMap.Perm (p.molecules.map (fun pm => (pm.occurrence, f pm))) := by
  apply perm_of_nodup_subset_length e.moleculeMap
    (p.molecules.map (fun pm => (pm.occurrence, f pm)))
  · exact moleculeMap_nodup_of_domain_nodup e.moleculeMap hdomain.1
  · intro pair hpair
    rcases pair with ⟨id, value⟩
    have hidDomain : id ∈ e.domain :=
      List.mem_map.mpr ⟨(id, value), hpair, rfl⟩
    have hidExpected : id ∈ p.molecules.map (fun pm => pm.occurrence) :=
      hdomain.2.2.2 hidDomain
    obtain ⟨pm, hpm, hidEq⟩ := List.mem_map.mp hidExpected
    have hlookupPair := lookup_eq_of_mem_map_nodup e.moleculeMap id value
      hdomain.1 hpair
    have hlookupPattern : e.lookup? id = some (f pm) := by
      rw [← hidEq]
      exact hlookup pm hpm
    have hvalue : f pm = value :=
      Option.some.inj (hlookupPattern.symm.trans hlookupPair)
    apply List.mem_map.mpr
    exact ⟨pm, hpm, Prod.ext hidEq hvalue⟩
  · calc
      e.moleculeMap.length = e.domain.length := by simp [Embedding.domain]
      _ = p.molecules.length := hdomain.2.1
      _ = (p.molecules.map (fun pm => (pm.occurrence, f pm))).length := by simp

private theorem candidate_of_embeddingSpec
    (p : Pattern) (mix : Mixture) (e : Embedding)
    (hspec : EmbeddingSpec p mix e) :
    ∃ candidate, candidate ∈ p.candidateEmbeddings mix ∧
      SamePatternMapping p e candidate ∧ candidate.moleculeMap.Perm e.moleculeMap := by
  rcases hspec with ⟨_, hdomain, _, hmolecules, _, _⟩
  let f : PatternMolecule → MoleculeInstanceId := fun pm =>
    (e.lookup? pm.occurrence).getD ⟨0⟩
  have hlookup : ∀ pm, pm ∈ p.molecules →
      e.lookup? pm.occurrence = some (f pm) := by
    intro pm hpm
    obtain ⟨runtimeId, actual, hlookup, _, _, _, _, _⟩ := hmolecules pm hpm
    have hchosen : f pm = runtimeId := by simp [f, hlookup]
    rw [hchosen]
    exact hlookup
  have hchoices : ∀ pm, pm ∈ p.molecules →
      ∃ actual, actual ∈ mix.molecules ∧ actual.id = f pm := by
    intro pm hpm
    obtain ⟨runtimeId, actual, hfound, hlookupFound, _, _, _, _⟩ := hmolecules pm hpm
    have hmem := findMolecule_mem mix runtimeId actual hlookupFound
    have hactualId := findMolecule_id mix runtimeId actual hlookupFound
    have hchosen : f pm = runtimeId := by simp [f, hfound]
    exact ⟨actual, hmem, by rw [hchosen]; exact hactualId⟩
  have hdomainPerm := exactEmbeddingDomain_iff_nodup_and_perm p e |>.mp hdomain
  have hidsNodup : (p.molecules.map (fun pm => pm.occurrence)).Nodup :=
    hdomainPerm.2.nodup hdomainPerm.1
  obtain ⟨candidate, hbuild, hcandidateMap⟩ :=
    candidateBuild_has_mapping mix p.molecules f hidsNodup hchoices
  have hcandidateMember : candidate ∈ p.candidateEmbeddings mix := by
    rw [candidateEmbeddings_eq_candidateBuild]
    exact hbuild
  have hcanonicalPerm := sourceMap_perm_of_canonical p e f hdomain hlookup
  have hcandidatePerm : e.moleculeMap.Perm candidate.moleculeMap := by
    rw [hcandidateMap]
    exact hcanonicalPerm
  have hcandidateDomainNodup : candidate.domain.Nodup := by
    rw [Embedding.domain, hcandidateMap]
    simpa [List.map_map, Function.comp_def] using hidsNodup
  have hcandidateMapDomainNodup :
      (candidate.moleculeMap.map Prod.fst).Nodup := by
    simpa [Embedding.domain] using hcandidateDomainNodup
  have hcandidateLookup : ∀ pm, pm ∈ p.molecules →
      candidate.lookup? pm.occurrence = some (f pm) := by
    intro pm hpm
    have hpair : (pm.occurrence, f pm) ∈ candidate.moleculeMap := by
      rw [hcandidateMap]
      exact List.mem_map.mpr ⟨pm, hpm, rfl⟩
    exact lookup_eq_of_mem_map_nodup candidate.moleculeMap pm.occurrence
      (f pm) hcandidateMapDomainNodup hpair
  have hsame : SamePatternMapping p e candidate := by
    intro pm hpm
    exact (hlookup pm hpm).trans (hcandidateLookup pm hpm).symm
  exact ⟨candidate, hcandidateMember, hsame, hcandidatePerm.symm⟩

private theorem lookup_go_perm {left right : List (PatternMoleculeId × MoleculeInstanceId)}
    (permutation : left.Perm right) (unique : (left.map Prod.fst).Nodup)
    (id : PatternMoleculeId) :
    Embedding.lookup?.go id left = Embedding.lookup?.go id right := by
  induction permutation with
  | nil => rfl
  | @cons head l1 l2 permutation ih =>
    have restUnique : (l1.map Prod.fst).Nodup := (List.nodup_cons.mp unique).2
    simp only [Embedding.lookup?.go]
    rw [ih restUnique]
  | swap a b rest =>
    have different : b.1 ≠ a.1 := by
      have absent := (List.nodup_cons.mp unique).1
      intro equal
      apply absent
      simp [equal]
    by_cases ha : a.1 = id <;> by_cases hb : b.1 = id
    · exact False.elim (different (hb.trans ha.symm))
    · simp [Embedding.lookup?.go, ha, hb]
    · simp [Embedding.lookup?.go, ha, hb]
    · simp [Embedding.lookup?.go, ha, hb]
  | trans p1 p2 ih1 ih2 =>
    exact (ih1 unique).trans (ih2 ((p1.map Prod.fst).nodup unique))

private theorem embedding_lookup_perm (left right : Embedding)
    (permutation : left.moleculeMap.Perm right.moleculeMap)
    (unique : left.domain.Nodup) (id : PatternMoleculeId) :
    left.lookup? id = right.lookup? id :=
  lookup_go_perm permutation unique id

private theorem embeddingSpec_perm_of_moleculeMap_perm
    (p : Pattern) (mix : Mixture) (e1 e2 : Embedding)
    (hperm : e1.moleculeMap.Perm e2.moleculeMap)
    (hspec : EmbeddingSpec p mix e1) : EmbeddingSpec p mix e2 := by
  obtain ⟨once, domain, injective, molecules, bonds, complex⟩ := hspec
  have domainPerm : e1.domain.Perm e2.domain := hperm.map Prod.fst
  have rangePerm : e1.range.Perm e2.range := hperm.map Prod.snd
  have lookups : e1.lookup? = e2.lookup? :=
    funext (embedding_lookup_perm e1 e2 hperm domain.1)
  have endpoints : ∀ endpoint, p.resolveEndpoint? e1 endpoint =
      p.resolveEndpoint? e2 endpoint := by
    intro endpoint
    simp only [Pattern.resolveEndpoint?, lookups]
  have exactBonds : ∀ group, p.exactBondMatches mix e1 group =
      p.exactBondMatches mix e2 group := by
    intro group
    simp only [Pattern.exactBondMatches, endpoints]
  have siteBonds : ∀ endpoint requirements,
      p.siteBondsMatch mix e1 endpoint requirements =
      p.siteBondsMatch mix e2 endpoint requirements := by
    intro endpoint requirements
    simp only [Pattern.siteBondsMatch, exactBonds]
  have sites : ∀ pm actual, p.sitesMatch mix e1 pm actual =
      p.sitesMatch mix e2 pm actual := by
    intro pm actual
    simp only [Pattern.sitesMatch, siteBonds]
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_⟩
  · intro pm member
    unfold mapsExactlyOnce
    rw [← (hperm.filter (fun pair => pair.1 == pm.occurrence)).length_eq]
    exact once pm member
  · exact ⟨domainPerm.nodup domain.1,
      domainPerm.length_eq.symm.trans domain.2.1,
      fun id member => domainPerm.subset (domain.2.2.1 member),
      fun id member => domain.2.2.2 (domainPerm.symm.subset member)⟩
  · exact (allUnique_eq_true_iff_nodup e2.range).mpr
      (rangePerm.nodup ((allUnique_eq_true_iff_nodup e1.range).mp injective))
  · intro pm member
    obtain ⟨runtimeId, actual, lookup, find, type, compartment, bond, site⟩ :=
      molecules pm member
    refine ⟨runtimeId, actual, ?_, find, type, compartment, bond, ?_⟩
    · rw [← lookups]
      exact lookup
    · rw [← sites]
      exact site
  · intro bond member
    obtain ⟨a, b, endpointA, endpointB, existsBond⟩ := bonds bond member
    exact ⟨a, b, (endpoints bond.a).symm.trans endpointA,
      (endpoints bond.b).symm.trans endpointB, existsBond⟩
  · intro a memberA b memberB
    exact complex a (rangePerm.symm.subset memberA)
      b (rangePerm.symm.subset memberB)

theorem referenceMatcher_sound : MatcherSound Pattern.matches := by
  intro p mix e hmem
  simp only [Pattern.matches, List.mem_filter] at hmem
  exact (embeddingMatches_iff_EmbeddingSpec p mix e).mp hmem.2

theorem referenceMatcher_complete : MatcherComplete Pattern.matches := by
  intro p mix e hspec
  obtain ⟨candidate, hcandidate, hsame, hperm⟩ :=
    candidate_of_embeddingSpec p mix e hspec
  have hcandidateSpec :=
    embeddingSpec_perm_of_moleculeMap_perm p mix e candidate hperm.symm hspec
  refine ⟨candidate, ?_, hsame⟩
  simp only [Pattern.matches, List.mem_filter]
  exact ⟨hcandidate, (embeddingMatches_iff_EmbeddingSpec p mix candidate).mpr hcandidateSpec⟩

theorem referenceMatcher_correct : ReferenceMatcherCorrect :=
  ⟨referenceMatcher_sound, referenceMatcher_complete⟩

end BNG
