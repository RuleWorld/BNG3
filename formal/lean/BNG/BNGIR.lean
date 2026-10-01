import BNG.Model

namespace BNG

/-!
# Structural BNGIR contract

BNGIR should serialize resolved semantics, not parser text.  This module defines
an intentionally boring versioned envelope around the semantic `Document`.
The important property is that decoding does not call a BNGL parser.

This formalizes the envelope/header portion of the Python wire contract in
`python/bionetgen/bngir.py` (read-only reference):

* the format tag must be `BNGIR` (`FORMAT`);
* exactly two versions decode — `0.1` and `0.2` (`SUPPORTED_VERSIONS`) —
  carried structurally as major/minor pairs;
* decoding runs a fail-closed feature gate over the declared feature names:
  the `_FEATURES` vocabulary for v0.1, plus `structured_patterns` and
  `structured_expressions` for v0.2;
* v0.2 additionally requires both structured names in its required-feature
  list (`_load_document_v02`).

Any envelope outside that contract refuses with `none`.  The model/protocol
payload halves of the JSON document are represented by the semantic
`Document` itself, so only the header and feature gate are modeled here.
-/

structure BNGIRVersion where
  major : Nat
  minor : Nat
  deriving Repr, DecidableEq, BEq

namespace BNGIRVersion

/-- BNGIR `0.1` (`VERSION` in `bngir.py`): the earlier payload version. -/
def v01 : BNGIRVersion := { major := 0, minor := 1 }

/-- BNGIR `0.2` (`STRUCTURAL_VERSION` in `bngir.py`): the structural version. -/
def v02 : BNGIRVersion := { major := 0, minor := 2 }

/-- A version decodes exactly when it is one of the two supported versions
(`SUPPORTED_VERSIONS = {"0.1", "0.2"}` in `bngir.py`). -/
def isSupported (v : BNGIRVersion) : Bool :=
  decide (v = v01) || decide (v = v02)

end BNGIRVersion

/-- The format tag every BNGIR document carries (`FORMAT = "BNGIR"`). -/
def bngirFormat : String := "BNGIR"

/-- Feature names the Python deserializer recognizes (`_FEATURES`).  Any
declared name outside this vocabulary fails closed. -/
def knownFeatures : List String :=
  [ "barrier_patterns", "compartments", "driven_reservoirs", "energy_patterns"
  , "functions", "observables", "population_maps", "protocol", "rules", "seeds" ]

/-- Feature names only the v0.2 gate admits on top of `knownFeatures`. -/
def structuredFeatures : List String :=
  ["structured_patterns", "structured_expressions"]

/-- The declared feature lists carried in the envelope (`features.required` /
`features.used` in the JSON payload). -/
structure BNGIRFeatures where
  required : List String := []
  used : List String := []
  deriving Repr, DecidableEq

/-- The minimal v0.2 feature record: the structured representation is both
required and used, which is what `_features_v02` emits for a model with no
additional feature sections. -/
def structuralV02Features : BNGIRFeatures :=
  { required := structuredFeatures, used := structuredFeatures }

/-- v0.1 feature gate: every declared name must be in `knownFeatures`
(`_load_document_v01` refuses anything else). -/
def featuresGateV01 (fs : BNGIRFeatures) : Bool :=
  fs.required.all (fun f => decide (f ∈ knownFeatures)) &&
  fs.used.all (fun f => decide (f ∈ knownFeatures))

/-- v0.2 feature gate: names may also come from `structuredFeatures`, and the
structured representation must be explicitly required
(`_load_document_v02`).  Unrecognized names fail closed. -/
def featuresGateV02 (fs : BNGIRFeatures) : Bool :=
  fs.required.all (fun f => decide (f ∈ knownFeatures ++ structuredFeatures)) &&
  fs.used.all (fun f => decide (f ∈ knownFeatures ++ structuredFeatures)) &&
  structuredFeatures.all (fun f => decide (f ∈ fs.required))

