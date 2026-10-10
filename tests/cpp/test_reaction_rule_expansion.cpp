#include <catch2/catch_test_macros.hpp>
#include <stdexcept>
#include <string>
#include <utility>

#include "parser/BNGAstVisitor.hpp"
#include "engine/NetworkGenerator.hpp"

using namespace bng;

static std::unique_ptr<ast::Model> parseModel(const std::string& bngl) {
    return parser::parseModel(bngl);
}

static std::unique_ptr<ast::Model> modelWithMaxIter(const std::string& option) {
    return parseModel(R"(
begin molecule types
    A(s~0~1~2)
end molecule types
begin seed species
    A(s~0) 1
end seed species
begin reaction rules
    r01: A(s~0) -> A(s~1) 1
    r12: A(s~1) -> A(s~2) 1
end reaction rules
begin actions
    generate_network({max_iter=>)" + option + R"(,overwrite=>1})
end actions
)");
}

TEST_CASE("Rule expansion: execution caches are independent", "[ReactionRule]") {
    auto model = parseModel(R"(
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin reaction rules
    A() -> B() 1
end reaction rules
)"
    );

    const auto& rule = model->getReactionRules().front();
    ast::SpeciesList species;
    species.add(ast::Species(
        ast::SpeciesGraph(model->getSeedSpecies().front().getGraph()), 1.0));

    auto firstState = rule.createExecutionState();
    auto secondState = rule.createExecutionState();
    ast::RxnList firstReactions;
    ast::RxnList secondReactions;
    const auto first = rule.expandRule(species, firstReactions, 0, *firstState, {}, 1, model.get());
    const auto independent = rule.expandRule(species, secondReactions, 0, *secondState, {}, 1, model.get());

    REQUIRE(first == 1);
    REQUIRE(independent == 1);
}

TEST_CASE("generate_network max_iter is compiled as a qualified typed option") {
    const auto compiledValue = [](const std::string& expression) {
        auto model = modelWithMaxIter(expression);
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto& action = generator.document().protocol().actions.front();
        REQUIRE(action.generateNetworkOptions.has_value());
        CHECK(action.arguments.at("max_iter") == expression);
        CHECK_FALSE(action.generateNetworkOptions->maxIterationsDiagnostic.has_value());
        REQUIRE(action.generateNetworkOptions->maxIterations.has_value());
        return *action.generateNetworkOptions->maxIterations;
    };

    CHECK(compiledValue("1+1") == 2);
    CHECK(compiledValue("2.5") == 2);
    CHECK(compiledValue("(1+1)*2") == 4);
    CHECK(compiledValue("1e2") == 100);
    CHECK(compiledValue("2**3") == 8);

    for (const auto& expression : {"0", "-1", "0.5", "2^3", "2**3**2",
                                   "(1/0)**0", "(1e308*1e308)**0",
                                   "-2**2", "(-2)**2", "iters", "exp(2)", "e",
                                   "9223372036854775808", "1e309"}) {
        INFO("max_iter expression: " << expression);
        auto model = modelWithMaxIter(expression);
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto& action = generator.document().protocol().actions.front();
        REQUIRE(action.generateNetworkOptions.has_value());
        CHECK_FALSE(action.generateNetworkOptions->maxIterations.has_value());
        REQUIRE(action.generateNetworkOptions->maxIterationsDiagnostic.has_value());
        CHECK(action.generateNetworkOptions->maxIterationsDiagnostic->message.find("max_iter") !=
              std::string::npos);
    }
}

