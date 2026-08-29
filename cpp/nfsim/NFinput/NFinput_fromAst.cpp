/// NFinput_fromAst.cpp
///
/// WO-2 direct ast -> NFcore::System construction. See NFinput_fromAst.hh for
/// the migration contract.
///
/// Design that keeps every intermediate state correct and shippable:
///   buildSystemFromAst() runs each per-section builder in order. A builder
///   that is not yet implemented returns false; buildSystemFromAst then deletes
///   the partial System and returns nullptr, and bind_nfsim falls back to the
///   in-memory-XML path. The direct path therefore activates only once ALL
///   sections are implemented — never half-built. An agent flips one builder
///   from `return false` to a real implementation at a time, each gated by
///   test_parity_nfsim (ast-direct must equal in-memory-XML under one seed).
///
/// IMPLEMENTED here: parameters, compartments, and molecule types.
/// STUBBED here:     functions, observables, species, and rules — each cites
///                   the TiXml init* function that is its behavioral
///                   specification. Port those, do not reinvent them.

#include "NFinput_fromAst.hh"
#include "NFinput.hh"

#include "ast/Compartment.hpp"
#include "ast/Model.hpp"
#include "ast/MoleculeType.hpp"
#include "ast/Parameter.hpp"
#include "ast/ParameterList.hpp"
#include "../NFcore/compartment.hh"
#include "../NFutil/NFutil.hh"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

using namespace NFcore;

