#pragma once

#include <cstdint>

namespace NFcore2 {

class SimulationState;
struct MatchContext;

enum RateLawKind {
    LEGACY_RATE_CONSTANT = 0,
    LEGACY_RATE_LOCAL_LINEAR = 1,
    LEGACY_RATE_DOR_PRODUCT = 2
};

// Bounded, source-derived rate descriptors.  Constant rates retain the old
// path; the two dynamic forms are evaluated against the matched root slots.
struct RateLawDescriptor {
    RateLawKind kind;
    std::uint16_t target;
    std::uint16_t partner_target;
    std::uint32_t component;
    std::uint32_t partner_component;
    double offset;
    double slope;
    double weight;
    RateLawDescriptor()
        : kind(LEGACY_RATE_CONSTANT), target(0), partner_target(1), component(0),
          partner_component(0), offset(0.0), slope(0.0), weight(1.0) {}

    double evaluate(const SimulationState& state, const MatchContext& context,
                    double base_rate) const;
};

} // namespace NFcore2
