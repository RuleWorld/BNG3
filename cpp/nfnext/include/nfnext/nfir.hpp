#pragma once

#include "nfnext/types.hpp"

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

namespace nfnext {

struct SiteSpec {
    std::string name;
    std::vector<std::string> states;
};

struct MoleculeTypeIR {
    TypeId id{0};
    std::string name;
    std::vector<SiteSpec> sites;
};

struct PredicateIR {
    PredicateKind kind{PredicateKind::SiteStateEq};
    TypeId molecule_type{0};
    std::uint16_t site{0};
    std::int32_t value{0};
    std::int32_t aux{0};
};

struct ActionIR {
    ActionKind kind{ActionKind::SetSiteState};
    TypeId molecule_type{0};
    std::uint16_t site{0};
    std::int32_t value{0};
    std::int32_t aux{0};
};

struct ExpandedRuleIR {
    RuleId id{0};
    std::string name;
    double rate{0.0};
    std::vector<PredicateIR> predicates;
    std::vector<ActionIR> actions;
    SourceSpan source;
};

struct RuleFamilyIR {
    FamilyId id{0};
    std::string name;
    std::uint32_t begin_index{0};
    std::uint32_t end_index{0}; // inclusive
    double default_rate{0.0};
    std::vector<double> indexed_rates;
    std::vector<PredicateIR> predicates;
    std::vector<ActionIR> actions;
    std::vector<RuleId> source_rules;
    bool coordinate_parameterized{false};
};

struct DependencyIndexIR {
    // Encoded feature -> families. Feature encoding is compiler-owned and stable
    // within an NFIR cache version.
    std::unordered_map<std::uint64_t, std::vector<FamilyId>> feature_to_families;
};

struct ModelIR {
    static constexpr std::uint32_t kFormatVersion = 1;

    std::string model_name;
    std::vector<MoleculeTypeIR> molecule_types;
    std::vector<ExpandedRuleIR> expanded_rules;
    std::vector<RuleFamilyIR> rule_families;
    DependencyIndexIR dependencies;
    BackendKind preferred_backend{BackendKind::Generic};
    std::uint32_t lattice_length{0};

    std::uint64_t fingerprint() const noexcept;
    std::string summary() const;
};

std::uint64_t encodeFeature(TypeId type, std::uint16_t site, PredicateKind kind, std::int32_t value) noexcept;

} // namespace nfnext