namespace NFinput {

// --------------------------------------------------------------------------- //
// Parameters — implemented directly from ast::ParameterList.
// Mirrors NFinput::initParameters (NFinput.cpp:286). The ast list already holds
// evaluated numeric values via ParameterList::evaluate(); no expression parsing
// is needed at this layer.
// --------------------------------------------------------------------------- //
bool addParametersFromAst(const bng::ast::Model& model, System* s,
                          std::map<std::string, double>& parameters, bool verbose) {
    const auto& plist = model.getParameters();
    for (const auto& p : plist.all()) {
        const std::string& name = p.getName();
        double value = plist.evaluate(name, 0.0);  // resolves inter-parameter refs
        parameters[name] = value;
        s->addParameter(name, value);
        if (verbose) {
            std::cerr << "[nfsim/ast] parameter " << name << " = " << value << "\n";
        }
    }
    return true;
}

// --------------------------------------------------------------------------- //
// Compartments — mirror NFinput::initCompartments (NFinput.cpp:230).  The
// parent links are intentionally installed in a second pass because BNGL
// permits a child to appear before its outside compartment in source order.
// --------------------------------------------------------------------------- //
bool addCompartmentsFromAst(const bng::ast::Model& model, System* s, bool verbose) {
    const auto& compartments = model.getCompartments();
    if (compartments.empty()) return true;

    std::unordered_set<std::string> seen;
    std::map<std::string, std::string> parentByChild;
    for (const auto& compartment : compartments) {
        const std::string name = compartment.getName();
        if (name.empty()) {
            std::cerr << "[nfsim/ast] compartment is missing a name\n";
            return false;
        }
        if (!seen.insert(name).second || s->getCompartment(name) != nullptr) {
            std::cerr << "[nfsim/ast] duplicate compartment '" << name << "'\n";
            return false;
        }

        auto* nfCompartment = new Compartment(
            name, compartment.getDimension(), compartment.getVolume());
        s->addCompartment(nfCompartment);
        if (!compartment.getParent().empty()) {
            parentByChild.emplace(name, compartment.getParent());
        }
        if (verbose) {
            std::cerr << "[nfsim/ast] compartment " << name
                      << " (dimension=" << compartment.getDimension()
                      << ", size=" << compartment.getVolume() << ")\n";
        }
    }

    for (const auto& [childName, parentName] : parentByChild) {
        auto* child = s->getCompartment(childName);
        auto* parent = s->getCompartment(parentName);
        if (parent != nullptr) {
            child->setParent(parent);
        } else {
            // Preserve the XML adapter's permissive behavior for an unknown
            // outside compartment, while making the direct-path diagnostic
            // explicit.  Seed species/rules will reject unusable references.
            std::cerr << "[nfsim/ast] warning: compartment '" << childName
                      << "' refers to unknown outside compartment '" << parentName
                      << "'\n";
        }
    }
    return true;
}

namespace {

std::string lowerCase(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

bool parseIntegerState(const std::string& text, int& value) {
    std::istringstream input(text);
    char trailing = '\0';
    if (!(input >> value) || (input >> trailing)) return false;
    return true;
}

} // namespace

// --------------------------------------------------------------------------- //
// Molecule types — mirror NFinput::initMoleculeTypes (NFinput.cpp:365).  The
// AST already contains the normalized component/state tokens, so this port
// only has to reproduce NFsim's integer-state expansion and symmetric-site
// renaming.  `allowedStates` is carried forward for the species/observable/
// rule builders that will consume it in later migration slices.
// --------------------------------------------------------------------------- //

bool addMoleculeTypesFromAst(const bng::ast::Model& model, System* s,
                             std::map<std::string, int>& allowedStates,
                             bool verbose) {
    try {
        for (const auto& moleculeType : model.getMoleculeTypes()) {
            const std::string& typeName = moleculeType.getName();
            if (typeName.empty()) {
                std::cerr << "[nfsim/ast] molecule type is missing a name\n";
                return false;
            }
            const std::string normalizedName = lowerCase(typeName);
            if (normalizedName == "null" || normalizedName == "trash") {
                if (verbose) {
                    std::cerr << "[nfsim/ast] skipping molecule type '" << typeName
                              << "'\n";
                }
                continue;
            }
            for (int index = 0; index < s->getNumOfMoleculeTypes(); ++index) {
                if (s->getMoleculeType(index)->getName() == typeName) {
                    std::cerr << "[nfsim/ast] duplicate molecule type '" << typeName
                              << "'\n";
                    return false;
                }
            }
            if (moleculeType.isPopulation() && !moleculeType.getComponents().empty()) {
                std::cerr << "[nfsim/ast] population type '" << typeName
                          << "' cannot have components\n";
                return false;
            }

            std::vector<std::string> componentNames;
            std::vector<std::string> defaultStates;
            std::vector<std::vector<std::string>> possibleStates;
            std::vector<std::vector<std::string>> equivalentComponents;
            std::vector<bool> integerComponents;
            std::vector<std::size_t> firstSymmetricSites;

            for (const auto& component : moleculeType.getComponents()) {
                if (component.name.empty()) {
                    std::cerr << "[nfsim/ast] component in molecule type '"
                              << typeName << "' is missing a name\n";
                    return false;
                }

                std::string componentName = component.name;
                auto duplicate = std::find(componentNames.begin(), componentNames.end(),
                                            componentName);
                if (duplicate != componentNames.end()) {
                    const auto duplicateIndex = static_cast<std::size_t>(
                        std::distance(componentNames.begin(), duplicate));
                    if (std::find(firstSymmetricSites.begin(), firstSymmetricSites.end(),
                                  duplicateIndex) == firstSymmetricSites.end()) {
                        firstSymmetricSites.push_back(duplicateIndex);
                    }

                    std::string renamed = componentName + "2";
                    auto equivalent = std::find_if(
                        equivalentComponents.begin(), equivalentComponents.end(),
                        [&](const auto& group) {
                            return !group.empty() && group.front() == componentName + "1";
                        });
                    if (equivalent != equivalentComponents.end()) {
                        renamed = componentName +
                                  std::to_string(equivalent->size() + 1);
                        equivalent->push_back(renamed);
                    } else {
                        equivalentComponents.push_back(
                            {componentName + "1", renamed});
                    }
                    componentName = std::move(renamed);
                }
                componentNames.push_back(componentName);

                std::vector<std::string> states;
                bool hasStringState = false;
                bool hasIntegerState = false;
                bool hasPlusMinusState = false;
                bool hasNegativeInteger = false;
                int maximumState = -1;
                for (const auto& state : component.allowedStates) {
                    int integerValue = 0;
                    if (parseIntegerState(state, integerValue)) {
                        hasIntegerState = true;
                        hasNegativeInteger = hasNegativeInteger || integerValue < 0;
                        maximumState = std::max(maximumState, integerValue);
                    } else {
                        hasStringState = true;
                        if (state == "PLUS" || state == "MINUS") {
                            hasPlusMinusState = true;
                        }
                    }
                }

                bool integerComponent = false;
                if (hasIntegerState && !hasStringState) {
                    if (hasNegativeInteger || maximumState < 0 || maximumState > 10000) {
                        std::cerr << "[nfsim/ast] integer states for '" << typeName
                                  << "." << componentName
                                  << "' must be in [0,10000]\n";
                        return false;
                    }
                    integerComponent = true;
                    states.reserve(static_cast<std::size_t>(maximumState + 1));
                    for (int value = 0; value <= maximumState; ++value) {
                        states.push_back(std::to_string(value));
                    }
                } else if (hasStringState) {
                    if (hasPlusMinusState) {
                        std::cerr << "[nfsim/ast] warning: PLUS/MINUS in string states "
                                     "for '" << typeName << "." << componentName
                                  << "' are labels, not integer increments\n";
                    }
                    for (const auto& state : component.allowedStates) {
                        if (std::find(states.begin(), states.end(), state) == states.end()) {
                            states.push_back(state);
                        }
                    }
                }

                integerComponents.push_back(integerComponent);
                defaultStates.push_back(states.empty() ? std::string {} : states.front());
                possibleStates.push_back(std::move(states));
            }

            // The first member of each symmetric class gets the `1` suffix
            // only after all components have been read, matching NFsim's XML
            // loader and preserving the generic site name for pattern input.
            for (const auto index : firstSymmetricSites) {
                const std::string original = componentNames.at(index);
                const std::string renamed = original + "1";
                componentNames[index] = renamed;
            }

            // Populate the state lookup using final NFsim component names.
            for (std::size_t index = 0; index < componentNames.size(); ++index) {
                for (std::size_t stateIndex = 0;
                     stateIndex < possibleStates[index].size(); ++stateIndex) {
                    allowedStates[typeName + "_" + componentNames[index] + "_" +
                                  possibleStates[index][stateIndex]] =
                        static_cast<int>(stateIndex);
                }
            }

            if (verbose) {
                std::cerr << "[nfsim/ast] molecule type " << typeName << " (";
                for (std::size_t i = 0; i < componentNames.size(); ++i) {
                    if (i != 0) std::cerr << ",";
                    std::cerr << componentNames[i];
                }
                std::cerr << ")\n";
            }

            auto* nfType = new MoleculeType(typeName, componentNames, defaultStates,
                                            possibleStates, integerComponents,
                                            moleculeType.isPopulation(), s);
            nfType->addEquivalentComponents(equivalentComponents);
        }
        return true;
    } catch (const std::exception& error) {
        std::cerr << "[nfsim/ast] molecule type construction failed: "
                  << error.what() << "\n";
        return false;
    }
}

bool addFunctionsFromAst(const bng::ast::Model& model, System* s,
                         const std::map<std::string, double>& parameters, bool verbose) {
    (void)model; (void)s; (void)parameters; (void)verbose;
    // SPEC: NFinput::initFunctions (parseFuncXML.cpp:488).
    // WO-3 INTERSECTION: build the function bodies through the shared evaluator
    //       (see ast/ExpressionEval.hpp), NOT exprtk. ast source:
    //       model.getFunctions() -> vector<Function>.
    return false;
}

bool addObservablesFromAst(const bng::ast::Model& model, System* s,
                           const std::map<std::string, double>& parameters,
                           bool verbose, int& suggestedTraversalLimit) {
    (void)model; (void)s; (void)parameters; (void)verbose; (void)suggestedTraversalLimit;
    // SPEC: NFinput::initObservables (NFinput.cpp:2935) +
    //       readObservableForTemplateMolecules (NFinput.cpp:2814).
    // ast source: model.getObservables() -> vector<Observable>.
    return false;
}

bool addSpeciesFromAst(const bng::ast::Model& model, System* s,
                       const std::map<std::string, double>& parameters, bool verbose) {
    (void)model; (void)s; (void)parameters; (void)verbose;
    // SPEC: the seed-species/ListOfSpecies loop in NFinput::initializeFromXML
    //       (instantiates initial Molecule populations into the System).
    // ast source: model.getSeedSpecies() -> vector<SeedSpecies>.
    return false;
}

bool addReactionRulesFromAst(const bng::ast::Model& model, System* s,
                             const std::map<std::string, double>& parameters,
                             bool blockSameComplexBinding, bool verbose,
                             int& suggestedTraversalLimit) {
    (void)model; (void)s; (void)parameters; (void)blockSameComplexBinding;
    (void)verbose; (void)suggestedTraversalLimit;
    // SPEC: NFinput::initReactionRules (NFinput.cpp:1266) — the largest section;
    //       TransformationSet construction, reactant template molecules, rate
    //       laws (incl. Arrhenius via NFinput_energy). Port last.
    // ast source: model.getReactionRules() -> vector<ReactionRule>.
    return false;
}

// --------------------------------------------------------------------------- //
// Orchestrator.
// --------------------------------------------------------------------------- //
System* buildSystemFromAst(const bng::ast::Model& model,
                           bool blockSameComplexBinding,
                           int globalMoleculeLimit,
                           bool verbose,
                           int& suggestedTraversalLimit) {
    // Migration escape hatch used by the parity gate: force the XML path.
    if (std::getenv("BNG_NFSIM_FORCE_XML")) {
        if (verbose) std::cerr << "[nfsim/ast] BNG_NFSIM_FORCE_XML set -> XML path\n";
        return nullptr;  // caller falls back to initializeFromModel (in-memory XML)
    }

    const std::string& name = model.getModelName();
    System* s = new System(name.empty() ? "model" : name,
                           blockSameComplexBinding, globalMoleculeLimit);

    std::map<std::string, double> parameters;
    std::map<std::string, int> allowedStates;
    suggestedTraversalLimit = 0;

    bool ok = false;
    try {
        // Keep this order aligned with initializeFromModel(): molecule types
        // and compartments must exist before species, observables, and rules.
        ok = addParametersFromAst(model, s, parameters, verbose) &&
             addMoleculeTypesFromAst(model, s, allowedStates, verbose) &&
             addCompartmentsFromAst(model, s, verbose) &&
             addFunctionsFromAst(model, s, parameters, verbose) &&
             addObservablesFromAst(model, s, parameters, verbose, suggestedTraversalLimit) &&
             addSpeciesFromAst(model, s, parameters, verbose) &&
             addReactionRulesFromAst(model, s, parameters, blockSameComplexBinding,
                                     verbose, suggestedTraversalLimit);
    } catch (const std::exception& error) {
        if (verbose) {
            std::cerr << "[nfsim/ast] direct construction failed: "
                      << error.what() << "\n";
        }
    }

    if (!ok) {
        // Some section is not yet ported. Discard the partial System and let the
        // caller use the in-memory-XML path. This is the expected state until
        // every builder above returns true.
        delete s;
        if (verbose) {
            std::cerr << "[nfsim/ast] direct path incomplete -> XML fallback\n";
        }
        return nullptr;
    }

    // s->prepareForSimulation() is the caller's responsibility, matching the
    // XML path in bind_nfsim.
    return s;
}

} // namespace NFinput
