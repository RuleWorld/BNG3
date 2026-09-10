#pragma once

#include "nfnext/generic_state.hpp"
#include "nfnext/pattern_ir.hpp"

#include <cstddef>
#include <cstdint>
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

    ParticleId particle(std::size_t node) const { return particles_.at(node); }
    const std::vector<ParticleId>& particles() const noexcept { return particles_; }
    const std::vector<TypeId>& typeSignature() const noexcept { return types_; }
    void setNode(std::size_t node, ParticleId particle_id, TypeId type) {
        particles_.at(node) = particle_id;
        types_.at(node) = type;
    }

    friend bool operator==(const Embedding& a, const Embedding& b) noexcept {
        return a.particles_ == b.particles_ && a.types_ == b.types_;
    }
    friend bool operator!=(const Embedding& a, const Embedding& b) noexcept { return !(a == b); }

private:
    std::vector<ParticleId> particles_;
    std::vector<TypeId> types_;

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

class GenericMatcher {
public:
    explicit GenericMatcher(const ModelIR& model) : model_(&model) {}

    std::vector<Embedding> enumerate(const PatternIR& pattern,
                                     const GenericGraphState& state,
                                     MatchMode mode = MatchMode::CompiledPlan) const;
    std::vector<Embedding> canonicalEmbeddings(const PatternIR& pattern,
                                               const GenericGraphState& state) const;
    std::vector<Embedding> canonicalize(const std::vector<Embedding>& embeddings) const;
    std::size_t embeddingMultiplicity(const PatternIR& pattern,
                                      const GenericGraphState& state) const;

private:
    const ModelIR* model_;
};

} // namespace nfnext
