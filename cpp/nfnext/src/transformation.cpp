#include "nfnext/transformation.hpp"

#include "nfnext/validator.hpp"

#include <algorithm>
#include <set>
#include <sstream>

namespace nfnext {
namespace {

const MoleculeTypeIR& typeFor(const ModelIR& model, TypeId type) {
    for (const auto& declaration : model.molecule_types)
        if (declaration.id == type) return declaration;
    throw TransformationCompileError("transformation references unknown molecule type");
}

void validateState(const MoleculeTypeIR& type, std::uint32_t site, std::int32_t state) {
    if (site >= type.sites.size())
        throw TransformationCompileError("transformation references unknown site");
    if (!type.sites[site].states.empty() &&
        (state < 0 || static_cast<std::size_t>(state) >= type.sites[site].states.size()))
        throw TransformationCompileError("transformation sets an invalid site state");
}

ParticleId embedded(const MatchEmbedding& embedding, std::size_t node,
                    const GenericGraphState& state) {
    ParticleId particle;
    try {
        particle = embedding.particle(node);
    } catch (const std::out_of_range&) {
        throw TransformationError("transformation references an unbound embedding node");
    }
    if (!state.alive(particle)) throw StaleEmbeddingError("transformation embedding is stale");
    return particle;
}

void recordBond(MutationSet& mutations, Mutation::Kind kind,
                ParticleId first, std::uint32_t first_site,
                ParticleId second, std::uint32_t second_site,
                const GenericGraphState& state) {
    Mutation mutation;
    mutation.kind = kind;
    mutation.first = {state.type(first), first_site};
    mutation.second = {state.type(second), second_site};
    mutation.first_particle = first;
    mutation.second_particle = second;
    mutations.record(std::move(mutation));
}

void execute(const TransformationIR& transformation, const MatchEmbedding& embedding,
             GenericGraphState& state, TransformationResult& result) {
    for (const auto particle : embedding.particles()) {
        if (!particle.valid() || !state.alive(particle))
            throw StaleEmbeddingError("transformation embedding is stale");
    }
    result.setReactantParticles(embedding.particles());
    std::map<CreatedMoleculeId, ParticleId> created;
    for (const auto& op : transformation.operations()) {
        switch (op.kind) {
            case TransformationOpKind::SetState: {
                const auto particle = embedded(embedding, op.first_node, state);
                const auto& type = typeFor(state.model(), state.type(particle));
                validateState(type, op.first_site, op.state);
                const auto old_state = state.siteState(particle, static_cast<std::uint16_t>(op.first_site));
                state.setSiteState(particle, static_cast<std::uint16_t>(op.first_site), op.state);
                result.mutations.record(Mutation::siteStateChanged(
                    particle, op.first_site, old_state, op.state));
                break;
            }
            case TransformationOpKind::AddBond:
            case TransformationOpKind::DeleteBond: {
                const auto first = embedded(embedding, op.first_node, state);
                const auto second = embedded(embedding, op.second_node, state);
                const auto first_site = static_cast<std::uint16_t>(op.first_site);
                const auto second_site = static_cast<std::uint16_t>(op.second_site);
                if (op.kind == TransformationOpKind::AddBond) {
                    if (state.bound(first, first_site) || state.bound(second, second_site))
                        throw TransformationError("transformation binds an already-bound site");
                    state.bind(first, first_site, second, second_site);
                    recordBond(result.mutations, Mutation::Kind::Bind, first, op.first_site,
                               second, op.second_site, state);
                } else {
                    const auto first_bond = state.bond(first, first_site);
                    const auto second_bond = state.bond(second, second_site);
                    if (first_bond.particle != second || first_bond.site != second_site ||
                        second_bond.particle != first || second_bond.site != first_site)
                        throw TransformationError("transformation deletes a missing bond");
                    state.unbind(first, first_site);
                    recordBond(result.mutations, Mutation::Kind::Unbind, first, op.first_site,
                               second, op.second_site, state);
                }
                break;
            }
            case TransformationOpKind::CreateMolecule: {
                const auto& type = typeFor(state.model(), op.molecule_type);
                for (const auto& initial : op.initial_states) validateState(type, initial.first, initial.second);
                const auto particle = state.create(op.molecule_type);
                created.emplace(op.created, particle);
                result.recordCreated(op.created, particle);
                for (const auto& initial : op.initial_states)
                    state.setSiteState(particle, static_cast<std::uint16_t>(initial.first), initial.second);
                break;
            }
            case TransformationOpKind::AddBondExistingToCreated: {
                const auto first = embedded(embedding, op.first_node, state);
                const auto found = created.find(op.created);
                if (found == created.end()) throw TransformationError("bond references a molecule not yet created");
                if (state.bound(first, static_cast<std::uint16_t>(op.first_site)) ||
                    state.bound(found->second, static_cast<std::uint16_t>(op.second_site)))
                    throw TransformationError("transformation binds an already-bound site");
                state.bind(first, static_cast<std::uint16_t>(op.first_site), found->second,
                           static_cast<std::uint16_t>(op.second_site));
                recordBond(result.mutations, Mutation::Kind::Bind, first, op.first_site,
                           found->second, op.second_site, state);
                break;
            }
            case TransformationOpKind::AddBondCreated: {
                const auto first = created.find(op.created);
                const auto second = created.find(op.second_created);
                if (first == created.end() || second == created.end())
                    throw TransformationError("bond references a molecule not yet created");
                if (state.bound(first->second, static_cast<std::uint16_t>(op.first_site)) ||
                    state.bound(second->second, static_cast<std::uint16_t>(op.second_site)))
                    throw TransformationError("transformation binds an already-bound site");
                state.bind(first->second, static_cast<std::uint16_t>(op.first_site), second->second,
                           static_cast<std::uint16_t>(op.second_site));
                recordBond(result.mutations, Mutation::Kind::Bind, first->second, op.first_site,
                           second->second, op.second_site, state);
                break;
            }
            case TransformationOpKind::DestroyMolecule: {
                const auto particle = embedded(embedding, op.first_node, state);
                state.destroy(particle);
                break;
            }
            case TransformationOpKind::DestroyComplex: {
                const auto root = embedded(embedding, op.first_node, state);
                std::vector<ParticleId> members;
                for (const auto particle : state.liveParticles())
                    if (state.sameComplex(root, particle)) members.push_back(particle);
                for (const auto particle : members) state.destroy(particle);
                break;
            }
        }
    }
}

} // namespace

CompiledTransformation compileTransformation(const TransformationIR& transformation,
                                             const ModelIR& model) {
    validateModel(model);
    std::set<CreatedMoleculeId> created;
    std::set<std::pair<CreatedMoleculeId, std::uint32_t>> occupied_created_sites;
    std::vector<std::pair<std::size_t, std::uint32_t>> write_set;
    for (const auto& op : transformation.operations()) {
        switch (op.kind) {
            case TransformationOpKind::SetState:
                if (std::find(write_set.begin(), write_set.end(),
                              std::make_pair(op.first_node, op.first_site)) == write_set.end())
                    write_set.emplace_back(op.first_node, op.first_site);
                break;
            case TransformationOpKind::CreateMolecule: {
                if (!created.insert(op.created).second)
                    throw TransformationCompileError("duplicate created-molecule ID");
                const auto& type = typeFor(model, op.molecule_type);
                std::set<std::uint32_t> initial_sites;
                for (const auto& initial : op.initial_states) {
                    if (!initial_sites.insert(initial.first).second)
                        throw TransformationCompileError("duplicate initial site state");
                    validateState(type, initial.first, initial.second);
                }
                break;
            }
            case TransformationOpKind::AddBondExistingToCreated:
                if (!created.count(op.created))
                    throw TransformationCompileError("bond references a molecule not yet created");
                if (!occupied_created_sites.emplace(op.created, op.second_site).second)
                    throw TransformationCompileError("created molecule site is bound twice");
                break;
            case TransformationOpKind::AddBondCreated:
                if (!created.count(op.created) || !created.count(op.second_created))
                    throw TransformationCompileError("bond references a molecule not yet created");
                if (!occupied_created_sites.emplace(op.created, op.first_site).second ||
                    !occupied_created_sites.emplace(op.second_created, op.second_site).second)
                    throw TransformationCompileError("created molecule site is bound twice");
                break;
            case TransformationOpKind::AddBond:
            case TransformationOpKind::DeleteBond:
            case TransformationOpKind::DestroyMolecule:
            case TransformationOpKind::DestroyComplex:
                break;
        }
    }
    return CompiledTransformation(transformation, model, std::move(write_set));
}

CompiledTransformation CompiledTransformation::inverseFor(const MatchEmbedding& embedding,
                                                           const GenericGraphState& state) const {
    TransformationIR inverse;
    for (auto it = ir_.ops_.rbegin(); it != ir_.ops_.rend(); ++it) {
        const auto& op = *it;
        switch (op.kind) {
            case TransformationOpKind::SetState: {
                const auto particle = embedded(embedding, op.first_node, state);
                inverse.setState(op.first_node, op.first_site,
                                  state.siteState(particle, static_cast<std::uint16_t>(op.first_site)));
                break;
            }
            case TransformationOpKind::AddBond:
                inverse.deleteBond(op.first_node, op.first_site, op.second_node, op.second_site);
                break;
            case TransformationOpKind::DeleteBond:
                inverse.addBond(op.first_node, op.first_site, op.second_node, op.second_site);
                break;
            default:
                throw TransformationError("inverse is not defined for this transformation");
        }
    }
    return compileTransformation(inverse, *model_);
}

TransformationResult applyTransformation(const TransformationIR& transformation,
                                          const MatchEmbedding& embedding,
                                          GenericGraphState& state) {
    return applyTransformation(compileTransformation(transformation, state.model()), embedding, state);
}

TransformationResult applyTransformation(const CompiledTransformation& transformation,
                                          const MatchEmbedding& embedding,
                                          GenericGraphState& state) {
    GenericGraphState candidate = state;
    TransformationResult result;
    execute(transformation.ir_, embedding, candidate, result);
    state = std::move(candidate);
    return result;
}

} // namespace nfnext
