// The NFnext execution-boundary qualification of issue #148.
//
// NFnext is a bounded prototype: it lowers a production CompiledModel into its
// own IR and executes a narrow subset of the semantics.  This program
// qualifies what the prototype actually carries -- the supported seeds, the
// observables, the parameter graph, the protocol and the output contract --
// and exports the recorded trajectories so the validation harness can compare
// the production-lowered execution with the reference fixtures and with an
// independently built native NFsim.
//
// The supported subset is narrow on purpose: unary site-state rules with an
// elementary expression rate over the parameter graph, isolated integer seed
// populations and unary Molecules observables.  Everything else must be
// refused, and the refusals are recorded next to the executions so a
// silently widened subset cannot pass.
//
// The program is not a self-contained oracle: the reference expectation it
// checks is the independent pure-death count law of the model it states, and
// the exported artifact is consumed by tests/validation, which owns the
// comparison against the independent NFsim.

#include "compile/CompiledModel.hpp"
#include "nfnext/from_bng.hpp"
#include "parser/BNGAstVisitor.hpp"

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

constexpr std::size_t kSeeds = 64;

// The number of standard errors the reference comparison uses.  The recorded
// seed policy and run budget fix the sampling error, so the observed mean is
// accepted only when it is inside this many empirical standard errors of the
// independent count law and outside the same distance of the law a wrong rate
// would produce.
constexpr double kDiscriminationSigma = 4.0;

struct Fixture {
    std::string id;
    std::string source;
    std::uint64_t initial{0};
    double rate{0.0};
    std::vector<double> sample_times;
};

std::string fixtureSource(std::uint64_t initial, double rate) {
    std::ostringstream out;
    out << "begin parameters\n"
        << "  k " << rate << "\n"
        << "end parameters\n"
        << "begin molecule types\n"
        << "  A(x~u~p)\n"
        << "end molecule types\n"
        << "begin seed species\n"
        << "  A(x~u) " << initial << "\n"
        << "end seed species\n"
        << "begin observables\n"
        << "  Molecules U A(x~u)\n"
        << "  Molecules P A(x~p)\n"
        << "end observables\n"
        << "begin reaction rules\n"
        << "  A(x~u) -> A(x~p) k\n"
        << "end reaction rules\n";
    return out.str();
}

std::vector<Fixture> fixtures() {
    const std::vector<double> sample_times{0.0, 0.5, 1.0, 2.0};
    std::vector<Fixture> result;
    const std::vector<std::pair<std::uint64_t, double>> shapes{
        {100, 0.5}, {40, 0.25}, {200, 1.0}};
    for (const auto& [initial, rate] : shapes) {
        Fixture fixture;
        fixture.id = "nfnext-unary-site-state-n" + std::to_string(initial) +
                     "-k" + std::to_string(rate);
        fixture.source = fixtureSource(initial, rate);
        fixture.initial = initial;
        fixture.rate = rate;
        fixture.sample_times = sample_times;
        result.push_back(std::move(fixture));
    }
    return result;
}

std::string jsonEscape(const std::string& text) {
    std::string out;
    for (const char character : text) {
        switch (character) {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default: out += character; break;
        }
    }
    return out;
}

std::string jsonNumber(double value) {
    std::ostringstream out;
    out.precision(17);
    out << value;
    return out.str();
}

struct Execution {
    bool executed{false};
    std::string reason;
    std::vector<std::string> columns;
    std::vector<std::vector<double>> rows;
    std::vector<std::uint64_t> seeds;
    std::vector<double> final_unphosphorylated;
    std::size_t rows_per_execution{0};
    double observed_mean{0.0};
    double observed_standard_error{0.0};
};

