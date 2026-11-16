import Std

namespace BNG

/-!
# Small utility functions

These are deliberately boring.  A formal semantics is easier to trust when
basic helpers are tiny enough to read in one sitting.
-/

/-- Return the element at index `n`, or `none` when the list is too short. -/
def listGet? {α : Type} : List α → Nat → Option α
  | [], _ => none
  | x :: _, 0 => some x
  | _ :: xs, Nat.succ n => listGet? xs n

/--
Executable duplicate check.

We use this in the lightweight validators.  The proposition-level theorems can
later be connected to `List.Nodup`; keeping the first pass Boolean makes the
examples easy to run with `#eval`.
-/
def allUnique {α : Type} [BEq α] : List α → Bool
  | [] => true
  | x :: xs => (!(xs.contains x)) && allUnique xs

/-- True when every item in `xs` is also present in `ys`. -/
def allContained {α : Type} [BEq α] (xs ys : List α) : Bool :=
  xs.all (fun x => ys.contains x)

/-- Kernel-proved identity: every list is contained in itself under lawful
boolean equality (supports supported-class renaming/identity reasoning). -/
theorem allContained_self {α : Type} [BEq α] [LawfulBEq α] (xs : List α) :
    allContained xs xs = true := by
  simp [allContained, List.all_eq_true]

end BNG
