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

} // namespace nfnext
