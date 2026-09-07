# NFcore2 native NFsim adapter — TDD status

Base target: `akutuva21/nfsim`, branch `perf/rasi-translation-optimization` (working branch previously observed at `d13086bd3cf2fd268be5efea4d83089301479de3`).

## Verification

- 331/331 standalone NFcore2 tests pass.
- GCC Debug: pass.
- GCC Release: pass.
- Clang Debug: pass.
- GCC ASan + UBSan: pass (including leak detection).
- Test source: 2829 lines.
- NFcore2 implementation source: 1586 lines.
- Test / implementation ratio: 1.78x (target >= 1.5x).

## New test-first work in this milestone

1. Runtime reciprocal-site inference for legacy NFsim unbinding, including nonzero reciprocal slots and transactional rejection of asymmetric graphs.
2. NFsim snapshot adapter support for inferred unbinding.
3. Model-image round-trip coverage for MATCH_STATE_NOT_EQUAL, TRANSFORM_ADD_STATE_WORD, and inferred unbind operands.
4. NFsim transformation-table decoder with tests for cross-reactant binding, same-reactant binding, malformed partner reactant/mapping indices, second-half suppression, state changes, increment/decrement, remove, empty, and unsupported/fallback transforms.
5. Native NFsim reader that converts System / ReactionClass / TemplateMolecule / TransformationSet public semantics into the tested parser-independent snapshot layer.

## Minimal legacy introspection additions

The native reader requires only read-only accessors:

- `ReactionClass::getTransformationSet()`
- `StateChangeTransform::getFinalStateValue()`
- `BindingTransform::getOtherReactantIndex()`
- `BindingTransform::getOtherMappingIndex()`

These are provided in `legacy-nfcore2-introspection.patch` and do not alter simulation state or hot-path behavior.

## Exact lowering currently supported

- Root-local state equality and exclusion.
- Root-local free/bound site predicates.
- State assignment.
- Checked state increment/decrement.
- Ordinary binding using NFsim's stored other-reactant + other-mapping index and the second half-transform's exact component.
- Unbinding using exact local site plus runtime reciprocal-slot discovery.
- Single-molecule deletion.
- Rule-family compression after normalization.

## Deliberate fallback remains

- connectedTo and graph predicates that cannot yet assign every internal TemplateMolecule to a stable NFcore2 match variable;
- partner-state predicates on internal graph nodes;
- whole-species / conditional deletion;
- compartment movement;
- local-function rate semantics;
- add-species/add-molecule and population transforms until their exact creation/population identity is represented in the compiled model.

## Important integration limitation

The native reader source is intended to compile inside the full NFsim branch and is excluded only from the standalone NFcore2 unit-test CMake target, because this VM cannot clone the repository. The parser-independent reader/decoder/lowering layers are fully compiled and tested here. A full branch build and Rasi-500/uORF shadow parity run still requires applying the overlay + legacy introspection patch in an environment containing the complete NFsim source tree and model fixtures.
