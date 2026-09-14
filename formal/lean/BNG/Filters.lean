import BNG.Operational

namespace BNG

/-!
# Contextual include/exclude rule filters

BNGL filter modifiers are *context* predicates on one selected reactant or
product complex.  A filter may carry several patterns; within one filter those
patterns are alternatives (OR).  Multiple filter declarations are additional
criteria (AND).

This reference implementation evaluates filters with the deliberately slow
semantic matcher.  That is exactly what we want from a correctness oracle.
-/

/-- At least one alternative filter pattern occurs in the selected complex. -/
def filterAlternativesMatch (patterns : List Pattern) (complex : Mixture) : Bool :=
  patterns.any (fun p => !(p.matches complex).isEmpty)

/-- Interpret include/exclude polarity after computing the OR of alternatives. -/
def RuleFilter.acceptsComplex (filter : RuleFilter) (complex : Mixture) : Bool :=
  let hit := filterAlternativesMatch filter.patterns complex
  match filter.mode with
  | .include => hit
  | .exclude => !hit

/-- Concrete reactant complex selected by one top-level rule match. -/
def reactantComplexFor? (mix : Mixture) (matched : RuleMatch) (patternIndex : Nat) : Option Mixture :=
  match matched.embeddingAt? patternIndex with
  | none => none
  | some embedding =>
      match embedding.range with
      | [] => none
      | first :: _ => some (mix.complexContaining first)

/-- First semantic molecule occurrence in one top-level product pattern. -/
def RuleDirection.firstProductEndpoint? (d : RuleDirection) (patternIndex : Nat) : Option RuleMoleculeEndpoint :=
  match listGet? d.products patternIndex with
  | none => none
  | some p =>
      match p.molecules with
      | [] => none
      | first :: _ => some {
          side := .product, pattern := patternIndex, molecule := first.occurrence }

/-- Concrete product complex after executing the rule mutation program. -/
def RuleDirection.productComplexFor? (d : RuleDirection) (mix : Mixture)
    (env : ExecutionEnv) (patternIndex : Nat) : Option Mixture :=
  match d.firstProductEndpoint? patternIndex with
  | none => none
  | some endpoint =>
      match d.resolveMolecule? env endpoint with
      | none => none
      | some id => some (mix.complexContaining id)

/-- Evaluate all reactant-side filters against a candidate match. -/
def RuleDirection.reactantFiltersPass (d : RuleDirection) (mix : Mixture)
    (matched : RuleMatch) : Bool :=
  d.filters.filter (fun f => f.side == PatternSide.reactant) |>.all (fun filter =>
    match reactantComplexFor? mix matched filter.patternIndex with
    | none => false
    | some complex => filter.acceptsComplex complex)

/-- Evaluate all product-side filters after the candidate transformation. -/
def RuleDirection.productFiltersPass (d : RuleDirection) (mix : Mixture)
    (env : ExecutionEnv) : Bool :=
  d.filters.filter (fun f => f.side == PatternSide.product) |>.all (fun filter =>
    match d.productComplexFor? mix env filter.patternIndex with
    | none => false
    | some complex => filter.acceptsComplex complex)

end BNG
