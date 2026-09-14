import BNG.Operational
import BNG.Model

namespace BNG

/-!
# Seed-species construction

Seed declarations should become concrete molecular graphs without a backend
re-parsing BNGL.  Construction is intentionally stricter than matching:
`any`, `bound`, and multi-state choices describe sets of possible graphs and
therefore cannot create one unique seed state without an additional convention.
-/

/-- Choose one concrete state for seed construction only when unambiguous. -/
def seedState? : StateConstraint → Option (Option StateId)
  | .any => some none
  | .exact state => some (some state)
  | .oneOf [state] => some (some state)
  | .oneOf _ => none

/-- Seed-site requirements must not require an unknown partner. -/
def seedBondRequirementsConstructible (requirements : List BondRequirement) : Bool :=
  requirements.all (fun req =>
    match req with
    | .free => true
    | .exact _ => true
    | .any => false
    | .bound => false)

/-- Instantiate concrete runtime sites for one seed molecule. -/
def seedSites? : List PatternSite → Option (List RuntimeSite)
  | [] => some []
  | site :: rest =>
      if !(seedBondRequirementsConstructible site.bonds) then none
      else
        match seedState? site.state, seedSites? rest with
        | some state, some tail =>
            some ({ component := site.component, state := state } :: tail)
        | _, _ => none

/-- Enumerate pattern molecules with fresh runtime IDs starting at `next`. -/
def instantiateSeedMolecules? : Nat → List PatternMolecule → Option (List RuntimeMolecule × Nat)
  | next, [] => some ([], next)
  | next, molecule :: rest =>
      match seedSites? molecule.sites, instantiateSeedMolecules? (next + 1) rest with
      | some sites, some (tail, cursor) =>
          some ({ id := ⟨next⟩
                  moleculeType := molecule.moleculeType
                  compartment := molecule.compartment
                  sites := sites } :: tail, cursor)
      | _, _ => none

/-- Runtime molecule ID assigned to one seed pattern occurrence. -/
def seedRuntimeId? (pattern : Pattern) (id : PatternMoleculeId) : Option MoleculeInstanceId :=
  let rec go : Nat → List PatternMolecule → Option MoleculeInstanceId
    | _, [] => none
    | next, molecule :: rest =>
        if molecule.occurrence == id then some ⟨next⟩ else go (next + 1) rest
  go 0 pattern.molecules

/-- Translate one explicit seed bond into concrete runtime endpoints. -/
def seedBond? (pattern : Pattern) (bond : PatternBond) : Option RuntimeBond :=
  match pattern.findMolecule? bond.a.molecule,
    pattern.findMolecule? bond.b.molecule,
    seedRuntimeId? pattern bond.a.molecule,
    seedRuntimeId? pattern bond.b.molecule with
  | some leftMolecule, some rightMolecule, some leftId, some rightId =>
      match leftMolecule.findSite? bond.a.site, rightMolecule.findSite? bond.b.site with
      | some leftSite, some rightSite =>
          some {
            a := { molecule := leftId, component := leftSite.component }
            b := { molecule := rightId, component := rightSite.component } }
      | _, _ => none
  | _, _, _, _ => none

/-- Translate all explicit pattern bonds atomically. -/
def seedBonds? (pattern : Pattern) : List PatternBond → Option (List RuntimeBond)
  | [] => some []
  | bond :: rest =>
      match seedBond? pattern bond, seedBonds? pattern rest with
      | some head, some tail => some (head :: tail)
      | _, _ => none

/-- Instantiate one semantic seed pattern as a concrete molecular species. -/
def Pattern.instantiateSeed? (pattern : Pattern) : Option Mixture :=
  match instantiateSeedMolecules? 0 pattern.molecules, seedBonds? pattern pattern.bonds with
  | some (molecules, cursor), some bonds =>
      some { nextMoleculeId := ⟨cursor⟩, molecules := molecules, bonds := bonds }
  | _, _ => none

/-- Resolve a compiled seed declaration to its concrete species shape. -/
def SeedDecl.species? (seed : SeedDecl) : Option Mixture :=
  seed.pattern.instantiateSeed?

end BNG
