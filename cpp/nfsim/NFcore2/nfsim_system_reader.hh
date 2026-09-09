#pragma once
#include "nfsim_adapter_contract.hh"
#include <cstddef>
#include <string>
#include <vector>

namespace NFcore2 {

struct NativeReactionHeader {
    std::string name;
    double base_rate;
    std::uint32_t parameter_index;
    std::uint32_t coordinate;
    std::vector<std::uint32_t> reactant_types;
    bool uses_local_function;
    bool uses_connected_to;
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
    NativeReactionHeader() : base_rate(0.0), parameter_index(0), coordinate(0),
        uses_local_function(false), uses_connected_to(false), rate_law(NATIVE_RATE_CONSTANT),
        local_offset(0.0), local_slope(0.0), local_state_component(0), dor_weight(1.0),
        dor_state_component(0), dor_partner_reactant(1), dor_partner_state_component(0) {}
};

class NFsimSystemReader {
public:
    virtual ~NFsimSystemReader() {}
    virtual std::size_t moleculeTypeCount() const = 0;
    virtual NativeMoleculeTypeSnapshot moleculeType(std::size_t index) const = 0;
    virtual std::size_t reactionCount() const = 0;
    virtual NativeReactionHeader reactionHeader(std::size_t index) const = 0;
    virtual void collectDependencies(std::size_t reaction_index,
        std::vector<NativeDependencySnapshot>& out) const = 0;
    virtual void collectTransforms(std::size_t reaction_index,
        std::vector<NativeTransformSnapshot>& out) const = 0;
    virtual void collectCompartments(std::vector<NativeCompartmentSnapshot>&) const {}
    virtual void collectGraphPatterns(std::size_t, std::vector<NativeGraphPatternSnapshot>&) const {}
};

NativeModelSnapshot readNFsimSystem(const NFsimSystemReader& reader);

} // namespace NFcore2