/-- Version-dispatched feature gate.  An unknown version gates to `false`;
the supported-version check refuses it before a gate would be consulted. -/
def featuresGate (v : BNGIRVersion) (fs : BNGIRFeatures) : Bool :=
  if decide (v = BNGIRVersion.v01) then featuresGateV01 fs
  else if decide (v = BNGIRVersion.v02) then featuresGateV02 fs
  else false

/-- Versioned, format-tagged envelope around the semantic document. -/
structure StructuralBNGIR where
  format : String := bngirFormat
  version : BNGIRVersion := BNGIRVersion.v02
  features : BNGIRFeatures := structuralV02Features
  document : Document
  deriving Repr

/-- The envelope is accepted exactly when its format tag, version, and feature
gate all pass — the same three checks `bngir.py` performs before it hands back
a document (`_parse_document` then `_load_document_v01`/`_load_document_v02`).
A refusal is `false`, never an approximation. -/
def structuralAccepted (ir : StructuralBNGIR) : Bool :=
  decide (ir.format = bngirFormat) &&
  BNGIRVersion.isSupported ir.version &&
  featuresGate ir.version ir.features

/-- Semantic encoding is structural: no BNGL source reconstruction occurs.
Produces a minimal v0.2 envelope. -/
def encodeStructural (doc : Document) : StructuralBNGIR :=
  { format := bngirFormat
    version := BNGIRVersion.v02
    features := structuralV02Features
    document := doc }

/-- Minimal v0.1 envelope: a model without extra feature sections declares no
features (`_payload_v01` emits `{"required": [], "used": []}`). -/
def encodeStructuralV01 (doc : Document) : StructuralBNGIR :=
  { format := bngirFormat
    version := BNGIRVersion.v01
    features := { required := [], used := [] }
    document := doc }

/-- Decode succeeds only for a well-tagged, supported version whose feature
gate passes; every other envelope refuses with `none`. -/
def decodeStructural? (ir : StructuralBNGIR) : Option Document :=
  if structuralAccepted ir then some ir.document else none

/-! ## Version laws -/

theorem BNGIRVersion.supported_v01 : BNGIRVersion.isSupported BNGIRVersion.v01 = true :=
  rfl

theorem BNGIRVersion.supported_v02 : BNGIRVersion.isSupported BNGIRVersion.v02 = true :=
  rfl

/-- "Accept iff supported": the supported set is exactly `{0.1, 0.2}`. -/
theorem BNGIRVersion.isSupported_iff (v : BNGIRVersion) :
    BNGIRVersion.isSupported v = true ↔
      v = BNGIRVersion.v01 ∨ v = BNGIRVersion.v02 := by
  simp [BNGIRVersion.isSupported, Bool.or_eq_true]

/-- Every supported version has major 0, so a nonzero major can never decode. -/
theorem BNGIRVersion.isSupported_major_zero (v : BNGIRVersion)
    (h : BNGIRVersion.isSupported v = true) : v.major = 0 := by
  rcases (BNGIRVersion.isSupported_iff v).mp h with H | H
  · rw [H]; rfl
  · rw [H]; rfl

/-- Unknown major: any version with `major ≠ 0` is outside the supported set. -/
theorem BNGIRVersion.isSupported_eq_false_of_major (v : BNGIRVersion)
    (hv : v.major ≠ 0) : BNGIRVersion.isSupported v = false := by
  by_cases hs : BNGIRVersion.isSupported v = true
  · exact absurd (BNGIRVersion.isSupported_major_zero v hs) hv
  · cases h : BNGIRVersion.isSupported v
    · rfl
    · exact absurd h hs

/-- Unknown minor: neither supported version carries any minor but 1 or 2. -/
theorem BNGIRVersion.isSupported_eq_false_of_minor (v : BNGIRVersion)
    (h1 : v.minor ≠ 1) (h2 : v.minor ≠ 2) :
    BNGIRVersion.isSupported v = false := by
  by_cases hs : BNGIRVersion.isSupported v = true
  · rcases (BNGIRVersion.isSupported_iff v).mp hs with H | H
    · exact absurd (by rw [H]; rfl) h1
    · exact absurd (by rw [H]; rfl) h2
  · cases h : BNGIRVersion.isSupported v
    · rfl
    · exact absurd h hs

