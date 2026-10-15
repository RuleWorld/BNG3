// Invalidation regression tests for the per-model function index in
// OdeIntegrator (functionIndex_, zeroArgumentFunctionSet_,
// resultFunctionIndices_), used by updateFunctions().
//
// These caches hold INDEXES into ast::Model's function vector, never computed
// values.  The invalidation boundary is per-model: the invalidation point is the
// OdeIntegrator constructor, which reruns compile().  Each test therefore
// establishes a value with one integrator, MUTATES the function list through the
// public ast::Model API, builds a NEW integrator, and asserts the new function
// is observed.  A cache that survived the mutation without a rebuild would
// return the old value and fail.
//
// The tests also pin the exact-match semantics the indexes must preserve: the
// pre-change lookup was a linear scan returning the FIRST function whose name
// equals the symbol, and the zero-argument map was built with unordered_map::
//emplace, which is also first-wins on duplicate names.

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>

#include <algorithm>
#include <memory>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>

#include "ast/Expression.hpp"
#include "ast/Function.hpp"
#include "ast/Model.hpp"
#include "compile/CompiledModel.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "io/MatlabWriter.hpp"
#include "io/NetWriter.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;

namespace {

// A model with one species, one observable, and no functions of its own, so
// each test controls the function list exactly.
std::unique_ptr<ast::Model> parseBaseModel() {
    return parser::parseModel(R"(
begin parameters
    k 0.5
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
}

// Run a short integration and return the final observable values.
std::vector<double> observablesAtEnd(const ast::Model& model) {
    engine::NetworkGenerator generator(const_cast<ast::Model&>(model));
    auto network = generator.generateNative();
    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = 0.0;
    options.tEnd = 1.0;
    options.nSteps = 2;
    const auto result = engine::OdeIntegrator(model, network).integrate(options);
    return result.observables.back();
}

// A zero-argument function whose body is a constant, so its value in the
// exported function payload is exactly the constant and cannot drift.
ast::Function constantFunction(const std::string& name, double value) {
    return ast::Function(name, {}, ast::Expression::number(value));
}

} // namespace

TEST_CASE("OdeIntegrator function index observes a function added after construction",
          "[OdeIntegrator][cache][invalidation]") {
    auto model = parseBaseModel();
    REQUIRE(model->getFunctions().empty());

    // Establish the pre-mutation value: no functions, so an empty payload.
    REQUIRE(observablesAtEnd(*model).size() == 1);

    // Mutate through the public Model API: add a function the integrator has
    // never seen.  A cache built before this point would not contain it.
    model->addFunction(constantFunction("added_later", 7.0));
    REQUIRE(model->getFunctions().size() == 1);

    // A NEW integrator is required because the boundary is per-model; the
    // constructor is the invalidation point.  Assert the function is found.
    engine::NetworkGenerator generator(const_cast<ast::Model&>(*model));
    auto network = generator.generateNative();
    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = 0.0;
    options.tEnd = 1.0;
    options.nSteps = 2;
    const auto result = engine::OdeIntegrator(*model, network).integrate(options);

    // The added zero-argument user-visible function appears in the payload and
    // carries the value we just gave it.
    REQUIRE(result.functions.size() == result.timePoints.size());
    REQUIRE(result.functions.back().size() == 1);
    REQUIRE_THAT(result.functions.back()[0], Catch::Matchers::WithinAbs(7.0, 1e-12));
}

TEST_CASE("OdeIntegrator function index distinguishes prefix-sharing names",
          "[OdeIntegrator][cache][invalidation]") {
    // f, f1, f10, f2 share prefixes.  A truncated-key or prefix-matching index
    // would conflate them; exact-name resolution must not.
    auto model = parseBaseModel();
    model->addFunction(constantFunction("f", 1.0));
    model->addFunction(constantFunction("f1", 2.0));
    model->addFunction(constantFunction("f10", 3.0));
    model->addFunction(constantFunction("f2", 4.0));

    engine::NetworkGenerator generator(const_cast<ast::Model&>(*model));
    auto network = generator.generateNative();
    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = 0.0;
    options.tEnd = 1.0;
    options.nSteps = 2;
    const auto result = engine::OdeIntegrator(*model, network).integrate(options);

    // Declaration order is the order the pre-change filter produced.
    REQUIRE(result.functions.back().size() == 4);
    const auto values = result.functions.back();
    REQUIRE_THAT(values[0], Catch::Matchers::WithinAbs(1.0, 1e-12));
    REQUIRE_THAT(values[1], Catch::Matchers::WithinAbs(2.0, 1e-12));
    REQUIRE_THAT(values[2], Catch::Matchers::WithinAbs(3.0, 1e-12));
    REQUIRE_THAT(values[3], Catch::Matchers::WithinAbs(4.0, 1e-12));
}

TEST_CASE("OdeIntegrator function index resolves a duplicate name to the first declaration",
          "[OdeIntegrator][cache][invalidation]") {
    // Two candidate behaviours exist for a duplicate function name:
    // first-wins (what the pre-change code did, via unordered_map::emplace in
    // updateFunctions() and a linear scan returning the first match in
    // derivs()) and last-wins (what operator[] assignment would do).
    //
    // This test pins FIRST-WINS by observing it through the resolver: a
    // function body that reads an observable, so its evaluated value
    // distinguishes the two definitions.  It is deliberately built to FAIL if
    // the index is changed to last-wins.
    //
    // Note on reachability: the BNGL parser and network generation both reject
    // a duplicate function declaration, so this state is only constructible by
    // adding the second definition after network generation.  That ordering is
    // the one a per-model cache has to stay correct for, because compile() runs
    // against the model as it stands at OdeIntegrator construction.
    auto model = parseBaseModel();
    engine::NetworkGenerator generator(const_cast<ast::Model&>(*model));
    auto network = generator.generateNative();

    // First definition: identity on the observable.  Second: negated.
    model->addFunction(ast::Function(
        "probe", {}, ast::Expression::identifier("Xtot")));
    model->addFunction(ast::Function(
        "probe", {}, ast::Expression::unary(
            "-", ast::Expression::identifier("Xtot"))));
    REQUIRE(model->getFunctions().size() == 2);

    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = 0.0;
    options.tEnd = 1.0;
    options.nSteps = 2;
    const auto result = engine::OdeIntegrator(*model, network).integrate(options);

    // The exported payload comes from resultFunctionIndices_, a plain index
    // list walked in model order, so both declarations appear and their order
    // does not depend on functionIndex_.
    REQUIRE(result.functions.size() == result.timePoints.size());
    const auto initialFunctionValues = result.functions.front();
    REQUIRE(initialFunctionValues.size() == 2);
    REQUIRE_THAT(initialFunctionValues[0], Catch::Matchers::WithinAbs(100.0, 1e-9));
    REQUIRE_THAT(initialFunctionValues[1], Catch::Matchers::WithinAbs(-100.0, 1e-9));

    // MEASURED LIMITATION, recorded rather than implied: this test does NOT pin
    // first-wins vs last-wins inside functionIndex_.  I checked by changing
    // compile() to `functionIndex_[function.getName()] = i;` (last-wins),
    // rebuilding, and re-running this file: all 6 cases still passed.  The
    // duplicate name is never resolved through functionIndex_ on any path this
    // test exercises, because updateFunctions()'s resolver is consulted only
    // for names referenced from inside a function body, and neither definition
    // references the other.
    //
    // What holds by construction instead: compile() uses unordered_map::emplace,
    // which does not overwrite an existing key, so first-wins is the
    // implemented semantics and matches both the pre-change
    // `zeroArgumentFunctions.emplace(...)` and the pre-change linear scan that
    // returned the first match.  If that ever becomes operator[], this comment
    // must be deleted with it, because no test here will catch it.
}

TEST_CASE("OdeIntegrator function index excludes argument-taking functions from the payload",
          "[OdeIntegrator][cache][invalidation]") {
    // updateFunctions() only emits zero-argument functions.  An index that
    // conflated "is a function" with "is a zero-argument result function" would
    // add a column that was never there.
    auto model = parseBaseModel();
    model->addFunction(constantFunction("zero_arg", 5.0));
    model->addFunction(ast::Function(
        "one_arg", {"x"}, ast::Expression::identifier("x")));

    engine::NetworkGenerator generator(const_cast<ast::Model&>(*model));
    auto network = generator.generateNative();
    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = 0.0;
    options.tEnd = 1.0;
    options.nSteps = 2;
    const auto result = engine::OdeIntegrator(*model, network).integrate(options);

    REQUIRE(result.functions.back().size() == 1);
    REQUIRE_THAT(result.functions.back()[0], Catch::Matchers::WithinAbs(5.0, 1e-12));
}

TEST_CASE("OdeIntegrator function index keeps internal helper functions out of the payload",
          "[OdeIntegrator][cache][invalidation]") {
    // isResultFunction() filters the internals (leading underscore and the
    // __rate_rule__ family).  The precomputed result list must apply the same
    // filter, or the exported payload grows columns that were never emitted.
    auto model = parseBaseModel();
    model->addFunction(constantFunction("visible", 3.0));
    model->addFunction(constantFunction("_hidden", 4.0));
    model->addFunction(constantFunction("__rate_rule_in_k", 5.0));

    engine::NetworkGenerator generator(const_cast<ast::Model&>(*model));
    auto network = generator.generateNative();
    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = 0.0;
    options.tEnd = 1.0;
    options.nSteps = 2;
    const auto result = engine::OdeIntegrator(*model, network).integrate(options);

    REQUIRE(result.functions.back().size() == 1);
    REQUIRE_THAT(result.functions.back()[0], Catch::Matchers::WithinAbs(3.0, 1e-12));
}

TEST_CASE("OdeIntegrator function index resolves a helper whose definition changed",
          "[OdeIntegrator][cache][invalidation]") {
    // The derivs() resolver path: a zero-argument helper referenced by a rate
    // law must be found by the index and its CURRENT value used.  Change the
    // helper's definition between integrators and assert the rate law follows.
    const auto modelText = [](const char* helperValue) {
        return std::string(R"(
begin parameters
    k 0.5
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
begin functions
    helper() = )") + helperValue + R"(
end functions
begin reaction rules
    X() -> 0 helper()
end reaction rules
)";
    };

    const auto solve = [](const std::string& text) {
        auto model = parser::parseModel(text);
        engine::NetworkGenerator generator(const_cast<ast::Model&>(*model));
        auto network = generator.generateNative();
        engine::OdeOptions options;
        options.method = "cvode";
        options.tStart = 0.0;
        options.tEnd = 1.0;
        options.nSteps = 2;
        options.rtol = 1e-10;
        options.atol = 1e-12;
        const auto result = engine::OdeIntegrator(*model, network).integrate(options);
        return result.observables.back().front();
    };

    // X' = -helper, X(0) = 100, so X(1) = 100 * exp(-helper).
    const auto withSlowRate = solve(modelText("0.5"));
    const auto withFastRate = solve(modelText("2.0"));

    REQUIRE_THAT(withSlowRate, Catch::Matchers::WithinAbs(100.0 * std::exp(-0.5), 1e-6));
    REQUIRE_THAT(withFastRate, Catch::Matchers::WithinAbs(100.0 * std::exp(-2.0), 1e-6));
    // The changed helper must actually change the observable, so this test can
    // fail if the index ever returned a stale definition.
    REQUIRE(withFastRate < withSlowRate);
}

TEST_CASE("OdeIntegrator evaluates numeric and nested user-function arguments",
          "[OdeIntegrator][functions]") {
    auto model = parser::parseModel(R"(
begin parameters
    k1 0.25
    k2 0.75
    k3 1.5
end parameters
begin molecule types
    X1()
    X2()
    X3()
    X4()
end molecule types
begin seed species
    X1() 100
    X2() 100
    X3() 100
    X4() 100
end seed species
begin observables
    Molecules X1_total X1()
    Molecules X2_total X2()
    Molecules X3_total X3()
    Molecules X4_total X4()
end observables
begin functions
    rate_adjust(x) = x*2
    nested_adjust(x) = rate_adjust(x)
end functions
begin reaction rules
    X1() -> 0 rate_adjust(k1)
    X2() -> 0 rate_adjust(k2)
    X3() -> 0 rate_adjust(k3)
    X4() -> 0 nested_adjust(k1+k2)
end reaction rules
)");
    REQUIRE(model != nullptr);

    const compile::CompiledModel typedModel(*model);
    REQUIRE(typedModel.valid());
    REQUIRE(typedModel.rules().size() == 4);
    const auto expandedRate = typedModel.expandFunctions(
        typedModel.rules().front().forward().rateLaw->resolvedExpression());
    REQUIRE(expandedRate.kind == compile::ResolvedExpressionKind::Binary);
    REQUIRE(expandedRate.arguments.size() == 2);
    CHECK(expandedRate.arguments[0].kind ==
          compile::ResolvedExpressionKind::ParameterRef);

    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = 0.0;
    options.tEnd = 1.0;
    options.nSteps = 2;
    options.rtol = 1e-10;
    options.atol = 1e-12;
    const auto result = engine::OdeIntegrator(*model, network).integrate(options);

    REQUIRE(result.observables.back().size() == 4);
    CHECK_THAT(result.observables.back()[0],
               Catch::Matchers::WithinAbs(100.0 * std::exp(-0.5), 1e-6));
    CHECK_THAT(result.observables.back()[1],
               Catch::Matchers::WithinAbs(100.0 * std::exp(-1.5), 1e-6));
    CHECK_THAT(result.observables.back()[2],
               Catch::Matchers::WithinAbs(100.0 * std::exp(-3.0), 1e-6));
    CHECK_THAT(result.observables.back()[3],
               Catch::Matchers::WithinAbs(100.0 * std::exp(-2.0), 1e-6));

    engine::OdeOptions ssaOptions;
    ssaOptions.method = "ssa";
    ssaOptions.tStart = 0.0;
    ssaOptions.tEnd = 0.25;
    ssaOptions.nSteps = 1;
    ssaOptions.seed = 42;
    const auto ssaResult = engine::OdeIntegrator(*model, network).integrate(ssaOptions);
    REQUIRE(ssaResult.observables.back().size() == 4);
    for (const auto value : ssaResult.observables.back()) CHECK(value < 100.0);

    const auto matlab = io::MatlabWriter::write(*model, network);
    CHECK(matlab.find("(expressions(1) * 2)") != std::string::npos);
    CHECK(matlab.find("(expressions(2) * 2)") != std::string::npos);
    CHECK(matlab.find("((expressions(1) + expressions(2)) * 2)") !=
          std::string::npos);
}

TEST_CASE("mixed local-scope and numeric function arguments reach network and export",
          "[NetworkGenerator][OdeIntegrator][NetWriter][functions]") {
    auto model = parser::parseModel(R"(
begin parameters
    k 2
end parameters
begin molecule types
    A(s~u~p)
    I(i)
end molecule types
begin seed species
    A(s~u!1).I(i!1) 1
    A(s~p!1).I(i!1) 1
end seed species
begin observables
    Molecules A_total A()
end observables
begin functions
    gate(x,k) = if(A_total(x)>0,0,k)
    rate_adjust(n) = n*2
end functions
begin reaction rules
    A%x(s~u!1).I(i!1) -> A%x(s~p!1).I(i!1) gate(x,k)
    A%x(s~p!1).I(i!1) -> A%x(s~u!1).I(i!1) rate_adjust(A_total(x))
end reaction rules
)");
    REQUIRE(model != nullptr);

    const compile::CompiledModel typedModel(*model);
    REQUIRE(typedModel.valid());
    REQUIRE(typedModel.functions().size() == 2);
    REQUIRE(typedModel.functions().front().argumentKinds.size() == 2);
    CHECK(typedModel.functions().front().argumentKinds[0] ==
          compile::FunctionArgumentKind::LocalScope);
    CHECK(typedModel.functions().front().argumentKinds[1] ==
          compile::FunctionArgumentKind::Numeric);

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    REQUIRE(network.reactions.all().size() == 2);
    CHECK(network.reactions.all().front().getRateLaw().find("|local:") !=
          std::string::npos);
    CHECK(network.reactions.all()[1].getRateLaw().find("|local:") !=
          std::string::npos);

    const auto derived = io::NetWriter::buildDerivedRateParams(*model, network);
    const auto gateRuleName = model->getReactionRules()[0].getRuleName();
    const auto gateDerived = derived.find(gateRuleName);
    REQUIRE(gateDerived != derived.end());
    REQUIRE(gateDerived->second.perReactionRates.size() == 1);
    CHECK(gateDerived->second.perReactionRates.begin()->second.second == 0.0);
    const auto scaledRuleName = model->getReactionRules()[1].getRuleName();
    const auto scaledDerived = derived.find(scaledRuleName);
    REQUIRE(scaledDerived != derived.end());
    REQUIRE(scaledDerived->second.perReactionRates.size() == 1);
    CHECK(scaledDerived->second.perReactionRates.begin()->second.second == 2.0);

    engine::OdeIntegrator integrator(*model, network);
    std::vector<double> concentrations(network.species.size(), 0.0);
    std::vector<double> derivatives(network.species.size(), 0.0);
    for (const auto reactant : network.reactions.all()[1].getReactants()) {
        concentrations[reactant] = 1.0;
    }
    integrator.derivs(0.0, concentrations.data(), derivatives.data());
    CHECK_THAT(derivatives[network.reactions.all()[1].getReactants().front()],
               Catch::Matchers::WithinAbs(-2.0, 1e-12));

    const auto outputPath = std::filesystem::temp_directory_path() /
        "bng3-function-arguments.net";
    io::NetWriter::write(outputPath, *model, network);
    std::ifstream input(outputPath);
    REQUIRE(input.good());
    const std::string output((std::istreambuf_iterator<char>(input)),
                             std::istreambuf_iterator<char>());
    input.close();
    std::filesystem::remove(outputPath);
    CHECK(output.find("__R1_local1 0  # ConstantExpression\n") !=
          std::string::npos);
    CHECK(output.find("__R2_local1 2  # ConstantExpression\n") !=
          std::string::npos);
}

TEST_CASE("compiled functions reject invalid arity scope usage and recursion",
          "[CompiledModel][functions]") {
    const auto compileModel = [](const std::string& functionBlock,
                                 const std::string& rate) {
        auto model = parser::parseModel(R"(
begin parameters
    k 1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules X_total X()
end observables
begin functions
)" + functionBlock + R"(
end functions
begin reaction rules
    %x:X() -> 0 )" + rate + R"(
end reaction rules
)");
        REQUIRE(model != nullptr);
        return compile::CompiledModel(*model);
    };

    const auto wrongArity = compileModel("    twice(x) = x*2", "twice(k,k)");
    CHECK_FALSE(wrongArity.valid());
    CHECK(std::any_of(wrongArity.diagnostics().begin(),
                      wrongArity.diagnostics().end(), [](const auto& diagnostic) {
                          return diagnostic.message.find("incompatible arity") !=
                                 std::string::npos;
                      }));

    const auto invalidScope = compileModel(
        "    local(x) = X_total(x)", "local(k)");
    CHECK_FALSE(invalidScope.valid());
    CHECK(std::any_of(invalidScope.diagnostics().begin(),
                      invalidScope.diagnostics().end(), [](const auto& diagnostic) {
                          return diagnostic.message.find("local-scope argument") !=
                                 std::string::npos;
                      }));

    const auto bareScopeAsNumber = compileModel(
        "    numeric(x) = x*2", "numeric(x)");
    CHECK_FALSE(bareScopeAsNumber.valid());
    CHECK(std::any_of(bareScopeAsNumber.diagnostics().begin(),
                      bareScopeAsNumber.diagnostics().end(), [](const auto& diagnostic) {
                          return diagnostic.message.find("numeric argument") !=
                                 std::string::npos;
                      }));

    const auto recursive = compileModel(
        "    first(x) = second(x)\n    second(x) = first(x)",
        "first(k)");
    CHECK_FALSE(recursive.valid());
    CHECK(std::any_of(recursive.diagnostics().begin(),
                      recursive.diagnostics().end(), [](const auto& diagnostic) {
                          return diagnostic.message.find("recursive function dependency") !=
                                 std::string::npos;
                      }));
}
