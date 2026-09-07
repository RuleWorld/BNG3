// RED CONTRACT: randomized dependency graph must never produce a false negative.
#include <random>
#include <set>
#include <catch2/catch_test_macros.hpp>
#include "compile/dependency/DependencyGraph.hpp"

TEST_CASE("randomized dependency index is a superset of literal dependency scan") {
    using namespace bng::compile::dependency;
    std::mt19937 rng(123456);
    for (int trial=0;trial<2000;++trial) {
        DependencyGraph g;
        struct F { SiteKey site; DependencyKind kind; std::size_t rule; };
        std::vector<F> literal;
        for (std::size_t i=0;i<50;++i) {
            SiteKey s{std::string(1,char('A'+(rng()%4))), "s"+std::to_string(rng()%8)};
            auto kind=(rng()%2)?DependencyKind::State:DependencyKind::Bond;
            g.addEnergyFactorDependency(i,s,kind);
            g.addRuleDependency(100+i,i);
            literal.push_back({s,kind,100+i});
        }
        SiteKey changed{std::string(1,char('A'+(rng()%4))), "s"+std::to_string(rng()%8)};
        auto mutation=MutationKey::state(changed);
        const auto indexed=g.affectedRules(mutation);
        std::set<std::size_t> got(indexed.begin(),indexed.end());
        for (const auto& f:literal) {
            if (f.kind==DependencyKind::State && f.site==changed)
                CHECK(got.count(f.rule)==1);
        }
    }
}
