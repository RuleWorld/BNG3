#include "nfnext/generic_state.hpp"

#include <algorithm>
#include <queue>
#include <sstream>
#include <unordered_map>

namespace nfnext {

GenericGraphState::GenericGraphState(const ModelIR& model) : model_(&model) {
    TypeId max_id = 0;
    for (const auto& mt : model.molecule_types) max_id = std::max(max_id, mt.id);
    type_site_counts_.assign(static_cast<std::size_t>(max_id) + 1, 0);
    for (const auto& mt : model.molecule_types) {
        if (mt.sites.size() > 65535) throw std::invalid_argument("too many sites for compact graph backend");
        type_site_counts_[mt.id] = static_cast<std::uint16_t>(mt.sites.size());
        stride_ = std::max(stride_, static_cast<std::uint16_t>(mt.sites.size()));
    }
    if (stride_ == 0) stride_ = 1;
}

std::uint16_t GenericGraphState::typeSiteCount(TypeId type) const {
    if (type >= type_site_counts_.size()) throw std::out_of_range("unknown molecule type");
    return type_site_counts_[type];
}

ParticleId GenericGraphState::create(TypeId type) {
    const auto sites = typeSiteCount(type);
    std::uint32_t slot;
    if (!free_.empty()) {
        slot = free_.back(); free_.pop_back(); alive_[slot] = 1; types_[slot] = type;
    } else {
        slot = static_cast<std::uint32_t>(types_.size());
        types_.push_back(type); generations_.push_back(1); alive_.push_back(1);
        site_states_.resize((static_cast<std::size_t>(slot) + 1) * stride_, 0);
        bond_particles_.resize((static_cast<std::size_t>(slot) + 1) * stride_);
        bond_sites_.resize((static_cast<std::size_t>(slot) + 1) * stride_, 0);
    }
    const ParticleId id{slot, generations_[slot]};
    for (std::uint16_t s = 0; s < stride_; ++s) {
        const auto o = static_cast<std::size_t>(slot) * stride_ + s;
        site_states_[o] = 0; bond_particles_[o] = {}; bond_sites_[o] = 0;
    }
    (void)sites;
    ++live_count_;
    return id;
}

bool GenericGraphState::alive(ParticleId id) const noexcept {
    return id.index < alive_.size() && alive_[id.index] != 0 && generations_[id.index] == id.generation;
}

void GenericGraphState::require(ParticleId id) const {
    if (!alive(id)) throw std::out_of_range("stale or invalid ParticleId");
}

void GenericGraphState::requireSite(ParticleId id, std::uint16_t site) const {
    require(id);
    if (site >= typeSiteCount(types_[id.index])) throw std::out_of_range("invalid molecule site");
}

std::size_t GenericGraphState::offset(ParticleId id, std::uint16_t site) const {
    requireSite(id, site);
    return static_cast<std::size_t>(id.index) * stride_ + site;
}

void GenericGraphState::destroy(ParticleId id) {
    require(id);
    const auto count = typeSiteCount(types_[id.index]);
    for (std::uint16_t s = 0; s < count; ++s) if (bound(id, s)) unbind(id, s);
    alive_[id.index] = 0; ++generations_[id.index]; free_.push_back(id.index); --live_count_;
}

TypeId GenericGraphState::type(ParticleId id) const { require(id); return types_[id.index]; }
std::int32_t GenericGraphState::siteState(ParticleId id, std::uint16_t site) const { return site_states_[offset(id, site)]; }
void GenericGraphState::setSiteState(ParticleId id, std::uint16_t site, std::int32_t state) { site_states_[offset(id, site)] = state; }
bool GenericGraphState::bound(ParticleId id, std::uint16_t site) const { return bond_particles_[offset(id, site)].valid(); }

SiteBond GenericGraphState::bond(ParticleId id, std::uint16_t site) const {
    const auto o = offset(id, site);
    return SiteBond{bond_particles_[o], bond_sites_[o]};
}

void GenericGraphState::bind(ParticleId a, std::uint16_t sa, ParticleId b, std::uint16_t sb) {
    const auto oa = offset(a, sa), ob = offset(b, sb);
    if (bond_particles_[oa].valid() || bond_particles_[ob].valid()) throw std::invalid_argument("site already bound");
    bond_particles_[oa] = b; bond_sites_[oa] = sb;
    bond_particles_[ob] = a; bond_sites_[ob] = sa;
}

void GenericGraphState::unbind(ParticleId a, std::uint16_t sa) {
    const auto oa = offset(a, sa);
    if (!bond_particles_[oa].valid()) return;
    const ParticleId b = bond_particles_[oa]; const std::uint16_t sb = bond_sites_[oa];
    bond_particles_[oa] = {}; bond_sites_[oa] = 0;
    if (alive(b) && sb < typeSiteCount(types_[b.index])) {
        const auto ob = static_cast<std::size_t>(b.index) * stride_ + sb;
        if (bond_particles_[ob] == a) { bond_particles_[ob] = {}; bond_sites_[ob] = 0; }
    }
}

std::vector<ParticleId> GenericGraphState::liveParticles() const {
    std::vector<ParticleId> particles;
    particles.reserve(live_count_);
    for (std::size_t index = 0; index < alive_.size(); ++index)
        if (alive_[index] != 0) particles.push_back({static_cast<std::uint32_t>(index), generations_[index]});
    return particles;
}

bool GenericGraphState::sameComplex(ParticleId a, ParticleId b) const {
    require(a);
    require(b);
    if (a == b) return true;
    std::vector<std::uint8_t> visited(types_.size(), 0);
    std::queue<ParticleId> pending;
    pending.push(a);
    visited[a.index] = 1;
    while (!pending.empty()) {
        const auto current = pending.front();
        pending.pop();
        const auto count = typeSiteCount(types_[current.index]);
        for (std::uint16_t site = 0; site < count; ++site) {
            const auto partner = bond(current, site).particle;
            if (!alive(partner) || visited[partner.index] != 0) continue;
            if (partner == b) return true;
            visited[partner.index] = 1;
            pending.push(partner);
        }
    }
    return false;
}

std::uint32_t GenericGraphState::complexId(ParticleId id) const {
    require(id);
    std::vector<std::uint8_t> visited(types_.size(), 0);
    std::queue<ParticleId> pending;
    pending.push(id);
    visited[id.index] = 1;
    std::uint32_t minimum = id.index;
    while (!pending.empty()) {
        const auto current = pending.front();
        pending.pop();
        minimum = std::min(minimum, current.index);
        const auto count = typeSiteCount(types_[current.index]);
        for (std::uint16_t site = 0; site < count; ++site) {
            const auto partner = bond(current, site).particle;
            if (!alive(partner) || visited[partner.index] != 0) continue;
            visited[partner.index] = 1;
            pending.push(partner);
        }
    }
    return minimum;
}

std::string GenericGraphState::snapshot() const {
    std::ostringstream out;
    out << stride_ << ':' << live_count_ << ':' << types_.size() << ';';
    for (std::size_t i = 0; i < types_.size(); ++i) {
        out << types_[i] << ':' << generations_[i] << ':' << static_cast<unsigned>(alive_[i]) << ';';
        for (std::uint16_t site = 0; site < stride_; ++site) {
            const auto offset = i * stride_ + site;
            out << site_states_[offset] << ':' << bond_particles_[offset].index << ':'
                << bond_particles_[offset].generation << ':' << bond_sites_[offset] << ';';
        }
    }
    out << "free:" << free_.size() << ':';
    for (const auto slot : free_) out << slot << ',';
    return out.str();
}

std::string GenericGraphState::canonicalState() const {
    auto particles = liveParticles();
    std::sort(particles.begin(), particles.end(), [this](ParticleId a, ParticleId b) {
        if (type(a) != type(b)) return type(a) < type(b);
        if (a.index != b.index) return a.index < b.index;
        return a.generation < b.generation;
    });
    std::unordered_map<std::uint64_t, std::size_t> positions;
    for (std::size_t i = 0; i < particles.size(); ++i) {
        const auto key = (static_cast<std::uint64_t>(particles[i].index) << 32) |
                         particles[i].generation;
        positions.emplace(key, i);
    }
    std::ostringstream out;
    for (const auto particle : particles) {
        out << type(particle) << '[';
        const auto count = typeSiteCount(type(particle));
        for (std::uint16_t site = 0; site < count; ++site) {
            if (site != 0) out << ',';
            out << siteState(particle, site) << '/';
            const auto bond_info = bond(particle, site);
            if (!bond_info.particle.valid()) {
                out << '-';
            } else {
                const auto key = (static_cast<std::uint64_t>(bond_info.particle.index) << 32) |
                                 bond_info.particle.generation;
                const auto found = positions.find(key);
                out << (found == positions.end() ? std::numeric_limits<std::size_t>::max() : found->second)
                    << '.' << bond_info.site;
            }
        }
        out << "]";
    }
    return out.str();
}

bool GenericGraphState::matchesLocal(ParticleId id, const std::vector<PredicateIR>& predicates) const {
    require(id);
    for (const auto& p : predicates) {
        if (p.molecule_type != type(id)) return false;
        switch (p.kind) {
            case PredicateKind::SiteStateEq:
                if (siteState(id, p.site) != p.value) return false;
                break;
            case PredicateKind::SiteBound:
                if (!bound(id, p.site)) return false;
                break;
            case PredicateKind::SiteFree:
                if (bound(id, p.site)) return false;
                break;
            default:
                return false; // non-local/topological predicate needs a specialized matcher
        }
    }
    return true;
}

std::vector<FamilyId> GenericGraphState::affectedFamilies(TypeId type, std::uint16_t site,
                                                           PredicateKind kind, std::int32_t value) const {
    const auto it = model_->dependencies.feature_to_families.find(encodeFeature(type, site, kind, value));
    return it == model_->dependencies.feature_to_families.end() ? std::vector<FamilyId>{} : it->second;
}

} // namespace nfnext
