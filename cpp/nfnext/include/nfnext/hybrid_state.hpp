#pragma once

#include "nfnext/population.hpp"
#include "nfnext/types.hpp"

#include <cmath>
#include <cstdint>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace nfnext {

class HybridValidationError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class HybridTransformationError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct ReactantHandle {
    std::size_t index{0};
    bool is_population{false};
    TypeId type{0};
};

class HybridRule {
public:
    double rate{1.0};

    struct ParticleReactantSpec {
        TypeId type{0};
        std::map<std::string, bool> require_free;
        std::map<std::string, std::string> require_state;
        std::map<std::string, std::string> set_state;
    };

    struct BondAction {
        std::size_t first_reactant{0};
        std::string first_site;
        std::size_t second_reactant{0};
        std::string second_site;
    };

    bool population_has_predicate{false};
    std::vector<ParticleReactantSpec> particle_reactants;
    std::vector<std::pair<SpeciesId, std::uint32_t>> population_reactants;
    std::vector<BondAction> bonds;
    std::vector<std::pair<SpeciesId, std::uint64_t>> consumed_pop;
    std::vector<std::pair<SpeciesId, std::uint64_t>> produced_pop;

    ReactantHandle particleReactant(TypeId type) {
        ReactantHandle h{particle_reactants.size(), false, type};
        ParticleReactantSpec spec;
        spec.type = type;
        particle_reactants.push_back(std::move(spec));
        return h;
    }

    ReactantHandle populationReactant(SpeciesId sp, std::uint32_t count = 1) {
        ReactantHandle h{population_reactants.size(), true, sp};
        population_reactants.emplace_back(sp, count);
        return h;
    }

    void requireFree(const ReactantHandle& h, const std::string& site) {
        if (h.is_population) {
            population_has_predicate = true;
            return;
        }
        particle_reactants.at(h.index).require_free[site] = true;
    }

    void requireState(const ReactantHandle& h, const std::string& site, const std::string& val) {
        if (h.is_population) {
            population_has_predicate = true;
            return;
        }
        particle_reactants.at(h.index).require_state[site] = val;
    }

    void setState(const ReactantHandle& h, const std::string& site, const std::string& val) {
        if (h.is_population) {
            population_has_predicate = true;
            return;
        }
        particle_reactants.at(h.index).set_state[site] = val;
    }

    void addBond(const ReactantHandle& h1, const std::string& s1,
                 const ReactantHandle& h2, const std::string& s2) {
        if (h1.is_population || h2.is_population) {
            population_has_predicate = true;
            return;
        }
        bonds.push_back({h1.index, s1, h2.index, s2});
    }

    void consumePopulation(SpeciesId sp, std::uint64_t count) {
        consumed_pop.emplace_back(sp, count);
    }

    void producePopulation(SpeciesId sp, std::uint64_t count) {
        produced_pop.emplace_back(sp, count);
    }
};

class HybridSchema;
class HybridState;

class HybridEvent {
public:
    std::vector<ParticleId> matched_particles;
    std::vector<std::pair<SpeciesId, std::uint64_t>> consumed_pop;
    std::vector<std::pair<SpeciesId, std::uint64_t>> produced_pop;
    std::vector<std::pair<std::size_t, std::pair<std::string, std::string>>> state_mutations;
    std::vector<HybridRule::BondAction> bonds;

    void fire(HybridState& s);
};

class CompiledHybridRule {
public:
    HybridRule rule;
    const HybridSchema* schema{nullptr};

    double propensity(const HybridState& s) const;
    HybridEvent firstEvent(HybridState& s) const;
};

class HybridSchema {
public:
    struct TypeEntry {
        std::string name;
        TypeId id{0};
        bool is_particle{false};
        bool is_population{false};
        bool is_hybridizable{false};
        std::vector<std::pair<std::string, std::vector<std::string>>> sites;
    };

    TypeId particleType(const std::string& name,
                         std::vector<std::pair<std::string, std::vector<std::string>>> sites) {
        TypeId id = static_cast<TypeId>(types_.size());
        types_.push_back({name, id, true, false, false, std::move(sites)});
        name_to_type_[name] = id;
        return id;
    }

    SpeciesId populationType(const std::string& name) {
        TypeId id = static_cast<TypeId>(types_.size());
        types_.push_back({name, id, false, true, false, {}});
        name_to_type_[name] = id;
        return id;
    }

    TypeId hybridizableType(const std::string& name,
                            std::vector<std::pair<std::string, std::vector<std::string>>> sites = {}) {
        TypeId id = static_cast<TypeId>(types_.size());
        types_.push_back({name, id, true, true, true, std::move(sites)});
        name_to_type_[name] = id;
        return id;
    }

    const TypeEntry& type(TypeId id) const { return types_.at(id); }
    const std::vector<TypeEntry>& types() const noexcept { return types_; }

    void validate(const HybridRule& r) const {
        if (r.population_has_predicate) {
            throw HybridValidationError("hybrid compiler rejects population type in bond predicate");
        }
        for (const auto& [sp, count] : r.consumed_pop) {
            if (sp < types_.size()) {
                const auto& t = types_[sp];
                if (t.is_particle && !t.is_population && !t.is_hybridizable) {
                    throw HybridValidationError(
                        "hybrid compiler rejects particle stoichiometry encoded as population count");
                }
            }
        }
    }

