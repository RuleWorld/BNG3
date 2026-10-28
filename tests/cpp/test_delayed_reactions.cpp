#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <filesystem>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <memory>
#include <string>

#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "engine/BatchSsa.hpp"
#include "engine/PsaSimulator.hpp"
#include "actions/ActionDispatch.hpp"
#include "io/BnglWriter.hpp"
#include "io/CppExportWriter.hpp"
#include "io/NetWriter.hpp"
#include "io/NetReader.hpp"
#include "io/SbmlWriter.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;

namespace {

std::unique_ptr<ast::Model> parse(const std::string& rule,
                                  const std::string& extra = "") {
    return parser::parseModel(R"(
begin model
begin parameters
  tau 2
end parameters
begin molecule types
  A()
  B()
  G()
  M()
end molecule types
begin seed species
  A() 10
  G() 2
end seed species
begin reaction rules
  )" + rule + R"(
end reaction rules
)" + extra + R"(
end model
)");
}

std::string readFile(const std::filesystem::path& path) {
    std::ifstream input(path);
    return std::string(std::istreambuf_iterator<char>(input), {});
}

std::size_t speciesIndex(const engine::GeneratedNetwork& network,
                         const std::string& molecule) {
    const auto prefix = molecule + "(";
    for (std::size_t i = 0; i < network.species.size(); ++i) {
        if (network.species.get(i).getSpeciesGraph().toString().rfind(prefix, 0) == 0) {
            return i;
        }
    }
    throw std::runtime_error("missing species " + molecule);
}

double poissonChernoffDeviation(double mean, double tailProbability) {
    const auto divergence = [mean](double deviation, bool upper) {
        const double delta = deviation / mean;
        return mean * ((1.0 + (upper ? delta : -delta)) *
                           std::log(1.0 + (upper ? delta : -delta)) -
                       (upper ? delta : -delta));
    };
    double low = 0.0;
    double high = mean;
    while (std::exp(-divergence(high, true)) > tailProbability) high *= 2.0;
    for (int i = 0; i < 80; ++i) {
        const double middle = (low + high) / 2.0;
        if (std::exp(-divergence(middle, true)) > tailProbability) low = middle;
        else high = middle;
    }
    const double upperDeviation = high;
    low = 0.0;
    high = mean;
    for (int i = 0; i < 80; ++i) {
        const double middle = (low + high) / 2.0;
        if (std::exp(-divergence(middle, false)) > tailProbability) low = middle;
        else high = middle;
    }
    return std::max(upperDeviation, high);
}

}  // namespace

TEST_CASE("delayed reaction metadata parses, survives network generation, and round trips") {
    auto model = parse("G() -> G() + M() 0.5 delay=tau+1 NonConsuming");
    REQUIRE(model->getReactionRules().size() == 1);
    const auto& rule = model->getReactionRules().front();
    REQUIRE(rule.getDelayExpression());
    CHECK(rule.getDelayExpression()->toBnglString() == "(tau + 1)");
    CHECK(rule.isNonConsuming());

    const auto bngl = io::BnglWriter::write(*model);
    CHECK_THAT(bngl, Catch::Matchers::ContainsSubstring("delay=(tau + 1) NonConsuming"));
    auto roundTrip = parser::parseModel(bngl);
    REQUIRE(roundTrip->getReactionRules().front().getDelayExpression());
    CHECK(roundTrip->getReactionRules().front().isNonConsuming());

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    REQUIRE(network.reactions.size() == 1);
    CHECK(network.reactions.all().front().getDelayExpression());
    CHECK(network.reactions.all().front().isNonConsuming());

    auto output = std::filesystem::temp_directory_path() / "bng3-delay-net-writer.net";
    io::NetWriterOptions options;
    io::NetWriter::write(output, *model, network, options);
    const auto netText = readFile(output);
    CHECK_THAT(netText, Catch::Matchers::ContainsSubstring("delay=__delay_1 NonConsuming"));
    CHECK_THAT(netText, Catch::Matchers::ContainsSubstring("__delay_1 3"));
    const auto parsedNet = io::NetReader::parse(output);
    REQUIRE(parsedNet.success);
    REQUIRE(parsedNet.parameters.count("__delay_1") == 1);
    CHECK(parsedNet.parameters.at("__delay_1") == Catch::Approx(3.0));
    REQUIRE(parsedNet.reactions.size() == 1);
    CHECK_THAT(parsedNet.reactions.front(),
               Catch::Matchers::ContainsSubstring("delay=__delay_1 NonConsuming"));

    auto reloaded = parser::parseModel(R"(
begin model
begin molecule types
  G()
  M()
end molecule types
begin seed species
  G() 2
end seed species
end model
)");
    reloaded->addAction(ast::Action{
        "readFile", {{"file", output.filename().string()}}});
    reloaded->addAction(ast::Action{
        "simulate", {{"method", "ode"}, {"t_end", "1"}, {"n_steps", "1"}}});
    CHECK_NOTHROW(actions::ActionDispatch::execute(
        *reloaded, output.parent_path() / "delayed_read.bngl"));
    std::filesystem::remove(output);
}

