#pragma once

#include <cstdint>
#include <limits>
#include <string>

namespace nfnext {

using TypeId = std::uint32_t;
using ParameterId = std::uint32_t;
using MoleculeTypeId = std::uint32_t;
using ComponentTypeId = std::uint32_t;
using ObservableId = std::uint32_t;
using FunctionId = std::uint32_t;
using CompartmentId = std::uint32_t;
using RuleId = std::uint32_t;
using FamilyId = std::uint32_t;
using FeatureId = std::uint32_t;
using Position = std::uint64_t;

constexpr std::uint32_t kInvalidIndex = std::numeric_limits<std::uint32_t>::max();

struct ParticleId {
    std::uint32_t index{kInvalidIndex};
    std::uint32_t generation{0};

    bool valid() const noexcept { return index != kInvalidIndex; }
    friend bool operator==(const ParticleId& a, const ParticleId& b) noexcept {
        return a.index == b.index && a.generation == b.generation;
    }
    friend bool operator!=(const ParticleId& a, const ParticleId& b) noexcept { return !(a == b); }
};

enum class BackendKind : std::uint8_t {
    Reference = 0,
    Generic = 1,
    Lattice = 2
};

enum class PredicateKind : std::uint8_t {
    SiteStateEq,
    SiteBound,
    SiteFree,
    PositionEq,
    PositionRange,
    NeighborFree,
    NeighborOccupied
};

enum class ActionKind : std::uint8_t {
    SetSiteState,
    Bind,
    Unbind,
    Create,
    Destroy,
    MovePosition
};

struct SourceSpan {
    std::string source;
    std::uint32_t line{0};
};

} // namespace nfnext
