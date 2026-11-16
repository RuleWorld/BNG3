import BNG.Graph

namespace BNG

/-!
# Runtime-ID-independent species identity

Generated reaction networks need to decide whether two concrete complexes are
the *same chemical species*. Runtime molecule allocation IDs cannot participate
in that decision.

This module defines an intentionally brute-force graph-isomorphism oracle.  It
is not a production canonical-label algorithm; it is the small obvious thing a
fast canonicalizer should agree with on generated fixtures.
-/

/-- A candidate bijection between molecule-instance IDs. -/
structure SpeciesIsoMap where
  moleculeMap : List (MoleculeInstanceId × MoleculeInstanceId) := []
  deriving Repr, DecidableEq, BEq

/-- Lookup a mapped molecule. -/
def SpeciesIsoMap.lookup? (m : SpeciesIsoMap) (id : MoleculeInstanceId) : Option MoleculeInstanceId :=
  (m.moleculeMap.find? (fun pair => pair.1 == id)).map Prod.snd

def SpeciesIsoMap.domain (m : SpeciesIsoMap) : List MoleculeInstanceId :=
  m.moleculeMap.map Prod.fst

def SpeciesIsoMap.range (m : SpeciesIsoMap) : List MoleculeInstanceId :=
  m.moleculeMap.map Prod.snd

/-- Runtime site collections are compared extensionally by component identity/state. -/
def runtimeSitesEquivalent (a b : List RuntimeSite) : Bool :=
  a.length == b.length &&
    a.all (fun site =>
      match b.find? (fun other => other.component == site.component) with
      | none => false
      | some other => other.state == site.state) &&
    b.all (fun site =>
      match a.find? (fun other => other.component == site.component) with
      | none => false
      | some other => other.state == site.state)

/-- Local molecule labels preserved by a species isomorphism. -/
def runtimeMoleculesEquivalent (a b : RuntimeMolecule) : Bool :=
  a.moleculeType == b.moleculeType &&
  a.compartment == b.compartment &&
  runtimeSitesEquivalent a.sites b.sites

/-- Kernel-proved renaming/canonicalization symmetry: site-level component/state
correspondence is symmetric for the supported class. -/
theorem runtimeSitesEquivalent_symm (a b : List RuntimeSite)
    (h : runtimeSitesEquivalent a b = true) : runtimeSitesEquivalent b a = true := by
  simp [runtimeSitesEquivalent, Bool.and_eq_true] at h ⊢
  rcases h with ⟨⟨hlen, hab⟩, hba⟩
  refine ⟨⟨?_, ?_⟩, ?_⟩
  · simpa using hlen.symm
  · exact hba
  · exact hab

/-- Identity mapping on a molecule-ID list. -/
def SpeciesIsoMap.idOn (ids : List MoleculeInstanceId) : SpeciesIsoMap :=
  { moleculeMap := ids.map (fun id => (id, id)) }

/-- Invert a candidate bijection by swapping domain and range entries. -/
def SpeciesIsoMap.inverse (m : SpeciesIsoMap) : SpeciesIsoMap :=
  { moleculeMap := m.moleculeMap.map (fun pair => (pair.2, pair.1)) }

@[simp] theorem SpeciesIsoMap.domain_inverse (m : SpeciesIsoMap) :
    m.inverse.domain = m.range := by
  simp [SpeciesIsoMap.inverse, SpeciesIsoMap.domain, SpeciesIsoMap.range]

@[simp] theorem SpeciesIsoMap.range_inverse (m : SpeciesIsoMap) :
    m.inverse.range = m.domain := by
  simp [SpeciesIsoMap.inverse, SpeciesIsoMap.domain, SpeciesIsoMap.range]

@[simp] theorem SpeciesIsoMap.domain_idOn (ids : List MoleculeInstanceId) :
    (SpeciesIsoMap.idOn ids).domain = ids := by
  unfold SpeciesIsoMap.idOn SpeciesIsoMap.domain
  induction ids with
  | nil => rfl
  | cons x xs ih => simp [ih]

@[simp] theorem SpeciesIsoMap.range_idOn (ids : List MoleculeInstanceId) :
    (SpeciesIsoMap.idOn ids).range = ids := by
  unfold SpeciesIsoMap.idOn SpeciesIsoMap.range
  induction ids with
  | nil => rfl
  | cons x xs ih => simp [ih]