Execution executeFixture(const Fixture& fixture) {
    Execution execution;
    execution.seeds.reserve(kSeeds);
    for (std::uint64_t index = 0; index < kSeeds; ++index) {
        execution.seeds.push_back(index);
    }
    const auto ast = bng::parser::parseModel(fixture.source);
    if (!ast) {
        execution.reason = "the fixture source did not parse";
        return execution;
    }
    const bng::compile::CompiledModel semantic(*ast);
    if (!semantic.valid()) {
        execution.reason = "the fixture source did not compile";
        return execution;
    }
    const auto lowered = nfnext::lowerFromBioNetGen(semantic);
    if (!lowered.ok()) {
        execution.reason = "the production lowering reported an error";
        return execution;
    }
    for (const std::uint64_t seed : execution.seeds) {
        nfnext::BngExecutionRequest request;
        request.sample_times = fixture.sample_times;
        request.seed = seed;
        try {
            const auto result = nfnext::executeFromBioNetGen(semantic, request);
            if (execution.columns.empty()) execution.columns = result.columns;
            if (result.columns != execution.columns) {
                execution.reason = "the output contract changed between seeds";
                return execution;
            }
            if (result.rows.empty()) {
                execution.reason = "the execution produced no rows";
                return execution;
            }
            if (execution.rows_per_execution == 0) {
                execution.rows_per_execution = result.rows.size();
            } else if (execution.rows_per_execution != result.rows.size()) {
                execution.reason = "the protocol produced a different row count "
                                   "between seeds";
                return execution;
            }
            execution.rows.push_back(result.rows.front());
            execution.final_unphosphorylated.push_back(result.rows.back()[1]);
        } catch (const std::exception& error) {
            execution.reason = std::string("the execution was refused: ") + error.what();
            return execution;
        }
    }
    double sum = 0.0;
    for (const double value : execution.final_unphosphorylated) sum += value;
    execution.observed_mean = sum / static_cast<double>(execution.final_unphosphorylated.size());
    double variance = 0.0;
    for (const double value : execution.final_unphosphorylated) {
        const double difference = value - execution.observed_mean;
        variance += difference * difference;
    }
    const std::size_t count = execution.final_unphosphorylated.size();
    execution.observed_standard_error =
        count > 1 ? std::sqrt(variance / static_cast<double>(count - 1)) /
                        std::sqrt(static_cast<double>(count))
                  : 0.0;
    execution.executed = true;
    return execution;
}

// The refusal controls: the parts of the model graph NFnext does not
// execute must be refused with a named reason, not silently ignored.
std::vector<std::pair<std::string, std::string>> refusals() {
    std::vector<std::pair<std::string, std::string>> result;
    const std::vector<std::pair<std::string, std::string>> cases{
        {"function-rate",
         "begin parameters\n  k 0.5\nend parameters\n"
         "begin molecule types\n  A(x~u~p)\nend molecule types\n"
         "begin seed species\n  A(x~u) 10\nend seed species\n"
         "begin observables\n  Molecules U A(x~u)\nend observables\n"
         "begin functions\n  f() 2*k\nend functions\n"
         "begin reaction rules\n  A(x~u) -> A(x~p) f()\nend reaction rules\n"},
        {"compartment",
         "begin parameters\n  k 0.5\nend parameters\n"
         "begin compartments\n  cell 3 1\nend compartments\n"
         "begin molecule types\n  A(x~u~p)\nend molecule types\n"
         "begin seed species\n  @cell:A(x~u) 10\nend seed species\n"
         "begin observables\n  Molecules U @cell:A(x~u)\nend observables\n"
         "begin reaction rules\n  @cell:A(x~u) -> @cell:A(x~p) k\nend reaction rules\n"},
        {"bonded-seed",
         "begin parameters\n  k 0.5\nend parameters\n"
         "begin molecule types\n  A(x~u~p)\n  B(y)\nend molecule types\n"
         "begin seed species\n  A(x~u!1).B(y!1) 10\nend seed species\n"
         "begin observables\n  Molecules U A(x~u)\nend observables\n"
         "begin reaction rules\n  A(x~u) -> A(x~p) k\nend reaction rules\n"}};
    for (const auto& [name, source] : cases) {
        const auto ast = bng::parser::parseModel(source);
        if (!ast) {
            result.emplace_back(name, "the refusal control did not parse");
            continue;
        }
        const bng::compile::CompiledModel semantic(*ast);
        nfnext::BngExecutionRequest request;
        request.sample_times = {0.0, 1.0};
        request.seed = 1;
        try {
            nfnext::executeFromBioNetGen(semantic, request);
            result.emplace_back(name, "");
        } catch (const std::exception& error) {
            result.emplace_back(name, error.what());
        }
    }
    return result;
}

} // namespace

