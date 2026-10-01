// Regression tests for the PK/PD-relevant rate-law lowering in
// OdeIntegrator::compile().
//
// Both defects were found by comparing a simulated trajectory against a
// closed-form pharmacokinetic/pharmacodynamic solution, and both are silent:
// the model runs, the run looks plausible, and the number is wrong.
//
//   DEFECT 1 -- `Sat(Vmax, Km, S)` names its SUBSTRATE in the third position.
//   The lowering decided "this is a Hill law" from the argument COUNT alone
//   (`paramNames.size() >= 3`) without looking at the keyword, so the substrate
//   was consumed as the Hill COEFFICIENT. Measured before the fix, on a
//   unimolecular decay from A=1000 with Vmax=2, Km=10, mean flux over
//   t in [0, 0.5]:
//       Sat(Vmax,Km,0.5)      -> 1.8181442324   == Hill(Vmax,Km,0.5)  [wrong]
//       Sat(Vmax,Km,2)        -> 1.9997998178   == Hill(Vmax,Km,2)    [wrong]
//       Sat(Vmax,Km)          -> 1.9801883040   == Vmax*A/(Km+A)      [right]
//   Hill with exponent 1 coincides with Sat, which is why an exponent of 1
//   looked correct and hid the bug.
//
//   DEFECT 2 -- a rate-law argument that is a NUMERIC LITERAL was built as a
//   bare identifier, which does not resolve, so the whole rate evaluated to
//   exactly zero and the run still succeeded:
//       Hill(Vmax,Km,2)       -> flux 0.0000000000
//       Sat(Vmax,Km,2)        -> flux 0.0000000000
//       Hill(Vmax,Km,n)       -> flux 1.9997998178   (n a parameter: correct)
//
// The oracle is exact, not a recorded golden value: each test integrates the
// closed-form ODE with RK4 at rtol-equivalent step refinement and compares the
// END state, which is what a fixed-step ODE output must reproduce.

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>

#include <cmath>
#include <string>
#include <vector>

#include "ast/Model.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "parser/BNGAstVisitor.hpp"

using Catch::Matchers::WithinAbs;
using Catch::Matchers::WithinRel;

namespace {

// One substrate decaying out of a compartment volume V, driven by a total-rate
// saturation law.  Amounts are counts; the analytic law is stated in the
// comment of each test.
constexpr double kVmax = 2.0;
constexpr double kKm = 10.0;
constexpr double kA0 = 1000.0;
constexpr double kTEnd = 0.5;
constexpr int kSteps = 4;

std::string saturationModel(const std::string& rateLaw) {
    return R"(begin model
begin parameters
  Vmax 2
  Km   10
  n    2
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 1000
end seed species
begin observables
  Molecules Amount A()
end observables
begin reaction rules
  A() -> 0  )" + rateLaw + R"(
end reaction rules
end model
)";
}

// Integrate dA/dt = f(A) from kA0 to kTEnd with classical RK4.  The saturation
// laws are smooth on [0, kA0], so a fine fixed step is exact to far below the
// tolerances asserted below.
template <typename F>
double rk4(F f, double y0, double t1, int n = 400000) {
    const double h = t1 / n;
    double y = y0;
    for (int i = 0; i < n; ++i) {
        const double k1 = f(y);
        const double k2 = f(y + 0.5 * h * k1);
        const double k3 = f(y + 0.5 * h * k2);
        const double k4 = f(y + h * k3);
        y += h / 6.0 * (k1 + 2.0 * k2 + 2.0 * k3 + k4);
    }
    return y;
}

// Total-rate Michaelis-Menten:  dA/dt = -Vmax*A/(Km + A)
double michaelisMenten(double a) { return -kVmax * a / (kKm + a); }

// Total-rate Hill with coefficient n:  dA/dt = -Vmax*A^n/(Km^n + A^n)
double hill(double a, double n) { return -kVmax * std::pow(a, n) / (std::pow(kKm, n) + std::pow(a, n)); }

double finalAmount(const std::string& rateLaw) {
    auto model = bng::parser::parseModel(saturationModel(rateLaw));
    REQUIRE(model != nullptr);

    bng::engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();

    bng::engine::OdeOptions options;
    options.tStart = 0.0;
    options.tEnd = kTEnd;
    options.nSteps = kSteps;
    options.atol = 1e-12;
    options.rtol = 1e-12;

    const auto result = bng::engine::OdeIntegrator(*model, network).integrate(options);
    REQUIRE(result.concentrations.size() == static_cast<std::size_t>(kSteps) + 1);
    REQUIRE(result.concentrations.back().size() == 1);
    return result.concentrations.back().front();
}

// Mean elimination flux over [0, kTEnd]; the quantity every measurement below is
// quoted in, because it is what distinguishes "wrong law" from "no reaction".
double meanFlux(const std::string& rateLaw) {
    return (kA0 - finalAmount(rateLaw)) / kTEnd;
}

}  // namespace

TEST_CASE("Sat with two arguments is the total-rate Michaelis-Menten law",
          "[OdeOptions][rate-law][pk]") {
    // The control for everything below: this spelling was always correct.
    const double measured = meanFlux("Sat(Vmax,Km)");
    const double expected = (kA0 - rk4(michaelisMenten, kA0, kTEnd)) / kTEnd;

    REQUIRE_THAT(measured, WithinRel(expected, 1e-4));
}

