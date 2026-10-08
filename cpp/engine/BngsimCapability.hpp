#pragma once

#include <string>
#include <utility>
#include <vector>

#include "ast/Model.hpp"
#include "FiniteBackend.hpp"
#include "NetworkGenerator.hpp"

namespace bng::engine {

enum class BngsimRateKind {
    Parameter,
    Function,
};

struct BngsimRateReference {
    BngsimRateKind kind;
    std::string name;
};

std::string bngsimReactionContext(std::size_t index, const ast::Rxn& reaction);
std::vector<int> checkedBngsimIndices(
    const std::vector<std::size_t>& indices,
    std::size_t speciesCount,
    const std::string& context);
std::vector<std::pair<int, double>> compileBngsimObservableEntries(
    ast::Model& model,
    const GeneratedNetwork& network,
    const ast::Observable& observable);
std::string bngsimTableCounterName(const ast::Expression& counter);
BngsimRateReference resolveBngsimRateReference(
    const ast::Model& model,
    const ast::Rxn& reaction,
    std::size_t index);

} // namespace bng::engine
