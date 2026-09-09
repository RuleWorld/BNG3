#pragma once

#include <cstdint>
#include <limits>
#include <string>
#include <vector>

namespace NFcore2 {

class SimulationState;
struct MatchContext;

enum RateLawKind {
    LEGACY_RATE_CONSTANT = 0,
    LEGACY_RATE_LOCAL_LINEAR = 1,
    LEGACY_RATE_DOR_PRODUCT = 2,
    LEGACY_RATE_EXPRESSION = 3
};

enum RateExpressionBindingKind {
    RATE_EXPRESSION_STATE = 0,
    RATE_EXPRESSION_CONSTANT = 1,
    RATE_EXPRESSION_REACTANT_COUNT = 2,
    RATE_EXPRESSION_SPECIES_MOLECULE_COUNT = 3,
    RATE_EXPRESSION_COMPARTMENT_VOLUME = 4,
    RATE_EXPRESSION_TRANSPORT_VOLUME_RATIO = 5,
    RATE_EXPRESSION_GLOBAL_MOLECULE_COUNT = 6
};

struct RateExpressionBinding {
    RateExpressionBindingKind kind;
    std::string name;
    std::uint16_t target;
    std::uint32_t component;
    std::uint32_t state_component;
    int state_value;
    std::uint32_t bond_component;
    int bond_state;
    std::uint32_t molecule_type;
    int scope;
    std::uint32_t compartment;
    bool compartment_ancestry;
    std::uint32_t destination_compartment;
    double value;
    RateExpressionBinding()
        : kind(RATE_EXPRESSION_CONSTANT), target(0), component(0),
          state_component(std::numeric_limits<std::uint32_t>::max()), state_value(-1),
          bond_component(std::numeric_limits<std::uint32_t>::max()), bond_state(-1),
          molecule_type(std::numeric_limits<std::uint32_t>::max()), scope(-1),
          compartment(std::numeric_limits<std::uint32_t>::max()), compartment_ancestry(false),
          destination_compartment(std::numeric_limits<std::uint32_t>::max()), value(0.0) {}

    static RateExpressionBinding constant(const std::string& binding_name, double constant_value) {
        RateExpressionBinding binding;
        binding.kind = RATE_EXPRESSION_CONSTANT;
        binding.name = binding_name;
        binding.value = constant_value;
        return binding;
    }
};

struct RateExpressionFunction {
    std::string name;
    std::string expression;
    std::vector<std::string> arguments;
};

// Bounded, source-derived rate descriptors. Constant rates retain the old
// path; dynamic bindings are evaluated against the matched root slots and
// simulation context.
struct RateLawDescriptor {
    RateLawKind kind;
    std::uint16_t target;
    std::uint16_t partner_target;
    std::uint32_t component;
    std::uint32_t partner_component;
    double offset;
    double slope;
    double weight;
    std::string expression;
    std::vector<std::uint32_t> expression_components;
    std::vector<RateExpressionBinding> expression_bindings;
    std::vector<RateExpressionFunction> expression_functions;
    RateLawDescriptor()
        : kind(LEGACY_RATE_CONSTANT), target(0), partner_target(1), component(0),
          partner_component(0), offset(0.0), slope(0.0), weight(1.0) {}

    double evaluate(const SimulationState& state, const MatchContext& context,
                    double base_rate) const;
};

} // namespace NFcore2
