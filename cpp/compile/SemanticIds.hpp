#pragma once

#include <cstddef>

#include "SymbolTable.hpp"

namespace bng::compile {

// Component and state identifiers are declaration-local: component names may
// repeat across molecule types and state names may repeat across components.
// Keeping the owning declaration in the ID prevents accidental cross-type use.
struct ComponentTypeId {
    MoleculeTypeId moleculeType;
    std::size_t index = static_cast<std::size_t>(-1);

    constexpr bool valid() const noexcept {
        return moleculeType.valid() && index != static_cast<std::size_t>(-1);
    }

    friend constexpr bool operator==(ComponentTypeId left, ComponentTypeId right) noexcept {
        return left.moleculeType == right.moleculeType && left.index == right.index;
    }
    friend constexpr bool operator!=(ComponentTypeId left, ComponentTypeId right) noexcept {
        return !(left == right);
    }
};

struct StateId {
    ComponentTypeId component;
    std::size_t index = static_cast<std::size_t>(-1);

    constexpr bool valid() const noexcept {
        return component.valid() && index != static_cast<std::size_t>(-1);
    }

    friend constexpr bool operator==(StateId left, StateId right) noexcept {
        return left.component == right.component && left.index == right.index;
    }
    friend constexpr bool operator!=(StateId left, StateId right) noexcept {
        return !(left == right);
    }
};

} // namespace bng::compile
