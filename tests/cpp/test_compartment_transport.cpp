#include <catch2/catch_test_macros.hpp>

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <cmath>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>

#include "ast/Parameter.hpp"
#include "parser/BNGAstVisitor.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"

using namespace bng;

static std::unique_ptr<ast::Model> parseModel(const std::string& bngl) {
    return parser::parseModel(bngl);
}

TEST_CASE("Compartment transport: endocytosis PM -> EM", "[Compartment]") {
    auto model = parseModel(R"(
begin parameters
    k_endo 0.1
end parameters
begin compartments
    EC 3 1.0
    PM 2 1.0 EC
    CP 3 1.0 PM
    EM 2 1.0 CP
    EN 3 1.0 EM
end compartments
begin molecule types
    R(l)
end molecule types
begin seed species
    @PM:R(l) 100
end seed species
begin reaction rules
    @PM:R(l) -> @EM:R(l) k_endo
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() == 2);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Concurrent compartment contexts do not cross-contaminate",
          "[Compartment][Concurrency]") {
    auto adjacentModel = parseModel(R"(
begin parameters
    kon 1.0e-4
end parameters
begin compartments
    EC 3 1
    mem 2 1 EC
end compartments
begin molecule types
    Lig(Site0)
    Receptor(Site0~U)
end molecule types
begin seed species
    @mem:Receptor(Site0~U) 1
    @EC:Lig(Site0) 1
end seed species
begin reaction rules
    @EC:Lig(Site0) + @mem:Receptor(Site0~U) -> @mem:Lig(Site0!1).Receptor(Site0~U!1) kon
end reaction rules
)");
    auto parentlessModel = parseModel(R"(
begin parameters
    kon 1.0e-4
end parameters
begin compartments
    EC 3 1
    mem 2 1
end compartments
begin molecule types
    Lig(Site0)
    Receptor(Site0~U)
end molecule types
begin seed species
    @mem:Receptor(Site0~U) 1
    @EC:Lig(Site0) 1
end seed species
begin reaction rules
    @EC:Lig(Site0) + @mem:Receptor(Site0~U) -> @mem:Lig(Site0!1).Receptor(Site0~U!1) kon
end reaction rules
)");
    REQUIRE(adjacentModel);
    REQUIRE(parentlessModel);
    const bng::compile::Document adjacentDocument(*adjacentModel);
    const bng::compile::Document parentlessDocument(*parentlessModel);

    engine::NetworkGenerator adjacentGenerator(adjacentDocument);
    engine::NetworkGenerator parentlessGenerator(parentlessDocument);
    CHECK(adjacentGenerator.generateNative(1).reactions.size() == 1);
    CHECK(parentlessGenerator.generateNative(1).reactions.size() == 0);

    std::mutex mutex;
    std::condition_variable condition;
    std::size_t waiting = 0;
    std::size_t phase = 0;
    const auto synchronize = [&] {
        std::unique_lock<std::mutex> lock(mutex);
        const auto observedPhase = phase;
        if (++waiting == 2) {
            waiting = 0;
            ++phase;
            condition.notify_all();
        } else {
            condition.wait(lock, [&] { return phase != observedPhase; });
        }
    };
    std::atomic<std::size_t> adjacentFailures{0};
    std::atomic<std::size_t> parentlessFailures{0};
    const auto repeat = [&](engine::NetworkGenerator& generator,
                            std::size_t expectedReactions,
                            std::atomic<std::size_t>& failures) {
        for (int i = 0; i < 128; ++i) {
            synchronize();
            if (generator.generateNative(1).reactions.size() != expectedReactions) {
                failures.fetch_add(1, std::memory_order_relaxed);
            }
            synchronize();
        }
    };

    std::thread adjacentThread(repeat, std::ref(adjacentGenerator), 1,
                               std::ref(adjacentFailures));
    std::thread parentlessThread(repeat, std::ref(parentlessGenerator), 0,
                                 std::ref(parentlessFailures));
    adjacentThread.join();
    parentlessThread.join();

    CHECK(adjacentFailures == 0);
    CHECK(parentlessFailures == 0);
}