// DEFECT 1.  A three-argument `Sat` names its SUBSTRATE.  The argument count
// must not decide that the law is a Hill law: doing so silently turned the
// substrate into the Hill coefficient and changed the model's meaning.
TEST_CASE("Sat naming its substrate is not lowered as a Hill law",
          "[OdeOptions][rate-law][pk]") {
    // Each coefficient is chosen so the Hill reading and the Sat reading differ
    // substantially AT THIS SUBSTRATE LEVEL.  Two exclusions, both measured:
    //   n = 1  -- Hill(Vmax,Km,1) is numerically identical to Sat(Vmax,Km),
    //              which is exactly why the bug survived an n=1 spot check;
    //   n = 0.5 -- at A=1000 with Km=10 the substrate is deep in saturation, and
    //              Hill with n=0.5 lands within 0.005 of the Sat flux, so it
    //              cannot discriminate the two readings here.
    for (const double n : {2.0, 4.0}) {
        CAPTURE(n);

        const std::string param = std::to_string(n);

        const double measured = meanFlux("Sat(Vmax,Km,n)");
        const double satExact = (kA0 - rk4(michaelisMenten, kA0, kTEnd)) / kTEnd;
        const double hillExact = (kA0 - rk4([n](double a) { return hill(a, n); },
                                             kA0, kTEnd)) / kTEnd;

        // Must follow the saturating law...
        REQUIRE_THAT(measured, WithinRel(satExact, 1e-4));
        // ...and must NOT follow the Hill reading.  The two exact fluxes are at
        // least 0.0196 apart, so requiring a separation larger than half of that
        // fails loudly on the old routing.  Written as an explicit inequality
        // because `WithinAbs` is a POSITIVE matcher: asserting it against
        // hillExact would assert the very thing this test exists to forbid.
        REQUIRE(std::abs(measured - hillExact) > 0.005);

        // And the literal spelling must agree with the parameter spelling.
        const double literal = meanFlux("Sat(Vmax,Km," + param + ")");
        REQUIRE_THAT(literal, WithinRel(satExact, 1e-4));
        REQUIRE(std::abs(literal - hillExact) > 0.005);
    }

    // The discriminating power the loop above relies on, asserted rather than
    // assumed: for each coefficient used, the two readings really do differ.
    const double satExact = (kA0 - rk4(michaelisMenten, kA0, kTEnd)) / kTEnd;
    for (const double n : {2.0, 4.0}) {
        CAPTURE(n);
        const double hillExact = (kA0 - rk4([n](double a) { return hill(a, n); },
                                             kA0, kTEnd)) / kTEnd;
        REQUIRE(std::abs(hillExact - satExact) > 0.01);
    }
}

// DEFECT 2.  A numeric literal in a rate law is not a symbol.  Built as a bare
// identifier it did not resolve, the rate evaluated to exactly zero, and the
// simulation still reported success -- a receptor-occupancy model whose Hill
// coefficient is written as a number simply never responded.
TEST_CASE("a literal Hill coefficient is not silently zero",
          "[OdeOptions][rate-law][pk]") {
    const double exact = (kA0 - rk4([](double a) { return hill(a, 2.0); },
                                    kA0, kTEnd)) / kTEnd;

    SECTION("Hill with the exponent as a literal") {
        REQUIRE_THAT(meanFlux("Hill(Vmax,Km,2)"), WithinRel(exact, 1e-4));
    }

    SECTION("Hill with the exponent as a parameter") {
        REQUIRE_THAT(meanFlux("Hill(Vmax,Km,n)"), WithinRel(exact, 1e-4));
    }

    SECTION("both spellings agree, so the literal is not a silent no-op") {
        const double literal = meanFlux("Hill(Vmax,Km,2)");
        const double named = meanFlux("Hill(Vmax,Km,n)");
        REQUIRE_THAT(literal, WithinRel(named, 1e-5));
        // Guards the specific regression: the measured flux must not be zero.
        REQUIRE(literal > 0.5 * exact);
    }
}

// A Hill law really is a Hill law, so the fix above did not flatten it into
// Michaelis-Menten.  This is the other direction of the same routing decision.
TEST_CASE("Hill keeps its own coefficient", "[OdeOptions][rate-law][pk]") {
    const double exact2 = (kA0 - rk4([](double a) { return hill(a, 2.0); },
                                     kA0, kTEnd)) / kTEnd;
    const double exact1 = (kA0 - rk4(michaelisMenten, kA0, kTEnd)) / kTEnd;

    REQUIRE_THAT(meanFlux("Hill(Vmax,Km,n)"), WithinRel(exact2, 1e-4));
    // n = 2 must be measurably different from n = 1 at this substrate level:
    // the two exact fluxes differ by 0.0196, so requiring that separation
    // fails loudly if Hill were ever flattened into Sat.  An explicit
    // inequality again, because `WithinAbs` would assert the opposite.
    REQUIRE(std::abs(meanFlux("Hill(Vmax,Km,n)") - exact1) > 0.005);
}