    CompiledHybridRule compile(const HybridRule& r) const {
        validate(r);
        return CompiledHybridRule{r, this};
    }

private:
    std::vector<TypeEntry> types_;
    std::unordered_map<std::string, TypeId> name_to_type_;
};

class HybridState {
public:
    struct Particle {
        ParticleId id{0};
        TypeId type{0};
        bool alive{true};
        std::map<std::string, std::string> site_states;
        std::map<std::string, std::pair<ParticleId, std::string>> bonds;
    };

    struct Snapshot {
        std::vector<std::uint64_t> populations;
        std::map<ParticleId, Particle> particles;
        std::uint32_t next_particle_index{0};

        bool operator==(const Snapshot& other) const {
            if (populations != other.populations || next_particle_index != other.next_particle_index)
                return false;
            if (particles.size() != other.particles.size()) return false;
            for (const auto& [id, p] : particles) {
                auto it = other.particles.find(id);
                if (it == other.particles.end()) return false;
                if (p.type != it->second.type || p.alive != it->second.alive ||
                    p.site_states != it->second.site_states || p.bonds != it->second.bonds)
                    return false;
            }
            return true;
        }
    };

    explicit HybridState(const HybridSchema& schema) : schema_(&schema) {
        populations_.resize(schema.types().size(), 0);
    }

    ParticleId create(TypeId type) {
        ParticleId id{next_particle_index_++, 0};
        Particle p;
        p.id = id;
        p.type = type;
        p.alive = true;
        if (schema_ && type < schema_->types().size()) {
            for (const auto& site : schema_->type(type).sites) {
                p.site_states[site.first] = site.second.empty() ? "" : site.second.front();
            }
        }
        particles_[id] = std::move(p);
        return id;
    }

    void setPopulation(SpeciesId sp, std::uint64_t count) {
        if (sp >= populations_.size()) populations_.resize(sp + 1, 0);
        populations_[sp] = count;
    }

    std::uint64_t population(SpeciesId sp) const {
        if (sp >= populations_.size()) return 0;
        return populations_[sp];
    }

    std::string siteState(ParticleId p, const std::string& site) const {
        auto it = particles_.find(p);
        if (it == particles_.end() || !it->second.alive) return "";
        auto sit = it->second.site_states.find(site);
        return sit != it->second.site_states.end() ? sit->second : "";
    }

    void setSiteState(ParticleId p, const std::string& site, const std::string& val) {
        auto it = particles_.find(p);
        if (it != particles_.end() && it->second.alive) {
            it->second.site_states[site] = val;
        }
    }

    bool bound(ParticleId p, const std::string& site) const {
        auto it = particles_.find(p);
        if (it == particles_.end() || !it->second.alive) return false;
        return it->second.bonds.find(site) != it->second.bonds.end();
    }

    void bind(ParticleId p1, const std::string& s1, ParticleId p2, const std::string& s2) {
        if (bound(p1, s1) || bound(p2, s2)) {
            throw HybridTransformationError("binding already-bound site");
        }
        particles_[p1].bonds[s1] = {p2, s2};
        particles_[p2].bonds[s2] = {p1, s1};
    }

    Snapshot snapshot() const {
        return Snapshot{populations_, particles_, next_particle_index_};
    }

    void restore(const Snapshot& snap) {
        populations_ = snap.populations;
        particles_ = snap.particles;
        next_particle_index_ = snap.next_particle_index;
    }

    std::uint64_t totalCopies(TypeId type) const {
        return particleCount(type) + population(type);
    }

    void particleize(TypeId type, std::uint64_t count) {
        if (population(type) < count) throw PopulationError("population underflow in particleize");
        setPopulation(type, population(type) - count);
        for (std::uint64_t i = 0; i < count; ++i) {
            create(type);
        }
    }

    std::uint64_t particleCount(TypeId type) const {
        std::uint64_t count = 0;
        for (const auto& [id, p] : particles_) {
            if (p.alive && p.type == type) ++count;
        }
        return count;
    }

    std::uint64_t observableTotal(TypeId type) const {
        return totalCopies(type);
    }

    void departicleizeEligible(TypeId type) {
        std::vector<ParticleId> eligible;
        for (const auto& [id, p] : particles_) {
            if (!p.alive || p.type != type) continue;
            if (!p.bonds.empty()) continue;
            bool default_states = true;
            if (schema_ && type < schema_->types().size()) {
                for (const auto& site : schema_->type(type).sites) {
                    std::string def_val = site.second.empty() ? "" : site.second.front();
                    auto it = p.site_states.find(site.first);
                    if (it != p.site_states.end() && it->second != def_val) {
                        default_states = false;
                        break;
                    }
                }
            }
            if (default_states) eligible.push_back(id);
        }
        for (const auto id : eligible) {
            particles_[id].alive = false;
        }
        setPopulation(type, population(type) + eligible.size());
    }

