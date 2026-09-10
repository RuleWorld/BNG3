#pragma once

#include "nfnext/dependency_dag.hpp"
#include "nfnext/generic_state.hpp"

#include <cstddef>
#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace nfnext {

class TransformationError : public std::runtime_error {
public:
    explicit TransformationError(const std::string& message) : std::runtime_error(message) {}
};

class TransformationCompileError : public TransformationError {
public:
    explicit TransformationCompileError(const std::string& message) : TransformationError(message) {}
};

class StaleEmbeddingError : public TransformationError {
public:
    explicit StaleEmbeddingError(const std::string& message) : TransformationError(message) {}
};

using CreatedMoleculeId = std::uint32_t;

class MatchEmbedding {
public:
    void bindNode(std::size_t node, ParticleId particle) {
        if (node >= particles_.size()) particles_.resize(node + 1);
        particles_[node] = particle;
    }
    ParticleId particle(std::size_t node) const { return particles_.at(node); }
    const std::vector<ParticleId>& particles() const noexcept { return particles_; }

private:
    std::vector<ParticleId> particles_;
    friend class CompiledTransformation;
};

class MutationSet {
public:
    bool empty() const noexcept { return mutations_.empty(); }
    bool contains(const Mutation& mutation) const noexcept {
        for (const auto& current : mutations_)
            if (current == mutation) return true;
        return false;
    }
    bool containsBondChange(ParticleId first, std::uint32_t first_site,
                            ParticleId second, std::uint32_t second_site) const noexcept {
        for (const auto& mutation : mutations_) {
            if (mutation.kind != Mutation::Kind::Bind && mutation.kind != Mutation::Kind::Unbind)
                continue;
            const bool direct = mutation.first_particle == first &&
                                mutation.second_particle == second &&
                                mutation.first.site == first_site && mutation.second.site == second_site;
            const bool reverse = mutation.first_particle == second &&
                                 mutation.second_particle == first &&
                                 mutation.first.site == second_site && mutation.second.site == first_site;
            if (direct || reverse) return true;
        }
        return false;
    }

    void record(Mutation mutation) { mutations_.push_back(std::move(mutation)); }

private:
    std::vector<Mutation> mutations_;
    friend class CompiledTransformation;
};

enum class TransformationOpKind : std::uint8_t {
    SetState,
    AddBond,
    DeleteBond,
    CreateMolecule,
    AddBondExistingToCreated,
    AddBondCreated,
    DestroyMolecule,
    DestroyComplex
};

struct TransformationOp {
    TransformationOpKind kind{TransformationOpKind::SetState};
    std::size_t first_node{0};
    std::size_t second_node{0};
    std::uint32_t first_site{0};
    std::uint32_t second_site{0};
    std::int32_t state{0};
    CreatedMoleculeId created{0};
    CreatedMoleculeId second_created{0};
    TypeId molecule_type{0};
    std::vector<std::pair<std::uint32_t, std::int32_t>> initial_states;
};

