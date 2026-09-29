#pragma once

#include "engine.hh"
#include "scheduler.hh"

#include <cstdint>
#include <random>
#include <vector>

namespace NFcore2 {

// One reactant root per entry; v1 supports at most two roots per member.
// The driver does not infer roots from bytecode: lowered models provide
// them from NativeReactionSnapshot::reactant_types via
// LegacyLoweringResult::rules[i] (rule order is shared), hand-built models
// provide them explicitly.
struct SsaMemberSignature {
    RuleFamilyId family;
    std::uint32_t member;
    std::vector<MoleculeTypeId> reactantTypes;
    SsaMemberSignature() : family(), member(0) {}
};

struct SsaDriverOptions {
    double tEnd = 1.0;
    std::uint64_t seed = 1;
    std::uint64_t maxEvents = 0; // 0 = unlimited
};

struct SsaDriverResult {
    double endTime = 0.0;
    std::uint64_t events = 0;
    std::uint64_t nullEvents = 0;
};

// STATUS: not wired.  SsaDriver has no production call site.  Every
// user-facing entry point for the network-free path — the pybind
// `simulate_nf` binding, `ActionDispatch::runNfSimulation`, and the
// CLI action loop — constructs and steps `NFcore::System`; none of
// them constructs an ExecutableModel or instantiates this class.
// The only callers are `tests/architecture_contracts/nfcore2/
// test_ssa_driver.cpp` and `tests/cpp/test_nfcore2_parity.cpp`.  The
// linker agrees: no SsaDriver symbol survives into the shipped
// extension.  Treat this as a qualification prototype under
// `bng_nfcore2`, not a delivered execution path, and do not route
// `method="nf"` traffic here without first proving seeded stochastic
// equivalence against NFcore beyond the single reversible-
// isomerization case in test_nfcore2_parity.cpp.
//
// Orientation of equal-typed reactant roots: canonicalPair() keeps one
// orientation per unordered pair, but matcher.cpp resolves every MATCH_*
// instruction against a root index (`x.target`), so the two orientations of
// a homotypic pair carry independent constraints.  enumerateFamily()
// therefore tries the canonical orientation first and falls back to the
// swapped one; a pair that matches in both orientations is still counted
// once, and a pair that matches in neither contributes nothing.
//
// Direct-method SSA over an ExecutableModel.
//
// v1 scope (fail-closed, anything else throws):
// - at most two reactant roots per member;
// - rate laws LEGACY_RATE_CONSTANT, LEGACY_RATE_LOCAL_LINEAR,
//   LEGACY_RATE_DOR_PRODUCT (EXPRESSION needs reactant-count tracking and
//   is rejected until it exists).
//
// Member activities are rate-summed over matched tuples: activity(m) =
// sum(evaluateRate(t) for t in tuples(m)). Sampling picks a member from the
// Fenwick scheduler, then a tuple within the member proportional to its
// rate. Rejected fires are null events: time advances, state is untouched.
//
// Refresh policy (correctness over speed, v1): after each fire, re-enumerate
// every family named by Engine::affectedFamilies(delta) plus every family
// whose reactant types changed live count. This stays correct even where
// the lowered dependency index omits existence features; incremental
// per-member refresh is follow-up work once parity holds.
class SsaDriver {
public:
    SsaDriver(const ExecutableModel& executable,
              const std::vector<SsaMemberSignature>& signatures);

    SsaDriverResult run(const SsaDriverOptions& options);

    // (Re)build every member table from live state. Called automatically at
    // the start of run(); exposed so tests and the System-seeding path can
    // seed state, initialize, then inspect before running.
    void initialize();
    SimulationState& state() { return engine_.state(); }
    const SimulationState& state() const { return engine_.state(); }
    const Engine& engine() const { return engine_; }

private:
    struct Tuple {
        std::vector<MoleculeRef> roots;
        double rate;
    };
    struct MemberState {
        std::vector<Tuple> tuples;
    };

    void enumerateFamily(std::uint32_t familyIndex);
    void refreshAfterFire(const FeatureDelta& delta,
                          const std::vector<std::size_t>& beforeCounts,
                          std::uint32_t firedFamily);
    std::size_t drawTuple(std::uint32_t familyIndex, std::uint32_t member,
                          double unit) const;
    static bool canonicalPair(const MoleculeRef& a, const MoleculeRef& b);

    const ExecutableModel& executable_;
    Engine engine_;
    HierarchicalScheduler scheduler_;
    // [familyIndex][memberIndex]
    std::vector<std::vector<MemberState> > members_;
    // Per family: reactant types per root, parallel to signatures.
    std::vector<std::vector<MoleculeTypeId> > roots_;
    std::mt19937_64 rng_;
};

} // namespace NFcore2
