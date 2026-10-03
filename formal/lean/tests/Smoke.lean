import BNG

open BNG
open BNG.Examples

/-!
# Smoke checks

These `#eval`s are intentionally human-readable.  A successful run should show:

* the model and starting concrete mixture are well formed (`true`);
* the whole binding/phosphorylation rule has exactly one match (`1`);
* applying it phosphorylates A and creates the A-B bond (`true`, `true`);
* the BNGIR envelope accepts versions 0.1/0.2, refuses everything else, and
  its feature gate fails closed on names outside the Python vocabulary.
-/

#eval model.wellFormed
#eval runtimeMixture.wellFormed model.signature
#eval (forward.matches runtimeMixture).length
#eval resultAIsPhosphorylated
#eval resultHasABBond

example (matched : RuleMatch) :
    forward.executeLoweredAt? runtimeMixture matched =
      forward.applyAt? runtimeMixture matched := by
  exact execute_lowered_rule_eq_reference forward runtimeMixture matched

/-! Additional source-level smoke probes for the expanded semantic layers. -/
#eval (forward.compileStructuralSemantics.mutations.length)
#eval (NFnextPacking.fromSignature model.signature).types.length
#eval nfnextUnsupportedReasons forward
#eval (forward.countedMatches runtimeMixture).length
#eval productComplex.instantiateSeed?.isSome

/-! Reaction-network edge smoke probe.  The starting pool contains A and B as
separate species; one closure step should be able to record an indexed A+B ->
A.B reaction and every resulting edge must refer to valid species indices. -/
def seedA : Mixture := runtimeMixture.restrictToMolecules [⟨0⟩]
def seedB : Mixture := runtimeMixture.restrictToMolecules [⟨1⟩]
def referenceReactionNetwork := model.referenceReactionNetwork 1 [seedA, seedB]
#eval referenceReactionNetwork.wellIndexed
#eval referenceReactionNetwork.reactions.length

/-! BNGIR envelope smoke probes.  `smokeDocument` wraps the worked example
model; the `#eval`s below should print `true` for every accept/refuse claim
and `false` only where a refusal is expected to evaluate the gate to false.
`example`s exercise every BNGIR theorem by re-stating it. -/

def smokeDocument : Document := { model := model }
def smokeV02 : StructuralBNGIR := encodeStructural smokeDocument
def smokeV01 : StructuralBNGIR := encodeStructuralV01 smokeDocument

/-! Header vocabulary. -/
#eval bngirFormat
#eval BNGIRVersion.isSupported BNGIRVersion.v01
#eval BNGIRVersion.isSupported BNGIRVersion.v02
#eval ({ major := 0, minor := 3 } : BNGIRVersion).isSupported
#eval ({ major := 1, minor := 0 } : BNGIRVersion).isSupported
#eval knownFeatures.length
#eval decide ("rules" ∈ knownFeatures)
#eval decide ("structured_patterns" ∈ knownFeatures)
#eval structuredFeatures
#eval structuralV02Features

/-! Feature gates: v0.1 admits only `_FEATURES`; v0.2 also admits the
structured names and requires them. -/
#eval featuresGateV01 { required := ["compartments"], used := ["rules"] }
#eval featuresGateV01 { required := ["structured_patterns"], used := [] }
#eval featuresGateV02 structuralV02Features
#eval featuresGateV02 { required := ["rules"], used := [] }
#eval featuresGateV02 { required := "quantum_features" :: structuredFeatures, used := [] }
#eval featuresGate BNGIRVersion.v01 structuralV02Features
#eval featuresGate BNGIRVersion.v02 structuralV02Features
#eval featuresGate ({ major := 0, minor := 3 } : BNGIRVersion) structuralV02Features

