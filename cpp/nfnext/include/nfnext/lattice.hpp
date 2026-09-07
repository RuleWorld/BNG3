#pragma once

#include "nfnext/counter_rng.hpp"
#include "nfnext/fenwick.hpp"
#include "nfnext/soa_arena.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace nfnext {

struct LatticeConfig {
    std::uint32_t length{0};
    double hop_rate{1.0};
    bool periodic{false};
    std::uint32_t footprint{1};
    double initiation_rate{0.0};
    double termination_rate{0.0};
    std::uint32_t initiation_position{0};
};

struct LatticeRunResult {
    double time{0.0};
    std::uint64_t events{0};
    std::uint64_t initiations{0};
    std::uint64_t hops{0};
    std::uint64_t terminations{0};
    std::uint64_t null_events{0};
};

class GenomeLattice {
public:
    explicit GenomeLattice(LatticeConfig config);

    ParticleId place(Position p, TypeId type = 0);
    bool occupied(Position p) const;
    ParticleId occupant(Position p) const;
    Position length() const noexcept { return config_.length; }
    std::uint32_t footprint() const noexcept { return config_.footprint; }
    std::size_t particles() const noexcept { return arena_.liveCount(); }

    bool isHead(Position p) const;
    bool canHop(Position p) const;
    bool hop(Position p);
    bool canInitiate() const;
    bool initiate(TypeId type = 0);
    bool canTerminate() const;
    bool terminate();

    double hopPropensity() const noexcept { return hop_propensities_.total(); }
    double initiationPropensity() const noexcept { return canInitiate() ? config_.initiation_rate : 0.0; }
    double terminationPropensity() const noexcept { return canTerminate() ? config_.termination_rate : 0.0; }
    double totalPropensity() const noexcept { return hopPropensity() + initiationPropensity() + terminationPropensity(); }
    Position selectHop(double target) const { return static_cast<Position>(hop_propensities_.lowerBound(target)); }

    LatticeRunResult run(std::uint64_t max_events, double max_time, std::uint64_t seed, std::uint64_t trajectory_id = 0);

private:
    Position next(Position p) const noexcept;
    bool spanFree(Position p) const;
    void fillSpan(Position p, ParticleId id);
    void clearSpan(Position p, ParticleId id);
    void refresh(Position head);
    void refreshForChangedSite(Position site);
    void refreshAfterHeadMove(Position old_head, Position new_head);

    LatticeConfig config_;
    ParticleArena arena_;
    std::vector<ParticleId> occupant_;
    FenwickTree hop_propensities_;
};

} // namespace nfnext
