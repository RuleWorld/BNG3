#pragma once

#include <cstddef>
#include <functional>
#include <string>
#include <vector>

#include "RateCandidateContext.hpp"

namespace BNGcore {
class Node;
class PatternGraph;
}

namespace bng::compile {

// The compile-owned execution contract for one compiled rule direction.
//
// The compiled semantic model already decides everything the network
// expansion needs to know about a rule: which reactant and product patterns
// it matches, which filters it declares, which local scopes its rate law
// reads, and which candidates have a structurally zero rate. This contract
// carries those decisions in compile-owned types, so an executor never has to
// recover them by reconstructing a legacy AST rule and re-deriving its
// semantics from source text.
//
// Every callback is optional. An executor that is handed an unset callback
// keeps its own default behaviour; the contract never silently changes one.
struct CompiledRuleExecutionHooks {
    // Reject a reactant match that does not satisfy the rule's filters.
    std::function<bool(std::size_t, const BNGcore::PatternGraph &)> reactantFilter;
    // Reject a generated product set that does not satisfy the rule's filters.
    std::function<bool(const std::vector<const BNGcore::PatternGraph *> &)>
        productFilter;
    // Distinguish embeddings whose scoped local observable counts differ, so
    // reactions with different local rates are not merged into one.
    std::function<std::string(std::size_t, std::size_t, const BNGcore::Node *,
                              const BNGcore::PatternGraph &)>
        localRateFingerprint;
    std::function<std::string(std::size_t, std::size_t, const BNGcore::Node *,
                              const BNGcore::PatternGraph &)>
        productScopeMatchSignature;
    std::function<std::string(const std::vector<const BNGcore::PatternGraph *> &,
                              const std::vector<std::size_t> &)>
        productLocalRateFingerprint;
    // Reject a candidate whose compiled rate law is structurally zero.
    std::function<bool(const RateCandidateContext &)> rejectZeroRate;
};

} // namespace bng::compile