/-! Envelope acceptance and decode. -/
#eval smokeV02.format == bngirFormat
#eval structuralAccepted smokeV02
#eval structuralAccepted smokeV01
#eval structuralAccepted { smokeV02 with version := { major := 0, minor := 3 } }
#eval structuralAccepted { smokeV02 with format := "OTHER" }
#eval (decodeStructural? smokeV02).isSome
#eval (decodeStructural? smokeV01).isSome
#eval (decodeStructural? { smokeV02 with format := "OTHER" }).isNone
def smokeUnknownFeatures : StructuralBNGIR :=
  { smokeV02 with features := { required := ["quantum_features"], used := [] } }
#eval (decodeStructural? smokeUnknownFeatures).isNone

/-! Version theorems. -/
example : BNGIRVersion.isSupported BNGIRVersion.v01 = true :=
  BNGIRVersion.supported_v01
example : BNGIRVersion.isSupported BNGIRVersion.v02 = true :=
  BNGIRVersion.supported_v02
example (v : BNGIRVersion) :
    BNGIRVersion.isSupported v = true ↔
      v = BNGIRVersion.v01 ∨ v = BNGIRVersion.v02 :=
  BNGIRVersion.isSupported_iff v
example (v : BNGIRVersion) (h : BNGIRVersion.isSupported v = true) : v.major = 0 :=
  BNGIRVersion.isSupported_major_zero v h
example (v : BNGIRVersion) (hv : v.major ≠ 0) :
    BNGIRVersion.isSupported v = false :=
  BNGIRVersion.isSupported_eq_false_of_major v hv
example (v : BNGIRVersion) (h1 : v.minor ≠ 1) (h2 : v.minor ≠ 2) :
    BNGIRVersion.isSupported v = false :=
  BNGIRVersion.isSupported_eq_false_of_minor v h1 h2

/-! Gate-dispatch theorems. -/
example (fs : BNGIRFeatures) :
    featuresGate BNGIRVersion.v01 fs = featuresGateV01 fs :=
  featuresGate_v01 fs
example (fs : BNGIRFeatures) :
    featuresGate BNGIRVersion.v02 fs = featuresGateV02 fs :=
  featuresGate_v02 fs

/-! Decode theorems. -/
example (ir : StructuralBNGIR) :
    structuralAccepted ir = true ↔
      ir.format = bngirFormat ∧
      BNGIRVersion.isSupported ir.version = true ∧
      featuresGate ir.version ir.features = true :=
  structuralAccepted_iff ir
example (ir : StructuralBNGIR) (doc : Document) :
    decodeStructural? ir = some doc ↔
      structuralAccepted ir = true ∧ ir.document = doc :=
  decodeStructural?_eq_some_iff ir doc
example (ir : StructuralBNGIR) (doc : Document)
    (h : decodeStructural? ir = some doc) : doc = ir.document :=
  decode_preserves_document ir doc h
example (ir : StructuralBNGIR) (doc : Document)
    (h : decodeStructural? ir = some doc) :
    BNGIRVersion.isSupported ir.version = true :=
  decode_some_version_supported ir doc h
example (ir : StructuralBNGIR)
    (hf : ir.format = bngirFormat)
    (hs : BNGIRVersion.isSupported ir.version = true)
    (hg : featuresGate ir.version ir.features = true) :
    decodeStructural? ir = some ir.document :=
  decode_some_of_format_supported_and_gate ir hf hs hg
example (v : BNGIRVersion) (fs : BNGIRFeatures) (doc : Document)
    (hv : BNGIRVersion.isSupported v = false) :
    decodeStructural? { version := v, features := fs, document := doc } = none :=
  decode_refuses_unsupported_version v fs doc hv
example (v : BNGIRVersion) (hv : v.major ≠ 0) (fs : BNGIRFeatures)
    (doc : Document) :
    decodeStructural? { version := v, features := fs, document := doc } = none :=
  decode_refuses_nonzero_major v hv fs doc
