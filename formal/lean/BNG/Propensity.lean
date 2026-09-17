import BNG.Stochastic

namespace BNG

/-!
# Symbolic propensity contract

Numerical rate evaluation and combinatorial match counting are intentionally
separate.  This avoids the common mistake of hiding stochastic semantics inside
one floating-point helper.

The reference layer produces a symbolic channel record that says:

* which resolved rate expression is used;
* how many legal whole-rule matches contribute;
* whether the rule is `TotalRate`;
* whether `MatchOnce` affected counting.

A backend-specific numerical layer can then prove/test that it evaluates this
contract with the same symmetry and unit conventions.
-/

structure PropensityContract where
  rate : RateLaw
  legalMatchCount : Nat
  totalRate : Bool
  matchOnce : Bool
  deriving Repr

/-- Construct the combinatorial propensity contract for one current mixture. -/
def RuleDirection.propensityContract (d : RuleDirection) (mix : Mixture) : PropensityContract :=
  { rate := d.rate
    legalMatchCount := d.channelMultiplicity mix
    totalRate := d.hasTotalRate
    matchOnce := d.hasMatchOnce }

/-- A channel with no legal match cannot fire regardless of numerical rate. -/
def PropensityContract.enabled (p : PropensityContract) : Bool :=
  decide (p.legalMatchCount > 0)

/--
Interpretation rule before symmetry/unit details:

* ordinary rate: numerical rate is multiplied by legal match multiplicity;
* TotalRate: supplied rate is already the total channel rate whenever enabled.

Keeping this as a datatype-level contract avoids baking floating-point choices
into the structural semantics.
-/
inductive ChannelRateInterpretation where
  | perMatch (multiplicity : Nat)
  | totalChannel
  deriving Repr, DecidableEq, BEq

def PropensityContract.interpretation (p : PropensityContract) : ChannelRateInterpretation :=
  if p.totalRate then .totalChannel else .perMatch p.legalMatchCount

end BNG
