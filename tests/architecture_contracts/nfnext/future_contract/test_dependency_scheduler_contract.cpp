#include "contract_test.hpp"

#if __has_include("nfnext/dependency_dag.hpp") && __has_include("nfnext/adaptive_scheduler.hpp")
#include "nfnext/dependency_dag.hpp"
#include "nfnext/adaptive_scheduler.hpp"
#include "nfnext/nfir.hpp"
#include <algorithm>
#include <random>
using namespace nfnext;

CONTRACT_CASE("dependency DAG maps changed state to only families that read it") {
    DependencyDagBuilder b;
    b.familyReads(0, Feature::siteState(1, 2, 3));
    b.familyReads(1, Feature::siteState(1, 7, 9));
    b.familyReads(2, Feature::siteBound(1, 2));
    auto dag = b.build();
    auto affected = dag.affectedBy(Mutation::setSiteState(1, 2, 3, 4));
    REQUIRE_EQ(affected, std::vector<FamilyId>({0}));
}

CONTRACT_CASE("bond mutation invalidates bound and free predicates on both endpoints") {
    DependencyDagBuilder b;
    b.familyReads(0, Feature::siteBound(0, 1));
    b.familyReads(1, Feature::siteFree(0, 1));
    b.familyReads(2, Feature::siteBound(2, 3));
    b.familyReads(3, Feature::siteFree(2, 3));
    auto dag = b.build();
    auto affected = dag.affectedBy(Mutation::bind({0,1}, {2,3}));
    std::sort(affected.begin(), affected.end());
    REQUIRE_EQ(affected, std::vector<FamilyId>({0,1,2,3}));
}

CONTRACT_CASE("destroy particle invalidates every feature owned by that particle type") {
    DependencyDagBuilder b;
    for (std::uint16_t s = 0; s < 8; ++s) {
        b.familyReads(s, Feature::siteState(5, s, 0));
        b.familyReads(20 + s, Feature::siteBound(5, s));
    }
    auto dag = b.build();
    auto affected = dag.affectedBy(Mutation::destroyType(5));
    REQUIRE_EQ(affected.size(), 16u);
}

CONTRACT_CASE("coordinate move invalidates only local lattice neighborhood") {
    DependencyDagBuilder b;
    for (Position p = 0; p < 10000; ++p)
        b.familyReads(p, Feature::neighborFree(0, p));
    auto dag = b.build();
    auto affected = dag.affectedBy(Mutation::movePosition(0, 5000, 5001, 10));
    REQUIRE(affected.size() <= 24u);
    REQUIRE(std::find(affected.begin(), affected.end(), 5000u) != affected.end());
}

CONTRACT_CASE("observable mutation invalidates function-dependent rates") {
    DependencyDagBuilder b;
    b.familyReads(7, Feature::observable(3));
    b.familyReads(8, Feature::parameter(2));
    auto dag = b.build();
    REQUIRE_EQ(dag.affectedBy(Mutation::observableChanged(3)), std::vector<FamilyId>({7}));
}

CONTRACT_CASE("dependency output is deduplicated") {
    DependencyDagBuilder b;
    b.familyReads(4, Feature::siteBound(0, 1));
    b.familyReads(4, Feature::siteFree(0, 1));
    auto dag = b.build();
    auto affected = dag.affectedBy(Mutation::bind({0,1},{1,1}));
    REQUIRE_EQ(affected.size(), 1u);
    REQUIRE_EQ(affected[0], 4u);
}

CONTRACT_CASE("dependency DAG result order is deterministic") {
    DependencyDagBuilder b;
    for (FamilyId f : {9u, 2u, 20u, 1u, 7u}) b.familyReads(f, Feature::siteBound(0, 0));
    auto dag = b.build();
    REQUIRE_EQ(dag.affectedBy(Mutation::unbind({0,0},{1,0})),
               std::vector<FamilyId>({1,2,7,9,20}));
}

CONTRACT_CASE("scheduler exact total equals sum of all channels") {
    AdaptiveScheduler s;
    s.reset({3, 2, 4});
    double sum = 0.0;
    for (std::size_t f = 0; f < 3; ++f)
        for (std::size_t c = 0; c < s.channels(f); ++c) {
            const double a = 0.25 + f + c * 0.125;
            s.set(f, c, a); sum += a;
        }
    REQUIRE_NEAR(s.total(), sum, 1e-12);
}