TEST_CASE("BNGL network generation uses typed max_iter and explicit native overrides") {
    auto defaultModel = parseModel(R"(
begin molecule types
    A(s~0~1~2)
end molecule types
begin seed species
    A(s~0) 1
end seed species
begin reaction rules
    r01: A(s~0) -> A(s~1) 1
    r12: A(s~1) -> A(s~2) 1
end reaction rules
)");
    REQUIRE(defaultModel != nullptr);
    engine::NetworkGenerator defaultGenerator(*defaultModel);
    const auto defaultNetwork = defaultGenerator.generate({});
    REQUIRE(defaultNetwork.species.size() == 3);
    REQUIRE(defaultNetwork.reactions.size() == 2);

    auto twoPassModel = modelWithMaxIter("1+1");
    REQUIRE(twoPassModel != nullptr);
    engine::NetworkGenerator twoPassGenerator(*twoPassModel);
    const auto twoPassNetwork = twoPassGenerator.generate({});
    REQUIRE(twoPassNetwork.species.size() == 3);
    REQUIRE(twoPassNetwork.reactions.size() == 2);

    auto onePassModel = modelWithMaxIter("1");
    REQUIRE(onePassModel != nullptr);
    engine::NetworkGenerator onePassGenerator(*onePassModel);
    const auto onePassNetwork = onePassGenerator.generate({});
    REQUIRE(onePassNetwork.species.size() == 2);
    REQUIRE(onePassNetwork.reactions.size() == 1);

    auto invalidProtocolModel = modelWithMaxIter("iters");
    REQUIRE(invalidProtocolModel != nullptr);
    engine::NetworkGenerator invalidGenerator(*invalidProtocolModel);
    try {
        (void)invalidGenerator.generate({});
        FAIL("invalid BNGL max_iter must fail before network generation");
    } catch (const std::runtime_error& error) {
        CHECK(std::string(error.what()).find("max_iter") != std::string::npos);
    }

    // This is the same native entry point used by the direct Python binding:
    // an explicit numeric override must not decode the BNGL protocol value.
    const auto overriddenNetwork = invalidGenerator.generateNative(2);
    REQUIRE(overriddenNetwork.species.size() == 3);
    REQUIRE(overriddenNetwork.reactions.size() == 2);
}

TEST_CASE("Rule expansion: pattern metadata survives reinitialization and move", "[ReactionRule]") {
    // Source-derived from akutuva21/bionetgen commit 7ee2db11: immutable
    // pattern metadata is rebuilt on initialize() and must survive moving a
    // fully initialized rule into the owning model before expansion.
    auto model = parseModel(R"(
begin parameters
    kf 1.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 100
end seed species
begin reaction rules
    A() -> B() kf
end reaction rules
)");

    auto rule = std::move(model->getReactionRules().front());
    model->getReactionRules().clear();
    rule.initialize();
    model->addReactionRule(std::move(rule));

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(5);

    REQUIRE(network.species.size() == 2);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Rule expansion: simple binding A + B -> AB", "[ReactionRule]") {
    auto model = parseModel(R"(
begin parameters
    kf 1.0
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 100
    B(a) 100
end seed species
begin observables
    Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
    A(b) + B(a) -> A(b!1).B(a!1) kf
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() == 3);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Rule expansion: plain deletion splitting a complex yields no reaction", "[ReactionRule]") {
    // BNG2 build_reaction returns undef when a molecule deletion without the
    // DeleteMolecules modifier would leave more fragments than product
    // patterns. ComplexDegradation Rule04 (A(b!1).B(a!1) -> A(b)) fires on the
    // dimer but must not fire on the trimer, where deleting B would orphan C.
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b)
    B(a,c)
    C(b)
end molecule types
begin seed species
    A(b!1).B(a!1,c) 1
    A(b!1).B(a!1,c!2).C(b!2) 1
end seed species
begin reaction rules
    Rule04: A(b!1).B(a!1) -> A(b) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Rule expansion: null self-loop reactions are pruned like BNG2", "[ReactionRule]") {
    // BNG2 RxnList.pm drops reactions whose reactant and product multisets
    // are identical (Hawse_full: 88 reactions, not 176). A wildcard rule
    // matching a species already in the target state yields no reaction.
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(s~U~P)
end molecule types
begin seed species
    A(s~U) 1
end seed species
begin reaction rules
    R: A(s) -> A(s~U) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.reactions.size() == 0);
}

TEST_CASE("Rule expansion: multi-type reactant pattern requires every molecule type", "[ReactionRule]") {
    auto model = parseModel(R"(
begin molecule types
    A()
    B()
    C()
end molecule types
begin seed species
    A().B() 1
    A() 1
end seed species
begin reaction rules
    A().B() -> C() 1
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(5);

    REQUIRE(network.species.size() == 3);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Rule expansion: DeleteMolecules degradation", "[ReactionRule]") {
    auto model = parseModel(R"(
begin parameters
    kd 0.1
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b!1).B(a!1) 100
end seed species
begin reaction rules
    A(b!1).B(a!1) -> B(a) kd DeleteMolecules
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() >= 2);
    REQUIRE(network.reactions.size() >= 1);
}

