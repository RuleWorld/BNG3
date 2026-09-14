import BNG.Examples

namespace BNG

/-!
# Theorem inventory

The first version of this project mostly proved bookkeeping facts.  The current
version crosses the important line into **operational semantics**:

* patterns are matched against a concrete molecular graph;
* rule mutations actually edit that graph; and
* an independent lowered backend action program is proved to produce exactly
  the same result as the reference semantic mutations.

These theorems still do **not** prove that a biological model is true, or that
NFsim as currently implemented refines the semantics.  The latter becomes the
next implementation bridge.
-/

/-- Source spelling is observationally irrelevant to the semantic payload. -/
theorem source_irrelevance_again {α : Type} (x : α) (s1 s2 : SourceInfo) :
    (WithSource.mk x s1).erase = (WithSource.mk x s2).erase := by
  rfl

/-- Pattern-side reversal is exact, so reverse-rule compilation has a clean basis. -/
theorem rule_side_roundtrip (side : PatternSide) : side.flip.flip = side := by
  exact PatternSide.flip_involutive side

/-- Structural pattern lowering preserves the number of graph nodes. -/
theorem pattern_lowering_keeps_nodes (p : Pattern) :
    p.lower.nodes.length = p.molecules.length := by
  exact lower_preserves_molecule_count p

/-- Structural pattern lowering preserves explicit exact bonds. -/
theorem pattern_lowering_keeps_bonds (p : Pattern) :
    p.lower.bonds.length = p.bonds.length := by
  exact lower_preserves_bond_count p

/-- Structural rule lowering cannot silently drop an edit. -/
theorem rule_lowering_keeps_edits (d : RuleDirection) :
    d.lowerActions.length = d.mutations.length := by
  exact lower_preserves_mutation_count d

/--
The important new one-step result: after lowering a semantic mutation into the
backend action vocabulary, executing it gives exactly the reference result.
-/
theorem backend_one_edit_refines_semantics
    (d : RuleDirection) (mutation : Mutation) (env : ExecutionEnv) (mix : Mixture) :
    d.executeBackendAction mutation.lower env mix = d.applyMutation mutation env mix := by
  exact execute_lowered_mutation_eq_reference d mutation env mix

/-- The equality scales from one edit to an arbitrary finite mutation program. -/
theorem backend_edit_program_refines_semantics
    (d : RuleDirection) (mutations : List Mutation) (env : ExecutionEnv) (mix : Mixture) :
    d.executeBackendProgram (mutations.map Mutation.lower) env mix =
      d.applyMutations mutations env mix := by
  exact execute_lowered_program_eq_reference d mutations env mix

/--
The public rule-step theorem.  For the explicitly supported feature subset and
same candidate match, the lowered backend step and reference rule step are
extensionally equal as `Option Mixture` computations.
-/
theorem backend_rule_step_refines_semantics
    (d : RuleDirection) (mix : Mixture) (matched : RuleMatch) :
    d.executeLoweredAt? mix matched = d.applyAt? mix matched := by
  exact execute_lowered_rule_eq_reference d mix matched

end BNG
