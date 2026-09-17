#pragma once

#include <cstddef>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "Capabilities.hpp"

namespace bng::ast {
class Model;
}

namespace bng::compile {

enum class SymbolKind {
    Parameter,
    Function,
    MoleculeType,
    Observable,
    Compartment,
    ReactionRule,
    EnergyPattern,
    Count,
};

template <typename Tag>
class SymbolId {
public:
    constexpr SymbolId() = default;
    static constexpr SymbolId fromDenseIndex(std::size_t value) {
        return SymbolId(value);
    }
    constexpr bool valid() const { return value_ != invalidValue; }
    constexpr std::size_t value() const { return value_; }

    friend constexpr bool operator==(SymbolId left, SymbolId right) {
        return left.value_ == right.value_;
    }
    friend constexpr bool operator!=(SymbolId left, SymbolId right) {
        return !(left == right);
    }

private:
    static constexpr std::size_t invalidValue = static_cast<std::size_t>(-1);
    explicit constexpr SymbolId(std::size_t value) : value_(value) {}
    std::size_t value_ = invalidValue;

    friend class SymbolTable;
};

struct ParameterTag;
struct FunctionTag;
struct MoleculeTypeTag;
struct ObservableTag;
struct CompartmentTag;
struct ReactionRuleTag;
struct EnergyPatternTag;
struct SeedSpeciesTag;

using ParameterId = SymbolId<ParameterTag>;
using FunctionId = SymbolId<FunctionTag>;
using MoleculeTypeId = SymbolId<MoleculeTypeTag>;
using ObservableId = SymbolId<ObservableTag>;
using CompartmentId = SymbolId<CompartmentTag>;
using ReactionRuleId = SymbolId<ReactionRuleTag>;
using EnergyPatternId = SymbolId<EnergyPatternTag>;
using SeedSpeciesId = SymbolId<SeedSpeciesTag>;

struct SymbolRef {
    SymbolKind kind = SymbolKind::Parameter;
    std::size_t index = 0;
};

// Name resolution owned by the semantic compile layer. IDs are namespace-
// specific and cannot be accidentally passed as another declaration kind.
class SymbolTable {
public:
    static SymbolTable fromModel(const ast::Model& model);

    std::optional<SymbolRef> resolve(SymbolKind kind, std::string_view name) const;
    std::optional<ParameterId> resolveParameter(std::string_view name) const;
    std::optional<FunctionId> resolveFunction(std::string_view name) const;
    std::optional<MoleculeTypeId> resolveMoleculeType(std::string_view name) const;
    std::optional<ObservableId> resolveObservable(std::string_view name) const;
    std::optional<CompartmentId> resolveCompartment(std::string_view name) const;
    std::optional<ReactionRuleId> resolveReactionRule(std::string_view name) const;
    std::optional<EnergyPatternId> resolveEnergyPattern(std::string_view name) const;

    std::size_t size(SymbolKind kind) const;
    const std::vector<Diagnostic>& diagnostics() const { return diagnostics_; }

private:
    struct Namespace {
        std::unordered_map<std::string, std::size_t> indices;
    };

    void add(SymbolKind kind, const std::string& name);

    template <typename Id>
    std::optional<Id> resolveTyped(SymbolKind kind, std::string_view name) const {
        const auto resolved = resolve(kind, name);
        if (!resolved.has_value()) return std::nullopt;
        return Id(resolved->index);
    }

    Namespace namespaces_[static_cast<std::size_t>(SymbolKind::Count)];
    std::vector<Diagnostic> diagnostics_;
};

} // namespace bng::compile
