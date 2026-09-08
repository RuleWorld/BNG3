// RED CONTRACT: enable only after compile/dependency/DependencyGraph.hpp lands.
#include <algorithm>
#include <catch2/catch_test_macros.hpp>

#include "compile/dependency/DependencyGraph.hpp"

using namespace bng::compile::dependency;

TEST_CASE("state mutation invalidates only factors that depend on that state") {
    DependencyGraph graph;
    const SiteKey ax{"A", "x"};
    const SiteKey ay{"A", "y"};
    graph.addEnergyFactorDependency(0, ax, DependencyKind::State);
    graph.addEnergyFactorDependency(1, ay, DependencyKind::State);
    graph.addRuleDependency(10, 0);
    graph.addRuleDependency(11, 1);

    const auto affected = graph.affectedRules(MutationKey::state(ax));
    CHECK(affected == std::vector<std::size_t>{10});
}

TEST_CASE("bond mutation invalidates both endpoint-dependent factors") {
    DependencyGraph graph;
    const SiteKey ax{"A", "x"};
    const SiteKey by{"B", "y"};
    graph.addEnergyFactorDependency(3, ax, DependencyKind::Bond);
    graph.addEnergyFactorDependency(4, by, DependencyKind::Bond);
    graph.addRuleDependency(20, 3);
    graph.addRuleDependency(21, 4);

    const auto affected = graph.affectedRules(MutationKey::bond(ax, by));
    CHECK(affected == std::vector<std::size_t>{20, 21});
}

TEST_CASE("unresolved mutation triggers conservative full invalidation") {
    DependencyGraph graph;
    graph.registerRule(1);
    graph.registerRule(2);
    graph.registerRule(3);
    graph.markConservativeGlobalDependency();
    CHECK(graph.affectedRules(MutationKey::unknown()) ==
          std::vector<std::size_t>{1, 2, 3});
}

TEST_CASE("molecule deletion invalidates all factors involving that molecule type") {
    DependencyGraph graph;
    graph.addEnergyFactorDependency(0, {"A", "x"}, DependencyKind::State);
    graph.addEnergyFactorDependency(1, {"A", "y"}, DependencyKind::Bond);
    graph.addEnergyFactorDependency(2, {"B", "z"}, DependencyKind::State);
    graph.addRuleDependency(30, 0);
    graph.addRuleDependency(31, 1);
    graph.addRuleDependency(32, 2);

    CHECK(graph.affectedRules(MutationKey::deleteMolecule("A")) ==
          std::vector<std::size_t>{30, 31});
}
