import BNG.Ids

namespace BNG

/-!
# Source text is provenance, not semantics

One of the most important architectural goals in the proposed BNG3 migration
is that a backend must never re-interpret BNGL strings.  We therefore keep
source spelling in an explicit wrapper that can be erased without touching the
semantic value.
-/

structure SourceInfo where
  /-- Human-readable original text, useful for diagnostics and round-tripping. -/
  text : String := ""
  /-- Optional file name or logical source name. -/
  file : Option String := none
  /-- Optional 1-based line number. -/
  line : Option Nat := none
  deriving Repr, DecidableEq

structure WithSource (α : Type) where
  semantic : α
  source : SourceInfo
  deriving Repr

/-- Throw away provenance and keep the meaning. -/
def WithSource.erase {α : Type} (x : WithSource α) : α := x.semantic

/--
Changing only the original spelling cannot change the semantic value.
This tiny theorem captures a surprisingly important compiler boundary.
-/
theorem source_text_is_not_semantics {α : Type} (x : α) (a b : SourceInfo) :
    (WithSource.mk x a).erase = (WithSource.mk x b).erase := by
  rfl

end BNG
