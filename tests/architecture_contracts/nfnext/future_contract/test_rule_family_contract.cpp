#include "contract_test.hpp"

#if __has_include("nfnext/family_compiler.hpp")
#include "nfnext/family_compiler.hpp"
#include "nfnext/nfir.hpp"
#include <algorithm>
#include <random>
using namespace nfnext;

static ExpandedRuleIR indexedRule(std::uint32_t i, double rate = 1.0) {
    ExpandedRuleIR r;
    r.id = i;
    r.name = "elongate_" + std::to_string(i);
    r.rate = rate;
    r.predicates.push_back(PredicateIR{PredicateKind::PositionEq, 0, 0, static_cast<std::int32_t>(i), 0});
    r.predicates.push_back(PredicateIR{PredicateKind::SiteStateEq, 0, 1, 3, 0});
    r.actions.push_back(ActionIR{ActionKind::MovePosition, 0, 0, 1, 0});
    return r;
}

CONTRACT_CASE("ten thousand translational rules collapse to one semantic family") {
    std::vector<ExpandedRuleIR> rules;
    for (std::uint32_t i = 0; i < 10000; ++i) rules.push_back(indexedRule(i));
    auto result = compileRuleFamilies(rules);
    REQUIRE_EQ(result.families.size(), 1u);
    REQUIRE_EQ(result.families[0].source_rules.size(), 10000u);
    REQUIRE(result.families[0].coordinate_parameterized);
}

CONTRACT_CASE("family recognition is semantic and does not require indexed names") {
    std::vector<ExpandedRuleIR> rules;
    for (std::uint32_t i = 0; i < 50; ++i) {
        auto r = indexedRule(i);
        r.name = "arbitrary_label_" + std::to_string(1000 - i);
        rules.push_back(r);
    }
    auto result = compileRuleFamilies(rules);
    REQUIRE_EQ(result.families.size(), 1u);
    REQUIRE(result.families[0].coordinate_parameterized);
}

CONTRACT_CASE("non-coordinate state values must never be normalized away") {
    auto a = indexedRule(10);
    auto b = indexedRule(11);
    b.predicates[1].value = 4;
    auto result = compileRuleFamilies({a, b});
    REQUIRE_EQ(result.families.size(), 2u);
}

CONTRACT_CASE("binding topology differences prevent family collapse") {
    auto a = indexedRule(10);
    auto b = indexedRule(11);
    b.predicates.push_back(PredicateIR{PredicateKind::SiteBound, 0, 2, 0, 0});
    auto result = compileRuleFamilies({a, b});
    REQUIRE_EQ(result.families.size(), 2u);
}

CONTRACT_CASE("action displacement differences prevent collapse") {
    auto a = indexedRule(10);
    auto b = indexedRule(11);
    b.actions[0].value = 2;
    auto result = compileRuleFamilies({a, b});
    REQUIRE_EQ(result.families.size(), 2u);
}

CONTRACT_CASE("per-coordinate rates are preserved exactly") {
    std::vector<ExpandedRuleIR> rules;
    for (std::uint32_t i = 0; i < 200; ++i) rules.push_back(indexedRule(i, 0.001 * (i + 1)));
    auto result = compileRuleFamilies(rules);
    REQUIRE_EQ(result.families.size(), 1u);
    REQUIRE_EQ(result.families[0].indexed_rates.size(), 200u);
    for (std::size_t i = 0; i < rules.size(); ++i)
        REQUIRE_NEAR(result.families[0].indexed_rates[i], rules[i].rate, 0.0);
}

CONTRACT_CASE("holes in coordinate domain remain explicit and cannot create ghost channels") {
    auto result = compileRuleFamilies({indexedRule(1), indexedRule(2), indexedRule(4), indexedRule(5)});
    REQUIRE_EQ(result.families.size(), 2u);
    REQUIRE_EQ(result.families[0].source_rules.size(), 2u);
    REQUIRE_EQ(result.families[1].source_rules.size(), 2u);
}

CONTRACT_CASE("family ordering preserves expanded-rule stochastic ordering contract") {
    std::vector<ExpandedRuleIR> rules = {indexedRule(50), indexedRule(51), indexedRule(3), indexedRule(4)};
    rules[0].id = 100; rules[1].id = 101; rules[2].id = 102; rules[3].id = 103;
    auto result = compileRuleFamilies(rules);
    REQUIRE_EQ(result.families.size(), 2u);
    REQUIRE_EQ(result.families[0].source_rules.front(), 100u);
    REQUIRE_EQ(result.families[1].source_rules.front(), 102u);
}