TEST_CASE("delayed rule syntax rejects invalid modes and dynamic delays") {
    CHECK_THROWS_WITH(parse("A() -> B() 1 NonConsuming"),
                      Catch::Matchers::ContainsSubstring("only with delay"));
    CHECK_THROWS_WITH(parse("A() <-> B() 1, 1 delay=tau"),
                      Catch::Matchers::ContainsSubstring("reversible"));
    CHECK_THROWS_WITH(parse("A() -> B() 1 delay=-1"),
                      Catch::Matchers::ContainsSubstring("nonnegative"));
    CHECK_THROWS_WITH(parse("A() -> B() 1 delay=time"),
                      Catch::Matchers::ContainsSubstring("parameter expression"));
    CHECK_THROWS_WITH(parse("A() <-> B() 1, 1 delay=0"),
                      Catch::Matchers::ContainsSubstring("reversible"));
    CHECK_THROWS_WITH(parse("A() -> B() 1 delay=tau delay=tau"),
                      Catch::Matchers::ContainsSubstring("only one delay"));
}

TEST_CASE("delay parameters reject aliases assigned by native events") {
    CHECK_THROWS_WITH(parser::parseModel(R"(
begin model
begin parameters
  tau 2
  tauAlias tau
end parameters
begin molecule types
  A()
  B()
end molecule types
begin reaction rules
  A() -> B() 1 delay=tauAlias
end reaction rules
begin bng3_events version 1
  event "change_tau"
    trigger: time >= 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: tau = 3
  end event
end bng3_events
end model
)"), Catch::Matchers::ContainsSubstring("event-assigned parameter 'tau'"));
}

TEST_CASE("delay expression durations may depend on time and state") {
    const auto makeModel = [](const std::string& duration, const std::string& event) {
        return parser::parseModel(R"(
begin model
begin parameters
  tau 2
  tauAlias tau
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin observables
  Molecules Aobs A()
end observables
begin reaction rules
  A() -> B() k*delay(Aobs, )" + duration + R"()
end reaction rules
)" + event + R"(
end model
)");
    };
    {
        // delay(Aobs, time()) always reads the initial history, Aobs(0) = 1,
        // so dA/dt = -k * 1 * A and A(t) = exp(-t) with k = 1.
        auto model = makeModel("time()", "");
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        const auto a = speciesIndex(network, "A");
        engine::OdeIntegrator integrator(*model, network);
        engine::OdeOptions options;
        options.method = "cvode";
        options.tEnd = 0.5;
        options.nSteps = 5;
        const auto result = integrator.integrate(options);
        CHECK(result.concentrations.back()[a] ==
              Catch::Approx(std::exp(-0.5)).epsilon(1e-6));
    }
    {
        CHECK_THROWS_WITH(makeModel("tauAlias", R"(
begin bng3_events version 1
  event "change_tau"
    trigger: time >= 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: tau = 3
  end event
end bng3_events
 )"), Catch::Matchers::ContainsSubstring("event-assigned parameter 'tau'"));
    }
}

TEST_CASE("delay keywords remain valid parameter identifiers outside modifiers") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
  delay 0.5
  NonConsuming 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin reaction rules
  A() -> B() delay*NonConsuming
end reaction rules
end model
)");
    CHECK(model->getParameters().evaluate("delay") == 0.5);
    CHECK(model->getParameters().evaluate("NonConsuming") == 1.0);
}

TEST_CASE("NET reload preserves a rate parameter named NonConsuming") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
  NonConsuming 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> B() NonConsuming