    const std::map<ParticleId, Particle>& particles() const noexcept { return particles_; }
    const HybridSchema* schema() const noexcept { return schema_; }

private:
    const HybridSchema* schema_{nullptr};
    std::vector<std::uint64_t> populations_;
    std::map<ParticleId, Particle> particles_;
    std::uint32_t next_particle_index_{0};
};

inline void HybridEvent::fire(HybridState& s) {
    auto before = s.snapshot();
    try {
        // Check underflow
        for (const auto& [sp, count] : consumed_pop) {
            if (s.population(sp) < count) throw PopulationError("population underflow");
        }
        // Mutate particles
        for (const auto& [idx, mutation] : state_mutations) {
            s.setSiteState(matched_particles.at(idx), mutation.first, mutation.second);
        }
        for (const auto& bond : bonds) {
            s.bind(matched_particles.at(bond.first_reactant), bond.first_site,
                   matched_particles.at(bond.second_reactant), bond.second_site);
        }
        // Update population
        for (const auto& [sp, count] : consumed_pop) {
            s.setPopulation(sp, s.population(sp) - count);
        }
        for (const auto& [sp, count] : produced_pop) {
            s.setPopulation(sp, s.population(sp) + count);
        }
    } catch (...) {
        s.restore(before);
        throw;
    }
}

inline double CompiledHybridRule::propensity(const HybridState& s) const {
    double pop_factor = 1.0;
    for (const auto& [sp, count] : rule.consumed_pop) {
        std::uint64_t n = s.population(sp);
        if (n < count) return 0.0;
        double comb = 1.0;
        for (std::uint64_t i = 0; i < count; ++i) {
            comb *= static_cast<double>(n - i);
            comb /= static_cast<double>(i + 1);
        }
        pop_factor *= comb;
    }

    if (rule.particle_reactants.empty()) {
        return rule.rate * pop_factor;
    }

    // Enumerate particle matches
    std::vector<std::vector<ParticleId>> candidate_lists;
    for (const auto& r_spec : rule.particle_reactants) {
        std::vector<ParticleId> candidates;
        for (const auto& [id, p] : s.particles()) {
            if (!p.alive || p.type != r_spec.type) continue;
            bool ok = true;
            for (const auto& [site, req_free] : r_spec.require_free) {
                if (req_free && s.bound(id, site)) { ok = false; break; }
            }
            if (!ok) continue;
            for (const auto& [site, req_state] : r_spec.require_state) {
                if (s.siteState(id, site) != req_state) { ok = false; break; }
            }
            if (ok) candidates.push_back(id);
        }
        candidate_lists.push_back(std::move(candidates));
    }

    // Count valid distinct embeddings
    std::size_t match_count = 0;
    std::vector<ParticleId> current;
    std::set<ParticleId> used;

    auto backtrack = [&](auto& self, std::size_t depth) -> void {
        if (depth == candidate_lists.size()) {
            ++match_count;
            return;
        }
        for (const auto p : candidate_lists[depth]) {
            if (used.count(p)) continue;
            used.insert(p);
            current.push_back(p);
            self(self, depth + 1);
            current.pop_back();
            used.erase(p);
        }
    };
    backtrack(backtrack, 0);

    return static_cast<double>(match_count) * pop_factor * rule.rate;
}

inline HybridEvent CompiledHybridRule::firstEvent(HybridState& s) const {
    HybridEvent ev;
    ev.consumed_pop = rule.consumed_pop;
    ev.produced_pop = rule.produced_pop;
    ev.bonds = rule.bonds;

    for (std::size_t r_idx = 0; r_idx < rule.particle_reactants.size(); ++r_idx) {
        const auto& r_spec = rule.particle_reactants[r_idx];
        for (const auto& [site, val] : r_spec.set_state) {
            ev.state_mutations.push_back({r_idx, {site, val}});
        }
    }

    // Find first embedding
    std::vector<std::vector<ParticleId>> candidate_lists;
    for (const auto& r_spec : rule.particle_reactants) {
        std::vector<ParticleId> candidates;
        for (const auto& [id, p] : s.particles()) {
            if (!p.alive || p.type != r_spec.type) continue;
            bool ok = true;
            for (const auto& [site, req_free] : r_spec.require_free) {
                if (req_free && s.bound(id, site)) { ok = false; break; }
            }
            if (!ok) continue;
            for (const auto& [site, req_state] : r_spec.require_state) {
                if (s.siteState(id, site) != req_state) { ok = false; break; }
            }
            if (ok) candidates.push_back(id);
        }
        candidate_lists.push_back(std::move(candidates));
    }

    std::vector<ParticleId> current;
    std::set<ParticleId> used;
    bool found = false;

    auto backtrack = [&](auto& self, std::size_t depth) -> void {
        if (found) return;
        if (depth == candidate_lists.size()) {
            ev.matched_particles = current;
            found = true;
            return;
        }
        for (const auto p : candidate_lists[depth]) {
            if (used.count(p)) continue;
            used.insert(p);
            current.push_back(p);
            self(self, depth + 1);
            current.pop_back();
            used.erase(p);
            if (found) return;
        }
    };
    backtrack(backtrack, 0);

    return ev;
}

} // namespace nfnext
