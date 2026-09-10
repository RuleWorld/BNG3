#pragma once

#include "nfnext/nfir.hpp"
#include "nfnext/types.hpp"

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace nfnext {

struct SiteBond {
    ParticleId particle{};
    std::uint16_t site{0};
};

// Generic compact graph state for non-lattice models. Slots are fixed-width by
// the maximum site count in the compiled model, giving direct array indexing
// without per-Molecule site allocations.
class GenericGraphState {
public:
    explicit GenericGraphState(const ModelIR& model);

    ParticleId create(TypeId type);
    void destroy(ParticleId id);
    bool alive(ParticleId id) const noexcept;

    TypeId type(ParticleId id) const;
    std::int32_t siteState(ParticleId id, std::uint16_t site) const;
    void setSiteState(ParticleId id, std::uint16_t site, std::int32_t state);
    bool bound(ParticleId id, std::uint16_t site) const;
    SiteBond bond(ParticleId id, std::uint16_t site) const;
    void bind(ParticleId a, std::uint16_t sa, ParticleId b, std::uint16_t sb);
    void unbind(ParticleId a, std::uint16_t sa);

    std::vector<ParticleId> liveParticles() const;
    bool sameComplex(ParticleId a, ParticleId b) const;
    std::uint32_t complexId(ParticleId id) const;
    std::string snapshot() const;
    std::string canonicalState() const;

    bool matchesLocal(ParticleId id, const std::vector<PredicateIR>& predicates) const;
    std::vector<FamilyId> affectedFamilies(TypeId type, std::uint16_t site,
                                           PredicateKind kind, std::int32_t value) const;

    std::size_t liveCount() const noexcept { return live_count_; }
    std::size_t capacity() const noexcept { return types_.size(); }
    std::uint16_t stride() const noexcept { return stride_; }
    const ModelIR& model() const noexcept { return *model_; }

private:
    std::size_t offset(ParticleId id, std::uint16_t site) const;
    void require(ParticleId id) const;
    void requireSite(ParticleId id, std::uint16_t site) const;
    std::uint16_t typeSiteCount(TypeId type) const;

    const ModelIR* model_;
    std::uint16_t stride_{0};
    std::vector<std::uint16_t> type_site_counts_;
    std::vector<TypeId> types_;
    std::vector<std::uint32_t> generations_;
    std::vector<std::uint8_t> alive_;
    std::vector<std::uint32_t> free_;
    std::vector<std::int32_t> site_states_;
    std::vector<ParticleId> bond_particles_;
    std::vector<std::uint16_t> bond_sites_;
    std::size_t live_count_{0};
};

} // namespace nfnext
