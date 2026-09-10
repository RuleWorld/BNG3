#pragma once

#include "nfnext/types.hpp"

#include <algorithm>
#include <cstdint>
#include <limits>
#include <map>
#include <set>
#include <tuple>
#include <utility>
#include <vector>

namespace nfnext {

enum class FeatureKind : std::uint8_t {
    SiteState = 0,
    SiteBound = 1,
    SiteFree = 2,
    NeighborFree = 3,
    NeighborOccupied = 4,
    Observable = 5,
    Parameter = 6
};

struct Feature {
    FeatureKind kind{FeatureKind::SiteState};
    TypeId type{0};
    Position site{0};
    std::int32_t value{0};

    static Feature siteState(TypeId type, std::uint32_t site, std::int32_t state) noexcept {
        return {FeatureKind::SiteState, type, site, state};
    }
    static Feature siteBound(TypeId type, std::uint32_t site) noexcept {
        return {FeatureKind::SiteBound, type, site, 0};
    }
    static Feature siteFree(TypeId type, std::uint32_t site) noexcept {
        return {FeatureKind::SiteFree, type, site, 0};
    }
    static Feature neighborFree(TypeId type, Position position) noexcept {
        return {FeatureKind::NeighborFree, type, position, 0};
    }
    static Feature neighborOccupied(TypeId type, Position position) noexcept {
        return {FeatureKind::NeighborOccupied, type, position, 0};
    }
    static Feature observable(std::uint32_t id) noexcept {
        return {FeatureKind::Observable, 0, id, 0};
    }
    static Feature parameter(std::uint32_t id) noexcept {
        return {FeatureKind::Parameter, 0, id, 0};
    }

    auto key() const noexcept {
        return std::make_tuple(kind, type, site, value);
    }
};

struct SiteRef {
    TypeId type{0};
    std::uint32_t site{0};

    friend bool operator==(const SiteRef& a, const SiteRef& b) noexcept {
        return a.type == b.type && a.site == b.site;
    }
};

struct Mutation {
    enum class Kind : std::uint8_t { SetSiteState, Bind, Unbind, DestroyType, MovePosition, ObservableChanged };

    Kind kind{Kind::SetSiteState};
    SiteRef first{};
    SiteRef second{};
    std::int32_t old_state{0};
    std::int32_t new_state{0};
    Position from{0};
    Position to{0};
    std::uint32_t radius{0};
    std::uint32_t id{0};
    ParticleId first_particle{};
    ParticleId second_particle{};

    static Mutation setSiteState(TypeId type, std::uint32_t site,
                                 std::int32_t old_state, std::int32_t new_state) noexcept {
        Mutation mutation;
        mutation.kind = Kind::SetSiteState;
        mutation.first = {type, site};
        mutation.old_state = old_state;
        mutation.new_state = new_state;
        return mutation;
    }
    static Mutation bind(SiteRef first, SiteRef second) noexcept {
        Mutation mutation;
        mutation.kind = Kind::Bind;
        mutation.first = first;
        mutation.second = second;
        return mutation;
    }
    static Mutation unbind(SiteRef first, SiteRef second) noexcept {
        Mutation mutation = bind(first, second);
        mutation.kind = Kind::Unbind;
        return mutation;
    }
    static Mutation destroyType(TypeId type) noexcept {
        Mutation mutation;
        mutation.kind = Kind::DestroyType;
        mutation.first.type = type;
        return mutation;
    }
    static Mutation movePosition(TypeId type, Position from, Position to,
                                 std::uint32_t radius) noexcept {
        Mutation mutation;
        mutation.kind = Kind::MovePosition;
        mutation.first.type = type;
        mutation.from = from;
        mutation.to = to;
        mutation.radius = radius;
        return mutation;
    }
    static Mutation observableChanged(std::uint32_t id) noexcept {
        Mutation mutation;
        mutation.kind = Kind::ObservableChanged;
        mutation.id = id;
        return mutation;
    }

    static Mutation siteStateChanged(ParticleId particle, std::uint32_t site,
                                     std::int32_t old_state, std::int32_t new_state) noexcept {
        Mutation mutation = setSiteState(0, site, old_state, new_state);
        mutation.first_particle = particle;
        return mutation;
    }

    friend bool operator==(const Mutation& a, const Mutation& b) noexcept {
        return a.kind == b.kind && a.first == b.first && a.second == b.second &&
               a.old_state == b.old_state && a.new_state == b.new_state &&
               a.from == b.from && a.to == b.to && a.radius == b.radius && a.id == b.id &&
               a.first_particle == b.first_particle && a.second_particle == b.second_particle;
    }
};

using DependencyIndex = std::map<
    std::tuple<FeatureKind, TypeId, Position, std::int32_t>,
    std::vector<FamilyId>>;

class DependencyDag;

class DependencyDagBuilder {
public:
    void familyReads(FamilyId family, const Feature& feature) {
        auto& families = reads_[feature.key()];
        if (std::find(families.begin(), families.end(), family) == families.end())
            families.push_back(family);
    }

    DependencyDag build() const;

private:
    DependencyIndex reads_;
};

class DependencyDag {
public:
    std::vector<FamilyId> affectedBy(const Mutation& mutation) const {
        std::set<FamilyId> affected;
        auto add = [this, &affected](const Feature& feature) {
            const auto found = reads_.find(feature.key());
            if (found != reads_.end()) affected.insert(found->second.begin(), found->second.end());
        };
        switch (mutation.kind) {
            case Mutation::Kind::SetSiteState:
                add(Feature::siteState(mutation.first.type, mutation.first.site, mutation.old_state));
                add(Feature::siteState(mutation.first.type, mutation.first.site, mutation.new_state));
                break;
            case Mutation::Kind::Bind:
            case Mutation::Kind::Unbind:
                for (const auto site : {mutation.first, mutation.second}) {
                    add(Feature::siteBound(site.type, site.site));
                    add(Feature::siteFree(site.type, site.site));
                }
                break;
            case Mutation::Kind::DestroyType:
                for (const auto& entry : reads_) {
                    if (std::get<1>(entry.first) == mutation.first.type) {
                        affected.insert(entry.second.begin(), entry.second.end());
                    }
                }
                break;
            case Mutation::Kind::MovePosition: {
                const auto addNeighborhood = [&add, &mutation](Position center) {
                    const auto begin = center > mutation.radius ? center - mutation.radius : 0;
                    const auto end = center > (std::numeric_limits<Position>::max() - mutation.radius)
                        ? std::numeric_limits<Position>::max() : center + mutation.radius;
                    for (Position position = begin;; ++position) {
                        add(Feature::neighborFree(mutation.first.type, position));
                        add(Feature::neighborOccupied(mutation.first.type, position));
                        if (position == end) break;
                    }
                };
                addNeighborhood(mutation.from);
                addNeighborhood(mutation.to);
                break;
            }
            case Mutation::Kind::ObservableChanged:
                add(Feature::observable(mutation.id));
                break;
        }
        return {affected.begin(), affected.end()};
    }

private:
    explicit DependencyDag(DependencyIndex reads)
        : reads_(std::move(reads)) {}

    DependencyIndex reads_;
    friend class DependencyDagBuilder;
};

inline DependencyDag DependencyDagBuilder::build() const {
    auto copy = reads_;
    for (auto& entry : copy)
        std::sort(entry.second.begin(), entry.second.end());
    return DependencyDag(std::move(copy));
}

} // namespace nfnext
