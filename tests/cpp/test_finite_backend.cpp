#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include "ast/Observable.hpp"
#include "engine/FiniteBackend.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "parser/BNGAstVisitor.hpp"

#ifdef BNG3_HAS_BNGSIM_ADAPTER
#include "engine/BngsimAdapter.hpp"
#include <bngsim/model.hpp>
#endif

using namespace bng;

TEST_CASE("FiniteBackend capabilities are available without BNGSIM build", "[finite_backend]") {
    auto caps = engine::getBngsimCapabilities();
    // In default build, available is false and version is "unavailable"
    // This lock ensures the capability object is stable and not exception-text.
#ifndef BNG3_HAS_BNGSIM_ADAPTER
    REQUIRE(!caps.available);
    REQUIRE(caps.version == "unavailable");
    REQUIRE(!caps.supportsOde);
#else
    REQUIRE(caps.available);
    REQUIRE(!caps.version.empty());
#endif
    REQUIRE(engine::bngsimVersion() == caps.version);
    REQUIRE(engine::isBngsimAvailable() == caps.available);
}

TEST_CASE("FiniteBackend simple model lowering check", "[finite_backend]") {
    auto model = parser::parseModel(R"(
begin parameters
 k 0.1
end parameters
begin molecule types
 X()
end molecule types
begin seed species
 X() 100
end seed species
begin reaction rules
 X() -> 0 k
end reaction rules
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator gen(*model);
    auto net = gen.generateNative();
    auto chk = engine::checkBngsimLowering(*model, net);
    // Lowerability describes BNG3 semantics; availability is reported
    // separately through getBngsimCapabilities().
    REQUIRE(chk.supported);
    REQUIRE(chk.blockers.empty());
}

TEST_CASE("FiniteBackend reports unsupported observable consistently", "[finite_backend]") {
    auto model = parser::parseModel(R"(
begin molecule types
 X()
end molecule types
begin seed species
 X() 1
end seed species
)");
    REQUIRE(model != nullptr);
    model->addObservable(ast::Observable("X_custom", "Custom", {"X()"}));
    engine::NetworkGenerator gen(*model);
    auto net = gen.generateNative();

    const std::string expected =
        "BNGsim adapter rejected observable 'X_custom': unsupported observable type 'Custom'";
    const auto check = engine::checkBngsimLowering(*model, net);
    REQUIRE_FALSE(check.supported);
    REQUIRE(check.blockers.size() == 1);
    CHECK(check.blockers.front() == expected);

#ifdef BNG3_HAS_BNGSIM_ADAPTER
    REQUIRE_THROWS_WITH(
        engine::buildBngsimNetwork(*model, net),
        Catch::Matchers::Equals(expected));
#endif
}

TEST_CASE("FiniteBackend reports TFUN provenance blocker consistently", "[finite_backend]") {
    auto model = parser::parseModel(R"(
begin molecule types
 X()
end molecule types
begin seed species
 X() 1
end seed species
begin functions
 rate() = TFUN('forcing.dat', time)
end functions
begin reaction rules
 X() -> 0 rate
end reaction rules
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator gen(*model);
    auto net = gen.generateNative();

    const std::string expected =
        "BNGsim adapter rejected TFUN: relative table path requires source-directory provenance";
    const auto check = engine::checkBngsimLowering(*model, net);
    REQUIRE_FALSE(check.supported);
    REQUIRE(check.blockers.size() == 1);
    CHECK(check.blockers.front() == expected);

#ifdef BNG3_HAS_BNGSIM_ADAPTER
    REQUIRE_THROWS_WITH(
        engine::buildBngsimNetwork(*model, net),
        Catch::Matchers::Equals(expected));
#endif
}

TEST_CASE("FiniteBackend compartment lowering is rejected with semantic blocker", "[finite_backend]") {
    auto model = parser::parseModel(R"(
begin compartments
 CYT 3 1
end compartments
begin molecule types
 X()
end molecule types
begin seed species
 X() 1
end seed species
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator gen(*model);
    auto net = gen.generateNative();
    auto chk = engine::checkBngsimLowering(*model, net);
    REQUIRE(!chk.supported);
    bool hasCompartment = false;
    for (const auto& b : chk.blockers) {
        if (b.find("compartments") != std::string::npos) hasCompartment = true;
    }
    REQUIRE(hasCompartment);
}

TEST_CASE("FiniteBackend non-reference rate is rejected", "[finite_backend]") {
    auto model = parser::parseModel(R"(
begin parameters
 k 0.1
end parameters
begin molecule types
 X()
end molecule types
begin seed species
 X() 1
end seed species
begin reaction rules
 X() -> 0 k*2
end reaction rules
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator gen(*model);
    auto net = gen.generateNative();
    auto chk = engine::checkBngsimLowering(*model, net);
    REQUIRE(!chk.supported);
    bool hasRate = false;
    for (const auto& b : chk.blockers) {
        if (b.find("rate law") != std::string::npos) hasRate = true;
    }
    REQUIRE(hasRate);
}

TEST_CASE("FiniteBackend backend string parsing", "[finite_backend]") {
    REQUIRE(engine::finiteBackendFromString("auto") == engine::FiniteBackend::Native);
    REQUIRE(engine::finiteBackendFromString("native") == engine::FiniteBackend::Native);
    REQUIRE(engine::finiteBackendFromString("bngsim") == engine::FiniteBackend::Bngsim);
    REQUIRE(engine::finiteBackendFromString("BNGSIM") == engine::FiniteBackend::Bngsim);
    REQUIRE(engine::finiteBackendToString(engine::FiniteBackend::Bngsim) == "bngsim");
    REQUIRE_THROWS_WITH(
        engine::finiteBackendFromString("unknown"),
        Catch::Matchers::ContainsSubstring("Unknown finite backend"));
}

TEST_CASE("FiniteBackend native ODE simulation still works", "[finite_backend]") {
    auto model = parser::parseModel(R"(
begin parameters
 k 0.1
end parameters
begin molecule types
 X()
end molecule types
begin seed species
 X() 100
end seed species
begin reaction rules
 X() -> 0 k
end reaction rules
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator gen(*model);
    auto net = gen.generateNative();
    engine::OdeOptions opts;
    opts.tStart = 0;
    opts.tEnd = 1;
    opts.nSteps = 2;
    opts.rtol = 1e-8;
    opts.atol = 1e-8;
    auto resNative = engine::simulateFiniteOde(*model, net, opts, engine::FiniteBackend::Native);
    REQUIRE(resNative.timePoints.size() == 3);
    REQUIRE(resNative.concentrations.size() == 3);
    // Native must produce decreasing concentrations
    CHECK(resNative.concentrations[0][0] > resNative.concentrations[1][0]);
    CHECK(resNative.concentrations[1][0] > resNative.concentrations[2][0]);
    // BNGsim explicit should fail closed when unavailable
#ifndef BNG3_HAS_BNGSIM_ADAPTER
    REQUIRE_THROWS_WITH(
        engine::simulateFiniteOde(*model, net, opts, engine::FiniteBackend::Bngsim),
        Catch::Matchers::ContainsSubstring("unavailable"));
#endif
}
