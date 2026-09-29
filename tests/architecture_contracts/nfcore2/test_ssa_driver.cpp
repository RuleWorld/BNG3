#include "test_harness.hh"
#include "driver.hh"
#include <cmath>
#include <vector>

using namespace NFcore2;

namespace {

MoleculeTypeId addType(ExecutableModel& e, const char* name) {
    MoleculeTypeDescriptor d;
    d.name = name;
    d.state_words = 1;
    d.bond_slots = 0;
    return e.buildMetadata().addMoleculeType(d);
}

MatcherId alwaysMatcher(ExecutableModel& e) {
    MatcherProgram p;
    p.add(MatchInstruction(MATCH_END));
    return e.buildMatchers().add(p);
}

TransformProgramId convertProgram(ExecutableModel& e, std::uint32_t toType) {
    TransformProgram p;
    TransformInstruction del{TRANSFORM_DELETE_MOLECULE};
    del.target = 0;
    p.add(del);
    TransformInstruction mk{TRANSFORM_CREATE_MOLECULE};
    mk.target = 1;
    mk.a = toType;
    p.add(mk);
    p.add(TransformInstruction{TRANSFORM_END});
    return e.buildTransforms().add(p);
}
RuleFamilyId addConvertFamily(ExecutableModel& e, const char* name,
                              MatcherId m, TransformProgramId t, double rate) {
    RuleFamilyDescriptor f;
    f.name = name;
    f.matcher = m;
    f.transform = t;
    RuleMember rm;
    rm.rate = rate;
    f.members.push_back(rm);
    return e.buildMetadata().addRuleFamily(f);
}

SsaMemberSignature sig(RuleFamilyId f, std::uint32_t m, MoleculeTypeId root) {
    SsaMemberSignature s;
    s.family = f;
    s.member = m;
    s.reactantTypes.push_back(root);
    return s;
}

void seed(ExecutableModel& e, SsaDriver& d, MoleculeTypeId t, int n) {
    for (int i = 0; i < n; ++i)
        d.state().molecules(t).create();
}

} // namespace

TEST(Driver_SelfConvertFiresExactEventCount) {
    ExecutableModel e;
    const MoleculeTypeId a = addType(e, "A");
    const RuleFamilyId f =
        addConvertFamily(e, "self", alwaysMatcher(e), convertProgram(e, 0), 1.5);
    // A->A convert deletes and recreates one A per event, so the live count
    // is invariant and each of the capped events must be a successful fire.
    std::vector<SsaMemberSignature> sigs;
    sigs.push_back(sig(f, 0, a));
    SsaDriver d(e, sigs);
    seed(e, d, a, 10);
    SsaDriverOptions opts;
    opts.tEnd = 100.0;
    opts.seed = 7;
    opts.maxEvents = 10;
    const SsaDriverResult r = d.run(opts);
    EXPECT_EQ(r.events, 10ull);
    EXPECT_EQ(d.state().molecules(a).liveCount(), 10u);
    EXPECT_TRUE(r.endTime <= 100.0);
}

TEST(Driver_BimolecularJoinIsExact) {
    ExecutableModel e;
    const MoleculeTypeId a = addType(e, "A");
    const MoleculeTypeId b = addType(e, "B");
    const MoleculeTypeId c = addType(e, "C");
    TransformProgram p;
    TransformInstruction d0{TRANSFORM_DELETE_MOLECULE};
    d0.target = 0;
    p.add(d0);
    TransformInstruction d1{TRANSFORM_DELETE_MOLECULE};
    d1.target = 1;
    p.add(d1);
    TransformInstruction mk{TRANSFORM_CREATE_MOLECULE};
    mk.target = 2;
    mk.a = c.value();
    p.add(mk);
    p.add(TransformInstruction(TRANSFORM_END));
    const TransformProgramId t = e.buildTransforms().add(p);
    RuleFamilyDescriptor f;
    f.name = "join";
    f.matcher = alwaysMatcher(e);
    f.transform = t;
    RuleMember rm;
    rm.rate = 0.7;
    f.members.push_back(rm);
    const RuleFamilyId fid = e.buildMetadata().addRuleFamily(f);
    SsaMemberSignature s;
    s.family = fid;
    s.member = 0;
    s.reactantTypes.push_back(a);
    s.reactantTypes.push_back(b);
    std::vector<SsaMemberSignature> sigs;
    sigs.push_back(s);
    SsaDriver driver(e, sigs);
    seed(e, driver, a, 4);
    seed(e, driver, b, 6);
    SsaDriverOptions opts;
    opts.tEnd = 100.0;
    opts.seed = 3;
    const SsaDriverResult r = driver.run(opts);
    EXPECT_EQ(r.events, 4ull);
    EXPECT_EQ(driver.state().molecules(a).liveCount(), 0u);
    EXPECT_EQ(driver.state().molecules(b).liveCount(), 2u);
    EXPECT_EQ(driver.state().molecules(c).liveCount(), 4u);
}