end reaction rules
end model
)");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    const auto output = std::filesystem::temp_directory_path() /
                        "bng3-net-nonconsuming-rate-parameter.net";
    io::NetWriter::write(output, *model, network);
    CHECK_THAT(readFile(output), Catch::Matchers::ContainsSubstring(
                                   "1 1 2 NonConsuming"));

    auto reloaded = parser::parseModel(R"(
begin model
begin molecule types
  A()
  B()
end molecule types
end model
)");
    reloaded->addAction(ast::Action{
        "readFile", {{"file", output.filename().string()}}});
    reloaded->addAction(ast::Action{
        "simulate", {{"method", "ode"}, {"t_end", "1"}, {"n_steps", "1"}}});
    CHECK_NOTHROW(actions::ActionDispatch::execute(
        *reloaded, output.parent_path() / "nonconsuming_parameter_read.bngl"));

    std::filesystem::remove(output);
    std::filesystem::remove(output.parent_path() / "nonconsuming_parameter_read.gdat");
}

TEST_CASE("static mathematical functions are permitted in delay parameters") {
    auto model = parse("A() -> B() 1 delay=sqrt(tau)+1");
    REQUIRE(model->getReactionRules().front().getDelayExpression());
    CHECK(model->getReactionRules().front().getDelayExpression()->evaluate(
              [&](const std::string& name) { return model->getParameters().evaluate(name); })
          == Catch::Approx(std::sqrt(2.0) + 1.0));

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    REQUIRE(network.reactions.size() == 1);
    CHECK(network.reactions.all().front().getDelayExpression());
}

TEST_CASE("NonConsuming delayed rules require nonnegative net species stoichiometry") {
    auto model = parse("A() -> 0 1 delay=tau NonConsuming");
    engine::NetworkGenerator generator(*model);
    CHECK_THROWS_WITH(generator.generateNative(),
                      Catch::Matchers::ContainsSubstring("negative net reactant stoichiometry"));
}

TEST_CASE("SBML lowers consuming delay with an empty initial history gate") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    io::SbmlWriter::Options options;
    options.startTime = 5.0;
    const auto xml = io::SbmlWriter::write(*model, &network, options);

    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("R1_init"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("R1_complete"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
                        "<modifierSpeciesReference species=\"S1\"/>"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("<csymbol encoding=\"text\" definitionURL=\"http://www.sbml.org/sbml/symbols/delay\"> delay </csymbol>"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("<cn> 5 </cn>"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("<apply><geq/>"));

    options.level = 2;
    const auto level2 = io::SbmlWriter::write(*model, &network, options);
    CHECK_THAT(level2, Catch::Matchers::ContainsSubstring(
                           "definitionURL=\"http://www.sbml.org/sbml/symbols/delay\""));
}

TEST_CASE("SBML action defaults to a valid version for Level 3") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    model->addAction(ast::Action{"writeSBML", {{"level", "3"}}});
    const auto sourcePath = std::filesystem::temp_directory_path() / "bng3-delay-action.bngl";
    actions::ActionDispatch::execute(*model, sourcePath);
    const auto outputPath = sourcePath.parent_path() / "bng3-delay-action_sbml.xml";
    CHECK_THAT(readFile(outputPath), Catch::Matchers::ContainsSubstring(
                                       "level=\"3\" version=\"2\""));
    std::filesystem::remove(outputPath);
}

TEST_CASE("native ODE applies consuming delayed reaction completions") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    const auto a = speciesIndex(network, "A");
    const auto b = speciesIndex(network, "B");
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = 0.0;
    options.tEnd = 4.0;
    options.nSteps = 8;
    const auto result = integrator.integrate(options);
    const auto& initial = result.concentrations.front();
    const auto& atDelay = result.concentrations[4];
    const auto& final = result.concentrations.back();
    CHECK(initial[a] == Catch::Approx(10.0));
    CHECK(initial[b] == Catch::Approx(0.0));
    CHECK(atDelay[a] == Catch::Approx(10.0 * std::exp(-1.0)).epsilon(1e-5));
    CHECK(atDelay[b] == Catch::Approx(0.0).margin(1e-7));
    CHECK(final[a] == Catch::Approx(10.0 * std::exp(-2.0)).epsilon(1e-5));
    CHECK(final[b] == Catch::Approx(10.0 * (1.0 - std::exp(-1.0))).epsilon(1e-5));
}