TEST_CASE("Rule expansion: deleting a bound molecule preserves a free site", "[ReactionRule]") {
    // BNG2 serializes an unbound component without an edge marker.  A
    // DeleteMolecules product must therefore remain the same species as the
    // independently seeded BNG2-equivalent graph, even when the deleted bond
    // was the component's only explicit internal unbound marker.
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    DNA(p1,p2)
    P1(dna)
    TF(d,dna)
    Sink()
end molecule types
begin seed species
    DNA(p1!1!2,p2).TF(d!3,dna!2).TF(d!3,dna!1) 1
    DNA(p1!1!2,p2!4).P1(dna!4).TF(d!3,dna!1).TF(d!3,dna!2) 1
end seed species
begin reaction rules
    P1 -> Sink() k DeleteMolecules
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(4);

    std::size_t targetCount = 0;
    for (std::size_t index = 0; index < network.species.size(); ++index) {
        const auto text = network.species.get(index).getSpeciesGraph().toString();
        REQUIRE_FALSE(text.empty());
        if (text.find("DNA(p1!1!2,p2)") == 0 && text.find("TF(") != std::string::npos &&
            text.find("P1(") == std::string::npos) {
            ++targetCount;
        }
    }
    REQUIRE(targetCount == 1);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Rule expansion: bidirectional rule decomposition", "[ReactionRule]") {
    auto model = parseModel(R"(
begin parameters
    kf 1.0
    kr 0.5
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 100
    B(a) 100
end seed species
begin reaction rules
    A(b) + B(a) <-> A(b!1).B(a!1) kf, kr
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() == 3);
    REQUIRE(network.reactions.size() == 2);
}

TEST_CASE("Rule expansion: reverse local-rate scope remains bound", "[ReactionRule]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(s~up~dn)
end molecule types
begin seed species
    A(s~dn) 1
    A(s~up) 1
end seed species
begin observables
    Molecules up A(s~up)
end observables
begin functions
    rate(z) = k + up(z)
end functions
begin reaction rules
    A%x(s~dn) <-> A%x(s~up) rate(x), rate(x)
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(4);

    REQUIRE(network.species.size() == 2);
    REQUIRE(network.reactions.size() == 2);

    bool sawDownContext = false;
    bool sawUpContext = false;
    for (const auto& reaction : network.reactions.all()) {
        const auto& rate = reaction.getRateLaw();
        sawDownContext = sawDownContext || rate.find("|local:up=0;") != std::string::npos;
        sawUpContext = sawUpContext || rate.find("|local:up=1;") != std::string::npos;
    }
    REQUIRE(sawDownContext);
    REQUIRE(sawUpContext);
}

TEST_CASE("Rule expansion: MatchOnce modifier", "[ReactionRule]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b,b)
    B(a)
end molecule types
begin seed species
    A(b,b) 100
    B(a) 200
end seed species
begin reaction rules
    A(b) + B(a) -> A(b!1).B(a!1) k MatchOnce
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.reactions.size() >= 1);
}

