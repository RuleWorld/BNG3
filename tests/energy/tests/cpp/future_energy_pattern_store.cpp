// RED CONTRACT: versioned compiled-plan cache.
#include <catch2/catch_test_macros.hpp>
#include "compile/energy/EnergyPatternStore.hpp"

using namespace bng::compile::energy;

TEST_CASE("binding plan cache is orientation-sensitive") {
    EnergyPatternStore store;
    store.addFactor(PatternDescriptor::parse("A(x!1,s~P).B(y!1)"), 1.0, "e");
    const auto& ab = store.bindingPlan("A", "x", "B", "y");
    const auto& ba = store.bindingPlan("B", "y", "A", "x");
    REQUIRE(ab.conditions().size() == 1);
    REQUIRE(ba.conditions().size() == 1);
    CHECK(ab.conditions()[0].reactantIndex == 0);
    CHECK(ba.conditions()[0].reactantIndex == 1);
}

TEST_CASE("adding a factor invalidates cached plans via store version") {
    EnergyPatternStore store;
    const auto version0 = store.version();
    store.addFactor(PatternDescriptor::parse("A(x!1).B(y!1)"), 1.0, "e1");
    CHECK(store.version() > version0);
    const auto first = store.bindingPlanRevision("A", "x", "B", "y");
    store.addFactor(PatternDescriptor::parse("A(x!1,s~P).B(y!1)"), 2.0, "e2");
    const auto second = store.bindingPlanRevision("A", "x", "B", "y");
    CHECK(second > first);
}

TEST_CASE("opaque factor forces conservative fallback for potentially overlapping center") {
    EnergyPatternStore store;
    store.addOpaqueFactor("legacy-unrepresentable");
    CHECK_FALSE(store.bindingPlan("A", "x", "B", "y").isExecutable());
}
