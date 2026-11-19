import BNG.Model
import BNG.Propensity
import BNG.Stochastic
import BNG.Protocol
import BNG.Hybrid
import BNG.ExtendedOperational

namespace BNG

/-!
# Exact rate and stochastic process semantics (issue #167)

This module completes the executable *definitions* that the formal rate and
stochastic work shares across every consumer:

* exact (rational) rate conventions and exact propensities;
* reactant symmetry / multiplicity factors;
* exact state updates;
* a stochastic one-event kernel over exact propensities;
* process definitions extended with delayed completions, protocol
  interventions, energy factors and hybrid particle/population state;
* one shared definition used by **both** execution correspondence and semantic
  equality.

Numerical floating-point ODE/SSA solver behaviour is deliberately **not**
proved here.  Every quantity below is an exact `Rat`; the manifest at the end
records that exclusion explicitly.  This is the boundary the selected
refinement statements are allowed to claim (issue #167 acceptance criterion 2).
-/

/-! ## 1. Exact numeric domain and rate conventions -/

/-- Exact value domain.  No `Float` appears in this module: a propensity is a
rational number, so "exact propensity" is a definitional property, not a
tolerance. -/
abbrev ExactValue := Rat

/-- A discrete species count. -/
abbrev SpeciesCount := Nat

/-- The supported rate-law conventions of the qualified ensemble.  Every other
BNGL rate convention is outside this slice (issue #167 boundary 1). -/
inductive RateConvention where
  | elementaryParameter
  | localFunction
  | localFunctionState
  | builtin
  | tfun
  | saturation
  | hill
  | michaelisMenten
  deriving Repr, DecidableEq, BEq

/-- A resolved rate law under one supported convention.  `constants` holds the
exact rational parameters (`k`, `kcat`, `K`, ...); `exponent` is the Hill order
and is irrelevant for the other conventions. -/
structure RateSpec where
  convention : RateConvention
  constants : List ExactValue
  exponent : Nat := 1
  deriving Repr, DecidableEq

/-- Exact rate of one channel at its primary reactant count.  The
symmetry/multiplicity factor is *not* folded into this value; it is applied by
`Channel.exactPropensity`, matching canonical BNG2 where the factor is a prefix
on the rate law for every rate-law shape. -/
def RateSpec.rateAt (r : RateSpec) (n : SpeciesCount) : Option ExactValue :=
  let nr : ExactValue := (n : ExactValue)
  match r.convention, r.constants with
  | .elementaryParameter, [k] => some k
  | .localFunction, [k] => some k
  | .localFunctionState, [k] => some (k * nr)
  | .builtin, [k] => some k
  | .tfun, [k] => some k
  | .saturation, [kcat, K] =>
      if K + nr = 0 then none else some (kcat / (K + nr))
  | .hill, [v, K] =>
      -- Hill(k,K,h) is already the total hazard k*n^h/(K^h+n^h) at count n.
      -- Return the per-molecule base so the shared multiplicity factor n gives
      -- exactly that hazard (not n times too large).
      let den : ExactValue := K ^ r.exponent + nr ^ r.exponent
      if den = 0 then none
      else if n = 0 then some 0
      else some (v * nr ^ (r.exponent - 1) / den)
  | .michaelisMenten, [v, K] =>
      if K + nr = 0 then none else some (v / (K + nr))
  | _, _ => none

/-- The rate conventions with a resolved, evaluable parameter list. -/
def RateSpec.wellFormed (r : RateSpec) : Bool :=
  (r.rateAt 1).isSome

/-! ## 2. Discrete state and exact state updates -/

structure State where
  counts : List (Nat × SpeciesCount)
  deriving Repr, DecidableEq

namespace State

def count (s : State) (id : Nat) : SpeciesCount :=
  match s.counts.find? (fun p => p.1 == id) with
  | some p => p.2
  | none => 0

def setCount (s : State) (id n : Nat) : State :=
  { s with
    counts :=
      if s.counts.any (fun p => p.1 == id) then
        s.counts.map (fun p => if p.1 == id then (id, n) else p)
      else
        (id, n) :: s.counts }

/-- Consume stoichiometry, failing on underflow (a disabled channel). -/
def consume (s : State) : List (Nat × Nat) → Option State
  | [] => some s
  | (id, k) :: rest =>
      let available := s.count id
      if available < k then none
      else (s.setCount id (available - k)).consume rest

/-- Produce stoichiometry (saturating at natural-number addition). -/
def produce (s : State) : List (Nat × Nat) → State
  | [] => s
  | (id, k) :: rest => (s.setCount id (s.count id + k)).produce rest

end State

/-! ## 3. Channels, symmetry factors and exact propensities -/

structure Stoich where
  species : Nat
  count : Nat
  deriving Repr, DecidableEq, BEq

/-- A stochastic reaction channel.  `symmetryFactor` is the combinatorial
symmetry of the reactant multiset (2 for `A + A`), `totalRate` selects the
`TotalRate` interpretation, `energyFactor` is an exact integer Boltzmann
multiplier, `gated` records protocol enable/disable, and `delay` schedules a
delayed completion. -/
structure Channel where
  id : Nat
  rate : RateSpec
  reactants : List Stoich
  products : List Stoich
  symmetryFactor : Nat := 1
  totalRate : Bool := false
  matchOnce : Bool := false
  delay : Option ExactValue := none
  energyFactor : Option Nat := none
  gated : Bool := true
  deriving Repr

/-- Ordered embeddings of `k` distinct molecules drawn from `n`: n(n-1)... -/
def fallingFactorial : Nat → Nat → Nat
  | _, 0 => 1
  | m, k + 1 => m * fallingFactorial (m - 1) k

namespace Channel

def gatedStoich (xs : List Stoich) : List (Nat × Nat) :=
  xs.map (fun s => (s.species, s.count))

/-- Ordered reactant embeddings before symmetry correction: the product of
falling factorials n(n-1)... for each reactant species. -/
def rawMultiplicity (ch : Channel) (s : State) : Nat :=
  ch.reactants.foldl
    (fun acc reactant => acc * fallingFactorial (s.count reactant.species) reactant.count)
    1

/-- Symmetry-corrected multiplicity.  The factor belongs to the reactants, not
to the shape of the rate law. -/
def multiplicity (ch : Channel) (s : State) : Nat :=
  let raw := ch.rawMultiplicity s
  if ch.symmetryFactor = 0 then 0 else raw / ch.symmetryFactor

def primaryCount (ch : Channel) (s : State) : Nat :=
  match ch.reactants with
  | [] => 0
  | r :: _ => s.count r.species

def enabled (ch : Channel) (s : State) : Bool :=
  ch.gated && ch.reactants.all (fun r => s.count r.species >= r.count)

def energyMultiplier (ch : Channel) : Nat :=
  match ch.energyFactor with
  | some e => e
  | none => 1

/-- The single exact propensity definition.  Every consumer (correspondence,
semantic equality, the CTMC kernel and the production comparison) calls this
one function. -/
def exactPropensity (ch : Channel) (s : State) : ExactValue :=
  if !ch.enabled s then 0
  else
    let base := match ch.rate.rateAt (ch.primaryCount s) with
      | some v => v
      | none => 0
    let mult : Nat := if ch.totalRate then 1 else ch.multiplicity s
    base * (mult : ExactValue) * (ch.energyMultiplier : ExactValue)

/-- Apply the exact stoichiometry update. -/
def applyStateUpdate (ch : Channel) (s : State) : Option State :=
  match s.consume (gatedStoich ch.reactants) with
  | none => none
  | some mid => some (mid.produce (gatedStoich ch.products))

end Channel

/-! ## 4. Stochastic one-event kernel over exact propensities -/

/-- The exact CTMC kernel: the probability channel `id` is the next firing is
its exact propensity divided by the total exact propensity. -/
def totalPropensity (channels : List Channel) (s : State) : ExactValue :=
  channels.foldl (fun acc ch => acc + ch.exactPropensity s) 0

def propensityOf (channels : List Channel) (s : State) (id : Nat) : ExactValue :=
  match channels.find? (fun ch => ch.id == id) with
  | some ch => ch.exactPropensity s
  | none => 0

def nextChannelProb (channels : List Channel) (s : State) (id : Nat) : ExactValue :=
  let total := totalPropensity channels s
  if total = 0 then 0 else propensityOf channels s id / total

/-! ## 5. Extended process definitions -/

structure DelayedCompletion where
  channelId : Nat
  fireAt : ExactValue
  deriving Repr, DecidableEq

/-- Protocol interventions are part of the process, so they cannot be silently
reinterpreted by a consuming backend. -/
inductive Intervention where
  | enable (channelId : Nat)
  | disable (channelId : Nat)
  | setRate (channelId : Nat) (rate : RateSpec)
  deriving Repr, DecidableEq

def applyIntervention : List Channel → Intervention → List Channel
  | [], _ => []
  | ch :: rest, iv =>
      let ch' :=
        match iv with
        | .enable id => if ch.id == id then { ch with gated := true } else ch
        | .disable id => if ch.id == id then { ch with gated := false } else ch
        | .setRate id rate => if ch.id == id then { ch with rate := rate } else ch
      ch' :: applyIntervention rest iv

/-- Energy state holds exact Boltzmann multipliers keyed by channel. -/
structure EnergyState where
  factors : List (Nat × Nat)
  deriving Repr, DecidableEq

/-- Hybrid state records which species occupy the particle and population
regimes.  Propensity semantics is regime-independent: both regimes consume the
same exact counts. -/
structure HybridState where
  particleSpecies : List Nat
  populationSpecies : List Nat
  deriving Repr, DecidableEq

namespace HybridState

def regimeOf (h : HybridState) (id : Nat) : Option Bool :=
  if h.particleSpecies.contains id then some true
  else if h.populationSpecies.contains id then some false
  else none

end HybridState

structure Process where
  state : State
  channels : List Channel
  time : ExactValue
  pending : List DelayedCompletion
  interventions : List Intervention
  energy : EnergyState
  hybrid : HybridState
  deriving Repr

namespace Process

def total (p : Process) : ExactValue := totalPropensity p.channels p.state

def nextProb (p : Process) (id : Nat) : ExactValue := nextChannelProb p.channels p.state id

/-- Schedule a delayed completion.  A delayed channel does not mutate the state
until its scheduled time; the exact propensity definition is unchanged. -/
def scheduleDelayed (p : Process) (ch : Channel) : Process :=
  match ch.delay with
  | some d =>
      { p with pending := p.pending ++ [{ channelId := ch.id, fireAt := p.time + d }] }
  | none => p

/-- Fire one channel.  Delayed channels only enqueue; immediate channels apply
their exact state update. -/
def fire (p : Process) (ch : Channel) : Process :=
  let p' := p.scheduleDelayed ch
  match ch.delay with
  | some _ => p'
  | none =>
      match ch.applyStateUpdate p'.state with
      | some s => { p' with state := s }
      | none => p'

/-- Apply the whole typed protocol in order. -/
def runProtocol (p : Process) : Process :=
  { p with channels := p.interventions.foldl applyIntervention p.channels }

end Process

/-! ## 6. One shared definition for execution correspondence and semantic equality -/

/-- A trace step records the channel, the exact propensity and the exact
before/after states.  It is produced by the SAME `Channel.exactPropensity` and
`Channel.applyStateUpdate` definitions the kernel uses. -/
structure TraceStep where
  channelId : Nat
  propensity : ExactValue
  before : State
  after : State
  deriving Repr, DecidableEq

def formalTraceStep (p : Process) (ch : Channel) : Option TraceStep :=
  match ch.applyStateUpdate p.state with
  | none => none
  | some after =>
      some
        { channelId := ch.id
          propensity := ch.exactPropensity p.state
          before := p.state
          after := after }

/-- Execution correspondence is judged pointwise against the production trace
using the same `TraceStep` and the same exact propensity field. -/
def corresponds (formal production : TraceStep) : Prop :=
  formal.channelId = production.channelId ∧
    formal.propensity = production.propensity ∧
    formal.before = production.before ∧
    formal.after = production.after

/-- Sort (id, propensity) pairs by id for a spelling-independent canonical
signature.  Source names never enter: only canonical ids and exact values. -/
def insortPair (x : Nat × ExactValue) : List (Nat × ExactValue) → List (Nat × ExactValue)
  | [] => [x]
  | y :: ys => if x.1 <= y.1 then x :: y :: ys else y :: insortPair x ys

def sortPairs : List (Nat × ExactValue) → List (Nat × ExactValue)
  | [] => []
  | x :: xs => insortPair x (sortPairs xs)

/-- Canonical signature: exact propensity of every channel at the current
state, keyed by canonical id. -/
def Process.signature (p : Process) : List (Nat × ExactValue) :=
  sortPairs (p.channels.map (fun ch => (ch.id, ch.exactPropensity p.state)))

/-- Semantic equality uses the identical `exactPropensity` definition as
correspondence.  It is equality of canonical signatures and total, never a
numerical similarity of trajectories. -/
def processSemanticEqual (p q : Process) : Prop :=
  p.signature = q.signature ∧ p.total = q.total

/-! ## 7. Assumption manifest -/

/-- Explicit assumptions under which the statements in this module are made.
`floatingPointSolverExcluded` records that no floating-point solver accuracy
claim is part of this formal result. -/
structure AssumptionManifest where
  exactRationalArithmetic : Bool
  finiteChannelSet : Bool
  symmetryFactorFromReactants : Bool
  totalRateContractExplicit : Bool
  delayedCompletionExplicit : Bool
  floatingPointSolverExcluded : Bool
  deriving Repr, DecidableEq

def supportedManifest : AssumptionManifest :=
  { exactRationalArithmetic := true
    finiteChannelSet := true
    symmetryFactorFromReactants := true
    totalRateContractExplicit := true
    delayedCompletionExplicit := true
    floatingPointSolverExcluded := true }

/-! ## Theorems -/

theorem rateAt_unimolecular (k n : Nat) :
    ({ convention := .elementaryParameter, constants := [(k : ExactValue)] } : RateSpec).rateAt n
      = some (k : ExactValue) := by
  simp [RateSpec.rateAt]

theorem propensity_disabled_is_zero (ch : Channel) (s : State) (h : ch.gated = false) :
    ch.exactPropensity s = 0 := by
  simp [Channel.exactPropensity, Channel.enabled, h]

theorem propensity_respects_canonical_fields (a b : Channel) (s : State)
    (h : a.rate = b.rate ∧ a.reactants = b.reactants ∧ a.products = b.products ∧
      a.symmetryFactor = b.symmetryFactor ∧ a.totalRate = b.totalRate ∧
      a.energyFactor = b.energyFactor ∧ a.gated = b.gated ∧ a.delay = b.delay) :
    a.exactPropensity s = b.exactPropensity s := by
  rcases h with ⟨hr, hre, hpr, hsy, ht, he, hg, hd⟩
  simp [Channel.exactPropensity, Channel.enabled, Channel.primaryCount, Channel.multiplicity,
    Channel.rawMultiplicity, Channel.energyMultiplier, hr, hre, hsy, ht, he, hg]

theorem energy_factor_restores_propensity (ch : Channel) (s : State) :
    ({ ch with energyFactor := some ch.energyMultiplier } : Channel).exactPropensity s =
      ch.exactPropensity s := by
  simp [Channel.exactPropensity, Channel.enabled, Channel.primaryCount, Channel.multiplicity,
    Channel.rawMultiplicity, Channel.energyMultiplier]

theorem intervention_disable_zero_propensity (channels : List Channel) (id : Nat) (s : State) :
    (match (applyIntervention channels (.disable id)).find? (fun ch => ch.id == id) with
      | some ch => ch.exactPropensity s = 0
      | none => True) := by
  induction channels with
  | nil => simp [applyIntervention]
  | cons ch rest ih =>
      by_cases hid : ch.id == id
      · simp [applyIntervention, hid, Channel.exactPropensity, Channel.enabled]
      · simpa [applyIntervention, hid] using ih

theorem hybrid_regime_does_not_change_propensity (p q : Process)
    (hs : p.state = q.state) (hc : p.channels = q.channels) :
    p.total = q.total := by
  simp [Process.total, hs, hc]

theorem fire_delayed_preserves_state (p : Process) (ch : Channel) (d : ExactValue)
    (h : ch.delay = some d) :
    (p.fire ch).state = p.state := by
  simp [Process.fire, Process.scheduleDelayed, h]

theorem formal_trace_uses_exact_propensity (p : Process) (ch : Channel) :
    (formalTraceStep p ch).map TraceStep.propensity = some (ch.exactPropensity p.state) ∨
      (formalTraceStep p ch).map TraceStep.propensity = none := by
  unfold formalTraceStep
  cases ch.applyStateUpdate p.state <;> simp

/-- A delayed completion enqueues exactly one pending event and defers its
state update; the exact propensity definition is shared, not duplicated. -/
theorem delayed_channel_defers_update (p : Process) (ch : Channel) (d : ExactValue)
    (hdelay : ch.delay = some d) :
    (p.fire ch).state = p.state ∧ (p.fire ch).pending.length = p.pending.length + 1 := by
  constructor
  · exact fire_delayed_preserves_state p ch d hdelay
  · simp [Process.fire, Process.scheduleDelayed, hdelay]

theorem processSemanticEqual_refl (p : Process) : processSemanticEqual p p := by
  constructor <;> rfl

theorem processSemanticEqual_symm (p q : Process) (h : processSemanticEqual p q) :
    processSemanticEqual q p := by
  exact ⟨h.1.symm, h.2.symm⟩

theorem processSemanticEqual_trans (p q r : Process)
    (hpq : processSemanticEqual p q) (hqr : processSemanticEqual q r) :
    processSemanticEqual p r := by
  exact ⟨hpq.1.trans hqr.1, hpq.2.trans hqr.2⟩

theorem semantic_equal_implies_total_equal (p q : Process) (h : processSemanticEqual p q) :
    p.total = q.total := h.2

theorem supported_manifest_excludes_float_solver :
    supportedManifest.floatingPointSolverExcluded = true := rfl

theorem supported_manifest_exact_arithmetic :
    supportedManifest.exactRationalArithmetic = true := rfl

end BNG
