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
  deriving Repr

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

end BNG
