#pragma once
#include "legacy_bridge.hh"
#include <cstdint>
#include <string>
#include <vector>

namespace NFcore2 {

// Stable, parser-independent snapshot of the public semantic data exposed by
// NFsim's System/ReactionClass/TemplateMolecule/TransformationSet classes.
// The actual NFsim adapter only has to populate this POD layer; all validation
// and lowering lives here and is unit-testable without the legacy object graph.
enum NativeDependencyKind {
    NATIVE_STATE_REQUIRED = 0,
    NATIVE_STATE_EXCLUDED = 1,
    NATIVE_BOND_FREE = 2,
    NATIVE_BOND_BOUND = 3,
    NATIVE_TOPOLOGY = 4,
    NATIVE_PARTNER_STATE_REQUIRED = 5,
    NATIVE_PARTNER_STATE_EXCLUDED = 6
};

struct NativeDependencySnapshot {
    NativeDependencyKind kind;
    std::uint16_t reactant;
    std::uint16_t partner_reactant;
    std::uint32_t component;
    std::uint32_t partner_component;
    std::uint32_t partner_state_component;
    int state;
    NativeDependencySnapshot() : kind(NATIVE_STATE_REQUIRED), reactant(0), partner_reactant(0),
        component(0), partner_component(0), partner_state_component(0), state(-1) {}
};

static const std::uint32_t NATIVE_INFER_PARTNER_COMPONENT = 0xffffffffu;

enum NativeTransformKind {
    NATIVE_STATE_CHANGE = 0,
    NATIVE_BINDING = 1,
    NATIVE_UNBINDING = 2,
    NATIVE_REMOVE = 3,
    NATIVE_ADD = 4,
    NATIVE_EMPTY = 5,
    NATIVE_INCREMENT_STATE = 6,
    NATIVE_DECREMENT_STATE = 7,
    NATIVE_LOCAL_FUNCTION_REFERENCE = 8,
    NATIVE_INCREMENT_POPULATION = 9,
    NATIVE_DECREMENT_POPULATION = 10,
    NATIVE_MOVE = 11
};

enum NativeRemovalType {
    NATIVE_DELETE_COMPLETE_SPECIES = 0,
    NATIVE_DELETE_MOLECULE_ONLY = 1,
    NATIVE_DELETE_MOLECULE_CONDITIONAL = 2
};

struct NativeTransformSnapshot {
    NativeTransformKind kind;
    std::uint16_t reactant;
    std::uint16_t other_reactant;
    std::uint32_t component;
    std::uint32_t other_component;
    int new_value;
    int removal_type;
    std::uint32_t added_molecule_type;
    NativeTransformSnapshot() : kind(NATIVE_EMPTY), reactant(0), other_reactant(0), component(0),
        other_component(0), new_value(0), removal_type(-1), added_molecule_type(0) {}
};

struct NativeMoleculeTypeSnapshot {
    std::string name;
    std::uint32_t component_count;
    bool population;
    NativeMoleculeTypeSnapshot() : component_count(0), population(false) {}
};

struct NativeReactionSnapshot {
    std::string name;
    double base_rate;
    std::uint32_t parameter_index;
    std::uint32_t coordinate;
    std::vector<std::uint32_t> reactant_types;
    std::vector<NativeDependencySnapshot> dependencies;
    std::vector<NativeTransformSnapshot> transforms;
    bool uses_local_function;
    bool uses_connected_to;
    NativeReactionSnapshot() : base_rate(0.0), parameter_index(0), coordinate(0),
        uses_local_function(false), uses_connected_to(false) {}
};

struct NativeModelSnapshot {
    std::vector<NativeMoleculeTypeSnapshot> molecule_types;
    std::vector<NativeReactionSnapshot> rules;
};

class NFsimSnapshotAdapter {
public:
    static LegacyModelIR toLegacy(const NativeModelSnapshot& source);
};

} // namespace NFcore2
