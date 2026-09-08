#include "nfsim_pattern_lowering.hh"

#include <algorithm>
#include <map>
#include <string>
#include <utility>

#include "../NFcore/NFcore.hh"
#include "../NFcore/templateMolecule.hh"

namespace NFcore2 {
namespace {

struct ResolvedSite {
    int state = NFcore::TemplateMolecule::NO_CONSTRAINT;
    int component = -1;
};

NFcore::MoleculeType* resolveMoleculeType(
    NFcore::System& system,
    const std::string& name,
    std::string& diagnostic) {
    try {
        return system.getMoleculeTypeByName(name);
    } catch (const std::exception& error) {
        diagnostic = "unknown molecule type '" + name + "': " + error.what();
        return nullptr;
    }
}

bool resolveComponent(
    NFcore::MoleculeType* moleculeType,
    const bng::compile::PatternSiteDescriptor& site,
    ResolvedSite& resolved,
    std::string& diagnostic) {
    std::string lookupName = site.componentName;
    if (moleculeType->isEquivalentComponent(lookupName)) {
        int* indices = nullptr;
        int count = 0;
        moleculeType->getEquivalencyClass(indices, count, lookupName);
        if (indices == nullptr || count == 0) {
            diagnostic = "could not resolve symmetric component '" + lookupName + "'";
            return false;
        }
        lookupName = moleculeType->getComponentName(indices[0]);
    }

    try {
        resolved.component = moleculeType->getCompIndexFromName(lookupName);
    } catch (const std::exception& error) {
        diagnostic = error.what();
        return false;
    }

    const auto& state = site.stateConstraint;
    if (state.empty() || state == "?" || state == "*") return true;

    const auto possibleStates = moleculeType->getPossibleCompStates();
    if (resolved.component < 0 ||
        static_cast<std::size_t>(resolved.component) >= possibleStates.size()) {
        diagnostic = "component state table is missing component '" +
                     site.componentName + "' on molecule type '" +
                     moleculeType->getName() + "'";
        return false;
    }
    int value = 0;
    bool found = false;
    for (const auto& candidate : possibleStates[static_cast<std::size_t>(resolved.component)]) {
        if (candidate == state) {
            found = true;
            break;
        }
        ++value;
    }
    if (!found) {
        diagnostic = "state '" + state + "' is not valid for component '" +
                     site.componentName + "' on molecule type '" +
                     moleculeType->getName() + "'";
        return false;
    }
    resolved.state = value;
    return true;
}

bool resolveCompartment(NFcore::System& system,
                        const std::string& name,
                        NFcore::Compartment*& compartment,
                        std::string& diagnostic) {
    compartment = nullptr;
    if (name.empty()) return true;
    compartment = system.getCompartment(name);
    if (compartment == nullptr) {
        diagnostic = "unknown compartment '" + name + "'";
        return false;
    }
    return true;
}

int symmetricBondState(bng::compile::BondConstraintKind kind) {
    using Kind = bng::compile::BondConstraintKind;
    switch (kind) {
    case Kind::Unbound:
    case Kind::Unspecified:
        return NFcore::TemplateMolecule::EMPTY;
    case Kind::Bound:
        return NFcore::TemplateMolecule::OCCUPIED;
    case Kind::Any:
    case Kind::Exact:
        return NFcore::TemplateMolecule::NO_CONSTRAINT;
    }
    return NFcore::TemplateMolecule::NO_CONSTRAINT;
}

void applyBondConstraint(NFcore::TemplateMolecule* templateMolecule,
                         const bng::compile::PatternSiteDescriptor& site,
                         const ResolvedSite& resolved,
                         std::size_t moleculeIndex,
                         std::size_t siteIndex) {
    using Kind = bng::compile::BondConstraintKind;
    const bool symmetric = templateMolecule->getMoleculeType()->isEquivalentComponent(
        site.componentName);
    if (!symmetric && resolved.state >= 0) {
        templateMolecule->addComponentConstraint(site.componentName, resolved.state);
    }

    const auto addConstraint = [&](Kind kind, std::size_t bondIndex) {
        if (symmetric) {
            templateMolecule->addSymCompConstraint(
                site.componentName,
                "m" + std::to_string(moleculeIndex) + "c" +
                    std::to_string(siteIndex) + "b" + std::to_string(bondIndex),
                symmetricBondState(kind), resolved.state);
            return;
        }
        switch (kind) {
        case Kind::Unbound:
        case Kind::Unspecified:
            templateMolecule->addEmptyComponent(site.componentName);
            break;
        case Kind::Bound:
            templateMolecule->addBoundComponent(site.componentName);
            break;
        case Kind::Any:
        case Kind::Exact:
            break;
        }
    };
    if (site.bondConstraints.empty()) {
        addConstraint(site.bondKind, 0);
    } else {
        for (std::size_t bondIndex = 0; bondIndex < site.bondConstraints.size();
             ++bondIndex) {
            addConstraint(site.bondConstraints[bondIndex].kind, bondIndex);
        }
    }
}

} // namespace

bool lowerPatternToNFsim(
    const bng::compile::Pattern& pattern,
    NFcore::System& system,
    std::vector<NFcore::TemplateMolecule*>& templates,
    bool& hasDisjointSets,
    int& suggestedTraversalLimit,
    std::string& diagnostic) {
    templates.clear();
    hasDisjointSets = false;
    diagnostic.clear();
    if (pattern.molecules().empty()) {
        diagnostic = "pattern contains no molecule nodes";
        return false;
    }

    std::vector<std::vector<ResolvedSite>> resolvedSites(pattern.molecules().size());
    for (std::size_t moleculeIndex = 0;
         moleculeIndex < pattern.molecules().size(); ++moleculeIndex) {
        const auto& molecule = pattern.molecules()[moleculeIndex];
        auto* moleculeType = resolveMoleculeType(system, molecule.moleculeType, diagnostic);
        if (moleculeType == nullptr) return false;
        NFcore::Compartment* compartment = nullptr;
        const auto& compartmentName = molecule.compartment.empty()
                                          ? pattern.compartment()
                                          : molecule.compartment;
        if (!resolveCompartment(system, compartmentName, compartment, diagnostic)) {
            return false;
        }
        resolvedSites[moleculeIndex].resize(molecule.sites.size());
        for (std::size_t siteIndex = 0; siteIndex < molecule.sites.size(); ++siteIndex) {
            if (molecule.sites[siteIndex].bondConstraints.size() > 1) {
                diagnostic = "NFsim direct lowering rejects multiple explicit bonds on one component";
                return false;
            }
            if (!resolveComponent(moleculeType, molecule.sites[siteIndex],
                                  resolvedSites[moleculeIndex][siteIndex], diagnostic)) {
                return false;
            }
        }
    }

    std::map<std::size_t, std::vector<std::pair<std::size_t, std::size_t>>> bondEndpoints;
    for (std::size_t moleculeIndex = 0;
         moleculeIndex < pattern.molecules().size(); ++moleculeIndex) {
        for (std::size_t siteIndex = 0;
             siteIndex < pattern.molecules()[moleculeIndex].sites.size(); ++siteIndex) {
            const auto& site = pattern.molecules()[moleculeIndex].sites[siteIndex];
            const auto addBondEndpoint = [&](const bng::compile::PatternBondDescriptor& bond) {
                if (bond.kind != bng::compile::BondConstraintKind::Exact) return true;
                if (bond.group.value == 0) {
                    diagnostic = "explicit bond has no bond-group identity";
                    return false;
                }
                bondEndpoints[bond.group.value].emplace_back(moleculeIndex, siteIndex);
                return true;
            };
            if (site.bondConstraints.empty()) {
                if (!addBondEndpoint({site.bondConstraint, site.bondKind,
                                      site.bondGroup})) {
                    return false;
                }
            } else {
                for (const auto& bond : site.bondConstraints) {
                    if (!addBondEndpoint(bond)) return false;
                }
            }
        }
    }
    for (const auto& entry : bondEndpoints) {
        if (entry.second.size() != 2) {
            diagnostic = "explicit bond group must have exactly two endpoints";
            return false;
        }
    }

    std::vector<NFcore::TemplateMolecule*> lowered;
    lowered.reserve(pattern.molecules().size());
    for (std::size_t moleculeIndex = 0;
         moleculeIndex < pattern.molecules().size(); ++moleculeIndex) {
        const auto& molecule = pattern.molecules()[moleculeIndex];
        auto* moleculeType = resolveMoleculeType(system, molecule.moleculeType, diagnostic);
        if (moleculeType == nullptr) return false;
        auto* templateMolecule = new NFcore::TemplateMolecule(moleculeType);
        NFcore::Compartment* compartment = nullptr;
        const auto& compartmentName = molecule.compartment.empty()
                                          ? pattern.compartment()
                                          : molecule.compartment;
        if (!resolveCompartment(system, compartmentName, compartment, diagnostic)) {
            return false;
        }
        templateMolecule->setCompartment(compartment);
        lowered.push_back(templateMolecule);
        for (std::size_t siteIndex = 0; siteIndex < molecule.sites.size(); ++siteIndex) {
            applyBondConstraint(templateMolecule, molecule.sites[siteIndex],
                                resolvedSites[moleculeIndex][siteIndex],
                                moleculeIndex, siteIndex);
        }
    }

    for (const auto& entry : bondEndpoints) {
        const auto& first = entry.second[0];
        const auto& second = entry.second[1];
        const auto& firstSite = pattern.molecules()[first.first].sites[first.second];
        const auto& secondSite = pattern.molecules()[second.first].sites[second.second];
        const std::string firstId = "m" + std::to_string(first.first) + "c" +
                                    std::to_string(first.second);
        const std::string secondId = "m" + std::to_string(second.first) + "c" +
                                     std::to_string(second.second);
        NFcore::TemplateMolecule::bind(
            lowered[first.first], firstSite.componentName, firstId,
            lowered[second.first], secondSite.componentName, secondId);
    }

    std::vector<std::vector<NFcore::TemplateMolecule*>> sets;
    std::vector<int> uniqueSetId;
    const int setCount = NFcore::TemplateMolecule::getNumDisjointSets(
        lowered, sets, uniqueSetId);
    if (setCount > 1) {
        hasDisjointSets = true;
        system.setUsingComplex(true);
        for (int set = 0; set < setCount - 1; ++set) {
            auto first = std::find(uniqueSetId.begin(), uniqueSetId.end(), set);
            auto second = std::find(uniqueSetId.begin(), uniqueSetId.end(), set + 1);
            if (first == uniqueSetId.end() || second == uniqueSetId.end()) {
                diagnostic = "could not connect disjoint template sets";
                return false;
            }
            const int firstIndex = static_cast<int>(
                std::distance(uniqueSetId.begin(), first));
            const int secondIndex = static_cast<int>(
                std::distance(uniqueSetId.begin(), second));
            const int firstConnection = lowered[firstIndex]->getN_connectedTo();
            const int secondConnection = lowered[secondIndex]->getN_connectedTo();
            lowered[firstIndex]->addConnectedTo(lowered[secondIndex], secondConnection);
            lowered[secondIndex]->addConnectedTo(lowered[firstIndex], firstConnection);
        }
    }

    suggestedTraversalLimit = std::max(
        suggestedTraversalLimit, static_cast<int>(lowered.size()) + 1);
    templates = std::move(lowered);
    return true;
}

} // namespace NFcore2
