import BNG

open BNG

namespace BNG.GraphIdentityBridge

/-- Formal bridge fixtures for #168 graph identity/canonicalization.

Each case compares two runtime-mixture graph artifacts via the typed
isomorphism oracle (`Mixture.isomorphicSpecies`) and bounded dedup
(`addSpeciesModuloIso`).  Case names/decisions must agree with the independent
production-artifact bridge script `formal/lean/scripts/check_graph_identity_bridge.py`.
-/

abbrev MolId := MoleculeInstanceId
abbrev MolType := MoleculeTypeId
abbrev CompType := ComponentTypeId
abbrev St := StateId

def mtA : MolType := ⟨0⟩
def mtB : MolType := ⟨1⟩
def cAx : CompType := ⟨0⟩
def cAy : CompType := ⟨1⟩  -- A.a/y-like generic sites for rings
def cAa : CompType := ⟨2⟩
def cAb : CompType := ⟨3⟩
def cBy : CompType := ⟨4⟩
def cBx : CompType := ⟨5⟩
def sU : St := ⟨0⟩
def sP : St := ⟨1⟩

def molA_x (id : Nat) (state : St) : RuntimeMolecule :=
  { id := ⟨id⟩, moleculeType := mtA, compartment := none,
    sites := [{ component := cAx, state := some state }] }

def molB_y (id : Nat) : RuntimeMolecule :=
  { id := ⟨id⟩, moleculeType := mtB, compartment := none,
    sites := [{ component := cBy, state := none }] }

def molB_xu (id : Nat) : RuntimeMolecule :=
  { id := ⟨id⟩, moleculeType := mtB, compartment := none,
    sites := [{ component := cBx, state := some sU }] }

def molA_ab (id : Nat) : RuntimeMolecule :=
  { id := ⟨id⟩, moleculeType := mtA, compartment := none,
    sites := [{ component := cAa, state := none }, { component := cAb, state := none }] }

def bondedBase : Mixture :=
  { nextMoleculeId := ⟨2⟩, molecules := [molA_x 0 sU, molB_y 1],
    bonds := [{ a := { molecule := ⟨0⟩, component := cAx }, b := { molecule := ⟨1⟩, component := cBy } }] }

def bondedRenamed : Mixture :=
  { nextMoleculeId := ⟨50⟩, molecules := [molB_y 8, molA_x 7 sU],
    bonds := [{ a := { molecule := ⟨8⟩, component := cBy }, b := { molecule := ⟨7⟩, component := cAx } }] }

def bondedStateMut : Mixture :=
  { nextMoleculeId := ⟨2⟩, molecules := [molA_x 0 sP, molB_y 1],
    bonds := [{ a := { molecule := ⟨0⟩, component := cAx }, b := { molecule := ⟨1⟩, component := cBy } }] }

def bondedTopologyMut : Mixture :=
  { nextMoleculeId := ⟨2⟩, molecules := [molA_x 0 sU, molB_y 1], bonds := [] }

def bondedAttachmentMut : Mixture :=
  { nextMoleculeId := ⟨2⟩, molecules := [molA_x 0 sU, molB_xu 1],
    bonds := [{ a := { molecule := ⟨0⟩, component := cAx }, b := { molecule := ⟨1⟩, component := cBx } }] }

-- A(a!1,b!2).A(a!2,b!3).A(a!3,b!1)  (3-cycle)
def ringBase : Mixture :=
  { nextMoleculeId := ⟨3⟩
    molecules := [molA_ab 0, molA_ab 1, molA_ab 2]
    bonds :=
      [ { a := { molecule := ⟨0⟩, component := cAa }, b := { molecule := ⟨1⟩, component := cAa } } -- !1 between 0.a-1.a (arbitrary consistent labels)
      , { a := { molecule := ⟨0⟩, component := cAb }, b := { molecule := ⟨2⟩, component := cAa } } -- !2
      , { a := { molecule := ⟨1⟩, component := cAb }, b := { molecule := ⟨2⟩, component := cAb } } -- !3
      ] }

-- permuted/relabelled ring: different IDs, different endpoint ordering
def ringPermuted : Mixture :=
  { nextMoleculeId := ⟨30⟩
    molecules := [molA_ab 20, molA_ab 21, molA_ab 22]
    bonds :=
      [ { a := { molecule := ⟨22⟩, component := cAb }, b := { molecule := ⟨21⟩, component := cAb } }
      , { a := { molecule := ⟨22⟩, component := cAa }, b := { molecule := ⟨20⟩, component := cAb } }
      , { a := { molecule := ⟨21⟩, component := cAa }, b := { molecule := ⟨20⟩, component := cAa } }
      ] }

-- open chain mutation: break one bond
def ringOpenMut : Mixture :=
  { nextMoleculeId := ⟨3⟩
    molecules := [molA_ab 0, molA_ab 1, molA_ab 2]
    bonds :=
      [ { a := { molecule := ⟨0⟩, component := cAb }, b := { molecule := ⟨2⟩, component := cAa } }
      , { a := { molecule := ⟨1⟩, component := cAb }, b := { molecule := ⟨2⟩, component := cAb } }
      ] }

structure CaseResult where
  name : String
  iso : Bool
  leftPool : Nat
  dedupPool : Nat
  deriving Repr

def mkCase (name : String) (left right : Mixture) : CaseResult :=
  let iso := left.isomorphicSpecies right
  let pool := [left]
  { name := name, iso := iso, leftPool := pool.length, dedupPool := (addSpeciesModuloIso pool right).length }


/-! ## Kernel-checked properties for the named supported class fixtures -/

-- Reflexive identity on concrete artifacts (renaming/canonical representative baseline).
example : bondedBase.isomorphicSpecies bondedBase = true := by native_decide
example : ringBase.isomorphicSpecies ringBase = true := by native_decide
-- Symmetric positive witnesses on explicit permutation/renaming pairs.
example : bondedRenamed.isomorphicSpecies bondedBase = true := by native_decide
example : ringPermuted.isomorphicSpecies ringBase = true := by native_decide
-- Adversarial negatives remain rejected in the opposite direction.
example : bondedStateMut.isomorphicSpecies bondedBase = false := by native_decide
example : ringOpenMut.isomorphicSpecies ringBase = false := by native_decide
-- Exact bounded identity accumulation (no duplicate iso representative).
example : (addSpeciesModuloIso [bondedRenamed] bondedBase).length = 1 := by native_decide
example : (addSpeciesModuloIso [ringPermuted] ringBase).length = 1 := by native_decide
example : (addSpeciesModuloIso [bondedStateMut] bondedBase).length = 2 := by native_decide


def results : List CaseResult :=
  [ mkCase "bonded_renamed_equal" bondedBase bondedRenamed
  , mkCase "bonded_state_mutation_unequal" bondedBase bondedStateMut
  , mkCase "bonded_topology_mutation_unequal" bondedBase bondedTopologyMut
  , mkCase "bonded_attachment_mutation_unequal" bondedBase bondedAttachmentMut
  , mkCase "ring_permutation_equal" ringBase ringPermuted
  , mkCase "ring_open_mutation_unequal" ringBase ringOpenMut ]

def emit (r : CaseResult) : String :=
  s!"case={r.name}\tiso={r.iso}\tleft_pool={r.leftPool}\tdedup_pool={r.dedupPool}"

def main : IO Unit := do
  for r in results do
    IO.println (emit r)

end BNG.GraphIdentityBridge

def main := BNG.GraphIdentityBridge.main
