import BNG

open BNG

namespace BNG.PropensityCountingBridge

/-!
Bounded stable propensity/counting correspondence slice (#167-adjacent).

Scope/assumptions (stated exactly):
- explicit finite runtime mixtures and compiled rule directions defined below;
- counts/flags checked: `RuleDirection.countedMatches.length`,
  `RuleDirection.channelMultiplicity`, `RuleDirection.hasMatchOnce`,
  `RuleDirection.hasTotalRate`, `RuleDirection.propensityContract.enabled`,
  `RuleDirection.propensityContract.interpretation`;
- this validates the formal counting/interpretation contract on named supported
  cases (including MatchOnce ordered-complex-key dedup and TotalRate
  interpretation) against an independent Python reference computation over the
  same explicit artifacts; it does not claim a full stochastic-engine trajectory
  correspondence and does not follow NFnext-moving behavior.
-/

abbrev MolId := MoleculeInstanceId
abbrev MolType := MoleculeTypeId
abbrev CompType := ComponentTypeId
abbrev St := StateId

def mtA : MolType := ⟨0⟩
def mtB : MolType := ⟨1⟩
def cAx : CompType := ⟨0⟩
def cBy : CompType := ⟨1⟩
def sU : St := ⟨0⟩
def sP : St := ⟨1⟩

def molA (id : Nat) (s : St) : RuntimeMolecule :=
  { id := ⟨id⟩, moleculeType := mtA, compartment := none,
    sites := [{ component := cAx, state := some s }] }
def molB (id : Nat) : RuntimeMolecule :=
  { id := ⟨id⟩, moleculeType := mtB, compartment := none,
    sites := [{ component := cBy, state := none }] }

-- Mixture: two separate A(x~u) and one B(y)
def mixAB : Mixture :=
  { nextMoleculeId := ⟨3⟩
    molecules := [molA 0 sU, molA 1 sU, molB 2]
    bonds := [] }

-- Patterns
def patA : Pattern :=
  { molecules := [
      { occurrence := ⟨0⟩
        moleculeType := mtA
        sites := [{ occurrence := ⟨0⟩, component := cAx, state := .exact sU }] }] }
def patB : Pattern :=
  { molecules := [
      { occurrence := ⟨0⟩
        moleculeType := mtB
        sites := [{ occurrence := ⟨0⟩, component := cBy }] }] }

def patAProd : Pattern := patA
def patBProd : Pattern := patB

-- Bimolecular A(x~u)+B(y) -> A(x~u)+B(y) (no-op-like rule shape for counting)
def dirBimol : RuleDirection :=
  { reactants := [patA, patB]
    products := [patAProd, patBProd]
    rate := { expression := .number 1.0 }
    mutations := []
    moleculeMap := [] }

-- Same rule with TotalRate
def dirBimolTotal : RuleDirection :=
  { dirBimol with modifiers := [.totalRate] }

-- Symmetric dimer in one complex: A(x~u!1).A(x~u!1)
def mixDimer : Mixture :=
  { nextMoleculeId := ⟨2⟩
    molecules := [molA 0 sU, molA 1 sU]
    bonds := [{ a := { molecule := ⟨0⟩, component := cAx }, b := { molecule := ⟨1⟩, component := cAx } }] }

-- Unimolecular pattern matching a molecule in that dimer context: A(x~u!+)
def patABound : Pattern :=
  { molecules := [
      { occurrence := ⟨0⟩
        moleculeType := mtA
        sites := [{ occurrence := ⟨0⟩, component := cAx, state := .exact sU, bonds := [.bound] }] }] }

def dirUni : RuleDirection :=
  { reactants := [patABound]
    products := [patABound]
    rate := { expression := .number 1.0 }
    mutations := []
    moleculeMap := [] }

def dirUniMatchOnce : RuleDirection :=
  { dirUni with modifiers := [.matchOnce] }

-- Two separate dimers A(x~u!1).A(x~u!1) and A(x~u!2).A(x~u!2)
def mixTwoDimers : Mixture :=
  { nextMoleculeId := ⟨4⟩
    molecules := [molA 0 sU, molA 1 sU, molA 2 sU, molA 3 sU]
    bonds :=
      [ { a := { molecule := ⟨0⟩, component := cAx }, b := { molecule := ⟨1⟩, component := cAx } }
      , { a := { molecule := ⟨2⟩, component := cAx }, b := { molecule := ⟨3⟩, component := cAx } } ] }

structure CaseResult where
  name : String
  multiplicity : Nat
  enabled : Bool
  perMatch : Bool
  deriving Repr

def interpPerMatch (p : PropensityContract) : Bool :=
  match p.interpretation with
  | .perMatch _ => true
  | .totalChannel => false

def mk (name : String) (d : RuleDirection) (mix : Mixture) : CaseResult :=
  let p := d.propensityContract mix
  { name := name
    multiplicity := p.legalMatchCount
    enabled := p.enabled
    perMatch := interpPerMatch p }

def results : List CaseResult :=
  [ mk "bimol_twoA_oneB" dirBimol mixAB
  , mk "bimol_twoA_oneB_totalRate" dirBimolTotal mixAB
  , mk "unimol_bound_in_dimer" dirUni mixDimer
  , mk "unimol_bound_in_dimer_matchOnce" dirUniMatchOnce mixDimer
  , mk "unimol_bound_in_two_dimers_matchOnce" dirUniMatchOnce mixTwoDimers
  ]

def emit (r : CaseResult) : String :=
  s!"case={r.name}\tmultiplicity={r.multiplicity}\tenabled={r.enabled}\tperMatch={r.perMatch}"

def main : IO Unit := do
  for r in results do
    IO.println (emit r)

end BNG.PropensityCountingBridge

def main := BNG.PropensityCountingBridge.main