TEST_CASE("native ODE nonconsuming reaction waits for delayed completion") {
    auto model = parse("G() -> G() + M() 0.5 delay=tau NonConsuming");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    const auto m = speciesIndex(network, "M");
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = 0.0;
    options.tEnd = 4.0;
    options.nSteps = 8;
    const auto result = integrator.integrate(options);
    CHECK(result.concentrations[4][m] == Catch::Approx(0.0).margin(1e-7));
    CHECK(result.concentrations.back()[m] == Catch::Approx(2.0).epsilon(1e-5));
}

TEST_CASE("native ODE continuation preserves delayed history and reset clears it") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    auto splitNetwork = generator.generateNative();
    auto wholeNetwork = splitNetwork;
    const auto a = speciesIndex(splitNetwork, "A");
    const auto b = speciesIndex(splitNetwork, "B");
    engine::OdeIntegrator splitIntegrator(*model, splitNetwork);
    engine::OdeOptions first;
    first.method = "cvode";
    first.tEnd = 2.0;
    first.nSteps = 4;
    const auto firstResult = splitIntegrator.integrate(first);
    engine::OdeOptions second = first;
    second.tStart = 2.0;
    second.tEnd = 4.0;
    second.continueSimulation = true;
    auto rejected = second;
    rejected.method = "euler";
    CHECK_THROWS_WITH(splitIntegrator.integrate(rejected),
                      Catch::Matchers::ContainsSubstring(
                          "Delayed reactions require the CVODE ODE method"));
    const auto continued = splitIntegrator.integrate(second);

    engine::OdeIntegrator wholeIntegrator(*model, wholeNetwork);
    engine::OdeOptions whole = first;
    whole.tEnd = 4.0;
    whole.nSteps = 8;
    const auto unsplit = wholeIntegrator.integrate(whole);
    REQUIRE(!firstResult.concentrations.empty());
    CHECK(firstResult.concentrations.back()[b] == Catch::Approx(0.0).margin(1e-7));
    CHECK(continued.concentrations.back()[a] ==
          Catch::Approx(unsplit.concentrations.back()[a]).epsilon(1e-7));
    CHECK(continued.concentrations.back()[b] ==
          Catch::Approx(unsplit.concentrations.back()[b]).epsilon(1e-7));

    splitNetwork.resetSimulationSession();
    splitNetwork.species.get(a).setAmount(10.0);
    splitNetwork.species.get(b).setAmount(0.0);
    engine::OdeOptions reset = first;
    reset.tEnd = 2.0;
    reset.nSteps = 4;
    const auto resetResult = splitIntegrator.integrate(reset);
    CHECK(resetResult.concentrations.back()[b] == Catch::Approx(0.0).margin(1e-7));
}

TEST_CASE("delayed ODE completion uses the historical parameter coefficient") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
  tau 2
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> B() k delay=tau
end reaction rules
end model
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    const auto b = speciesIndex(network, "B");
    engine::OdeIntegrator firstIntegrator(*model, network);
    engine::OdeOptions first;
    first.method = "cvode";
    first.tEnd = 1.0;
    first.nSteps = 10;
    const auto firstResult = firstIntegrator.integrate(first);
    REQUIRE(firstResult.concentrations.size() == 11);
    model->getParameters().all().at(1).setValue(1.0);

    engine::OdeIntegrator continuedIntegrator(*model, network);
    engine::OdeOptions continuation = first;
    continuation.tStart = 1.0;
    continuation.tEnd = 3.0;
    continuation.nSteps = 20;
    continuation.continueSimulation = true;
    const auto continued = continuedIntegrator.integrate(continuation);
    CHECK(continued.concentrations.back()[b] ==
          Catch::Approx(10.0 * (1.0 - std::exp(-0.5))).epsilon(1e-5));
}

