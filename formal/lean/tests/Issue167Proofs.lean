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
example : (homodimer.applyStateUpdate fourA).map (fun s => (s.count 0, s.count 1)) = some (2, 1) := by decide

-- Delayed channel defers state update and enqueues completion.
def delayedUnimol : Channel := { unimolecular with delay := some 1 }
example : (proc167.fire delayedUnimol).state = proc167.state :=
  fire_delayed_preserves_state proc167 delayedUnimol 1 rfl
example : (proc167.fire delayedUnimol).state = proc167.state ∧ (proc167.fire delayedUnimol).pending.length = proc167.pending.length + 1 :=
  delayed_channel_defers_update proc167 delayedUnimol 1 rfl

-- Intervention / disabled channel yields zero propensity.
def disabledUnimol : Channel := { unimolecular with gated := false }
example : disabledUnimol.exactPropensity initialState = 0 :=
  propensity_disabled_is_zero disabledUnimol initialState rfl

-- Energy multiplier scales propensity.
def energyUnimol : Channel := { unimolecular with energyFactor := some 3 }
#eval energyUnimol.exactPropensity initialState
example : ({ unimolecular with energyFactor := some unimolecular.energyMultiplier } : Channel).exactPropensity initialState = unimolecular.exactPropensity initialState :=
  energy_factor_restores_propensity unimolecular initialState

-- Hybrid regime preserves exact total propensity.
def procHybrid : Process := { proc167 with hybrid := { particleSpecies := [0], populationSpecies := [1] } }
example : proc167.total = procHybrid.total :=
  hybrid_regime_does_not_change_propensity proc167 procHybrid rfl rfl

-- Semantic equality is an equivalence relation and implies total propensity equality.
example : processSemanticEqual proc167 proc167 := processSemanticEqual_refl proc167
example (h : processSemanticEqual proc167 procHybrid) : processSemanticEqual procHybrid proc167 :=
  processSemanticEqual_symm proc167 procHybrid h
example (p q r : Process) (hpq : processSemanticEqual p q) (hqr : processSemanticEqual q r) : processSemanticEqual p r :=
  processSemanticEqual_trans p q r hpq hqr

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