int main(int argc, char** argv) {
    std::string artifact;
    if (argc > 1) {
        artifact = argv[1];
    } else if (const char* fromEnvironment = std::getenv("BNG3_NFNEXT_BOUNDARY_ARTIFACT")) {
        artifact = fromEnvironment;
    }
    bool failed = false;
    std::ostringstream json;
    json << "{\n  \"schema_version\": 1,\n";
    json << "  \"generated_by\": \"bng3_nfnext_execution_boundary\",\n";
    json << "  \"discrimination_sigma\": " << jsonNumber(kDiscriminationSigma) << ",\n";
    json << "  \"fixtures\": [\n";
    const auto all = fixtures();
    for (std::size_t index = 0; index < all.size(); ++index) {
        const Fixture& fixture = all[index];
        const Execution execution = executeFixture(fixture);
        const double finalTime = fixture.sample_times.back();
        const double reference = static_cast<double>(fixture.initial) *
                                 std::exp(-fixture.rate * finalTime);
        const double alternative = static_cast<double>(fixture.initial) *
                                   std::exp(-2.0 * fixture.rate * finalTime);
        const double standardError = execution.observed_standard_error;
        const bool within =
            execution.executed &&
            std::abs(execution.observed_mean - reference) <=
                kDiscriminationSigma * standardError;
        const bool separated =
            execution.executed &&
            std::abs(execution.observed_mean - alternative) >
                kDiscriminationSigma * standardError;
        const bool seeded =
            execution.executed && !execution.rows.empty() &&
            execution.rows.front().size() == 3 &&
            std::abs(execution.rows.front()[1] - static_cast<double>(fixture.initial)) < 1e-9 &&
            std::abs(execution.rows.front()[2]) < 1e-9;
        const bool contract = execution.executed &&
            execution.columns == std::vector<std::string>{"time", "U", "P"} &&
            execution.rows_per_execution == fixture.sample_times.size();
        if (!execution.executed || !within || !separated || !seeded || !contract) {
            failed = true;
            std::cerr << "nfnext execution boundary: fixture " << fixture.id
                      << " failed"
                      << " executed=" << (execution.executed ? "yes" : "no")
                      << " within=" << (within ? "yes" : "no")
                      << " separated=" << (separated ? "yes" : "no")
                      << " seeded=" << (seeded ? "yes" : "no")
                      << " contract=" << (contract ? "yes" : "no");
            if (!execution.reason.empty()) std::cerr << " reason=" << execution.reason;
            std::cerr << "\n";
        }
        json << "    {\n";
        json << "      \"id\": \"" << jsonEscape(fixture.id) << "\",\n";
        json << "      \"source\": \"" << jsonEscape(fixture.source) << "\",\n";
        json << "      \"initial\": " << fixture.initial << ",\n";
        json << "      \"rate\": " << jsonNumber(fixture.rate) << ",\n";
        json << "      \"sample_times\": [";
        for (std::size_t position = 0; position < fixture.sample_times.size(); ++position) {
            if (position) json << ", ";
            json << jsonNumber(fixture.sample_times[position]);
        }
        json << "],\n";
        json << "      \"columns\": [";
        for (std::size_t position = 0; position < execution.columns.size(); ++position) {
            if (position) json << ", ";
            json << "\"" << jsonEscape(execution.columns[position]) << "\"";
        }
        json << "],\n";
        json << "      \"initial_row\": [";
        if (!execution.rows.empty()) {
            for (std::size_t position = 0; position < execution.rows.front().size(); ++position) {
                if (position) json << ", ";
                json << jsonNumber(execution.rows.front()[position]);
            }
        }
        json << "],\n";
        json << "      \"seeds\": [";
        for (std::size_t position = 0; position < execution.seeds.size(); ++position) {
            if (position) json << ", ";
            json << execution.seeds[position];
        }
        json << "],\n";
        json << "      \"final_unphosphorylated\": [";
        for (std::size_t position = 0; position < execution.final_unphosphorylated.size(); ++position) {
            if (position) json << ", ";
            json << jsonNumber(execution.final_unphosphorylated[position]);
        }
        json << "],\n";
        json << "      \"observed_mean\": " << jsonNumber(execution.observed_mean) << ",\n";
        json << "      \"observed_standard_error\": " << jsonNumber(standardError) << ",\n";
        json << "      \"reference_mean\": " << jsonNumber(reference) << ",\n";
        json << "      \"alternative_mean\": " << jsonNumber(alternative) << ",\n";
        json << "      \"reason\": \"" << jsonEscape(execution.reason) << "\"\n";
        json << "    }" << (index + 1 < all.size() ? "," : "") << "\n";
    }
    json << "  ],\n";
    json << "  \"refusals\": [\n";
    const auto recorded = refusals();
    for (std::size_t index = 0; index < recorded.size(); ++index) {
        const bool refused = !recorded[index].second.empty();
        if (!refused) {
            failed = true;
            std::cerr << "nfnext execution boundary: refusal control "
                      << recorded[index].first << " was not refused\n";
        }
        json << "    {\"case\": \"" << jsonEscape(recorded[index].first) << "\", \"refused\": "
             << (refused ? "true" : "false") << ", \"reason\": \""
             << jsonEscape(recorded[index].second) << "\"}"
             << (index + 1 < recorded.size() ? "," : "") << "\n";
    }
    json << "  ]\n}\n";

    if (!artifact.empty()) {
        std::ofstream out(artifact);
        if (!out) {
            std::cerr << "nfnext execution boundary: cannot write the artifact "
                      << artifact << "\n";
            return 2;
        }
        out << json.str();
    } else {
        std::cout << json.str();
    }
    return failed ? 1 : 0;
}
