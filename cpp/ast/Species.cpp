#include "Species.hpp"

#include <utility>

namespace bng::ast {

Species::Species(SpeciesGraph graph, double amount, bool constant, std::string compartment)
    : graph_(std::move(graph)),
      amount_(amount),
      constant_(constant),
      compartment_(std::move(compartment)) {
    // Propagate species-level compartment to the SpeciesGraph for string generation
    if (!compartment_.empty() && graph_.getCompartment().empty()) {
        graph_.setCompartment(compartment_);
    }
}

const SpeciesGraph& Species::getSpeciesGraph() const {
    return graph_;
}

SpeciesGraph& Species::getSpeciesGraph() {
    return graph_;
}

double Species::getAmount() const {
    return amount_;
}

void Species::setAmount(double amount) {
    amount_ = amount;
    ++amountVersion_;
}

std::uint64_t Species::getAmountVersion() const {
    return amountVersion_;
}

bool Species::isConstant() const {
    return constant_;
}

const std::string& Species::getCompartment() const {
    return compartment_;
}

void Species::setCompartment(std::string compartment) {
    compartment_ = std::move(compartment);
}

std::string Species::canonicalName() const {
    // Perl convention (bng2/Perl2/SpeciesGraph.pm: toString): the species
    // compartment prefixes the name, the constant marker follows it, and a
    // molecule whose compartment differs from the species compartment carries
    // an explicit @compartment suffix.
    std::string result;
    if (!compartment_.empty()) {
        result += "@" + compartment_ + "::";
    }
    if (constant_) {
        result += "$";
    }

    std::vector<std::string> molCompartments;
    std::string speciesStr = graph_.getGraph().get_BNG2_string(molCompartments);

    if (!compartment_.empty() && !molCompartments.empty()) {
        std::string annotated;
        std::size_t molIdx = 0;
        std::size_t pos = 0;
        while (pos < speciesStr.size()) {
            int parenDepth = 0;
            std::size_t molEnd = pos;
            while (molEnd < speciesStr.size()) {
                if (speciesStr[molEnd] == '(') parenDepth++;
                else if (speciesStr[molEnd] == ')') parenDepth--;
                else if (speciesStr[molEnd] == '.' && parenDepth == 0) break;
                molEnd++;
            }

            annotated += speciesStr.substr(pos, molEnd - pos);

            if (molIdx < molCompartments.size() &&
                !molCompartments[molIdx].empty() &&
                molCompartments[molIdx] != compartment_) {
                annotated += "@" + molCompartments[molIdx];
            }

            if (molEnd < speciesStr.size() && speciesStr[molEnd] == '.') {
                annotated += '.';
                molEnd++;
            }

            pos = molEnd;
            molIdx++;
        }
        speciesStr = annotated;
    }

    result += speciesStr;
    return result;
}

std::size_t Species::getIndex() const {
    return index_;
}

void Species::setIndex(std::size_t index) {
    index_ = index;
}

bool Species::rulesApplied() const {
    return rulesApplied_;
}

void Species::setRulesApplied(bool value) {
    rulesApplied_ = value;
}

} // namespace bng::ast
