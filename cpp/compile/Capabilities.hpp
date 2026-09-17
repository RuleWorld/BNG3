#pragma once

#include <cstdint>
#include <initializer_list>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace bng::ast {
class Model;
}

namespace bng::compile {

enum class Severity {
    Info,
    Warning,
    Error,
};

enum class ValidationCategory {
    Syntax,
    InternalStructure,
    Symbols,
    Patterns,
    Rules,
    Expressions,
    RateLaws,
    Energy,
    Units,
    BackendCapability,
    ModelingPractice,
};

enum class DiagnosticCode {
    InvalidModel,
    UnsupportedFeature,
};

struct SourceSpan {
    std::size_t line = 0;
    std::size_t column = 0;
    std::size_t endLine = 0;
    std::size_t endColumn = 0;
};

struct Diagnostic {
    DiagnosticCode code = DiagnosticCode::InvalidModel;
    Severity severity = Severity::Error;
    ValidationCategory category = ValidationCategory::InternalStructure;
    std::string message;
    std::optional<SourceSpan> source;
    std::optional<std::string> entity;
};

enum class Feature : std::uint8_t {
    EnergyPatterns,
    PopulationMaps,
    Functions,
    LocalFunctions,
    TableFunctions,
    Compartments,
    IntegerStates,
    ProtocolActions,
    Count,
};

class FeatureSet {
public:
    FeatureSet() = default;
    FeatureSet(std::initializer_list<Feature> features);

    void add(Feature feature);
    bool contains(Feature feature) const;
    bool empty() const { return mask_ == 0; }
    std::vector<Feature> toVector() const;

private:
    static std::uint64_t bit(Feature feature);
    std::uint64_t mask_ = 0;
};

FeatureSet featuresUsed(const ast::Model& model);

enum class BackendKind {
    Network,
    NFsim,
};

enum class CapabilityState {
    Native,
    ExactLowering,
    CompatibilityOnly,
    Unsupported,
};

class CapabilityReport {
public:
    void set(Feature feature, CapabilityState state);
    CapabilityState state(Feature feature) const;
    bool isSupported() const;

    void addDiagnostic(Diagnostic diagnostic);
    const std::vector<Diagnostic>& diagnostics() const { return diagnostics_; }

private:
    std::map<Feature, CapabilityState> states_;
    std::vector<Diagnostic> diagnostics_;
};

// Report support before a backend allocates mutable runtime state.  A
// CompatibilityOnly feature is supported through the existing compatibility
// bridge; Unsupported is a hard fail and must never be silently ignored.
CapabilityReport capabilitiesFor(const ast::Model& model, BackendKind backend);

} // namespace bng::compile
