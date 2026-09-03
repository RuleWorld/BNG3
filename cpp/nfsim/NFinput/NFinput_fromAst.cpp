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
/// IMPLEMENTED here: parameters, compartments, molecule types, observables,
///                    seed species, bounded direct reaction rules, direct
///                    Arrhenius energy expansion, time-backed global
///                    functions, zero-argument composites, one-argument
///                    molecule/species-scoped and time-bearing local functions,
///                    time/parameter-backed local TFUNs, FunctionProduct,
///                    Sat/Hill rate laws, bounded reactant/product
///                    include/exclude filters,
///                    and bounded reversible filter swapping,
///                    and dynamic reaction rates over parameters, observables,
///                    time, one TFUN expression, or bounded zero-argument
///                    model-function chains.
///                    Bounded symmetric state-change and bond reaction centers
///                    are expanded into explicit NFcore reaction classes when
///                    all stated symmetric sites are reaction-center sites.
///                    The same permutations retain live generated
///                    global/composite rate functions for supported dynamic
///                    rates.
///                   Bounded nested local functions and function-counter local
///                   TFUNs whose counter is a zero-argument base global are
///                   also direct composites.
/// GATED here:       deeper/complex local functions, unbounded function-counter
///                   composites, other rate-law forms, complex product filters,
///                   and reaction centers not yet represented by the direct
///                   mapping. A bounded static state-change permutation slice
///                   handles symmetric reaction centers; the remaining cases
///                   fail closed and cite the TiXml init* function
///                   that remains their compatibility oracle.

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
#include "../NFcore/energyPattern.hh"
#include "../NFfunction/NFfunction.hh"
#include "../NFutil/NFutil.hh"
#include "NFinput_energy.hh"

#include "parser/antlr_compat.hpp"

#include "PatternGraphBuilder.hpp"
#include "BNGLexer.h"
#include "BNGParser.h"
#include "../NFreactions/transformations/moleculeCreator.hh"
#include "../NFreactions/transformations/transformation.hh"
#include "../NFreactions/transformations/transformationSet.hh"

#include <antlr4-runtime.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <set>
#include <unordered_set>
#include <utility>
#include <vector>

using namespace NFcore;

// The legacy function constructor is still the behavioral specification for
// NFsim local functions.  It is link-visible from parseFuncXML.cpp; calling it
// with AST-derived references avoids constructing an intermediate XML node.
bool createLocalFunction(
    std::string name,
    std::string expression,
    std::vector<std::string>& argNames,
    std::vector<std::string>& refNames,
    std::vector<std::string>& refTypes,
    NFcore::System* s,
    std::map<std::string, double>& parameter,
    TiXmlElement* pListOfObservables,
    std::map<std::string, int>& allowedStates,
    bool verbose);

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