/-! ## Gate dispatch laws -/

theorem featuresGate_v01 (fs : BNGIRFeatures) :
    featuresGate BNGIRVersion.v01 fs = featuresGateV01 fs :=
  rfl

theorem featuresGate_v02 (fs : BNGIRFeatures) :
    featuresGate BNGIRVersion.v02 fs = featuresGateV02 fs :=
  rfl

/-! ## Decode laws -/

/-- Acceptance decomposes into the three independent header checks. -/
theorem structuralAccepted_iff (ir : StructuralBNGIR) :
    structuralAccepted ir = true ↔
      ir.format = bngirFormat ∧
      BNGIRVersion.isSupported ir.version = true ∧
      featuresGate ir.version ir.features = true := by
  simp [structuralAccepted, Bool.and_eq_true, and_assoc]

/-- Successful decode both accepts the envelope and pins the document. -/
theorem decodeStructural?_eq_some_iff (ir : StructuralBNGIR) (doc : Document) :
    decodeStructural? ir = some doc ↔
      structuralAccepted ir = true ∧ ir.document = doc := by
  unfold decodeStructural?
  by_cases h : structuralAccepted ir = true <;> simp [h]

/-- Decode never invents a document: a successful decode returns exactly the
envelope's document. -/
theorem decode_preserves_document (ir : StructuralBNGIR) (doc : Document)
    (h : decodeStructural? ir = some doc) : doc = ir.document :=
  ((decodeStructural?_eq_some_iff ir doc).mp h).2.symm

/-- Necessary direction of "accept iff supported": a successful decode implies
the version was in the supported set. -/
theorem decode_some_version_supported (ir : StructuralBNGIR) (doc : Document)
    (h : decodeStructural? ir = some doc) :
    BNGIRVersion.isSupported ir.version = true :=
  ((structuralAccepted_iff ir).mp ((decodeStructural?_eq_some_iff ir doc).mp h).1).2.1

/-- Sufficient direction: a correct format tag, a supported version, and a
passing feature gate decode to the envelope's own document. -/
theorem decode_some_of_format_supported_and_gate (ir : StructuralBNGIR)
    (hf : ir.format = bngirFormat)
    (hs : BNGIRVersion.isSupported ir.version = true)
    (hg : featuresGate ir.version ir.features = true) :
    decodeStructural? ir = some ir.document :=
  (decodeStructural?_eq_some_iff ir ir.document).2
    ⟨(structuralAccepted_iff ir).2 ⟨hf, hs, hg⟩, rfl⟩

/-- Any version outside the supported set refuses, whatever its features. -/
theorem decode_refuses_unsupported_version (v : BNGIRVersion) (fs : BNGIRFeatures)
    (doc : Document) (hv : BNGIRVersion.isSupported v = false) :
    decodeStructural? { version := v, features := fs, document := doc } = none := by
  simp [decodeStructural?, structuralAccepted, hv]

/-- Unknown major refuses to decode for every minor value. -/
theorem decode_refuses_nonzero_major (v : BNGIRVersion) (hv : v.major ≠ 0)
    (fs : BNGIRFeatures) (doc : Document) :
    decodeStructural? { version := v, features := fs, document := doc } = none :=
  decode_refuses_unsupported_version v fs doc
    (BNGIRVersion.isSupported_eq_false_of_major v hv)

/-- Unknown minor refuses to decode for every other header content. -/
theorem decode_refuses_unknown_minor (v : BNGIRVersion) (h1 : v.minor ≠ 1)
    (h2 : v.minor ≠ 2) (fs : BNGIRFeatures) (doc : Document) :
    decodeStructural? { version := v, features := fs, document := doc } = none :=
  decode_refuses_unsupported_version v fs doc
    (BNGIRVersion.isSupported_eq_false_of_minor v h1 h2)

