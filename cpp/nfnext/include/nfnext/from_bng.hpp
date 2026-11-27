#pragma once

#include "nfnext/nfir.hpp"

#include <memory>
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

// Execute one trajectory initialized at start_time. Sample times are absolute
// and the output rows contain time followed by declared observables.
struct BngExecutionState;

struct BngExecutionRequest {
    std::vector<double> sample_times;
    std::uint64_t seed{0};
    std::uint64_t max_events{1'000'000};
    std::size_t max_particles{1'000'000};
    double start_time{0.0};
    std::shared_ptr<const BngExecutionState> continuation;
    bool retain_state{false};
    // When nonzero, keep at most this many particle molecules of each mapped
    // type in the graph and hold the remainder in its lumped population.
    // Representation changes conserve total copies exactly. Zero disables the
    // reconcile step and preserves the prior execution semantics.
    std::uint64_t population_threshold{0};
};

struct BngExecutionResult {
    std::vector<std::string> columns;
    std::vector<std::vector<double>> rows;
    std::uint64_t event_count{0};
    std::shared_ptr<BngExecutionState> final_state;
};

// Execute through the network-free NFIR runtime with explicit diagnostics
// when the compiled model uses unsupported semantics.
BngExecutionResult executeFromBioNetGen(const bng::compile::CompiledModel& model,
                                      const BngExecutionRequest& request);

// Format the final particle and population species counts in BNG/NFsim
// .species text format (`<species> <count>` per line).
std::string formatFinalSpecies(const BngExecutionState& state);

} // namespace nfnext
