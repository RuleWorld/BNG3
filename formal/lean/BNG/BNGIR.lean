import BNG.Model

namespace BNG

/-!
# Structural BNGIR contract

BNGIR should serialize resolved semantics, not parser text.  This module defines
an intentionally boring versioned envelope around the semantic `Document`.
The important property is that decoding does not call a BNGL parser.
-/

structure BNGIRVersion where
  major : Nat
  minor : Nat
  deriving Repr, DecidableEq, BEq

/-- Experimental structural representation corresponding to the proposed v0.2. -/
structure StructuralBNGIR where
  version : BNGIRVersion := { major := 0, minor := 2 }
  document : Document
  deriving Repr

/-- Semantic encoding is structural: no BNGL source reconstruction occurs. -/
def encodeStructural (doc : Document) : StructuralBNGIR :=
  { document := doc }

/-- Decode only versions whose major/minor semantics this implementation knows. -/
def decodeStructural? (ir : StructuralBNGIR) : Option Document :=
  if ir.version == ({ major := 0, minor := 2 } : BNGIRVersion)
  then some ir.document
  else none

/-- Structural v0.2 round-trip is exact at the semantic-object level. -/
theorem structural_roundtrip (doc : Document) :
    decodeStructural? (encodeStructural doc) = some doc := by
  rfl

end BNG