TEST_CASE("native delayed event execution survives an ODE continuation") {
    auto model = parser::parseModel(R"(
begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 0
end seed species
begin observables
  Molecules A_count A()
end observables
begin bng3_events version 1
  event "later"
    trigger: time >= 0.5
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    delay: 1
    assignment: A_count = 5
  end event
end bng3_events
end model
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    const auto a = speciesIndex(network, "A");
    engine::OdeIntegrator firstIntegrator(*model, network);
    engine::OdeOptions first;
    first.method = "cvode";
    first.tEnd = 1.0;
    first.nSteps = 10;
    const auto firstResult = firstIntegrator.integrate(first);
    CHECK(firstResult.concentrations.back()[a] == Catch::Approx(0.0));

    engine::OdeIntegrator continuedIntegrator(*model, network);
    engine::OdeOptions continuation = first;
    continuation.tStart = 1.0;
    continuation.tEnd = 2.0;
    continuation.continueSimulation = true;
    const auto continued = continuedIntegrator.integrate(continuation);
    CHECK(continued.concentrations.back()[a] == Catch::Approx(5.0));
}

TEST_CASE("action continue preserves delayed SSA completions across legs") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
  tau 2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin observables
  Molecules B_count B()
end observables
begin reaction rules
  A() -> B() 1000000 delay=tau
end reaction rules
end model
)");
    model->addAction(ast::Action{"simulate", {
        {"method", "ssa"}, {"t_end", "1"}, {"n_steps", "2"},
        {"seed", "17"}, {"prefix", "bng3_delayed_action"}}});
    model->addAction(ast::Action{"simulate", {
        {"method", "ssa"}, {"t_end", "2"}, {"n_steps", "4"},
        {"seed", "17"}, {"prefix", "bng3_delayed_action"},
        {"continue", "1"}}});
    const auto source = std::filesystem::temp_directory_path() /
                        "bng3_delayed_action.bngl";
    CHECK_NOTHROW(actions::ActionDispatch::execute(*model, source));
    const auto output = source.parent_path() / "bng3_delayed_action.gdat";
    std::istringstream data(readFile(output));
    std::string line;
    double finalTime = -1.0;
    double finalB = -1.0;
    while (std::getline(data, line)) {
        if (line.empty() || line.front() == '#') continue;
        std::istringstream row(line);
        double time = 0.0;
        double b = 0.0;
        if (row >> time >> b) {
            finalTime = time;
            finalB = b;
        }
    }
    CHECK(finalTime == Catch::Approx(3.0));
    CHECK(finalB == 1.0);
    std::filesystem::remove(output);
}

TEST_CASE("native event triggers and assignments evaluate historical delay expressions") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
  tau 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
  B() 0
end seed species
begin observables
  Molecules Aobs A()
  Molecules B_count B()
end observables
begin functions
  delayed(x) delay(x, tau)
end functions
begin reaction rules
  A() -> 0 1
end reaction rules
begin bng3_events version 1
  event "delayed_threshold"
    trigger: delayed(Aobs) < 0.5
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: B_count = delayed(Aobs)
  end event
end bng3_events
end model
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    const auto b = speciesIndex(network, "B");
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 3.0;
    options.nSteps = 30;
    const auto result = integrator.integrate(options);
    CHECK(result.concentrations.back()[b] == Catch::Approx(0.5).epsilon(2e-5));
}

TEST_CASE("direct SSA consumes at initiation and completes with zero propensity") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
  tau 2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin reaction rules
  A() -> B() 1000000 delay=tau
end reaction rules
end model
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    const auto a = speciesIndex(network, "A");
    const auto b = speciesIndex(network, "B");
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "ssa";
    options.seed = 17;
    options.tStart = 5.0;
    options.tEnd = 8.0;
    options.nSteps = 6;
    const auto result = integrator.integrate(options);
    REQUIRE(result.concentrations.size() == 7);
    CHECK(result.concentrations.front()[a] == 1.0);
    CHECK(result.concentrations.front()[b] == 0.0);
    CHECK(result.concentrations[4][a] == 0.0);
    CHECK(result.concentrations[4][b] == 0.0);
    CHECK(result.concentrations.back()[b] == 1.0);
}

