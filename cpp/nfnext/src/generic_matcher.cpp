#include "nfnext/generic_matcher.hpp"

#include "nfnext/validator.hpp"

#include <algorithm>
#include <functional>
#include <numeric>
#include <sstream>
#include <tuple>
#include <utility>

namespace nfnext {
namespace {

const MoleculeTypeIR* findType(const ModelIR& model, TypeId id) {
    for (const auto& type : model.molecule_types)
        if (type.id == id) return &type;
    return nullptr;
}

bool contains(const std::vector<std::int32_t>& states, std::int32_t value) {
    return std::find(states.begin(), states.end(), value) != states.end();
}

bool sameSiteConstraint(const PatternIR::SiteConstraint& a,
                        const PatternIR::SiteConstraint& b) {
    return a.site == b.site;
}

bool aliases(const PatternIR& pattern, std::size_t a, std::size_t b) {
    if (a == b) return true;
    return std::any_of(pattern.aliases.begin(), pattern.aliases.end(),
                       [a, b](const auto& pair) {
                           return (pair.first == a && pair.second == b) ||
                                  (pair.first == b && pair.second == a);
                       });
}

void validatePattern(const PatternIR& pattern, const ModelIR& model) {
    validateModel(model);

    auto requireNode = [&pattern](std::size_t node, const char* what) {
        if (node >= pattern.nodes.size()) {
            throw PatternCompileError(std::string(what) + " references unknown pattern node");
        }
    };

    for (std::size_t node_index = 0; node_index < pattern.nodes.size(); ++node_index) {
        const auto& node = pattern.nodes[node_index];
        const auto* type = findType(model, node.molecule_type);
        if (type == nullptr) {
            throw PatternCompileError("pattern node references unknown molecule type");
        }
        for (const auto& constraint : node.constraints) {
            if (constraint.site >= type->sites.size()) {
                throw PatternCompileError("pattern site constraint references unknown site");
            }
            if (constraint.kind == PatternIR::SiteConstraintKind::StateSet &&
                constraint.states.empty()) {
                throw PatternCompileError("pattern state set cannot be empty");
            }
            const auto& states = type->sites[constraint.site].states;
            auto validState = [&states](std::int32_t state) {
                return states.empty() || (state >= 0 &&
                    static_cast<std::size_t>(state) < states.size());
            };
            if (constraint.kind == PatternIR::SiteConstraintKind::State &&
                !validState(constraint.state)) {
                throw PatternCompileError("pattern state constraint is outside the site schema");
            }
            if (constraint.kind == PatternIR::SiteConstraintKind::StateSet) {
                for (const auto state : constraint.states)
                    if (!validState(state))
                        throw PatternCompileError("pattern state set is outside the site schema");
            }
        }
        for (std::size_t i = 0; i < node.constraints.size(); ++i) {
            for (std::size_t j = i + 1; j < node.constraints.size(); ++j) {
                const auto& left = node.constraints[i];
                const auto& right = node.constraints[j];
                if (!sameSiteConstraint(left, right)) continue;
                const bool left_state = left.kind == PatternIR::SiteConstraintKind::State;
                const bool right_state = right.kind == PatternIR::SiteConstraintKind::State;
                const bool left_set = left.kind == PatternIR::SiteConstraintKind::StateSet;
                const bool right_set = right.kind == PatternIR::SiteConstraintKind::StateSet;
                if (left_state && right_state && left.state != right.state)
                    throw PatternCompileError("pattern has conflicting state constraints");
                if (left_state && right_set && !contains(right.states, left.state))
                    throw PatternCompileError("pattern state is absent from its state set");
                if (right_state && left_set && !contains(left.states, right.state))
                    throw PatternCompileError("pattern state is absent from its state set");
                if (left_set && right_set) {
                    const bool overlap = std::any_of(left.states.begin(), left.states.end(),
                        [&right](auto state) { return contains(right.states, state); });
                    if (!overlap) throw PatternCompileError("pattern state sets do not overlap");
                }
                if ((left.kind == PatternIR::SiteConstraintKind::Free &&
                     right.kind == PatternIR::SiteConstraintKind::Bound) ||
                    (left.kind == PatternIR::SiteConstraintKind::Bound &&
                     right.kind == PatternIR::SiteConstraintKind::Free))
                    throw PatternCompileError("pattern site cannot be both free and bound");
            }
        }
    }

    for (const auto& bond : pattern.bonds) {
        requireNode(bond.first, "bond");
        requireNode(bond.second, "bond");
        const auto* first_type = findType(model, pattern.nodes[bond.first].molecule_type);
        const auto* second_type = findType(model, pattern.nodes[bond.second].molecule_type);
        if (bond.first_site >= first_type->sites.size() ||
            bond.second_site >= second_type->sites.size())
            throw PatternCompileError("pattern bond references unknown site");
        if (bond.first == bond.second && bond.first_site == bond.second_site)
            throw PatternCompileError("pattern bond cannot connect a site to itself");
    }
    for (const auto& pair : pattern.aliases) {
        requireNode(pair.first, "alias");
        requireNode(pair.second, "alias");
    }
    for (const auto& constraint : pattern.molecularity) {
        requireNode(constraint.left, "molecularity");
        requireNode(constraint.right, "molecularity");
    }
    for (const auto& pair : pattern.connected_to) {
        requireNode(pair.first, "connected-to");
        requireNode(pair.second, "connected-to");
    }
    for (const auto& group : pattern.interchangeable) {
        for (const auto node : group) requireNode(node, "interchangeable group");
        for (std::size_t i = 0; i < group.size(); ++i) {
            for (std::size_t j = i + 1; j < group.size(); ++j) {
                if (group[i] == group[j])
                    throw PatternCompileError("interchangeable group repeats a node");
                if (pattern.nodes[group[i]].molecule_type != pattern.nodes[group[j]].molecule_type)
                    throw PatternCompileError("interchangeable nodes must have the same molecule type");
            }
        }
    }

    for (std::size_t node = 0; node < pattern.nodes.size(); ++node) {
        for (const auto& constraint : pattern.nodes[node].constraints) {
            const bool free = constraint.kind == PatternIR::SiteConstraintKind::Free;
            if (!free && constraint.kind != PatternIR::SiteConstraintKind::Bound) continue;
            for (const auto& bond : pattern.bonds) {
                const bool endpoint =
                    (bond.first == node && bond.first_site == constraint.site) ||
                    (bond.second == node && bond.second_site == constraint.site);
                if (endpoint && free)
                    throw PatternCompileError("pattern site is required free but has a bond");
            }
        }
    }
}

bool nodeMatches(const PatternIR::Node& node, ParticleId particle,
                 const GenericGraphState& state) {
    if (state.type(particle) != node.molecule_type) return false;
    for (const auto& constraint : node.constraints) {
        switch (constraint.kind) {
            case PatternIR::SiteConstraintKind::State:
                if (state.siteState(particle, static_cast<std::uint16_t>(constraint.site)) !=
                    constraint.state) return false;
                break;
            case PatternIR::SiteConstraintKind::StateSet:
                if (!contains(constraint.states,
                              state.siteState(particle, static_cast<std::uint16_t>(constraint.site))))
                    return false;
                break;
            case PatternIR::SiteConstraintKind::Free:
                if (state.bound(particle, static_cast<std::uint16_t>(constraint.site))) return false;
                break;
            case PatternIR::SiteConstraintKind::Bound:
                if (!state.bound(particle, static_cast<std::uint16_t>(constraint.site))) return false;
                break;
        }
    }
    return true;
}

bool exactBond(const PatternIR::Bond& bond, const std::vector<ParticleId>& assignment,
               const GenericGraphState& state) {
    const auto first = state.bond(assignment[bond.first],
                                  static_cast<std::uint16_t>(bond.first_site));
    const auto second = state.bond(assignment[bond.second],
                                   static_cast<std::uint16_t>(bond.second_site));
    return first.particle == assignment[bond.second] &&
           first.site == bond.second_site &&
           second.particle == assignment[bond.first] &&
           second.site == bond.first_site;
}

bool partialTopologyMatches(const PatternIR& pattern, std::size_t assigned_count,
                            const std::vector<ParticleId>& assignment,
                            const GenericGraphState& state) {
    for (const auto& bond : pattern.bonds) {
        if (bond.first >= assigned_count || bond.second >= assigned_count) continue;
        if (!exactBond(bond, assignment, state)) return false;
    }
    for (const auto& constraint : pattern.molecularity) {
        if (constraint.left >= assigned_count || constraint.right >= assigned_count) continue;
        const bool same = state.sameComplex(assignment[constraint.left], assignment[constraint.right]);
        if ((constraint.kind == MolecularityKind::SameComplex && !same) ||
            (constraint.kind == MolecularityKind::DifferentComplex && same)) return false;
    }
    for (const auto& pair : pattern.connected_to) {
        if (pair.first >= assigned_count || pair.second >= assigned_count) continue;
        if (!state.sameComplex(assignment[pair.first], assignment[pair.second])) return false;
    }
    return true;
}

bool idLess(const ParticleId& a, const ParticleId& b) {
    return std::tie(a.index, a.generation) < std::tie(b.index, b.generation);
}

bool embeddingLess(const Embedding& a, const Embedding& b) {
    for (std::size_t i = 0; i < a.particles().size() && i < b.particles().size(); ++i) {
        if (a.particles()[i] == b.particles()[i]) continue;
        return idLess(a.particles()[i], b.particles()[i]);
    }
    if (a.particles().size() != b.particles().size())
        return a.particles().size() < b.particles().size();
    return a.typeSignature() < b.typeSignature();
}

bool embeddingEqual(const Embedding& a, const Embedding& b) { return a == b; }

std::vector<Embedding> canonicalizeForPattern(const PatternIR& pattern,
                                               const std::vector<Embedding>& embeddings) {
    std::vector<Embedding> canonical;
    canonical.reserve(embeddings.size());
    for (const auto& original : embeddings) {
        Embedding embedding = original;
        for (const auto& group : pattern.interchangeable) {
            std::vector<std::pair<ParticleId, TypeId>> values;
            values.reserve(group.size());
            for (const auto node : group)
                values.emplace_back(embedding.particle(node), embedding.typeSignature()[node]);
            std::sort(values.begin(), values.end(), [](const auto& left, const auto& right) {
                return idLess(left.first, right.first);
            });
            for (std::size_t i = 0; i < group.size(); ++i) {
                embedding.setNode(group[i], values[i].first, values[i].second);
            }
        }
        canonical.push_back(std::move(embedding));
    }
    std::sort(canonical.begin(), canonical.end(), embeddingLess);
    canonical.erase(std::unique(canonical.begin(), canonical.end(), embeddingEqual), canonical.end());
    return canonical;
}

struct BondKey {
    std::size_t first{0};
    std::uint32_t first_site{0};
    std::size_t second{0};
    std::uint32_t second_site{0};
    bool operator<(const BondKey& other) const noexcept {
        return std::tie(first, first_site, second, second_site) <
               std::tie(other.first, other.first_site, other.second, other.second_site);
    }
    bool operator==(const BondKey& other) const noexcept {
        return first == other.first && first_site == other.first_site &&
               second == other.second && second_site == other.second_site;
    }
};

BondKey normalizeBond(std::size_t first, std::uint32_t first_site,
                      std::size_t second, std::uint32_t second_site) {
    if (std::tie(second, second_site) < std::tie(first, first_site))
        return {second, second_site, first, first_site};
    return {first, first_site, second, second_site};
}

std::vector<BondKey> bondKeys(const PatternIR& pattern,
                              const std::vector<std::size_t>* permutation = nullptr) {
    std::vector<BondKey> keys;
    keys.reserve(pattern.bonds.size());
    for (const auto& bond : pattern.bonds) {
        const auto first = permutation == nullptr ? bond.first : permutation->at(bond.first);
        const auto second = permutation == nullptr ? bond.second : permutation->at(bond.second);
        keys.push_back(normalizeBond(first, bond.first_site, second, bond.second_site));
    }
    std::sort(keys.begin(), keys.end());
    return keys;
}

using PairKey = std::pair<std::size_t, std::size_t>;

std::vector<PairKey> pairKeys(const std::vector<std::pair<std::size_t, std::size_t>>& pairs,
                              const std::vector<std::size_t>* permutation = nullptr) {
    std::vector<PairKey> keys;
    keys.reserve(pairs.size());
    for (const auto& pair : pairs) {
        auto first = permutation == nullptr ? pair.first : permutation->at(pair.first);
        auto second = permutation == nullptr ? pair.second : permutation->at(pair.second);
        if (second < first) std::swap(first, second);
        keys.emplace_back(first, second);
    }
    std::sort(keys.begin(), keys.end());
    return keys;
}

std::vector<std::tuple<unsigned, std::size_t, std::size_t>> molecularityKeys(
    const PatternIR& pattern, const std::vector<std::size_t>* permutation = nullptr) {
    std::vector<std::tuple<unsigned, std::size_t, std::size_t>> keys;
    keys.reserve(pattern.molecularity.size());
    for (const auto& constraint : pattern.molecularity) {
        auto first = permutation == nullptr ? constraint.left : permutation->at(constraint.left);
        auto second = permutation == nullptr ? constraint.right : permutation->at(constraint.right);
        if (second < first) std::swap(first, second);
        keys.emplace_back(static_cast<unsigned>(constraint.kind), first, second);
    }
    std::sort(keys.begin(), keys.end());
    return keys;
}

bool nodeEquivalent(const PatternIR::Node& a, const PatternIR::Node& b) {
    if (a.molecule_type != b.molecule_type || a.constraints.size() != b.constraints.size()) return false;
    return std::equal(a.constraints.begin(), a.constraints.end(), b.constraints.begin(),
        [](const auto& left, const auto& right) {
            return left.kind == right.kind && left.site == right.site &&
                   left.state == right.state && left.states == right.states;
        });
}

bool equivalentUnder(const PatternIR& pattern, const std::vector<std::size_t>& permutation) {
    for (std::size_t node = 0; node < pattern.nodes.size(); ++node)
        if (!nodeEquivalent(pattern.nodes[node], pattern.nodes[permutation[node]])) return false;
    if (bondKeys(pattern, &permutation) != bondKeys(pattern)) return false;
    if (pairKeys(pattern.aliases, &permutation) != pairKeys(pattern.aliases)) return false;
    if (pairKeys(pattern.connected_to, &permutation) != pairKeys(pattern.connected_to)) return false;
    if (molecularityKeys(pattern, &permutation) != molecularityKeys(pattern)) return false;
    return true;
}

std::size_t automorphismCount(const PatternIR& pattern) {
    std::vector<std::size_t> permutation(pattern.nodes.size());
    std::iota(permutation.begin(), permutation.end(), 0);
    std::size_t count = 0;
    do {
        if (equivalentUnder(pattern, permutation)) ++count;
    } while (std::next_permutation(permutation.begin(), permutation.end()));
    return count;
}

} // namespace

std::size_t MatchPlan::automorphismCount() const { return ::nfnext::automorphismCount(pattern_); }

MatchPlan compileMatchPlan(const PatternIR& pattern, const ModelIR& model) {
    validatePattern(pattern, model);
    return MatchPlan(pattern, model);
}

std::size_t bruteForceAutomorphismCount(const PatternIR& pattern, const ModelIR& model) {
    validatePattern(pattern, model);
    return automorphismCount(pattern);
}

std::vector<Embedding> GenericMatcher::enumerate(const PatternIR& pattern,
                                                  const GenericGraphState& state,
                                                  MatchMode mode) const {
    (void)mode;
    compileMatchPlan(pattern, *model_);
    const auto particles = state.liveParticles();
    std::vector<ParticleId> assignment(pattern.nodes.size());
    std::vector<bool> assigned(pattern.nodes.size(), false);
    std::vector<Embedding> matches;
    std::vector<TypeId> types;
    types.reserve(pattern.nodes.size());

    std::function<void(std::size_t)> visit = [&](std::size_t node) {
        if (node == pattern.nodes.size()) {
            matches.emplace_back(assignment, types);
            return;
        }
        for (const auto particle : particles) {
            if (!nodeMatches(pattern.nodes[node], particle, state)) continue;
            bool duplicate = false;
            for (std::size_t previous = 0; previous < node; ++previous) {
                if (assigned[previous] && assignment[previous] == particle &&
                    !aliases(pattern, previous, node)) {
                    duplicate = true;
                    break;
                }
            }
            if (duplicate) continue;
            assignment[node] = particle;
            assigned[node] = true;
            types.push_back(state.type(particle));
            if (partialTopologyMatches(pattern, node + 1, assignment, state)) visit(node + 1);
            types.pop_back();
            assigned[node] = false;
        }
    };
    visit(0);
    return canonicalizeForPattern(pattern, matches);
}

std::vector<Embedding> GenericMatcher::canonicalEmbeddings(const PatternIR& pattern,
                                                            const GenericGraphState& state) const {
    return canonicalize(enumerate(pattern, state, MatchMode::CompiledPlan));
}

std::vector<Embedding> GenericMatcher::canonicalize(const std::vector<Embedding>& embeddings) const {
    std::vector<Embedding> canonical = embeddings;
    std::sort(canonical.begin(), canonical.end(), embeddingLess);
    canonical.erase(std::unique(canonical.begin(), canonical.end(), embeddingEqual), canonical.end());
    return canonical;
}

std::size_t GenericMatcher::embeddingMultiplicity(const PatternIR& pattern,
                                                  const GenericGraphState& state) const {
    return enumerate(pattern, state).size();
}

} // namespace nfnext