TEST(Driver_ReversibleIsomerizationMatchesEquilibrium) {
    // A -> B at k1=2, B -> A at k2=1: equilibrium P(B) = 2/3 per particle.
    double sumB = 0.0;
    const int runs = 300;
    for (int run = 0; run < runs; ++run) {
        ExecutableModel e;
        const MoleculeTypeId a = addType(e, "A");
        const MoleculeTypeId b = addType(e, "B");
        const MatcherId m = alwaysMatcher(e);
        const RuleFamilyId f1 =
            addConvertFamily(e, "fwd", m, convertProgram(e, b.value()), 2.0);
        const RuleFamilyId f2 =
            addConvertFamily(e, "rev", m, convertProgram(e, a.value()), 1.0);
        std::vector<SsaMemberSignature> sigs;
        sigs.push_back(sig(f1, 0, a));
        sigs.push_back(sig(f2, 0, b));
        SsaDriver d(e, sigs);
        seed(e, d, a, 20);
        SsaDriverOptions opts;
        opts.tEnd = 10.0;
        opts.seed = static_cast<std::uint64_t>(1000 + run);
        d.run(opts);
        const std::size_t na = d.state().molecules(a).liveCount();
        const std::size_t nb = d.state().molecules(b).liveCount();
        if (na + nb != 20u)
            nf2test::fail(__FILE__, __LINE__, "particle conservation violated");
        sumB += static_cast<double>(nb);
    }
    const double meanB = sumB / runs;
    // Theory: 40/3 = 13.33; SEM ~ 0.12. Tolerance spans many sigma.
    EXPECT_NEAR(meanB, 40.0 / 3.0, 0.6);
}

TEST(Driver_RejectsThreeRoots) {
    ExecutableModel e;
    const MoleculeTypeId a = addType(e, "A");
    const RuleFamilyId f =
        addConvertFamily(e, "r", alwaysMatcher(e), convertProgram(e, 0), 1.0);
    SsaMemberSignature s;
    s.family = f;
    s.member = 0;
    s.reactantTypes.push_back(a);
    s.reactantTypes.push_back(a);
    s.reactantTypes.push_back(a);
    std::vector<SsaMemberSignature> sigs;
    sigs.push_back(s);
    bool threw = false;
    try {
        SsaDriver d(e, sigs);
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    EXPECT_TRUE(threw);
}

TEST(Driver_RejectsMissingFamilyRoots) {
    ExecutableModel e;
    const MoleculeTypeId a = addType(e, "A");
    addConvertFamily(e, "r", alwaysMatcher(e), convertProgram(e, 0), 1.0);
    (void)a;
    std::vector<SsaMemberSignature> sigs;
    bool threw = false;
    try {
        SsaDriver d(e, sigs);
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    EXPECT_TRUE(threw);
}

TEST(Driver_AsymmetricHomotypicPairMatchesEitherOrientation) {
    ExecutableModel e;
    const MoleculeTypeId a = addType(e, "A");
    const MoleculeTypeId c = addType(e, "C");
    // A + A -> C with an *asymmetric* homotypic matcher: root 0 must carry
    // state bit 0 and root 1 must not.  Both roots name the same molecule
    // type, so the two root positions carry independent constraints and only
    // one orientation of a given reactant pair can match.
    MatcherProgram mp;
    MatchInstruction t0(MATCH_TYPE_EXISTS);
    t0.target = 0;
    t0.a = a.value();
    mp.add(t0);
    MatchInstruction t1(MATCH_TYPE_EXISTS);
    t1.target = 1;
    t1.a = a.value();
    mp.add(t1);
    MatchInstruction s0(MATCH_STATE_MASK);
    s0.target = 0;
    s0.a = 0;
    s0.mask = 1ull;
    s0.value = 1ull;
    mp.add(s0);
    MatchInstruction s1(MATCH_STATE_MASK);
    s1.target = 1;
    s1.a = 0;
    s1.mask = 1ull;
    s1.value = 0ull;
    mp.add(s1);
    mp.add(MatchInstruction(MATCH_END));
    const MatcherId mid = e.buildMatchers().add(mp);

    TransformProgram tp;
    TransformInstruction d0{TRANSFORM_DELETE_MOLECULE};
    d0.target = 0;
    tp.add(d0);
    TransformInstruction d1{TRANSFORM_DELETE_MOLECULE};
    d1.target = 1;
    tp.add(d1);
    TransformInstruction mk{TRANSFORM_CREATE_MOLECULE};
    mk.target = 2;
    mk.a = c.value();
    tp.add(mk);
    tp.add(TransformInstruction(TRANSFORM_END));
    const TransformProgramId tid = e.buildTransforms().add(tp);

    RuleFamilyDescriptor f;
    f.name = "asym";
    f.matcher = mid;
    f.transform = tid;
    RuleMember rm;
    rm.rate = 1.0;
    f.members.push_back(rm);
    const RuleFamilyId fid = e.buildMetadata().addRuleFamily(f);

    SsaMemberSignature s;
    s.family = fid;
    s.member = 0;
    s.reactantTypes.push_back(a);
    s.reactantTypes.push_back(a);
    std::vector<SsaMemberSignature> sigs;
    sigs.push_back(s);
    SsaDriver d(e, sigs);

    // The molecule carrying the state bit is created *second*, so it holds
    // the higher handle slot and canonicalPair keeps the orientation that
    // puts the state-less molecule at root 0 -- the orientation that fails to
    // match.  The reactant pair itself is legal: only the swapped orientation
    // satisfies the matcher, so the family must have activity and must fire.
    d.state().molecules(a).create(); // slot 0: state bit clear
    const MoleculeHandle marked =
        d.state().molecules(a).create(); // slot 1: state bit set
    d.state().molecules(a).setStateWord(marked, 0, 1ull);

    SsaDriverOptions opts;
    opts.tEnd = 100.0;
    opts.seed = 5;
    opts.maxEvents = 1;
    const SsaDriverResult r = d.run(opts);
    EXPECT_EQ(r.events, 1ull);
    EXPECT_EQ(r.nullEvents, 0ull);
    EXPECT_EQ(d.state().molecules(a).liveCount(), 0u);
    EXPECT_EQ(d.state().molecules(c).liveCount(), 1u);
}
