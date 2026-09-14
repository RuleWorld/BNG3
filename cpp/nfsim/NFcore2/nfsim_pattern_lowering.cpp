#include "nfsim_pattern_lowering.hh"

#include <algorithm>
#include <functional>
#include <map>
#include <set>
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
            // A concrete component can carry at most one bond.  Repeated
            // component names are NFsim's equivalent-site orbit, however;
            // each explicit bond label selects a distinct orbit member and
            // is represented by a separate symmetric constraint below.
            if (molecule.sites[siteIndex].bondConstraints.size() > 1 &&
                !moleculeType->isEquivalentComponent(
                    molecule.sites[siteIndex].componentName)) {
                diagnostic = "NFsim direct lowering rejects multiple explicit bonds on one component";
                return false;
            }
            if (!resolveComponent(moleculeType, molecule.sites[siteIndex],
                                  resolvedSites[moleculeIndex][siteIndex], diagnostic)) {
                return false;
            }
        }
    }

    struct BondEndpoint {
        std::size_t molecule;
        std::size_t site;
        std::size_t bond;
    };
    std::map<std::size_t, std::vector<BondEndpoint>> bondEndpoints;
    for (std::size_t moleculeIndex = 0;
         moleculeIndex < pattern.molecules().size(); ++moleculeIndex) {
        for (std::size_t siteIndex = 0;
             siteIndex < pattern.molecules()[moleculeIndex].sites.size(); ++siteIndex) {
            const auto& site = pattern.molecules()[moleculeIndex].sites[siteIndex];
            const auto addBondEndpoint = [&](const bng::compile::PatternBondDescriptor& bond,
                                             std::size_t bondIndex) {
                if (bond.kind != bng::compile::BondConstraintKind::Exact) return true;
                if (bond.group.value == 0) {
                    diagnostic = "explicit bond has no bond-group identity";
                    return false;
                }
                bondEndpoints[bond.group.value].push_back(
                    BondEndpoint{moleculeIndex, siteIndex, bondIndex});
                return true;
            };
            if (site.bondConstraints.empty()) {
                if (!addBondEndpoint({site.bondConstraint, site.bondKind,
                                      site.bondGroup}, 0)) {
                    return false;
                }
            } else {
                for (std::size_t bondIndex = 0;
                     bondIndex < site.bondConstraints.size(); ++bondIndex) {
                    if (!addBondEndpoint(site.bondConstraints[bondIndex], bondIndex))
                        return false;
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
        const auto& firstSite = pattern.molecules()[first.molecule].sites[first.site];
        const auto& secondSite = pattern.molecules()[second.molecule].sites[second.site];
        const bool firstSymmetric = lowered[first.molecule]->getMoleculeType()->
            isEquivalentComponent(firstSite.componentName);
        const bool secondSymmetric = lowered[second.molecule]->getMoleculeType()->
            isEquivalentComponent(secondSite.componentName);
        const std::string firstId = "m" + std::to_string(first.molecule) + "c" +
            std::to_string(first.site) + (firstSymmetric ? "b" + std::to_string(first.bond) : "");
        const std::string secondId = "m" + std::to_string(second.molecule) + "c" +
            std::to_string(second.site) + (secondSymmetric ? "b" + std::to_string(second.bond) : "");
        NFcore::TemplateMolecule::bind(
            lowered[first.molecule], firstSite.componentName, firstId,
            lowered[second.molecule], secondSite.componentName, secondId);
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


bool lowerPatternToNFsimPermutations(
    const bng::compile::Pattern& pattern,
    NFcore::System& system,
    const std::set<std::pair<std::size_t, std::size_t>>& concreteSymmetricSites,
    std::vector<std::vector<NFcore::TemplateMolecule*>>& builds,
    std::vector<RuntimeComponentNames>& assignments,
    bool& hasDisjointSets,
    int& suggestedTraversalLimit,
    std::string& diagnostic) {
    builds.clear();
    assignments.clear();
    hasDisjointSets = false;
    diagnostic.clear();
    if (pattern.molecules().empty()) {
        diagnostic = "pattern contains no molecule nodes";
        return false;
    }

    RuntimeComponentNames initial;
    initial.reserve(pattern.molecules().size());
    for (const auto& molecule : pattern.molecules()) {
        auto* moleculeType = resolveMoleculeType(system, molecule.moleculeType, diagnostic);
        if (moleculeType == nullptr) return false;
        std::vector<std::string> names;
        names.reserve(molecule.sites.size());
        for (const auto& site : molecule.sites) names.push_back(site.componentName);
        initial.push_back(std::move(names));
    }
    assignments.push_back(std::move(initial));

    // NFsim represents repeated BNGL component declarations as an equivalency
    // class with concrete runtime names (x1, x2, ...).  Enumerate injective
    // assignments for each generic name.  The reaction adapter later
    // deduplicates permutations that differ only at context-only sites.
    for (std::size_t moleculeIndex = 0;
         moleculeIndex < pattern.molecules().size(); ++moleculeIndex) {
        const auto& molecule = pattern.molecules()[moleculeIndex];
        auto* moleculeType = resolveMoleculeType(system, molecule.moleculeType, diagnostic);
        if (moleculeType == nullptr) return false;
        std::map<std::string, std::vector<std::size_t>> occurrences;
        for (std::size_t siteIndex = 0; siteIndex < molecule.sites.size(); ++siteIndex) {
            if (moleculeType->isEquivalentComponent(molecule.sites[siteIndex].componentName)) {
                occurrences[molecule.sites[siteIndex].componentName].push_back(siteIndex);
            }
        }
        for (const auto& [genericName, siteIndices] : occurrences) {
            int* equivalentIndices = nullptr;
            int equivalentCount = 0;
            moleculeType->getEquivalencyClass(
                equivalentIndices, equivalentCount, genericName);
            if (equivalentIndices == nullptr || equivalentCount <= 0 ||
                siteIndices.size() > static_cast<std::size_t>(equivalentCount)) {
                diagnostic = "too many symmetric components named '" + genericName +
                             "' in molecule type '" + molecule.moleculeType + "'";
                return false;
            }
            std::vector<std::string> equivalentNames;
            equivalentNames.reserve(static_cast<std::size_t>(equivalentCount));
            for (int index = 0; index < equivalentCount; ++index) {
                equivalentNames.push_back(
                    moleculeType->getComponentName(equivalentIndices[index]));
            }

            std::vector<std::vector<std::string>> choices;
            std::vector<std::string> choice(siteIndices.size());
            std::vector<bool> used(equivalentNames.size(), false);
            std::function<void(std::size_t)> enumerate = [&](std::size_t position) {
                if (position == siteIndices.size()) {
                    choices.push_back(choice);
                    return;
                }
                for (std::size_t nameIndex = 0;
                     nameIndex < equivalentNames.size(); ++nameIndex) {
                    if (used[nameIndex]) continue;
                    used[nameIndex] = true;
                    choice[position] = equivalentNames[nameIndex];
                    enumerate(position + 1);
                    used[nameIndex] = false;
                }
            };
            enumerate(0);

            std::vector<RuntimeComponentNames> next;
            next.reserve(assignments.size() * choices.size());
            for (const auto& base : assignments) {
                for (const auto& selected : choices) {
                    RuntimeComponentNames variant = base;
                    for (std::size_t position = 0; position < siteIndices.size(); ++position) {
                        variant[moleculeIndex][siteIndices[position]] = selected[position];
                    }
                    next.push_back(std::move(variant));
                }
            }
            assignments = std::move(next);
        }
    }

    struct BondEndpoint {
        std::size_t molecule = 0;
        std::size_t site = 0;
        std::size_t bond = 0;
    };
    std::map<std::size_t, std::vector<BondEndpoint>> bondEndpoints;
    for (std::size_t moleculeIndex = 0;
         moleculeIndex < pattern.molecules().size(); ++moleculeIndex) {
        const auto& molecule = pattern.molecules()[moleculeIndex];
        for (std::size_t siteIndex = 0; siteIndex < molecule.sites.size(); ++siteIndex) {
            const auto& site = molecule.sites[siteIndex];
            const auto addEndpoint = [&](const bng::compile::PatternBondDescriptor& bond,
                                         std::size_t bondIndex) {
                if (bond.kind != bng::compile::BondConstraintKind::Exact) return true;
                if (bond.group.value == 0) {
                    diagnostic = "explicit bond has no bond-group identity";
                    return false;
                }
                bondEndpoints[bond.group.value].push_back(
                    BondEndpoint{moleculeIndex, siteIndex, bondIndex});
                return true;
            };
            if (site.bondConstraints.empty()) {
                if (!addEndpoint({site.bondConstraint, site.bondKind, site.bondGroup}, 0))
                    return false;
            } else {
                for (std::size_t bondIndex = 0;
                     bondIndex < site.bondConstraints.size(); ++bondIndex) {
                    if (!addEndpoint(site.bondConstraints[bondIndex], bondIndex))
                        return false;
                }
            }
        }
    }
    for (const auto& [group, endpoints] : bondEndpoints) {
        (void)group;
        if (endpoints.size() != 2) {
            diagnostic = "explicit bond group must have exactly two endpoints";
            return false;
        }
    }

    const auto stateValue = [&](NFcore::MoleculeType* moleculeType,
                                const std::string& runtimeName,
                                const bng::compile::PatternSiteDescriptor& site,
                                int& value) {
        value = NFcore::TemplateMolecule::NO_CONSTRAINT;
        if (site.stateConstraint.empty() || site.stateConstraint == "?" ||
            site.stateConstraint == "*") return true;
        try {
            const int componentIndex = moleculeType->getCompIndexFromName(runtimeName);
            value = moleculeType->getStateValueFromName(
                componentIndex, site.stateConstraint);
            return true;
        } catch (const std::exception& error) {
            diagnostic = error.what();
            return false;
        }
    };

    for (const auto& runtimeNames : assignments) {
        std::vector<NFcore::TemplateMolecule*> templates;
        templates.reserve(pattern.molecules().size());
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
            if (!resolveCompartment(system, compartmentName, compartment, diagnostic))
                return false;
            templateMolecule->setCompartment(compartment);
            templates.push_back(templateMolecule);
        }

        for (std::size_t moleculeIndex = 0;
             moleculeIndex < pattern.molecules().size(); ++moleculeIndex) {
            const auto& molecule = pattern.molecules()[moleculeIndex];
            auto* moleculeType = templates[moleculeIndex]->getMoleculeType();
            for (std::size_t siteIndex = 0; siteIndex < molecule.sites.size(); ++siteIndex) {
                const auto& site = molecule.sites[siteIndex];
                const bool symmetric = moleculeType->isEquivalentComponent(site.componentName);
                const bool concrete = symmetric &&
                    concreteSymmetricSites.count({moleculeIndex, siteIndex}) != 0;
                const auto& runtimeName = runtimeNames[moleculeIndex][siteIndex];

                std::string stateLookupName = runtimeName;
                if (symmetric && !concrete) {
                    int* equivalentIndices = nullptr;
                    int equivalentCount = 0;
                    moleculeType->getEquivalencyClass(
                        equivalentIndices, equivalentCount, site.componentName);
                    if (equivalentIndices == nullptr || equivalentCount <= 0) {
                        diagnostic = "could not resolve symmetric component '" +
                                     site.componentName + "'";
                        return false;
                    }
                    stateLookupName = moleculeType->getComponentName(equivalentIndices[0]);
                }
                int resolvedState = NFcore::TemplateMolecule::NO_CONSTRAINT;
                if (!stateValue(moleculeType, stateLookupName, site, resolvedState))
                    return false;

                const auto applyConstraint = [&](bng::compile::BondConstraintKind kind,
                                                 std::size_t bondIndex) {
                    if (symmetric && !concrete) {
                        templates[moleculeIndex]->addSymCompConstraint(
                            site.componentName,
                            "m" + std::to_string(moleculeIndex) + "c" +
                                std::to_string(siteIndex) + "b" +
                                std::to_string(bondIndex),
                            symmetricBondState(kind), resolvedState);
                        return true;
                    }
                    if (resolvedState != NFcore::TemplateMolecule::NO_CONSTRAINT) {
                        templates[moleculeIndex]->addComponentConstraint(
                            runtimeName, resolvedState);
                    }
                    switch (kind) {
                    case bng::compile::BondConstraintKind::Unbound:
                    case bng::compile::BondConstraintKind::Unspecified:
                        templates[moleculeIndex]->addEmptyComponent(runtimeName);
                        break;
                    case bng::compile::BondConstraintKind::Bound:
                        templates[moleculeIndex]->addBoundComponent(runtimeName);
                        break;
                    case bng::compile::BondConstraintKind::Any:
                    case bng::compile::BondConstraintKind::Exact:
                        break;
                    }
                    return true;
                };

                if (site.bondConstraints.empty()) {
                    if (!applyConstraint(site.bondKind, 0)) return false;
                } else {
                    bool stateApplied = false;
                    for (std::size_t bondIndex = 0;
                         bondIndex < site.bondConstraints.size(); ++bondIndex) {
                        // A concrete component should receive its state
                        // constraint only once even if the source carried more
                        // than one bond token.
                        if (!symmetric || concrete) {
                            const int savedState = resolvedState;
                            if (stateApplied) resolvedState = NFcore::TemplateMolecule::NO_CONSTRAINT;
                            if (!applyConstraint(site.bondConstraints[bondIndex].kind, bondIndex))
                                return false;
                            resolvedState = savedState;
                            stateApplied = true;
                        } else if (!applyConstraint(
                                       site.bondConstraints[bondIndex].kind, bondIndex)) {
                            return false;
                        }
                    }
                }
            }
        }

        for (const auto& [group, endpoints] : bondEndpoints) {
            (void)group;
            const auto& first = endpoints[0];
            const auto& second = endpoints[1];
            const auto& firstSite =
                pattern.molecules()[first.molecule].sites[first.site];
            const auto& secondSite =
                pattern.molecules()[second.molecule].sites[second.site];
            const bool firstSymmetric = templates[first.molecule]->getMoleculeType()->
                isEquivalentComponent(firstSite.componentName);
            const bool secondSymmetric = templates[second.molecule]->getMoleculeType()->
                isEquivalentComponent(secondSite.componentName);
            const bool firstConcrete = firstSymmetric &&
                concreteSymmetricSites.count({first.molecule, first.site}) != 0;
            const bool secondConcrete = secondSymmetric &&
                concreteSymmetricSites.count({second.molecule, second.site}) != 0;
            const auto firstName = firstConcrete
                ? runtimeNames[first.molecule][first.site]
                : firstSite.componentName;
            const auto secondName = secondConcrete
                ? runtimeNames[second.molecule][second.site]
                : secondSite.componentName;
            const auto firstId = "m" + std::to_string(first.molecule) + "c" +
                std::to_string(first.site) +
                (firstSymmetric && !firstConcrete ? "b" + std::to_string(first.bond) : "");
            const auto secondId = "m" + std::to_string(second.molecule) + "c" +
                std::to_string(second.site) +
                (secondSymmetric && !secondConcrete ? "b" + std::to_string(second.bond) : "");
            NFcore::TemplateMolecule::bind(
                templates[first.molecule], firstName, firstId,
                templates[second.molecule], secondName, secondId);
        }

        std::vector<std::vector<NFcore::TemplateMolecule*>> sets;
        std::vector<int> uniqueSetId;
        const int setCount = NFcore::TemplateMolecule::getNumDisjointSets(
            templates, sets, uniqueSetId);
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
                const int firstConnection = templates[firstIndex]->getN_connectedTo();
                const int secondConnection = templates[secondIndex]->getN_connectedTo();
                templates[firstIndex]->addConnectedTo(
                    templates[secondIndex], secondConnection);
                templates[secondIndex]->addConnectedTo(
                    templates[firstIndex], firstConnection);
            }
        }
        suggestedTraversalLimit = std::max(
            suggestedTraversalLimit, static_cast<int>(templates.size()) + 1);
        builds.push_back(std::move(templates));
    }
    return !builds.empty() && builds.size() == assignments.size();
}

} // namespace NFcore2