TEST_CASE("direct SSA delayed completion laws match binomial and Poisson oracles") {
    constexpr std::size_t runs = 512;
    std::uint64_t consumingTotal = 0;
    std::uint64_t nonconsumingTotal = 0;
    for (std::size_t run = 0; run < runs; ++run) {
        {
            auto model = parse("A() -> B() 0.5 delay=tau");
            engine::NetworkGenerator generator(*model);
            auto network = generator.generateNative();
            const auto b = speciesIndex(network, "B");
            engine::OdeIntegrator integrator(*model, network);
            engine::OdeOptions options;
            options.method = "ssa";
            options.seed = static_cast<int>(run + 1);
            options.tEnd = 4.0;
            options.nSteps = 2;
            const auto result = integrator.integrate(options);
            consumingTotal += static_cast<std::uint64_t>(
                result.concentrations.back()[b]);
        }
        {
            auto model = parse("G() -> G() + M() 0.5 delay=tau NonConsuming");
            engine::NetworkGenerator generator(*model);
            auto network = generator.generateNative();
            const auto m = speciesIndex(network, "M");
            engine::OdeIntegrator integrator(*model, network);
            engine::OdeOptions options;
            options.method = "ssa";
            options.seed = static_cast<int>(run + 1);
            options.tEnd = 4.0;
            options.nSteps = 2;
            const auto result = integrator.integrate(options);
            nonconsumingTotal += static_cast<std::uint64_t>(
                result.concentrations.back()[m]);
        }
    }
    constexpr double familywiseAlpha = 0.01;
    constexpr double perTailAlpha = familywiseAlpha / 4.0;
    const double consumingTrials = 10.0 * runs;
    const double consumingProbability = 1.0 - std::exp(-1.0);
    const double consumingMean = consumingTrials * consumingProbability;
    const double consumingDeviation = std::sqrt(
        consumingTrials * std::log(2.0 / (familywiseAlpha / 2.0)) / 2.0);
    const auto consumingLower = static_cast<std::uint64_t>(
        std::floor(consumingMean - consumingDeviation));
    const auto consumingUpper = static_cast<std::uint64_t>(
        std::ceil(consumingMean + consumingDeviation));
    const double nonconsumingMean = 2.0 * runs;
    const double nonconsumingDeviation = poissonChernoffDeviation(
        nonconsumingMean, perTailAlpha);
    CHECK(consumingTotal >= consumingLower);
    CHECK(consumingTotal <= consumingUpper);
    CHECK(nonconsumingTotal >= static_cast<std::uint64_t>(
                                   std::floor(nonconsumingMean - nonconsumingDeviation)));
    CHECK(nonconsumingTotal <= static_cast<std::uint64_t>(
                                   std::ceil(nonconsumingMean + nonconsumingDeviation)));
}

TEST_CASE("direct SSA continuation preserves its queue and random stream") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    auto splitNetwork = generator.generateNative();
    auto wholeNetwork = splitNetwork;
    engine::OdeIntegrator splitIntegrator(*model, splitNetwork);
    engine::OdeOptions first;
    first.method = "ssa";
    first.seed = 29;
    first.tEnd = 2.0;
    first.nSteps = 2;
    const auto firstResult = splitIntegrator.integrate(first);
    engine::OdeOptions second = first;
    second.tStart = 2.0;
    second.tEnd = 4.0;
    second.continueSimulation = true;
    const auto continued = splitIntegrator.integrate(second);

    engine::OdeIntegrator wholeIntegrator(*model, wholeNetwork);
    engine::OdeOptions whole = first;
    whole.tEnd = 4.0;
    whole.nSteps = 4;
    const auto unsplit = wholeIntegrator.integrate(whole);
    REQUIRE(!firstResult.concentrations.empty());
    REQUIRE(!continued.concentrations.empty());
    REQUIRE(!unsplit.concentrations.empty());
    CHECK(continued.concentrations.back() == unsplit.concentrations.back());

    splitNetwork.resetSimulationSession();
    splitNetwork.species.get(speciesIndex(splitNetwork, "A")).setAmount(10.0);
    engine::OdeOptions reset = first;
    reset.continueSimulation = false;
    reset.tEnd = 1.0;
    const auto resetResult = splitIntegrator.integrate(reset);
    CHECK(resetResult.concentrations.front()[speciesIndex(splitNetwork, "A")] == 10.0);
}

TEST_CASE("SSA and PSA retain explicit delayed-reaction backend boundaries") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    CHECK_NOTHROW(engine::CpuBatchSsaSimulator(*model, network));
    CHECK_THROWS_WITH(engine::PsaSimulator(*model, network),
                      Catch::Matchers::ContainsSubstring("not supported by PSA"));
}

TEST_CASE("native ODE evaluates the whole delay expression from historical states") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
  tau 1
  lambda 1
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin observables
  Molecules Aobs A()
end observables
begin functions
  doubled(x) 2*x
end functions
begin reaction rules
  A() -> 0 lambda
  0 -> B() k*delay(doubled(Aobs), tau)
end reaction rules
end model
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    const auto a = speciesIndex(network, "A");
    const auto b = speciesIndex(network, "B");
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 3.0;
    options.nSteps = 30;
    const auto result = integrator.integrate(options);
    CHECK(result.concentrations[10][a] == Catch::Approx(std::exp(-1.0)).epsilon(1e-5));
    CHECK(result.concentrations[10][b] == Catch::Approx(2.0).epsilon(1e-5));
    const double expected = 2.0 + 2.0 * (1.0 - std::exp(-2.0));
    CHECK(result.concentrations.back()[b] == Catch::Approx(expected).epsilon(1e-5));
}