/-- A document tagged as some other format refuses to decode. -/
theorem decode_refuses_wrong_format (fmt : String) (doc : Document)
    (hf : fmt ≠ bngirFormat) :
    decodeStructural? { format := fmt, document := doc } = none := by
  simp [decodeStructural?, structuralAccepted, hf]

/-! ## Feature-gate refusals -/

/-- v0.1 fails closed on a required feature outside `_FEATURES`. -/
theorem decodeV01_refuses_unknown_required_feature (f : String)
    (hf : f ∉ knownFeatures) (doc : Document) :
    decodeStructural?
      { version := BNGIRVersion.v01
        features := { required := [f], used := [] }
        document := doc } = none := by
  simp [decodeStructural?, structuralAccepted, BNGIRVersion.supported_v01,
    featuresGate_v01, featuresGateV01, List.all, hf]

/-- v0.1 fails closed on a used feature outside `_FEATURES`. -/
theorem decodeV01_refuses_unknown_used_feature (f : String)
    (hf : f ∉ knownFeatures) (doc : Document) :
    decodeStructural?
      { version := BNGIRVersion.v01
        features := { required := [], used := [f] }
        document := doc } = none := by
  simp [decodeStructural?, structuralAccepted, BNGIRVersion.supported_v01,
    featuresGate_v01, featuresGateV01, List.all, hf]

/-- v0.2 fails closed on a required feature outside
`_FEATURES ∪ {structured_patterns, structured_expressions}`. -/
theorem decodeV02_refuses_unknown_required_feature (f : String)
    (hf : f ∉ knownFeatures ++ structuredFeatures) (doc : Document) :
    decodeStructural?
      { version := BNGIRVersion.v02
        features := { required := [f], used := [] }
        document := doc } = none := by
  simp [decodeStructural?, structuralAccepted, BNGIRVersion.supported_v02,
    featuresGate_v02, featuresGateV02, List.all, hf]

/-- v0.2 fails closed on a used feature outside the extended vocabulary. -/
theorem decodeV02_refuses_unknown_used_feature (f : String)
    (hf : f ∉ knownFeatures ++ structuredFeatures) (doc : Document) :
    decodeStructural?
      { version := BNGIRVersion.v02
        features := { required := [], used := [f] }
        document := doc } = none := by
  simp [decodeStructural?, structuralAccepted, BNGIRVersion.supported_v02,
    featuresGate_v02, featuresGateV02, List.all, hf]

/-- The v0.1 gate knows nothing of the `structured_*` names: they refuse
there even though v0.2 requires them. -/
theorem decodeV01_refuses_structured_features (doc : Document) :
    decodeStructural?
      { version := BNGIRVersion.v01
        features := structuralV02Features
        document := doc } = none :=
  rfl

/-- A v0.2 envelope must require the structured representation explicitly. -/
theorem decodeV02_requires_structured_features (doc : Document) :
    decodeStructural?
      { version := BNGIRVersion.v02
        features := { required := [], used := [] }
        document := doc } = none :=
  rfl

/-! ## Round-trips and encode-then-mutate refusals -/

/-- Structural v0.2 round-trip is exact at the semantic-object level. -/
theorem structural_roundtrip (doc : Document) :
    decodeStructural? (encodeStructural doc) = some doc := by
  rfl

/-- Structural v0.1 round-trip is exact at the semantic-object level. -/
theorem structural_roundtrip_v01 (doc : Document) :
    decodeStructural? (encodeStructuralV01 doc) = some doc := by
  rfl

/-- Bumping the version after encoding refuses: the mutated envelope no longer
names a version whose semantics were encoded. -/
theorem encode_refuses_version_mutation (doc : Document) :
    decodeStructural?
      { (encodeStructural doc) with
        version := { major := 0, minor := 3 } } = none := by
  rfl

/-- Declaring an unknown required feature after encoding refuses. -/
theorem encode_refuses_feature_mutation (doc : Document) :
    decodeStructural?
      { (encodeStructural doc) with
        features := { required := ["quantum_features"], used := [] } } = none := by
  rfl

end BNG