example (v : BNGIRVersion) (h1 : v.minor ≠ 1) (h2 : v.minor ≠ 2)
    (fs : BNGIRFeatures) (doc : Document) :
    decodeStructural? { version := v, features := fs, document := doc } = none :=
  decode_refuses_unknown_minor v h1 h2 fs doc
example (fmt : String) (doc : Document) (hf : fmt ≠ bngirFormat) :
    decodeStructural? { format := fmt, document := doc } = none :=
  decode_refuses_wrong_format fmt doc hf

/-! Feature-gate refusal theorems. -/
example (f : String) (hf : f ∉ knownFeatures) (doc : Document) :
    decodeStructural?
      { version := BNGIRVersion.v01
        features := { required := [f], used := [] }
        document := doc } = none :=
  decodeV01_refuses_unknown_required_feature f hf doc
example (f : String) (hf : f ∉ knownFeatures) (doc : Document) :
    decodeStructural?
      { version := BNGIRVersion.v01
        features := { required := [], used := [f] }
        document := doc } = none :=
  decodeV01_refuses_unknown_used_feature f hf doc
example (f : String) (hf : f ∉ knownFeatures ++ structuredFeatures)
    (doc : Document) :
    decodeStructural?
      { version := BNGIRVersion.v02
        features := { required := [f], used := [] }
        document := doc } = none :=
  decodeV02_refuses_unknown_required_feature f hf doc
example (f : String) (hf : f ∉ knownFeatures ++ structuredFeatures)
    (doc : Document) :
    decodeStructural?
      { version := BNGIRVersion.v02
        features := { required := [], used := [f] }
        document := doc } = none :=
  decodeV02_refuses_unknown_used_feature f hf doc
example (doc : Document) :
    decodeStructural?
      { version := BNGIRVersion.v01
        features := structuralV02Features
        document := doc } = none :=
  decodeV01_refuses_structured_features doc
example (doc : Document) :
    decodeStructural?
      { version := BNGIRVersion.v02
        features := { required := [], used := [] }
        document := doc } = none :=
  decodeV02_requires_structured_features doc

/-! Round-trip and encode-then-mutate theorems. -/
example (doc : Document) : decodeStructural? (encodeStructural doc) = some doc :=
  structural_roundtrip doc
example (doc : Document) :
    decodeStructural? (encodeStructuralV01 doc) = some doc :=
  structural_roundtrip_v01 doc
example (doc : Document) :
    decodeStructural?
      { (encodeStructural doc) with
        version := { major := 0, minor := 3 } } = none :=
  encode_refuses_version_mutation doc
example (doc : Document) :
    decodeStructural?
      { (encodeStructural doc) with
        features := { required := ["quantum_features"], used := [] } } = none :=
  encode_refuses_feature_mutation doc

/-! ## Machine-checked assertions

The eval output above is descriptive and cannot fail the command. These
example declarations use native_decide to pin the same fixture values through
Lean's compiled evaluator. Their proof terms use the trusted native_decide
extension rather than having the kernel reduce the computations, so they are
executable regression checks, not kernel-reduced proofs. A semantic change
that flips a value makes this explicit Lean command fail to elaborate. -/

example : model.wellFormed = true := by native_decide
example : runtimeMixture.wellFormed model.signature = true := by native_decide
example : (forward.matches runtimeMixture).length = 1 := by native_decide
example : resultAIsPhosphorylated = true := by native_decide
example : resultHasABBond = true := by native_decide

example : (forward.compileStructuralSemantics.mutations.length) = 2 := by native_decide
example : (NFnextPacking.fromSignature model.signature).types.length = 2 := by native_decide
example : nfnextUnsupportedReasons forward = [] := by native_decide
example : (forward.countedMatches runtimeMixture).length = 1 := by native_decide
example : productComplex.instantiateSeed?.isSome = true := by native_decide

example : referenceReactionNetwork.wellIndexed = true := by native_decide
example : referenceReactionNetwork.reactions.length = 2 := by native_decide