TEST_CASE("Failed network generation restores the previous compartment context",
          "[Compartment][Exception]") {
    auto bindingModel = parseModel(R"(
begin parameters
    kon 1.0e-4
end parameters
begin compartments
    EC 3 1
    mem 2 1 EC
end compartments
begin molecule types
    Lig(Site0)
    Receptor(Site0~U)
end molecule types
begin seed species
    @mem:Receptor(Site0~U) 1
    @EC:Lig(Site0) 1
end seed species
begin reaction rules
    @EC:Lig(Site0) + @mem:Receptor(Site0~U) -> @mem:Lig(Site0!1).Receptor(Site0~U!1) kon
end reaction rules
)");
    REQUIRE(bindingModel);
    const bng::compile::Document bindingDocument(*bindingModel);
    engine::NetworkGenerator bindingGenerator(bindingDocument);
    auto seedNetwork = bindingGenerator.generateNative(0);
    REQUIRE(seedNetwork.species.size() == 2);

    auto invalidModel = parseModel(R"(
begin functions
    amount() = time
end functions
begin compartments
    cell 3 1
end compartments
begin molecule types
    A()
end molecule types
begin seed species
    @cell:A() amount()
end seed species
)");
    REQUIRE(invalidModel);
    const bng::compile::Document invalidDocument(*invalidModel);
    engine::NetworkGenerator invalidGenerator(invalidDocument);

    // Leave a distinct context active around the failing call. The valid
    // binding rule below distinguishes this parentless topology from the
    // adjacent topology installed by the failed model's generation pass.
    ast::setCompartmentDimensions({{"EC", 3}, {"mem", 2}});
    ast::setCompartmentParents({});
    std::string generationError;
    try {
        (void)invalidGenerator.generateNative();
    } catch (const std::exception& error) {
        generationError = error.what();
    }
    INFO("network generation error: " << generationError);
    CHECK(generationError.find("network seed amount is not compile-time evaluable") !=
          std::string::npos);

    const auto& bindingRule = bindingModel->getReactionRules().front();
    auto executionState = bindingRule.createExecutionState();
    const auto expanded = bindingRule.expandRule(
        seedNetwork.species, seedNetwork.reactions, 0, *executionState, {},
        seedNetwork.species.size(), bindingModel.get());
    CHECK(expanded == 0);
}

TEST_CASE("One generated network supports repeated solver instances and rate overrides",
          "[CompiledModel][Instantiation]") {
    auto model = parseModel(R"(
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
)");
    REQUIRE(model);

    const bng::compile::Document originalDocument(*model);
    engine::NetworkGenerator generator(originalDocument);
    const auto network = generator.generateNative();
    REQUIRE(network.species.size() == 1);
    REQUIRE(network.reactions.size() == 1);

    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 2.0;
    options.nSteps = 20;
    options.rtol = 1e-11;
    options.atol = 1e-13;

    engine::OdeIntegrator originalIntegrator(*model, network);
    const auto original = originalIntegrator.integrate(options);
    const auto repeated = originalIntegrator.integrate(options);
    REQUIRE(original.timePoints.size() == repeated.timePoints.size());
    for (std::size_t i = 0; i < original.timePoints.size(); ++i) {
        const auto expected = 100.0 * std::exp(-0.1 * original.timePoints[i]);
        CHECK(std::abs(original.concentrations[i][0] - expected) < 1e-6);
        CHECK(std::abs(repeated.concentrations[i][0] - expected) < 1e-6);
    }

    model->getParameters().add(
        bng::ast::Parameter("k", bng::ast::Expression::number(0.25)));
    REQUIRE(originalDocument.model().parameters().front().constantValue.has_value());
    CHECK(std::abs(*originalDocument.model().parameters().front().constantValue - 0.1) <
          1e-12);

    // A rate-only override can reuse the same generated topology; each solver
    // instance compiles its own coefficients and trajectory state.
    engine::OdeIntegrator overriddenIntegrator(*model, network);
    const auto overridden = overriddenIntegrator.integrate(options);
    for (std::size_t i = 0; i < overridden.timePoints.size(); ++i) {
        const auto expected = 100.0 * std::exp(-0.25 * overridden.timePoints[i]);
        CHECK(std::abs(overridden.concentrations[i][0] - expected) < 1e-6);
    }

    const bng::compile::Document updatedDocument(*model);
    engine::NetworkGenerator updatedGenerator(updatedDocument);
    const auto freshNetwork = updatedGenerator.generateNative();
    engine::OdeIntegrator freshIntegrator(*model, freshNetwork);
    const auto fresh = freshIntegrator.integrate(options);
    REQUIRE(fresh.timePoints.size() == overridden.timePoints.size());
    for (std::size_t i = 0; i < overridden.timePoints.size(); ++i) {
        CHECK(std::abs(overridden.concentrations[i][0] - fresh.concentrations[i][0]) <
              1e-12);
    }
}