bool addOptionsFromAst(const bng::ast::Model& model, System* s, bool verbose) {
    if (s == nullptr) return false;

    // NFinput reads this as a model attribute and applies it to concentration
    // conversion.  Keep parsing strict here so malformed AST options take the
    // compatibility path instead of silently changing molecule counts.
    const auto& options = model.getOptions();
    const auto numberPerQuantity = options.find("NumberPerQuantityUnit");
    if (numberPerQuantity != options.end()) {
        try {
            std::size_t consumed = 0;
            const double value = std::stod(numberPerQuantity->second, &consumed);
            if (consumed != numberPerQuantity->second.size() || !std::isfinite(value) ||
                value < 0.0) {
                std::cerr << "[nfsim/ast] invalid NumberPerQuantityUnit value '"
                          << numberPerQuantity->second << "'\n";
                return false;
            }
            s->setNumberPerQuantityUnit(value);
            if (verbose) {
                std::cerr << "[nfsim/ast] NumberPerQuantityUnit = " << value << "\n";
            }
        } catch (const std::exception&) {
            std::cerr << "[nfsim/ast] invalid NumberPerQuantityUnit value '"
                      << numberPerQuantity->second << "'\n";
            return false;
        }
    }

    // The remaining setOption values configure BioNetGen writers or other
    // backends; NFsim has no corresponding System state.  Retain them in the
    // AST for those consumers rather than rejecting an otherwise valid model.
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

std::string resolveTfunPath(const std::string& filePath,
                            const std::filesystem::path& sourcePath) {
    const std::filesystem::path path(filePath);
    if (path.is_absolute() || sourcePath.empty()) return path.string();
    return (sourcePath.parent_path() / path).lexically_normal().string();
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

const bng::ast::Function* getModelFunction(const bng::ast::Model& model,
                                            const std::string& name) {
    const auto iter = std::find_if(
        model.getFunctions().begin(), model.getFunctions().end(),
        [&](const auto& function) { return function.getName() == name; });
    return iter == model.getFunctions().end() ? nullptr : &*iter;
}

bool hasScopedArgument(const std::string& pattern, const std::string& argument) {
    if (argument.empty()) return false;
    const std::string needle = "%" + argument;
    std::size_t position = pattern.find(needle);
    while (position != std::string::npos) {
        const std::size_t end = position + needle.size();
        if (end == pattern.size() || pattern.compare(end, 2, "::") == 0 ||
            !std::isalnum(static_cast<unsigned char>(pattern[end])) &&
                pattern[end] != '_') {
            return true;
        }
        position = pattern.find(needle, position + 1);
    }
    return false;
}

bool hasSpeciesScopedArgument(const std::string& pattern, const std::string& argument) {
    if (argument.empty()) return false;
    const std::string needle = "%" + argument + "::";
    std::size_t position = pattern.find(needle);
    while (position != std::string::npos) {
        // A scope prefix belongs to a molecule-pattern boundary. Accept the
        // start of the species, a species-level compartment prefix, or a
        // dot-connected molecule; reject labels embedded in names.
        if (position == 0 || pattern[position - 1] == '.' || pattern[position - 1] == ':') {
            return true;
        }
        position = pattern.find(needle, position + 1);
    }
    return false;
}

struct FunctionProductOperand {
    std::string name;
    std::string argument;
};

bool parseFunctionProductOperand(const bng::ast::Model& model,
                                 const bng::ast::Expression& expression,
                                 FunctionProductOperand& operand,
                                 std::string& diagnostic) {
    using bng::ast::ExpressionKind;
    if (expression.kind() != ExpressionKind::Function &&
        expression.kind() != ExpressionKind::ObservableRef) {
        diagnostic = "FunctionProduct operands must be function calls";
        return false;
    }
    const auto* function = getModelFunction(model, expression.name());
    if (function == nullptr || function->getArgs().size() != 1 ||
        expression.args().size() != 1 ||
        expression.args().front().kind() != ExpressionKind::Identifier) {
        diagnostic = "FunctionProduct operands must call one-argument local functions";
        return false;
    }
    operand.name = expression.name();
    operand.argument = expression.args().front().name();
    return true;
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

void collectTableFunctions(const bng::ast::Expression& expression,
                           std::vector<const bng::ast::Expression*>& tables) {
    if (expression.kind() == bng::ast::ExpressionKind::TableFunction) {
        tables.push_back(&expression);
    }
    for (const auto& child : expression.args()) {
        collectTableFunctions(child, tables);
    }
}

std::string expressionForNfsim(const bng::ast::Expression& expression) {
    using bng::ast::ExpressionKind;
    switch (expression.kind()) {
    case ExpressionKind::Number:
    case ExpressionKind::Identifier:
        return expression.toString();
    case ExpressionKind::Unary:
        return expression.name() + expressionForNfsim(expression.args().front());
    case ExpressionKind::Binary:
        return "(" + expressionForNfsim(expression.args()[0]) + " " + expression.name() +
               " " + expressionForNfsim(expression.args()[1]) + ")";
    case ExpressionKind::Function:
    case ExpressionKind::ObservableRef: {
        std::ostringstream output;
        output << expression.name() << '(';
        for (std::size_t index = 0; index < expression.args().size(); ++index) {
            if (index != 0) output << ',';
            output << expressionForNfsim(expression.args()[index]);
        }
        output << ')';
        return output.str();
    }
    case ExpressionKind::TableFunction:
        return "__TFUN_VAL__";
    }
    return {};
}

// NFsim's legacy CompositeFunction reserves reactant_1 through reactant_9 for
// the current reaction's mapping counts.  They are not model functions or
// observables, even though the BNGL expression grammar represents the call as
// a function-shaped reference.
bool isReactantCountReference(const std::string& name) {
    return name.size() == 10 && name.compare(0, 9, "reactant_") == 0 &&
           name.back() >= '1' && name.back() <= '9';
}

bool expandDynamicRateExpression(
    const bng::ast::Expression& expression,
    const bng::ast::Model& model,
    const std::map<std::string, double>& parameters,
    std::set<std::string>& observableReferences,
    std::set<std::string>& functionCounterReferences,
    std::set<std::string>& parameterReferences,
    std::vector<const bng::ast::Expression*>& tableFunctions,
    std::set<std::string>* localFunctionReferences,
    std::set<std::string>* localFunctionArgumentNames,
    bool& usesTime,
    std::set<std::string>& activeFunctions,
    std::string& expanded,
    std::string& diagnostic) {
    using bng::ast::ExpressionKind;

    const auto preserveScopedModelFunctionCall =
        [&](const bng::ast::Function& function,
            const bng::ast::Expression& call,
            std::string& result) {
            if (localFunctionReferences == nullptr ||
                localFunctionArgumentNames == nullptr ||
                function.getArgs().size() != 1 || call.args().size() != 1 ||
                call.args().front().kind() != ExpressionKind::Identifier) {
                diagnostic = "dynamic rates require one scope identifier for "
                             "argument-bearing model function '" + function.getName() + "'";
                return false;
            }
            const auto& argument = call.args().front().name();
            localFunctionReferences->insert(function.getName());
            localFunctionArgumentNames->insert(argument);
            result = function.getName() + "(" + argument + ")";
            return true;
        };

    const auto expandModelFunction = [&](const bng::ast::Function& function,
                                         std::string& result) {
        if (!function.getArgs().empty()) {
            diagnostic = "dynamic rates cannot call argument-bearing model function '" +
                         function.getName() + "' without a local scope";
            return false;
        }
        if (!activeFunctions.insert(function.getName()).second) {
            diagnostic = "dynamic rate references recursive model function '" +
                         function.getName() + "'";
            return false;
        }
        std::string body;
        const bool ok = expandDynamicRateExpression(
            function.getExpression(), model, parameters, observableReferences,
            functionCounterReferences, parameterReferences, tableFunctions,
            localFunctionReferences, localFunctionArgumentNames, usesTime,
            activeFunctions, body, diagnostic);
        activeFunctions.erase(function.getName());
        if (ok) result = "(" + body + ")";
        return ok;
    };
    const auto expressionHasModelFunctionReference =
        [&](const auto& node, const auto& self) -> bool {
        if ((node.kind() == ExpressionKind::Identifier ||
             node.kind() == ExpressionKind::Function ||
             node.kind() == ExpressionKind::ObservableRef) &&
            getModelFunction(model, node.name()) != nullptr) {
            return true;
        }
        return std::any_of(node.args().begin(), node.args().end(),
                           [&](const auto& child) { return self(child, self); });
    };

    switch (expression.kind()) {
    case ExpressionKind::Number:
        expanded = expression.toString();
        return true;
    case ExpressionKind::Identifier: {
        const auto& name = expression.name();
        if (name == "time" || name == "t") {
            usesTime = true;
            expanded = name;
            return true;
        }
        if (parameters.count(name) != 0) {
            parameterReferences.insert(name);
            expanded = name;
            return true;
        }
        if (name == "_PI" || name == "_e" || name == "_Na") {
            expanded = name;
            return true;
        }
        if (isReactantCountReference(name)) {
            functionCounterReferences.insert(name);
            expanded = name;
            return true;
        }
        if (const auto* function = getModelFunction(model, name)) {
            if (!expressionHasModelFunctionReference(
                    function->getExpression(), expressionHasModelFunctionReference)) {
                functionCounterReferences.insert(name);
                expanded = name;
                return true;
            }
            return expandModelFunction(*function, expanded);
        }
        if (hasModelObservable(model, name)) {
            observableReferences.insert(name);
            expanded = name;
            return true;
        }
        diagnostic = "unknown identifier '" + name + "' in dynamic reaction rate";
        return false;
    }
    case ExpressionKind::Unary: {
        if (expression.args().size() != 1) {
            diagnostic = "malformed unary dynamic reaction rate expression";
            return false;
        }
        std::string operand;
        if (!expandDynamicRateExpression(
                expression.args().front(), model, parameters, observableReferences,
                functionCounterReferences, parameterReferences, tableFunctions,
                localFunctionReferences, localFunctionArgumentNames, usesTime,
                activeFunctions, operand, diagnostic)) {
            return false;
        }
        expanded = expression.name() + operand;
        return true;
    }
    case ExpressionKind::Binary: {
        if (expression.args().size() != 2) {
            diagnostic = "malformed binary dynamic reaction rate expression";
            return false;
        }
        std::string lhs;
        std::string rhs;
        if (!expandDynamicRateExpression(
                expression.args()[0], model, parameters, observableReferences,
                functionCounterReferences, parameterReferences, tableFunctions,
                localFunctionReferences, localFunctionArgumentNames, usesTime,
                activeFunctions, lhs, diagnostic) ||
            !expandDynamicRateExpression(
                expression.args()[1], model, parameters, observableReferences,
                functionCounterReferences, parameterReferences, tableFunctions,
                localFunctionReferences, localFunctionArgumentNames, usesTime,
                activeFunctions, rhs, diagnostic)) {
            return false;
        }
        expanded = "(" + lhs + " " + expression.name() + " " + rhs + ")";
        return true;
    }
    case ExpressionKind::Function: {
        const auto name = expression.name();
        const auto lowerName = lowerCase(name);
        if (lowerName == "time" || lowerName == "t") {
            if (!expression.args().empty()) {
                diagnostic = name + "() takes no arguments";
                return false;
            }
            usesTime = true;
            expanded = lowerName;
            return true;
        }
        if (isReactantCountReference(name)) {
            if (!expression.args().empty()) {
                diagnostic = name + "() takes no arguments";
                return false;
            }
            functionCounterReferences.insert(name);
            expanded = name + "()";
            return true;
        }
        if (const auto* function = getModelFunction(model, name)) {
            if (!expression.args().empty()) {
                return preserveScopedModelFunctionCall(*function, expression, expanded);
            }
            if (!expressionHasModelFunctionReference(
                    function->getExpression(), expressionHasModelFunctionReference)) {
                functionCounterReferences.insert(name);
                expanded = name + "()";
                return true;
            }
            return expandModelFunction(*function, expanded);
        }
        if (expression.args().empty() && hasModelObservable(model, name)) {
            observableReferences.insert(name);
            expanded = name + "()";
            return true;
        }
        if (!isSupportedGlobalBuiltin(name)) {
            diagnostic = "unsupported NFsim global-function builtin '" + name + "'";
            return false;
        }
        std::ostringstream output;
        output << name << '(';
        for (std::size_t index = 0; index < expression.args().size(); ++index) {
            if (index != 0) output << ',';
            std::string argument;
            if (!expandDynamicRateExpression(
                    expression.args()[index], model, parameters, observableReferences,
                    functionCounterReferences, parameterReferences, tableFunctions,
                    localFunctionReferences, localFunctionArgumentNames, usesTime,
                    activeFunctions, argument, diagnostic)) {
                return false;
            }
            output << argument;
        }
        output << ')';
        expanded = output.str();
        return true;
    }
    case ExpressionKind::ObservableRef: {
        const auto& name = expression.name();
        if (isReactantCountReference(name)) {
            if (!expression.args().empty()) {
                diagnostic = name + "() takes no arguments";
                return false;
            }
            functionCounterReferences.insert(name);
            expanded = name + "()";
            return true;
        }
        if (const auto* function = getModelFunction(model, name)) {
            if (!expression.args().empty()) {
                return preserveScopedModelFunctionCall(*function, expression, expanded);
            }
            if (!expressionHasModelFunctionReference(
                    function->getExpression(), expressionHasModelFunctionReference)) {
                functionCounterReferences.insert(name);
                expanded = name + "()";
                return true;
            }
            return expandModelFunction(*function, expanded);
        }
        if (!expression.args().empty() || !hasModelObservable(model, name)) {
            diagnostic = "observable reference '" + name +
                         "' is missing or has unsupported arguments";
            return false;
        }
        observableReferences.insert(name);
        expanded = name + "()";
        return true;
    }
    case ExpressionKind::TableFunction: {
        if (expression.args().size() != 1 ||
            (expression.tableFilePath().empty() &&
             (expression.tableXValues().empty() ||
              expression.tableXValues().size() != expression.tableYValues().size())) ||
            (!expression.tableFilePath().empty() &&
             (!expression.tableXValues().empty() || !expression.tableYValues().empty()))) {
            diagnostic = "malformed TFUN metadata";
            return false;
        }

        const auto& counter = expression.args().front();
        const auto counterName = counter.name();
        if (counter.kind() != ExpressionKind::Identifier &&
            counter.kind() != ExpressionKind::Function &&
            counter.kind() != ExpressionKind::ObservableRef) {
            diagnostic = "TFUN counter must be time, a parameter, observable, or function name";
            return false;
        }
        const auto lowerCounterName = lowerCase(counterName);
        if (lowerCounterName == "time" || lowerCounterName == "t") {
            if (!counter.args().empty()) {
                diagnostic = "TFUN time counter cannot take arguments";
                return false;
            }
            usesTime = true;
        } else if (counter.kind() == ExpressionKind::Identifier &&
                   parameters.count(counterName) != 0) {
            parameterReferences.insert(counterName);
        } else if (counter.args().empty() && hasModelObservable(model, counterName)) {
            observableReferences.insert(counterName);
        } else if (counter.args().empty()) {
            const auto* counterFunction = getModelFunction(model, counterName);
            if (counterFunction == nullptr || !counterFunction->getArgs().empty()) {
                diagnostic = "unsupported TFUN counter '" + counterName + "'";
                return false;
            }
            functionCounterReferences.insert(counterName);
        } else {
            diagnostic = "unsupported TFUN counter '" + counterName + "'";
            return false;
        }
        tableFunctions.push_back(&expression);
        expanded = "__TFUN_VAL__";
        return true;
    }
    }

    diagnostic = "unrecognized dynamic reaction rate expression";
    return false;
}

std::string replaceNamedReferences(
    const std::string& expression,
    const std::map<std::string, std::string>& replacements) {
    if (replacements.empty()) return expression;

    std::string result;
    result.reserve(expression.size());
    std::size_t index = 0;
    while (index < expression.size()) {
        const unsigned char first = static_cast<unsigned char>(expression[index]);
        if (!std::isalpha(first) && expression[index] != '_') {
            result.push_back(expression[index++]);
            continue;
        }

        const std::size_t start = index++;
        while (index < expression.size()) {
            const unsigned char current = static_cast<unsigned char>(expression[index]);
            if (!std::isalnum(current) && expression[index] != '_') break;
            ++index;
        }
        const std::string token = expression.substr(start, index - start);
        const auto replacement = replacements.find(token);
        if (replacement == replacements.end()) {
            result.append(expression, start, index - start);
            continue;
        }

        std::size_t lookahead = index;
        while (lookahead < expression.size() &&
               std::isspace(static_cast<unsigned char>(expression[lookahead]))) {
            ++lookahead;
        }
        if (lookahead < expression.size() && expression[lookahead] == '(') {
            std::size_t close = lookahead + 1;
            while (close < expression.size() &&
                   std::isspace(static_cast<unsigned char>(expression[close]))) {
                ++close;
            }
            if (close < expression.size() && expression[close] == ')') {
                result += replacement->second;
                result += "()";
                index = close + 1;
                continue;
            }
        }
        result += replacement->second;
    }
    return result;
}

bool configureDirectTableFunction(
    const bng::ast::Expression& table,
    const bng::ast::Model& model,
    const std::map<std::string, double>& parameters,
    const std::filesystem::path& sourcePath,
    System* system,
    GlobalFunction* global,
    CompositeFunction* composite,
    LocalFunction* local,
    std::string& diagnostic) {
    if (table.kind() != bng::ast::ExpressionKind::TableFunction ||
        table.args().size() != 1) {
        diagnostic = "malformed TFUN metadata";
        return false;
    }
    const bool fileBacked = !table.tableFilePath().empty();
    if (!fileBacked && (table.tableXValues().empty() ||
                        table.tableXValues().size() != table.tableYValues().size())) {
        diagnostic = "inline TFUN has empty or mismatched data columns";
        return false;
    }
    if (fileBacked && (!table.tableXValues().empty() || !table.tableYValues().empty())) {
        diagnostic = "file-backed TFUN cannot also contain inline data";
        return false;
    }

    const auto configureTarget = [&]() {
        try {
            if (global != nullptr) {
                if (fileBacked) {
                    global->enableFileDependency(
                        resolveTfunPath(table.tableFilePath(), sourcePath),
                        table.tableMethod());
                } else {
                    global->enableInlineDependency(
                        table.tableXValues(), table.tableYValues(), table.tableMethod());
                }
                global->setCtrName("__TFUN_VAL__");
            } else if (composite != nullptr) {
                if (fileBacked) {
                    composite->enableFileDependency(
                        resolveTfunPath(table.tableFilePath(), sourcePath),
                        table.tableMethod());
                } else {
                    composite->enableInlineDependency(
                        table.tableXValues(), table.tableYValues(), table.tableMethod());
                }
                composite->setCtrName("__TFUN_VAL__");
            } else if (local != nullptr) {
                if (fileBacked) {
                    local->enableFileDependency(
                        resolveTfunPath(table.tableFilePath(), sourcePath),
                        table.tableMethod());
                } else {
                    local->enableInlineDependency(
                        table.tableXValues(), table.tableYValues(), table.tableMethod());
                }
                local->setCtrName("__TFUN_VAL__");
            } else {
                diagnostic = "TFUN has no target function object";
                return false;
            }
        } catch (const std::exception& error) {
            diagnostic = "could not load TFUN table";
            if (fileBacked) {
                diagnostic += " '" + resolveTfunPath(table.tableFilePath(), sourcePath) + "'";
            }
            diagnostic += ": " + std::string(error.what());
            return false;
        }
        return true;
    };

    const auto& counter = table.args().front();
    const auto attachObservable = [&](const std::string& name) {
        auto* observable = system->getObservableByName(name);
        if (observable == nullptr) {
            diagnostic = "TFUN observable counter '" + name + "' is not registered";
            return false;
        }
        if (global != nullptr) observable->addReferenceToGlobalFunction(global);
        if (composite != nullptr) observable->addReferenceToCompositeFunction(composite);
        if (local != nullptr) {
            local->setCounterFromObservable(observable);
        }
        return true;
    };
    const auto attachFunction = [&](const std::string& name) {
        if (composite == nullptr) {
            diagnostic = "local/global TFUN cannot use a function counter";
            return false;
        }
        auto* counterFunction = system->getGlobalFunctionByName(name);
        if (counterFunction == nullptr) {
            diagnostic = "TFUN counter function '" + name + "' is not a base global";
            return false;
        }
        composite->addFunctionPointer(counterFunction);
        return true;
    };

    std::string counterName;
    if (counter.kind() == bng::ast::ExpressionKind::Identifier ||
        counter.kind() == bng::ast::ExpressionKind::ObservableRef ||
        counter.kind() == bng::ast::ExpressionKind::Function) {
        counterName = counter.name();
    }
    if (counterName.empty()) {
        diagnostic = "TFUN counter must be time, a parameter, observable, or function name";
        return false;
    }

    if (lowerCase(counterName) == "time" || lowerCase(counterName) == "t") {
        if ((counter.kind() == bng::ast::ExpressionKind::ObservableRef ||
             counter.kind() == bng::ast::ExpressionKind::Function) &&
            !counter.args().empty()) {
            diagnostic = "TFUN time counter cannot take arguments";
            return false;
        }
        if (!configureTarget()) return false;
        if (global != nullptr) global->setCounterFromTime(system);
        else if (composite != nullptr) composite->setCounterFromTime(system);
        else local->setCounterFromTime(system);
        return true;
    }

    if (counter.kind() == bng::ast::ExpressionKind::Identifier &&
        parameters.count(counterName) != 0) {
        if (!configureTarget()) return false;
        if (global != nullptr) global->setCounterFromParameter(system, counterName);
        else if (composite != nullptr) composite->setCounterFromParameter(system, counterName);
        else local->setCounterFromParameter(system, counterName);
        return true;
    }

    const bool namedObservable =
        (counter.kind() == bng::ast::ExpressionKind::Identifier ||
         counter.kind() == bng::ast::ExpressionKind::ObservableRef) &&
        counter.args().empty() && hasModelObservable(model, counterName);
    if (namedObservable) {
        if (!attachObservable(counterName)) return false;
        if (!configureTarget()) return false;
        return true;
    }

    const bool namedFunction =
        (counter.kind() == bng::ast::ExpressionKind::Identifier ||
         counter.kind() == bng::ast::ExpressionKind::ObservableRef ||
         counter.kind() == bng::ast::ExpressionKind::Function) &&
        counter.args().empty() && hasModelFunction(model, counterName);
    if (namedFunction) {
        if (!attachFunction(counterName)) return false;
        if (!configureTarget()) return false;
        return true;
    }

    diagnostic = "unsupported TFUN counter '" + counterName + "'";
    return false;
}

bool collectGlobalFunctionReferences(
    const bng::ast::Expression& expression, const bng::ast::Model& model,
    const std::map<std::string, double>& parameters, std::set<std::string>&
        observableReferences, std::set<std::string>& functionReferences,
    std::string& diagnostic) {
    using bng::ast::ExpressionKind;

    switch (expression.kind()) {
    case ExpressionKind::Number:
        return true;
    case ExpressionKind::Identifier: {
        const auto& name = expression.name();
        if (name == "time" || name == "t") {
            return true;
        }
        if (parameters.count(name) != 0 || name == "_PI" || name == "_e" ||
            name == "_Na") {
            return true;
        }
        if (hasModelObservable(model, name)) {
            observableReferences.insert(name);
            return true;
        }
        if (hasModelFunction(model, name)) {
            const auto* target = getModelFunction(model, name);
            if (target == nullptr || !target->getArgs().empty()) {
                diagnostic = "global function references argument-bearing model function '" +
                             name + "'";
                return false;
            }
            functionReferences.insert(name);
            return true;
        }
        diagnostic = "unknown identifier '" + name + "'";
        return false;
    }
    case ExpressionKind::Unary:
    case ExpressionKind::Binary:
        for (const auto& child : expression.args()) {
            if (!collectGlobalFunctionReferences(child, model, parameters,
                                                  observableReferences, functionReferences,
                                                  diagnostic)) {
                return false;
            }
        }
        return true;
    case ExpressionKind::TableFunction:
        if (expression.args().size() != 1 ||
            (expression.tableFilePath().empty() &&
             (expression.tableXValues().empty() ||
              expression.tableXValues().size() != expression.tableYValues().size())) ||
            (!expression.tableFilePath().empty() &&
             (!expression.tableXValues().empty() || !expression.tableYValues().empty()))) {
            diagnostic = "malformed TFUN metadata";
            return false;
        }
        return collectGlobalFunctionReferences(
            expression.args().front(), model, parameters, observableReferences,
            functionReferences, diagnostic);
    case ExpressionKind::Function:
        if (lowerCase(expression.name()) == "time" ||
            lowerCase(expression.name()) == "t") {
            if (!expression.args().empty()) {
                diagnostic = expression.name() + "() takes no arguments";
                return false;
            }
            return true;
        }
        if (hasModelFunction(model, expression.name())) {
            const auto* target = getModelFunction(model, expression.name());
            if (target == nullptr || !target->getArgs().empty() ||
                !expression.args().empty()) {
                diagnostic = "global function calls argument-bearing model function '" +
                             expression.name() + "' (local mapping is not yet direct)";
                return false;
            }
            functionReferences.insert(expression.name());
            return true;
        }
        if (!isSupportedGlobalBuiltin(expression.name())) {
            diagnostic = "unsupported NFsim global-function builtin '" +
                         expression.name() + "'";
            return false;
        }
        for (const auto& child : expression.args()) {
            if (!collectGlobalFunctionReferences(child, model, parameters,
                                                  observableReferences, functionReferences,
                                                  diagnostic)) {
                return false;
            }
        }
        return true;
    case ExpressionKind::ObservableRef:
        if (hasModelFunction(model, expression.name())) {
            const auto* target = getModelFunction(model, expression.name());
            if (target == nullptr || !target->getArgs().empty() ||
                !expression.args().empty()) {
                diagnostic = "global function calls argument-bearing model function '" +
                             expression.name() + "' (local mapping is not yet direct)";
                return false;
            }
            functionReferences.insert(expression.name());
            return true;
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

bool expressionUsesTime(const bng::ast::Expression& expression) {
    if (expression.kind() == bng::ast::ExpressionKind::Identifier &&
        (expression.name() == "time" || expression.name() == "t")) {
        return true;
    }
    if (expression.kind() == bng::ast::ExpressionKind::Function &&
        (lowerCase(expression.name()) == "time" ||
         lowerCase(expression.name()) == "t")) {
        return true;
    }
    return std::any_of(expression.args().begin(), expression.args().end(),
                       [](const auto& child) { return expressionUsesTime(child); });
}

bool collectLocalFunctionReferences(
    const bng::ast::Expression& expression, const bng::ast::Model& model,
    const std::map<std::string, double>& parameters, const std::string& argumentName,
    std::vector<std::pair<std::string, std::string>>& references,
    std::string& diagnostic) {
    using bng::ast::ExpressionKind;

    const auto addReference = [&](const std::string& name, const std::string& type) {
        const auto reference = std::make_pair(name, type);
        if (std::find(references.begin(), references.end(), reference) == references.end()) {
            references.push_back(reference);
        }
    };

    switch (expression.kind()) {
    case ExpressionKind::Number:
        return true;
    case ExpressionKind::Identifier:
        if (expression.name() == argumentName) {
            diagnostic = "local argument '" + argumentName +
                         "' must scope an observable reference";
            return false;
        }
        if (expression.name() == "time" || expression.name() == "t") {
            return true;
        }
        if (parameters.count(expression.name()) != 0 || expression.name() == "_PI" ||
            expression.name() == "_e" || expression.name() == "_Na") {
            if (parameters.count(expression.name()) != 0) {
                addReference(expression.name(), "Constant");
            }
            return true;
        }
        if (hasModelObservable(model, expression.name())) {
            // BNGL permits a zero-argument observable in a local function
            // without an explicit call, e.g. ``k*Total + 0*Scoped(x)``.
            // NFsim's legacy local-function constructor treats this as a
            // global-scope observable reference.
            addReference(expression.name(), "Observable");
            return true;
        }
        diagnostic = "unknown local-function identifier '" + expression.name() + "'";
        return false;
    case ExpressionKind::Unary:
    case ExpressionKind::Binary:
        for (const auto& child : expression.args()) {
            if (!collectLocalFunctionReferences(child, model, parameters, argumentName,
                                                 references, diagnostic)) {
                return false;
            }
        }
        return true;
    case ExpressionKind::TableFunction:
        if (expression.args().size() != 1 ||
            (expression.tableFilePath().empty() &&
             (expression.tableXValues().empty() ||
              expression.tableXValues().size() != expression.tableYValues().size())) ||
            (!expression.tableFilePath().empty() &&
             (!expression.tableXValues().empty() || !expression.tableYValues().empty()))) {
            diagnostic = "malformed local TFUN metadata";
            return false;
        }
        if ((expression.args().front().kind() == ExpressionKind::Identifier ||
             expression.args().front().kind() == ExpressionKind::ObservableRef) &&
            expression.args().front().args().empty() &&
            hasModelObservable(model, expression.args().front().name())) {
            return true;
        }
        return collectLocalFunctionReferences(
            expression.args().front(), model, parameters, argumentName, references,
            diagnostic);
    case ExpressionKind::Function:
        if (lowerCase(expression.name()) == "time" ||
            lowerCase(expression.name()) == "t") {
            if (!expression.args().empty()) {
                diagnostic = "local function time/t references must have no arguments";
                return false;
            }
            return true;
        }
        if (hasModelFunction(model, expression.name())) {
            diagnostic = "local function calls model function '" + expression.name() +
                         "' (nested local/composite mapping is not direct yet)";
            return false;
        }
        if (!isSupportedGlobalBuiltin(expression.name())) {
            diagnostic = "unsupported NFsim local-function builtin '" +
                         expression.name() + "'";
            return false;
        }
        for (const auto& child : expression.args()) {
            if (!collectLocalFunctionReferences(child, model, parameters, argumentName,
                                                 references, diagnostic)) {
                return false;
            }
        }
        return true;
    case ExpressionKind::ObservableRef:
        if (hasModelFunction(model, expression.name())) {
            diagnostic = "local function calls model function '" + expression.name() +
                         "' (nested local/composite mapping is not direct yet)";
            return false;
        }
        if (!hasModelObservable(model, expression.name())) {
            diagnostic = "local function references unknown observable '" +
                         expression.name() + "'";
            return false;
        }
        if (expression.args().empty()) {
            addReference(expression.name(), "Observable");
            return true;
        }
        if (expression.args().size() == 1 &&
            expression.args().front().kind() == ExpressionKind::Identifier &&
            expression.args().front().name() == argumentName) {
            addReference(expression.name(), "Observable");
            return true;
        }
        diagnostic = "local observable '" + expression.name() +
                     "' must use exactly the local argument '" + argumentName + "'";
        return false;
    }

    diagnostic = "unrecognized local-function expression node";
    return false;
}

void collectModelFunctionCalls(
    const bng::ast::Expression& expression,
    const bng::ast::Model& model,
    std::vector<const bng::ast::Expression*>& calls) {
    using bng::ast::ExpressionKind;
    if ((expression.kind() == ExpressionKind::Identifier ||
         expression.kind() == ExpressionKind::Function ||
         expression.kind() == ExpressionKind::ObservableRef) &&
        hasModelFunction(model, expression.name())) {
        calls.push_back(&expression);
    }
    for (const auto& child : expression.args()) {
        collectModelFunctionCalls(child, model, calls);
    }
}

bool validateNestedLocalCompositeExpression(
    const bng::ast::Expression& expression,
    const bng::ast::Model& model,
    const std::map<std::string, double>& parameters,
    const std::string& argumentName,
    std::string& diagnostic) {
    using bng::ast::ExpressionKind;

    switch (expression.kind()) {
    case ExpressionKind::Number:
        return true;
    case ExpressionKind::Identifier:
        if (hasModelFunction(model, expression.name())) {
            const auto* target = getModelFunction(model, expression.name());
            if (target == nullptr || !target->getArgs().empty()) {
                diagnostic = "nested local composite uses an argument-bearing function "
                             "without the local argument";
                return false;
            }
            return true;
        }
        if (expression.name() == argumentName) {
            diagnostic = "nested local composite cannot use a bare local argument";
            return false;
        }
        if (expression.name() == "time" || expression.name() == "t" ||
            parameters.count(expression.name()) != 0 || expression.name() == "_PI" ||
            expression.name() == "_e" || expression.name() == "_Na") {
            return true;
        }
        diagnostic = "nested local composite has unsupported identifier '" +
                     expression.name() + "'";
        return false;
    case ExpressionKind::Unary:
    case ExpressionKind::Binary:
        for (const auto& child : expression.args()) {
            if (!validateNestedLocalCompositeExpression(
                    child, model, parameters, argumentName, diagnostic)) {
                return false;
            }
        }
        return true;
    case ExpressionKind::Function:
        if (hasModelFunction(model, expression.name())) {
            const auto* target = getModelFunction(model, expression.name());
            if (target == nullptr) {
                diagnostic = "nested local composite references an unknown model function";
                return false;
            }
            if (target->getArgs().empty()) {
                if (!expression.args().empty()) {
                    diagnostic = "zero-argument model function '" + expression.name() +
                                 "' was called with arguments";
                    return false;
                }
                return true;
            }
            if (target->getArgs().size() != 1 || expression.args().size() != 1 ||
                expression.args().front().kind() != ExpressionKind::Identifier ||
                expression.args().front().name() != argumentName) {
                diagnostic = "nested local composite calls '" + expression.name() +
                             "' with an unsupported argument";
                return false;
            }
            return true;
        }
        if (lowerCase(expression.name()) == "time" ||
            lowerCase(expression.name()) == "t") {
            if (!expression.args().empty()) {
                diagnostic = "nested local composite time/t references take no arguments";
                return false;
            }
            return true;
        }
        if (!isSupportedGlobalBuiltin(expression.name())) {
            diagnostic = "nested local composite uses unsupported builtin '" +
                         expression.name() + "'";
            return false;
        }
        for (const auto& child : expression.args()) {
            if (!validateNestedLocalCompositeExpression(
                    child, model, parameters, argumentName, diagnostic)) {
                return false;
            }
        }
        return true;
    case ExpressionKind::ObservableRef:
        if (hasModelFunction(model, expression.name())) {
            const auto* target = getModelFunction(model, expression.name());
            if (target == nullptr) {
                diagnostic = "nested local composite references an unknown model function";
                return false;
            }
            if (target->getArgs().empty() && expression.args().empty()) return true;
            if (target->getArgs().size() == 1 && expression.args().size() == 1 &&
                expression.args().front().kind() == ExpressionKind::Identifier &&
                expression.args().front().name() == argumentName) {
                return true;
            }
            diagnostic = "nested local composite calls model function '" +
                         expression.name() + "' with an unsupported argument";
            return false;
        }
        diagnostic = "nested local composite cannot reference observables directly";
        return false;
    case ExpressionKind::TableFunction:
        diagnostic = "nested local composites do not combine with TFUN expressions";
        return false;
    }

    diagnostic = "unrecognized nested local composite expression node";
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
        std::vector<const bng::ast::MoleculeType*> moleculeTypes;
        moleculeTypes.reserve(model.getMoleculeTypes().size());
        for (const auto& moleculeType : model.getMoleculeTypes()) {
            moleculeTypes.push_back(&moleculeType);
        }
        std::sort(moleculeTypes.begin(), moleculeTypes.end(),
                  [](const auto* left, const auto* right) {
                      return left->getName() < right->getName();
                  });

        for (const auto* moleculeTypePtr : moleculeTypes) {
            const auto& moleculeType = *moleculeTypePtr;
            const std::string& typeName = moleculeType.getName();
            if (typeName.empty()) {
                std::cerr << "[nfsim/ast] molecule type is missing a name\n";
                return false;
            }
            // Null is an NFsim keyword, not a constructible molecule type.
            // It is accepted in product positions as the degradation sink,
            // but NFsim rejects it in reactant and observable patterns.
            const std::string normalizedName = lowerCase(typeName);
            if (normalizedName == "null") {
                if (verbose) {
                    std::cerr << "[nfsim/ast] skipping reserved molecule type '"
                              << typeName << "'\n";
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
                    // `?` is a pattern wildcard, never a constructible
                    // state.  NFinput::initMoleculeTypes also keeps PLUS and
                    // MINUS out of the string-state count so an otherwise
                    // numeric component remains an integer site; they are
                    // transition sentinels consumed by the rule builder.
                    if (state == "?") {
                        continue;
                    }
                    int integerValue = 0;
                    if (parseIntegerState(state, integerValue)) {
                        hasIntegerState = true;
                        hasNegativeInteger = hasNegativeInteger || integerValue < 0;
                        maximumState = std::max(maximumState, integerValue);
                    } else {
                        if (state == "PLUS" || state == "MINUS") {
                            hasPlusMinusState = true;
                        } else {
                            hasStringState = true;
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
                        if (state == "?") {
                            continue;
                        }
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
                         const std::map<std::string, double>& parameters, bool verbose,
                         const std::filesystem::path& sourcePath) {
    // SPEC: NFinput::initFunctions (parseFuncXML.cpp:488).
    // This slice handles parameter/observable/time-backed global functions,
    // composites whose dependencies are all zero-argument global functions,
    // bounded one-level nested local composites, and the bounded one-argument
    // local-function mapping below. Both inline
    // and file-backed TFUN are represented by NFsim's existing file-function
    // machinery; relative table paths resolve beside the BNGL source when the
    // caller supplies it.
    if (s == nullptr) return false;

    std::unordered_set<std::string> names;
    for (const auto& function : model.getFunctions()) {
        const std::string& name = function.getName();
        if (name.empty() || !names.insert(name).second ||
            s->getGlobalFunctionByName(name) != nullptr ||
            s->getCompositeFunctionByName(name) != nullptr ||
            s->getLocalFunctionByName(name) != nullptr) {
            std::cerr << "[nfsim/ast] duplicate or missing global function '" << name
                      << "'\n";
            return false;
        }
        if (function.getArgs().size() > 1) {
            std::cerr << "[nfsim/ast] function '" << name
                      << "' has more than one argument; NFsim local functions support one\n";
            return false;
        }
    }

    // Keep the legacy local-function constructor as the semantic oracle, but
    // feed it references collected from the AST instead of XML attributes.
    std::map<std::string, double> legacyParameters(parameters);
    std::map<std::string, int> legacyAllowedStates;
    std::vector<const bng::ast::Function*> pendingFunctionCounterTfun;
    std::vector<const bng::ast::Function*> pendingNestedLocalComposites;
    const auto isFunctionCounterTfun = [&](const bng::ast::Function& function) {
        std::vector<const bng::ast::Expression*> tables;
        collectTableFunctions(function.getExpression(), tables);
        if (tables.size() != 1 || tables.front()->args().size() != 1) return false;
        const auto& counter = tables.front()->args().front();
        if ((counter.kind() != bng::ast::ExpressionKind::Identifier &&
             counter.kind() != bng::ast::ExpressionKind::Function &&
             counter.kind() != bng::ast::ExpressionKind::ObservableRef) ||
            !counter.args().empty()) {
            return false;
        }
        const auto* counterFunction = getModelFunction(model, counter.name());
        return counterFunction != nullptr && counterFunction->getArgs().empty();
    };
    const auto isBoundedNestedLocalComposite = [&](const bng::ast::Function& function,
                                                    std::string& diagnostic) {
        if (function.getArgs().size() != 1) return false;

        std::vector<const bng::ast::Expression*> calls;
        collectModelFunctionCalls(function.getExpression(), model, calls);
        if (calls.empty()) return false;

        for (const auto* call : calls) {
            const auto* target = getModelFunction(model, call->name());
            if (target == nullptr || target->getName() == function.getName()) return false;
            if (target->getArgs().empty()) {
                if (!call->args().empty()) return false;
                std::vector<const bng::ast::Expression*> targetCalls;
                collectModelFunctionCalls(target->getExpression(), model, targetCalls);
                if (!targetCalls.empty()) return false;
                continue;
            }
            if (target->getArgs().size() != 1 || isFunctionCounterTfun(*target)) return false;

            std::vector<const bng::ast::Expression*> targetCalls;
            collectModelFunctionCalls(target->getExpression(), model, targetCalls);
            if (!targetCalls.empty()) return false;

            std::vector<std::pair<std::string, std::string>> targetReferences{
                {target->getArgs().front(), "Local"}};
            std::string targetDiagnostic;
            if (!collectLocalFunctionReferences(
                    target->getExpression(), model, parameters,
                    target->getArgs().front(), targetReferences, targetDiagnostic)) {
                return false;
            }
        }

        return validateNestedLocalCompositeExpression(
            function.getExpression(), model, parameters,
            function.getArgs().front(), diagnostic);
    };
    for (const auto& function : model.getFunctions()) {
        if (function.getArgs().empty()) continue;

        std::vector<std::pair<std::string, std::string>> references;
        for (const auto& argument : function.getArgs()) {
            references.emplace_back(argument, "Local");
        }
        std::string diagnostic;
        if (!collectLocalFunctionReferences(
                function.getExpression(), model, parameters, function.getArgs().front(),
                references, diagnostic)) {
            if (isFunctionCounterTfun(function)) {
                pendingFunctionCounterTfun.push_back(&function);
                continue;
            }
            std::string compositeDiagnostic;
            if (isBoundedNestedLocalComposite(function, compositeDiagnostic)) {
                pendingNestedLocalComposites.push_back(&function);
                continue;
            }
            std::cerr << "[nfsim/ast] cannot map local function '" << function.getName()
                      << "': " << diagnostic << "\n";
            return false;
        }

        std::vector<const bng::ast::Expression*> tableFunctions;
        collectTableFunctions(function.getExpression(), tableFunctions);
        if (tableFunctions.size() > 1) {
            std::cerr << "[nfsim/ast] local function '" << function.getName()
                      << "' has more than one TFUN expression; direct NFsim supports one"
                      << " table per function\n";
            return false;
        }

        std::stable_sort(
            references.begin(), references.end(),
            [](const auto& lhs, const auto& rhs) { return lhs.first.size() > rhs.first.size(); });
        std::vector<std::string> referenceNames;
        std::vector<std::string> referenceTypes;
        for (const auto& [name, type] : references) {
            referenceNames.push_back(name);
            referenceTypes.push_back(type);
        }
        auto argumentNames = function.getArgs();
        if (!::createLocalFunction(
                function.getName(), expressionForNfsim(function.getExpression()), argumentNames,
                referenceNames, referenceTypes, s, legacyParameters, nullptr,
                legacyAllowedStates, verbose)) {
            std::cerr << "[nfsim/ast] legacy local-function construction failed for '"
                      << function.getName() << "'\n";
            return false;
        }

        auto* local = s->getLocalFunctionByName(function.getName());
        if (local == nullptr) {
            std::cerr << "[nfsim/ast] failed to resolve local function '"
                      << function.getName() << "'\n";
            return false;
        }
        if (!tableFunctions.empty()) {
            std::string tableDiagnostic;
            if (!configureDirectTableFunction(
                    *tableFunctions.front(), model, parameters, sourcePath, s,
                    nullptr, nullptr, local, tableDiagnostic)) {
                std::cerr << "[nfsim/ast] cannot map TFUN local function '"
                          << function.getName() << "': " << tableDiagnostic << "\n";
                return false;
            }
        }

        if (expressionUsesTime(function.getExpression())) {
            local->setTimeDependent(true);
            s->setHasTimeDependentFunctions(true);
        }

        // NFsim's DOR reaction expects a composite wrapper even when its body
        // is just a single local function call.  The wrapper is also how the
        // XML loader represents local rate functions.
        std::vector<std::string> functionsCalled{function.getName()};
        std::vector<std::string> parameterNames;
        auto* composite = new CompositeFunction(
            s, function.getName(),
            function.getName() + "(" + function.getArgs().front() + ")",
            functionsCalled, argumentNames, parameterNames);
        if (!s->addCompositeFunction(composite)) {
            delete composite;
            std::cerr << "[nfsim/ast] failed to register local-function wrapper '"
                      << function.getName() << "'\n";
            return false;
        }
        if (verbose) {
            std::cerr << "[nfsim/ast] local function " << function.getName() << "("
                      << function.getArgs().front() << ") = "
                      << function.getExpression().toString() << "\n";
        }
    }

    struct PendingFunction {
        std::string name;
        std::string expression;
        std::vector<std::string> observableReferences;
        std::vector<std::string> functionReferences;
        std::vector<std::string> parameterReferences;
        bool usesTime = false;
        const bng::ast::Expression* tableFunction = nullptr;
    };
    std::vector<PendingFunction> pending;
    pending.reserve(model.getFunctions().size());

    for (const auto& function : model.getFunctions()) {
        if (!function.getArgs().empty()) continue;
        std::set<std::string> observableReferences;
        std::set<std::string> functionReferences;
        std::set<std::string> parameterReferences;
        std::vector<const bng::ast::Expression*> tableFunctions;
        bool usesTime = false;
        std::set<std::string> activeFunctions;
        std::string expandedExpression;
        std::string diagnostic;
        if (!expandDynamicRateExpression(
                function.getExpression(), model, parameters, observableReferences,
                functionReferences, parameterReferences, tableFunctions, nullptr, nullptr,
                usesTime, activeFunctions, expandedExpression, diagnostic)) {
            std::cerr << "[nfsim/ast] cannot map function '" << function.getName()
                      << "': " << diagnostic << "\n";
            return false;
        }
        if (tableFunctions.size() > 1) {
            std::cerr << "[nfsim/ast] function '" << function.getName()
                      << "' has more than one TFUN expression; direct NFsim supports one"
                      << " table per function\n";
            return false;
        }

        PendingFunction next {
            function.getName(),
            expandedExpression,
            {observableReferences.begin(), observableReferences.end()},
            {functionReferences.begin(), functionReferences.end()},
            {parameterReferences.begin(), parameterReferences.end()},
            usesTime,
            tableFunctions.empty() ? nullptr : tableFunctions.front()};
        pending.push_back(std::move(next));
    }

    // Base globals must exist before composites are finalized.  This mirrors
    // the XML loader, which resolves composite references after all function
    // declarations have been created.
    for (const auto& function : pending) {
        if (!function.functionReferences.empty()) continue;
        // GlobalFunction predates const-correctness and takes mutable vector
        // references; keep the staged metadata immutable until this boundary,
        // then pass local copies to its legacy constructor.
        auto referenceNames = function.observableReferences;
        std::vector<std::string> referenceTypes(referenceNames.size(), "Observable");
        auto parameterNames = function.parameterReferences;
        auto* global = new GlobalFunction(function.name, function.expression,
                                           referenceNames, referenceTypes, parameterNames, s);
        if (function.tableFunction != nullptr) {
            std::string diagnostic;
            if (!configureDirectTableFunction(*function.tableFunction, model, parameters,
                                              sourcePath, s, global, nullptr, nullptr,
                                              diagnostic)) {
                delete global;
                std::cerr << "[nfsim/ast] cannot map TFUN function '" << function.name
                          << "': " << diagnostic << "\n";
                return false;
            }
        }
        if (!s->addGlobalFunction(global)) {
            delete global;
            std::cerr << "[nfsim/ast] failed to register global function '"
                      << function.name << "'\n";
            return false;
        }
        if (function.usesTime) {
            global->setCounterFromTime(s);
            s->setHasTimeDependentFunctions(true);
        }
        if (verbose) {
            std::cerr << "[nfsim/ast] global function " << function.name << "() = "
                      << function.expression << "\n";
        }
    }

    // A bounded nested local function is also represented as a composite in
    // NFsim.  Its dependencies may be one plain local function with the same
    // argument plus zero-argument base globals; deeper composite chains remain
    // fail-closed above.
    for (const auto* function : pendingNestedLocalComposites) {
        std::set<std::string> functionReferences;
        std::vector<const bng::ast::Expression*> calls;
        collectModelFunctionCalls(function->getExpression(), model, calls);
        for (const auto* call : calls) functionReferences.insert(call->name());

        for (const auto& dependency : functionReferences) {
            const auto* target = getModelFunction(model, dependency);
            if (target == nullptr) {
                std::cerr << "[nfsim/ast] nested local function '" << function->getName()
                          << "' references an unknown model function '" << dependency
                          << "'\n";
                return false;
            }
            if (target->getArgs().empty()) {
                if (s->getGlobalFunctionByName(dependency) == nullptr) {
                    std::cerr << "[nfsim/ast] nested local function '" << function->getName()
                              << "' requires base global '" << dependency << "'\n";
                    return false;
                }
            } else if (s->getLocalFunctionByName(dependency) == nullptr) {
                std::cerr << "[nfsim/ast] nested local function '" << function->getName()
                          << "' requires plain local dependency '" << dependency << "'\n";
                return false;
            }
        }

        std::vector<std::string> functionsCalled(
            functionReferences.begin(), functionReferences.end());
        std::vector<std::string> argumentNames = function->getArgs();
        std::vector<std::string> parameterNames;
        for (const auto& dependency : function->getExpression().getDependencies()) {
            if (parameters.count(dependency) != 0) parameterNames.push_back(dependency);
        }
        auto* composite = new CompositeFunction(
            s, function->getName(), expressionForNfsim(function->getExpression()),
            functionsCalled, argumentNames, parameterNames);
        if (!s->addCompositeFunction(composite)) {
            delete composite;
            std::cerr << "[nfsim/ast] failed to register nested local function '"
                      << function->getName() << "'\n";
            return false;
        }
        if (expressionUsesTime(function->getExpression())) {
            composite->setCounterFromTime(s);
            s->setHasTimeDependentFunctions(true);
        }
        if (verbose) {
            std::cerr << "[nfsim/ast] nested local composite " << function->getName()
                      << "(" << (argumentNames.empty() ? "" : argumentNames.front())
                      << ") = " << function->getExpression().toString() << "\n";
        }
    }

    // A function-counter TFUN with an argument is a composite function in
    // NFsim's XML loader, not a LocalFunction.  Build that same object after
    // all zero-argument base globals have been registered.
    for (const auto* function : pendingFunctionCounterTfun) {
        std::set<std::string> observableReferences;
        std::set<std::string> functionReferences;
        std::string diagnostic;
        if (!collectGlobalFunctionReferences(
                function->getExpression(), model, parameters,
                observableReferences, functionReferences, diagnostic)) {
            std::cerr << "[nfsim/ast] cannot map function-counter TFUN '"
                      << function->getName() << "': " << diagnostic << "\n";
            return false;
        }
        if (!observableReferences.empty()) {
            std::cerr << "[nfsim/ast] function-counter TFUN '" << function->getName()
                      << "' cannot reference observables in its composite body\n";
            return false;
        }

        std::vector<const bng::ast::Expression*> tableFunctions;
        collectTableFunctions(function->getExpression(), tableFunctions);
        const auto& counter = tableFunctions.front()->args().front();
        const auto counterName = counter.name();
        const auto counterFunction = getModelFunction(model, counterName);
        if (counterFunction == nullptr || !counterFunction->getArgs().empty() ||
            s->getGlobalFunctionByName(counterName) == nullptr) {
            std::cerr << "[nfsim/ast] function-counter TFUN '" << function->getName()
                      << "' requires a base global counter '" << counterName << "'\n";
            return false;
        }
        if (expressionUsesTime(function->getExpression()) &&
            lowerCase(counterName) != "time" && lowerCase(counterName) != "t") {
            std::cerr << "[nfsim/ast] function-counter TFUN '" << function->getName()
                      << "' cannot combine a function counter with a time-dependent body\n";
            return false;
        }

        std::vector<std::string> functionsCalled(
            functionReferences.begin(), functionReferences.end());
        std::vector<std::string> argumentNames = function->getArgs();
        std::vector<std::string> parameterNames;
        for (const auto& dependency : function->getExpression().getDependencies()) {
            if (parameters.count(dependency) != 0) parameterNames.push_back(dependency);
        }
        auto* composite = new CompositeFunction(
            s, function->getName(), expressionForNfsim(function->getExpression()),
            functionsCalled, argumentNames, parameterNames);
        if (!configureDirectTableFunction(
                *tableFunctions.front(), model, parameters, sourcePath, s,
                nullptr, composite, nullptr, diagnostic)) {
            delete composite;
            std::cerr << "[nfsim/ast] cannot map function-counter TFUN '"
                      << function->getName() << "': " << diagnostic << "\n";
            return false;
        }
        if (!s->addCompositeFunction(composite)) {
            delete composite;
            std::cerr << "[nfsim/ast] failed to register function-counter TFUN '"
                      << function->getName() << "'\n";
            return false;
        }
        if (expressionUsesTime(function->getExpression())) {
            composite->setCounterFromTime(s);
            s->setHasTimeDependentFunctions(true);
        }
        if (verbose) {
            std::cerr << "[nfsim/ast] function-counter TFUN " << function->getName()
                      << "(" << (argumentNames.empty() ? "" : argumentNames.front())
                      << ") = " << function->getExpression().toString() << "\n";
        }
    }

    for (const auto& function : pending) {
        if (function.functionReferences.empty()) continue;
        if (!function.observableReferences.empty() && function.tableFunction == nullptr) {
            std::cerr << "[nfsim/ast] cannot map composite function '" << function.name
                      << "': composite functions cannot reference observables\n";
            return false;
        }

        std::vector<std::string> functionsCalled;
        for (const auto& dependency : function.functionReferences) {
            if (isReactantCountReference(dependency)) {
                functionsCalled.push_back(dependency);
                continue;
            }
            const auto* target = getModelFunction(model, dependency);
            const auto targetPending = std::find_if(
                pending.begin(), pending.end(),
                [&](const PendingFunction& candidate) { return candidate.name == dependency; });
            if (target == nullptr || !target->getArgs().empty() ||
                targetPending == pending.end() ||
                !targetPending->functionReferences.empty()) {
                std::cerr << "[nfsim/ast] cannot map composite function '" << function.name
                          << "': dependency '" << dependency
                          << "' is not a base global function\n";
                return false;
            }
            functionsCalled.push_back(dependency);
        }

        auto argumentNames = std::vector<std::string> {};
        auto parameterNames = function.parameterReferences;
        auto* composite = new CompositeFunction(
            s, function.name, function.expression, functionsCalled,
            argumentNames, parameterNames);
        if (function.tableFunction != nullptr) {
            std::string diagnostic;
            if (!configureDirectTableFunction(*function.tableFunction, model, parameters,
                                              sourcePath, s, nullptr, composite, nullptr,
                                              diagnostic)) {
                delete composite;
                std::cerr << "[nfsim/ast] cannot map TFUN composite '" << function.name
                          << "': " << diagnostic << "\n";
                return false;
            }
        }
        if (!s->addCompositeFunction(composite)) {
            delete composite;
            std::cerr << "[nfsim/ast] failed to register composite function '"
                      << function.name << "'\n";
            return false;
        }
        if (function.usesTime) {
            composite->setCounterFromTime(s);
            s->setHasTimeDependentFunctions(true);
        }
        if (verbose) {
            std::cerr << "[nfsim/ast] composite function " << function.name << "() = "
                      << function.expression << "\n";
        }
    }

    s->finalizeCompositeFunctions();
    return true;
}

namespace {

struct GraphComponent {
    BNGcore::Node* node = nullptr;
    std::string name;
    std::vector<BNGcore::Node*> bonds;
};

struct GraphMolecule {
    BNGcore::Node* node = nullptr;
    std::string name;
    std::vector<GraphComponent> components;
};

struct ParsedObservablePattern {
    BNGcore::PatternGraph graph;
    std::string compartment;
    std::string relation;
    int quantity = -1;
};

struct ParsedReactionFilter {
    bool include = false;
    bool products = false;
    std::size_t patternIndex = 0;
    std::vector<std::string> patterns;
};

bool isBondNode(const BNGcore::Node& node) {
    return node.get_type().get_type_name() == BNGcore::BOND_NODE_TYPE.get_type_name();
}

bool isComponentNode(const BNGcore::Node& node) {
    if (isBondNode(node)) return false;
    for (auto edge = node.edges_in_begin(); edge != node.edges_in_end(); ++edge) {
        if (!isBondNode(**edge)) return true;
    }
    return false;
}

bool isMoleculeNode(const BNGcore::Node& node) {
    return !isBondNode(node) && !isComponentNode(node);
}

std::vector<GraphMolecule> collectGraphMolecules(const BNGcore::PatternGraph& graph) {
    std::vector<GraphMolecule> result;
    for (auto node = graph.begin(); node != graph.end(); ++node) {
        if (!isMoleculeNode(**node)) continue;

        GraphMolecule molecule;
        molecule.node = *node;
        molecule.name = (*node)->get_type().get_type_name();
        for (auto edge = (*node)->edges_out_begin(); edge != (*node)->edges_out_end(); ++edge) {
            if (!isComponentNode(**edge)) continue;
            GraphComponent component;
            component.node = *edge;
            component.name = (*edge)->get_type().get_type_name();
            for (auto bond = (*edge)->edges_out_begin(); bond != (*edge)->edges_out_end(); ++bond) {
                if (isBondNode(**bond)) component.bonds.push_back(*bond);
            }
            molecule.components.push_back(std::move(component));
        }
        result.push_back(std::move(molecule));
    }
    return result;
}

std::string graphStateToken(const BNGcore::Node& node) {
    const std::string state = node.get_state().get_BNG2_string();
    if (state.empty()) return {};
    return state.front() == '~' ? state.substr(1) : state;
}

std::string graphBondToken(const BNGcore::Node& node) {
    return node.get_state().get_BNG2_string();
}

std::string graphSortState(const GraphComponent& component) {
    const auto state = graphStateToken(*component.node);
    // buildPatternGraph represents an omitted seed state as the graph
    // wildcard `?`; BNG2's source SpeciesGraph represents that same input as
    // an undefined state for quasi-canonical ordering.
    return state == "?" ? std::string() : state;
}

std::size_t graphComponentBondCount(const GraphComponent& component) {
    return static_cast<std::size_t>(std::count_if(
        component.bonds.begin(), component.bonds.end(), [](const auto* bond) {
            return graphBondToken(*bond) != "!-";
        }));
}

bool graphComponentLess(const GraphComponent& left,
                        const GraphComponent& right) {
    if (left.name != right.name) return left.name < right.name;
    const auto leftState = graphSortState(left);
    const auto rightState = graphSortState(right);
    if (leftState != rightState) {
        if (leftState.empty() != rightState.empty()) return leftState.empty();
        return leftState < rightState;
    }
    // BNG2's cmp_component puts components with more edges first after name
    // and state comparisons.
    const auto leftBondCount = graphComponentBondCount(left);
    const auto rightBondCount = graphComponentBondCount(right);
    if (leftBondCount != rightBondCount) {
        return leftBondCount > rightBondCount;
    }
    return false;
}

bool graphMoleculeLess(const GraphMolecule& left,
                       const GraphMolecule& right) {
    if (left.name != right.name) return left.name < right.name;
    if (left.components.size() != right.components.size()) {
        return left.components.size() < right.components.size();
    }

    const auto leftCompartment = left.node->get_compartment();
    const auto rightCompartment = right.node->get_compartment();
    if (leftCompartment.empty() != rightCompartment.empty()) {
        return leftCompartment.empty();
    }
    if (leftCompartment != rightCompartment) return leftCompartment < rightCompartment;

    for (std::size_t index = 0; index < left.components.size(); ++index) {
        if (graphComponentLess(left.components[index], right.components[index])) return true;
        if (graphComponentLess(right.components[index], left.components[index])) return false;
    }
    return false;
}

std::vector<GraphMolecule> canonicalizeSeedGraphMolecules(
    std::vector<GraphMolecule> molecules) {
    for (auto& molecule : molecules) {
        std::stable_sort(molecule.components.begin(), molecule.components.end(),
                         graphComponentLess);
    }
    std::stable_sort(molecules.begin(), molecules.end(), graphMoleculeLess);
    return molecules;
}

bool parseObservablePattern(const std::string& text,
                            const bng::ast::Model& model,
                            ParsedObservablePattern& result,
                            std::string& diagnostic) {
    antlr4::ANTLRInputStream input(text);
    BNGLexer lexer(&input);
    antlr4::CommonTokenStream tokens(&lexer);
    BNGParser parser(&tokens);
    auto* pattern = parser.observable_pattern();
    if (pattern == nullptr || parser.getNumberOfSyntaxErrors() != 0) {
        diagnostic = "could not parse observable pattern '" + text + "'";
        return false;
    }

    auto& mutableModel = const_cast<bng::ast::Model&>(model);
    if (pattern->species_def() != nullptr) {
        result.graph = bng::parser::buildPatternGraph(
            pattern->species_def(), mutableModel, false);
        result.compartment = bng::parser::extractSpeciesCompartment(
            pattern->species_def());
    } else {
        // The legacy observable grammar also accepts a bare molecule type in
        // a stoichiometric comparison, for example `R==2`.  Parse a synthetic
        // empty-site pattern so it enters the same template construction path
        // as `R()` while retaining the relation from the original text.
        if (pattern->STRING() == nullptr || pattern->INT() == nullptr) {
            diagnostic = "invalid stoichiometric observable pattern '" + text + "'";
            return false;
        }
        const std::string moleculeName = pattern->STRING()->getText();
        const bool knownMolecule = std::any_of(
            model.getMoleculeTypes().begin(), model.getMoleculeTypes().end(),
            [&](const auto& moleculeType) {
                return moleculeType.getName() == moleculeName;
            });
        if (!knownMolecule) {
            diagnostic = "stoichiometric observable names unknown molecule type '" +
                         moleculeName + "'";
            return false;
        }

        antlr4::ANTLRInputStream syntheticInput(moleculeName + "()");
        BNGLexer syntheticLexer(&syntheticInput);
        antlr4::CommonTokenStream syntheticTokens(&syntheticLexer);
        BNGParser syntheticParser(&syntheticTokens);
        auto* syntheticSpecies = syntheticParser.species_def();
        if (syntheticSpecies == nullptr ||
            syntheticParser.getNumberOfSyntaxErrors() != 0) {
            diagnostic = "could not construct stoichiometric molecule pattern '" +
                         text + "'";
            return false;
        }
        result.graph = bng::parser::buildPatternGraph(
            syntheticSpecies, mutableModel, false);
        if (pattern->EQUALS() != nullptr) result.relation = "==";
        else if (pattern->GTE() != nullptr) result.relation = ">=";
        else if (pattern->GT() != nullptr) result.relation = ">";
        else if (pattern->LTE() != nullptr) result.relation = "<=";
        else if (pattern->LT() != nullptr) result.relation = "<";
    }
    if (result.graph.empty()) {
        diagnostic = "observable pattern '" + text + "' contains no molecule graph";
        return false;
    }
    if (pattern->GT() != nullptr && pattern->INT() != nullptr) {
        result.relation = pattern->GT()->getText();
    }
    if (!result.relation.empty() && pattern->INT() != nullptr) {
        try {
            result.quantity = std::stoi(pattern->INT()->getText());
        } catch (const std::exception&) {
            diagnostic = "invalid stoichiometric quantity in observable pattern '" + text + "'";
            return false;
        }
    }
    return true;
}

std::string trimText(std::string value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return {};
    const auto last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

std::vector<std::string> splitTopLevelComma(const std::string& text) {
    std::vector<std::string> parts;
    std::size_t start = 0;
    int parentheses = 0;
    int brackets = 0;
    int braces = 0;
    char quote = '\0';
    bool escaped = false;
    for (std::size_t index = 0; index < text.size(); ++index) {
        const char c = text[index];
        if (quote != '\0') {
            if (escaped) {
                escaped = false;
            } else if (c == '\\') {
                escaped = true;
            } else if (c == quote) {
                quote = '\0';
            }
            continue;
        }
        if (c == '\'' || c == '"') {
            quote = c;
            continue;
        }
        if (c == '(') ++parentheses;
        else if (c == ')') --parentheses;
        else if (c == '[') ++brackets;
        else if (c == ']') --brackets;
        else if (c == '{') ++braces;
        else if (c == '}') --braces;
        else if (c == ',' && parentheses == 0 && brackets == 0 && braces == 0) {
            parts.push_back(trimText(text.substr(start, index - start)));
            start = index + 1;
        }
    }
    parts.push_back(trimText(text.substr(start)));
    return parts;
}

bool isReactionFilterModifier(const std::string& modifier) {
    const auto open = modifier.find('(');
    const auto name = lowerCase(trimText(
        modifier.substr(0, open == std::string::npos ? modifier.size() : open)));
    return name == "include_reactants" || name == "exclude_reactants" ||
           name == "include_products" || name == "exclude_products";
}

bool parseReactionFilterModifier(const std::string& modifier,
                                 ParsedReactionFilter& result,
                                 std::string& diagnostic) {
    const auto open = modifier.find('(');
    const auto close = modifier.rfind(')');
    if (open == std::string::npos || close <= open || close != modifier.size() - 1) {
        diagnostic = "malformed reaction filter modifier '" + modifier + "'";
        return false;
    }

    const auto name = lowerCase(trimText(modifier.substr(0, open)));
    if (name != "include_reactants" && name != "exclude_reactants" &&
        name != "include_products" && name != "exclude_products") {
        diagnostic = "unknown reaction filter modifier '" + modifier + "'";
        return false;
    }
    result.include = name.rfind("include_", 0) == 0;
    result.products = name.rfind("include_products", 0) == 0 ||
                      name.rfind("exclude_products", 0) == 0;

    const auto parts = splitTopLevelComma(
        modifier.substr(open + 1, close - open - 1));
    if (parts.size() < 2 || parts.front().empty()) {
        diagnostic = "reaction filter modifier needs a pattern index and pattern: '" +
                     modifier + "'";
        return false;
    }
    try {
        std::size_t consumed = 0;
        const auto rawIndex = std::stoul(parts.front(), &consumed);
        if (consumed != parts.front().size() || rawIndex == 0) {
            diagnostic = "reaction filter index must be a positive integer: '" +
                         modifier + "'";
            return false;
        }
        result.patternIndex = rawIndex - 1;
    } catch (const std::exception&) {
        diagnostic = "reaction filter index must be a positive integer: '" +
                     modifier + "'";
        return false;
    }

    result.patterns.clear();
    for (std::size_t index = 1; index < parts.size(); ++index) {
        if (parts[index].empty()) {
            diagnostic = "reaction filter contains an empty pattern: '" + modifier + "'";
            return false;
        }
        result.patterns.push_back(parts[index]);
    }
    return true;
}

bool parseSpeciesFilterPattern(const std::string& text,
                               const bng::ast::Model& model,
                               bng::ast::SpeciesGraph& result,
                               std::string& diagnostic) {
    antlr4::ANTLRInputStream input(text);
    BNGLexer lexer(&input);
    antlr4::CommonTokenStream tokens(&lexer);
    BNGParser parser(&tokens);
    auto* species = parser.species_def();
    if (species == nullptr || parser.getNumberOfSyntaxErrors() != 0 ||
        tokens.LA(1) != antlr4::Token::EOF) {
        diagnostic = "could not parse reaction filter pattern '" + text + "'";
        return false;
    }

    auto& mutableModel = const_cast<bng::ast::Model&>(model);
    result = bng::ast::SpeciesGraph(
        bng::parser::buildPatternGraph(species, mutableModel, true),
        bng::parser::extractSpeciesCompartment(species));
    result.setCompartmentIsPrefix(bng::parser::isSpeciesCompartmentPrefix(species));
    if (result.getGraph().empty()) {
        diagnostic = "reaction filter pattern '" + text + "' contains no molecule graph";
        return false;
    }
    return true;
}

bool validateProductFiltersFromAst(const bng::ast::ReactionRule& rule,
                                   const bng::ast::Model& model,
                                   bool& passes,
                                   std::string& diagnostic) {
    passes = true;
    const auto& productPatterns = rule.getProductPatterns();
    for (const auto& modifier : rule.getModifiers()) {
        if (!isReactionFilterModifier(modifier)) continue;

        ParsedReactionFilter parsedModifier;
        if (!parseReactionFilterModifier(modifier, parsedModifier, diagnostic)) {
            return false;
        }
        if (!parsedModifier.products) continue;
        if (parsedModifier.patternIndex >= productPatterns.size()) {
            diagnostic = "reaction product filter refers to an unknown product pattern index";
            return false;
        }

        const auto productMolecules = collectGraphMolecules(
            productPatterns[parsedModifier.patternIndex].getGraph());
        for (const auto& patternText : parsedModifier.patterns) {
            bng::ast::SpeciesGraph filterPattern;
            if (!parseSpeciesFilterPattern(patternText, model, filterPattern, diagnostic)) {
                return false;
            }
            const auto filterMolecules = collectGraphMolecules(filterPattern.getGraph());
            if (filterMolecules.size() != 1 || !filterMolecules.front().components.empty()) {
                diagnostic =
                    "direct NFsim product filters support only one bare molecule pattern";
                return false;
            }

            const bool contains = std::any_of(
                productMolecules.begin(), productMolecules.end(),
                [&](const auto& molecule) {
                    return molecule.name == filterMolecules.front().name;
                });
            if ((parsedModifier.include && !contains) ||
                (!parsedModifier.include && contains)) {
                passes = false;
            }
        }
    }
    return true;
}

bool parseSeedAmount(const bng::ast::SeedSpecies& seed,
                     const std::map<std::string, double>& parameters,
                     int& count,
                     std::string& diagnostic) {
    try {
        const double amount = seed.getAmount().evaluate(
            [&](const std::string& name) -> double {
                if (name == "_PI") return 3.14159265358979323846;
                if (name == "_e") return 2.71828182845904523536;
                if (name == "_Na") return 6.02214076e23;
                const auto iter = parameters.find(name);
                if (iter == parameters.end()) {
                    throw std::runtime_error("unknown seed amount symbol '" + name + "'");
                }
                return iter->second;
            },
            0.0);
        if (!std::isfinite(amount) || amount < 0.0 ||
            amount > static_cast<double>(std::numeric_limits<int>::max())) {
            diagnostic = "seed amount is outside NFsim's nonnegative integer range";
            return false;
        }
        count = static_cast<int>(amount);
        return true;
    } catch (const std::exception& error) {
        diagnostic = error.what();
        return false;
    }
}

bool getEquivalentNames(MoleculeType* moleculeType,
                        const std::string& genericName,
                        std::vector<std::string>& names) {
    if (!moleculeType->isEquivalentComponent(genericName)) return false;
    int* indices = nullptr;
    int count = 0;
    moleculeType->getEquivalencyClass(indices, count, genericName);
    if (indices == nullptr || count <= 0) return false;
    names.reserve(static_cast<std::size_t>(count));
    for (int index = 0; index < count; ++index) {
        names.push_back(moleculeType->getComponentName(indices[index]));
    }
    return true;
}

using RuntimeNames = std::vector<std::vector<std::string>>;

bool makeRuntimeNameAssignments(const std::vector<GraphMolecule>& molecules,
                                System* system,
                                bool expandSymmetry,
                                std::vector<RuntimeNames>& assignments,
                                std::string& diagnostic) {
    RuntimeNames initial;
    initial.reserve(molecules.size());
    for (const auto& molecule : molecules) {
        auto* moleculeType = system->getMoleculeTypeByName(molecule.name);
        if (moleculeType == nullptr) {
            diagnostic = "unknown molecule type '" + molecule.name + "'";
            return false;
        }
        std::vector<std::string> names;
        names.reserve(molecule.components.size());
        for (const auto& component : molecule.components) names.push_back(component.name);
        initial.push_back(std::move(names));
    }
    assignments.push_back(std::move(initial));
    if (!expandSymmetry) return true;

    for (std::size_t moleculeIndex = 0; moleculeIndex < molecules.size(); ++moleculeIndex) {
        auto* moleculeType = system->getMoleculeTypeByName(molecules[moleculeIndex].name);
        std::map<std::string, std::vector<std::size_t>> occurrences;
        for (std::size_t componentIndex = 0;
             componentIndex < molecules[moleculeIndex].components.size(); ++componentIndex) {
            const auto& component = molecules[moleculeIndex].components[componentIndex];
            if (moleculeType->isEquivalentComponent(component.name)) {
                occurrences[component.name].push_back(componentIndex);
            }
        }

        for (const auto& occurrence : occurrences) {
            const auto& genericName = occurrence.first;
            const auto& componentIndices = occurrence.second;
            std::vector<std::string> equivalentNames;
            if (!getEquivalentNames(moleculeType, genericName, equivalentNames) ||
                componentIndices.size() > equivalentNames.size()) {
                diagnostic = "too many symmetric components named '" + genericName +
                             "' in molecule type '" + molecules[moleculeIndex].name + "'";
                return false;
            }

            std::vector<std::vector<std::string>> choices;
            std::vector<std::string> choice(componentIndices.size());
            std::vector<bool> used(equivalentNames.size(), false);
            std::function<void(std::size_t)> enumerate = [&](std::size_t position) {
                if (position == componentIndices.size()) {
                    choices.push_back(choice);
                    return;
                }
                for (std::size_t nameIndex = 0; nameIndex < equivalentNames.size(); ++nameIndex) {
                    if (used[nameIndex]) continue;
                    used[nameIndex] = true;
                    choice[position] = equivalentNames[nameIndex];
                    enumerate(position + 1);
                    used[nameIndex] = false;
                }
            };
            enumerate(0);

            std::vector<RuntimeNames> next;
            for (const auto& base : assignments) {
                for (const auto& choiceNames : choices) {
                    RuntimeNames variant = base;
                    for (std::size_t position = 0; position < componentIndices.size(); ++position) {
                        variant[moleculeIndex][componentIndices[position]] = choiceNames[position];
                    }
                    next.push_back(std::move(variant));
                }
            }
            assignments = std::move(next);
        }
    }
    return true;
}

bool resolveCompartment(System* system, const std::string& name,
                        Compartment*& compartment, std::string& diagnostic) {
    compartment = nullptr;
    if (name.empty()) return true;
    compartment = system->getCompartment(name);
    if (compartment == nullptr) {
        diagnostic = "unknown compartment '" + name + "'";
        return false;
    }
    return true;
}

int componentStateValue(MoleculeType* moleculeType, const std::string& componentName,
                        const std::string& state, std::string& diagnostic) {
    if (state.empty() || state == "?" || state == "*") return -1;
    try {
        const int componentIndex = moleculeType->getCompIndexFromName(componentName);
        return moleculeType->getStateValueFromName(componentIndex, state);
    } catch (const std::exception& error) {
        diagnostic = error.what();
        return -2;
    }
}

bool buildTemplatePatterns(const BNGcore::PatternGraph& graph,
                           const std::string& patternCompartment,
                           System* system,
                           bool expandSymmetry,
                           std::vector<std::vector<TemplateMolecule*>>& builds,
                           bool& hasDisjointSets,
                           int& suggestedTraversalLimit,
                           std::string& diagnostic,
                           std::vector<RuntimeNames>* runtimeAssignments = nullptr,
                           const std::set<std::pair<std::size_t, std::size_t>>*
                               concreteSymmetricComponents = nullptr) {
    const auto molecules = collectGraphMolecules(graph);
    if (molecules.empty()) {
        diagnostic = "pattern contains no molecule nodes";
        return false;
    }

    if (runtimeAssignments != nullptr) runtimeAssignments->clear();

    std::vector<RuntimeNames> assignments;
    if (!makeRuntimeNameAssignments(molecules, system, expandSymmetry, assignments, diagnostic)) {
        return false;
    }

    for (const auto& runtimeNames : assignments) {
        std::vector<TemplateMolecule*> templates;
        templates.reserve(molecules.size());
        for (std::size_t moleculeIndex = 0; moleculeIndex < molecules.size(); ++moleculeIndex) {
            const auto& molecule = molecules[moleculeIndex];
            auto* moleculeType = system->getMoleculeTypeByName(molecule.name);
            if (moleculeType == nullptr) {
                diagnostic = "unknown molecule type '" + molecule.name + "'";
                return false;
            }
            auto* templateMolecule = new TemplateMolecule(moleculeType);
            const std::string compartmentName = molecule.node->get_compartment().empty()
                                                    ? patternCompartment
                                                    : molecule.node->get_compartment();
            Compartment* compartment = nullptr;
            if (!resolveCompartment(system, compartmentName, compartment, diagnostic)) return false;
            templateMolecule->setCompartment(compartment);
            templates.push_back(templateMolecule);
        }

        for (std::size_t moleculeIndex = 0; moleculeIndex < molecules.size(); ++moleculeIndex) {
            const auto& molecule = molecules[moleculeIndex];
            auto* moleculeType = system->getMoleculeTypeByName(molecule.name);
            auto* templateMolecule = templates[moleculeIndex];
            for (std::size_t componentIndex = 0;
                 componentIndex < molecule.components.size(); ++componentIndex) {
                const auto& component = molecule.components[componentIndex];
                const std::string runtimeName = runtimeNames[moleculeIndex][componentIndex];
                const std::string state = graphStateToken(*component.node);
                const bool symmetric = moleculeType->isEquivalentComponent(component.name);
                const bool concreteSymmetric =
                    symmetric && expandSymmetry &&
                    (concreteSymmetricComponents == nullptr ||
                     concreteSymmetricComponents->count(
                         {moleculeIndex, componentIndex}) != 0);
                std::string stateLookupName = runtimeName;
                if (symmetric && !concreteSymmetric) {
                    std::vector<std::string> equivalentNames;
                    if (!getEquivalentNames(moleculeType, component.name, equivalentNames)) {
                        diagnostic = "could not resolve symmetric component '" + component.name + "'";
                        return false;
                    }
                    stateLookupName = equivalentNames.front();
                }
                const int stateValue = componentStateValue(
                    moleculeType, stateLookupName, state, diagnostic);
                if (stateValue == -2) return false;

                std::string bondState;
                std::size_t bondEndpointCount = 0;
                if (!component.bonds.empty()) {
                    if (component.bonds.size() != 1) {
                        diagnostic = "component '" + component.name +
                                     "' has multiple bond constraints";
                        return false;
                    }
                    bondState = graphBondToken(*component.bonds.front());
                    for (auto edge = component.bonds.front()->edges_in_begin();
                         edge != component.bonds.front()->edges_in_end(); ++edge) {
                        if (isComponentNode(**edge)) ++bondEndpointCount;
                    }
                    if (bondEndpointCount > 2) {
                        diagnostic = "bond constraint has more than two endpoints";
                        return false;
                    }
                }

                if (symmetric && !concreteSymmetric) {
                    int bondConstraint = TemplateMolecule::NO_CONSTRAINT;
                    if (bondState == "!-") bondConstraint = TemplateMolecule::EMPTY;
                    else if (bondState == "!+") bondConstraint = TemplateMolecule::OCCUPIED;
                    else if (bondState.empty()) bondConstraint = TemplateMolecule::EMPTY;
                    templateMolecule->addSymCompConstraint(
                        component.name,
                        "m" + std::to_string(moleculeIndex) + "c" +
                            std::to_string(componentIndex),
                        bondConstraint,
                        stateValue < 0 ? TemplateMolecule::NO_CONSTRAINT : stateValue);
                } else {
                    if (stateValue >= 0) {
                        templateMolecule->addComponentConstraint(runtimeName, stateValue);
                    }
                    if (bondState == "!-") {
                        templateMolecule->addEmptyComponent(runtimeName);
                    } else if (bondState == "!+" && bondEndpointCount == 1) {
                        templateMolecule->addBoundComponent(runtimeName);
                    } else if (bondState.empty()) {
                        // A component written in a pattern without a bond
                        // token is explicitly required to be free.  The AST
                        // keeps `A()` (wildcard) distinct from `A(b)` (free
                        // site), so preserve that distinction here.
                        templateMolecule->addEmptyComponent(runtimeName);
                    } else if (!bondState.empty() && bondState != "!?" && bondState != "!+" ) {
                        diagnostic = "unsupported bond state '" + bondState + "'";
                        return false;
                    }
                }
            }
        }

        std::unordered_set<BNGcore::Node*> processedBonds;
        for (std::size_t moleculeIndex = 0; moleculeIndex < molecules.size(); ++moleculeIndex) {
            const auto& molecule = molecules[moleculeIndex];
            for (std::size_t componentIndex = 0;
                 componentIndex < molecule.components.size(); ++componentIndex) {
                const auto& component = molecule.components[componentIndex];
                for (auto* bond : component.bonds) {
                    if (!processedBonds.insert(bond).second) continue;
                    if (graphBondToken(*bond) != "!+") continue;

                    std::vector<std::pair<std::size_t, std::size_t>> endpoints;
                    for (std::size_t otherMolecule = 0; otherMolecule < molecules.size(); ++otherMolecule) {
                        for (std::size_t otherComponent = 0;
                             otherComponent < molecules[otherMolecule].components.size(); ++otherComponent) {
                            const auto& other = molecules[otherMolecule].components[otherComponent];
                            if (std::find(other.bonds.begin(), other.bonds.end(), bond) != other.bonds.end()) {
                                endpoints.emplace_back(otherMolecule, otherComponent);
                            }
                        }
                    }
                    // `!+` on one component is an occupancy constraint, not
                    // an explicit bond edge.  The component-constraint pass
                    // above already installed it; there is nothing to bind
                    // here.  Explicit bond IDs still require two endpoints.
                    if (endpoints.size() == 1) continue;
                    if (endpoints.size() != 2) {
                        diagnostic = "a bound bond must connect exactly two component sites";
                        return false;
                    }

                    const auto [firstMolecule, firstComponent] = endpoints[0];
                    const auto [secondMolecule, secondComponent] = endpoints[1];
                    const auto firstName = runtimeNames[firstMolecule][firstComponent];
                    const auto secondName = runtimeNames[secondMolecule][secondComponent];
                    const auto firstRaw = molecules[firstMolecule].components[firstComponent].name;
                    const auto secondRaw = molecules[secondMolecule].components[secondComponent].name;
                    const auto firstMoleculeType =
                        templates[firstMolecule]->getMoleculeType();
                    const auto secondMoleculeType =
                        templates[secondMolecule]->getMoleculeType();
                    const bool firstConcreteSymmetric =
                        firstMoleculeType->isEquivalentComponent(firstRaw) &&
                        expandSymmetry &&
                        (concreteSymmetricComponents == nullptr ||
                         concreteSymmetricComponents->count(
                             {firstMolecule, firstComponent}) != 0);
                    const bool secondConcreteSymmetric =
                        secondMoleculeType->isEquivalentComponent(secondRaw) &&
                        expandSymmetry &&
                        (concreteSymmetricComponents == nullptr ||
                         concreteSymmetricComponents->count(
                             {secondMolecule, secondComponent}) != 0);
                    const auto firstId = "m" + std::to_string(firstMolecule) + "c" +
                                         std::to_string(firstComponent);
                    const auto secondId = "m" + std::to_string(secondMolecule) + "c" +
                                          std::to_string(secondComponent);
                    TemplateMolecule::bind(
                        templates[firstMolecule],
                        firstConcreteSymmetric ? firstName : firstRaw,
                        firstId,
                        templates[secondMolecule],
                        secondConcreteSymmetric ? secondName : secondRaw,
                        secondId);
                }
            }
        }

        std::vector<std::vector<TemplateMolecule*>> sets;
        std::vector<int> uniqueSetId;
        const int setCount = TemplateMolecule::getNumDisjointSets(templates, sets, uniqueSetId);
        if (setCount > 1) {
            hasDisjointSets = true;
            system->setUsingComplex(true);
            for (int set = 0; set < setCount - 1; ++set) {
                auto first = std::find(uniqueSetId.begin(), uniqueSetId.end(), set);
                auto second = std::find(uniqueSetId.begin(), uniqueSetId.end(), set + 1);
                if (first == uniqueSetId.end() || second == uniqueSetId.end()) {
                    diagnostic = "could not connect disjoint template sets";
                    return false;
                }
                const int firstIndex = static_cast<int>(std::distance(uniqueSetId.begin(), first));
                const int secondIndex = static_cast<int>(std::distance(uniqueSetId.begin(), second));
                const int firstConnection = templates[firstIndex]->getN_connectedTo();
                const int secondConnection = templates[secondIndex]->getN_connectedTo();
                templates[firstIndex]->addConnectedTo(templates[secondIndex], secondConnection);
                templates[secondIndex]->addConnectedTo(templates[firstIndex], firstConnection);
            }
        }

        suggestedTraversalLimit = std::max(
            suggestedTraversalLimit, static_cast<int>(templates.size()) + 1);
        builds.push_back(std::move(templates));
        if (runtimeAssignments != nullptr) runtimeAssignments->push_back(runtimeNames);
    }
    return !builds.empty();
}

bool hasReactionModifier(const bng::ast::ReactionRule& rule, const std::string& wanted) {
    const std::string needle = lowerCase(wanted);
    for (const auto& modifier : rule.getModifiers()) {
        if (lowerCase(modifier) == needle) return true;
    }
    return false;
}

bool hasReactionModifierPrefix(const bng::ast::ReactionRule& rule,
                               const std::string& prefix) {
    const std::string needle = lowerCase(prefix);
    for (const auto& modifier : rule.getModifiers()) {
        if (lowerCase(modifier).rfind(needle, 0) == 0) return true;
    }
    return false;
}

std::vector<std::string> reverseReactionFilterModifiers(
    const std::vector<std::string>& modifiers) {
    std::vector<std::string> reversed;
    reversed.reserve(modifiers.size());
    for (const auto& modifier : modifiers) {
        std::string transformed = modifier;
        const auto normalized = lowerCase(transformed);
        const auto replacePrefix = [&](const std::string& from,
                                       const std::string& to) {
            if (normalized.rfind(from, 0) == 0) {
                transformed.replace(0, from.size(), to);
                return true;
            }
            return false;
        };
        if (!replacePrefix("exclude_reactants", "exclude_products") &&
            !replacePrefix("include_reactants", "include_products") &&
            !replacePrefix("exclude_products", "exclude_reactants")) {
            replacePrefix("include_products", "include_reactants");
        }
        reversed.push_back(std::move(transformed));
    }
    return reversed;
}

bool hasUnsupportedReactionFilterModifier(const bng::ast::ReactionRule& rule) {
    for (const auto& modifier : rule.getModifiers()) {
        const auto open = modifier.find('(');
        const auto name = lowerCase(trimText(
            modifier.substr(0, open == std::string::npos ? modifier.size() : open)));
        if ((name.rfind("include_", 0) == 0 || name.rfind("exclude_", 0) == 0) &&
            name != "include_reactants" && name != "exclude_reactants" &&
            name != "include_products" && name != "exclude_products") {
            return true;
        }
    }
    return false;
}

bool addReactantFiltersFromAst(
    const bng::ast::ReactionRule& rule,
    const bng::ast::Model& model,
    System* system,
    TransformationSet* transformationSet,
    const std::vector<TemplateMolecule*>& reactantRoots,
    bool& hasDisjointSets,
    int& suggestedTraversalLimit,
    std::string& diagnostic) {
    std::size_t filterOrdinal = 0;
    for (const auto& modifier : rule.getModifiers()) {
        if (!isReactionFilterModifier(modifier)) continue;

        ParsedReactionFilter parsedModifier;
        if (!parseReactionFilterModifier(modifier, parsedModifier, diagnostic)) {
            return false;
        }
        if (parsedModifier.products) continue;
        if (parsedModifier.patternIndex >= reactantRoots.size()) {
            diagnostic = "reaction filter refers to an unknown reactant pattern index";
            return false;
        }

        for (const auto& patternText : parsedModifier.patterns) {
            bng::ast::SpeciesGraph filterPattern;
            if (!parseSpeciesFilterPattern(patternText, model, filterPattern, diagnostic)) {
                return false;
            }

            std::vector<std::vector<TemplateMolecule*>> builds;
            bool filterHasDisjointSets = false;
            if (!buildTemplatePatterns(
                    filterPattern.getGraph(), filterPattern.getCompartment(), system, false,
                    builds, filterHasDisjointSets, suggestedTraversalLimit, diagnostic) ||
                builds.size() != 1 || builds.front().empty()) {
                for (auto& build : builds) {
                    for (auto* templateMolecule : build) delete templateMolecule;
                }
                diagnostic = diagnostic.empty()
                                 ? "reaction filter pattern requires unsupported symmetry expansion"
                                 : diagnostic;
                return false;
            }

            std::map<std::string, TemplateMolecule*> parsedTemplates;
            for (std::size_t index = 0; index < builds.front().size(); ++index) {
                parsedTemplates.emplace(
                    "filter_" + std::to_string(filterOrdinal) + "_M" +
                        std::to_string(index + 1),
                    builds.front()[index]);
            }
            auto* root = builds.front().front();
            if (parsedModifier.include) {
                transformationSet->addIncludeReactant(
                    static_cast<int>(parsedModifier.patternIndex), root, parsedTemplates);
            } else {
                transformationSet->addExcludeReactant(
                    static_cast<int>(parsedModifier.patternIndex), root, parsedTemplates);
            }
            hasDisjointSets = hasDisjointSets || filterHasDisjointSets;
            ++filterOrdinal;
        }
    }
    return true;
}

bool componentNameForReactionRef(const bng::ast::ReactionRule& rule,
                                  const bng::ast::ReactionRule::ComponentRef& ref,
                                  std::string& name,
                                  std::string& diagnostic) {
    const auto& patterns = rule.getReactantPatterns();
    if (ref.patternIndex >= patterns.size()) {
        diagnostic = "operation refers to an unknown reactant pattern";
        return false;
    }
    const auto molecules = collectGraphMolecules(patterns[ref.patternIndex].getGraph());
    if (ref.moleculeIndex >= molecules.size() ||
        ref.componentIndex >= molecules[ref.moleculeIndex].components.size()) {
        diagnostic = "operation refers to an unknown reactant component";
        return false;
    }
    name = molecules[ref.moleculeIndex].components[ref.componentIndex].name;
    return true;
}

bool templateForReactionRef(
    const bng::ast::ReactionRule::ComponentRef& ref,
    const std::vector<std::vector<TemplateMolecule*>>& patternTemplates,
    TemplateMolecule*& result,
    std::string& diagnostic) {
    if (ref.patternIndex >= patternTemplates.size() ||
        ref.moleculeIndex >= patternTemplates[ref.patternIndex].size()) {
        diagnostic = "operation refers to an unknown reactant template";
        return false;
    }
    result = patternTemplates[ref.patternIndex][ref.moleculeIndex];
    return result != nullptr;
}

bool evaluateStaticExpression(const bng::ast::Expression& expression,
                              const std::map<std::string, double>& parameters,
                              double& value,
                              std::string& diagnostic) {
    if (expressionUsesTime(expression)) {
        diagnostic = "expression depends on simulation time";
        return false;
    }
    try {
        value = expression.evaluate([&](const std::string& name) -> double {
            if (name == "_PI" || name == "_pi") return 3.14159265358979323846;
            if (name == "_e") return 2.71828182845904523536;
            if (name == "_Na") return 6.02214076e23;
            const auto iter = parameters.find(name);
            if (iter == parameters.end()) {
                throw std::runtime_error("unknown static-expression symbol '" + name + "'");
            }
            return iter->second;
        }, 0.0);
        if (!std::isfinite(value)) {
            diagnostic = "expression is not finite";
            return false;
        }
        return true;
    } catch (const std::exception& error) {
        diagnostic = error.what();
        return false;
    }
}

bool evaluateStaticReactionRate(const bng::ast::Expression& expression,
                                const std::map<std::string, double>& parameters,
                                double& value,
                                std::string& diagnostic) {
    if (!evaluateStaticExpression(expression, parameters, value, diagnostic)) return false;
    if (value < 0.0) {
        diagnostic = "reaction rate is not a finite nonnegative value";
        return false;
    }
    return true;
}

// Defined below the symmetry helpers.  Symmetric reaction-center expansion
// uses the same generated live function objects as the ordinary direct path;
// keeping this boundary explicit prevents it from inventing a second rate
// evaluator.
bool addDynamicReactionRateFunction(
    const bng::ast::Expression& expression,
    const bng::ast::Model& model,
    const std::map<std::string, double>& parameters,
    System* system,
    const std::filesystem::path& sourcePath,
    std::size_t ordinal,
    GlobalFunction*& global,
    CompositeFunction*& composite,
    std::vector<std::string>& localFunctionArgumentNames,
    std::string& diagnostic);

enum class SymmetricReactionExpansionResult {
    NotApplicable,
    Added,
    Error,
};

struct ExpandedReactantPattern {
    std::vector<std::vector<TemplateMolecule*>> builds;
    std::vector<RuntimeNames> assignments;
};

bool buildExpandedReactantPatterns(
    const bng::ast::ReactionRule& rule,
    System* system,
    const std::set<bng::ast::ReactionRule::ComponentRef>& reactionCenter,
    int& suggestedTraversalLimit,
    std::vector<ExpandedReactantPattern>& expandedPatterns,
    bool& hasDisjointSets,
    std::string& diagnostic) {
    expandedPatterns.clear();
    expandedPatterns.reserve(rule.getReactantPatterns().size());
    hasDisjointSets = false;
    for (std::size_t patternIndex = 0;
         patternIndex < rule.getReactantPatterns().size(); ++patternIndex) {
        const auto& pattern = rule.getReactantPatterns()[patternIndex];
        ExpandedReactantPattern expanded;
        std::set<std::pair<std::size_t, std::size_t>> localReactionCenter;
        for (const auto& ref : reactionCenter) {
            if (ref.patternIndex == patternIndex) {
                localReactionCenter.emplace(ref.moleculeIndex, ref.componentIndex);
            }
        }
        if (!buildTemplatePatterns(
                pattern.getGraph(), pattern.getCompartment(), system, true,
                expanded.builds, hasDisjointSets, suggestedTraversalLimit,
                diagnostic, &expanded.assignments, &localReactionCenter) ||
            expanded.builds.empty() ||
            expanded.builds.size() != expanded.assignments.size()) {
            if (diagnostic.empty()) diagnostic = "invalid symmetric reactant pattern";
            return false;
        }

        // The legacy XML loader expands only symmetric components at the
        // reaction center.  Context-only symmetric components still constrain
        // matching, but expanding their interchangeable names would create
        // duplicate reaction classes (for example L(r,r,r) contributes three
        // choices for one reactive r, not all 3! label permutations).
        std::set<std::vector<std::string>> seenKeys;
        std::vector<std::vector<TemplateMolecule*>> uniqueBuilds;
        std::vector<RuntimeNames> uniqueAssignments;
        uniqueBuilds.reserve(expanded.builds.size());
        uniqueAssignments.reserve(expanded.assignments.size());
        for (std::size_t buildIndex = 0;
             buildIndex < expanded.builds.size(); ++buildIndex) {
            std::vector<std::string> key;
            for (const auto& ref : reactionCenter) {
                if (ref.patternIndex != patternIndex ||
                    ref.moleculeIndex >= expanded.assignments[buildIndex].size() ||
                    ref.componentIndex >=
                        expanded.assignments[buildIndex][ref.moleculeIndex].size()) {
                    continue;
                }
                key.push_back(expanded.assignments[buildIndex][ref.moleculeIndex]
                                  [ref.componentIndex]);
            }
            if (!seenKeys.insert(key).second) {
                // TemplateMolecule instances register themselves with their
                // MoleculeType, which owns their lifetime.  Do not delete a
                // duplicate build here: it is intentionally omitted from the
                // reaction, but must remain registered for System teardown.
                continue;
            }
            uniqueBuilds.push_back(std::move(expanded.builds[buildIndex]));
            uniqueAssignments.push_back(std::move(expanded.assignments[buildIndex]));
        }
        expanded.builds = std::move(uniqueBuilds);
        expanded.assignments = std::move(uniqueAssignments);
        expandedPatterns.push_back(std::move(expanded));
    }
    return !expandedPatterns.empty();
}

bool collectSymmetricReactantComponents(
    const bng::ast::ReactionRule& rule,
    System* system,
    std::set<bng::ast::ReactionRule::ComponentRef>& symmetricComponents,
    std::string& diagnostic) {
    symmetricComponents.clear();
    for (std::size_t patternIndex = 0;
         patternIndex < rule.getReactantPatterns().size();
         ++patternIndex) {
        const auto molecules = collectGraphMolecules(
            rule.getReactantPatterns()[patternIndex].getGraph());
        for (std::size_t moleculeIndex = 0;
             moleculeIndex < molecules.size(); ++moleculeIndex) {
            auto* moleculeType = system->getMoleculeTypeByName(molecules[moleculeIndex].name);
            if (moleculeType == nullptr) {
                diagnostic = "unknown molecule type '" + molecules[moleculeIndex].name + "'";
                return false;
            }
            for (std::size_t componentIndex = 0;
                 componentIndex < molecules[moleculeIndex].components.size();
                 ++componentIndex) {
                if (moleculeType->isEquivalentComponent(
                        molecules[moleculeIndex].components[componentIndex].name)) {
                    symmetricComponents.insert(
                        bng::ast::ReactionRule::ComponentRef{
                            patternIndex, moleculeIndex, componentIndex});
                }
            }
        }
    }
    return true;
}

bool hasOnlySymmetricPermutationModifiers(const bng::ast::ReactionRule& rule) {
    for (const auto& modifier : rule.getModifiers()) {
        const auto normalized = lowerCase(trimText(modifier));
        if (normalized != "totalrate" && normalized != "matchonce") return false;
    }
    return true;
}

SymmetricReactionExpansionResult addSymmetricStateChangeReactionRulesFromAst(
    const bng::ast::ReactionRule& rule,
    const bng::ast::Model& model,
    System* system,
    const std::map<std::string, double>& parameters,
    bool blockSameComplexBinding,
    bool verbose,
    int& suggestedTraversalLimit,
    const std::filesystem::path& sourcePath,
    std::size_t rateOrdinal,
    std::string& diagnostic) {
    const auto& operations = rule.getOperations();
    if (operations.empty() ||
        std::any_of(
            operations.begin(), operations.end(), [](const auto& operation) {
                return operation.type !=
                       bng::ast::ReactionRule::TransformOp::Type::ChangeState;
            }) ||
        rule.getRates().size() != 1 || rule.getReactantPatterns().empty() ||
        rule.getProductPatterns().empty() || !hasOnlySymmetricPermutationModifiers(rule)) {
        return SymmetricReactionExpansionResult::NotApplicable;
    }

    double rateValue = 0.0;
    std::string rateDiagnostic;
    const bool staticRate = evaluateStaticReactionRate(
        rule.getRates().front(), parameters, rateValue, rateDiagnostic);
    if (!staticRate && evaluateStaticExpression(
                           rule.getRates().front(), parameters, rateValue, rateDiagnostic)) {
        // Preserve the ordinary direct-path rejection for a statically invalid
        // (for example negative) rate instead of treating it as dynamic.
        return SymmetricReactionExpansionResult::NotApplicable;
    }

    std::set<bng::ast::ReactionRule::ComponentRef> symmetricComponents;
    if (!collectSymmetricReactantComponents(
            rule, system, symmetricComponents, diagnostic)) {
        return SymmetricReactionExpansionResult::Error;
    }

    if (symmetricComponents.empty()) {
        return SymmetricReactionExpansionResult::NotApplicable;
    }

    std::set<bng::ast::ReactionRule::ComponentRef> reactionCenter;
    for (const auto& operation : operations) {
        if (!reactionCenter.insert(operation.source).second) {
            // Two operations on the same component need an explicit sequential
            // semantics that the permutation slice does not define.
            return SymmetricReactionExpansionResult::NotApplicable;
        }
    }
    const bool hasSymmetricReactionCenter = std::any_of(
        symmetricComponents.begin(), symmetricComponents.end(),
        [&](const auto& component) { return reactionCenter.count(component) != 0; });
    if (!hasSymmetricReactionCenter) {
        // Context-only symmetry has no reaction-center site to select.  Keep
        // that case on the generic compatibility path until its full matching
        // semantics are represented.
        return SymmetricReactionExpansionResult::NotApplicable;
    }

    GlobalFunction* dynamicGlobal = nullptr;
    CompositeFunction* dynamicComposite = nullptr;
    std::vector<std::string> dynamicLocalFunctionArguments;
    if (!staticRate && !addDynamicReactionRateFunction(
                           rule.getRates().front(), model, parameters, system, sourcePath,
                           rateOrdinal, dynamicGlobal, dynamicComposite,
                           dynamicLocalFunctionArguments, rateDiagnostic)) {
        return SymmetricReactionExpansionResult::NotApplicable;
    }
    if (!dynamicLocalFunctionArguments.empty()) {
        return SymmetricReactionExpansionResult::NotApplicable;
    }

    std::vector<ExpandedReactantPattern> expandedPatterns;
    bool hasDisjointSets = false;
    if (!buildExpandedReactantPatterns(
            rule, system, reactionCenter, suggestedTraversalLimit, expandedPatterns,
            hasDisjointSets, diagnostic)) {
        return SymmetricReactionExpansionResult::Error;
    }

    std::vector<std::size_t> selectedBuild(expandedPatterns.size(), 0);
    std::size_t reactionOrdinal = 0;
    std::function<bool(std::size_t)> addExpandedCombination =
        [&](std::size_t patternIndex) {
            if (patternIndex < expandedPatterns.size()) {
                for (std::size_t buildIndex = 0;
                     buildIndex < expandedPatterns[patternIndex].builds.size();
                     ++buildIndex) {
                    selectedBuild[patternIndex] = buildIndex;
                    if (!addExpandedCombination(patternIndex + 1)) return false;
                }
                return true;
            }

            std::vector<TemplateMolecule*> roots;
            roots.reserve(expandedPatterns.size());
            for (std::size_t index = 0; index < expandedPatterns.size(); ++index) {
                const auto& build =
                    expandedPatterns[index].builds[selectedBuild[index]];
                if (build.empty()) {
                    diagnostic = "symmetric reactant pattern produced no template";
                    return false;
                }
                roots.push_back(build.front());
            }

            auto* transformationSet = new TransformationSet(roots);
            transformationSet->setComplexBookkeeping(
                blockSameComplexBinding || hasDisjointSets);
            transformationSet->setNumProductPatterns(
                static_cast<unsigned int>(rule.getProductPatterns().size()));

            bool applied = false;
            for (const auto& stateChange : operations) {
                if (stateChange.source.patternIndex >= expandedPatterns.size()) {
                    diagnostic = "state-change source is outside the expanded reactant pattern";
                    applied = false;
                    break;
                }
                const auto& sourcePattern =
                    expandedPatterns[stateChange.source.patternIndex];
                const auto& sourceAssignment =
                    sourcePattern.assignments[selectedBuild[stateChange.source.patternIndex]];
                if (stateChange.source.moleculeIndex >= sourceAssignment.size() ||
                    stateChange.source.componentIndex >=
                        sourceAssignment[stateChange.source.moleculeIndex].size() ||
                    stateChange.source.moleculeIndex >=
                        sourcePattern.builds[selectedBuild[stateChange.source.patternIndex]]
                            .size()) {
                    diagnostic = "state-change target is outside the expanded reactant pattern";
                    applied = false;
                    break;
                }
                const std::string& runtimeComponentName =
                    sourceAssignment[stateChange.source.moleculeIndex]
                        [stateChange.source.componentIndex];
                auto* target = sourcePattern.builds[
                    selectedBuild[stateChange.source.patternIndex]][
                    stateChange.source.moleculeIndex];
                try {
                    if (stateChange.newState == "PLUS") {
                        applied = transformationSet->addIncrementStateTransform(
                            target, runtimeComponentName);
                    } else if (stateChange.newState == "MINUS") {
                        applied = transformationSet->addDecrementStateTransform(
                            target, runtimeComponentName);
                    } else {
                        applied = transformationSet->addStateChangeTransform(
                            target, runtimeComponentName, stateChange.newState);
                    }
                } catch (const std::exception& error) {
                    diagnostic = error.what();
                    applied = false;
                }
                if (!applied) break;
            }
            if (!applied) {
                if (diagnostic.empty()) diagnostic = "could not add symmetric state-change transformation";
                delete transformationSet;
                return false;
            }
            transformationSet->finalize();

            const auto reactionName =
                rule.getRuleName() + "_sym" + std::to_string(reactionOrdinal + 1);
            ReactionClass* reaction = nullptr;
            if (dynamicGlobal != nullptr) {
                reaction = new FunctionalRxnClass(
                    reactionName, dynamicGlobal, transformationSet, system);
            } else if (dynamicComposite != nullptr) {
                reaction = new FunctionalRxnClass(
                    reactionName, dynamicComposite, transformationSet, system);
            } else {
                std::string rateParameterName;
                if (rule.getRates().front().kind() == bng::ast::ExpressionKind::Identifier &&
                    parameters.count(rule.getRates().front().name()) != 0) {
                    rateParameterName = rule.getRates().front().name();
                }
                reaction = new BasicRxnClass(
                    reactionName, rateValue, rateParameterName, transformationSet, system);
            }
            reaction->setTotalRateFlag(hasReactionModifier(rule, "totalrate"));
            if (hasReactionModifier(rule, "matchonce")) {
                for (std::size_t index = 0; index < expandedPatterns.size(); ++index) {
                    reaction->setMatchOnce(static_cast<unsigned int>(index), true);
                }
            }
            ++reactionOrdinal;
            if (dynamicGlobal != nullptr || dynamicComposite != nullptr || rateValue > 0.0) {
                system->addReaction(reaction);
                if (verbose) {
                    std::cerr << "[nfsim/ast] reaction " << rule.getRuleName()
                              << " (direct symmetric permutation)\n";
                }
            } else {
                delete reaction;
            }
            return true;
        };

    if (!addExpandedCombination(0)) {
        return SymmetricReactionExpansionResult::Error;
    }
    return SymmetricReactionExpansionResult::Added;
}

SymmetricReactionExpansionResult addSymmetricBondReactionRulesFromAst(
    const bng::ast::ReactionRule& rule,
    const bng::ast::Model& model,
    System* system,
    const std::map<std::string, double>& parameters,
    bool blockSameComplexBinding,
    bool verbose,
    int& suggestedTraversalLimit,
    const std::filesystem::path& sourcePath,
    std::size_t rateOrdinal,
    std::string& diagnostic) {
    const auto& operations = rule.getOperations();
    if (operations.size() != 1 ||
        (operations.front().type !=
             bng::ast::ReactionRule::TransformOp::Type::AddBond &&
         operations.front().type !=
             bng::ast::ReactionRule::TransformOp::Type::DeleteBond) ||
        rule.getRates().size() != 1 || rule.getReactantPatterns().empty() ||
        rule.getProductPatterns().empty() || !hasOnlySymmetricPermutationModifiers(rule)) {
        return SymmetricReactionExpansionResult::NotApplicable;
    }

    double rateValue = 0.0;
    std::string rateDiagnostic;
    const bool staticRate = evaluateStaticReactionRate(
        rule.getRates().front(), parameters, rateValue, rateDiagnostic);
    if (!staticRate && evaluateStaticExpression(
                           rule.getRates().front(), parameters, rateValue, rateDiagnostic)) {
        return SymmetricReactionExpansionResult::NotApplicable;
    }

    std::set<bng::ast::ReactionRule::ComponentRef> symmetricComponents;
    if (!collectSymmetricReactantComponents(
            rule, system, symmetricComponents, diagnostic)) {
        return SymmetricReactionExpansionResult::Error;
    }
    if (symmetricComponents.empty()) {
        return SymmetricReactionExpansionResult::NotApplicable;
    }

    const auto& bondChange = operations.front();
    std::set<bng::ast::ReactionRule::ComponentRef> reactionCenter {
        bondChange.source, bondChange.partner};
    std::string ignoredComponentName;
    if (!componentNameForReactionRef(
            rule, bondChange.source, ignoredComponentName, diagnostic) ||
        !componentNameForReactionRef(
            rule, bondChange.partner, ignoredComponentName, diagnostic)) {
        return SymmetricReactionExpansionResult::Error;
    }
    bool hasSymmetricReactionCenter = false;
    for (const auto& component : symmetricComponents) {
        if (reactionCenter.find(component) != reactionCenter.end()) {
            hasSymmetricReactionCenter = true;
        }
    }
    if (!hasSymmetricReactionCenter) {
        return SymmetricReactionExpansionResult::NotApplicable;
    }

    GlobalFunction* dynamicGlobal = nullptr;
    CompositeFunction* dynamicComposite = nullptr;
    std::vector<std::string> dynamicLocalFunctionArguments;
    if (!staticRate && !addDynamicReactionRateFunction(
                           rule.getRates().front(), model, parameters, system, sourcePath,
                           rateOrdinal, dynamicGlobal, dynamicComposite,
                           dynamicLocalFunctionArguments, rateDiagnostic)) {
        return SymmetricReactionExpansionResult::NotApplicable;
    }
    if (!dynamicLocalFunctionArguments.empty()) {
        return SymmetricReactionExpansionResult::NotApplicable;
    }

    std::vector<ExpandedReactantPattern> expandedPatterns;
    bool hasDisjointSets = false;
    if (!buildExpandedReactantPatterns(
            rule, system, reactionCenter, suggestedTraversalLimit, expandedPatterns,
            hasDisjointSets, diagnostic)) {
        return SymmetricReactionExpansionResult::Error;
    }

    std::vector<std::size_t> selectedBuild(expandedPatterns.size(), 0);
    std::size_t reactionOrdinal = 0;
    std::function<bool(std::size_t)> addExpandedCombination =
        [&](std::size_t patternIndex) {
            if (patternIndex < expandedPatterns.size()) {
                for (std::size_t buildIndex = 0;
                     buildIndex < expandedPatterns[patternIndex].builds.size();
                     ++buildIndex) {
                    selectedBuild[patternIndex] = buildIndex;
                    if (!addExpandedCombination(patternIndex + 1)) return false;
                }
                return true;
            }

            auto getRuntimeComponent = [&](const bng::ast::ReactionRule::ComponentRef& ref,
                                           TemplateMolecule*& templateMolecule,
                                           std::string& componentName) {
                if (ref.patternIndex >= expandedPatterns.size() ||
                    ref.moleculeIndex >=
                        expandedPatterns[ref.patternIndex]
                            .builds[selectedBuild[ref.patternIndex]].size()) {
                    diagnostic = "bond endpoint is outside the expanded reactant pattern";
                    return false;
                }
                const auto& pattern = expandedPatterns[ref.patternIndex];
                const auto& assignment = pattern.assignments[selectedBuild[ref.patternIndex]];
                if (ref.moleculeIndex >= assignment.size() ||
                    ref.componentIndex >= assignment[ref.moleculeIndex].size()) {
                    diagnostic = "bond endpoint is outside the expanded component assignment";
                    return false;
                }
                templateMolecule = pattern.builds[selectedBuild[ref.patternIndex]]
                                       [ref.moleculeIndex];
                componentName = assignment[ref.moleculeIndex][ref.componentIndex];
                return templateMolecule != nullptr;
            };

            TemplateMolecule* lhs = nullptr;
            TemplateMolecule* rhs = nullptr;
            std::string lhsName;
            std::string rhsName;
            if (!getRuntimeComponent(bondChange.source, lhs, lhsName) ||
                !getRuntimeComponent(bondChange.partner, rhs, rhsName)) {
                return false;
            }

            std::vector<TemplateMolecule*> roots;
            roots.reserve(expandedPatterns.size());
            for (std::size_t index = 0; index < expandedPatterns.size(); ++index) {
                const auto& build = expandedPatterns[index].builds[selectedBuild[index]];
                if (build.empty()) {
                    diagnostic = "symmetric reactant pattern produced no template";
                    return false;
                }
                roots.push_back(build.front());
            }
            auto* transformationSet = new TransformationSet(roots);
            bool applied = false;
            try {
                if (bondChange.type ==
                    bng::ast::ReactionRule::TransformOp::Type::AddBond) {
                    applied = transformationSet->addBindingTransform(
                        lhs, lhsName, rhs, rhsName);
                } else {
                    applied = transformationSet->addUnbindingTransform(
                        lhs, lhsName, rhs, rhsName);
                }
            } catch (const std::exception& error) {
                diagnostic = error.what();
            }
            if (!applied) {
                if (diagnostic.empty()) diagnostic = "could not add symmetric bond transformation";
                delete transformationSet;
                return false;
            }
            transformationSet->setComplexBookkeeping(
                blockSameComplexBinding || hasDisjointSets);
            transformationSet->setNumProductPatterns(
                static_cast<unsigned int>(rule.getProductPatterns().size()));
            transformationSet->finalize();

            const auto reactionName =
                rule.getRuleName() + "_sym" + std::to_string(reactionOrdinal + 1);
            ReactionClass* reaction = nullptr;
            if (dynamicGlobal != nullptr) {
                reaction = new FunctionalRxnClass(
                    reactionName, dynamicGlobal, transformationSet, system);
            } else if (dynamicComposite != nullptr) {
                reaction = new FunctionalRxnClass(
                    reactionName, dynamicComposite, transformationSet, system);
            } else {
                std::string rateParameterName;
                if (rule.getRates().front().kind() == bng::ast::ExpressionKind::Identifier &&
                    parameters.count(rule.getRates().front().name()) != 0) {
                    rateParameterName = rule.getRates().front().name();
                }
                reaction = new BasicRxnClass(
                    reactionName, rateValue, rateParameterName, transformationSet, system);
            }
            reaction->setTotalRateFlag(hasReactionModifier(rule, "totalrate"));
            if (hasReactionModifier(rule, "matchonce")) {
                for (std::size_t index = 0; index < expandedPatterns.size(); ++index) {
                    reaction->setMatchOnce(static_cast<unsigned int>(index), true);
                }
            }
            ++reactionOrdinal;
            if (dynamicGlobal != nullptr || dynamicComposite != nullptr || rateValue > 0.0) {
                system->addReaction(reaction);
                if (verbose) {
                    std::cerr << "[nfsim/ast] reaction " << rule.getRuleName()
                              << " (direct symmetric bond permutation)\n";
                }
            } else {
                delete reaction;
            }
            return true;
        };

    if (!addExpandedCombination(0)) {
        return SymmetricReactionExpansionResult::Error;
    }
    return SymmetricReactionExpansionResult::Added;
}

bool addDynamicReactionRateFunction(
    const bng::ast::Expression& expression,
    const bng::ast::Model& model,
    const std::map<std::string, double>& parameters,
    System* system,
    const std::filesystem::path& sourcePath,
    std::size_t ordinal,
    GlobalFunction*& global,
    CompositeFunction*& composite,
    std::vector<std::string>& localFunctionArgumentNamesOut,
    std::string& diagnostic) {
    global = nullptr;
    composite = nullptr;
    localFunctionArgumentNamesOut.clear();

    std::set<std::string> observableReferences;
    std::set<std::string> functionReferences;
    std::set<std::string> localFunctionReferences;
    std::set<std::string> localFunctionArgumentNames;
    std::set<std::string> parameterReferences;
    std::vector<const bng::ast::Expression*> tableFunctions;
    bool usesTime = false;
    std::set<std::string> activeFunctions;
    std::string expandedExpression;
    if (!expandDynamicRateExpression(
            expression, model, parameters, observableReferences,
            functionReferences, parameterReferences, tableFunctions,
            &localFunctionReferences, &localFunctionArgumentNames, usesTime,
            activeFunctions, expandedExpression, diagnostic)) {
        return false;
    }
    if (tableFunctions.size() > 1) {
        diagnostic = "dynamic reaction rates support at most one TFUN expression";
        return false;
    }

    if (!usesTime && observableReferences.empty() && functionReferences.empty() &&
        localFunctionReferences.empty() &&
        tableFunctions.empty()) {
        diagnostic = "rate expression is not a supported dynamic function";
        return false;
    }
    if (usesTime && !tableFunctions.empty()) {
        const auto& counter = tableFunctions.front()->args().front();
        const auto counterName = counter.name();
        if (lowerCase(counterName) != "time" && lowerCase(counterName) != "t") {
            diagnostic = "dynamic reaction rates cannot combine a non-time TFUN counter "
                         "with a time-dependent expression";
            return false;
        }
    }

    std::string name = "__bng3_reaction_rate_" + std::to_string(ordinal + 1);
    std::size_t suffix = 1;
    while (system->getGlobalFunctionByName(name) != nullptr ||
           system->getCompositeFunctionByName(name) != nullptr ||
           system->getLocalFunctionByName(name) != nullptr) {
        name = "__bng3_reaction_rate_" + std::to_string(ordinal + 1) +
               "_" + std::to_string(suffix++);
    }

    std::vector<std::string> parameterNames(
        parameterReferences.begin(), parameterReferences.end());
    if (!functionReferences.empty() || !localFunctionReferences.empty()) {
        // CompositeFunction can depend on live observable values only through
        // GlobalFunction objects.  Materialize a zero-argument alias for each
        // direct observable, then rewrite the generated expression to refer to
        // those aliases.  This preserves dependency invalidation while keeping
        // the legacy composite-function parser's observable restriction intact.
        std::map<std::string, std::string> observableAliases;
        std::size_t aliasIndex = 1;
        for (const auto& observableName : observableReferences) {
            std::string aliasName = "__bng3_reaction_observable_" +
                                    std::to_string(ordinal + 1) + "_" +
                                    std::to_string(aliasIndex++);
            std::size_t aliasSuffix = 1;
            while (system->getGlobalFunctionByName(aliasName) != nullptr ||
                   system->getCompositeFunctionByName(aliasName) != nullptr ||
                   system->getLocalFunctionByName(aliasName) != nullptr) {
                aliasName = "__bng3_reaction_observable_" +
                            std::to_string(ordinal + 1) + "_" +
                            std::to_string(aliasIndex - 1) + "_" +
                            std::to_string(aliasSuffix++);
            }

            std::vector<std::string> aliasReferences {observableName};
            std::vector<std::string> aliasTypes {"Observable"};
            std::vector<std::string> aliasParameters;
            auto* alias = new GlobalFunction(
                aliasName, observableName, aliasReferences, aliasTypes,
                aliasParameters, system);
            if (!system->addGlobalFunction(alias)) {
                delete alias;
                diagnostic = "failed to register generated reaction observable alias '" +
                             aliasName + "'";
                return false;
            }
            observableAliases.emplace(observableName, std::move(aliasName));
        }

        for (const auto& dependency : functionReferences) {
            if (isReactantCountReference(dependency)) {
                // CompositeFunction binds reactant_N at preparation time from
                // the current reaction mapping. It is not a System global,
                // even though the source-shaped expression retains the name.
                continue;
            }
            if (system->getGlobalFunctionByName(dependency) == nullptr) {
                diagnostic = "dynamic reaction rates only support references to base global "
                             "functions; '" + dependency + "' is composite or unavailable";
                return false;
            }
        }
        for (const auto& dependency : localFunctionReferences) {
            if (system->getLocalFunctionByName(dependency) == nullptr) {
                diagnostic = "dynamic reaction rate references unavailable local function '" +
                             dependency + "'";
                return false;
            }
        }
        std::vector<std::string> functionsCalled(
            functionReferences.begin(), functionReferences.end());
        for (const auto& [observableName, aliasName] : observableAliases) {
            (void)observableName;
            functionsCalled.push_back(aliasName);
        }
        functionsCalled.insert(
            functionsCalled.end(), localFunctionReferences.begin(),
            localFunctionReferences.end());
        std::vector<std::string> argumentNames(
            localFunctionArgumentNames.begin(), localFunctionArgumentNames.end());
        const auto compositeExpression = replaceNamedReferences(
            expandedExpression, observableAliases);
        auto candidate = std::make_unique<CompositeFunction>(
            system, name, compositeExpression, functionsCalled,
            argumentNames, parameterNames);
        if (!tableFunctions.empty() &&
            !configureDirectTableFunction(
                *tableFunctions.front(), model, parameters, sourcePath, system,
                nullptr, candidate.get(), nullptr, diagnostic)) {
            return false;
        }
        if (!system->addCompositeFunction(candidate.get())) {
            diagnostic = "failed to register generated dynamic reaction-rate composite";
            return false;
        }
        composite = candidate.release();
        composite->finalizeInitialization(system);
        localFunctionArgumentNamesOut = std::move(argumentNames);
        if (usesTime) {
            composite->setCounterFromTime(system);
            system->setHasTimeDependentFunctions(true);
        }
        return true;
    }

    std::vector<std::string> referenceNames(
        observableReferences.begin(), observableReferences.end());
    std::vector<std::string> referenceTypes(referenceNames.size(), "Observable");
    auto candidate = std::make_unique<GlobalFunction>(
        name, expandedExpression, referenceNames, referenceTypes,
        parameterNames, system);

    if (!tableFunctions.empty() &&
        !configureDirectTableFunction(
            *tableFunctions.front(), model, parameters, sourcePath, system,
            candidate.get(), nullptr, nullptr, diagnostic)) {
        return false;
    }

    if (!system->addGlobalFunction(candidate.get())) {
        diagnostic = "failed to register generated dynamic reaction rate function";
        return false;
    }
    global = candidate.release();
    if (usesTime) {
        global->setCounterFromTime(system);
        system->setHasTimeDependentFunctions(true);
    }
    return true;
}

bool addEnergyPatternsFromAst(const bng::ast::Model& model, System* system,
                              const std::map<std::string, double>& parameters,
                              bool verbose) {
    const auto& energyPatterns = model.getEnergyPatterns();
    if (energyPatterns.empty()) return true;

    double phi = 0.5;
    double rt = 2.478;
    if (const auto iter = parameters.find("phi"); iter != parameters.end()) phi = iter->second;
    if (const auto iter = parameters.find("RT"); iter != parameters.end()) rt = iter->second;
    if (!std::isfinite(phi) || !std::isfinite(rt) || rt == 0.0) {
        std::cerr << "[nfsim/ast] energy expansion requires finite phi and nonzero RT\n";
        return false;
    }

    auto* energyFunction = new EnergyFunction(phi, rt);
    std::set<std::string> ids;
    for (std::size_t patternIndex = 0; patternIndex < energyPatterns.size(); ++patternIndex) {
        const auto& pattern = energyPatterns[patternIndex];
        EnergyPatternInfo info;
        info.id = pattern.getLabel().empty()
                      ? "energy_" + std::to_string(patternIndex + 1)
                      : pattern.getLabel();
        if (!ids.insert(info.id).second) {
            std::cerr << "[nfsim/ast] duplicate energy-pattern id '" << info.id << "'\n";
            delete energyFunction;
            return false;
        }

        std::string diagnostic;
        if (!evaluateStaticExpression(
                pattern.getExpression(), parameters, info.energyValue, diagnostic)) {
            std::cerr << "[nfsim/ast] cannot evaluate energy pattern '" << info.id
                      << "': " << diagnostic << "\n";
            delete energyFunction;
            return false;
        }

        const auto molecules = collectGraphMolecules(pattern.getGraph().getGraph());
        if (molecules.empty()) {
            std::cerr << "[nfsim/ast] energy pattern '" << info.id
                      << "' contains no molecule graph\n";
            delete energyFunction;
            return false;
        }

        for (std::size_t moleculeIndex = 0; moleculeIndex < molecules.size(); ++moleculeIndex) {
            const auto& molecule = molecules[moleculeIndex];
            MoleculeType* moleculeType = nullptr;
            try {
                moleculeType = system->getMoleculeTypeByName(molecule.name);
            } catch (const std::exception& error) {
                diagnostic = error.what();
            }
            if (moleculeType == nullptr) {
                std::cerr << "[nfsim/ast] cannot map energy pattern '" << info.id
                          << "': " << diagnostic << "\n";
                delete energyFunction;
                return false;
            }

            EpMolecule energyMolecule;
            energyMolecule.typeName = molecule.name;
            energyMolecule.xmlId = "m" + std::to_string(moleculeIndex + 1);
            for (std::size_t componentIndex = 0;
                 componentIndex < molecule.components.size(); ++componentIndex) {
                const auto& component = molecule.components[componentIndex];
                try {
                    moleculeType->getCompIndexFromName(component.name);
                } catch (const std::exception& error) {
                    std::cerr << "[nfsim/ast] cannot map energy pattern '" << info.id
                              << "': " << error.what() << "\n";
                    delete energyFunction;
                    return false;
                }
                EpMolecule::CompInfo energyComponent;
                energyComponent.name = component.name;
                energyComponent.isBound = false;
                energyComponent.stateConstraint = graphStateToken(*component.node);
                if (energyComponent.stateConstraint == "?" ||
                    energyComponent.stateConstraint == "*") {
                    energyComponent.stateConstraint.clear();
                }
                energyMolecule.components.push_back(std::move(energyComponent));
            }
            info.molecules.push_back(std::move(energyMolecule));
        }

        std::set<BNGcore::Node*> processedBonds;
        for (std::size_t moleculeIndex = 0; moleculeIndex < molecules.size(); ++moleculeIndex) {
            for (std::size_t componentIndex = 0;
                 componentIndex < molecules[moleculeIndex].components.size(); ++componentIndex) {
                const auto& component = molecules[moleculeIndex].components[componentIndex];
                for (auto* bond : component.bonds) {
                    if (graphBondToken(*bond) != "!+") continue;
                    if (!processedBonds.insert(bond).second) continue;

                    std::vector<std::pair<int, int>> endpoints;
                    for (std::size_t candidateMolecule = 0;
                         candidateMolecule < molecules.size(); ++candidateMolecule) {
                        for (std::size_t candidateComponent = 0;
                             candidateComponent < molecules[candidateMolecule].components.size();
                             ++candidateComponent) {
                            const auto& candidate =
                                molecules[candidateMolecule].components[candidateComponent];
                            if (std::find(candidate.bonds.begin(), candidate.bonds.end(), bond) !=
                                candidate.bonds.end()) {
                                endpoints.emplace_back(
                                    static_cast<int>(candidateMolecule),
                                    static_cast<int>(candidateComponent));
                            }
                        }
                    }
                    if (endpoints.size() != 2) {
                        std::cerr << "[nfsim/ast] energy pattern '" << info.id
                                  << "' has a bound bond without exactly two endpoints\n";
                        delete energyFunction;
                        return false;
                    }

                    EnergyPatternInfo::Bond energyBond;
                    energyBond.mol1 = endpoints[0].first;
                    energyBond.comp1 = endpoints[0].second;
                    energyBond.mol2 = endpoints[1].first;
                    energyBond.comp2 = endpoints[1].second;
                    info.bonds.push_back(energyBond);
                    auto& first = info.molecules[energyBond.mol1].components[energyBond.comp1];
                    auto& second = info.molecules[energyBond.mol2].components[energyBond.comp2];
                    first.isBound = true;
                    second.isBound = true;
                    first.bondPartnerId = info.molecules[energyBond.mol2].xmlId;
                    second.bondPartnerId = info.molecules[energyBond.mol1].xmlId;
                }
            }
        }

        energyFunction->addEnergyPattern(info);
        if (verbose) {
            std::cerr << "[nfsim/ast] energy pattern " << info.id
                      << " = " << info.energyValue << "\n";
        }
    }

    system->setEnergyFunction(energyFunction);
    if (verbose) {
        std::cerr << "[nfsim/ast] parsed " << energyFunction->getNumPatterns()
                  << " energy pattern(s), RT=" << rt << "\n";
    }
    return true;
}

bool isArrheniusExpression(const bng::ast::Expression& expression) {
    return expression.kind() == bng::ast::ExpressionKind::Function &&
           lowerCase(expression.name()) == "arrhenius" && expression.args().size() == 2;
}

bool addDirectArrheniusBinding(const bng::ast::ReactionRule& rule, System* system,
                               const std::map<std::string, double>& parameters,
                               bool blockSameComplexBinding, bool verbose,
                               int& suggestedTraversalLimit) {
    if (rule.getRates().size() != 1 ||
        !isArrheniusExpression(rule.getRates().front())) {
        return false;
    }

    const auto* energyFunction = system->getEnergyFunction();
    if (energyFunction == nullptr) {
        std::cerr << "[nfsim/ast] Arrhenius reaction '" << rule.getRuleName()
                  << "' requires energy patterns\n";
        return false;
    }

    const auto& reactantPatterns = rule.getReactantPatterns();
    if (reactantPatterns.size() != 2 || rule.getProducts().empty()) {
        std::cerr << "[nfsim/ast] direct Arrhenius binding requires two reactant patterns\n";
        return false;
    }
    const auto firstReactantMolecules = collectGraphMolecules(reactantPatterns[0].getGraph());
    const auto secondReactantMolecules = collectGraphMolecules(reactantPatterns[1].getGraph());
    if (firstReactantMolecules.size() != 1 || secondReactantMolecules.size() != 1) {
        std::cerr << "[nfsim/ast] direct Arrhenius binding requires one molecule per reactant\n";
        return false;
    }

    const bng::ast::ReactionRule::TransformOp* addBond = nullptr;
    for (const auto& operation : rule.getOperations()) {
        if (operation.type == bng::ast::ReactionRule::TransformOp::Type::AddBond) {
            if (addBond != nullptr) {
                std::cerr << "[nfsim/ast] direct Arrhenius binding supports one added bond\n";
                return false;
            }
            addBond = &operation;
        } else {
            std::cerr << "[nfsim/ast] direct Arrhenius binding supports only AddBond\n";
            return false;
        }
    }
    if (addBond == nullptr || addBond->source.patternIndex == addBond->partner.patternIndex ||
        addBond->source.moleculeIndex != 0 || addBond->partner.moleculeIndex != 0) {
        std::cerr << "[nfsim/ast] direct Arrhenius binding has an invalid reaction center\n";
        return false;
    }

    std::string site1;
    std::string site2;
    std::string diagnostic;
    if (!componentNameForReactionRef(rule, addBond->source, site1, diagnostic) ||
        !componentNameForReactionRef(rule, addBond->partner, site2, diagnostic)) {
        std::cerr << "[nfsim/ast] cannot map Arrhenius reaction '" << rule.getRuleName()
                  << "': " << diagnostic << "\n";
        return false;
    }

    MoleculeType* moleculeType1 = nullptr;
    MoleculeType* moleculeType2 = nullptr;
    try {
        moleculeType1 = system->getMoleculeTypeByName(firstReactantMolecules[0].name);
        moleculeType2 = system->getMoleculeTypeByName(secondReactantMolecules[0].name);
    } catch (const std::exception& error) {
        std::cerr << "[nfsim/ast] cannot map Arrhenius reaction '" << rule.getRuleName()
                  << "': " << error.what() << "\n";
        return false;
    }
    if (addBond->source.patternIndex != 0) {
        std::swap(moleculeType1, moleculeType2);
        std::swap(site1, site2);
    }

    double phi = 0.0;
    double activationEnergy = 0.0;
    if (!evaluateStaticExpression(
            rule.getRates().front().args()[0], parameters, phi, diagnostic) ||
        !evaluateStaticExpression(
            rule.getRates().front().args()[1], parameters, activationEnergy, diagnostic)) {
        std::cerr << "[nfsim/ast] cannot map Arrhenius reaction '" << rule.getRuleName()
                  << "': " << diagnostic << "\n";
        return false;
    }

    std::map<std::string, double> unusedParameters;
    std::map<std::string, int> unusedStates;
    int reactionCount = 0;
    const std::size_t firstNewReaction = system->getAllReactions().size();
    if (!createExpandedBindingReactions(
            rule.getRuleName(), phi, activationEnergy, moleculeType1, site1,
            moleculeType2, site2, system, unusedParameters, unusedStates,
            blockSameComplexBinding, verbose, reactionCount, rule.isBidirectional())) {
        return false;
    }

    const auto reactions = system->getAllReactions();
    for (std::size_t reactionIndex = firstNewReaction;
         reactionIndex < reactions.size(); ++reactionIndex) {
        auto* reaction = reactions[reactionIndex];
        reaction->setTotalRateFlag(hasReactionModifier(rule, "totalrate"));
        if (hasReactionModifier(rule, "matchonce")) {
            for (std::size_t reactantIndex = 0;
                 reactantIndex < reactantPatterns.size(); ++reactantIndex) {
                reaction->setMatchOnce(static_cast<unsigned int>(reactantIndex), true);
            }
        }
    }
    suggestedTraversalLimit = std::max(suggestedTraversalLimit, 2);
    return true;
}

bool addDirectArrheniusStateChange(const bng::ast::ReactionRule& rule, System* system,
                                   const std::map<std::string, double>& parameters,
                                   bool blockSameComplexBinding, bool verbose,
                                   int& suggestedTraversalLimit) {
    if (rule.getRates().size() != 1 ||
        !isArrheniusExpression(rule.getRates().front())) {
        return false;
    }

    const auto& reactantPatterns = rule.getReactantPatterns();
    if (reactantPatterns.size() != 1) {
        std::cerr << "[nfsim/ast] direct Arrhenius state change requires one reactant pattern\n";
        return false;
    }
    const auto molecules = collectGraphMolecules(reactantPatterns.front().getGraph());
    if (molecules.size() != 1) {
        std::cerr << "[nfsim/ast] direct Arrhenius state change requires one reactant molecule\n";
        return false;
    }

    const bng::ast::ReactionRule::TransformOp* stateChange = nullptr;
    for (const auto& operation : rule.getOperations()) {
        if (operation.type == bng::ast::ReactionRule::TransformOp::Type::ChangeState) {
            if (stateChange != nullptr) {
                std::cerr << "[nfsim/ast] direct Arrhenius state change supports one changed component\n";
                return false;
            }
            stateChange = &operation;
        } else {
            std::cerr << "[nfsim/ast] direct Arrhenius state change supports only ChangeState\n";
            return false;
        }
    }
    if (stateChange == nullptr || stateChange->source.patternIndex != 0 ||
        stateChange->source.moleculeIndex != 0 || stateChange->newState == "PLUS" ||
        stateChange->newState == "MINUS" ||
        stateChange->source.componentIndex >= molecules.front().components.size()) {
        std::cerr << "[nfsim/ast] direct Arrhenius state change has an invalid reaction center\n";
        return false;
    }

    std::string component;
    std::string diagnostic;
    if (!componentNameForReactionRef(rule, stateChange->source, component, diagnostic)) {
        std::cerr << "[nfsim/ast] cannot map Arrhenius reaction '" << rule.getRuleName()
                  << "': " << diagnostic << "\n";
        return false;
    }
    const std::string stateFrom = graphStateToken(
        *molecules.front().components[stateChange->source.componentIndex].node);
    if (stateFrom.empty() || stateFrom == "?" || stateFrom == "*") {
        std::cerr << "[nfsim/ast] Arrhenius state change needs an explicit source state\n";
        return false;
    }

    MoleculeType* moleculeType = nullptr;
    try {
        moleculeType = system->getMoleculeTypeByName(molecules.front().name);
    } catch (const std::exception& error) {
        std::cerr << "[nfsim/ast] cannot map Arrhenius reaction '" << rule.getRuleName()
                  << "': " << error.what() << "\n";
        return false;
    }

    double phi = 0.0;
    double activationEnergy = 0.0;
    if (!evaluateStaticExpression(
            rule.getRates().front().args()[0], parameters, phi, diagnostic) ||
        !evaluateStaticExpression(
            rule.getRates().front().args()[1], parameters, activationEnergy, diagnostic)) {
        std::cerr << "[nfsim/ast] cannot map Arrhenius reaction '" << rule.getRuleName()
                  << "': " << diagnostic << "\n";
        return false;
    }

    const std::size_t firstNewReaction = system->getAllReactions().size();
    int reactionCount = 0;
    if (!createExpandedStateChangeReactions(
            rule.getRuleName(), phi, activationEnergy, moleculeType, component,
            stateFrom, stateChange->newState, system, blockSameComplexBinding,
            verbose, reactionCount, rule.isBidirectional())) {
        return false;
    }

    const auto reactions = system->getAllReactions();
    for (std::size_t reactionIndex = firstNewReaction;
         reactionIndex < reactions.size(); ++reactionIndex) {
        auto* reaction = reactions[reactionIndex];
        reaction->setTotalRateFlag(hasReactionModifier(rule, "totalrate"));
        if (hasReactionModifier(rule, "matchonce")) {
            reaction->setMatchOnce(0, true);
        }
    }
    suggestedTraversalLimit = std::max(suggestedTraversalLimit, 1);
    return true;
}

std::string graphMoleculeCompartment(const bng::ast::SpeciesGraph& pattern,
                                     const GraphMolecule& molecule) {
    if (!molecule.node->get_compartment().empty()) {
        return molecule.node->get_compartment();
    }
    return pattern.getCompartment();
}

bool isDiscardMolecule(const GraphMolecule& molecule) {
    const std::string normalizedName = lowerCase(molecule.name);
    return normalizedName == "null" || normalizedName == "trash";
}

struct DirectProductMolecule {
    TemplateMolecule* templateMolecule = nullptr;
    MoleculeCreator* creator = nullptr;
    std::vector<std::string> runtimeComponentNames;
};

bool buildDirectProductMolecule(const bng::ast::SpeciesGraph& pattern,
                                std::size_t moleculeIndex,
                                System* system,
                                DirectProductMolecule& result,
                                std::string& diagnostic) {
    const auto molecules = collectGraphMolecules(pattern.getGraph());
    if (moleculeIndex >= molecules.size()) {
        diagnostic = "AddMolecule refers to an unknown product molecule";
        return false;
    }

    const auto& molecule = molecules[moleculeIndex];
    auto* moleculeType = system->getMoleculeTypeByName(molecule.name);
    if (moleculeType == nullptr) {
        diagnostic = "unknown product molecule type '" + molecule.name + "'";
        return false;
    }
    if (moleculeType->isPopulationType()) {
        diagnostic = "population product molecules require population mapping";
        return false;
    }

    auto* templateMolecule = new TemplateMolecule(moleculeType);
    const std::string compartmentName = molecule.node->get_compartment().empty()
                                            ? pattern.getCompartment()
                                            : molecule.node->get_compartment();
    Compartment* compartment = nullptr;
    if (!resolveCompartment(system, compartmentName, compartment, diagnostic)) {
        delete templateMolecule;
        return false;
    }
    templateMolecule->setCompartment(compartment);

    // MoleculeCreator creates a default molecule, so the creator template must
    // constrain every site to be empty.  This is the same invariant enforced by
    // NFinput::readProductMolecule for XML-created product molecules.
    for (int componentIndex = 0;
         componentIndex < moleculeType->getNumOfComponents(); ++componentIndex) {
        templateMolecule->addEmptyComponent(moleculeType->getComponentName(componentIndex));
    }

    std::vector<std::pair<int, int>> componentStates;
    std::vector<std::string> runtimeComponentNames;
    std::map<std::string, std::size_t> symmetricComponentUse;
    std::set<int> specifiedComponents;
    for (const auto& component : molecule.components) {
        if (component.bonds.size() > 1) {
            diagnostic = "product component has multiple bond constraints";
            delete templateMolecule;
            return false;
        }
        if (component.bonds.size() == 1) {
            const std::string bond = graphBondToken(*component.bonds.front());
            if (bond != "!-" && bond != "!?" && bond != "!+") {
                diagnostic = "unsupported product bond constraint '" + bond + "'";
                delete templateMolecule;
                return false;
            }
            if (bond == "!+") {
                std::vector<std::pair<std::size_t, std::size_t>> endpoints;
                for (std::size_t candidateMolecule = 0;
                     candidateMolecule < molecules.size(); ++candidateMolecule) {
                    for (std::size_t candidateComponent = 0;
                         candidateComponent < molecules[candidateMolecule].components.size();
                         ++candidateComponent) {
                        const auto& candidate = molecules[candidateMolecule]
                                                     .components[candidateComponent];
                        if (std::find(candidate.bonds.begin(), candidate.bonds.end(),
                                      component.bonds.front()) != candidate.bonds.end()) {
                            endpoints.emplace_back(candidateMolecule, candidateComponent);
                        }
                    }
                }
                if (endpoints.size() != 2) {
                    diagnostic = "product bond must connect exactly two components";
                    delete templateMolecule;
                    return false;
                }
                // NFsim's legacy XML loader permits a product bond whose two
                // endpoints are on the same newly created molecule.  The
                // TransformationSet supports this mapping by assigning the
                // second endpoint the next mapping slot, so keep the graph
                // edge and let the product-bond transform install it.
            }
        }
        std::string runtimeName = component.name;
        if (moleculeType->isEquivalentComponent(component.name)) {
            std::vector<std::string> equivalentNames;
            if (!getEquivalentNames(moleculeType, component.name, equivalentNames)) {
                diagnostic = "could not resolve symmetric product component '" +
                             component.name + "'";
                delete templateMolecule;
                return false;
            }
            auto& useCount = symmetricComponentUse[component.name];
            if (useCount >= equivalentNames.size()) {
                diagnostic = "too many symmetric product components named '" +
                             component.name + "'";
                delete templateMolecule;
                return false;
            }
            runtimeName = equivalentNames[useCount++];
        }
        runtimeComponentNames.push_back(runtimeName);

        int componentIndex = -1;
        try {
            componentIndex = moleculeType->getCompIndexFromName(runtimeName);
        } catch (const std::exception& error) {
            diagnostic = error.what();
            delete templateMolecule;
            return false;
        }
        if (!specifiedComponents.insert(componentIndex).second) {
            diagnostic = "product molecule specifies a component more than once";
            delete templateMolecule;
            return false;
        }

        const std::string state = graphStateToken(*component.node);
        const int stateValue = componentStateValue(
            moleculeType, runtimeName, state, diagnostic);
        if (stateValue == -2) {
            delete templateMolecule;
            return false;
        }
        if (stateValue >= 0) {
            componentStates.emplace_back(componentIndex, stateValue);
            try {
                templateMolecule->addComponentConstraint(runtimeName, stateValue);
            } catch (const std::exception& error) {
                diagnostic = error.what();
                delete templateMolecule;
                return false;
            }
        }
    }

    result.templateMolecule = templateMolecule;
    result.runtimeComponentNames = std::move(runtimeComponentNames);
    result.creator = new MoleculeCreator(
        templateMolecule, moleculeType, componentStates, compartment);
    return true;
}

struct RuleGraphMolecule {
    std::size_t patternIndex = 0;
    std::size_t moleculeIndex = 0;
    GraphMolecule molecule;
};

std::vector<RuleGraphMolecule> collectRuleGraphMolecules(
    const std::vector<bng::ast::SpeciesGraph>& patterns) {
    std::vector<RuleGraphMolecule> result;
    for (std::size_t patternIndex = 0; patternIndex < patterns.size(); ++patternIndex) {
        const auto molecules = collectGraphMolecules(patterns[patternIndex].getGraph());
        for (std::size_t moleculeIndex = 0; moleculeIndex < molecules.size(); ++moleculeIndex) {
            result.push_back(RuleGraphMolecule{patternIndex, moleculeIndex, molecules[moleculeIndex]});
        }
    }
    return result;
}

std::string graphMoleculeKey(const GraphMolecule& molecule) {
    std::vector<std::string> componentNames;
    componentNames.reserve(molecule.components.size());
    for (const auto& component : molecule.components) {
        componentNames.push_back(component.name);
    }
    std::sort(componentNames.begin(), componentNames.end());
    std::ostringstream key;
    key << molecule.name << ":";
    for (const auto& componentName : componentNames) key << componentName << ";";
    return key.str();
}

bool buildProductComponentMapping(
    const bng::ast::ReactionRule& rule,
    std::map<bng::ast::ReactionRule::ComponentRef,
             bng::ast::ReactionRule::ComponentRef>& productToReactant,
    std::map<bng::ast::ReactionRule::ComponentRef,
             bng::ast::ReactionRule::ComponentRef>& productMoleculeToReactant,
    std::string& diagnostic) {
    const auto reactants = collectRuleGraphMolecules(rule.getReactantPatterns());
    const auto products = collectRuleGraphMolecules(rule.getProductPatterns());
    productMoleculeToReactant.clear();
    std::unordered_map<std::string, std::vector<std::size_t>> reactantsByKey;
    for (std::size_t index = 0; index < reactants.size(); ++index) {
        reactantsByKey[graphMoleculeKey(reactants[index].molecule)].push_back(index);
    }

    std::vector<bool> usedReactants(reactants.size(), false);
    for (const auto& product : products) {
        const auto key = graphMoleculeKey(product.molecule);
        auto keyIt = reactantsByKey.find(key);
        if (keyIt == reactantsByKey.end()) continue;

        std::size_t matchedIndex = reactants.size();
        for (const auto candidate : keyIt->second) {
            if (!usedReactants[candidate]) {
                matchedIndex = candidate;
                break;
            }
        }
        if (matchedIndex == reactants.size()) continue;
        usedReactants[matchedIndex] = true;
        const auto& reactant = reactants[matchedIndex];
        productMoleculeToReactant.emplace(
            bng::ast::ReactionRule::ComponentRef{
                product.patternIndex, product.moleculeIndex, 0},
            bng::ast::ReactionRule::ComponentRef{
                reactant.patternIndex, reactant.moleculeIndex, 0});

        std::map<std::string, std::vector<std::size_t>> reactantComponents;
        for (std::size_t componentIndex = 0;
             componentIndex < reactant.molecule.components.size(); ++componentIndex) {
            reactantComponents[reactant.molecule.components[componentIndex].name].push_back(
                componentIndex);
        }
        std::map<std::string, std::size_t> componentOffsets;
        for (std::size_t componentIndex = 0;
             componentIndex < product.molecule.components.size(); ++componentIndex) {
            const auto& productComponent = product.molecule.components[componentIndex];
            auto componentIt = reactantComponents.find(productComponent.name);
            if (componentIt == reactantComponents.end()) {
                diagnostic = "product component has no matching reactant component";
                return false;
            }
            const auto offset = componentOffsets[productComponent.name]++;
            if (offset >= componentIt->second.size()) {
                diagnostic = "product contains more components than its reactant molecule";
                return false;
            }
            productToReactant.emplace(
                bng::ast::ReactionRule::ComponentRef{
                    product.patternIndex, product.moleculeIndex, componentIndex},
                bng::ast::ReactionRule::ComponentRef{
                    reactant.patternIndex, reactant.moleculeIndex,
                    componentIt->second[offset]});
        }
    }
    return true;
}

bool componentNameForGraphRef(
    const std::vector<bng::ast::SpeciesGraph>& patterns,
    const bng::ast::ReactionRule::ComponentRef& ref,
    std::string& name,
    std::string& diagnostic) {
    if (ref.patternIndex >= patterns.size()) {
        diagnostic = "component reference points outside the pattern list";
        return false;
    }
    const auto molecules = collectGraphMolecules(patterns[ref.patternIndex].getGraph());
    if (ref.moleculeIndex >= molecules.size() ||
        ref.componentIndex >= molecules[ref.moleculeIndex].components.size()) {
        diagnostic = "component reference points outside its molecule";
        return false;
    }
    name = molecules[ref.moleculeIndex].components[ref.componentIndex].name;
    return true;
}

} // namespace

bool addObservablesFromAst(const bng::ast::Model& model, System* s,
                           const std::map<std::string, double>& parameters,
                           bool verbose, int& suggestedTraversalLimit) {
    (void)parameters;
    if (s == nullptr) return false;

    std::unordered_set<std::string> names;
    for (const auto& observable : model.getObservables()) {
        if (observable.getName().empty() || !names.insert(observable.getName()).second) {
            std::cerr << "[nfsim/ast] duplicate or missing observable '"
                      << observable.getName() << "'\n";
            return false;
        }
        if (observable.getPatterns().empty()) {
            std::cerr << "[nfsim/ast] observable '" << observable.getName()
                      << "' contains no patterns\n";
            return false;
        }

        const std::string type = observable.getType();
        if (type != "Molecules" && type != "Species") {
            std::cerr << "[nfsim/ast] unsupported observable type '" << type
                      << "'\n";
            return false;
        }
        const bool moleculesObservable = type == "Molecules";
        if (!moleculesObservable) s->setUsingComplex(true);

        std::vector<TemplateMolecule*> templates;
        std::vector<std::string> relations;
        std::vector<int> quantities;
        bool hasDisjointSets = false;
        for (const auto& patternText : observable.getPatterns()) {
            ParsedObservablePattern parsed;
            std::string diagnostic;
            if (!parseObservablePattern(patternText, model, parsed, diagnostic)) {
                std::cerr << "[nfsim/ast] cannot map observable '" << observable.getName()
                          << "': " << diagnostic << "\n";
                return false;
            }

            std::vector<std::vector<TemplateMolecule*>> builds;
            if (!buildTemplatePatterns(parsed.graph, parsed.compartment, s,
                                        moleculesObservable, builds, hasDisjointSets,
                                        suggestedTraversalLimit, diagnostic)) {
                std::cerr << "[nfsim/ast] cannot map observable '" << observable.getName()
                          << "': " << diagnostic << "\n";
                return false;
            }
            for (auto& build : builds) {
                // One observable template represents one whole pattern.  The
                // first template is the root; buildTemplatePatterns wires the
                // remaining molecules to it with explicit bonds or
                // connected-to edges.  Adding every molecule here would count
                // a connected pattern once per member rather than once per
                // matching pattern.
                if (build.empty()) {
                    diagnostic = "observable pattern produced no template";
                    return false;
                }
                templates.push_back(build.front());
                relations.push_back(parsed.relation);
                quantities.push_back(parsed.quantity);
            }
        }
        if (templates.empty()) return false;

        bool hasStoichiometricConstraints = false;
        for (const auto& relation : relations) {
            if (!relation.empty()) {
                hasStoichiometricConstraints = true;
                break;
            }
        }
        if (hasStoichiometricConstraints) s->setUsingComplex(true);

        Observable* created = nullptr;
        if (moleculesObservable) {
            if (hasStoichiometricConstraints) {
                created = new MoleculesObservable(observable.getName(), templates,
                                                  relations, quantities);
            } else {
                created = new MoleculesObservable(observable.getName(), templates);
            }
            // Match the legacy XML loader: register only the root template's
            // molecule type.  Connected members are reached through that root
            // during observable matching.
            std::unordered_set<MoleculeType*> addedTypes;
            for (auto* templateMolecule : templates) {
                if (addedTypes.insert(templateMolecule->getMoleculeType()).second) {
                    templateMolecule->getMoleculeType()->addMolObs(
                        static_cast<MoleculesObservable*>(created));
                }
            }
        } else {
            created = new SpeciesObservable(observable.getName(), templates,
                                            relations, quantities);
        }
        s->addObservableForOutput(created);
        if (verbose) {
            std::cerr << "[nfsim/ast] " << type << " observable "
                      << observable.getName() << "\n";
        }
    }
    return true;
}

bool addSpeciesFromAstWithOverrides(
    const bng::ast::Model& model, System* s,
    const std::map<std::string, double>& parameters, bool verbose,
    const SeedAmountOverrides& seedAmountOverrides) {
    if (s == nullptr) return false;

    for (const auto& seed : model.getSeedSpecies()) {
        const auto molecules = canonicalizeSeedGraphMolecules(
            collectGraphMolecules(seed.getGraph()));
        if (molecules.empty()) {
            std::cerr << "[nfsim/ast] seed species '" << seed.getPattern()
                      << "' contains no molecule graph\n";
            return false;
        }
        // A declared Null()/Trash() is an ordinary molecule in BNGL.  Only
        // fixed discard seeds (the `$Null`/`$Trash` convention) or an
        // undeclared discard name are sentinels; preserving this distinction
        // matters for models that use Null as a catalyst or observable.
        const bool allDiscard = std::all_of(
            molecules.begin(), molecules.end(), isDiscardMolecule);
        const bool hasUndeclaredDiscard = std::any_of(
            molecules.begin(), molecules.end(), [&](const auto& molecule) {
                for (int index = 0; index < s->getNumOfMoleculeTypes(); ++index) {
                    if (s->getMoleculeType(index)->getName() == molecule.name) return false;
                }
                return true;
            });
        if (allDiscard && (seed.isConstant() || hasUndeclaredDiscard)) {
            continue;
        }
        std::string diagnostic;
        int count = 0;
        std::vector<std::string> overrideKeys = {
            seed.getPattern(), seed.getGraph().get_BNG2_string()};
        if (!seed.getCompartment().empty()) {
            const auto& compartment = seed.getCompartment();
            overrideKeys.push_back("@" + compartment + "::" + seed.getPattern());
            overrideKeys.push_back("@" + compartment + ":" + seed.getPattern());
            overrideKeys.push_back(
                "@" + compartment + "::" + seed.getGraph().get_BNG2_string());
        }

        auto overrideIt = seedAmountOverrides.end();
        for (const auto& key : overrideKeys) {
            overrideIt = seedAmountOverrides.find(key);
            if (overrideIt != seedAmountOverrides.end()) break;
        }
        if (overrideIt != seedAmountOverrides.end()) {
            const double amount = overrideIt->second;
            if (!std::isfinite(amount) || amount < 0.0 ||
                amount > static_cast<double>(std::numeric_limits<int>::max()) ||
                std::floor(amount) != amount) {
                std::cerr << "[nfsim/ast] cannot map seed species '"
                          << seed.getPattern()
                          << "': action concentration must be a nonnegative integer\n";
                return false;
            }
            count = static_cast<int>(amount);
        } else if (!parseSeedAmount(seed, parameters, count, diagnostic)) {
            std::cerr << "[nfsim/ast] cannot map seed species '" << seed.getPattern()
                      << "': " << diagnostic << "\n";
            return false;
        }

        std::vector<RuntimeNames> assignments;
        if (!makeRuntimeNameAssignments(molecules, s, true, assignments, diagnostic) ||
            assignments.empty()) {
            std::cerr << "[nfsim/ast] cannot map seed species '" << seed.getPattern()
                      << "': " << diagnostic << "\n";
            return false;
        }
        const auto& runtimeNames = assignments.front();

        bool foundPopulation = false;
        bool foundParticle = false;
        std::vector<Compartment*> compartments;
        for (const auto& molecule : molecules) {
            auto* moleculeType = s->getMoleculeTypeByName(molecule.name);
            if (moleculeType == nullptr) {
                std::cerr << "[nfsim/ast] unknown seed molecule type '" << molecule.name
                          << "'\n";
                return false;
            }
            foundPopulation = foundPopulation || moleculeType->isPopulationType();
            foundParticle = foundParticle || !moleculeType->isPopulationType();
            const std::string compartmentName = molecule.node->get_compartment().empty()
                                                    ? seed.getCompartment()
                                                    : molecule.node->get_compartment();
            Compartment* compartment = nullptr;
            if (!resolveCompartment(s, compartmentName, compartment, diagnostic)) {
                std::cerr << "[nfsim/ast] cannot map seed species '" << seed.getPattern()
                          << "': " << diagnostic << "\n";
                return false;
            }
            compartments.push_back(compartment);
        }
        if (foundPopulation && foundParticle) {
            std::cerr << "[nfsim/ast] seed species mixes population and particle molecules\n";
            return false;
        }
        if (foundPopulation && molecules.size() != 1) {
            std::cerr << "[nfsim/ast] population seed species must contain one molecule\n";
            return false;
        }

        const int copies = foundPopulation ? 1 : count;
        std::vector<std::vector<Molecule*>> generated(
            molecules.size(), std::vector<Molecule*>());
        // Match NFinput::initStartSpecies' allocation order: all copies of a
        // molecule position are allocated before advancing to the next
        // position.  The order is observable through MoleculeList IDs and is
        // part of the seeded NFsim mapping stream for repeated molecules.
        for (std::size_t moleculeIndex = 0; moleculeIndex < molecules.size(); ++moleculeIndex) {
            for (int copy = 0; copy < copies; ++copy) {
                auto* moleculeType = s->getMoleculeTypeByName(molecules[moleculeIndex].name);
                auto* molecule = moleculeType->genDefaultMolecule(compartments[moleculeIndex]);
                generated[moleculeIndex].push_back(molecule);
                for (std::size_t componentIndex = 0;
                     componentIndex < molecules[moleculeIndex].components.size(); ++componentIndex) {
                    const auto& component = molecules[moleculeIndex].components[componentIndex];
                    const std::string state = graphStateToken(*component.node);
                    if (state.empty() || state == "?" || state == "*") continue;
                    const int stateValue = componentStateValue(
                        moleculeType, runtimeNames[moleculeIndex][componentIndex], state,
                        diagnostic);
                    if (stateValue < 0) {
                        std::cerr << "[nfsim/ast] cannot map seed species '"
                                  << seed.getPattern() << "': " << diagnostic << "\n";
                        return false;
                    }
                    molecule->setComponentState(
                        runtimeNames[moleculeIndex][componentIndex], stateValue);
                }
            }
        }

        for (int copy = 0; copy < copies; ++copy) {
            std::unordered_set<BNGcore::Node*> processedBonds;
            for (std::size_t moleculeIndex = 0; moleculeIndex < molecules.size(); ++moleculeIndex) {
                for (std::size_t componentIndex = 0;
                     componentIndex < molecules[moleculeIndex].components.size(); ++componentIndex) {
                    for (auto* bond : molecules[moleculeIndex].components[componentIndex].bonds) {
                        if (!processedBonds.insert(bond).second) continue;
                        if (graphBondToken(*bond) != "!+") continue;
                        std::vector<std::pair<std::size_t, std::size_t>> endpoints;
                        for (std::size_t otherMolecule = 0; otherMolecule < molecules.size(); ++otherMolecule) {
                            for (std::size_t otherComponent = 0;
                                 otherComponent < molecules[otherMolecule].components.size(); ++otherComponent) {
                                const auto& other = molecules[otherMolecule].components[otherComponent];
                                if (std::find(other.bonds.begin(), other.bonds.end(), bond) != other.bonds.end()) {
                                    endpoints.emplace_back(otherMolecule, otherComponent);
                                }
                            }
                        }
                        // The legacy XML species reader treats a one-ended
                        // numeric bond as seed metadata (numberOfBonds=1),
                        // not as a runtime bond.  This occurs in the bundled
                        // RNA NFsim fixtures.  Preserve the same open-site
                        // runtime representation while still rejecting an
                        // impossible multi-ended bond.
                        if (endpoints.size() == 1) continue;
                        if (endpoints.size() != 2) {
                            std::cerr << "[nfsim/ast] seed species has an incomplete bound bond\n";
                            return false;
                        }
                        const auto [firstMolecule, firstComponent] = endpoints[0];
                        const auto [secondMolecule, secondComponent] = endpoints[1];
                        Molecule::bind(
                            generated[firstMolecule][copy],
                            runtimeNames[firstMolecule][firstComponent],
                            generated[secondMolecule][copy],
                            runtimeNames[secondMolecule][secondComponent]);
                    }
                }
            }
        }

        if (foundPopulation) {
            if (!generated[0].front()->setPopulation(count)) {
                std::cerr << "[nfsim/ast] failed to set population seed count\n";
                return false;
            }
        }

        if (seed.isConstant()) {
            if (molecules.size() != 1 || foundPopulation) {
                std::cerr << "[nfsim/ast] fixed seed species must be one particle molecule\n";
                return false;
            }
            auto* moleculeType = s->getMoleculeTypeByName(molecules.front().name);
            moleculeType->setFixed(true, count, compartments.front());
        }
        if (verbose) {
            std::cerr << "[nfsim/ast] seed " << seed.getPattern()
                      << " count=" << count << "\n";
        }
    }
    return true;
}

bool addSpeciesFromAst(const bng::ast::Model& model, System* s,
                       const std::map<std::string, double>& parameters, bool verbose) {
    static const SeedAmountOverrides noOverrides;
    return addSpeciesFromAstWithOverrides(
        model, s, parameters, verbose, noOverrides);
}

bool addReactionRulesFromAst(const bng::ast::Model& model, System* s,
                             const std::map<std::string, double>& parameters,
                             bool blockSameComplexBinding, bool verbose,
                             int& suggestedTraversalLimit,
                             const std::filesystem::path& sourcePath) {
    if (s == nullptr) return false;

    // SPEC: NFinput::initReactionRules (NFinput.cpp:1266). This direct slice
    // covers elementary state changes, binding/unbinding, identity rules,
    // standalone product-molecule creation, explicit degradation, compartment
    // transport including MoveConnected, and the two-direction expansion of
    // reversible rules. Scoped / local rates and
    // reactant filters, bare-molecule product filters, and reversible filter
    // swapping are mapped within their bounded direct slices. Static symmetric
    // state-change and bond reaction centers are expanded when all stated
    // symmetric sites are reaction-center sites. Complex product filters and
    // unsupported modifiers remain fail-closed. Dynamic rates may inline zero-argument
    // model-function chains; unsupported composite/local forms remain gated.
    // A bounded direct Arrhenius binding slice uses NFsim's existing
    // energy-pattern expansion
    // implementation.

    for (std::size_t originalRuleOrdinal = 0;
         originalRuleOrdinal < model.getReactionRules().size();
         ++originalRuleOrdinal) {
        const auto& originalRule = model.getReactionRules()[originalRuleOrdinal];
        const auto& originalRates = originalRule.getRates();
        const bool directArrhenius =
            originalRates.size() == 1 && isArrheniusExpression(originalRates.front());
        if ((!originalRule.isBidirectional() && originalRates.size() != 1) ||
            (originalRule.isBidirectional() && originalRates.size() != 2 &&
             !directArrhenius)) {
            std::cerr << "[nfsim/ast] reaction '" << originalRule.getRuleName()
                      << "' has an invalid number of rate expressions for its directionality\n";
            return false;
        }

        if (directArrhenius) {
            if (originalRule.hasScopePrefix() ||
                hasReactionModifierPrefix(originalRule, "include_") ||
                hasReactionModifierPrefix(originalRule, "exclude_") ||
                hasReactionModifier(originalRule, "moveconnected")) {
                std::cerr << "[nfsim/ast] direct Arrhenius reaction uses an unsupported modifier\n";
                return false;
            }
            const bool onlyStateChange =
                !originalRule.getOperations().empty() && std::all_of(
                    originalRule.getOperations().begin(), originalRule.getOperations().end(),
                    [](const auto& operation) {
                        return operation.type ==
                               bng::ast::ReactionRule::TransformOp::Type::ChangeState;
                    });
            const bool added = onlyStateChange
                                   ? addDirectArrheniusStateChange(
                                         originalRule, s, parameters, blockSameComplexBinding,
                                         verbose, suggestedTraversalLimit)
                                   : addDirectArrheniusBinding(
                                         originalRule, s, parameters, blockSameComplexBinding,
                                         verbose, suggestedTraversalLimit);
            if (!added) {
                return false;
            }
            continue;
        }

        // The AST stores a reversible rule as one pair of patterns and two
        // rates.  Construct the reverse direction through the same
        // ReactionRule initializer so its component/bond/product mappings are
        // recomputed with the reversed pattern indices instead of being
        // guessed in this adapter.
        std::unique_ptr<bng::ast::ReactionRule> reverseRule;
        if (originalRule.isBidirectional()) {
            reverseRule = std::make_unique<bng::ast::ReactionRule>(
                originalRule.getRuleName() + "_reverse",
                originalRule.getLabel(),
                originalRule.getProducts(),
                originalRule.getReactants(),
                std::vector<bng::ast::Expression>{originalRates[1]},
                reverseReactionFilterModifiers(originalRule.getModifiers()),
                false,
                originalRule.getProductPatterns(),
                originalRule.getReactantPatterns());
        }

        std::vector<const bng::ast::ReactionRule*> directions{&originalRule};
        if (reverseRule != nullptr) directions.push_back(reverseRule.get());
        for (std::size_t directionOrdinal = 0;
             directionOrdinal < directions.size(); ++directionOrdinal) {
            const auto* rulePtr = directions[directionOrdinal];
            const auto& rule = *rulePtr;
            bool productFiltersPass = true;
            std::string productFilterDiagnostic;
            if (!validateProductFiltersFromAst(
                    rule, model, productFiltersPass, productFilterDiagnostic)) {
                std::cerr << "[nfsim/ast] cannot map reaction '" << rule.getRuleName()
                          << "': " << productFilterDiagnostic << "\n";
                return false;
            }
            if (!productFiltersPass) continue;
            const auto& reactantPatterns = rule.getReactantPatterns();
            const auto& productPatterns = rule.getProductPatterns();
            const auto& rates = rule.getRates();
            const bng::ast::Function* rateFunction =
                rates.empty() ? nullptr : getModelFunction(model, rates.front().name());
            const bool localFunctionRate =
                !rates.empty() && rateFunction != nullptr && !rateFunction->getArgs().empty() &&
                (rates.front().kind() == bng::ast::ExpressionKind::ObservableRef ||
                 rates.front().kind() == bng::ast::ExpressionKind::Function) &&
                rates.front().args().size() == rateFunction->getArgs().size();
            const bool explicitFunctionProductRate =
                !rates.empty() &&
                rates.front().kind() == bng::ast::ExpressionKind::Function &&
                lowerCase(rates.front().name()) == "functionproduct" &&
                rates.front().args().size() == 2;
            const bool rawFunctionProductShape =
                !rates.empty() &&
                rates.front().kind() == bng::ast::ExpressionKind::Binary &&
                rates.front().name() == "*" && rates.front().args().size() == 2;
            bool functionProductRate = explicitFunctionProductRate;
            FunctionProductOperand functionProductOperand1;
            FunctionProductOperand functionProductOperand2;
            if (functionProductRate) {
                std::string productDiagnostic;
                if (!parseFunctionProductOperand(
                        model, rates.front().args()[0], functionProductOperand1,
                        productDiagnostic) ||
                    !parseFunctionProductOperand(
                        model, rates.front().args()[1], functionProductOperand2,
                        productDiagnostic)) {
                    std::cerr << "[nfsim/ast] reaction '" << rule.getRuleName()
                              << "' cannot use FunctionProduct: " << productDiagnostic
                              << "\n";
                    return false;
                }
            } else if (rawFunctionProductShape) {
                // BNG2 emits a raw multiplication for DOR2 local functions
                // (for example, rateA(x)*rateB(y)), while the explicit
                // FunctionProduct form is also accepted as a bounded bridge.
                // Recognize only the exact two one-argument local-function
                // shape so ordinary arithmetic still follows the generic
                // dynamic-rate path.
                std::string productDiagnostic;
                if (parseFunctionProductOperand(
                        model, rates.front().args()[0], functionProductOperand1,
                        productDiagnostic) &&
                    parseFunctionProductOperand(
                        model, rates.front().args()[1], functionProductOperand2,
                        productDiagnostic)) {
                    functionProductRate = true;
                }
            }
            const auto hasRateScope = [&](const std::string& argument) {
                return std::any_of(
                    rule.getReactants().begin(), rule.getReactants().end(),
                    [&](const auto& reactant) { return hasScopedArgument(reactant, argument); });
            };
            const bool localFunctionScopeAvailable =
                !localFunctionRate || std::all_of(
                    rates.front().args().begin(), rates.front().args().end(),
                    [&](const auto& argument) {
                        return argument.kind() == bng::ast::ExpressionKind::Identifier &&
                               hasRateScope(argument.name());
                    });
            const bool functionProductScopeAvailable =
                !functionProductRate ||
                (hasRateScope(functionProductOperand1.argument) &&
                 hasRateScope(functionProductOperand2.argument));
            const auto hasScopedModelFunctionCall =
                [&](const auto& expression, const auto& self) -> bool {
                using ExpressionKind = bng::ast::ExpressionKind;
                if ((expression.kind() == ExpressionKind::Function ||
                     expression.kind() == ExpressionKind::ObservableRef) &&
                    !expression.args().empty()) {
                    const auto* function = getModelFunction(model, expression.name());
                    if (function != nullptr &&
                        function->getArgs().size() == expression.args().size() &&
                        std::all_of(
                            expression.args().begin(), expression.args().end(),
                            [&](const auto& argument) {
                                return argument.kind() == ExpressionKind::Identifier &&
                                       hasRateScope(argument.name());
                            })) {
                        return true;
                    }
                }
                return std::any_of(
                    expression.args().begin(), expression.args().end(),
                    [&](const auto& child) { return self(child, self); });
            };
            // A species-scoped rule may put a local-function call inside
            // arithmetic (for example ``kr*(1-pOn(x))``).  That is not the
            // narrow ``f(x)`` localFunctionRate shape, but the generic dynamic
            // adapter can preserve and bind the scoped argument as a DOR rate.
            const bool dynamicScopedFunctionAvailable =
                !rates.empty() &&
                hasScopedModelFunctionCall(rates.front(), hasScopedModelFunctionCall);
            if ((rule.hasScopePrefix() && !localFunctionRate && !functionProductRate &&
                 !dynamicScopedFunctionAvailable) ||
                (localFunctionRate && !localFunctionScopeAvailable) ||
                (functionProductRate && !functionProductScopeAvailable) || rates.empty() ||
                (reactantPatterns.empty() && productPatterns.empty())) {
                std::cerr << "[nfsim/ast] reaction '" << rule.getRuleName()
                          << "' requires unsupported scope, empty reaction, or missing-rate handling\n";
                return false;
            }
            if (hasUnsupportedReactionFilterModifier(rule)) {
                std::cerr << "[nfsim/ast] reaction '" << rule.getRuleName()
                          << "' uses an unsupported reaction modifier\n";
                return false;
            }
            if (reactantPatterns.size() != rule.getReactants().size() &&
                !rule.getReactants().empty()) {
                std::cerr << "[nfsim/ast] reaction '" << rule.getRuleName()
                          << "' has an unsupported non-species reactant\n";
                return false;
            }

            std::string symmetricDiagnostic;
            // The AST keeps both rates on a bidirectional rule.  Symmetry
            // expansion creates one NFcore reaction per direction, so present
            // the forward helper with the same single-rate view used by the
            // synthetic reverse rule below.  Leave the original rule intact
            // for the ordinary direct path when this helper is not applicable.
            std::unique_ptr<bng::ast::ReactionRule> singleDirectionRule;
            const auto* symmetryRule = &rule;
            if (rule.isBidirectional()) {
                if (rule.getRates().size() != 2) {
                    std::cerr << "[nfsim/ast] reaction '" << rule.getRuleName()
                              << "' has an invalid bidirectional rate list\n";
                    return false;
                }
                singleDirectionRule = std::make_unique<bng::ast::ReactionRule>(
                    rule.getRuleName(), rule.getLabel(), rule.getReactants(),
                    rule.getProducts(),
                    std::vector<bng::ast::Expression>{rule.getRates().front()},
                    rule.getModifiers(), false, rule.getReactantPatterns(),
                    rule.getProductPatterns());
                symmetryRule = singleDirectionRule.get();
            }
            const auto symmetricResult = addSymmetricStateChangeReactionRulesFromAst(
                *symmetryRule, model, s, parameters, blockSameComplexBinding, verbose,
                suggestedTraversalLimit, sourcePath,
                originalRuleOrdinal * 2 + directionOrdinal, symmetricDiagnostic);
            if (symmetricResult == SymmetricReactionExpansionResult::Added) continue;
            if (symmetricResult == SymmetricReactionExpansionResult::Error) {
                std::cerr << "[nfsim/ast] cannot map reaction '" << rule.getRuleName()
                          << "': "
                          << (symmetricDiagnostic.empty()
                                  ? "symmetric reaction-center expansion failed"
                                  : symmetricDiagnostic)
                          << "\n";
                return false;
            }
            symmetricDiagnostic.clear();
            const auto symmetricBondResult = addSymmetricBondReactionRulesFromAst(
                *symmetryRule, model, s, parameters, blockSameComplexBinding, verbose,
                suggestedTraversalLimit, sourcePath,
                originalRuleOrdinal * 2 + directionOrdinal, symmetricDiagnostic);
            if (symmetricBondResult == SymmetricReactionExpansionResult::Added) continue;
            if (symmetricBondResult == SymmetricReactionExpansionResult::Error) {
                std::cerr << "[nfsim/ast] cannot map reaction '" << rule.getRuleName()
                          << "': "
                          << (symmetricDiagnostic.empty()
                                  ? "symmetric bond expansion failed"
                                  : symmetricDiagnostic)
                          << "\n";
                return false;
            }

        std::vector<std::vector<TemplateMolecule*>> patternTemplates;
        std::vector<TemplateMolecule*> reactantRoots;
        bool hasDisjointSets = false;
        for (std::size_t patternIndex = 0; patternIndex < reactantPatterns.size(); ++patternIndex) {
            std::vector<std::vector<TemplateMolecule*>> builds;
            std::string diagnostic;
            if (!buildTemplatePatterns(
                    reactantPatterns[patternIndex].getGraph(),
                    reactantPatterns[patternIndex].getCompartment(),
                    s, false, builds, hasDisjointSets, suggestedTraversalLimit, diagnostic) ||
                builds.size() != 1 || builds.front().empty()) {
                std::cerr << "[nfsim/ast] cannot map reaction '" << rule.getRuleName()
                          << "': " << (diagnostic.empty() ? "invalid reactant pattern" : diagnostic)
                          << "\n";
                return false;
            }
            reactantRoots.push_back(builds.front().front());
            patternTemplates.push_back(std::move(builds.front()));
        }

        bool ok = true;
        std::string diagnostic;
        const auto& operations = rule.getOperations();

        // AddMolecule transforms need their extra mapping sets allocated before
        // the TransformationSet is finalized.  Product-side bond operations are
        // installed after these templates exist, so a newly created molecule can
        // bind to a reactant or to another newly created molecule.
        std::vector<DirectProductMolecule> directProducts;
        std::vector<TemplateMolecule*> addMoleculeTemplates;
        std::vector<MoleculeCreator*> moleculeCreators;
        std::map<bng::ast::ReactionRule::ComponentRef, std::size_t> addedProductIndexes;
        auto addDirectProduct = [&](const bng::ast::ReactionRule::ComponentRef& productRef) {
            if (productRef.patternIndex >= productPatterns.size()) {
                diagnostic = "AddMolecule refers to an unknown product pattern";
                return false;
            }
            const auto productMolecules = collectGraphMolecules(
                productPatterns[productRef.patternIndex].getGraph());
            if (productRef.moleculeIndex >= productMolecules.size()) {
                diagnostic = "AddMolecule refers to an unknown product molecule";
                return false;
            }
            // Null/Trash are NFsim's degradation sentinels, not real molecule
            // types.  The XML loader drops these product entries and keeps the
            // corresponding DeleteMolecule operation.
            const auto& productMolecule = productMolecules[productRef.moleculeIndex];
            bool declaredProductType = false;
            for (int index = 0; index < s->getNumOfMoleculeTypes(); ++index) {
                if (s->getMoleculeType(index)->getName() == productMolecule.name) {
                    declaredProductType = true;
                    break;
                }
            }
            if (isDiscardMolecule(productMolecule) && !declaredProductType) {
                return true;
            }
            if (!addedProductIndexes.emplace(productRef, directProducts.size()).second) {
                diagnostic = "duplicate AddMolecule operation for a product molecule";
                return false;
            }
            DirectProductMolecule product;
            if (!buildDirectProductMolecule(
                    productPatterns[productRef.patternIndex], productRef.moleculeIndex,
                    s, product, diagnostic)) {
                return false;
            }
            directProducts.push_back(product);
            addMoleculeTemplates.push_back(product.templateMolecule);
            moleculeCreators.push_back(product.creator);
            return true;
        };
        for (const auto& operation : operations) {
            if (operation.type == bng::ast::ReactionRule::TransformOp::Type::AddMolecule) {
                const bng::ast::ReactionRule::ComponentRef productRef{
                    operation.patternIndex, operation.moleculeIndex, 0};
                if (!addDirectProduct(productRef)) {
                    ok = false;
                    break;
                }
            }
        }
        if (ok && reactantPatterns.empty() && addMoleculeTemplates.empty()) {
            for (std::size_t patternIndex = 0;
                 patternIndex < productPatterns.size() && ok; ++patternIndex) {
                const auto molecules = collectGraphMolecules(
                    productPatterns[patternIndex].getGraph());
                for (std::size_t moleculeIndex = 0;
                     moleculeIndex < molecules.size(); ++moleculeIndex) {
                    if (!addDirectProduct({patternIndex, moleculeIndex, 0})) {
                        ok = false;
                        break;
                    }
                }
            }
        }

        auto cleanupDirectProducts = [&]() {
            for (auto& product : directProducts) {
                delete product.creator;
                delete product.templateMolecule;
                product.creator = nullptr;
                product.templateMolecule = nullptr;
            }
            directProducts.clear();
            addMoleculeTemplates.clear();
            moleculeCreators.clear();
        };

        TransformationSet* transformationSet = nullptr;
        if (ok) {
            if (addMoleculeTemplates.empty()) {
                transformationSet = new TransformationSet(reactantRoots);
            } else {
                transformationSet = new TransformationSet(reactantRoots, addMoleculeTemplates);
            }
            transformationSet->setComplexBookkeeping(blockSameComplexBinding || hasDisjointSets);
            transformationSet->setNumProductPatterns(
                static_cast<unsigned int>(productPatterns.size()));
            for (auto* creator : moleculeCreators) {
                if (!transformationSet->addAddMolecule(creator)) {
                    diagnostic = "could not add product-molecule creator";
                    ok = false;
                    break;
                }
            }
        }
        if (ok && !addReactantFiltersFromAst(
                      rule, model, s, transformationSet, reactantRoots, hasDisjointSets,
                      suggestedTraversalLimit, diagnostic)) {
            ok = false;
        }
        if (ok) {
            transformationSet->setComplexBookkeeping(blockSameComplexBinding || hasDisjointSets);
        }

        // Reconstruct the AST-side product mapping used by ReactionRule's
        // cross-bond bookkeeping.  The public ReactionRule API exposes the
        // elementary operations but not its private cross-bond tables.
        std::map<bng::ast::ReactionRule::ComponentRef,
                 bng::ast::ReactionRule::ComponentRef> productToReactant;
        std::map<bng::ast::ReactionRule::ComponentRef,
                 bng::ast::ReactionRule::ComponentRef> productMoleculeToReactant;
        if (ok && !buildProductComponentMapping(
                      rule, productToReactant, productMoleculeToReactant, diagnostic)) {
            ok = false;
        }

        if (ok) {
            const auto reactantMolecules = collectRuleGraphMolecules(reactantPatterns);
            const auto productMolecules = collectRuleGraphMolecules(productPatterns);
            for (const auto& moleculeMapping : productMoleculeToReactant) {
                const auto& productRef = moleculeMapping.first;
                const auto& reactantRef = moleculeMapping.second;
                const auto productPatternIndex = productRef.patternIndex;
                const auto productMoleculeIndex = productRef.moleculeIndex;
                const auto reactantPatternIndex = reactantRef.patternIndex;
                const auto reactantMoleculeIndex = reactantRef.moleculeIndex;
                const auto productIt = std::find_if(
                    productMolecules.begin(), productMolecules.end(),
                    [productPatternIndex, productMoleculeIndex](const auto& molecule) {
                        return molecule.patternIndex == productPatternIndex &&
                               molecule.moleculeIndex == productMoleculeIndex;
                    });
                const auto reactantIt = std::find_if(
                    reactantMolecules.begin(), reactantMolecules.end(),
                    [reactantPatternIndex, reactantMoleculeIndex](const auto& molecule) {
                        return molecule.patternIndex == reactantPatternIndex &&
                               molecule.moleculeIndex == reactantMoleculeIndex;
                    });
                if (productIt == productMolecules.end() ||
                    reactantIt == reactantMolecules.end()) {
                    diagnostic = "compartment transport refers to an unknown molecule";
                    ok = false;
                    break;
                }

                const std::string productCompartment = graphMoleculeCompartment(
                    productPatterns[productIt->patternIndex], productIt->molecule);
                const std::string reactantCompartment = graphMoleculeCompartment(
                    reactantPatterns[reactantIt->patternIndex], reactantIt->molecule);
                if (productCompartment.empty() ||
                    productCompartment == reactantCompartment) {
                    continue;
                }

                // MoveTransformation invalidates the affected complex's
                // canonical label.  NFsim's legacy implementation therefore
                // expects complex bookkeeping even for an otherwise
                // molecule-only model.
                s->setUsingComplex(true);
                Compartment* destination = nullptr;
                if (!resolveCompartment(
                        s, productCompartment, destination, diagnostic)) {
                    ok = false;
                    break;
                }
                TemplateMolecule* templateMolecule = nullptr;
                if (!templateForReactionRef(
                        reactantRef, patternTemplates, templateMolecule, diagnostic) ||
                    !transformationSet->addMoveTransform(
                        templateMolecule, destination,
                        hasReactionModifier(rule, "moveconnected"))) {
                    if (diagnostic.empty()) {
                        diagnostic = "could not add direct compartment transport";
                    }
                    ok = false;
                    break;
                }
            }
        }

        std::map<bng::ast::ReactionRule::ComponentRef,
                 std::pair<TemplateMolecule*, std::string>> addedProductComponents;
        if (ok) {
            for (const auto& [productRef, productIndex] : addedProductIndexes) {
                const auto& operationProduct = directProducts.at(productIndex);
                const auto molecules = collectGraphMolecules(
                    productPatterns[productRef.patternIndex].getGraph());
                if (productRef.moleculeIndex >= molecules.size()) {
                    diagnostic = "AddMolecule refers to an unknown product molecule";
                    ok = false;
                    break;
                }
                const auto& graphMolecule = molecules[productRef.moleculeIndex];
                for (std::size_t componentIndex = 0;
                     componentIndex < graphMolecule.components.size(); ++componentIndex) {
                    addedProductComponents.emplace(
                        bng::ast::ReactionRule::ComponentRef{
                            productRef.patternIndex, productRef.moleculeIndex, componentIndex},
                        std::make_pair(operationProduct.templateMolecule,
                                       operationProduct.runtimeComponentNames.at(componentIndex)));
                }
            }
        }

        auto mapComponent = [&](const bng::ast::ReactionRule::ComponentRef& ref,
                                TemplateMolecule*& templateMolecule,
                                std::string& componentName) -> bool {
            if (!templateForReactionRef(ref, patternTemplates, templateMolecule, diagnostic) ||
                !componentNameForReactionRef(rule, ref, componentName, diagnostic)) {
                return false;
            }
            if (templateMolecule->getMoleculeType()->isEquivalentComponent(componentName)) {
                diagnostic = "symmetric reaction-center components require permutation expansion";
                return false;
            }
            return true;
        };

        // NFsim requires unbinding before binding when a rule does both.
        if (ok) {
            for (const auto& operation : operations) {
                if (operation.type != bng::ast::ReactionRule::TransformOp::Type::DeleteBond) continue;
                TemplateMolecule* lhs = nullptr;
                TemplateMolecule* rhs = nullptr;
                std::string lhsName;
                std::string rhsName;
                if (!mapComponent(operation.source, lhs, lhsName) ||
                    !mapComponent(operation.partner, rhs, rhsName) ||
                    !transformationSet->addUnbindingTransform(lhs, lhsName, rhs, rhsName)) {
                    ok = false;
                    break;
                }
            }
        }
        if (ok) {
            for (const auto& operation : operations) {
                if (operation.type != bng::ast::ReactionRule::TransformOp::Type::AddBond) continue;
                TemplateMolecule* lhs = nullptr;
                TemplateMolecule* rhs = nullptr;
                std::string lhsName;
                std::string rhsName;
                if (!mapComponent(operation.source, lhs, lhsName) ||
                    !mapComponent(operation.partner, rhs, rhsName) ||
                    !transformationSet->addBindingTransform(lhs, lhsName, rhs, rhsName)) {
                    ok = false;
                    break;
                }
            }
        }
        if (ok && !addedProductComponents.empty()) {
            // AddBond operations only contain two reactant-mapped components.
            // Bonds involving an AddMolecule are represented by the product
            // graph, so inspect those edges and use the special transform that
            // skips pre-creation null-condition checks.
            std::unordered_map<BNGcore::Node*,
                               std::vector<bng::ast::ReactionRule::ComponentRef>> productBondEndpoints;
            for (std::size_t patternIndex = 0;
                 patternIndex < productPatterns.size(); ++patternIndex) {
                const auto molecules = collectGraphMolecules(
                    productPatterns[patternIndex].getGraph());
                for (std::size_t moleculeIndex = 0;
                     moleculeIndex < molecules.size(); ++moleculeIndex) {
                    const auto& molecule = molecules[moleculeIndex];
                    for (std::size_t componentIndex = 0;
                         componentIndex < molecule.components.size(); ++componentIndex) {
                        const auto& component = molecule.components[componentIndex];
                        for (auto* bond : component.bonds) {
                            if (graphBondToken(*bond) != "!+") continue;
                            productBondEndpoints[bond].push_back(
                                bng::ast::ReactionRule::ComponentRef{
                                    patternIndex, moleculeIndex, componentIndex});
                        }
                    }
                }
            }

            for (const auto& [bond, endpoints] : productBondEndpoints) {
                (void)bond;
                if (endpoints.size() != 2) {
                    diagnostic = "product bond does not connect exactly two components";
                    ok = false;
                    break;
                }
                const auto firstAdded = addedProductComponents.find(endpoints[0]);
                const auto secondAdded = addedProductComponents.find(endpoints[1]);
                if (firstAdded == addedProductComponents.end() &&
                    secondAdded == addedProductComponents.end()) {
                    continue;
                }
                if (firstAdded != addedProductComponents.end() &&
                    secondAdded != addedProductComponents.end()) {
                    if (!transformationSet->addNewMoleculeBindingTransform(
                            firstAdded->second.first, firstAdded->second.second,
                            secondAdded->second.first, secondAdded->second.second)) {
                        diagnostic = "could not add binding between product molecules";
                        ok = false;
                        break;
                    }
                    continue;
                }

                const auto added = firstAdded != addedProductComponents.end()
                                       ? firstAdded : secondAdded;
                const auto existingRef = firstAdded != addedProductComponents.end()
                                             ? endpoints[1] : endpoints[0];
                const auto mapped = productToReactant.find(existingRef);
                if (mapped == productToReactant.end()) {
                    diagnostic = "product bond refers to an unmapped existing component";
                    ok = false;
                    break;
                }
                TemplateMolecule* existingTemplate = nullptr;
                std::string existingName;
                if (!templateForReactionRef(
                        mapped->second, patternTemplates, existingTemplate, diagnostic) ||
                    !componentNameForReactionRef(
                        rule, mapped->second, existingName, diagnostic) ||
                    existingTemplate->getMoleculeType()->isEquivalentComponent(existingName)) {
                    if (diagnostic.empty()) {
                        diagnostic = "symmetric existing component in product bond is unsupported";
                    }
                    ok = false;
                    break;
                }
                // A product bond to an existing molecule requires the
                // reactant site to be available.  New-molecule binding uses a
                // deferred transform and cannot preflight this condition
                // after the product molecule is created, so encode the
                // availability on the reactant template itself.
                existingTemplate->addEmptyComponent(existingName);
                if (!transformationSet->addNewMoleculeBindingTransform(
                        existingTemplate, existingName,
                        added->second.first, added->second.second)) {
                    diagnostic = "could not add binding between reactant and product molecule";
                    ok = false;
                    break;
                }
            }
        }
        if (ok) {
            for (const auto& operation : operations) {
                if (operation.type != bng::ast::ReactionRule::TransformOp::Type::ChangeState) continue;
                TemplateMolecule* target = nullptr;
                std::string componentName;
                if (!mapComponent(operation.source, target, componentName)) {
                    ok = false;
                    break;
                }
                bool applied = false;
                if (operation.newState == "PLUS") {
                    applied = transformationSet->addIncrementStateTransform(target, componentName);
                } else if (operation.newState == "MINUS") {
                    applied = transformationSet->addDecrementStateTransform(target, componentName);
                } else {
                    applied = transformationSet->addStateChangeTransform(
                        target, componentName, operation.newState);
                }
                if (!applied) {
                    diagnostic = "could not add state-change transformation";
                    ok = false;
                    break;
                }
            }
        }

        const bool deleteMolecules = hasReactionModifier(rule, "deletemolecules");
        if (ok) {
            if (productPatterns.empty() && operations.empty()) {
                // `A(...) -> 0` has no product graph for ReactionRule to diff.
                // Match the XML loader's complete-species versus
                // DeleteMolecules distinction explicitly.
                for (auto* root : reactantRoots) {
                    if (root->getMoleculeType()->isPopulationType()) {
                        ok = transformationSet->addDecrementPopulation(root);
                    } else {
                        ok = transformationSet->addDeleteMolecule(
                            root, deleteMolecules
                                      ? TransformationFactory::DELETE_MOLECULES
                                      : TransformationFactory::COMPLETE_SPECIES_REMOVAL);
                    }
                    if (!ok) break;
                }
            } else {
                for (const auto& operation : operations) {
                    if (operation.type != bng::ast::ReactionRule::TransformOp::Type::DeleteMolecule) continue;
                    TemplateMolecule* target = nullptr;
                    if (!templateForReactionRef(
                            {operation.patternIndex, operation.moleculeIndex, 0},
                            patternTemplates, target, diagnostic)) {
                        ok = false;
                        break;
                    }
                    if (target->getMoleculeType()->isPopulationType()) {
                        ok = transformationSet->addDecrementPopulation(target);
                    } else {
                        ok = transformationSet->addDeleteMolecule(
                            target, deleteMolecules
                                      ? TransformationFactory::DELETE_MOLECULES
                                      : TransformationFactory::COMPLETE_SPECIES_REMOVAL);
                    }
                    if (!ok) break;
                }
            }
        }

        if (!ok) {
            std::cerr << "[nfsim/ast] cannot map reaction '" << rule.getRuleName()
                      << "': " << (diagnostic.empty() ? "NFsim transformation rejected" : diagnostic)
                      << "\n";
            delete transformationSet;
            transformationSet = nullptr;
            cleanupDirectProducts();
            return false;
        }

        std::vector<std::string> localFunctionArgumentNames;
        std::vector<std::string> functionProductArguments1;
        std::vector<std::string> functionProductArguments2;
        std::size_t functionProductPattern1 = reactantRoots.size();
        std::size_t functionProductPattern2 = reactantRoots.size();
        std::size_t localFunctionPattern = reactantRoots.size();
        const auto mapFunctionProductArgument =
            [&](const FunctionProductOperand& operand,
                std::vector<std::string>& argumentNames,
                std::size_t& matchingPattern) {
                matchingPattern = reactantRoots.size();
                for (std::size_t patternIndex = 0;
                     patternIndex < reactantRoots.size(); ++patternIndex) {
                    if (patternIndex >= rule.getReactants().size()) continue;
                    if (!hasScopedArgument(
                            rule.getReactants()[patternIndex], operand.argument)) {
                        continue;
                    }
                    if (matchingPattern != reactantRoots.size()) {
                        diagnostic = "a FunctionProduct scope identifier refers to multiple reactants";
                        return false;
                    }
                    matchingPattern = patternIndex;
                }
                if (matchingPattern == reactantRoots.size()) {
                    diagnostic = "FunctionProduct scope identifier '" + operand.argument +
                                 "' has no matching reactant";
                    return false;
                }
                if (reactantRoots[matchingPattern]->getMoleculeType()->isPopulationType()) {
                    diagnostic = "FunctionProduct cannot scope population reactants";
                    return false;
                }
                const int matchingScope = hasSpeciesScopedArgument(
                    rule.getReactants()[matchingPattern], operand.argument)
                    ? LocalFunction::SPECIES
                    : LocalFunction::MOLECULE;
                if (!transformationSet->addLocalFunctionReference(
                        reactantRoots[matchingPattern], operand.argument, matchingScope)) {
                    diagnostic = "could not add FunctionProduct scope reference";
                    return false;
                }
                argumentNames.push_back(operand.argument);
                return true;
            };
        const auto mapLocalFunctionArgument = [&](const std::string& argumentName) {
            std::size_t matchingPattern = reactantRoots.size();
            int matchingScope = LocalFunction::MOLECULE;
            for (std::size_t patternIndex = 0;
                 patternIndex < reactantRoots.size(); ++patternIndex) {
                if (patternIndex >= rule.getReactants().size()) continue;
                if (!hasScopedArgument(
                        rule.getReactants()[patternIndex], argumentName)) {
                    continue;
                }
                if (matchingPattern != reactantRoots.size()) {
                    diagnostic = "a local-function scope identifier refers to multiple reactants";
                    return false;
                }
                matchingPattern = patternIndex;
                if (hasSpeciesScopedArgument(
                        rule.getReactants()[patternIndex], argumentName)) {
                    matchingScope = LocalFunction::SPECIES;
                }
            }
            if (matchingPattern == reactantRoots.size()) {
                diagnostic = "local-function scope identifier '" + argumentName +
                             "' has no matching reactant";
                return false;
            }
            if (localFunctionPattern == reactantRoots.size()) {
                localFunctionPattern = matchingPattern;
            } else if (localFunctionPattern != matchingPattern) {
                diagnostic = "local-function scope identifiers must refer to one reactant";
                return false;
            }
            if (reactantRoots[matchingPattern]->getMoleculeType()->isPopulationType()) {
                diagnostic = "local functions cannot scope population reactants";
                return false;
            }
            if (std::find(
                    localFunctionArgumentNames.begin(), localFunctionArgumentNames.end(),
                    argumentName) != localFunctionArgumentNames.end()) {
                return true;
            }
            if (!transformationSet->addLocalFunctionReference(
                    reactantRoots[matchingPattern], argumentName, matchingScope)) {
                diagnostic = "could not add local-function scope reference";
                return false;
            }
            localFunctionArgumentNames.push_back(argumentName);
            return true;
        };
        if (functionProductRate) {
            ok = mapFunctionProductArgument(
                     functionProductOperand1, functionProductArguments1,
                     functionProductPattern1) &&
                 mapFunctionProductArgument(
                     functionProductOperand2, functionProductArguments2,
                     functionProductPattern2);
            if (ok && functionProductPattern1 == functionProductPattern2) {
                diagnostic = "FunctionProduct requires two different scoped reactants";
                ok = false;
            }
        }
        if (localFunctionRate) {
            const auto& rate = rates.front();
            for (const auto& argument : rate.args()) {
                if (argument.kind() != bng::ast::ExpressionKind::Identifier) {
                    diagnostic = "local-function rate arguments must be scope identifiers";
                    ok = false;
                    break;
                }
                if (!mapLocalFunctionArgument(argument.name())) {
                    ok = false;
                    break;
                }
            }
        }
        if (!ok) {
            std::cerr << "[nfsim/ast] cannot map reaction '" << rule.getRuleName()
                      << "': " << diagnostic << "\n";
            delete transformationSet;
            transformationSet = nullptr;
            cleanupDirectProducts();
            return false;
        }

        const auto& rate = rates.front();
        ReactionClass* reaction = nullptr;
        std::string rateParameterName;
        const bool michaelisMenten =
            rate.kind() == bng::ast::ExpressionKind::Function &&
            (lowerCase(rate.name()) == "mm") && rate.args().size() == 2;
        const bool saturationRate =
            rate.kind() == bng::ast::ExpressionKind::Function &&
            lowerCase(rate.name()) == "sat";
        const bool hillRate =
            rate.kind() == bng::ast::ExpressionKind::Function &&
            lowerCase(rate.name()) == "hill";
        if ((michaelisMenten || saturationRate || hillRate) &&
            hasReactionModifier(rule, "totalrate")) {
            std::cerr << "[nfsim/ast] reaction '" << rule.getRuleName()
                      << "' uses a built-in saturating rate with unsupported TotalRate\n";
            delete transformationSet;
            return false;
        }
        const bool namedFunction =
            (rate.kind() == bng::ast::ExpressionKind::Identifier ||
             rate.kind() == bng::ast::ExpressionKind::Function ||
             rate.kind() == bng::ast::ExpressionKind::ObservableRef) &&
            hasModelFunction(model, rate.name());
        if (michaelisMenten) {
            if (reactantRoots.size() != 2) {
                std::cerr << "[nfsim/ast] reaction '" << rule.getRuleName()
                          << "' uses MM but does not have exactly two reactants\n";
                delete transformationSet;
                return false;
            }
            double kcat = 0.0;
            double km = 0.0;
            if (!evaluateStaticReactionRate(rate.args()[0], parameters, kcat, diagnostic) ||
                !evaluateStaticReactionRate(rate.args()[1], parameters, km, diagnostic) ||
                km < 0.0) {
                if (diagnostic.empty()) diagnostic = "MM constants must be nonnegative";
                std::cerr << "[nfsim/ast] cannot map reaction '" << rule.getRuleName()
                          << "': " << diagnostic << "\n";
                delete transformationSet;
                return false;
            }
            transformationSet->finalize();
            reaction = new MMRxnClass(rule.getRuleName(), kcat, km, transformationSet, s);
        } else if (saturationRate || hillRate) {
            if (reactantRoots.empty()) {
                std::cerr << "[nfsim/ast] reaction '" << rule.getRuleName()
                          << "' uses a saturating rate without reactants\n";
                delete transformationSet;
                return false;
            }
            if ((saturationRate &&
                 (rate.args().size() < 2 ||
                  rate.args().size() > reactantRoots.size() + 1)) ||
                (hillRate && rate.args().size() != 3)) {
                std::cerr << "[nfsim/ast] reaction '" << rule.getRuleName()
                          << "' has invalid " << (saturationRate ? "Sat" : "Hill")
                          << " constants for its reactants\n";
                delete transformationSet;
                return false;
            }
            std::vector<double> constants;
            constants.reserve(rate.args().size());
            for (const auto& argument : rate.args()) {
                double value = 0.0;
                if (!evaluateStaticReactionRate(argument, parameters, value, diagnostic)) {
                    std::cerr << "[nfsim/ast] cannot map reaction '" << rule.getRuleName()
                              << "': " << diagnostic << "\n";
                    delete transformationSet;
                    return false;
                }
                constants.push_back(value);
            }
            if (saturationRate) {
                transformationSet->finalize();
                reaction = new SatRxnClass(
                    rule.getRuleName(), std::move(constants), transformationSet, s);
            } else {
                transformationSet->finalize();
                reaction = new HillRxnClass(
                    rule.getRuleName(), constants[0], constants[1], constants[2],
                    transformationSet, s);
            }
        } else if (functionProductRate) {
            auto* composite1 = s->getCompositeFunctionByName(functionProductOperand1.name);
            auto* composite2 = s->getCompositeFunctionByName(functionProductOperand2.name);
            if (composite1 == nullptr || composite2 == nullptr ||
                functionProductArguments1.empty() || functionProductArguments2.empty()) {
                std::cerr << "[nfsim/ast] reaction '" << rule.getRuleName()
                          << "' has an unregistered FunctionProduct operand\n";
                delete transformationSet;
                return false;
            }
            transformationSet->finalize();
            reaction = new DOR2RxnClass(
                rule.getRuleName(), 1.0, "", transformationSet, composite1, composite2,
                functionProductArguments1, functionProductArguments2, s);
        } else if (localFunctionRate) {
            auto* composite = s->getCompositeFunctionByName(rate.name());
            if (composite == nullptr || localFunctionArgumentNames.empty()) {
                std::cerr << "[nfsim/ast] reaction '" << rule.getRuleName()
                          << "' has an unregistered local-function rate\n";
                delete transformationSet;
                return false;
            }
            transformationSet->finalize();
            reaction = new DORRxnClass(
                rule.getRuleName(), 1.0, "", transformationSet, composite,
                localFunctionArgumentNames, s);
        } else if (namedFunction) {
            auto* global = s->getGlobalFunctionByName(rate.name());
            auto* composite = s->getCompositeFunctionByName(rate.name());
            if ((rate.kind() == bng::ast::ExpressionKind::Function ||
                 rate.kind() == bng::ast::ExpressionKind::ObservableRef) &&
                !rate.args().empty()) {
                std::cerr << "[nfsim/ast] reaction '" << rule.getRuleName()
                          << "' has an unsupported rate function\n";
                delete transformationSet;
                return false;
            }
            transformationSet->finalize();
            if (global != nullptr) {
                reaction = new FunctionalRxnClass(
                    rule.getRuleName(), global, transformationSet, s);
            } else if (composite != nullptr) {
                reaction = new FunctionalRxnClass(
                    rule.getRuleName(), composite, transformationSet, s);
            } else {
                std::cerr << "[nfsim/ast] reaction '" << rule.getRuleName()
                          << "' has an unregistered rate function\n";
                delete transformationSet;
                return false;
            }
        } else {
            double rateValue = 0.0;
            if (evaluateStaticExpression(rate, parameters, rateValue, diagnostic)) {
                if (rateValue < 0.0) {
                    diagnostic = "reaction rate is not a finite nonnegative value";
                    std::cerr << "[nfsim/ast] cannot map reaction '" << rule.getRuleName()
                              << "': " << diagnostic << "\n";
                    delete transformationSet;
                    return false;
                }
                if (rate.kind() == bng::ast::ExpressionKind::Identifier &&
                    parameters.count(rate.name()) != 0) {
                    rateParameterName = rate.name();
                }
                transformationSet->finalize();
                reaction = new BasicRxnClass(
                    rule.getRuleName(), 0.0, "", transformationSet, s);
                reaction->setBaseRate(rateValue, rateParameterName);
            } else {
                GlobalFunction* dynamicGlobal = nullptr;
                CompositeFunction* dynamicComposite = nullptr;
                std::vector<std::string> dynamicLocalFunctionArguments;
                if (!addDynamicReactionRateFunction(
                        rate, model, parameters, s, sourcePath,
                        originalRuleOrdinal * 2 + directionOrdinal,
                        dynamicGlobal, dynamicComposite, dynamicLocalFunctionArguments,
                        diagnostic)) {
                    std::cerr << "[nfsim/ast] cannot map reaction '" << rule.getRuleName()
                              << "': " << diagnostic << "\n";
                    delete transformationSet;
                    return false;
                }
                for (const auto& argumentName : dynamicLocalFunctionArguments) {
                    if (!mapLocalFunctionArgument(argumentName)) {
                        std::cerr << "[nfsim/ast] cannot map reaction '"
                                  << rule.getRuleName() << "': " << diagnostic << "\n";
                        delete transformationSet;
                        return false;
                    }
                }
                transformationSet->finalize();
                if (dynamicGlobal != nullptr) {
                    reaction = new FunctionalRxnClass(
                        rule.getRuleName(), dynamicGlobal, transformationSet, s);
                } else if (dynamicComposite != nullptr) {
                    if (dynamicLocalFunctionArguments.empty()) {
                        reaction = new FunctionalRxnClass(
                            rule.getRuleName(), dynamicComposite, transformationSet, s);
                    } else {
                        reaction = new DORRxnClass(
                            rule.getRuleName(), 1.0, "", transformationSet,
                            dynamicComposite, dynamicLocalFunctionArguments, s);
                        dynamicComposite->setGlobalObservableDependency(reaction, s);
                    }
                } else {
                    std::cerr << "[nfsim/ast] dynamic reaction rate produced no function\n";
                    delete transformationSet;
                    return false;
                }
            }
        }

        reaction->setTotalRateFlag(hasReactionModifier(rule, "totalrate"));
        if (hasReactionModifier(rule, "matchonce")) {
            for (std::size_t index = 0; index < reactantRoots.size(); ++index) {
                reaction->setMatchOnce(static_cast<unsigned int>(index), true);
            }
        }

        // Match NFinput::initReactionRules: a zero-order synthesis rate is
        // converted from concentration/time to molecule-count/time using the
        // product compartment volume and NumberPerQuantityUnit.  The factor is
        // kept on functional reactions for update_a(); elementary rates must be
        // scaled once before they enter the live reaction list.
        if (reactantRoots.empty()) {
            Compartment* productCompartment = nullptr;
            bool allSameCompartment = true;
            for (const auto& product : collectRuleGraphMolecules(productPatterns)) {
                const auto& molecule = product.molecule;
                bool declaredProductType = false;
                for (int index = 0; index < s->getNumOfMoleculeTypes(); ++index) {
                    if (s->getMoleculeType(index)->getName() == molecule.name) {
                        declaredProductType = true;
                        break;
                    }
                }
                if (isDiscardMolecule(molecule) && !declaredProductType) {
                    continue;
                }

                const std::string compartmentName = graphMoleculeCompartment(
                    productPatterns[product.patternIndex], molecule);
                if (compartmentName.empty()) continue;
                Compartment* compartment = nullptr;
                if (!resolveCompartment(s, compartmentName, compartment, diagnostic)) {
                    std::cerr << "[nfsim/ast] cannot map reaction '"
                              << rule.getRuleName() << "': " << diagnostic << "\n";
                    delete reaction;
                    delete transformationSet;
                    cleanupDirectProducts();
                    return false;
                }
                if (productCompartment == nullptr) {
                    productCompartment = compartment;
                } else if (productCompartment != compartment) {
                    allSameCompartment = false;
                    std::cerr << "[nfsim/ast] warning: zero-order synthesis ('"
                              << rule.getRuleName()
                              << "') has products in different compartments; "
                                 "volume scaling may be incorrect\n";
                    break;
                }
            }

            double volumeConversion = 1.0;
            if (productCompartment != nullptr && allSameCompartment) {
                volumeConversion = productCompartment->getSize();
                const double numberPerQuantity = s->getNumberPerQuantityUnit();
                if (numberPerQuantity > 0.0) {
                    volumeConversion *= numberPerQuantity;
                }
            }
            reaction->volumeConversionFactor = volumeConversion;
            if (reaction->getRxnType() != ReactionClass::OBS_DEPENDENT_RXN) {
                reaction->setBaseRate(
                    reaction->getBaseRate() * volumeConversion, "");
            }
        }

        // Keep zero-rate elementary rules out of the live reaction list, as the
        // XML loader does. Functional reactions retain their dynamic function.
        if (reaction->getRxnType() == ReactionClass::BASIC_RXN &&
            reaction->getBaseRate() <= 0.0) {
            delete reaction;
            continue;
        }
        s->addReaction(reaction);
        if (verbose) {
            std::cerr << "[nfsim/ast] reaction " << rule.getRuleName() << " (direct)\n";
        }
        }
    }
    return true;
}

// --------------------------------------------------------------------------- //
// Orchestrator.
// --------------------------------------------------------------------------- //
System* buildSystemFromAst(const bng::ast::Model& model,
                           bool blockSameComplexBinding,
                           int globalMoleculeLimit,
                           bool verbose,
                           int& suggestedTraversalLimit,
                           const std::filesystem::path& sourcePath) {
    // Preserve the historical API contract: before the direct adapter grew a
    // separate complex-bookkeeping flag, this argument controlled both the
    // System constructor and same-complex binding checks.
    static const SeedAmountOverrides noOverrides;
    return buildSystemFromAstWithSeedOverrides(
        model, blockSameComplexBinding, blockSameComplexBinding,
        globalMoleculeLimit, verbose, suggestedTraversalLimit, sourcePath,
        noOverrides);
}

System* buildSystemFromAst(const bng::ast::Model& model,
                           bool useComplex,
                           bool blockSameComplexBinding,
                           int globalMoleculeLimit,
                           bool verbose,
                           int& suggestedTraversalLimit,
                           const std::filesystem::path& sourcePath) {
    static const SeedAmountOverrides noOverrides;
    return buildSystemFromAstWithSeedOverrides(
        model, useComplex, blockSameComplexBinding, globalMoleculeLimit,
        verbose, suggestedTraversalLimit, sourcePath, noOverrides);
}

System* buildSystemFromAstWithSeedOverrides(
    const bng::ast::Model& model,
    bool useComplex,
    bool blockSameComplexBinding,
    int globalMoleculeLimit,
    bool verbose,
    int& suggestedTraversalLimit,
    const std::filesystem::path& sourcePath,
    const SeedAmountOverrides& seedAmountOverrides) {
    // Migration escape hatch used by the parity gate: force the XML path.
    if (std::getenv("BNG_NFSIM_FORCE_XML")) {
        if (verbose) std::cerr << "[nfsim/ast] BNG_NFSIM_FORCE_XML set -> XML path\n";
        return nullptr;  // caller falls back to initializeFromModel (in-memory XML)
    }

    const std::string& name = model.getModelName();
    System* s = new System(name.empty() ? "model" : name,
                           useComplex, globalMoleculeLimit);
    // The CLI enables complex-scoped local functions by default.  The direct
    // AST entry point has no separate -nocslf argument, so preserve that
    // default explicitly instead of leaving the legacy System flag unset.
    s->setEvaluateComplexScopedLocalFunctions(true);

    std::map<std::string, double> parameters;
    std::map<std::string, int> allowedStates;
    suggestedTraversalLimit = 0;

    bool ok = false;
    try {
        // Keep dependencies explicit: observables must exist before global
        // functions are prepared, while molecule types and compartments must
        // exist before any pattern is materialized.
        ok = addOptionsFromAst(model, s, verbose) &&
             addParametersFromAst(model, s, parameters, verbose) &&
             addMoleculeTypesFromAst(model, s, allowedStates, verbose) &&
             addCompartmentsFromAst(model, s, verbose) &&
             addObservablesFromAst(model, s, parameters, verbose, suggestedTraversalLimit) &&
             addFunctionsFromAst(model, s, parameters, verbose, sourcePath) &&
             addEnergyPatternsFromAst(model, s, parameters, verbose) &&
             addSpeciesFromAstWithOverrides(
                 model, s, parameters, verbose, seedAmountOverrides) &&
             addReactionRulesFromAst(model, s, parameters, blockSameComplexBinding,
                                     verbose, suggestedTraversalLimit, sourcePath);
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