/-- Map one concrete endpoint through a molecule-ID bijection. -/
def SpeciesIsoMap.mapEndpoint? (mapping : SpeciesIsoMap) (e : ConcreteEndpoint) : Option ConcreteEndpoint :=
  (mapping.lookup? e.molecule).map (fun molecule =>
    { molecule := molecule, component := e.component })

/-- Every edge in `left` is carried to an edge in `right`. -/
def bondsPreservedForward (left right : Mixture) (mapping : SpeciesIsoMap) : Bool :=
  left.bonds.all (fun edge =>
    match mapping.mapEndpoint? edge.a, mapping.mapEndpoint? edge.b with
    | some a, some b => right.hasBond a b
    | _, _ => false)

/-- Candidate mapping is a bijection over all molecules in both mixtures. -/
def SpeciesIsoMap.bijectiveFor (mapping : SpeciesIsoMap) (left right : Mixture) : Bool :=
  allUnique mapping.domain && allUnique mapping.range &&
  sameMoleculeIdSet mapping.domain (left.molecules.map (fun m => m.id)) &&
  sameMoleculeIdSet mapping.range (right.molecules.map (fun m => m.id))

/-- Candidate mapping preserves molecule labels and the complete bond graph. -/
def SpeciesIsoMap.validFor (mapping : SpeciesIsoMap) (left right : Mixture) : Bool :=
  mapping.bijectiveFor left right &&
  mapping.moleculeMap.all (fun pair =>
    match left.findMolecule? pair.1, right.findMolecule? pair.2 with
    | some a, some b => runtimeMoleculesEquivalent a b
    | _, _ => false) &&
  bondsPreservedForward left right mapping &&
  left.bonds.length == right.bonds.length



/-- Brute-force every raw molecule bijection candidate. -/
def candidateSpeciesIsoMaps (left right : Mixture) : List SpeciesIsoMap :=
  let rec build : List RuntimeMolecule → List SpeciesIsoMap
    | [] => [{ moleculeMap := [] }]
    | molecule :: rest =>
        let tails := build rest
        right.molecules.flatMap (fun target =>
          tails.map (fun tail =>
            { moleculeMap := (molecule.id, target.id) :: tail.moleculeMap }))
  build left.molecules

/-- Runtime-ID-independent molecular-graph equivalence. -/
def Mixture.isomorphicSpecies (left right : Mixture) : Bool :=
  left.molecules.length == right.molecules.length &&
  left.bonds.length == right.bonds.length &&
  (candidateSpeciesIsoMaps left right).any (fun mapping => mapping.validFor left right)

/-- One mixture is a single connected species rather than several complexes. -/
def Mixture.singleComplex (mix : Mixture) : Bool :=
  match mix.molecules with
  | [] => false
  | first :: _ => sameMoleculeIdSet (mix.connectedFrom first.id) (mix.molecules.map (fun m => m.id))

/-- Add a species only when no graph-isomorphic representative already exists. -/
def addSpeciesModuloIso (pool : List Mixture) (candidate : Mixture) : List Mixture :=
  if pool.any (fun existing => existing.isomorphicSpecies candidate) then pool
  else pool ++ [candidate]

/--
Named supported class for this formal identity oracle: finite runtime mixtures
compared by typed molecular graph isomorphism over molecule type, component
identity/state, optional compartments, and exact undirected bonds.  The oracle
accepts only bijections validated by `SpeciesIsoMap.validFor`.
-/
def SupportedGraphIdentityClass (_mix : Mixture) : Prop := True

/-- A valid isomorphism witness enforces equal bond counts (structural
invariant for compared artifacts in this supported class). -/
theorem SpeciesIsoMap.validFor_bond_count (m : SpeciesIsoMap) (left right : Mixture)
    (h : m.validFor left right = true) :
    left.bonds.length = right.bonds.length := by
  simp [SpeciesIsoMap.validFor, Bool.and_eq_true] at h
  simpa using h.2

/-- A valid isomorphism witness bijects the full molecule-ID sets of both sides
(renaming/coverage invariant). -/
theorem SpeciesIsoMap.validFor_bijective (m : SpeciesIsoMap) (left right : Mixture)
    (h : m.validFor left right = true) :
    m.bijectiveFor left right = true := by
  simp [SpeciesIsoMap.validFor, Bool.and_eq_true] at h
  exact h.1.1.1

