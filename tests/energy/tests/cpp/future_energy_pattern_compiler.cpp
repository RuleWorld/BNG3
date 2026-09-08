// RED CONTRACT: generalized energy-pattern compiler.
#include <algorithm>
#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include "compile/energy/EnergyPatternCompiler.hpp"
#include "compile/PatternDescriptor.hpp"

using namespace bng::compile::energy;

TEST_CASE("shared context predicate is deduplicated across energy factors") {
    EnergyPatternCompiler compiler;
    compiler.addFactor(PatternDescriptor::parse("A(b!1,c!2).B(a!1).C(x!2)"), 1.0, "e1");
    compiler.addFactor(PatternDescriptor::parse("A(b!1,c!2,d!3).B(a!1).C(x!2).D(x!3)"), 2.0, "e2");

    auto plan = compiler.compileBinding("A", "b", "B", "a");
    REQUIRE(plan.isFactorized());
    // A.c--C.x appears in both factors but must occupy one predicate bit.
    const auto count_c = std::count_if(plan.conditions().begin(), plan.conditions().end(), [](const auto& c) {
        return c.moleculeType == "A" && c.componentName == "c";
    });
    CHECK(count_c == 1);
}

TEST_CASE("binding context on reactant one retains reactant orientation") {
    EnergyPatternCompiler compiler;
    compiler.addFactor(PatternDescriptor::parse("A(b!1).B(a!1,c~P)"), 2.0, "e");
    auto plan = compiler.compileBinding("A", "b", "B", "a");
    REQUIRE(plan.isFactorized());
    REQUIRE(plan.conditions().size() == 1);
    CHECK(plan.conditions()[0].reactantIndex == 1);
    CHECK(plan.conditions()[0].expectedState == "P");
}

TEST_CASE("mixed-reactant context compiles without materializing boolean combinations") {
    EnergyPatternCompiler compiler;
    compiler.addFactor(PatternDescriptor::parse("A(b!1,s~P).B(a!1,t~P)"), 3.0, "mixed");
    auto plan = compiler.compileBinding("A", "b", "B", "a");
    REQUIRE(plan.isFactorized());
    CHECK_FALSE(plan.singleReactantIndex().has_value());
    REQUIRE(plan.conditions().size() == 2);
    CHECK(plan.tryDeltaG(0b11).value() == Catch::Approx(3.0));
    CHECK(plan.tryDeltaG(0b01).value() == Catch::Approx(0.0));
}

TEST_CASE("one-hop bonded-partner state is represented explicitly") {
    EnergyPatternCompiler compiler;
    compiler.addFactor(PatternDescriptor::parse("A(b!1,c!2).B(a!1).C(x!2,s~P)"), 4.0, "partner_state");
    auto plan = compiler.compileBinding("A", "b", "B", "a");
    REQUIRE(plan.isFactorized());
    const auto partner = std::find_if(plan.conditions().begin(), plan.conditions().end(), [](const auto& c) {
        return c.partnerType == "C" && c.expectedState == "P";
    });
    REQUIRE(partner != plan.conditions().end());
}

TEST_CASE("correlated two-hop topology fails closed to materialization") {
    EnergyPatternCompiler compiler;
    compiler.addFactor(PatternDescriptor::parse(
        "A(b!1,c!2).B(a!1).C(x!2,y!3).D(z!3,s~P)"), 5.0, "two_hop");
    auto plan = compiler.compileBinding("A", "b", "B", "a");
    CHECK_FALSE(plan.isExecutable());
}

TEST_CASE("state transition uses signed to-minus-from energy contributions") {
    EnergyPatternCompiler compiler;
    compiler.addFactor(PatternDescriptor::parse("A(s~U,c!1).C(x!1)"), 0.5, "U");
    compiler.addFactor(PatternDescriptor::parse("A(s~P,c!1).C(x!1)"), 2.0, "P");
    auto plan = compiler.compileStateChange("A", "s", "U", "P");
    REQUIRE(plan.isFactorized());
    CHECK(plan.tryDeltaG(1).value() == Catch::Approx(1.5));
}

TEST_CASE("63 independent predicates fit bitmask representation but 64 fail closed") {
    auto makeCompiler=[](int n){
        EnergyPatternCompiler compiler;
        for(int i=0;i<n;++i){
            compiler.addFactor(PatternDescriptor::parse(
                "A(x!1,c"+std::to_string(i)+"!2).B(y!1).C"+std::to_string(i)+"(z!2)"),
                1.0,"e"+std::to_string(i));
        }
        return compiler;
    };
    auto c63=makeCompiler(63); auto p63=c63.compileBinding("A","x","B","y");
    CHECK(p63.isFactorized());
    CHECK(p63.conditions().size()==63);
    auto c64=makeCompiler(64); auto p64=c64.compileBinding("A","x","B","y");
    CHECK_FALSE(p64.isExecutable());
}

TEST_CASE("deduplicated predicate retains provenance from every contributing factor") {
    EnergyPatternCompiler compiler;
    compiler.addFactor(PatternDescriptor::parse("A(x!1,c!2).B(y!1).C(z!2)"),1,"e1");
    compiler.addFactor(PatternDescriptor::parse("A(x!1,c!2,d~P).B(y!1).C(z!2)"),2,"e2");
    auto p=compiler.compileBinding("A","x","B","y");
    REQUIRE(p.isFactorized());
    const auto it=std::find_if(p.conditions().begin(),p.conditions().end(),[](const auto& c){return c.componentName=="c";});
    REQUIRE(it!=p.conditions().end());
    CHECK(it->sourceFactorIndices.size()==2);
}
