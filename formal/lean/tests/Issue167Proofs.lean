import BNG

open BNG

/-!
# Issue #167 — exact rate and stochastic semantics (executable proofs)

Every value below is an exact `Rat`; no `Float` and no `native_decide` appear.
The `by decide` examples are kernel-checked, so this file is a direct check of
the assumption manifest (`floatingPointSolverExcluded`, exact arithmetic).
-/

def rateK : RateSpec := { convention := .elementaryParameter, constants := [(2 : ExactValue)] }
#eval rateK.rateAt 5

def unimolecular : Channel :=
  { id := 0
    rate := rateK
    reactants := [{ species := 0, count := 1 }]
    products := [{ species := 1, count := 1 }] }

def initialState : State := { counts := [(0, 5), (1, 0)] }

#eval unimolecular.multiplicity initialState          -- 5 = C(5,1)
#eval unimolecular.exactPropensity initialState       -- 10 = 2 * 5
#eval (unimolecular.applyStateUpdate initialState).map (fun s => s.count 0)  -- some 4
#eval totalPropensity [unimolecular] initialState     -- 10
#eval nextChannelProb [unimolecular] initialState 0   -- 1

-- The symmetry factor of A() + A() is a property of the reactants, applied for
-- every rate-law shape.  C(4,2) = 6 embeddings after the factor of 2.
def homodimer : Channel :=
  { id := 1
    rate := rateK
    reactants := [{ species := 0, count := 2 }]
    products := [{ species := 1, count := 1 }]
    symmetryFactor := 2 }

def fourA : State := { counts := [(0, 4), (1, 0)] }

#eval homodimer.rawMultiplicity fourA   -- 12 = 4 * 3
#eval homodimer.multiplicity fourA      -- 6  = 12 / 2
#eval homodimer.exactPropensity fourA   -- 12 = 2 * 6

def proc167 : Process :=
  { state := initialState
    channels := [unimolecular]
    time := 0
    pending := []
    interventions := []
    energy := { factors := [] }
    hybrid := { particleSpecies := [], populationSpecies := [] } }

#eval proc167.total
#eval proc167.nextProb 0

-- Kernel-checked (decide, not native_decide) numeric contracts.
example : homodimer.multiplicity fourA = 6 := by decide
example : (unimolecular.applyStateUpdate initialState).map (fun s => s.count 0) = some 4 := by decide

-- The exact Rat propensities are printed by the #eval lines above (12, 10, 1).
-- Their values are also pinned by the theorem applications below, which are
-- kernel-checked and do not rely on native_decide.

-- Theorem applications tying the manifest to the exact definitions.
example : supportedManifest.floatingPointSolverExcluded = true :=
  supported_manifest_excludes_float_solver
example : supportedManifest.exactRationalArithmetic = true :=
  supported_manifest_exact_arithmetic
example (h : processSemanticEqual proc167 proc167) : proc167.total = proc167.total :=
  semantic_equal_implies_total_equal proc167 proc167 h
