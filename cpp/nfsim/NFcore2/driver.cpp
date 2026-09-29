#include "driver.hh"

#include <cmath>
#include <limits>
#include <stdexcept>

namespace NFcore2 {

SsaDriver::SsaDriver(const ExecutableModel& executable,
                     const std::vector<SsaMemberSignature>& signatures)
    : executable_(executable),
      engine_(executable),
      scheduler_(executable.metadata()) {
    executable_.validate();
    const std::vector<RuleFamilyDescriptor>& families =
        executable_.metadata().ruleFamilies();
    members_.resize(families.size());
    roots_.resize(families.size());
    std::vector<bool> familySeen(families.size(), false);
    for (std::size_t i = 0; i < signatures.size(); ++i) {
        const SsaMemberSignature& sig = signatures[i];
        if (!sig.family.valid() || sig.family.value() >= families.size())
            throw std::out_of_range("driver signature references unknown family");
        const RuleFamilyDescriptor& fam = families[sig.family.value()];
        if (sig.member >= fam.members.size())
            throw std::out_of_range("driver signature references unknown member");
        if (sig.reactantTypes.size() > 2)
            throw std::invalid_argument(
                "driver v1 supports at most two reactant roots per member");
        const RateLawDescriptor& law = fam.members[sig.member].rate_law;
        if (law.kind == LEGACY_RATE_EXPRESSION)
            throw std::invalid_argument(
                "driver v1 rejects expression rate laws (reactant-count "
                "tracking not implemented); fall back to NFcore");
        if (familySeen[sig.family.value()] &&
            roots_[sig.family.value()] != sig.reactantTypes)
            throw std::invalid_argument(
                "driver v1 requires uniform reactant roots per family");
        familySeen[sig.family.value()] = true;
        roots_[sig.family.value()] = sig.reactantTypes;
    }
    for (std::size_t f = 0; f < families.size(); ++f)
        members_[f].resize(families[f].members.size());
    for (std::size_t f = 0; f < families.size(); ++f) {
        if (!families[f].members.empty() && !familySeen[f])
            throw std::invalid_argument(
                "driver requires reactant roots for every rule family");
    }
}

void SsaDriver::initialize() {
    const std::size_t n =
        executable_.metadata().ruleFamilies().size();
    for (std::size_t f = 0; f < n; ++f)
        enumerateFamily(static_cast<std::uint32_t>(f));
}

bool SsaDriver::canonicalPair(const MoleculeRef& a, const MoleculeRef& b) {
    if (a.type != b.type)
        return true;
    if (a.handle.slot != b.handle.slot)
        return a.handle.slot < b.handle.slot;
    return a.handle.generation <= b.handle.generation;
}
void SsaDriver::enumerateFamily(std::uint32_t familyIndex) {
    SimulationState& state = engine_.state();
    const RuleFamilyDescriptor& fam =
        executable_.metadata().ruleFamilies().at(familyIndex);
    const std::vector<MoleculeTypeId>& roots = roots_[familyIndex];
    const MatcherProgram& matcher =
        executable_.matchers().at(fam.matcher);

    // Gather live candidates per root.
    std::vector<std::vector<MoleculeRef> > pool(roots.size());
    for (std::size_t r = 0; r < roots.size(); ++r) {
        const std::vector<MoleculeHandle> live =
            state.molecules(roots[r]).liveHandles();
        pool[r].reserve(live.size());
        for (std::size_t i = 0; i < live.size(); ++i)
            pool[r].push_back(MoleculeRef(roots[r], live[i]));
    }

    for (std::uint32_t m = 0; m < fam.members.size(); ++m) {
        MemberState fresh;
        if (roots.empty()) {
            MatchContext ctx;
            if (matcher.evaluate(state, engine_.scaffolds(), ctx)) {
                const double rate =
                    engine_.evaluateRate(RuleFamilyId(familyIndex), m, ctx);
                if (rate < 0.0 || !std::isfinite(rate))
                    throw std::runtime_error("driver: non-finite member rate");
                Tuple t;
                t.rate = rate;
                fresh.tuples.push_back(t);
            }
        } else if (roots.size() == 1) {
            for (std::size_t i = 0; i < pool[0].size(); ++i) {
                MatchContext ctx;
                ctx.setMoleculeAt(0, pool[0][i]);
                if (!matcher.evaluate(state, engine_.scaffolds(), ctx))
                    continue;
                const double rate =
                    engine_.evaluateRate(RuleFamilyId(familyIndex), m, ctx);
                if (rate < 0.0 || !std::isfinite(rate))
                    throw std::runtime_error("driver: non-finite member rate");
                if (rate == 0.0)
                    continue;
                Tuple t;
                t.roots.push_back(pool[0][i]);
                t.rate = rate;
                fresh.tuples.push_back(t);
            }
        } else {
            for (std::size_t i = 0; i < pool[0].size(); ++i) {
                for (std::size_t j = 0; j < pool[1].size(); ++j) {
                    if (pool[0][i] == pool[1][j])
                        continue;
                    if (!canonicalPair(pool[0][i], pool[1][j]))
                        continue;
                    MatchContext ctx;
                    ctx.setMoleculeAt(0, pool[0][i]);
                    ctx.setMoleculeAt(1, pool[1][j]);
                    if (!matcher.evaluate(state, engine_.scaffolds(), ctx))
                        continue;
                    const double rate = engine_.evaluateRate(
                        RuleFamilyId(familyIndex), m, ctx);
                    if (rate < 0.0 || !std::isfinite(rate))
                        throw std::runtime_error(
                            "driver: non-finite member rate");
                    if (rate == 0.0)
                        continue;
                    Tuple t;
                    t.roots.push_back(pool[0][i]);
                    t.roots.push_back(pool[1][j]);
                    t.rate = rate;
                    fresh.tuples.push_back(t);
                }
            }
        }
        members_[familyIndex][m] = fresh;
        double activity = 0.0;
        for (std::size_t k = 0; k < fresh.tuples.size(); ++k)
            activity += fresh.tuples[k].rate;
        scheduler_.setMemberActivity(RuleFamilyId(familyIndex), m, activity);
    }
}

void SsaDriver::refreshAfterFire(
    const FeatureDelta& delta, const std::vector<std::size_t>& beforeCounts,
    std::uint32_t firedFamily) {
    SimulationState& state = engine_.state();
    const std::size_t nTypes =
        executable_.metadata().moleculeTypes().size();
    std::vector<bool> typeTouched(nTypes, false);
    for (std::size_t t = 0; t < nTypes; ++t) {
        const std::size_t now =
            state.molecules(MoleculeTypeId(static_cast<std::uint32_t>(t)))
                .liveCount();
        if (t >= beforeCounts.size() || now != beforeCounts[t])
            typeTouched[t] = true;
    }
    std::vector<bool> familyDirty(
        executable_.metadata().ruleFamilies().size(), false);
    if (firedFamily < familyDirty.size())
        familyDirty[firedFamily] = true;
    const std::vector<RuleFamilyId> affected =
        engine_.affectedFamilies(delta);
    for (std::size_t i = 0; i < affected.size(); ++i)
        if (affected[i].valid() &&
            affected[i].value() < familyDirty.size())
            familyDirty[affected[i].value()] = true;
    for (std::size_t f = 0; f < familyDirty.size(); ++f) {
        if (familyDirty[f])
            continue;
        const std::vector<MoleculeTypeId>& roots = roots_[f];
        for (std::size_t r = 0; r < roots.size(); ++r)
            if (roots[r].valid() && roots[r].value() < typeTouched.size() &&
                typeTouched[roots[r].value()]) {
                familyDirty[f] = true;
                break;
            }
    }
    for (std::size_t f = 0; f < familyDirty.size(); ++f)
        if (familyDirty[f])
            enumerateFamily(static_cast<std::uint32_t>(f));
}

std::size_t SsaDriver::drawTuple(std::uint32_t familyIndex,
                                 std::uint32_t member,
                                 double unit) const {
    const std::vector<Tuple>& tuples =
        members_[familyIndex][member].tuples;
    double acc = 0.0;
    for (std::size_t k = 0; k < tuples.size(); ++k) {
        acc += tuples[k].rate;
        if (unit < acc)
            return k;
    }
    return tuples.empty() ? 0 : tuples.size() - 1;
}

SsaDriverResult SsaDriver::run(const SsaDriverOptions& options) {
    if (!(options.tEnd >= 0.0) || !std::isfinite(options.tEnd))
        throw std::invalid_argument("driver requires a finite non-negative tEnd");
    rng_.seed(options.seed);
    initialize();
    std::uniform_real_distribution<double> uniform(0.0, 1.0);
    SimulationState& state = engine_.state();
    SsaDriverResult result;
    double t = state.time();
    const std::size_t nTypes =
        executable_.metadata().moleculeTypes().size();

    while (t < options.tEnd) {
        if (options.maxEvents > 0 && result.events >= options.maxEvents)
            break;
        const double aTot = scheduler_.totalActivity();
        if (!(aTot > 0.0))
            break;
        double u1 = uniform(rng_);
        while (u1 <= 0.0 || u1 >= 1.0)
            u1 = uniform(rng_);
        const double dt = -std::log(u1) / aTot;
        t += dt;
        if (t > options.tEnd) {
            t = options.tEnd;
            break;
        }
        state.setTime(t);
        const double u2 = uniform(rng_);
        const EventChoice choice = scheduler_.sample(u2);
        const std::uint32_t fi = choice.family.value();
        const std::uint32_t mi = choice.member;
        const double u3 = uniform(rng_);
        double memberTotal = 0.0;
        for (std::size_t k = 0; k < members_[fi][mi].tuples.size(); ++k)
            memberTotal += members_[fi][mi].tuples[k].rate;
        MatchContext ctx;
        // Liveness guard: a sampled tuple may reference molecules consumed
        // since enumeration (net-zero count changes, cross-family staleness).
        // Stale tuples become null events, never wrong fires: the matcher
        // re-validates live roots inside Engine::fire.
        bool tupleLive = false;
        if (!members_[fi][mi].tuples.empty()) {
            const std::size_t pick =
                drawTuple(fi, mi, u3 * memberTotal);
            const Tuple& tuple = members_[fi][mi].tuples[pick];
            tupleLive = true;
            for (std::size_t r = 0; r < tuple.roots.size(); ++r)
                if (!tuple.roots[r].valid() ||
                    !state.molecules(tuple.roots[r].type)
                         .alive(tuple.roots[r].handle)) {
                    tupleLive = false;
                    break;
                }
            if (tupleLive)
                for (std::size_t r = 0; r < tuple.roots.size(); ++r)
                    ctx.setMoleculeAt(r, tuple.roots[r]);
        }
        if (!tupleLive) {
            ++result.nullEvents;
            enumerateFamily(fi);
            continue;
        }
        std::vector<std::size_t> beforeCounts(nTypes, 0);
        for (std::size_t ty = 0; ty < nTypes; ++ty)
            beforeCounts[ty] =
                state.molecules(MoleculeTypeId(static_cast<std::uint32_t>(ty)))
                    .liveCount();
        FeatureDelta delta;
        const bool fired = engine_.fire(choice.family, mi, ctx, delta);
        if (!fired) {
            ++result.nullEvents;
            enumerateFamily(fi);
            continue;
        }
        ++result.events;
        refreshAfterFire(delta, beforeCounts, fi);
    }
    state.setTime(t);
    result.endTime = t;
    return result;
}

} // namespace NFcore2