TEST_CASE("ODE collects parameterized function delays with sparse output") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
  tau 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin observables
  Molecules Aobs A()
end observables
begin functions
  delayed(x, d) delay(x, d)
end functions
begin reaction rules
  A() -> 0 1
  0 -> B() delayed(Aobs, tau)
end reaction rules
end model
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    const auto b = speciesIndex(network, "B");
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 4.0;
    options.nSteps = 1;
    const auto result = integrator.integrate(options);
    REQUIRE(result.timePoints.size() == 2);
    // SBML prehistory holds A=1 through t=1; afterward the delayed source is
    // exp(-(t-1)), giving 1 + (1-exp(-3)) total at t=4.
    CHECK(result.concentrations.back()[b] ==
          Catch::Approx(2.0 - std::exp(-3.0)).epsilon(1e-5));
    options.method = "rk4";
    CHECK_THROWS_WITH(engine::OdeIntegrator(*model, network).integrate(options),
                      Catch::Matchers::ContainsSubstring(
                          "delay(expr, tau) requires the CVODE ODE method"));
}

TEST_CASE("nested function delay uses historical parameter values") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
  tau 2
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin observables
  Molecules Aobs A()
end observables
begin functions
  delayed(x) delay(x, tau)
end functions
begin reaction rules
  0 -> B() delayed(k*Aobs)
end reaction rules
end model
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    const auto b = speciesIndex(network, "B");
    engine::OdeIntegrator firstIntegrator(*model, network);
    engine::OdeOptions first;
    first.method = "cvode";
    first.tEnd = 1.0;
    first.nSteps = 5;
    REQUIRE_NOTHROW(firstIntegrator.integrate(first));
    model->getParameters().all().at(1).setValue(1.0);

    engine::OdeIntegrator continuedIntegrator(*model, network);
    engine::OdeOptions continuation = first;
    continuation.tStart = 1.0;
    continuation.tEnd = 3.0;
    continuation.continueSimulation = true;
    const auto continued = continuedIntegrator.integrate(continuation);
    // The delayed source still sees k=0.5 for source times through t=1;
    // this contributes 0.5 on [0,1] and the same on the continued [1,3].
    CHECK(continued.concentrations.back()[b] == Catch::Approx(1.5).epsilon(1e-5));
}

TEST_CASE("method of steps propagates breakpoints through summed delays") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
  tau1 0.7
  tau2 0.9
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin observables
  Molecules Aobs A()
end observables
begin reaction rules
  A() -> 0 1
  0 -> B() delay(delay(Aobs, tau1), tau2)
end reaction rules
end model
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    const auto b = speciesIndex(network, "B");
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 4.0;
    options.nSteps = 1;
    const auto result = integrator.integrate(options);
    CHECK(result.concentrations.back()[b] ==
          Catch::Approx(2.6 - std::exp(-2.4)).epsilon(2e-5));
}

TEST_CASE("network exporters refuse delay metadata even when the AST lacks the rule") {
    auto delayedModel = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*delayedModel);
    const auto delayedNetwork = generator.generateNative();
    auto ordinaryModel = parse("A() -> B() 0.5");
    CHECK_THROWS_WITH(io::CppExportWriter::write(*ordinaryModel, delayedNetwork),
                      Catch::Matchers::ContainsSubstring(
                          "Delayed reactions are not supported by C++ export"));
}

TEST_CASE("native ODE validates delayed parameter values at execution time") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    model->getParameters().all().front().setValue(-1.0);
    CHECK_THROWS_WITH(engine::OdeIntegrator(*model, network),
                      Catch::Matchers::ContainsSubstring("finite and nonnegative"));
}


