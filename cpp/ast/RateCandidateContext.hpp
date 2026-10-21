#pragma once

// The candidate-reaction context is compile-owned: it describes a candidate
// in the backend neutral graph vocabulary. This header keeps the historical
// ``bng::ast`` spelling available for AST-side callers.

#include "compile/RateCandidateContext.hpp"

namespace bng::ast {

using RateCandidateContext = compile::RateCandidateContext;

} // namespace bng::ast