TEST_CASE("generate_network max_agg is numeric and filters generated products only") {
    const auto generateWithMaxAgg = [](const std::string& maxAgg) {
        auto model = parseModel(R"(
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1
end seed species
begin reaction rules
  bind: A(b) + A(b) -> A(b!1).A(b!1) 1
end reaction rules
end model

generate_network({overwrite=>1,max_iter=>3,max_agg=>)" + maxAgg + R"(})
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        return generator.generate({});
    };

    const auto expressionBound = generateWithMaxAgg("1+1");
    CHECK(expressionBound.species.size() == 2);
    CHECK(expressionBound.reactions.size() == 1);

    const auto fractionalBelowProductSize = generateWithMaxAgg("1.5");
    CHECK(fractionalBelowProductSize.species.size() == 1);
    CHECK(fractionalBelowProductSize.reactions.size() == 0);

    const auto fractionalAboveProductSize = generateWithMaxAgg("2.5");
    CHECK(fractionalAboveProductSize.species.size() == 2);
    CHECK(fractionalAboveProductSize.reactions.size() == 1);

    const auto negativeBound = generateWithMaxAgg("-1");
    CHECK(negativeBound.species.size() == 1);
    CHECK(negativeBound.reactions.size() == 0);

    auto boundaryModel = parseModel(R"(
begin model
begin molecule types
  A(b)
  X(b)
  Y(b)
  Z(b)
end molecule types
begin seed species
  A(b!1!2).A(b!1).A(b!2) 1
  X(b) 1
  Y(b) 1
end seed species
begin reaction rules
  trimer: X(b) + X(b) + X(b) -> X(b!1).X(b!1!2).X(b!2) 1
  convert: Y(b) -> Z(b) 1
end reaction rules
end model

generate_network({overwrite=>1,max_iter=>3,max_agg=>2})
)");
    REQUIRE(boundaryModel != nullptr);
    engine::NetworkGenerator boundaryGenerator(*boundaryModel);
    const auto boundary = boundaryGenerator.generate({});
    REQUIRE(boundary.species.size() == 4);
    REQUIRE(boundary.reactions.size() == 1);

    bool retainedOverLimitSeed = false;
    bool rejectedOverLimitProduct = true;
    bool allowedOtherProduct = false;
    for (const auto& species : boundary.species.all()) {
        const auto& graph = species.getSpeciesGraph().toString();
        retainedOverLimitSeed = retainedOverLimitSeed ||
            graph == "A(b!1!2).A(b!1).A(b!2)";
        rejectedOverLimitProduct = rejectedOverLimitProduct &&
            graph != "X(b!1).X(b!1!2).X(b!2)";
        allowedOtherProduct = allowedOtherProduct || graph == "Z(b)";
    }
    CHECK(retainedOverLimitSeed);
    CHECK(rejectedOverLimitProduct);
    CHECK(allowedOtherProduct);
}

TEST_CASE("generate_network max_agg compiles finite numeric expressions and defers diagnostics") {
    const auto compileMaxAgg = [](const std::string& source) {
        auto model = parseModel(R"(
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1
end seed species
end model

generate_network({max_agg=>)" + source + R"(})
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        REQUIRE(generator.document().valid());
        const auto& action = generator.document().protocol().actions.front();
        REQUIRE(action.generateNetworkOptions.has_value());
        CHECK(action.arguments.at("max_agg") == source);
        return *action.generateNetworkOptions;
    };

    for (const auto& [source, expected] : std::vector<std::pair<std::string, double>>{
             {"1+1", 2.0}, {"2.5", 2.5}, {"1e2", 100.0}, {"-1", -1.0}}) {
        INFO("max_agg expression: " << source);
        const auto options = compileMaxAgg(source);
        CHECK_FALSE(options.maxAggregateDiagnostic.has_value());
        REQUIRE(options.maxAggregate.has_value());
        CHECK(*options.maxAggregate == expected);
    }

    for (const auto& source : {"unknown", "exp(2)", "1e309", "1/0", "\"2junk\""}) {
        INFO("max_agg expression: " << source);
        const auto options = compileMaxAgg(source);
        CHECK_FALSE(options.maxAggregate.has_value());
        REQUIRE(options.maxAggregateDiagnostic.has_value());
        CHECK(options.maxAggregateDiagnostic->message.find("max_agg") != std::string::npos);
        CHECK(options.maxAggregateDiagnostic->message.find(source) != std::string::npos);

        const std::string invalidBnglPrefix = R"(
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1
end seed species
end model

generate_network({max_agg=>)";
        auto invalidModel = parseModel(invalidBnglPrefix + source + "})\n");
        REQUIRE(invalidModel != nullptr);
        engine::NetworkGenerator invalidGenerator(*invalidModel);
        CHECK(invalidGenerator.document().valid());
        try {
            (void)invalidGenerator.generateNative(3);
            FAIL("invalid max_agg must fail when generation begins");
        } catch (const std::runtime_error& error) {
            CHECK(std::string(error.what()).find(source) != std::string::npos);
        }
    }
}

TEST_CASE("generate_network max_agg uses the first action that supplies the option") {
    auto model = parseModel(R"(
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1
end seed species
begin reaction rules
  bind: A(b) + A(b) -> A(b!1).A(b!1) 1
end reaction rules
end model

begin actions
  generate_network({max_iter=>1})
  generate_network({max_agg=>1})
end actions
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generate({});
    CHECK(network.species.size() == 1);
    CHECK(network.reactions.size() == 0);
}