TEST_CASE("CPU SSA batches isolate delayed completion queues across workers") {
    constexpr std::size_t batchSize = 64;
    const auto run = [&](const std::string& rule, unsigned int workers) {
        auto model = parse(rule);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        engine::CpuBatchSsaSimulator simulator(*model, network);
        engine::BatchSsaOptions options;
        options.batchSize = batchSize;
        options.tEnd = 4.0;
        options.nSteps = 4;
        options.baseSeed = 2718;
        return workers == 1
            ? simulator.simulateSingleWorker(options)
            : simulator.simulateMultiCore(options, workers);
    };
    for (const auto* rule : {"A() -> B() 0.5 delay=tau",
                             "G() -> G() + M() 0.5 delay=tau NonConsuming"}) {
        const auto serial = run(rule, 1);
        const auto parallel = run(rule, 4);
        const auto repeatedParallel = run(rule, 4);
        REQUIRE(serial.trajectoryEventCounts.size() == batchSize);
        CHECK(serial.trajectoryEventCounts == parallel.trajectoryEventCounts);
        CHECK(parallel.trajectoryEventCounts == repeatedParallel.trajectoryEventCounts);
        CHECK(serial.finalSpecies == parallel.finalSpecies);
        CHECK(serial.finalObservables == parallel.finalObservables);
        CHECK(serial.totalEvents == parallel.totalEvents);

        auto oracleModel = parse(rule);
        engine::NetworkGenerator oracleGenerator(*oracleModel);
        const auto oracleNetwork = oracleGenerator.generateNative();
        const auto delayedProduct = speciesIndex(
            oracleNetwork, rule[0] == 'A' ? "B" : "M");
        for (std::size_t trajectory = 0; trajectory < batchSize; ++trajectory) {
            engine::OdeIntegrator direct(*oracleModel, oracleNetwork);
            engine::OdeOptions directOptions;
            directOptions.method = "ssa";
            directOptions.tEnd = 4.0;
            directOptions.nSteps = 4;
            directOptions.seed = engine::batchTrajectoryEngineSeed(2718, trajectory);
            const auto directResult = direct.integrate(directOptions);
            CHECK(directResult.concentrations[2][delayedProduct] == 0.0);
            CHECK(serial.finalSpecies[trajectory * oracleNetwork.species.size() +
                                      delayedProduct] ==
                  static_cast<std::int32_t>(std::round(
                      directResult.concentrations.back()[delayedProduct])));
        }

        auto model = parse(rule);
        engine::NetworkGenerator generator(*model);
        auto network = generator.generateNative();
        engine::OdeIntegrator integrator(*model, network);
        engine::OdeOptions options;
        options.method = "ssa";
        options.batchSize = batchSize;
        options.batchGpuPreferred = false;
        options.tEnd = 4.0;
        options.nSteps = 4;
        options.seed = 2718;
        const auto batch = integrator.integrate(options);
        const auto repeatedBatch = integrator.integrate(options);
        CHECK(batch.concentrations == repeatedBatch.concentrations);
        CHECK(batch.eventCount == repeatedBatch.eventCount);
    }
}

TEST_CASE("delayed SSA continuation is restricted to one trajectory") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);

    engine::OdeOptions batch;
    batch.method = "ssa";
    batch.batchSize = 2;
    batch.continueSimulation = true;
    CHECK_THROWS_WITH(integrator.integrate(batch),
                      Catch::Matchers::ContainsSubstring(
                          "continue_simulation is not supported for batch SSA"));

    engine::OdeOptions isolated;
    isolated.method = "ssa";
    isolated.isolatedTrajectory = true;
    isolated.continueSimulation = true;
    CHECK_THROWS_WITH(integrator.integrate(isolated),
                      Catch::Matchers::ContainsSubstring(
                          "continue_simulation is not supported for isolated trajectories"));
}

TEST_CASE("continuation applies an explicit species reset to the seed amount") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    const auto a = speciesIndex(network, "A");
    const auto b = speciesIndex(network, "B");
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions first;
    first.method = "cvode";
    first.tEnd = 1.0;
    first.nSteps = 10;
    const auto firstResult = integrator.integrate(first);
    for (std::size_t i = 0; i < network.species.size(); ++i) {
        network.species.get(i).setAmount(firstResult.concentrations.back()[i]);
    }
    network.species.get(a).setAmount(10.0);
    engine::OdeOptions continuation = first;
    continuation.tStart = 1.0;
    continuation.tEnd = 3.0;
    continuation.nSteps = 20;
    continuation.continueSimulation = true;
    const auto result = integrator.integrate(continuation);
    CHECK(result.concentrations.back()[a] ==
          Catch::Approx(10.0 * std::exp(-1.0)).epsilon(1e-5));
    CHECK(result.concentrations.back()[b] ==
          Catch::Approx(10.0 * (1.0 - std::exp(-0.5))).epsilon(1e-5));
}