TEST_CASE("Fresh compiled models observe changed compartment volumes",
          "[CompiledModel][Invalidation]") {
    auto model = parseModel(R"(
begin compartments
    cell 3 2.0
end compartments
begin molecule types
    A()
end molecule types
begin seed species
    A()@cell 1
end seed species
)");
    REQUIRE(model);

    const bng::compile::Document originalDocument(*model);
    REQUIRE(originalDocument.model().compartments().size() == 1);
    CHECK(std::abs(originalDocument.model().compartments()[0].volume - 2.0) <
          1e-12);

    model->getCompartments()[0].setVolume(7.0);
    CHECK(std::abs(originalDocument.model().compartments()[0].volume - 2.0) <
          1e-12);

    const bng::compile::Document updatedDocument(*model);
    REQUIRE(updatedDocument.model().compartments().size() == 1);
    CHECK(std::abs(updatedDocument.model().compartments()[0].volume - 7.0) <
          1e-12);

    engine::NetworkGenerator originalGenerator(originalDocument);
    engine::NetworkGenerator updatedGenerator(updatedDocument);
    const auto originalNetwork = originalGenerator.generateNative();
    const auto updatedNetwork = updatedGenerator.generateNative();
    CHECK(originalNetwork.species.size() == updatedNetwork.species.size());
    CHECK(originalNetwork.reactions.size() == updatedNetwork.reactions.size());
}

TEST_CASE("Compartment transport: exocytosis EM -> PM", "[Compartment]") {
    auto model = parseModel(R"(
begin parameters
    k_exo 0.05
end parameters
begin compartments
    EC 3 1.0
    PM 2 1.0 EC
    CP 3 1.0 PM
    EM 2 1.0 CP
    EN 3 1.0 EM
end compartments
begin molecule types
    R(l)
end molecule types
begin seed species
    @EM:R(l) 100
end seed species
begin reaction rules
    @EM:R(l) -> @PM:R(l) k_exo
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() == 2);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Compartment transport: volume-to-volume", "[Compartment]") {
    auto model = parseModel(R"(
begin parameters
    k_trans 0.01
end parameters
begin compartments
    EC 3 1.0
    PM 2 1.0 EC
    CP 3 1.0 PM
end compartments
begin molecule types
    L()
end molecule types
begin seed species
    @EC:L() 100
end seed species
begin reaction rules
    @EC:L() -> @CP:L() k_trans
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() == 2);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Compartment transport: population reaction may consume distinct volumes", "[Compartment]") {
    auto model = parseModel(R"(
begin parameters
    k_bind 0.1
end parameters
begin compartments
    left 3 1.0
    right 3 1.0
end compartments
begin molecule types
    R()
    G()
    RG()
end molecule types
begin seed species
    @left:R() 10
    @right:G() 20
end seed species
begin reaction rules
    @left:R() + @right:G() -> @left:RG() k_bind
end reaction rules
)");

    engine::NetworkGenerator gen(*model);
    const auto network = gen.generateNative(1);

    REQUIRE(network.species.size() == 3);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Compartment transport: cross-volume bond formation remains rejected", "[Compartment]") {
    auto model = parseModel(R"(
begin parameters
    k_bind 0.1
end parameters
begin compartments
    left 3 1.0
    right 3 1.0
end compartments
begin molecule types
    R(b)
    G(a)
end molecule types
begin seed species
    @left:R(b) 1
    @right:G(a) 1
end seed species
begin reaction rules
    @left:R(b) + @right:G(a) -> @left:R(b!1).G(a!1) k_bind
end reaction rules
)");

    engine::NetworkGenerator gen(*model);
    const auto network = gen.generateNative(1);

    REQUIRE(network.reactions.size() == 0);
}

