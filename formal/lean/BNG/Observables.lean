import BNG.Hybrid

namespace BNG

/-!
# Observable semantics

A formal model is not useful if only rule execution is defined while the
quantities users plot and fit remain informal.  This module gives a small,
explicit meaning to the standard `Molecules` and `Species` observables.

* `Molecules` counts valid pattern embeddings.
* `Species` counts connected complexes that are matched as a whole.

`counter` and custom observable kinds intentionally remain unsupported here;
returning `none` is preferable to guessing their meaning.
-/

/-- Number of ordinary embeddings of one pattern. -/
def Pattern.moleculeObservableCount (p : Pattern) (mix : Mixture) : Nat :=
  (p.matches mix).length

/-- Number of whole connected complexes matched by one pattern. -/
def Pattern.speciesObservableCount (p : Pattern) (mix : Mixture) : Nat :=
  p.matches mix |>.filter (embeddingCoversWholeComplex mix) |>.length

/-- Evaluate a compiled observable against a concrete particle mixture. -/
def ObservableDecl.evaluate? (decl : ObservableDecl) (mix : Mixture) : Option Nat :=
  match decl.kind with
  | .molecules =>
      some (decl.patterns.foldl (fun total p => total + p.moleculeObservableCount mix) 0)
  | .species =>
      some (decl.patterns.foldl (fun total p => total + p.speciesObservableCount mix) 0)
  | .counter => none
  | .custom _ => none

/-- Empty pattern lists contribute zero to standard count observables. -/
theorem empty_molecule_observable_zero (id : ObservableId) (name : String) (mix : Mixture) :
    ({ id := id, name := name, kind := .molecules, patterns := [] } : ObservableDecl).evaluate? mix = some 0 := by
  rfl

end BNG