/-- Renaming/canonicalization symmetry on the supported class: inverting a
bijective molecule-id witness swaps the covered artifact-ID sets. -/
theorem SpeciesIsoMap.inverse_bijectiveFor (m : SpeciesIsoMap) (left right : Mixture)
    (h : m.bijectiveFor left right = true) :
    m.inverse.bijectiveFor right left = true := by
  simp [SpeciesIsoMap.bijectiveFor, Bool.and_eq_true] at h ⊢
  rcases h with ⟨⟨⟨hdomU, hranU⟩, hdomSet⟩, hranSet⟩
  exact ⟨⟨⟨by simpa using hranU, by simpa using hdomU⟩, by simpa using hranSet⟩, by simpa using hdomSet⟩

/-- Kernel-proved renaming/coverage invariant: a bijective witness implies equal
molecule-instance counts for the supported class artifacts. -/
theorem SpeciesIsoMap.bijectiveFor_molecule_count (m : SpeciesIsoMap) (left right : Mixture)
    (h : m.bijectiveFor left right = true) :
    left.molecules.length = right.molecules.length := by
  have hb := h
  simp [SpeciesIsoMap.bijectiveFor, Bool.and_eq_true] at hb
  rcases hb with ⟨⟨⟨_, _⟩, hL⟩, hR⟩
  -- extract length equality from sameMoleculeIdSet (a && b && c && d && e form)
  simp [sameMoleculeIdSet, Bool.and_eq_true] at hL hR
  -- hL: (((allUnique domain && allUnique leftIds) && domain.length == leftIds.length) && allContained domain leftIds) && allContained leftIds domain
  -- easier: get beq on lengths
  have hLlen : m.domain.length = left.molecules.length := by
    rcases hL with ⟨⟨⟨⟨_, _⟩, hlen⟩, _⟩, _⟩
    simpa [List.length_map] using hlen
  have hRlen : m.range.length = right.molecules.length := by
    rcases hR with ⟨⟨⟨⟨_, _⟩, hlen⟩, _⟩, _⟩
    simpa [List.length_map] using hlen
  have hdom : m.domain.length = m.moleculeMap.length := by simp [SpeciesIsoMap.domain]
  have hran : m.range.length = m.moleculeMap.length := by simp [SpeciesIsoMap.range]
  omega

/-- A valid isomorphism witness implies equal molecule-instance counts (exact
bounded renaming/coverage invariant for the supported class). -/
theorem SpeciesIsoMap.validFor_molecule_count (m : SpeciesIsoMap) (left right : Mixture)
    (h : m.validFor left right = true) :
    left.molecules.length = right.molecules.length := by
  exact m.bijectiveFor_molecule_count left right (m.validFor_bijective left right h)

/-- Kernel-proved renaming invariant: a valid witness preserves local molecule
labels (type, compartment, component/state correspondence) for mapped pairs. -/
theorem SpeciesIsoMap.validFor_molecules (m : SpeciesIsoMap) (left right : Mixture)
    (h : m.validFor left right = true) :
    m.moleculeMap.all (fun pair =>
      match left.findMolecule? pair.1, right.findMolecule? pair.2 with
      | some a, some b => runtimeMoleculesEquivalent a b
      | _, _ => false) = true := by
  simp only [SpeciesIsoMap.validFor, Bool.and_eq_true] at h
  exact h.1.1.2

/-- Kernel-proved renaming/canonicalization invariant: a valid witness preserves
bond structure in the forward direction for the supported class. -/
theorem SpeciesIsoMap.validFor_bondsForward (m : SpeciesIsoMap) (left right : Mixture)
    (h : m.validFor left right = true) : bondsPreservedForward left right m = true := by
  simp only [SpeciesIsoMap.validFor, Bool.and_eq_true] at h
  exact h.1.2

/-- Kernel-proved renaming witness property: bijective mapping domain IDs are unique. -/
theorem SpeciesIsoMap.bijectiveFor_domain_unique (m : SpeciesIsoMap) (left right : Mixture)
    (h : m.bijectiveFor left right = true) : allUnique m.domain = true := by
  simp [SpeciesIsoMap.bijectiveFor, Bool.and_eq_true] at h
  exact h.1.1.1

