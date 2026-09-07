#include <algorithm>
#include <cmath>
#include <cstdint>
#include <string>
#include <vector>

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include "compile/CompiledModel.hpp"
#include "compile/CompiledRule.hpp"
#include "compile/energy/EnergyDeltaPlan.hpp"
#include "NFcore/energyPattern.hh"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("EnergyDeltaPlan evaluates conjunctive local factors") {
    using namespace bng::compile::energy;

    EnergyCondition c;
    c.kind = ConditionKind::Bond;
    c.reactantIndex = 0;
    c.moleculeType = "A";
    c.componentName = "c";
    c.expectedBound = true;
    c.partnerType = "C";
    c.partnerComponent = "x";

    EnergyCondition d = c;
    d.componentName = "d";
    d.partnerType = "D";

    std::vector<EnergyTerm> terms {
        {1.0, std::uint64_t{1} << 0, 1},
        {2.0, std::uint64_t{1} << 1, 2},
        {4.0, (std::uint64_t{1} << 0) | (std::uint64_t{1} << 1), 3},
    };
    auto plan = EnergyDeltaPlan::factorized(0.5, {c, d}, terms);
    REQUIRE(plan.has_value());
    REQUIRE(plan->isFactorized());
    CHECK(plan->singleReactantIndex() == 0);
    CHECK(plan->tryDeltaG(0).value() == Catch::Approx(0.5));
    CHECK(plan->tryDeltaG(1).value() == Catch::Approx(1.5));
    CHECK(plan->tryDeltaG(2).value() == Catch::Approx(2.5));
    CHECK(plan->tryDeltaG(3).value() == Catch::Approx(7.5));

    const auto factors = plan->buildArrheniusTable(0.5, 1.0, true, 8);
    REQUIRE(factors.has_value());
    REQUIRE(factors->size() == 4);
    CHECK((*factors)[3] == Catch::Approx(std::exp(-3.75)));
}

TEST_CASE("EnergyFunction compiles binding context into EnergyDeltaPlan") {
    NFcore::EnergyFunction energy(0.5, 1.0);

    NFcore::EnergyPatternInfo pattern;
    pattern.id = "A_context_B";
    pattern.energyValue = 2.0;

    NFcore::EpMolecule moleculeA;
    moleculeA.typeName = "A";
    moleculeA.xmlId = "a";
    moleculeA.components.push_back({"b", "b", true, ""});
    moleculeA.components.push_back({"c", "c", true, ""});

    NFcore::EpMolecule moleculeB;
    moleculeB.typeName = "B";
    moleculeB.xmlId = "b";
    moleculeB.components.push_back({"a", "a", true, ""});

    NFcore::EpMolecule moleculeC;
    moleculeC.typeName = "C";
    moleculeC.xmlId = "c";
    moleculeC.components.push_back({"x", "x", true, ""});

    pattern.molecules = {moleculeA, moleculeB, moleculeC};
    pattern.bonds.push_back({0, 0, 1, 0});
    pattern.bonds.push_back({0, 1, 2, 0});
    energy.addEnergyPattern(pattern);

    const auto plan = energy.compileBindingDeltaPlan("A", "b", "B", "a");
    REQUIRE(plan.isFactorized());
    CHECK(plan.baseEnergy() == Catch::Approx(0.0));
    REQUIRE(plan.conditions().size() == 1);
    CHECK(plan.conditions()[0].reactantIndex == 0);
    CHECK(plan.conditions()[0].moleculeType == "A");
    CHECK(plan.conditions()[0].componentName == "c");
    CHECK(plan.conditions()[0].partnerType == "C");
    CHECK(plan.conditions()[0].partnerComponent == "x");
    REQUIRE(plan.terms().size() == 1);
    CHECK(plan.terms()[0].energyValue == Catch::Approx(2.0));
    CHECK(plan.terms()[0].conditionMask == 1);
    CHECK(plan.tryDeltaG(0).value() == Catch::Approx(0.0));
    CHECK(plan.tryDeltaG(1).value() == Catch::Approx(2.0));

    // Existing NFsim compatibility API must be a view of the same plan.
    NFcore::EnergyBindingContext legacy;
    REQUIRE(energy.getBindingContext("A", "b", "B", "a", legacy));
    CHECK(legacy.baseEnergy == Catch::Approx(plan.baseEnergy()));
    REQUIRE(legacy.conditionalTerms.size() == plan.terms().size());
    CHECK(legacy.conditionalTerms[0].energyValue ==
          Catch::Approx(plan.terms()[0].energyValue));
    CHECK(legacy.conditionalTerms[0].conditionMask == plan.terms()[0].conditionMask);
}

TEST_CASE("EnergyFunction compiles signed state-change delta plan") {
    NFcore::EnergyFunction energy(0.5, 1.0);

    auto makePattern = [](const std::string& id, const std::string& state, double value) {
        NFcore::EnergyPatternInfo pattern;
        pattern.id = id;
        pattern.energyValue = value;

        NFcore::EpMolecule moleculeM;
        moleculeM.typeName = "M";
        moleculeM.xmlId = id + "_m";
        moleculeM.components.push_back({"s", "", false, state});
        moleculeM.components.push_back({"c", id + "_c", true, ""});

        NFcore::EpMolecule moleculeC;
        moleculeC.typeName = "C";
        moleculeC.xmlId = id + "_c";
        moleculeC.components.push_back({"x", id + "_m", true, ""});

        pattern.molecules = {moleculeM, moleculeC};
        pattern.bonds.push_back({0, 1, 1, 0});
        return pattern;
    };

    energy.addEnergyPattern(makePattern("up", "up", 2.0));
    energy.addEnergyPattern(makePattern("down", "down", 0.5));

    const auto plan = energy.compileStateChangeDeltaPlan("M", "s", "down", "up");
    REQUIRE(plan.isFactorized());
    REQUIRE(plan.conditions().size() == 1);
    REQUIRE(plan.terms().size() == 2);
    CHECK(plan.tryDeltaG(0).value() == Catch::Approx(0.0));
    CHECK(plan.tryDeltaG(1).value() == Catch::Approx(1.5));
}

TEST_CASE("CompiledRateLaw types existing Arrhenius syntax without changing it") {
    const auto expression = bng::parser::parseExpression("Arrhenius(phi,Ea)");
    const auto rate = bng::compile::CompiledRateLaw::compile(expression);
    CHECK(rate.kind == bng::compile::RateLawKind::ArrheniusEnergy);
    CHECK(rate.isEnergyCoupled());
    CHECK(rate.arguments.size() == 2);
}

TEST_CASE("CompiledModel derives a mutation signature from ReactionRule operations") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 1
    B(a) 1
end seed species
begin reaction rules
    bind: A(b) + B(a) -> A(b!1).B(a!1) 1
end reaction rules
)BNG");
    REQUIRE(model != nullptr);

    const bng::compile::CompiledModel compiled(*model);
    REQUIRE(compiled.rules().size() == 1);
    const auto& rule = compiled.rules().front();
    CHECK(rule.name() == model->getReactionRules().front().getRuleName());
    CHECK(rule.label() == "bind:");

    const bool hasAddBond = std::any_of(
        rule.mutations().begin(), rule.mutations().end(), [](const auto& mutation) {
            return mutation.kind == bng::compile::MutationKind::AddBond;
        });
    CHECK(hasAddBond);
    CHECK(rule.affectedComponents().size() == 2);
}
