import BNG.Observables

namespace BNG

/-!
# Reference stochastic channel semantics

The purpose here is not to implement Gillespie's algorithm.  It is to pin down
**what is being counted** before a simulator multiplies by a kinetic rate.

The dangerous mistake is assigning the whole channel hazard to every embedding.
Instead we separate:

1. valid whole-rule matches;
2. optional `MatchOnce` collapsing;
3. the channel multiplicity used by the propensity calculation.

Rate-expression evaluation is a separate layer.
-/

/-- Does a direction carry a specific flag-like modifier? -/
def RuleDirection.hasMatchOnce (d : RuleDirection) : Bool :=
  d.modifiers.any (fun modifier =>
    match modifier with | .matchOnce => true | _ => false)

def RuleDirection.hasTotalRate (d : RuleDirection) : Bool :=
  d.modifiers.any (fun modifier =>
    match modifier with | .totalRate => true | _ => false)

/--
Ordered complex key for one whole-rule match.

Order matters because reactant positions can have different semantics.  Each
embedding contributes the connected complex containing its first mapped
molecule.  Empty embeddings get an empty key entry and are not silently merged
with a real complex ID.
-/
def RuleMatch.orderedComplexKey (mix : Mixture) (m : RuleMatch) : List (Option MoleculeInstanceId) :=
  m.embeddings.map (fun e =>
    match e.range with
    | [] => none
    | first :: _ => some first)

/-- Remove later matches with a duplicate ordered complex key. -/
private def deduplicateMatchOnce.go (mix : Mixture)
    (seen : List (List (Option MoleculeInstanceId))) : List RuleMatch → List RuleMatch
  | [] => []
  | candidate :: rest =>
      let key := candidate.orderedComplexKey mix
      if seen.any (fun previous => previous == key) then
        deduplicateMatchOnce.go mix seen rest
      else
        candidate :: deduplicateMatchOnce.go mix (key :: seen) rest

def deduplicateMatchOnce (mix : Mixture) (entries : List RuleMatch) : List RuleMatch :=
  deduplicateMatchOnce.go mix [] entries

/-- Whole-rule matches eligible for stochastic counting. -/
def RuleDirection.countedMatches (d : RuleDirection) (mix : Mixture) : List RuleMatch :=
  let allMatches := d.matches mix
  if d.hasMatchOnce then deduplicateMatchOnce mix allMatches else allMatches

/-- Combinatorial multiplicity of one reaction channel before kinetic-rate evaluation. -/
def RuleDirection.channelMultiplicity (d : RuleDirection) (mix : Mixture) : Nat :=
  (d.countedMatches mix).length

/--
`TotalRate` changes how a supplied rate is interpreted; it does not create one
hazard per embedding.  Keeping this Boolean explicit lets backend refinement
proofs state when ordinary symmetry/multiplicity correction is bypassed.
-/
def RuleDirection.rateIsTotalChannelRate (d : RuleDirection) : Bool :=
  d.hasTotalRate

end BNG
