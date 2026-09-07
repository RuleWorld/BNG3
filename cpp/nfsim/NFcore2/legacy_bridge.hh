#pragma once
#include "executable_model.hh"
#include "rule_compiler.hh"
#include <cstdint>
#include <string>
#include <vector>

namespace NFcore2 {

// Parser-independent semantic input emitted by the existing NFsim XML/BNGL
// construction layer. It deliberately describes meaning, not ReactionClass
// implementation details, so the bridge can be reused by a future parser.
enum LegacyPredicateKind {
    LEGACY_PRED_TYPE_EXISTS,
    LEGACY_PRED_STATE_MASK,
    LEGACY_PRED_STATE_NOT_EQUAL,
    LEGACY_PRED_BOND_PRESENT,
    LEGACY_PRED_BOND_FREE,
    LEGACY_PRED_BOND_TO,
    LEGACY_PRED_POPULATION_AT_LEAST,
    LEGACY_PRED_COMPARTMENT,
    LEGACY_PRED_CONNECTED_TO,
    LEGACY_PRED_SCAFFOLD_STATE,
    LEGACY_PRED_SCAFFOLD_FREE,
    LEGACY_PRED_UNSUPPORTED
};

struct LegacyPredicateIR {
    LegacyPredicateKind kind;
    std::uint16_t target;
    std::uint32_t a;
    std::uint32_t b;
    std::uint64_t mask;
    std::uint64_t value;
    bool has_partner_component;
    FeatureId partner_feature;
    LegacyPredicateIR() : kind(LEGACY_PRED_UNSUPPORTED), target(0), a(0), b(0), mask(0), value(0), has_partner_component(false) {}
};

enum LegacyTransformKind {
    LEGACY_TRANSFORM_SET_STATE_WORD,
    LEGACY_TRANSFORM_ADD_STATE_WORD,
    LEGACY_TRANSFORM_SET_SCAFFOLD_STATE,
    LEGACY_TRANSFORM_MOVE_OCCUPANT,
    LEGACY_TRANSFORM_POPULATION_ADD,
    LEGACY_TRANSFORM_BIND,
    LEGACY_TRANSFORM_UNBIND,
    LEGACY_TRANSFORM_CREATE_MOLECULE,
    LEGACY_TRANSFORM_DELETE_MOLECULE,
    LEGACY_TRANSFORM_DELETE_SPECIES,
    LEGACY_TRANSFORM_MOVE_MOLECULE,
    LEGACY_TRANSFORM_UNSUPPORTED
};

struct LegacyTransformIR {
    LegacyTransformKind kind;
    std::uint16_t target;
    std::uint16_t other;
    std::uint32_t a;
    std::uint32_t b;
    std::int64_t value;
    FeatureId changed_feature;
    LegacyTransformIR()
        : kind(LEGACY_TRANSFORM_UNSUPPORTED), target(0), other(0), a(0), b(0), value(0), changed_feature() {}
};

struct LegacyRuleIR {
    std::string name;
    std::vector<LegacyPredicateIR> predicates;
    std::vector<LegacyTransformIR> transforms;
    double rate;
    RateLawDescriptor rate_law;
    std::uint32_t parameter_index;
    std::uint32_t coordinate;
    bool uses_local_function;
    bool uses_connected_to;
    bool changes_topology;
    bool topology_change_is_local;
    LegacyRuleIR()
        : rate(0.0), parameter_index(0), coordinate(0), uses_local_function(false),
          uses_connected_to(false), changes_topology(false), topology_change_is_local(false) {}
};

struct LegacyModelIR {
    std::vector<MoleculeTypeDescriptor> molecule_types;
    std::vector<FeatureDescriptor> features;
    std::vector<LegacyRuleIR> rules;
};

enum LoweringFallbackReason {
    LOWERING_SUPPORTED,
    LOWERING_UNSUPPORTED_PREDICATE,
    LOWERING_UNSUPPORTED_TRANSFORM,
    LOWERING_LOCAL_FUNCTION,
    LOWERING_CONNECTED_TO,
    LOWERING_TOPOLOGY_CHANGE
};

struct LoweredRuleInfo {
    LoweringFallbackReason reason;
    RuleFamilyId family;
    std::uint32_t member;
    LoweredRuleInfo() : reason(LOWERING_SUPPORTED), family(), member(0) {}
    bool supported() const { return reason == LOWERING_SUPPORTED; }
};

struct LegacyLoweringResult {
    ExecutableModel executable;
    std::vector<LoweredRuleInfo> rules;
    std::size_t supported_rule_count;
    std::size_t fallback_rule_count;
    LegacyLoweringResult() : supported_rule_count(0), fallback_rule_count(0) {}
};

class LegacyLowerer {
public:
    static LegacyLoweringResult lower(const LegacyModelIR& legacy);
    static std::string matcherSignature(const LegacyRuleIR& rule);
    static std::string transformSignature(const LegacyRuleIR& rule);
};

} // namespace NFcore2
