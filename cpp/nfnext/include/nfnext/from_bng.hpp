#pragma once

#include "nfnext/nfir.hpp"

#include <string>
#include <vector>

namespace bng::compile { class CompiledModel; }

namespace nfnext {

enum class BngLoweringSeverity : std::uint8_t {
    Warning = 0,
    Error = 1,
};

struct BngLoweringIssue {
    BngLoweringSeverity severity{BngLoweringSeverity::Error};
    std::string entity;
    std::string message;
};

struct BngLoweringResult {
    ModelIR model;
    std::vector<BngLoweringIssue> issues;

    bool ok() const noexcept;
};

// Lower the backend-independent BioNetGen compiled model into NFnext's
// execution-oriented NFIR. Unsupported semantic constructs fail closed: a
// rule that cannot be represented losslessly is omitted and reported as an
// error instead of being approximated.
BngLoweringResult lowerFromBioNetGen(const bng::compile::CompiledModel& model);

// Explicit protocol for the opt-in unary site-state executor. Times are absolute
// from initial time zero; rows include time followed by declared observables.
// BNGL action sequences are not accepted or implicitly executed by this API.
struct BngExecutionRequest {
    std::vector<double> sample_times;
    std::uint64_t seed{0};
    std::uint64_t max_events{1'000'000};
    std::size_t max_particles{1'000'000};
};

struct BngExecutionResult {
    std::vector<std::string> columns;
    std::vector<std::vector<double>> rows;
    std::uint64_t event_count{0};
};

// Executes only static-rate unary site-state rules, isolated integer seed
// populations and unary Molecules observables. All other semantics throw.
BngExecutionResult executeFromBioNetGen(const bng::compile::CompiledModel& model,
                                      const BngExecutionRequest& request);

} // namespace nfnext
