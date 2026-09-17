#include "SymbolTable.hpp"

#include <string>

#include "ast/Model.hpp"

namespace bng::compile {

namespace {

const char* kindName(SymbolKind kind) {
    switch (kind) {
    case SymbolKind::Parameter: return "parameter";
    case SymbolKind::Function: return "function";
    case SymbolKind::MoleculeType: return "molecule type";
    case SymbolKind::Observable: return "observable";
    case SymbolKind::Compartment: return "compartment";
    case SymbolKind::ReactionRule: return "reaction rule";
    case SymbolKind::EnergyPattern: return "energy pattern";
    case SymbolKind::Count: break;
    }
    return "symbol";
}

} // namespace

SymbolTable SymbolTable::fromModel(const ast::Model& model) {
    SymbolTable result;
    for (const auto& parameter : model.getParameters().all()) {
        result.add(SymbolKind::Parameter, parameter.getName());
    }
    for (const auto& function : model.getFunctions()) {
        result.add(SymbolKind::Function, function.getName());
    }
    for (const auto& moleculeType : model.getMoleculeTypes()) {
        result.add(SymbolKind::MoleculeType, moleculeType.getName());
    }
    for (const auto& observable : model.getObservables()) {
        result.add(SymbolKind::Observable, observable.getName());
    }
    for (const auto& compartment : model.getCompartments()) {
        result.add(SymbolKind::Compartment, compartment.getName());
    }
    for (const auto& rule : model.getReactionRules()) {
        result.add(SymbolKind::ReactionRule, rule.getRuleName());
    }
    for (const auto& energyPattern : model.getEnergyPatterns()) {
        result.add(SymbolKind::EnergyPattern, energyPattern.getLabel());
    }
    return result;
}

void SymbolTable::add(SymbolKind kind, const std::string& name) {
    if (name.empty()) return;
    auto& indices = namespaces_[static_cast<std::size_t>(kind)].indices;
    const auto [found, inserted] = indices.emplace(name, indices.size());
    if (inserted) return;

    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::Symbols;
    diagnostic.entity = name;
    diagnostic.message = "duplicate " + std::string(kindName(kind)) + " declaration: " + name;
    diagnostics_.push_back(std::move(diagnostic));
}

std::optional<SymbolRef> SymbolTable::resolve(SymbolKind kind, std::string_view name) const {
    if (kind == SymbolKind::Count) return std::nullopt;
    const auto& indices = namespaces_[static_cast<std::size_t>(kind)].indices;
    const auto found = indices.find(std::string(name));
    if (found == indices.end()) return std::nullopt;
    return SymbolRef{kind, found->second};
}

std::optional<ParameterId> SymbolTable::resolveParameter(std::string_view name) const {
    return resolveTyped<ParameterId>(SymbolKind::Parameter, name);
}

std::optional<FunctionId> SymbolTable::resolveFunction(std::string_view name) const {
    return resolveTyped<FunctionId>(SymbolKind::Function, name);
}

std::optional<MoleculeTypeId> SymbolTable::resolveMoleculeType(std::string_view name) const {
    return resolveTyped<MoleculeTypeId>(SymbolKind::MoleculeType, name);
}

std::optional<ObservableId> SymbolTable::resolveObservable(std::string_view name) const {
    return resolveTyped<ObservableId>(SymbolKind::Observable, name);
}

std::optional<CompartmentId> SymbolTable::resolveCompartment(std::string_view name) const {
    return resolveTyped<CompartmentId>(SymbolKind::Compartment, name);
}

std::optional<ReactionRuleId> SymbolTable::resolveReactionRule(std::string_view name) const {
    return resolveTyped<ReactionRuleId>(SymbolKind::ReactionRule, name);
}

std::optional<EnergyPatternId> SymbolTable::resolveEnergyPattern(std::string_view name) const {
    return resolveTyped<EnergyPatternId>(SymbolKind::EnergyPattern, name);
}

std::size_t SymbolTable::size(SymbolKind kind) const {
    if (kind == SymbolKind::Count) return 0;
    return namespaces_[static_cast<std::size_t>(kind)].indices.size();
}

} // namespace bng::compile
