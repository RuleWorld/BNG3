#include "nfnext/lattice.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace nfnext {

GenomeLattice::GenomeLattice(LatticeConfig config)
    : config_(config), occupant_(config.length), hop_propensities_(config.length) {
    if (config_.length == 0) throw std::invalid_argument("lattice length must be > 0");
    if (config_.footprint == 0 || config_.footprint > config_.length)
        throw std::invalid_argument("footprint must be in [1,length]");
    if (config_.periodic && config_.footprint != 1)
        throw std::invalid_argument("periodic lattice currently supports footprint=1 only");
    if (config_.initiation_position + config_.footprint > config_.length)
        throw std::invalid_argument("initiation span exceeds lattice");
    if (!(config_.hop_rate >= 0.0) || !(config_.initiation_rate >= 0.0) || !(config_.termination_rate >= 0.0))
        throw std::invalid_argument("rates must be >= 0");
}

bool GenomeLattice::occupied(Position p) const {
    return p < occupant_.size() && occupant_[p].valid() && arena_.alive(occupant_[p]);
}

ParticleId GenomeLattice::occupant(Position p) const {
    if (!occupied(p)) return {};
    return occupant_[p];
}

bool GenomeLattice::isHead(Position p) const {
    if (!occupied(p)) return false;
    const ParticleId id = occupant_[p];
    return arena_.position(id) == p;
}

bool GenomeLattice::spanFree(Position p) const {
    if (p + config_.footprint > config_.length) return false;
    for (Position x = p; x < p + config_.footprint; ++x) if (occupied(x)) return false;
    return true;
}

void GenomeLattice::fillSpan(Position p, ParticleId id) {
    for (Position x = p; x < p + config_.footprint; ++x) occupant_[x] = id;
}

void GenomeLattice::clearSpan(Position p, ParticleId id) {
    for (Position x = p; x < p + config_.footprint && x < config_.length; ++x)
        if (occupant_[x] == id) occupant_[x] = {};
}

ParticleId GenomeLattice::place(Position p, TypeId type) {
    if (!spanFree(p)) throw std::invalid_argument("placement span is occupied or out of bounds");
    ParticleId id = arena_.create(type, p);
    fillSpan(p, id);
    for (Position x = p; x < p + config_.footprint; ++x) refreshForChangedSite(x);
    refresh(p);
    return id;
}

Position GenomeLattice::next(Position p) const noexcept {
    if (p + 1 < config_.length) return p + 1;
    return config_.periodic ? 0 : config_.length;
}

bool GenomeLattice::canHop(Position p) const {
    if (!isHead(p)) return false;
    if (config_.periodic) return !occupied(next(p));
    const Position entering = p + config_.footprint;
    return entering < config_.length && !occupied(entering);
}

void GenomeLattice::refresh(Position head) {
    if (head >= config_.length) return;
    hop_propensities_.set(head, canHop(head) ? config_.hop_rate : 0.0);
}

void GenomeLattice::refreshForChangedSite(Position site) {
    // A head at h depends on the entering site h+footprint. Therefore a change
    // at site x can change eligibility of h=x-footprint.
    if (site >= config_.footprint) refresh(site - config_.footprint);
    if (config_.periodic && config_.footprint == 1 && site == 0) refresh(config_.length - 1);
}

void GenomeLattice::refreshAfterHeadMove(Position old_head, Position new_head) {
    refresh(old_head);
    refresh(new_head);
    refreshForChangedSite(old_head);
    if (!config_.periodic) refreshForChangedSite(old_head + config_.footprint);
    else refreshForChangedSite(new_head);
}

bool GenomeLattice::hop(Position p) {
    if (!canHop(p)) return false;
    const ParticleId id = occupant_[p];
    const Position q = next(p);
    if (config_.periodic) {
        occupant_[p] = {};
        occupant_[q] = id;
    } else {
        const Position entering = p + config_.footprint;
        occupant_[p] = {};
        occupant_[entering] = id;
    }
    arena_.setPosition(id, q);
    refreshAfterHeadMove(p, q);
    return true;
}

bool GenomeLattice::canInitiate() const {
    return config_.initiation_rate > 0.0 && spanFree(config_.initiation_position);
}

bool GenomeLattice::initiate(TypeId type) {
    if (!canInitiate()) return false;
    place(config_.initiation_position, type);
    return true;
}

bool GenomeLattice::canTerminate() const {
    if (config_.periodic || !(config_.termination_rate > 0.0)) return false;
    const Position terminal_head = config_.length - config_.footprint;
    return isHead(terminal_head);
}

bool GenomeLattice::terminate() {
    if (!canTerminate()) return false;
    const Position head = config_.length - config_.footprint;
    const ParticleId id = occupant_[head];
    clearSpan(head, id);
    arena_.destroy(id);
    for (Position x = head; x < config_.length; ++x) refreshForChangedSite(x);
    refresh(head);
    return true;
}

LatticeRunResult GenomeLattice::run(std::uint64_t max_events, double max_time, std::uint64_t seed, std::uint64_t trajectory_id) {
    CounterRng rng(seed, trajectory_id);
    LatticeRunResult out;
    while (out.events < max_events && out.time < max_time) {
        const double init_a = initiationPropensity();
        const double hop_a = hopPropensity();
        const double term_a = terminationPropensity();
        const double total = init_a + hop_a + term_a;
        if (!(total > 0.0)) break;
        const std::uint64_t base_counter = out.events * 2;
        const double dt = rng.exponential(base_counter, total);
        if (out.time + dt > max_time) { out.time = max_time; break; }
        double target = rng.uniformOpen01(base_counter + 1) * total;
        out.time += dt;
        bool fired = false;
        if (target < init_a) {
            fired = initiate(); if (fired) ++out.initiations;
        } else if ((target -= init_a) < hop_a) {
            const Position p = selectHop(target); fired = hop(p); if (fired) ++out.hops;
        } else {
            fired = terminate(); if (fired) ++out.terminations;
        }
        if (fired) ++out.events; else ++out.null_events;
    }
    return out;
}

} // namespace nfnext