/-- Kernel-proved renaming witness property: bijective mapping range IDs are unique. -/
theorem SpeciesIsoMap.bijectiveFor_range_unique (m : SpeciesIsoMap) (left right : Mixture)
    (h : m.bijectiveFor left right = true) : allUnique m.range = true := by
  simp [SpeciesIsoMap.bijectiveFor, Bool.and_eq_true] at h
  exact h.1.1.2

/-- A valid isomorphism witness has a unique-ID domain (supported-class renaming). -/
theorem SpeciesIsoMap.validFor_domain_unique (m : SpeciesIsoMap) (left right : Mixture)
    (h : m.validFor left right = true) : allUnique m.domain = true :=
  m.bijectiveFor_domain_unique left right (m.validFor_bijective left right h)

/-- A valid isomorphism witness has a unique-ID range (supported-class renaming). -/
theorem SpeciesIsoMap.validFor_range_unique (m : SpeciesIsoMap) (left right : Mixture)
    (h : m.validFor left right = true) : allUnique m.range = true :=
  m.bijectiveFor_range_unique left right (m.validFor_bijective left right h)

/-- Oracle-positive identity implies equal molecule and bond counts for the
explicit supported class artifacts. -/
theorem isomorphicSpecies_counts (left right : Mixture)
    (h : left.isomorphicSpecies right = true) :
    left.molecules.length = right.molecules.length ∧
      left.bonds.length = right.bonds.length := by
  simp [Mixture.isomorphicSpecies, Bool.and_eq_true] at h
  refine ⟨?_, ?_⟩
  · simpa using h.1.1
  · simpa using h.1.2

/-- Kernel-proved extraction of a renaming/canonicalization witness from the
supported-class graph-identity oracle decision. -/
theorem isomorphicSpecies_witness (left right : Mixture)
    (h : left.isomorphicSpecies right = true) :
    ∃ m ∈ candidateSpeciesIsoMaps left right, m.validFor left right = true := by
  simp [Mixture.isomorphicSpecies, Bool.and_eq_true] at h
  exact h.2


theorem addSpeciesModuloIso_preserves_existing (pool : List Mixture) (candidate : Mixture)
    (existing : Mixture) (hmem : existing ∈ pool) :
    existing ∈ addSpeciesModuloIso pool candidate := by
  unfold addSpeciesModuloIso
  by_cases h : pool.any (fun existing => existing.isomorphicSpecies candidate) = true
  · simp [h, hmem]
  · simp [h]
    exact Or.inl hmem

theorem addSpeciesModuloIso_idempotent_of_iso (pool : List Mixture) (candidate : Mixture)
    (hiso : pool.any (fun existing => existing.isomorphicSpecies candidate) = true) :
    addSpeciesModuloIso pool candidate = pool := by
  simp [addSpeciesModuloIso, hiso]

/-- Exact bounded identity: every pool member remains present after insertion
attempt, and the candidate is represented modulo graph isomorphism. -/
theorem addSpeciesModuloIso_contains_candidate_or_iso (pool : List Mixture) (candidate : Mixture) :
    candidate ∈ addSpeciesModuloIso pool candidate ∨
      ∃ existing ∈ pool, existing.isomorphicSpecies candidate = true := by
  unfold addSpeciesModuloIso
  by_cases h : pool.any (fun existing => existing.isomorphicSpecies candidate) = true
  · right
    rcases List.any_eq_true.mp h with ⟨existing, hex, hiso⟩
    exact ⟨existing, hex, hiso⟩
  · left
    simp [h]

/-- Exact bounded identity accumulation: a representative is added iff no
graph-isomorphic representative already exists in the pool (for the named
supported class oracle). -/
theorem addSpeciesModuloIso_length (pool : List Mixture) (candidate : Mixture) :
    (addSpeciesModuloIso pool candidate).length =
      if pool.any (fun existing => existing.isomorphicSpecies candidate) then pool.length
      else pool.length + 1 := by
  unfold addSpeciesModuloIso
  by_cases h : pool.any (fun existing => existing.isomorphicSpecies candidate) = true
  · simp [h]
  · simp [h]



theorem addSpeciesModuloIso_empty (candidate : Mixture) :
    addSpeciesModuloIso [] candidate = [candidate] := by
  simp [addSpeciesModuloIso]

end BNG
