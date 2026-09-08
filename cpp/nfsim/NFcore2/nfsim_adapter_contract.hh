#pragma once
#include "legacy_bridge.hh"
#include <cstdint>
#include <limits>
#include <string>
#include <vector>

namespace NFcore2 {

inline std::uint32_t nativeCompartmentId(const std::string& name) {
    std::uint32_t hash = 2166136261u;
    for (std::size_t i = 0; i < name.size(); ++i) {
        hash ^= static_cast<std::uint8_t>(name[i]);
        hash *= 16777619u;
    }
    return hash;
}

// Stable, parser-independent snapshot of the public semantic data exposed by
// NFsim's System/ReactionClass/TemplateMolecule/TransformationSet classes.
// The actual NFsim adapter only has to populate this POD layer; all validation
// and lowering lives here and is unit-testable without the legacy object graph.
enum NativeDependencyKind {
    NATIVE_STATE_REQUIRED = 0,
    NATIVE_STATE_EXCLUDED = 1,
    NATIVE_BOND_FREE = 2,
    NATIVE_BOND_BOUND = 3,
    NATIVE_BOND_TO = 4,
    NATIVE_TOPOLOGY = 5,
    NATIVE_PARTNER_STATE_REQUIRED = 6,
    NATIVE_PARTNER_STATE_EXCLUDED = 7,
    NATIVE_COMPARTMENT_REQUIRED = 8
};

struct NativeDependencySnapshot {
    NativeDependencyKind kind;
    std::uint16_t reactant;
    std::uint16_t partner_reactant;
    std::uint32_t component;
    std::uint32_t partner_component;
    std::uint32_t partner_state_component;
    std::uint32_t compartment;
    int state;
    bool compartment_ancestry;
    NativeDependencySnapshot() : kind(NATIVE_STATE_REQUIRED), reactant(0), partner_reactant(0),
        component(0), partner_component(0), partner_state_component(0), compartment(0), state(-1), compartment_ancestry(false) {}
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

enum NativeRateLawKind {
    NATIVE_RATE_CONSTANT = 0,
    NATIVE_RATE_LOCAL_LINEAR = 1,
    NATIVE_RATE_DOR_PRODUCT = 2,
    NATIVE_RATE_EXPRESSION = 3
};

enum NativeRateExpressionBindingKind {
    NATIVE_RATE_EXPRESSION_STATE = 0,
    NATIVE_RATE_EXPRESSION_CONSTANT = 1
};

struct NativeRateExpressionBindingSnapshot {
    NativeRateExpressionBindingKind kind;
    std::string name;
    std::uint16_t reactant;
    std::uint32_t component;
    double value;
    NativeRateExpressionBindingSnapshot()
        : kind(NATIVE_RATE_EXPRESSION_CONSTANT), reactant(0), component(0), value(0.0) {}
    static NativeRateExpressionBindingSnapshot state(const std::string& name,
                                                     std::uint16_t reactant,
                                                     std::uint32_t component) {
        NativeRateExpressionBindingSnapshot b; b.kind=NATIVE_RATE_EXPRESSION_STATE;
        b.name=name; b.reactant=reactant; b.component=component; return b;
    }
    static NativeRateExpressionBindingSnapshot constant(const std::string& name,
                                                        double value) {
        NativeRateExpressionBindingSnapshot b; b.kind=NATIVE_RATE_EXPRESSION_CONSTANT;
        b.name=name; b.value=value; return b;
    }
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
    std::int64_t population_delta;
    std::uint32_t destination_compartment;
    bool move_connected;
    NativeTransformSnapshot() : kind(NATIVE_EMPTY), reactant(0), other_reactant(0), component(0),
        other_component(0), new_value(0), removal_type(-1), added_molecule_type(0), population_delta(0),
        destination_compartment(0), move_connected(false) {}
};

struct NativeGraphNodeSnapshot {
    std::uint32_t molecule_type;
    std::uint16_t reactant;
    std::uint32_t state_component;
    std::uint32_t compartment;
    std::vector<std::uint32_t> free_components;
    std::vector<std::uint32_t> bound_components;
    struct SymmetricConstraint {
        std::vector<std::uint32_t> components;
        int state;
        int bond_state;
        std::uint32_t partner_node;
        std::vector<std::uint32_t> partner_components;
        bool partner_symmetric;
        SymmetricConstraint() : state(-1), bond_state(-1),
            partner_node(std::numeric_limits<std::uint32_t>::max()), partner_symmetric(false) {}
    };
    std::vector<SymmetricConstraint> symmetric_constraints;
    int state;
    NativeGraphNodeSnapshot() : molecule_type(0), reactant(std::numeric_limits<std::uint16_t>::max()),
        state_component(std::numeric_limits<std::uint32_t>::max()),
        compartment(std::numeric_limits<std::uint32_t>::max()), state(-1) {}
};
struct NativeGraphEdgeSnapshot {
    std::uint32_t first_node, first_component, second_node, second_component;
    NativeGraphEdgeSnapshot() : first_node(0), first_component(0), second_node(0), second_component(0) {}
};
struct NativeGraphPatternSnapshot {
    std::vector<NativeGraphNodeSnapshot> nodes;
    std::vector<NativeGraphEdgeSnapshot> edges;
};
struct NativeCompartmentSnapshot {
    std::uint32_t id;
    std::uint32_t parent;
    int dimensions;
    double size;
    NativeCompartmentSnapshot() : id(0), parent(std::numeric_limits<std::uint32_t>::max()), dimensions(3), size(0.0) {}
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
    std::vector<NativeGraphPatternSnapshot> graph_patterns;
    NativeRateLawKind rate_law;
    double local_offset;
    double local_slope;
    std::uint32_t local_state_component;
    double dor_weight;
    std::uint32_t dor_state_component;
    std::uint32_t dor_partner_reactant;
    std::uint32_t dor_partner_state_component;
    std::string rate_expression;
    std::vector<std::uint32_t> rate_expression_components;
    std::vector<NativeRateExpressionBindingSnapshot> rate_expression_bindings;
    NativeReactionSnapshot() : base_rate(0.0), parameter_index(0), coordinate(0),
        uses_local_function(false), uses_connected_to(false), rate_law(NATIVE_RATE_CONSTANT), local_offset(0.0), local_slope(0.0), local_state_component(0), dor_weight(1.0), dor_state_component(0), dor_partner_reactant(1), dor_partner_state_component(0) {}
};

struct NativeModelSnapshot {
    std::vector<NativeMoleculeTypeSnapshot> molecule_types;
    std::vector<NativeReactionSnapshot> rules;
    std::vector<NativeCompartmentSnapshot> compartments;
};

class NFsimSnapshotAdapter {
public:
    static LegacyModelIR toLegacy(const NativeModelSnapshot& source);
};

} // namespace NFcore2
