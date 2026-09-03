#include "MoleculeType.hpp"

#include <algorithm>
#include <map>
#include <utility>

namespace bng::ast {

MoleculeType::MoleculeType(std::string name, std::vector<ComponentType> components, bool population)
    : name_(std::move(name)), components_(std::move(components)), population_(population) {}

const std::string& MoleculeType::getName() const {
    return name_;
}

const std::vector<ComponentType>& MoleculeType::getComponents() const {
    return components_;
}

bool MoleculeType::isPopulation() const {
    return population_;
}

void MoleculeType::mergeInferredComponents(const std::vector<ComponentType>& components) {
    std::map<std::string, std::size_t> incomingCounts;
    std::map<std::string, std::vector<std::string>> mergedStates;

    for (const auto& component : components_) {
        auto& states = mergedStates[component.name];
        for (const auto& state : component.allowedStates) {
            if (std::find(states.begin(), states.end(), state) == states.end()) {
                states.push_back(state);
            }
        }
    }
    for (const auto& component : components) {
        ++incomingCounts[component.name];
        auto& states = mergedStates[component.name];
        for (const auto& state : component.allowedStates) {
            if (std::find(states.begin(), states.end(), state) == states.end()) {
                states.push_back(state);
            }
        }
    }

    std::map<std::string, std::size_t> currentCounts;
    for (auto& component : components_) {
        const auto states = mergedStates.find(component.name);
        if (states != mergedStates.end()) {
            component.allowedStates = states->second;
        }
        ++currentCounts[component.name];
    }

    for (const auto& [name, incomingCount] : incomingCounts) {
        const auto currentCount = currentCounts[name];
        const auto requestedCount = std::max(currentCount, incomingCount);
        if (requestedCount <= currentCount) {
            continue;
        }
        const auto& states = mergedStates[name];
        for (std::size_t index = currentCount; index < requestedCount; ++index) {
            components_.push_back(ComponentType {name, states});
        }
    }
}

} // namespace bng::ast