CONTRACT_CASE("family compiler does not collapse across rate-law class") {
    auto a = indexedRule(1);
    auto b = indexedRule(2);
    a.rate_law.kind = RateLawKind::Elementary;
    b.rate_law.kind = RateLawKind::Function;
    b.rate_law.expression = "k*Obs";
    auto result = compileRuleFamilies({a, b});
    REQUIRE_EQ(result.families.size(), 2u);
}

CONTRACT_CASE("stateSet membership must remain exact during collapse") {
    auto a = indexedRule(1);
    auto b = indexedRule(2);
    a.predicates.push_back(PredicateIR::stateSet(0, 3, {1, 2, 5}));
    b.predicates.push_back(PredicateIR::stateSet(0, 3, {1, 2, 5}));
    REQUIRE_EQ(compileRuleFamilies({a, b}).families.size(), 1u);
    b.predicates.back() = PredicateIR::stateSet(0, 3, {1, 2, 6});
    REQUIRE_EQ(compileRuleFamilies({a, b}).families.size(), 2u);
}

CONTRACT_CASE("connected-to and same-complex constraints remain structural") {
    auto a = indexedRule(1);
    auto b = indexedRule(2);
    a.pattern.molecularity.push_back(MolecularityConstraint::sameComplex(0, 1));
    b.pattern.molecularity.push_back(MolecularityConstraint::differentComplex(0, 1));
    REQUIRE_EQ(compileRuleFamilies({a, b}).families.size(), 2u);
}

CONTRACT_CASE("family compilation is deterministic under hash-map perturbation") {
    std::vector<ExpandedRuleIR> rules;
    for (std::uint32_t i = 0; i < 500; ++i) rules.push_back(indexedRule(i, 1 + (i % 7)));
    const auto expected = compileRuleFamilies(rules).semanticFingerprint();
    for (int rep = 0; rep < 30; ++rep) {
        auto copy = rules;
        for (auto& r : copy) {
            r.annotations.clear();
            r.annotations["z"] = "1";
            r.annotations["a"] = "2";
        }
        REQUIRE_EQ(compileRuleFamilies(copy).semanticFingerprint(), expected);
    }
}

CONTRACT_CASE("family compiler exposes an exact expansion oracle") {
    std::vector<ExpandedRuleIR> rules;
    for (std::uint32_t i = 100; i < 110; ++i) rules.push_back(indexedRule(i, i * 0.25));
    auto result = compileRuleFamilies(rules);
    auto expanded = expandFamilies(result.families);
    REQUIRE_EQ(expanded.size(), rules.size());
    for (std::size_t i = 0; i < rules.size(); ++i)
        REQUIRE(semanticRuleEqual(expanded[i], rules[i]));
}

CONTRACT_CASE("randomized collapse then expand is semantics-preserving") {
    std::mt19937_64 rng(12345);
    for (int trial = 0; trial < 200; ++trial) {
        std::vector<ExpandedRuleIR> rules;
        const int n = 1 + static_cast<int>(rng() % 200);
        const int base = static_cast<int>(rng() % 1000);
        for (int i = 0; i < n; ++i) {
            auto r = indexedRule(base + i, 0.1 + static_cast<double>(rng() % 1000) / 1000.0);
            if ((rng() % 17) == 0) r.predicates[1].value = 4;
            rules.push_back(r);
        }
        auto expanded = expandFamilies(compileRuleFamilies(rules).families);
        REQUIRE_EQ(expanded.size(), rules.size());
        for (std::size_t i = 0; i < rules.size(); ++i)
            REQUIRE(semanticRuleEqual(expanded[i], rules[i]));
    }
}

CONTRACT_CASE("collapse does not depend on human-readable names") {
    auto a = indexedRule(7); auto b = indexedRule(8);
    a.name = "foo"; b.name = "bar";
    auto x = compileRuleFamilies({a, b});
    a.name = "something"; b.name = "entirely-different";
    auto y = compileRuleFamilies({a, b});
    REQUIRE_EQ(x.semanticFingerprint(), y.semanticFingerprint());
}

CONTRACT_CASE("compiler records exact reasons for a rejected family merge") {
    auto a = indexedRule(7); auto b = indexedRule(8);
    b.actions[0].value = 3;
    FamilyCompileOptions opts; opts.explain_rejections = true;
    auto out = compileRuleFamilies({a, b}, opts);
    REQUIRE_EQ(out.families.size(), 2u);
    REQUIRE(!out.rejections.empty());
    REQUIRE(out.rejections[0].reason.find("action") != std::string::npos);
}

CONTRACT_MAIN("rule-family")
#else
#error "RED CONTRACT: implement semantic family compiler in nfnext/family_compiler.hpp"
#endif
