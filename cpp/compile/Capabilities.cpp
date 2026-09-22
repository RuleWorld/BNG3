#include "Capabilities.hpp"

#include <algorithm>
#include <cctype>
#include <utility>

#include "ast/Expression.hpp"
#include "ast/Model.hpp"
#include "energy/DrivenEnergy.hpp"

namespace bng::compile {

namespace {

void addUnsupported(CapabilityReport& report, Feature feature,
                    const std::string& backend, const std::string& detail) {
    report.set(feature, CapabilityState::Unsupported);
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::UnsupportedFeature;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::BackendCapability;
    diagnostic.entity = backend;
    diagnostic.message = backend + " cannot execute " + detail;
    report.addDiagnostic(std::move(diagnostic));
}

bool isIntegerState(const std::string& value) {
    if (value.empty()) return false;
    const auto first = value.front() == '-' || value.front() == '+' ? 1u : 0u;
    if (first == value.size()) return false;
    return std::all_of(value.begin() + first, value.end(), [](unsigned char c) {
        return std::isdigit(c) != 0;
    });
}

bool containsTableFunction(const ast::Expression& expression) {
    if (expression.kind() == ast::ExpressionKind::TableFunction) return true;
    return std::any_of(expression.args().begin(), expression.args().end(), [](const auto& arg) {
        return containsTableFunction(arg);
    });
}

void inspectExpression(const ast::Expression& expression, FeatureSet& features) {
    if (containsTableFunction(expression)) features.add(Feature::TableFunctions);
}

// Matches the spelling accepted elsewhere in the pipeline (NetWriter's
// parseArrhenius and the NFsim adapters both accept either case).
bool isArrheniusRateLaw(const ast::Expression& expression) {
    if (expression.kind() != ast::ExpressionKind::Function) return false;
    std::string name = expression.name();
    std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return name == "arrhenius";
}

} // namespace

FeatureSet::FeatureSet(std::initializer_list<Feature> features) {
    for (const auto feature : features) add(feature);
}

std::uint64_t FeatureSet::bit(Feature feature) {
    const auto index = static_cast<unsigned>(feature);
    return index >= static_cast<unsigned>(Feature::Count) ? 0 : (std::uint64_t{1} << index);
}

void FeatureSet::add(Feature feature) {
    mask_ |= bit(feature);
}

bool FeatureSet::contains(Feature feature) const {
    return (mask_ & bit(feature)) != 0;
}

std::vector<Feature> FeatureSet::toVector() const {
    std::vector<Feature> result;
    for (unsigned index = 0; index < static_cast<unsigned>(Feature::Count); ++index) {
        const auto feature = static_cast<Feature>(index);
        if (contains(feature)) result.push_back(feature);
    }
    return result;
}

FeatureSet featuresUsed(const ast::Model& model) {
    FeatureSet features;
    if (!model.getEnergyPatterns().empty()) features.add(Feature::EnergyPatterns);
    if (!model.getBarrierPatterns().empty()) features.add(Feature::BarrierPatterns);
    if (!model.getPopulationMaps().empty()) features.add(Feature::PopulationMaps);
    if (!model.getFunctions().empty()) features.add(Feature::Functions);
    if (!model.getCompartments().empty()) features.add(Feature::Compartments);
    for (const auto& parameter : model.getParameters().all()) {
        if (parameter.hasUnit()) { features.add(Feature::Units); break; }
    }
    if (!features.contains(Feature::Units)) {
        for (const auto& compartment : model.getCompartments()) {
            if (compartment.hasUnit()) { features.add(Feature::Units); break; }
        }
    }
    if (!features.contains(Feature::Units)) {
        for (const auto& seed : model.getSeedSpecies()) {
            if (seed.hasUnit()) { features.add(Feature::Units); break; }
        }
    }
    if (!features.contains(Feature::Units)) {
        for (const auto& definition : model.getUnitSystem().definitions()) {
            if (!definition.builtin) { features.add(Feature::Units); break; }
        }
    }
    if (!features.contains(Feature::Units) && !model.getUnitDefaults().empty()) {
        features.add(Feature::Units);
    }
    if (!model.getActions().empty() || !model.getSimulationProtocol().empty()) {
        features.add(Feature::ProtocolActions);
    }

    for (const auto& moleculeType : model.getMoleculeTypes()) {
        for (const auto& component : moleculeType.getComponents()) {
            if (std::any_of(component.allowedStates.begin(), component.allowedStates.end(), isIntegerState)) {
                features.add(Feature::IntegerStates);
            }
        }
    }

    for (const auto& function : model.getFunctions()) {
        if (!function.getArgs().empty()) features.add(Feature::LocalFunctions);
        inspectExpression(function.getExpression(), features);
    }
    for (const auto& energyPattern : model.getEnergyPatterns()) {
        inspectExpression(energyPattern.getExpression(), features);
    }
    for (const auto& rule : model.getReactionRules()) {
        if (rule.hasScopePrefix()) features.add(Feature::LocalFunctions);
        if (rule.hasDrivingWork()) features.add(Feature::DrivenReservoirs);
        for (const auto& rate : rule.getRates()) inspectExpression(rate, features);
    }
    for (const auto& barrier : model.getBarrierPatterns()) {
        if (barrier.hasExpression()) inspectExpression(barrier.expression(), features);
    }
    return features;
}

void CapabilityReport::set(Feature feature, CapabilityState state) {
    states_[feature] = state;
}

CapabilityState CapabilityReport::state(Feature feature) const {
    const auto found = states_.find(feature);
    return found == states_.end() ? CapabilityState::Unsupported : found->second;
}

bool CapabilityReport::isSupported() const {
    const auto unsupported = std::any_of(states_.begin(), states_.end(), [](const auto& entry) {
        return entry.second == CapabilityState::Unsupported;
    });
    const auto errors = std::any_of(diagnostics_.begin(), diagnostics_.end(), [](const auto& diagnostic) {
        return diagnostic.severity == Severity::Error;
    });
    return !unsupported && !errors;
}

void CapabilityReport::addDiagnostic(Diagnostic diagnostic) {
    diagnostics_.push_back(std::move(diagnostic));
}

CapabilityReport capabilitiesFor(const ast::Model& model, BackendKind backend) {
    CapabilityReport report;
    const auto features = featuresUsed(model);
    for (const auto feature : features.toVector()) {
        // The native network compiler and the NFsim adapter both have an
        // execution path for the current semantic families.  Population maps
        // are deliberately different: they require HybridModelGenerator and
        // cannot be dropped into an NFcore::System without changing meaning.
        const auto state = feature == Feature::Units && backend == BackendKind::NFsim
                               ? CapabilityState::Unsupported
                           : feature == Feature::Functions ||
                                   feature == Feature::LocalFunctions ||
                                   feature == Feature::TableFunctions ||
                                   feature == Feature::ProtocolActions
                               ? CapabilityState::CompatibilityOnly
                               : CapabilityState::ExactLowering;
        report.set(feature, state);
    }

    // Barrier patterns and driving reservoirs extend eBNGL beyond canonical
    // NFsim, so no independent oracle exists for them. They stay unsupported
    // at every backend boundary until the gate is explicitly set, and the gate
    // itself is documented as experimental rather than as parity.
    const bool generalEnergy = energy::generalEnergyEnabled();
    if (!generalEnergy) {
        if (features.contains(Feature::BarrierPatterns)) {
            addUnsupported(report, Feature::BarrierPatterns,
                           backend == BackendKind::NFsim ? "NFsim" : "the network compiler",
                           std::string("barrier patterns without ") +
                               energy::generalEnergyGateName() + " set");
        }
        if (features.contains(Feature::DrivenReservoirs)) {
            addUnsupported(report, Feature::DrivenReservoirs,
                           backend == BackendKind::NFsim ? "NFsim" : "the network compiler",
                           std::string("driven_by() reservoir work without ") +
                               energy::generalEnergyGateName() + " set");
        }
    } else {
        // A driving reservoir only has meaning for an Arrhenius rate law: it
        // shifts dG, and a plain rate constant has no dG to shift. Treating it
        // as a no-op would silently discard the user's thermodynamics.
        for (const auto& rule : model.getReactionRules()) {
            if (!rule.hasDrivingWork()) continue;
            const bool arrhenius =
                !rule.getRates().empty() && isArrheniusRateLaw(rule.getRates().front());
            if (!arrhenius) {
                addUnsupported(report, Feature::DrivenReservoirs,
                               backend == BackendKind::NFsim ? "NFsim" : "the network compiler",
                               "driven_by() on a rule whose rate law is not Arrhenius");
                break;
            }
        }
        // A barrier pattern needs energy patterns to be meaningful in the same
        // sense: with no dG in the model there is no Arrhenius expansion for
        // the barrier to modify.
        if (features.contains(Feature::BarrierPatterns) &&
            !features.contains(Feature::EnergyPatterns)) {
            Diagnostic diagnostic;
            diagnostic.code = DiagnosticCode::UnsupportedFeature;
            diagnostic.severity = Severity::Warning;
            diagnostic.category = ValidationCategory::Energy;
            diagnostic.entity = "barrier patterns";
            diagnostic.message =
                "barrier patterns have no effect without energy patterns and an "
                "Arrhenius rate law";
            report.addDiagnostic(std::move(diagnostic));
        }
    }

    if (backend == BackendKind::NFsim && features.contains(Feature::Units)) {
        addUnsupported(report, Feature::Units, "NFsim",
                       "physical-unit annotations without a verified count-rate bridge");
    }

    if (backend == BackendKind::NFsim &&
        features.contains(Feature::PopulationMaps)) {
        addUnsupported(report, Feature::PopulationMaps, "NFsim",
                       "population maps; use the hybrid population backend");
    }
    return report;
}

} // namespace bng::compile
