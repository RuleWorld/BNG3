#include "nfnext/generic_matcher.hpp"

#include "nfnext/validator.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <map>
#include <numeric>
#include <set>
#include <sstream>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace nfnext {
namespace {

const MoleculeTypeIR* findType(const ModelIR& model, TypeId id) {
    if (id < model.molecule_types.size() && model.molecule_types[id].id == id) {
        return &model.molecule_types[id];
    }
    for (const auto& type : model.molecule_types)
        if (type.id == id) return &type;
    return nullptr;
}

bool typeHasDuplicateSiteNames(const MoleculeTypeIR& type) {
    for (std::size_t i = 0; i < type.sites.size(); ++i) {
        for (std::size_t j = i + 1; j < type.sites.size(); ++j) {
            if (type.sites[i].name == type.sites[j].name) return true;
        }
    }
    return false;
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

void validatePatternOnly(const PatternIR& pattern, const ModelIR& model) {
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
    for (const auto& sc : pattern.species_compartments) {
        requireNode(sc.first, "species-compartment");
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

void validatePattern(const PatternIR& pattern, const ModelIR& model) {
    validateModel(model);
    validatePatternOnly(pattern, model);
}

std::optional<CompartmentId> complexSpeciesCompartment(const GenericGraphState& state,
                                                       const ModelIR& model,
                                                       ParticleId root,
                                                       std::vector<ParticleId>& scratch) {
    state.complexMembers(root, scratch);
    if (scratch.empty()) return std::nullopt;
    const CompartmentId firstComp = state.compartment(scratch.front());
    bool allSame = true;
    for (std::size_t i = 1; i < scratch.size(); ++i) {
        if (state.compartment(scratch[i]) != firstComp) {
            allSame = false;
            break;
        }
    }
    if (allSame) return firstComp;

    std::optional<CompartmentId> surface;
    for (const auto p : scratch) {
        const CompartmentId cid = state.compartment(p);
        if (cid >= model.compartments.size()) return std::nullopt;
        if (model.compartments[cid].dimensions == 2) {
            if (surface.has_value() && *surface != cid) return std::nullopt;
            surface = cid;
        }
    }
    if (!surface.has_value()) return std::nullopt;
    const auto& sRec = model.compartments[*surface];
    for (const auto p : scratch) {
        const CompartmentId cid = state.compartment(p);
        if (cid == *surface) continue;
        if (sRec.parent.has_value() && *sRec.parent == cid) continue;
        if (cid < model.compartments.size() &&
            model.compartments[cid].parent.has_value() &&
            *model.compartments[cid].parent == *surface) continue;
        return std::nullopt;
    }
    return surface;
}

bool siteConstraintMatches(const PatternIR::SiteConstraint& constraint,
                           ParticleId particle,
                           std::uint16_t concrete_site,
                           const GenericGraphState& state) {
    switch (constraint.kind) {
        case PatternIR::SiteConstraintKind::State:
            return state.siteState(particle, concrete_site) == constraint.state;
        case PatternIR::SiteConstraintKind::StateSet:
            return contains(constraint.states, state.siteState(particle, concrete_site));
        case PatternIR::SiteConstraintKind::Free:
            return !state.bound(particle, concrete_site);
        case PatternIR::SiteConstraintKind::Bound:
            return state.bound(particle, concrete_site);
    }
    return false;
}

bool nodeMatchesDirect(const PatternIR::Node& node, ParticleId particle,
                       const GenericGraphState& state) {
    if (state.type(particle) != node.molecule_type) return false;
    if (node.compartment.has_value() && state.compartment(particle) != *node.compartment)
        return false;
    for (const auto& constraint : node.constraints) {
        if (!siteConstraintMatches(constraint, particle,
                                   static_cast<std::uint16_t>(constraint.site), state)) {
            return false;
        }
    }
    return true;
}

std::vector<std::uint16_t> mentionedSitesForNode(const PatternIR& pattern, std::size_t node_index) {
    std::vector<std::uint16_t> sites;
    for (const auto& c : pattern.nodes[node_index].constraints) {
        sites.push_back(static_cast<std::uint16_t>(c.site));
    }
    for (const auto& b : pattern.bonds) {
        if (b.first == node_index) sites.push_back(static_cast<std::uint16_t>(b.first_site));
        if (b.second == node_index) sites.push_back(static_cast<std::uint16_t>(b.second_site));
    }
    std::sort(sites.begin(), sites.end());
    sites.erase(std::unique(sites.begin(), sites.end()), sites.end());
    return sites;
}

template <class Callback>
void enumerateNodeSiteMaps(const PatternIR::Node& node,
                           const MoleculeTypeIR& type,
                           const std::vector<std::uint16_t>& mentioned_sites,
                           ParticleId particle,
                           const GenericGraphState& state,
                           std::optional<std::pair<std::uint16_t, std::uint16_t>> pinned_site,
                           Callback&& on_map) {
    if (state.type(particle) != node.molecule_type) return;
    if (node.compartment.has_value() && state.compartment(particle) != *node.compartment) return;

    const std::size_t total_sites = type.sites.size();
    std::vector<std::uint16_t> site_map(total_sites, 0);
    std::iota(site_map.begin(), site_map.end(), static_cast<std::uint16_t>(0));

    if (mentioned_sites.empty()) {
        on_map(site_map);
        return;
    }

    // Group constraints by pattern site for O(1) lookup during backtracking.
    std::vector<std::vector<std::size_t>> constraints_by_site(total_sites);
    for (std::size_t ci = 0; ci < node.constraints.size(); ++ci) {
        constraints_by_site[node.constraints[ci].site].push_back(ci);
    }

    auto concreteSatisfies = [&](std::uint16_t pat_site, std::uint16_t conc_site) -> bool {
        if (type.sites[conc_site].name != type.sites[pat_site].name) return false;
        for (const auto ci : constraints_by_site[pat_site]) {
            if (!siteConstraintMatches(node.constraints[ci], particle, conc_site, state))
                return false;
        }
        return true;
    };

    std::vector<std::uint8_t> used(total_sites, 0);
    if (pinned_site.has_value()) {
        if (pinned_site->first >= total_sites || pinned_site->second >= total_sites) return;
        if (!concreteSatisfies(pinned_site->first, pinned_site->second)) return;
        site_map[pinned_site->first] = pinned_site->second;
        used[pinned_site->second] = 1;
    }

    std::function<void(std::size_t)> assign = [&](std::size_t idx) {
        if (idx == mentioned_sites.size()) {
            on_map(site_map);
            return;
        }
        const std::uint16_t pat_site = mentioned_sites[idx];
        if (pinned_site.has_value() && pat_site == pinned_site->first) {
            assign(idx + 1);
            return;
        }
        for (std::uint16_t conc = 0; conc < static_cast<std::uint16_t>(total_sites); ++conc) {
            if (used[conc]) continue;
            if (!concreteSatisfies(pat_site, conc)) continue;
            site_map[pat_site] = conc;
            used[conc] = 1;
            assign(idx + 1);
            used[conc] = 0;
        }
    };
    assign(0);
}

bool exactBondMapped(const PatternIR::Bond& bond,
                     const std::vector<ParticleId>& assignment,
                     const std::vector<std::vector<std::uint16_t>>& site_maps,
                     bool use_site_maps,
                     const GenericGraphState& state) {
    const std::uint16_t s1 = use_site_maps && bond.first < site_maps.size() &&
                                     bond.first_site < site_maps[bond.first].size()
                                 ? site_maps[bond.first][bond.first_site]
                                 : static_cast<std::uint16_t>(bond.first_site);
    const std::uint16_t s2 = use_site_maps && bond.second < site_maps.size() &&
                                     bond.second_site < site_maps[bond.second].size()
                                 ? site_maps[bond.second][bond.second_site]
                                 : static_cast<std::uint16_t>(bond.second_site);
    const auto first = state.bond(assignment[bond.first], s1);
    const auto second = state.bond(assignment[bond.second], s2);
    return first.particle == assignment[bond.second] &&
           first.site == s2 &&
           second.particle == assignment[bond.first] &&
           second.site == s1;
}

bool partialTopologyMatchesForNode(const PatternIR& pattern,
                                   std::size_t current_node,
                                   const std::vector<bool>& assigned,
                                   const std::vector<ParticleId>& assignment,
                                   const std::vector<std::vector<std::uint16_t>>& site_maps,
                                   bool use_site_maps,
                                   const GenericGraphState& state,
                                   const ModelIR& model,
                                   std::vector<ParticleId>& scratch) {
    for (const auto& bond : pattern.bonds) {
        if (bond.first != current_node && bond.second != current_node) continue;
        if (!assigned[bond.first] || !assigned[bond.second]) continue;
        if (!exactBondMapped(bond, assignment, site_maps, use_site_maps, state)) return false;
    }
    for (const auto& constraint : pattern.molecularity) {
        if (constraint.left != current_node && constraint.right != current_node) continue;
        if (!assigned[constraint.left] || !assigned[constraint.right]) continue;
        const bool same = state.sameComplex(assignment[constraint.left], assignment[constraint.right]);
        if ((constraint.kind == MolecularityKind::SameComplex && !same) ||
            (constraint.kind == MolecularityKind::DifferentComplex && same)) return false;
    }
    for (const auto& pair : pattern.connected_to) {
        if (pair.first != current_node && pair.second != current_node) continue;
        if (!assigned[pair.first] || !assigned[pair.second]) continue;
        if (!state.sameComplex(assignment[pair.first], assignment[pair.second])) return false;
    }
    for (const auto& sc : pattern.species_compartments) {
        if (sc.first != current_node) continue;
        const auto comp = complexSpeciesCompartment(state, model, assignment[current_node], scratch);
        if (!comp.has_value() || *comp != sc.second) return false;
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
    if (a.typeSignature() != b.typeSignature())
        return a.typeSignature() < b.typeSignature();
    return a.siteMaps() < b.siteMaps();
}

bool embeddingEqual(const Embedding& a, const Embedding& b) { return a == b; }

std::vector<Embedding> canonicalizeForPattern(const PatternIR& pattern,
                                               const std::vector<Embedding>& embeddings) {
    if (pattern.interchangeable.empty()) return embeddings;
    std::vector<Embedding> canonical;
    canonical.reserve(embeddings.size());
    for (const auto& original : embeddings) {
        Embedding embedding = original;
        const bool hasMaps = embedding.hasSiteMaps();
        for (const auto& group : pattern.interchangeable) {
            struct Entry {
                ParticleId particle;
                TypeId type;
                std::vector<std::uint16_t> site_map;
            };
            std::vector<Entry> values;
            values.reserve(group.size());
            for (const auto node : group) {
                Entry e;
                e.particle = embedding.particle(node);
                e.type = embedding.typeSignature()[node];
                if (hasMaps && node < embedding.siteMaps().size()) {
                    e.site_map = embedding.siteMaps()[node];
                }
                values.push_back(std::move(e));
            }
            std::sort(values.begin(), values.end(), [](const Entry& left, const Entry& right) {
                if (!(left.particle == right.particle)) return idLess(left.particle, right.particle);
                return left.site_map < right.site_map;
            });
            for (std::size_t i = 0; i < group.size(); ++i) {
                embedding.setNode(group[i], values[i].particle, values[i].type);
                if (hasMaps) embedding.setSiteMap(group[i], std::move(values[i].site_map));
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
    if (a.molecule_type != b.molecule_type || a.compartment != b.compartment ||
        a.constraints.size() != b.constraints.size()) return false;
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

// Fast pruned backtracking automorphism count (exact equivalent of enumerating all
// permutations satisfying equivalentUnder, but O(k) on chains/asymmetric graphs
// instead of O(k!)).
std::size_t prunedAutomorphismCount(const PatternIR& pattern) {
    const std::size_t n = pattern.nodes.size();
    if (n <= 1) return 1;

    struct IncidentBond {
        std::size_t neighbor;
        std::uint32_t my_site;
        std::uint32_t neighbor_site;
    };
    std::vector<std::vector<IncidentBond>> bond_adj(n);
    std::vector<std::size_t> same_deg(n, 0), diff_deg(n, 0), alias_deg(n, 0), conn_deg(n, 0);
    for (const auto& b : pattern.bonds) {
        bond_adj[b.first].push_back({b.second, b.first_site, b.second_site});
        if (b.first != b.second) {
            bond_adj[b.second].push_back({b.first, b.second_site, b.first_site});
        }
    }
    for (const auto& c : pattern.molecularity) {
        if (c.kind == MolecularityKind::SameComplex) {
            ++same_deg[c.left]; ++same_deg[c.right];
        } else {
            ++diff_deg[c.left]; ++diff_deg[c.right];
        }
    }
    for (const auto& p : pattern.aliases) { ++alias_deg[p.first]; ++alias_deg[p.second]; }
    for (const auto& p : pattern.connected_to) { ++conn_deg[p.first]; ++conn_deg[p.second]; }

    // Precompute candidate targets per node using invariants.
    std::vector<std::vector<std::size_t>> candidates(n);
    for (std::size_t u = 0; u < n; ++u) {
        std::vector<std::pair<std::uint32_t, std::uint32_t>> u_sig;
        for (const auto& ib : bond_adj[u]) u_sig.emplace_back(ib.my_site, ib.neighbor_site);
        std::sort(u_sig.begin(), u_sig.end());
        for (std::size_t v = 0; v < n; ++v) {
            if (!nodeEquivalent(pattern.nodes[u], pattern.nodes[v])) continue;
            if (bond_adj[u].size() != bond_adj[v].size()) continue;
            if (same_deg[u] != same_deg[v] || diff_deg[u] != diff_deg[v] ||
                alias_deg[u] != alias_deg[v] || conn_deg[u] != conn_deg[v]) continue;
            std::vector<std::pair<std::uint32_t, std::uint32_t>> v_sig;
            for (const auto& ib : bond_adj[v]) v_sig.emplace_back(ib.my_site, ib.neighbor_site);
            std::sort(v_sig.begin(), v_sig.end());
            if (u_sig != v_sig) continue;
            candidates[u].push_back(v);
        }
    }

    // Order nodes by BFS along bonds, starting each component from the node with
    // fewest candidates (e.g. endpoints of a chain have 2 candidates!).
    struct ParentLink {
        bool has{false};
        std::size_t parent{0};
        std::uint32_t parent_site{0};
        std::uint32_t my_site{0};
    };
    std::vector<std::size_t> order;
    order.reserve(n);
    std::vector<ParentLink> parent_link(n);
    std::vector<bool> in_order(n, false);
    while (order.size() < n) {
        std::size_t best = n;
        for (std::size_t u = 0; u < n; ++u) {
            if (in_order[u]) continue;
            if (best == n || candidates[u].size() < candidates[best].size()) best = u;
        }
        std::vector<std::size_t> queue{best};
        in_order[best] = true;
        for (std::size_t head = 0; head < queue.size(); ++head) {
            const std::size_t cur = queue[head];
            order.push_back(cur);
            for (const auto& ib : bond_adj[cur]) {
                if (in_order[ib.neighbor]) continue;
                in_order[ib.neighbor] = true;
                parent_link[ib.neighbor] = {true, cur, ib.my_site, ib.neighbor_site};
                queue.push_back(ib.neighbor);
            }
        }
    }

    const auto base_bonds = bondKeys(pattern);
    const auto base_aliases = pairKeys(pattern.aliases);
    const auto base_conn = pairKeys(pattern.connected_to);
    const auto base_mol = molecularityKeys(pattern);

    // Quick lookup sets for incremental edge checks.
    std::set<BondKey> bond_set(base_bonds.begin(), base_bonds.end());
    std::set<PairKey> alias_set(base_aliases.begin(), base_aliases.end());
    std::set<PairKey> conn_set(base_conn.begin(), base_conn.end());
    std::set<std::tuple<unsigned, std::size_t, std::size_t>> mol_set(base_mol.begin(), base_mol.end());

    std::vector<std::size_t> perm(n, n);
    std::vector<bool> assigned(n, false);
    std::vector<bool> used(n, false);
    std::size_t count = 0;

    auto partialConsistent = [&](std::size_t u, std::size_t pu) -> bool {
        for (const auto& ib : bond_adj[u]) {
            if (!assigned[ib.neighbor]) continue;
            const std::size_t pv = perm[ib.neighbor];
            if (!bond_set.count(normalizeBond(pu, ib.my_site, pv, ib.neighbor_site))) return false;
        }
        for (const auto& p : pattern.aliases) {
            if (p.first != u && p.second != u) continue;
            const std::size_t other = (p.first == u) ? p.second : p.first;
            if (!assigned[other]) continue;
            auto a = pu, b = perm[other];
            if (b < a) std::swap(a, b);
            if (!alias_set.count({a, b})) return false;
        }
        for (const auto& p : pattern.connected_to) {
            if (p.first != u && p.second != u) continue;
            const std::size_t other = (p.first == u) ? p.second : p.first;
            if (!assigned[other]) continue;
            auto a = pu, b = perm[other];
            if (b < a) std::swap(a, b);
            if (!conn_set.count({a, b})) return false;
        }
        for (const auto& c : pattern.molecularity) {
            if (c.left != u && c.right != u) continue;
            const std::size_t other = (c.left == u) ? c.right : c.left;
            if (!assigned[other]) continue;
            auto a = pu, b = perm[other];
            if (b < a) std::swap(a, b);
            if (!mol_set.count({static_cast<unsigned>(c.kind), a, b})) return false;
        }
        return true;
    };

    std::function<void(std::size_t)> dfs = [&](std::size_t depth) {
        if (depth == n) {
            if (bondKeys(pattern, &perm) == base_bonds &&
                pairKeys(pattern.aliases, &perm) == base_aliases &&
                pairKeys(pattern.connected_to, &perm) == base_conn &&
                molecularityKeys(pattern, &perm) == base_mol) {
                ++count;
            }
            return;
        }
        const std::size_t u = order[depth];
        if (parent_link[u].has) {
            const std::size_t p_parent = perm[parent_link[u].parent];
            for (const auto& ib : bond_adj[p_parent]) {
                if (ib.my_site != parent_link[u].parent_site ||
                    ib.neighbor_site != parent_link[u].my_site) continue;
                const std::size_t pu = ib.neighbor;
                if (used[pu]) continue;
                if (std::find(candidates[u].begin(), candidates[u].end(), pu) == candidates[u].end())
                    continue;
                perm[u] = pu;
                assigned[u] = true;
                used[pu] = true;
                if (partialConsistent(u, pu)) dfs(depth + 1);
                assigned[u] = false;
                used[pu] = false;
            }
            return;
        }
        for (const std::size_t pu : candidates[u]) {
            if (used[pu]) continue;
            perm[u] = pu;
            assigned[u] = true;
            used[pu] = true;
            if (partialConsistent(u, pu)) dfs(depth + 1);
            assigned[u] = false;
            used[pu] = false;
        }
    };
    dfs(0);
    return count;
}

std::size_t bruteForcePermutationCount(const PatternIR& pattern) {
    if (pattern.nodes.size() > 6) return prunedAutomorphismCount(pattern);
    std::vector<std::size_t> permutation(pattern.nodes.size());
    std::iota(permutation.begin(), permutation.end(), 0);
    std::size_t count = 0;
    do {
        if (equivalentUnder(pattern, permutation)) ++count;
    } while (std::next_permutation(permutation.begin(), permutation.end()));
    return count;
}

// Compute the full (node_perm, site_perm) automorphism count of a pattern,
// treating SameComplex as transitive connected-component equivalence and allowing
// same-name sites on each molecule to permute.
std::size_t fullPatternAutomorphismCount(const PatternIR& pattern, const ModelIR& model) {
    const std::size_t n = pattern.nodes.size();
    if (n == 0) return 1;

    // Build SameComplex equivalence component ID per node (including bonds and SameComplex).
    std::vector<std::size_t> comp(n);
    std::iota(comp.begin(), comp.end(), 0);
    std::function<std::size_t(std::size_t)> findRep = [&](std::size_t x) -> std::size_t {
        while (comp[x] != x) { comp[x] = comp[comp[x]]; x = comp[x]; }
        return x;
    };
    auto unite = [&](std::size_t a, std::size_t b) {
        a = findRep(a); b = findRep(b);
        if (a != b) comp[b] = a;
    };
    for (const auto& b : pattern.bonds) unite(b.first, b.second);
    for (const auto& c : pattern.molecularity) {
        if (c.kind == MolecularityKind::SameComplex) unite(c.left, c.right);
    }
    for (std::size_t i = 0; i < n; ++i) comp[i] = findRep(i);

    std::vector<std::vector<std::uint16_t>> mentioned(n);
    for (std::size_t u = 0; u < n; ++u) mentioned[u] = mentionedSitesForNode(pattern, u);

    // Precompute canonical per-site constraint signature for each node/site.
    using ConstraintSig = std::vector<std::tuple<int, std::int32_t, std::vector<std::int32_t>>>;
    std::vector<std::map<std::uint16_t, ConstraintSig>> node_site_sigs(n);
    for (std::size_t u = 0; u < n; ++u) {
        for (const auto& c : pattern.nodes[u].constraints) {
            node_site_sigs[u][static_cast<std::uint16_t>(c.site)].emplace_back(
                static_cast<int>(c.kind), c.state, c.states);
        }
        for (auto& [_, sig] : node_site_sigs[u]) std::sort(sig.begin(), sig.end());
    }

    // Build undirected bond lookup set.
    struct UndirBond {
        std::size_t a; std::uint16_t sa;
        std::size_t b; std::uint16_t sb;
        bool operator<(const UndirBond& o) const noexcept {
            return std::tie(a, sa, b, sb) < std::tie(o.a, o.sa, o.b, o.sb);
        }
        bool operator==(const UndirBond& o) const noexcept {
            return a == o.a && sa == o.sa && b == o.b && sb == o.sb;
        }
    };
    auto makeUndirBond = [](std::size_t a, std::uint16_t sa, std::size_t b, std::uint16_t sb) {
        if (std::tie(b, sb) < std::tie(a, sa)) return UndirBond{b, sb, a, sa};
        return UndirBond{a, sa, b, sb};
    };
    std::vector<UndirBond> base_bonds;
    std::vector<std::vector<std::size_t>> bond_neighbors(n);
    for (const auto& b : pattern.bonds) {
        base_bonds.push_back(makeUndirBond(b.first, static_cast<std::uint16_t>(b.first_site),
                                           b.second, static_cast<std::uint16_t>(b.second_site)));
        bond_neighbors[b.first].push_back(b.second);
        if (b.first != b.second) bond_neighbors[b.second].push_back(b.first);
    }
    std::sort(base_bonds.begin(), base_bonds.end());
    std::set<UndirBond> bond_set(base_bonds.begin(), base_bonds.end());

    // Species-compartment per node.
    std::vector<std::optional<CompartmentId>> node_species_comp(n);
    for (const auto& sc : pattern.species_compartments) {
        const auto c = comp[sc.first];
        for (std::size_t u = 0; u < n; ++u) {
            if (comp[u] == c) node_species_comp[u] = sc.second;
        }
    }

    // Order nodes by BFS along bonds.
    std::vector<std::size_t> order;
    std::vector<std::optional<std::size_t>> parent_node(n);
    std::vector<bool> in_order(n, false);
    while (order.size() < n) {
        std::size_t start = 0;
        while (in_order[start]) ++start;
        std::vector<std::size_t> q{start};
        in_order[start] = true;
        for (std::size_t h = 0; h < q.size(); ++h) {
            const std::size_t cur = q[h];
            order.push_back(cur);
            for (const std::size_t nb : bond_neighbors[cur]) {
                if (!in_order[nb]) {
                    in_order[nb] = true;
                    parent_node[nb] = cur;
                    q.push_back(nb);
                }
            }
        }
    }

    std::vector<std::size_t> perm(n, n);
    std::vector<std::vector<std::uint16_t>> site_maps(n);
    std::vector<bool> assigned(n, false);
    std::vector<bool> used(n, false);
    std::size_t total = 0;

    auto enumerateValidSiteMaps = [&](std::size_t u, std::size_t pu, auto&& cb) {
        const auto* type = findType(model, pattern.nodes[u].molecule_type);
        if (!type) return;
        const auto& uSites = mentioned[u];
        const auto& puSites = mentioned[pu];
        if (uSites.size() != puSites.size()) return;
        std::vector<std::uint16_t> smap(type->sites.size(), 0);
        std::iota(smap.begin(), smap.end(), static_cast<std::uint16_t>(0));
        if (uSites.empty()) {
            cb(smap);
            return;
        }
        std::vector<std::uint8_t> usedTarget(puSites.size(), 0);
        std::function<void(std::size_t)> assignSite = [&](std::size_t idx) {
            if (idx == uSites.size()) {
                cb(smap);
                return;
            }
            const std::uint16_t us = uSites[idx];
            const auto& uSig = node_site_sigs[u][us];
            for (std::size_t j = 0; j < puSites.size(); ++j) {
                if (usedTarget[j]) continue;
                const std::uint16_t ps = puSites[j];
                if (type->sites[us].name != type->sites[ps].name) continue;
                if (uSig != node_site_sigs[pu][ps]) continue;
                smap[us] = ps;
                usedTarget[j] = 1;
                assignSite(idx + 1);
                usedTarget[j] = 0;
            }
        };
        assignSite(0);
    };

    auto checkBondsWithAssigned = [&](std::size_t u) -> bool {
        const std::size_t pu = perm[u];
        for (const auto& b : pattern.bonds) {
            if (b.first != u && b.second != u) continue;
            if (!assigned[b.first] || !assigned[b.second]) continue;
            const std::size_t a = perm[b.first];
            const std::uint16_t sa = site_maps[b.first][b.first_site];
            const std::size_t c = perm[b.second];
            const std::uint16_t sc = site_maps[b.second][b.second_site];
            if (!bond_set.count(makeUndirBond(a, sa, c, sc))) return false;
        }
        for (std::size_t prev = 0; prev < n; ++prev) {
            if (!assigned[prev] || prev == u) continue;
            if ((comp[u] == comp[prev]) != (comp[pu] == comp[perm[prev]])) return false;
        }
        return true;
    };

    std::function<void(std::size_t)> dfs = [&](std::size_t depth) {
        if (depth == n) {
            ++total;
            return;
        }
        const std::size_t u = order[depth];
        auto tryTarget = [&](std::size_t pu) {
            if (used[pu]) return;
            if (pattern.nodes[u].molecule_type != pattern.nodes[pu].molecule_type) return;
            if (pattern.nodes[u].compartment != pattern.nodes[pu].compartment) return;
            if (node_species_comp[u] != node_species_comp[pu]) return;
            if (bond_neighbors[u].size() != bond_neighbors[pu].size()) return;
            if (mentioned[u].size() != mentioned[pu].size()) return;
            perm[u] = pu;
            assigned[u] = true;
            used[pu] = true;
            enumerateValidSiteMaps(u, pu, [&](const std::vector<std::uint16_t>& smap) {
                site_maps[u] = smap;
                if (checkBondsWithAssigned(u)) dfs(depth + 1);
            });
            assigned[u] = false;
            used[pu] = false;
        };

        if (parent_node[u].has_value()) {
            const std::size_t p_parent = perm[*parent_node[u]];
            std::unordered_set<std::size_t> tried;
            for (const std::size_t nb : bond_neighbors[p_parent]) {
                if (tried.insert(nb).second) tryTarget(nb);
            }
        } else {
            for (std::size_t pu = 0; pu < n; ++pu) tryTarget(pu);
        }
    };

    dfs(0);
    return total == 0 ? 1 : total;
}

std::vector<Embedding> enumerateCore(const PatternIR& pattern,
                                     const ModelIR& model,
                                     const GenericGraphState& state,
                                     const std::vector<ParticleId>* allowed_particles,
                                     bool stop_on_first) {
    validatePatternOnly(pattern, model);
    const std::size_t n = pattern.nodes.size();
    std::vector<Embedding> matches;
    if (n == 0) {
        matches.emplace_back();
        return matches;
    }

    // Check if any node's molecule type has duplicate site names.
    bool use_site_maps = false;
    std::vector<const MoleculeTypeIR*> node_types(n, nullptr);
    std::vector<bool> node_dup_sites(n, false);
    std::vector<std::vector<std::uint16_t>> mentioned(n);
    for (std::size_t u = 0; u < n; ++u) {
        node_types[u] = findType(model, pattern.nodes[u].molecule_type);
        if (node_types[u] && typeHasDuplicateSiteNames(*node_types[u])) {
            node_dup_sites[u] = true;
            use_site_maps = true;
            mentioned[u] = mentionedSitesForNode(pattern, u);
        }
    }

    // Build optional per-type filtered allowed particle lists.
    std::unordered_map<TypeId, std::vector<ParticleId>> allowed_by_type;
    std::unordered_set<std::uint64_t> allowed_set;
    auto particleKey = [](ParticleId p) -> std::uint64_t {
        return (static_cast<std::uint64_t>(p.index) << 32) | p.generation;
    };
    if (allowed_particles != nullptr) {
        for (const auto p : *allowed_particles) {
            if (!state.alive(p)) continue;
            allowed_by_type[state.type(p)].push_back(p);
            allowed_set.insert(particleKey(p));
        }
    }

    // Build bond and same-complex adjacency for spanning-tree traversal order.
    struct BondEdge {
        std::size_t neighbor;
        std::uint16_t my_site;
        std::uint16_t neighbor_site;
    };
    std::vector<std::vector<BondEdge>> bond_adj(n);
    std::vector<std::vector<std::size_t>> complex_adj(n);
    for (const auto& b : pattern.bonds) {
        if (b.first != b.second) {
            bond_adj[b.first].push_back({b.second, static_cast<std::uint16_t>(b.first_site),
                                         static_cast<std::uint16_t>(b.second_site)});
            bond_adj[b.second].push_back({b.first, static_cast<std::uint16_t>(b.second_site),
                                          static_cast<std::uint16_t>(b.first_site)});
        }
    }
    for (const auto& c : pattern.molecularity) {
        if (c.kind == MolecularityKind::SameComplex && c.left != c.right) {
            complex_adj[c.left].push_back(c.right);
            complex_adj[c.right].push_back(c.left);
        }
    }
    for (const auto& p : pattern.connected_to) {
        if (p.first != p.second) {
            complex_adj[p.first].push_back(p.second);
            complex_adj[p.second].push_back(p.first);
        }
    }

    auto candidatePoolSize = [&](std::size_t u) -> std::size_t {
        const TypeId t = pattern.nodes[u].molecule_type;
        if (allowed_particles != nullptr) {
            const auto it = allowed_by_type.find(t);
            return it == allowed_by_type.end() ? 0 : it->second.size();
        }
        return state.liveSlotsOfType(t).size();
    };

    // Quick empty check: if any required type has 0 live particles, return empty immediately.
    for (std::size_t u = 0; u < n; ++u) {
        if (candidatePoolSize(u) == 0) return matches;
    }

    struct TraversalStep {
        std::size_t node{0};
        bool via_bond{false};
        std::size_t parent{0};
        std::uint16_t parent_site{0};
        std::uint16_t my_site{0};
        bool via_complex{false};
        std::size_t complex_anchor{0};
    };
    std::vector<TraversalStep> plan;
    plan.reserve(n);
    std::vector<bool> in_plan(n, false);

    while (plan.size() < n) {
        // Pick unplaced node with smallest candidate pool (tie-break by most constraints/bonds).
        std::size_t best = n;
        std::size_t best_size = std::numeric_limits<std::size_t>::max();
        for (std::size_t u = 0; u < n; ++u) {
            if (in_plan[u]) continue;
            const auto sz = candidatePoolSize(u);
            if (best == n || sz < best_size ||
                (sz == best_size && pattern.nodes[u].constraints.size() > pattern.nodes[best].constraints.size())) {
                best = u;
                best_size = sz;
            }
        }
        std::vector<std::size_t> queue{best};
        in_plan[best] = true;
        plan.push_back(TraversalStep{best});
        for (std::size_t head = 0; head < queue.size(); ++head) {
            const std::size_t cur = queue[head];
            for (const auto& edge : bond_adj[cur]) {
                if (in_plan[edge.neighbor]) continue;
                in_plan[edge.neighbor] = true;
                TraversalStep step;
                step.node = edge.neighbor;
                step.via_bond = true;
                step.parent = cur;
                step.parent_site = edge.my_site;
                step.my_site = edge.neighbor_site;
                plan.push_back(step);
                queue.push_back(edge.neighbor);
            }
            for (const auto nb : complex_adj[cur]) {
                if (in_plan[nb]) continue;
                in_plan[nb] = true;
                TraversalStep step;
                step.node = nb;
                step.via_complex = true;
                step.complex_anchor = cur;
                plan.push_back(step);
                queue.push_back(nb);
            }
        }
    }

    std::vector<ParticleId> assignment(n);
    std::vector<TypeId> types(n, 0);
    std::vector<bool> assigned(n, false);
    std::vector<std::vector<std::uint16_t>> site_maps(use_site_maps ? n : 0);
    if (use_site_maps) {
        for (std::size_t u = 0; u < n; ++u) {
            if (node_types[u]) {
                site_maps[u].resize(node_types[u]->sites.size());
                std::iota(site_maps[u].begin(), site_maps[u].end(), static_cast<std::uint16_t>(0));
            }
        }
    }
    std::vector<ParticleId> scratch;
    bool found_any = false;

    auto particleAvailableForNode = [&](std::size_t node, ParticleId particle) -> bool {
        if (!state.alive(particle)) return false;
        if (allowed_particles != nullptr && !allowed_set.count(particleKey(particle))) return false;
        for (std::size_t prev = 0; prev < n; ++prev) {
            if (assigned[prev] && assignment[prev] == particle && !aliases(pattern, prev, node)) {
                return false;
            }
        }
        return true;
    };

    std::function<void(std::size_t)> visit = [&](std::size_t depth) {
        if (stop_on_first && found_any) return;
        if (depth == n) {
            if (use_site_maps) {
                matches.emplace_back(assignment, types, site_maps);
            } else {
                matches.emplace_back(assignment, types);
            }
            found_any = true;
            return;
        }

        const auto& step = plan[depth];
        const std::size_t node = step.node;

        auto tryParticle = [&](ParticleId particle,
                               std::optional<std::pair<std::uint16_t, std::uint16_t>> pinned_site) {
            if (stop_on_first && found_any) return;
            if (!particleAvailableForNode(node, particle)) return;

            if (!node_dup_sites[node]) {
                if (!nodeMatchesDirect(pattern.nodes[node], particle, state)) return;
                if (pinned_site.has_value() && pinned_site->first != pinned_site->second) return;
                assignment[node] = particle;
                types[node] = state.type(particle);
                assigned[node] = true;
                if (partialTopologyMatchesForNode(pattern, node, assigned, assignment,
                                                  site_maps, use_site_maps, state, model, scratch)) {
                    visit(depth + 1);
                }
                assigned[node] = false;
                return;
            }

            enumerateNodeSiteMaps(
                pattern.nodes[node], *node_types[node], mentioned[node],
                particle, state, pinned_site,
                [&](const std::vector<std::uint16_t>& smap) {
                    if (stop_on_first && found_any) return;
                    assignment[node] = particle;
                    types[node] = state.type(particle);
                    site_maps[node] = smap;
                    assigned[node] = true;
                    if (partialTopologyMatchesForNode(pattern, node, assigned, assignment,
                                                      site_maps, use_site_maps, state, model, scratch)) {
                        visit(depth + 1);
                    }
                    assigned[node] = false;
                });
        };

        if (step.via_bond) {
            const std::uint16_t p_conc_site =
                use_site_maps ? site_maps[step.parent][step.parent_site] : step.parent_site;
            const auto bond_info = state.bond(assignment[step.parent], p_conc_site);
            if (!bond_info.particle.valid()) return;
            tryParticle(bond_info.particle,
                        std::make_pair(step.my_site, bond_info.site));
            return;
        }

        if (step.via_complex) {
            std::vector<ParticleId> members;
            state.complexMembers(assignment[step.complex_anchor], members);
            for (const auto particle : members) {
                if (state.type(particle) != pattern.nodes[node].molecule_type) continue;
                tryParticle(particle, std::nullopt);
                if (stop_on_first && found_any) return;
            }
            return;
        }

        const TypeId target_type = pattern.nodes[node].molecule_type;
        if (allowed_particles != nullptr) {
            const auto it = allowed_by_type.find(target_type);
            if (it == allowed_by_type.end()) return;
            for (const auto particle : it->second) {
                tryParticle(particle, std::nullopt);
                if (stop_on_first && found_any) return;
            }
        } else {
            const auto& slots = state.liveSlotsOfType(target_type);
            for (const auto slot : slots) {
                tryParticle(state.particleAtSlot(slot), std::nullopt);
                if (stop_on_first && found_any) return;
            }
        }
    };

    visit(0);
    if (stop_on_first) return matches;
    return canonicalizeForPattern(pattern, matches);
}

} // namespace

std::size_t MatchPlan::automorphismCount() const { return prunedAutomorphismCount(pattern_); }

MatchPlan compileMatchPlan(const PatternIR& pattern, const ModelIR& model) {
    validatePattern(pattern, model);
    return MatchPlan(pattern, model);
}

std::size_t bruteForceAutomorphismCount(const PatternIR& pattern, const ModelIR& model) {
    validatePattern(pattern, model);
    return bruteForcePermutationCount(pattern);
}

std::size_t GenericMatcher::fullAutomorphismCount(const PatternIR& pattern) const {
    validatePatternOnly(pattern, *model_);
    return fullPatternAutomorphismCount(pattern, *model_);
}

std::optional<IndependentMatchCount> GenericMatcher::countIndependent(
    const PatternIR& pattern, const GenericGraphState& state) const {
    if (!pattern.bonds.empty() || !pattern.aliases.empty() ||
        !pattern.connected_to.empty() || !pattern.species_compartments.empty() ||
        pattern.nodes.empty()) {
        return std::nullopt;
    }
    for (const auto& constraint : pattern.molecularity) {
        if (constraint.kind != MolecularityKind::DifferentComplex) return std::nullopt;
    }

    const std::size_t n = pattern.nodes.size();
    const bool has_interchangeable = !pattern.interchangeable.empty();
    if (has_interchangeable) {
        if (n != 2 || pattern.interchangeable.size() != 1 ||
            pattern.interchangeable[0].size() != 2) {
            return std::nullopt;
        }
        const auto a = pattern.interchangeable[0][0];
        const auto b = pattern.interchangeable[0][1];
        if (!((a == 0 && b == 1) || (a == 1 && b == 0))) return std::nullopt;
    }

    auto collectNodeCandidates = [&](std::size_t nodeIdx,
                                     std::vector<ParticleId>& out_particles,
                                     std::vector<std::vector<std::uint16_t>>& out_maps) -> bool {
        const auto& node = pattern.nodes[nodeIdx];
        const auto* type = findType(*model_, node.molecule_type);
        if (!type) return false;
        const bool dupSites = typeHasDuplicateSiteNames(*type);
        const auto& slots = state.liveSlotsOfType(node.molecule_type);
        if (!dupSites) {
            out_particles.reserve(slots.size());
            for (const auto slot : slots) {
                const auto p = state.particleAtSlot(slot);
                if (nodeMatchesDirect(node, p, state)) out_particles.push_back(p);
            }
            return true;
        }
        const auto mentioned = mentionedSitesForNode(pattern, nodeIdx);
        for (const auto slot : slots) {
            const auto p = state.particleAtSlot(slot);
            enumerateNodeSiteMaps(
                node, *type, mentioned, p, state, std::nullopt,
                [&](const std::vector<std::uint16_t>& smap) {
                    out_particles.push_back(p);
                    out_maps.push_back(smap);
                });
        }
        return true;
    };

    // 1-node independent pattern (handles duplicate sites too!).
    if (n == 1) {
        IndependentMatchCount result;
        result.candidates.resize(1);
        result.candidate_site_maps.resize(1);
        if (!collectNodeCandidates(0, result.candidates[0], result.candidate_site_maps[0]))
            return std::nullopt;
        result.count = result.candidates[0].size();
        return result;
    }

    // 2-node independent pattern: supports distinct types, same-type pairs,
    // interchangeable identical pairs, duplicate-site molecules, and
    // DifferentComplex molecularity in O(N) time without materializing O(N^2) pairs!
    if (n == 2) {
        IndependentMatchCount result;
        result.candidates.resize(2);
        result.candidate_site_maps.resize(2);
        result.interchangeable_pair = has_interchangeable;
        result.different_complex = !pattern.molecularity.empty();
        result.same_type_pair = (pattern.nodes[0].molecule_type == pattern.nodes[1].molecule_type);

        if (!collectNodeCandidates(0, result.candidates[0], result.candidate_site_maps[0]))
            return std::nullopt;
        if (result.candidates[0].empty()) {
            result.count = 0;
            return result;
        }
        if (has_interchangeable) {
            result.candidates[1] = result.candidates[0];
            result.candidate_site_maps[1] = result.candidate_site_maps[0];
        } else {
            if (!collectNodeCandidates(1, result.candidates[1], result.candidate_site_maps[1]))
                return std::nullopt;
            if (result.candidates[1].empty()) {
                result.count = 0;
                return result;
            }
        }

        // If the model has compartments, bail out to the general path whenever
        // candidates span more than one compartment so compartment adjacency and
        // per-match volume scaling are handled with full fidelity.
        if (!model_->compartments.empty()) {
            const CompartmentId refComp = state.compartment(result.candidates[0].front());
            for (const auto p : result.candidates[0]) {
                if (state.compartment(p) != refComp) return std::nullopt;
            }
            if (!has_interchangeable) {
                for (const auto p : result.candidates[1]) {
                    if (state.compartment(p) != refComp) return std::nullopt;
                }
            }
        }

        const std::size_t c0 = result.candidates[0].size();
        const std::size_t c1 = result.candidates[1].size();
        const double raw_prod = static_cast<double>(c0) * static_cast<double>(c1);
        if (!std::isfinite(raw_prod) ||
            raw_prod > static_cast<double>(std::numeric_limits<std::size_t>::max())) {
            return std::nullopt;
        }
        std::size_t invalid_pairs = 0;
        if (result.different_complex) {
            std::unordered_map<std::uint32_t, std::size_t> freq0;
            freq0.reserve(c0);
            for (const auto p : result.candidates[0]) ++freq0[state.complexId(p)];
            if (has_interchangeable) {
                for (const auto& [_, f] : freq0) invalid_pairs += f * f;
            } else {
                for (const auto p : result.candidates[1]) {
                    const auto it = freq0.find(state.complexId(p));
                    if (it != freq0.end()) invalid_pairs += it->second;
                }
            }
        } else if (result.same_type_pair) {
            std::unordered_map<std::uint32_t, std::size_t> freq0;
            freq0.reserve(c0);
            for (const auto p : result.candidates[0]) ++freq0[p.index];
            if (has_interchangeable) {
                for (const auto& [_, f] : freq0) invalid_pairs += f * f;
            } else {
                for (const auto p : result.candidates[1]) {
                    const auto it = freq0.find(p.index);
                    if (it != freq0.end()) invalid_pairs += it->second;
                }
            }
        }
        const std::size_t ordered = (c0 * c1 >= invalid_pairs) ? (c0 * c1 - invalid_pairs) : 0;
        result.count = has_interchangeable ? (ordered / 2) : ordered;
        return result;
    }

    // 3+ node independent patterns: require distinct molecule types and isolated
    // particles when DifferentComplex molecularity is present.
    std::set<TypeId> types;
    for (const auto& node : pattern.nodes)
        if (!types.insert(node.molecule_type).second) return std::nullopt;

    if (!model_->compartments.empty()) return std::nullopt;

    IndependentMatchCount result;
    result.candidates.resize(n);
    result.candidate_site_maps.resize(n);
    result.different_complex = !pattern.molecularity.empty();
    double product = 1.0;
    for (std::size_t i = 0; i < n; ++i) {
        if (!collectNodeCandidates(i, result.candidates[i], result.candidate_site_maps[i]))
            return std::nullopt;
        if (!pattern.molecularity.empty()) {
            for (const auto p : result.candidates[i]) {
                if (state.anySiteBound(p)) return std::nullopt;
            }
        }
        if (result.candidates[i].empty()) {
            result.count = 0;
            return result;
        }
        product *= static_cast<double>(result.candidates[i].size());
        if (!std::isfinite(product) ||
            product > static_cast<double>(std::numeric_limits<std::size_t>::max()))
            return std::nullopt;
    }
    result.count = static_cast<std::size_t>(product);
    return result;
}

std::vector<Embedding> GenericMatcher::enumerate(const PatternIR& pattern,
                                                 const GenericGraphState& state,
                                                 MatchMode mode) const {
    (void)mode;
    return enumerateCore(pattern, *model_, state, nullptr, false);
}

std::vector<Embedding> GenericMatcher::enumerateInParticles(
    const PatternIR& pattern,
    const GenericGraphState& state,
    const std::vector<ParticleId>& allowed_particles) const {
    return enumerateCore(pattern, *model_, state, &allowed_particles, false);
}

bool GenericMatcher::hasMatchInParticles(
    const PatternIR& pattern,
    const GenericGraphState& state,
    const std::vector<ParticleId>& allowed_particles) const {
    return !enumerateCore(pattern, *model_, state, &allowed_particles, true).empty();
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