TEST_CASE("Compartment transport: replacement does not dereference deleted reactant", "[Compartment]") {
    auto model = parseModel(R"(
begin compartments
    outer 3 1.0
    inner 3 1.0
end compartments
begin molecule types
    A()
    B()
end molecule types
begin seed species
    @outer:A() 1
end seed species
begin reaction rules
    @outer:A() -> @inner:B() 1
end reaction rules
)");

    engine::NetworkGenerator gen(*model);
    const auto network = gen.generateNative(1);

    REQUIRE(network.species.size() == 2);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Issue 232 preserves both seeded reversible compartment directions",
          "[Compartment][issue-232]") {
    auto model = parseModel(R"(
begin parameters
    kf 2
    kr 3
end parameters
begin compartments
    C1 3 1
    C2 2 1 C1
    C3 3 1 C2
end compartments
begin molecule types
    A()
    B()
    C()
end molecule types
begin seed species
    A()@C1 1
    B()@C3 1
    C()@C3 1
end seed species
begin reaction rules
    R1: A()@C1 + B()@C3 <-> C()@C3 kf,kr
end reaction rules
)");
    REQUIRE(model != nullptr);

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(1);

    REQUIRE(network.reactions.size() == 2);
    const auto reverseCount = std::count_if(
        network.reactions.all().begin(), network.reactions.all().end(),
        [](const auto& reaction) {
            return reaction.getOriginRuleName().find("reverse") !=
                std::string::npos;
        });
    CHECK(reverseCount == 1);
}

TEST_CASE("Issue 246 does not infer adjacency for parentless compartments",
          "[Compartment][issue-246]") {
    auto model = parseModel(R"(
begin parameters
    kon 1.0e-4
end parameters
begin compartments
    EC 3 1
    mem 2 1
end compartments
begin molecule types
    Lig(Site0)
    Receptor(Site0~U~P)
end molecule types
begin seed species
    @mem:Receptor(Site0~U) 1
    @EC:Lig(Site0) 1
end seed species
begin reaction rules
    @EC:Lig(Site0) + @mem:Receptor(Site0~U) -> @mem:Lig(Site0!1).Receptor(Site0~U!1) kon
end reaction rules
)");
    REQUIRE(model != nullptr);

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(1);

    CHECK(network.reactions.size() == 0);
}

TEST_CASE("Issue 124 permits parameters after rules and seed species",
          "[Parser][issue-124]") {
    auto model = parseModel(R"(
begin reaction rules
    A() -> B() k2
end reaction rules
begin seed species
    A() 2
    B() 0
end seed species
begin molecule types
    A()
    B()
end molecule types
begin parameters
    k1 1
    k2 k1 + 1
end parameters
)");
    REQUIRE(model != nullptr);
    CHECK(model->getParameters().get("k2").getValue() == 2.0);

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    CHECK(network.reactions.size() == 1);
}