CONTRACT_CASE("zero-propensity channels are never selected") {
    AdaptiveScheduler s;
    s.reset({100});
    for (int i = 0; i < 100; ++i) s.set(0, i, i == 57 ? 3.0 : 0.0);
    for (int k = 0; k < 1000; ++k) {
        auto ch = s.sample((k + 0.5) / 1000.0 * s.total());
        REQUIRE_EQ(ch.family, 0u);
        REQUIRE_EQ(ch.channel, 57u);
    }
}

CONTRACT_CASE("sampling boundaries obey half-open cumulative intervals") {
    AdaptiveScheduler s;
    s.reset({3});
    s.set(0,0,1.0); s.set(0,1,2.0); s.set(0,2,4.0);
    REQUIRE_EQ(s.sample(0.0).channel, 0u);
    REQUIRE_EQ(s.sample(0.999999999).channel, 0u);
    REQUIRE_EQ(s.sample(1.0).channel, 1u);
    REQUIRE_EQ(s.sample(2.999999999).channel, 1u);
    REQUIRE_EQ(s.sample(3.0).channel, 2u);
    REQUIRE_EQ(s.sample(6.999999999).channel, 2u);
}

CONTRACT_CASE("scheduler rejects negative NaN and infinite propensities") {
    AdaptiveScheduler s; s.reset({1});
    REQUIRE_THROWS_AS(s.set(0,0,-1.0), SchedulerError);
    REQUIRE_THROWS_AS(s.set(0,0,std::numeric_limits<double>::infinity()), SchedulerError);
    REQUIRE_THROWS_AS(s.set(0,0,std::numeric_limits<double>::quiet_NaN()), SchedulerError);
}

CONTRACT_CASE("scheduler local update leaves unrelated family totals byte-identical") {
    AdaptiveScheduler s; s.reset({2,2,2});
    for (std::size_t f=0; f<3; ++f) for(std::size_t c=0;c<2;++c) s.set(f,c,1+f+c);
    const auto before0 = s.familySnapshot(0);
    const auto before2 = s.familySnapshot(2);
    s.set(1, 1, 99.0);
    REQUIRE_EQ(s.familySnapshot(0), before0);
    REQUIRE_EQ(s.familySnapshot(2), before2);
}

CONTRACT_CASE("adaptive scheduler may switch representation without changing sample mapping") {
    AdaptiveScheduler dense;
    AdaptiveScheduler sparse;
    dense.reset({10000}, SchedulerRepresentation::DenseFenwick);
    sparse.reset({10000}, SchedulerRepresentation::SparseActive);
    for (std::size_t i=0;i<10000;++i) {
        double a = (i % 997 == 0) ? (1.0 + i * 0.001) : 0.0;
        dense.set(0,i,a); sparse.set(0,i,a);
    }
    REQUIRE_NEAR(dense.total(), sparse.total(), 0.0);
    for (int k=0;k<10000;++k) {
        double x = (k + 0.123) / 10000.0 * dense.total();
        REQUIRE_EQ(dense.sample(x), sparse.sample(x));
    }
}

CONTRACT_CASE("bulk dependency repair is equivalent to individual updates") {
    AdaptiveScheduler a, b;
    a.reset({100}); b.reset({100});
    for (int i=0;i<100;++i) { a.set(0,i,1.0); b.set(0,i,1.0); }
    std::vector<ChannelUpdate> updates;
    for (int i=0;i<100;i+=3) updates.push_back({0, static_cast<std::size_t>(i), 2.0+i});
    for (auto& u : updates) a.set(u.family,u.channel,u.propensity);
    b.apply(updates);
    REQUIRE_EQ(a.snapshot(), b.snapshot());
}

CONTRACT_CASE("random scheduler selection matches linear reference oracle") {
    std::mt19937_64 rng(99);
    for (int trial=0; trial<100; ++trial) {
        const std::size_t n = 1 + rng()%500;
        AdaptiveScheduler s; s.reset({n});
        std::vector<double> a(n); double total=0;
        for (std::size_t i=0;i<n;++i) { a[i]=(rng()%1000)/100.0; s.set(0,i,a[i]); total+=a[i]; }
        if (total == 0) continue;
        for (int draw=0; draw<100; ++draw) {
            const double target = (static_cast<double>(rng()) / std::numeric_limits<std::uint64_t>::max()) * std::nextafter(total,0.0);
            double acc=0; std::size_t ref=0;
            for (; ref<n; ++ref) { acc += a[ref]; if (target < acc) break; }
            REQUIRE_EQ(s.sample(target).channel, ref);
        }
    }
}

CONTRACT_MAIN("dependency-scheduler")
#else
#error "RED CONTRACT: implement dependency_dag.hpp and adaptive_scheduler.hpp"
#endif
