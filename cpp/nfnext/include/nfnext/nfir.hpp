#pragma once

#include "nfnext/types.hpp"

#include <cstdint>
#include <initializer_list>
#include <string>
#include <unordered_map>
#include <utility>
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

enum class RateLawKind : std::uint8_t {
    Elementary = 0,
    Function = 1
};

struct RateLawIR {
    RateLawKind kind{RateLawKind::Elementary};
    std::string expression;
};

enum class MolecularityKind : std::uint8_t {
    SameComplex = 0,
    DifferentComplex = 1
};

struct MolecularityConstraint {
    MolecularityKind kind{MolecularityKind::SameComplex};
    std::uint16_t left{0};
    std::uint16_t right{0};

    static MolecularityConstraint sameComplex(std::uint16_t a, std::uint16_t b) noexcept {
        return {MolecularityKind::SameComplex, a, b};
    }
    static MolecularityConstraint differentComplex(std::uint16_t a, std::uint16_t b) noexcept {
        return {MolecularityKind::DifferentComplex, a, b};
    }
};

struct PatternIR {
    enum class SiteConstraintKind : std::uint8_t {
        State = 0,
        StateSet = 1,
        Free = 2,
        Bound = 3
    };

    struct SiteConstraint {
        SiteConstraintKind kind{SiteConstraintKind::State};
        std::uint32_t site{0};
        std::int32_t state{0};
        std::vector<std::int32_t> states;
    };

    struct Node {
        TypeId molecule_type{0};
        std::vector<SiteConstraint> constraints;

        void siteState(std::uint32_t site, std::int32_t state) {
            constraints.push_back({SiteConstraintKind::State, site, state, {}});
        }
        void siteStateSet(std::uint32_t site, std::vector<std::int32_t> states) {
            constraints.push_back({SiteConstraintKind::StateSet, site, 0, std::move(states)});
        }
        void siteFree(std::uint32_t site) {
            constraints.push_back({SiteConstraintKind::Free, site, 0, {}});
        }
        void siteBound(std::uint32_t site) {
            constraints.push_back({SiteConstraintKind::Bound, site, 0, {}});
        }
    };

    struct Bond {
        std::size_t first{0};
        std::uint32_t first_site{0};
        std::size_t second{0};
        std::uint32_t second_site{0};
    };

    std::vector<MolecularityConstraint> molecularity;
    std::vector<Node> nodes;
    std::vector<Bond> bonds;
    std::vector<std::pair<std::size_t, std::size_t>> aliases;
    std::vector<std::pair<std::size_t, std::size_t>> connected_to;
    std::vector<std::vector<std::size_t>> interchangeable;

    std::size_t addNode(TypeId type) {
        nodes.push_back(Node{type, {}});
        return nodes.size() - 1;
    }
    Node& node(std::size_t id) { return nodes.at(id); }
    const Node& node(std::size_t id) const { return nodes.at(id); }
    void requireBond(std::size_t first, std::uint32_t first_site,
                     std::size_t second, std::uint32_t second_site) {
        bonds.push_back({first, first_site, second, second_site});
    }
    void allowAlias(std::size_t first, std::size_t second) {
        aliases.emplace_back(first, second);
    }
    void requireSameComplex(std::size_t first, std::size_t second) {
        molecularity.push_back(MolecularityConstraint::sameComplex(
            static_cast<std::uint16_t>(first), static_cast<std::uint16_t>(second)));
    }
    void requireDifferentComplex(std::size_t first, std::size_t second) {
        molecularity.push_back(MolecularityConstraint::differentComplex(
            static_cast<std::uint16_t>(first), static_cast<std::uint16_t>(second)));
    }
    void requireConnectedTo(std::size_t first, std::size_t second) {
        connected_to.emplace_back(first, second);
    }
    void markInterchangeable(std::initializer_list<std::size_t> group) {
        interchangeable.emplace_back(group);
    }
};

struct PredicateIR {
    PredicateKind kind{PredicateKind::SiteStateEq};
    TypeId molecule_type{0};
    std::uint16_t site{0};
    std::int32_t value{0};
    std::int32_t aux{0};
    std::vector<std::int32_t> state_set;

    static PredicateIR stateSet(TypeId type, std::uint16_t site,
                                 std::vector<std::int32_t> states) {
        PredicateIR predicate;
        predicate.kind = PredicateKind::SiteStateEq;
        predicate.molecule_type = type;
        predicate.site = site;
        predicate.state_set = std::move(states);
        return predicate;
    }
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
    RateLawIR rate_law;
    std::vector<PredicateIR> predicates;
    std::vector<ActionIR> actions;
    PatternIR pattern;
    SourceSpan source;
    std::unordered_map<std::string, std::string> annotations;
};

struct RuleFamilyIR {
    FamilyId id{0};
    std::string name;
    std::uint32_t begin_index{0};
    std::uint32_t end_index{0}; // inclusive
    double default_rate{0.0};
    RateLawIR rate_law;
    std::vector<double> indexed_rates;
    std::vector<PredicateIR> predicates;
    std::vector<ActionIR> actions;
    PatternIR pattern;
    std::vector<RuleId> source_rules;
    bool coordinate_parameterized{false};
};

struct DependencyIndexIR {
    // Encoded feature -> families. Feature encoding is compiler-owned and stable
    // within an NFIR cache version.
    std::unordered_map<std::uint64_t, std::vector<FamilyId>> feature_to_families;
};

struct ModelIR {
    static constexpr std::uint32_t kFormatVersion = 3;

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
