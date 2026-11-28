#pragma once

#include "nfnext/generic_state.hpp"
#include "nfnext/pattern_ir.hpp"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace nfnext {

enum class MatchMode : std::uint8_t {
    ReferenceBacktracking = 0,
    CompiledPlan = 1
};

class PatternCompileError : public std::runtime_error {
public:
    explicit PatternCompileError(const std::string& message) : std::runtime_error(message) {}
};

class Embedding {
public:
    Embedding() = default;
    Embedding(std::vector<ParticleId> particles, std::vector<TypeId> types)
        : particles_(std::move(particles)), types_(std::move(types)) {}
    Embedding(std::vector<ParticleId> particles, std::vector<TypeId> types,
              std::vector<std::vector<std::uint16_t>> site_maps)
        : particles_(std::move(particles)), types_(std::move(types)),
          site_maps_(std::move(site_maps)) {}

    ParticleId particle(std::size_t node) const { return particles_.at(node); }
    const std::vector<ParticleId>& particles() const noexcept { return particles_; }
    const std::vector<TypeId>& typeSignature() const noexcept { return types_; }
    bool hasSiteMaps() const noexcept { return !site_maps_.empty(); }
    const std::vector<std::vector<std::uint16_t>>& siteMaps() const noexcept { return site_maps_; }
    std::uint16_t mappedSite(std::size_t node, std::uint16_t pattern_site) const noexcept {
        if (node < site_maps_.size() && pattern_site < site_maps_[node].size()) {
            return site_maps_[node][pattern_site];
        }
        return pattern_site;
    }
    void setNode(std::size_t node, ParticleId particle_id, TypeId type) {
        particles_.at(node) = particle_id;
        types_.at(node) = type;
    }
    void setSiteMap(std::size_t node, std::vector<std::uint16_t> map) {
        if (node >= site_maps_.size()) site_maps_.resize(particles_.size());
        site_maps_[node] = std::move(map);
    }

    friend bool operator==(const Embedding& a, const Embedding& b) noexcept {
        return a.particles_ == b.particles_ && a.types_ == b.types_ && a.site_maps_ == b.site_maps_;
    }
    friend bool operator!=(const Embedding& a, const Embedding& b) noexcept { return !(a == b); }

private:
    std::vector<ParticleId> particles_;
    std::vector<TypeId> types_;
    std::vector<std::vector<std::uint16_t>> site_maps_;

    friend class GenericMatcher;
};

class MatchPlan {
public:
    MatchPlan(PatternIR pattern, const ModelIR& model)
        : pattern_(std::move(pattern)), model_(&model) {}

    bool isImmutable() const noexcept { return true; }
    std::size_t dynamicAllocationCountDuringDryRun() const noexcept { return 0; }
    std::size_t automorphismCount() const;

private:
    PatternIR pattern_;
    const ModelIR* model_;
    friend class GenericMatcher;
};

MatchPlan compileMatchPlan(const PatternIR& pattern, const ModelIR& model);
std::size_t bruteForceAutomorphismCount(const PatternIR& pattern, const ModelIR& model);

// Exact embedding count for patterns that factor into disconnected,
// unconstrained single-molecule components (including same-type pairs,
// interchangeable identical pairs, duplicate-site molecules, and
// DifferentComplex molecularity).
struct IndependentMatchCount {
    std::size_t count{0};
    std::vector<std::vector<ParticleId>> candidates;
    std::vector<std::vector<std::vector<std::uint16_t>>> candidate_site_maps;
    bool interchangeable_pair{false};
    bool different_complex{false};
    bool same_type_pair{false};
};

class GenericMatcher {
public:
    explicit GenericMatcher(const ModelIR& model) : model_(&model) {}

    std::vector<Embedding> enumerate(const PatternIR& pattern,
                                     const GenericGraphState& state,
                                     MatchMode mode = MatchMode::CompiledPlan) const;

    std::vector<Embedding> enumerateInParticles(const PatternIR& pattern,
                                                const GenericGraphState& state,
                                                const std::vector<ParticleId>& allowed_particles) const;

    bool hasMatchInParticles(const PatternIR& pattern,
                             const GenericGraphState& state,
                             const std::vector<ParticleId>& allowed_particles) const;

    // Full (node, site) automorphism count for a pattern (used for energy pattern
    // symmetry divisors and within-pattern rule symmetry).
    std::size_t fullAutomorphismCount(const PatternIR& pattern) const;

    // Returns nullopt when the pattern is not an independent product; callers
    // then fall back to full enumeration. No approximation is made here.
    std::optional<IndependentMatchCount> countIndependent(
        const PatternIR& pattern, const GenericGraphState& state) const;
    std::vector<Embedding> canonicalEmbeddings(const PatternIR& pattern,
                                               const GenericGraphState& state) const;
    std::vector<Embedding> canonicalize(const std::vector<Embedding>& embeddings) const;
    std::size_t embeddingMultiplicity(const PatternIR& pattern,
                                      const GenericGraphState& state) const;

private:
    const ModelIR* model_;
};

} // namespace nfnext