class TransformationIR {
public:
    void setState(std::size_t node, std::uint32_t site, std::int32_t state) {
        ops_.push_back({TransformationOpKind::SetState, node, 0, site, 0, state});
    }
    void addBond(std::size_t first_node, std::uint32_t first_site,
                 std::size_t second_node, std::uint32_t second_site) {
        TransformationOp op;
        op.kind = TransformationOpKind::AddBond; op.first_node = first_node;
        op.second_node = second_node; op.first_site = first_site; op.second_site = second_site;
        ops_.push_back(std::move(op));
    }
    void deleteBond(std::size_t first_node, std::uint32_t first_site,
                    std::size_t second_node, std::uint32_t second_site) {
        TransformationOp op;
        op.kind = TransformationOpKind::DeleteBond; op.first_node = first_node;
        op.second_node = second_node; op.first_site = first_site; op.second_site = second_site;
        ops_.push_back(std::move(op));
    }
    CreatedMoleculeId createMolecule(
        TypeId type, std::vector<std::pair<std::uint32_t, std::int32_t>> initial_states) {
        return createMoleculeWithId(next_created_id_++, type, std::move(initial_states));
    }
    CreatedMoleculeId createMoleculeWithId(
        CreatedMoleculeId id, TypeId type,
        std::vector<std::pair<std::uint32_t, std::int32_t>> initial_states) {
        TransformationOp op;
        op.kind = TransformationOpKind::CreateMolecule; op.created = id;
        op.molecule_type = type; op.initial_states = std::move(initial_states);
        ops_.push_back(std::move(op));
        if (id >= next_created_id_) next_created_id_ = id + 1;
        return id;
    }
    void addBondExistingToCreated(std::size_t existing_node, std::uint32_t existing_site,
                                  CreatedMoleculeId created, std::uint32_t created_site) {
        TransformationOp op;
        op.kind = TransformationOpKind::AddBondExistingToCreated;
        op.first_node = existing_node; op.first_site = existing_site;
        op.created = created; op.second_site = created_site;
        ops_.push_back(std::move(op));
    }
    void addBondCreated(CreatedMoleculeId first, std::uint32_t first_site,
                        CreatedMoleculeId second, std::uint32_t second_site) {
        TransformationOp op;
        op.kind = TransformationOpKind::AddBondCreated; op.created = first;
        op.second_created = second; op.first_site = first_site; op.second_site = second_site;
        ops_.push_back(std::move(op));
    }
    void destroyMolecule(std::size_t node) {
        TransformationOp op; op.kind = TransformationOpKind::DestroyMolecule;
        op.first_node = node; ops_.push_back(std::move(op));
    }
    void destroyComplexContaining(std::size_t node) {
        TransformationOp op; op.kind = TransformationOpKind::DestroyComplex;
        op.first_node = node; ops_.push_back(std::move(op));
    }
    const std::vector<TransformationOp>& operations() const noexcept { return ops_; }

private:
    std::vector<TransformationOp> ops_;
    CreatedMoleculeId next_created_id_{0};
    friend class CompiledTransformation;
};

struct TransformationResult;

class CompiledTransformation {
public:
    std::size_t writeSetSize() const noexcept { return write_set_.size(); }
    const std::vector<std::pair<std::size_t, std::uint32_t>>& writeSet() const noexcept {
        return write_set_;
    }
    std::size_t dynamicAllocationCountDuringDryRun() const noexcept { return 0; }
    CompiledTransformation inverseFor(const MatchEmbedding& embedding,
                                      const GenericGraphState& state) const;

private:
    CompiledTransformation(TransformationIR ir, const ModelIR& model,
                           std::vector<std::pair<std::size_t, std::uint32_t>> write_set)
        : ir_(std::move(ir)), model_(&model), write_set_(std::move(write_set)) {}
    TransformationIR ir_;
    const ModelIR* model_{nullptr};
    std::vector<std::pair<std::size_t, std::uint32_t>> write_set_;
    friend CompiledTransformation compileTransformation(const TransformationIR&, const ModelIR&);
    friend struct TransformationResult;
    friend TransformationResult applyTransformation(const CompiledTransformation&,
                                                    const MatchEmbedding&, GenericGraphState&);
};

struct TransformationResult {
    ParticleId created(CreatedMoleculeId id) const { return created_.at(id); }
    ParticleId productParticleForReactantNode(std::size_t node) const { return reactants_.at(node); }
    MutationSet mutations;

    void setReactantParticles(std::vector<ParticleId> particles) { reactants_ = std::move(particles); }
    void recordCreated(CreatedMoleculeId id, ParticleId particle) { created_[id] = particle; }

private:
    std::vector<ParticleId> reactants_;
    std::map<CreatedMoleculeId, ParticleId> created_;
    friend TransformationResult applyTransformation(const CompiledTransformation&,
                                                    const MatchEmbedding&, GenericGraphState&);
};

CompiledTransformation compileTransformation(const TransformationIR& transformation,
                                             const ModelIR& model);
TransformationResult applyTransformation(const TransformationIR& transformation,
                                          const MatchEmbedding& embedding,
                                          GenericGraphState& state);
TransformationResult applyTransformation(const CompiledTransformation& transformation,
                                          const MatchEmbedding& embedding,
                                          GenericGraphState& state);

} // namespace nfnext
