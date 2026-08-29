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
/// IMPLEMENTED here: parameters, compartments, molecule types, and the safe
///                    parameter/observable-backed global-function subset.
/// STUBBED here:     observables, species, and rules; local/composite/time
///                   functions still fail closed and cite the TiXml init*
///                   function that is their behavioral specification.

#include "NFinput_fromAst.hh"
#include "NFinput.hh"

#include "ast/Compartment.hpp"
#include "ast/Function.hpp"
#include "ast/Model.hpp"
#include "ast/MoleculeType.hpp"
#include "ast/Expression.hpp"
#include "ast/Parameter.hpp"
#include "ast/ParameterList.hpp"
#include "../NFcore/compartment.hh"
#include "../NFfunction/NFfunction.hh"
#include "../NFutil/NFutil.hh"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <set>
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

bool hasModelFunction(const bng::ast::Model& model, const std::string& name) {
    return std::any_of(model.getFunctions().begin(), model.getFunctions().end(),
                       [&](const auto& function) { return function.getName() == name; });
}

bool hasModelObservable(const bng::ast::Model& model, const std::string& name) {
    return std::any_of(model.getObservables().begin(), model.getObservables().end(),
                       [&](const auto& observable) { return observable.getName() == name; });
}

bool isSupportedGlobalBuiltin(const std::string& name) {
    // Keep this list aligned with the functions registered by the NFsim
    // ExprTk-backed parser.  Rate-law helpers and TFUN need their own
    // adapters; accepting them here would make the direct path fail later in
    // GlobalFunction::prepareForSimulation().
    static const std::unordered_set<std::string> supported = {
        "abs",  "acos", "acosh", "asin", "asinh", "atan", "atanh", "ceil",
        "cos",  "cosh", "exp",   "floor", "if",    "ln",    "log",   "log10",
        "log2", "max",  "min",   "rint",  "sign",  "sin",   "sinh",  "sqrt",
        "sum",  "tan",  "tanh"};
    return supported.count(lowerCase(name)) != 0;
}

bool collectGlobalFunctionReferences(
    const bng::ast::Expression& expression, const bng::ast::Model& model,
    const std::map<std::string, double>& parameters, std::set<std::string>&
        observableReferences,
    std::string& diagnostic) {
    using bng::ast::ExpressionKind;

    switch (expression.kind()) {
    case ExpressionKind::Number:
        return true;
    case ExpressionKind::Identifier: {
        const auto& name = expression.name();
        if (name == "time" || name == "t") {
            diagnostic = "time-dependent global functions require the NFsim time adapter";
            return false;
        }
        if (parameters.count(name) != 0 || name == "_PI" || name == "_e" ||
            name == "_Na") {
            return true;
        }
        diagnostic = "unknown identifier '" + name + "'";
        return false;
    }
    case ExpressionKind::Unary:
    case ExpressionKind::Binary:
        for (const auto& child : expression.args()) {
            if (!collectGlobalFunctionReferences(child, model, parameters,
                                                  observableReferences, diagnostic)) {
                return false;
            }
        }
        return true;
    case ExpressionKind::Function:
        if (hasModelFunction(model, expression.name())) {
            diagnostic = "global function calls model function '" + expression.name() +
                         "' (composite/local mapping is not yet direct)";
            return false;
        }
        if (lowerCase(expression.name()) == "time") {
            diagnostic = "time-dependent global functions require the NFsim time adapter";
            return false;
        }
        if (!isSupportedGlobalBuiltin(expression.name())) {
            diagnostic = "unsupported NFsim global-function builtin '" +
                         expression.name() + "'";
            return false;
        }
        for (const auto& child : expression.args()) {
            if (!collectGlobalFunctionReferences(child, model, parameters,
                                                  observableReferences, diagnostic)) {
                return false;
            }
        }
        return true;
    case ExpressionKind::ObservableRef:
        if (hasModelFunction(model, expression.name())) {
            diagnostic = "global function calls model function '" + expression.name() +
                         "' (composite/local mapping is not yet direct)";
            return false;
        }
        if (!hasModelObservable(model, expression.name()) || !expression.args().empty()) {
            diagnostic = "observable reference '" + expression.name() +
                         "' is missing or has unsupported arguments";
            return false;
        }
        observableReferences.insert(expression.name());
        return true;
    }

    diagnostic = "unrecognized expression node";
    return false;
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
    // SPEC: NFinput::initFunctions (parseFuncXML.cpp:488).
    // This slice handles only parameter/observable-backed global functions.
    // Local functions, composite functions, time/TFUN functions, and rate-law
    // helpers deliberately return false so the caller can use the compatibility
    // XML path rather than constructing a subtly different simulation.
    if (s == nullptr) return false;

    std::unordered_set<std::string> names;
    for (const auto& function : model.getFunctions()) {
        const std::string& name = function.getName();
        if (name.empty() || !names.insert(name).second ||
            s->getGlobalFunctionByName(name) != nullptr) {
            std::cerr << "[nfsim/ast] duplicate or missing global function '" << name
                      << "'\n";
            return false;
        }
        if (!function.getArgs().empty()) {
            std::cerr << "[nfsim/ast] function '" << name
                      << "' has arguments; direct local-function mapping is pending\n";
            return false;
        }
    }

    struct PendingFunction {
        std::string name;
        std::string expression;
        std::vector<std::string> observableReferences;
        std::vector<std::string> parameterReferences;
    };
    std::vector<PendingFunction> pending;
    pending.reserve(model.getFunctions().size());

    for (const auto& function : model.getFunctions()) {
        std::set<std::string> observableReferences;
        std::string diagnostic;
        if (!collectGlobalFunctionReferences(function.getExpression(), model, parameters,
                                              observableReferences, diagnostic)) {
            std::cerr << "[nfsim/ast] cannot map function '" << function.getName()
                      << "': " << diagnostic << "\n";
            return false;
        }

        std::set<std::string> parameterReferences;
        for (const auto& dependency : function.getExpression().getDependencies()) {
            if (parameters.count(dependency) != 0) {
                parameterReferences.insert(dependency);
            }
        }

        PendingFunction next {
            function.getName(),
            function.getExpression().toString(),
            {observableReferences.begin(), observableReferences.end()},
            {parameterReferences.begin(), parameterReferences.end()}};
        pending.push_back(std::move(next));
    }

    for (const auto& function : pending) {
        // GlobalFunction predates const-correctness and takes mutable vector
        // references; keep the staged metadata immutable until this boundary,
        // then pass local copies to its legacy constructor.
        auto referenceNames = function.observableReferences;
        std::vector<std::string> referenceTypes(referenceNames.size(), "Observable");
        auto parameterNames = function.parameterReferences;
        auto* global = new GlobalFunction(function.name, function.expression,
                                           referenceNames, referenceTypes, parameterNames, s);
        if (!s->addGlobalFunction(global)) {
            delete global;
            std::cerr << "[nfsim/ast] failed to register global function '"
                      << function.name << "'\n";
            return false;
        }
        if (verbose) {
            std::cerr << "[nfsim/ast] global function " << function.name << "() = "
                      << function.expression << "\n";
        }
    }
    return true;
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
