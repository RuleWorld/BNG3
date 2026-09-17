#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include "engine/FiniteBackend.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "parser/BNGAstVisitor.hpp"

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
#ifndef BNG3_HAS_BNGSIM_ADAPTER
    // Without adapter, supported must be false and blockers must mention unavailable
    REQUIRE(!chk.supported);
    bool hasUnavailable = false;
    for (const auto& b : chk.blockers) {
        if (b.find("unavailable") != std::string::npos) hasUnavailable = true;
    }
    REQUIRE(hasUnavailable);
#else
    REQUIRE(chk.supported);
    REQUIRE(chk.blockers.empty());
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
