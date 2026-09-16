#include "NFinput_fromCompiled.hh"

#include "compile/CompiledModel.hpp"
#include "NFcore/NFcore.hh"
#include "NFcore/compartment.hh"
#include "NFcore/energyPattern.hh"
#include "NFcore2/nfsim_pattern_lowering.hh"
#include "NFfunction/NFfunction.hh"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <limits>
#include <set>
#include <unordered_map>
#include <stdexcept>
#include <unordered_set>
#include <utility>
#include <vector>

class TiXmlElement;
bool createLocalFunction(
    std::string name, std::string expression,
    std::vector<std::string>& argNames, std::vector<std::string>& refNames,
    std::vector<std::string>& refTypes, NFcore::System* system,
    std::map<std::string, double>& parameter, TiXmlElement* observables,
    std::map<std::string, int>& allowedStates, bool verbose);

namespace NFinput {
namespace {

std::string lowerCase(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

bool parseIntegerState(const std::string& state, int& value) {
    if (state.empty()) return false;
    std::size_t consumed = 0;
    try {
        const long parsed = std::stol(state, &consumed, 10);
        if (consumed != state.size() || parsed < std::numeric_limits<int>::min() ||
            parsed > std::numeric_limits<int>::max()) return false;
        value = static_cast<int>(parsed);
        return true;
    } catch (...) {
        return false;
    }
}



std::string runtimeComponentName(
    const bng::compile::CompiledModel& model,
    bng::compile::ComponentTypeId id) {
    const auto* type = model.moleculeType(id.moleculeType);
    const auto* component = model.component(id);
    if (type == nullptr || component == nullptr) return {};
    std::size_t total = 0;
    std::size_t ordinal = 0;
    for (std::size_t i = 0; i < type->components.size(); ++i) {
        if (type->components[i].name != component->name) continue;
        ++total;
        if (i <= id.index) ordinal = total;
    }
    if (total <= 1) return component->name;
    return component->name + std::to_string(ordinal);
}

NFcore::Compartment* compiledCompartment(
    const bng::compile::CompiledModel& model,
    const bng::compile::Pattern& pattern,
    const bng::compile::PatternMoleculeDescriptor& molecule,
    NFcore::System& system) {
    std::string name = molecule.compartment.empty() ? pattern.compartment()
                                                     : molecule.compartment;
    if (name.empty() && molecule.compartmentId.has_value()) {
        const auto* declaration = model.compartment(*molecule.compartmentId);
        if (declaration != nullptr) name = declaration->name;
    }
    if (name.empty() && pattern.compartmentId().has_value()) {
        const auto* declaration = model.compartment(*pattern.compartmentId());
        if (declaration != nullptr) name = declaration->name;
    }
    return name.empty() ? nullptr : system.getCompartment(name);
}

bool seedCount(const bng::compile::CompiledSeed& seed,
               const std::map<std::string, double>& overrides,
               int& count, std::string& diagnostic) {
    auto found = overrides.find(seed.sourcePattern);
    if (found == overrides.end() && !seed.compartment.empty()) {
        found = overrides.find("@" + seed.compartment + ":" + seed.sourcePattern);
        if (found == overrides.end())
            found = overrides.find("@" + seed.compartment + "::" + seed.sourcePattern);
    }
    const auto amount = found == overrides.end()
                            ? seed.evaluatedAmount
                            : std::optional<double>(found->second);
    if (!amount.has_value() || !std::isfinite(*amount) || *amount < 0.0 ||
        *amount > static_cast<double>(std::numeric_limits<int>::max()) ||
        std::floor(*amount) != *amount) {
        diagnostic = "seed amount must resolve to a nonnegative integer";
        return false;
    }
    count = static_cast<int>(*amount);
    return true;
}


const char* unaryText(bng::compile::UnaryOp op) {
    using Op = bng::compile::UnaryOp;
    switch (op) {
    case Op::Plus: return "+";
    case Op::Negate: return "-";
    case Op::LogicalNot: return "!";
    case Op::Unknown: return "";
    }
    return "";
}

const char* binaryText(bng::compile::BinaryOp op) {
    using Op = bng::compile::BinaryOp;
    switch (op) {
    case Op::Add: return "+";
    case Op::Subtract: return "-";
    case Op::Multiply: return "*";
    case Op::Divide: return "/";
    case Op::Power: return "^";
    case Op::Less: return "<";
    case Op::LessEqual: return "<=";
    case Op::Greater: return ">";
    case Op::GreaterEqual: return ">=";
    case Op::Equal: return "==";
    case Op::NotEqual: return "!=";
    case Op::LogicalAnd: return "&&";
    case Op::LogicalOr: return "||";
    case Op::Unknown: return "";
    }
    return "";
}

const char* builtinText(bng::compile::BuiltinFunction op) {
    using Fn = bng::compile::BuiltinFunction;
    switch (op) {
    case Fn::Abs: return "abs"; case Fn::Acos: return "acos";
    case Fn::Acosh: return "acosh"; case Fn::Asin: return "asin";
    case Fn::Asinh: return "asinh"; case Fn::Atan: return "atan";
    case Fn::Atanh: return "atanh"; case Fn::Avg: return "avg";
    case Fn::Ceil: return "ceil"; case Fn::Cos: return "cos";
    case Fn::Cosh: return "cosh"; case Fn::E: return "e";
    case Fn::Exp: return "exp"; case Fn::Factorial: return "factorial";
    case Fn::Floor: return "floor";
    case Fn::If: return "if"; case Fn::Ln: return "ln";
    case Fn::Log10: return "log10"; case Fn::Log2: return "log2";
    case Fn::Max: return "max"; case Fn::Min: return "min";
    case Fn::MRatio: return "mratio"; case Fn::Pi: return "pi";
    case Fn::Rint: return "rint"; case Fn::Sin: return "sin";
    case Fn::Sinh: return "sinh"; case Fn::Sqrt: return "sqrt";
    case Fn::Sum: return "sum"; case Fn::Tan: return "tan";
    case Fn::Tanh: return "tanh"; case Fn::Time: return "time";
    case Fn::Arrhenius: return "Arrhenius"; case Fn::Saturation: return "Sat";
    case Fn::MichaelisMenten: return "MM"; case Fn::Hill: return "Hill";
    case Fn::FunctionProduct: return "FunctionProduct"; case Fn::Hybrid: return "Hybrid";
    case Fn::TableFunction: return "tfun"; case Fn::Unknown: return "";
    }
    return "";
}

std::string expressionText(const bng::compile::CompiledModel& model,
                           const bng::compile::ResolvedExpression& expression,
                           bool& ok) {
    using Kind = bng::compile::ResolvedExpressionKind;
    if (!ok) return {};
    const auto renderArgs = [&](const auto& args, const std::string& name) {
        std::string result = name + "(";
        for (std::size_t i = 0; i < args.size(); ++i) {
            if (i != 0) result += ',';
            result += expressionText(model, args[i], ok);
        }
        result += ')';
        return result;
    };
    switch (expression.kind) {
    case Kind::Number:
        if (!std::isfinite(expression.numberValue)) { ok = false; return {}; }
        if (expression.operation == "_Na") return "_Na";
        return std::to_string(expression.numberValue);
    case Kind::ParameterRef: {
        if (!expression.symbol.has_value()) { ok = false; return {}; }
        const auto* p = model.parameter(bng::compile::ParameterId::fromDenseIndex(
            expression.symbol->index));
        if (p == nullptr) { ok = false; return {}; }
        return p->name;
    }
    case Kind::ObservableRef: {
        if (!expression.symbol.has_value()) { ok = false; return {}; }
        const auto* o = model.observable(bng::compile::ObservableId::fromDenseIndex(
            expression.symbol->index));
        if (o == nullptr) { ok = false; return {}; }
        return expression.arguments.empty() ? o->name : renderArgs(expression.arguments, o->name);
    }
    case Kind::FunctionRef: {
        if (!expression.symbol.has_value()) { ok = false; return {}; }
        const auto* f = model.function(bng::compile::FunctionId::fromDenseIndex(
            expression.symbol->index));
        if (f == nullptr) { ok = false; return {}; }
        return expression.arguments.empty() ? f->name + "()" : renderArgs(expression.arguments, f->name);
    }
    case Kind::LocalRef:
        return expression.localName;
    case Kind::ReactantCountRef:
        return "reactant_" + std::to_string(expression.reactantIndex + 1);
    case Kind::TimeRef:
        return "time";
    case Kind::Unary:
        if (!expression.unaryOp.has_value() || expression.arguments.size() != 1) {
            ok = false; return {};
        }
        return std::string(unaryText(*expression.unaryOp)) +
               expressionText(model, expression.arguments.front(), ok);
    case Kind::Binary:
        if (!expression.binaryOp.has_value() || expression.arguments.size() != 2) {
            ok = false; return {};
        }
        return "(" + expressionText(model, expression.arguments[0], ok) + " " +
               binaryText(*expression.binaryOp) + " " +
               expressionText(model, expression.arguments[1], ok) + ")";
    case Kind::BuiltinCall:
        if (!expression.builtin.has_value() ||
            *expression.builtin == bng::compile::BuiltinFunction::TableFunction) {
            ok = false; return {};
        }
        return renderArgs(expression.arguments, builtinText(*expression.builtin));
    case Kind::TableFunction:
        return "__TFUN_VAL__";
    case Kind::Unresolved:
        ok = false;
        return {};
    }
    ok = false;
    return {};
}

struct ExpressionDependencies {
    std::set<std::string> parameters;
    std::set<std::string> observables;
    std::set<std::string> functions;
    bool usesTime = false;
    bool hasLocal = false;
    bool hasTable = false;
};

void collectDependencies(const bng::compile::CompiledModel& model,
                         const bng::compile::ResolvedExpression& expression,
                         ExpressionDependencies& deps) {
    using Kind = bng::compile::ResolvedExpressionKind;
    if (expression.kind == Kind::ParameterRef && expression.symbol.has_value()) {
        if (const auto* p = model.parameter(bng::compile::ParameterId::fromDenseIndex(
                expression.symbol->index))) deps.parameters.insert(p->name);
    } else if (expression.kind == Kind::ObservableRef && expression.symbol.has_value()) {
        if (const auto* o = model.observable(bng::compile::ObservableId::fromDenseIndex(
                expression.symbol->index))) deps.observables.insert(o->name);
    } else if (expression.kind == Kind::FunctionRef && expression.symbol.has_value()) {
        if (const auto* f = model.function(bng::compile::FunctionId::fromDenseIndex(
                expression.symbol->index))) deps.functions.insert(f->name);
    } else if (expression.kind == Kind::ReactantCountRef) {
        deps.functions.insert("reactant_" + std::to_string(expression.reactantIndex + 1));
    } else if (expression.kind == Kind::TimeRef ||
               (expression.kind == Kind::BuiltinCall && expression.builtin.has_value() &&
                *expression.builtin == bng::compile::BuiltinFunction::Time)) {
        deps.usesTime = true;
    } else if (expression.kind == Kind::LocalRef) {
        deps.hasLocal = true;
    } else if (expression.kind == Kind::TableFunction) {
        deps.hasTable = true;
    }
    for (const auto& child : expression.arguments) collectDependencies(model, child, deps);
}

std::string replaceCompiledObservableNames(
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
        const auto found = replacements.find(token);
        if (found == replacements.end()) {
            result.append(expression, start, index - start);
            continue;
        }
        std::size_t lookahead = index;
        while (lookahead < expression.size() &&
               std::isspace(static_cast<unsigned char>(expression[lookahead]))) ++lookahead;
        if (lookahead < expression.size() && expression[lookahead] == '(') {
            std::size_t close = lookahead + 1;
            while (close < expression.size() &&
                   std::isspace(static_cast<unsigned char>(expression[close]))) ++close;
            if (close < expression.size() && expression[close] == ')') {
                result += found->second;
                result += "()";
                index = close + 1;
                continue;
            }
        }
        result += found->second;
    }
    return result;
}



bool isReactantCountName(const std::string& name) {
    return name.size() == 10 && name.compare(0, 9, "reactant_") == 0 &&
           name.back() >= '1' && name.back() <= '9';
}

void collectTableFunctions(const bng::compile::ResolvedExpression& expression,
                           std::vector<const bng::compile::ResolvedExpression*>& tables) {
    if (expression.kind == bng::compile::ResolvedExpressionKind::TableFunction)
        tables.push_back(&expression);
    for (const auto& child : expression.arguments) collectTableFunctions(child, tables);
}

std::string resolveTfunPath(const std::string& filePath,
                            const std::filesystem::path& sourcePath) {
    const std::filesystem::path path(filePath);
    if (path.is_absolute() || sourcePath.empty()) return path.string();
    return (sourcePath.parent_path() / path).lexically_normal().string();
}

bool configureTableFunction(
    const bng::compile::CompiledModel& model,
    const bng::compile::ResolvedExpression& table,
    const std::filesystem::path& sourcePath,
    NFcore::System* system,
    NFcore::GlobalFunction* global,
    NFcore::CompositeFunction* composite,
    NFcore::LocalFunction* local,
    std::string& diagnostic) {
    using Kind = bng::compile::ResolvedExpressionKind;
    if (table.kind != Kind::TableFunction || table.arguments.size() != 1) {
        diagnostic = "malformed TFUN metadata";
        return false;
    }
    const bool fileBacked = !table.tableFile.empty();
    if (!fileBacked && (table.tableX.empty() || table.tableX.size() != table.tableY.size())) {
        diagnostic = "inline TFUN has empty or mismatched data columns";
        return false;
    }
    if (fileBacked && (!table.tableX.empty() || !table.tableY.empty())) {
        diagnostic = "file-backed TFUN cannot also contain inline data";
        return false;
    }
    const auto configureTarget = [&]() {
        try {
            if (global != nullptr) {
                if (fileBacked) global->enableFileDependency(resolveTfunPath(table.tableFile, sourcePath), table.tableMethod);
                else global->enableInlineDependency(table.tableX, table.tableY, table.tableMethod);
                global->setCtrName("__TFUN_VAL__");
            } else if (composite != nullptr) {
                if (fileBacked) composite->enableFileDependency(resolveTfunPath(table.tableFile, sourcePath), table.tableMethod);
                else composite->enableInlineDependency(table.tableX, table.tableY, table.tableMethod);
                composite->setCtrName("__TFUN_VAL__");
            } else if (local != nullptr) {
                if (fileBacked) local->enableFileDependency(resolveTfunPath(table.tableFile, sourcePath), table.tableMethod);
                else local->enableInlineDependency(table.tableX, table.tableY, table.tableMethod);
                local->setCtrName("__TFUN_VAL__");
            } else {
                diagnostic = "TFUN has no target function object";
                return false;
            }
        } catch (const std::exception& error) {
            diagnostic = "could not configure TFUN: " + std::string(error.what());
            return false;
        }
        return true;
    };

    const auto& counter = table.arguments.front();
    if (counter.kind == Kind::TimeRef) {
        if (!configureTarget()) return false;
        if (global) global->setCounterFromTime(system);
        else if (composite) composite->setCounterFromTime(system);
        else local->setCounterFromTime(system);
        system->setHasTimeDependentFunctions(true);
        return true;
    }
    if (counter.kind == Kind::ParameterRef && counter.symbol.has_value()) {
        const auto* parameter = model.parameter(
            bng::compile::ParameterId::fromDenseIndex(counter.symbol->index));
        if (parameter == nullptr || !configureTarget()) return false;
        if (global) global->setCounterFromParameter(system, parameter->name);
        else if (composite) composite->setCounterFromParameter(system, parameter->name);
        else local->setCounterFromParameter(system, parameter->name);
        return true;
    }
    if (counter.kind == Kind::ObservableRef && counter.symbol.has_value() &&
        counter.arguments.empty()) {
        const auto* observableDecl = model.observable(
            bng::compile::ObservableId::fromDenseIndex(counter.symbol->index));
        auto* observable = observableDecl == nullptr ? nullptr
                                                     : system->getObservableByName(observableDecl->name);
        if (observable == nullptr || !configureTarget()) {
            diagnostic = "TFUN observable counter is not registered";
            return false;
        }
        if (global) observable->addReferenceToGlobalFunction(global);
        if (composite) observable->addReferenceToCompositeFunction(composite);
        if (local) local->setCounterFromObservable(observable);
        return true;
    }
    if (counter.kind == Kind::FunctionRef && counter.symbol.has_value() &&
        counter.arguments.empty() && composite != nullptr) {
        const auto* functionDecl = model.function(
            bng::compile::FunctionId::fromDenseIndex(counter.symbol->index));
        auto* function = functionDecl == nullptr ? nullptr
                                                 : system->getGlobalFunctionByName(functionDecl->name);
        if (function == nullptr || !configureTarget()) {
            diagnostic = "TFUN function counter is not a registered base global";
            return false;
        }
        composite->addFunctionPointer(function);
        return true;
    }
    diagnostic = "unsupported TFUN counter in compiled expression";
    return false;
}

} // namespace

bool configureTableFunctionFromCompiled(
    const bng::compile::CompiledModel& model,
    const bng::compile::ResolvedExpression& table,
    const std::filesystem::path& sourcePath,
    NFcore::System* system,
    NFcore::GlobalFunction* global,
    NFcore::CompositeFunction* composite,
    NFcore::LocalFunction* local,
    std::string& diagnostic) {
    return configureTableFunction(
        model, table, sourcePath, system, global, composite, local, diagnostic);
}

bool addOptionsFromCompiled(const bng::compile::CompiledModel& model,
                            NFcore::System* system, bool verbose) {
    if (system == nullptr) return false;
    const auto& options = model.metadata().options;
    const auto found = options.find("NumberPerQuantityUnit");
    if (found == options.end()) return true;
    try {
        std::size_t consumed = 0;
        const double value = std::stod(found->second, &consumed);
        if (consumed != found->second.size() || !std::isfinite(value) || value < 0.0)
            return false;
        system->setNumberPerQuantityUnit(value);
        if (verbose) std::cerr << "[nfsim/compiled] NumberPerQuantityUnit = " << value << "\n";
        return true;
    } catch (...) {
        return false;
    }
}

bool addParametersFromCompiled(const bng::compile::CompiledModel& model,
                               NFcore::System* system,
                               std::map<std::string, double>& parameters,
                               bool verbose) {
    if (system == nullptr) return false;
    for (const auto& parameter : model.parameters()) {
        if (!parameter.constantValue.has_value() || !std::isfinite(*parameter.constantValue)) {
            std::cerr << "[nfsim/compiled] parameter '" << parameter.name
                      << "' is not compile-time evaluated\n";
            return false;
        }
        parameters[parameter.name] = *parameter.constantValue;
        system->addParameter(parameter.name, *parameter.constantValue);
        if (verbose) std::cerr << "[nfsim/compiled] parameter " << parameter.name
                               << " = " << *parameter.constantValue << "\n";
    }
    return true;
}

bool addCompartmentsFromCompiled(const bng::compile::CompiledModel& model,
                                 NFcore::System* system, bool verbose) {
    if (system == nullptr) return false;
    std::unordered_set<std::string> seen;
    for (const auto& compartment : model.compartments()) {
        if (compartment.name.empty() || !seen.insert(compartment.name).second ||
            system->getCompartment(compartment.name) != nullptr) return false;
        system->addCompartment(new NFcore::Compartment(
            compartment.name, compartment.dimension, compartment.volume));
        if (verbose) std::cerr << "[nfsim/compiled] compartment " << compartment.name << "\n";
    }
    for (const auto& compartment : model.compartments()) {
        if (!compartment.parent.has_value()) continue;
        const auto* parentDecl = model.compartment(*compartment.parent);
        auto* child = system->getCompartment(compartment.name);
        auto* parent = parentDecl == nullptr ? nullptr : system->getCompartment(parentDecl->name);
        if (child == nullptr || parent == nullptr) return false;
        child->setParent(parent);
    }
    return true;
}

bool addMoleculeTypesFromCompiled(const bng::compile::CompiledModel& model,
                                  NFcore::System* system,
                                  std::map<std::string, int>& allowedStates,
                                  bool verbose) {
    if (system == nullptr) return false;
    try {
        std::vector<const bng::compile::CompiledMoleculeType*> moleculeTypes;
        for (const auto& type : model.moleculeTypes()) moleculeTypes.push_back(&type);
        std::sort(moleculeTypes.begin(), moleculeTypes.end(), [](const auto* a, const auto* b) {
            return a->name < b->name;
        });

        for (const auto* type : moleculeTypes) {
            const auto& typeName = type->name;
            if (typeName.empty()) return false;
            if (lowerCase(typeName) == "null") continue;
            for (int i = 0; i < system->getNumOfMoleculeTypes(); ++i)
                if (system->getMoleculeType(i)->getName() == typeName) return false;
            if (type->population && !type->components.empty()) return false;

            std::vector<std::string> componentNames;
            std::vector<std::string> defaultStates;
            std::vector<std::vector<std::string>> possibleStates;
            std::vector<std::vector<std::string>> equivalentComponents;
            std::vector<bool> integerComponents;
            std::vector<std::size_t> firstSymmetricSites;

            for (const auto& component : type->components) {
                if (component.name.empty()) return false;
                std::string componentName = component.name;
                auto duplicate = std::find(componentNames.begin(), componentNames.end(), componentName);
                if (duplicate != componentNames.end()) {
                    const auto duplicateIndex = static_cast<std::size_t>(std::distance(componentNames.begin(), duplicate));
                    if (std::find(firstSymmetricSites.begin(), firstSymmetricSites.end(), duplicateIndex) == firstSymmetricSites.end())
                        firstSymmetricSites.push_back(duplicateIndex);
                    std::string renamed = componentName + "2";
                    auto equivalent = std::find_if(equivalentComponents.begin(), equivalentComponents.end(),
                        [&](const auto& group) { return !group.empty() && group.front() == componentName + "1"; });
                    if (equivalent != equivalentComponents.end()) {
                        renamed = componentName + std::to_string(equivalent->size() + 1);
                        equivalent->push_back(renamed);
                    } else {
                        equivalentComponents.push_back({componentName + "1", renamed});
                    }
                    componentName = std::move(renamed);
                }
                componentNames.push_back(componentName);

                std::vector<std::string> states;
                bool hasStringState = false, hasIntegerState = false, hasPlusMinusState = false,
                     hasNegativeInteger = false;
                int maximumState = -1;
                for (const auto& state : component.stateNames) {
                    if (state == "?") continue;
                    int integerValue = 0;
                    if (parseIntegerState(state, integerValue)) {
                        hasIntegerState = true;
                        hasNegativeInteger = hasNegativeInteger || integerValue < 0;
                        maximumState = std::max(maximumState, integerValue);
                    } else if (state == "PLUS" || state == "MINUS") {
                        hasPlusMinusState = true;
                    } else {
                        hasStringState = true;
                    }
                }
                bool integerComponent = false;
                if (hasIntegerState && !hasStringState) {
                    if (hasNegativeInteger || maximumState < 0 || maximumState > 10000) return false;
                    integerComponent = true;
                    for (int value = 0; value <= maximumState; ++value) states.push_back(std::to_string(value));
                } else if (hasStringState) {
                    (void)hasPlusMinusState;
                    for (const auto& state : component.stateNames)
                        if (state != "?" && std::find(states.begin(), states.end(), state) == states.end())
                            states.push_back(state);
                }
                integerComponents.push_back(integerComponent);
                defaultStates.push_back(states.empty() ? std::string{} : states.front());
                possibleStates.push_back(std::move(states));
            }

            for (const auto index : firstSymmetricSites) componentNames[index] += "1";
            for (std::size_t i = 0; i < componentNames.size(); ++i)
                for (std::size_t state = 0; state < possibleStates[i].size(); ++state)
                    allowedStates[typeName + "_" + componentNames[i] + "_" + possibleStates[i][state]] = static_cast<int>(state);

            auto* nfType = new NFcore::MoleculeType(typeName, componentNames, defaultStates,
                                                    possibleStates, integerComponents,
                                                    type->population, system);
            nfType->addEquivalentComponents(equivalentComponents);
            if (verbose) std::cerr << "[nfsim/compiled] molecule type " << typeName << "\n";
        }
        return true;
    } catch (const std::exception& error) {
        std::cerr << "[nfsim/compiled] molecule type construction failed: " << error.what() << "\n";
        return false;
    }
}



bool addObservablesFromCompiled(const bng::compile::CompiledModel& model,
                                NFcore::System* system, bool verbose,
                                int& suggestedTraversalLimit) {
    if (system == nullptr) return false;
    std::unordered_set<std::string> names;
    for (const auto& observable : model.observables()) {
        if (observable.name.empty() || !names.insert(observable.name).second ||
            observable.terms.empty()) return false;
        if (observable.kind != bng::compile::ObservableKind::Molecules &&
            observable.kind != bng::compile::ObservableKind::Species) return false;
        const bool moleculesObservable =
            observable.kind == bng::compile::ObservableKind::Molecules;
        if (!moleculesObservable) system->setUsingComplex(true);

        std::vector<NFcore::TemplateMolecule*> roots;
        std::vector<std::string> relations;
        std::vector<int> quantities;
        for (const auto& term : observable.terms) {
            bool hasDisjointSets = false;
            std::string diagnostic;
            if (moleculesObservable) {
                // Legacy NFsim counts every valid symmetric embedding for a
                // Molecules observable.  Expand the full equivalent-site
                // orbit here so compiled lowering has the same observable
                // contract as the XML bridge and the native NFsim oracle.
                std::set<std::pair<std::size_t, std::size_t>> symmetricSites;
                for (std::size_t moleculeIndex = 0;
                     moleculeIndex < term.pattern.molecules().size(); ++moleculeIndex) {
                    const auto& molecule = term.pattern.molecules()[moleculeIndex];
                    if (!molecule.moleculeTypeId.has_value()) {
                        diagnostic = "observable molecule has no resolved type";
                        break;
                    }
                    const auto* type = model.moleculeType(*molecule.moleculeTypeId);
                    if (type == nullptr) {
                        diagnostic = "observable molecule refers to an unknown type";
                        break;
                    }
                    for (std::size_t siteIndex = 0; siteIndex < molecule.sites.size();
                         ++siteIndex) {
                        const auto& site = molecule.sites[siteIndex];
                        const auto repeated = std::count_if(
                            type->components.begin(), type->components.end(),
                            [&](const auto& component) {
                                return component.name == site.componentName;
                            });
                        if (repeated > 1)
                            symmetricSites.emplace(moleculeIndex, siteIndex);
                    }
                }
                if (!diagnostic.empty()) {
                    std::cerr << "[nfsim/compiled] cannot lower observable '"
                              << observable.name << "': " << diagnostic << "\n";
                    return false;
                }

                std::vector<std::vector<NFcore::TemplateMolecule*>> builds;
                std::vector<NFcore2::RuntimeComponentNames> assignments;
                if (!NFcore2::lowerPatternToNFsimPermutations(
                        term.pattern, *system, symmetricSites, builds, assignments,
                        hasDisjointSets, suggestedTraversalLimit, diagnostic) ||
                    builds.empty()) {
                    std::cerr << "[nfsim/compiled] cannot lower observable '"
                              << observable.name << "': " << diagnostic << "\n";
                    return false;
                }
                for (const auto& build : builds) {
                    if (build.empty()) {
                        diagnostic = "observable permutation produced no template";
                        std::cerr << "[nfsim/compiled] cannot lower observable '"
                                  << observable.name << "': " << diagnostic << "\n";
                        return false;
                    }
                    roots.push_back(build.front());
                }
            } else {
                std::vector<NFcore::TemplateMolecule*> lowered;
                if (!NFcore2::lowerPatternToNFsim(
                        term.pattern, *system, lowered, hasDisjointSets,
                        suggestedTraversalLimit, diagnostic) || lowered.empty()) {
                    std::cerr << "[nfsim/compiled] cannot lower observable '"
                              << observable.name << "': " << diagnostic << "\n";
                    return false;
                }
                roots.push_back(lowered.front());
            }
            if (hasDisjointSets || !term.relation.empty()) system->setUsingComplex(true);
            relations.push_back(term.relation);
            quantities.push_back(term.quantity);
        }

        const bool stoichiometric = std::any_of(
            relations.begin(), relations.end(), [](const auto& value) { return !value.empty(); });
        NFcore::Observable* created = nullptr;
        if (moleculesObservable) {
            if (stoichiometric) {
                created = new NFcore::MoleculesObservable(
                    observable.name, roots, relations, quantities);
            } else {
                created = new NFcore::MoleculesObservable(observable.name, roots);
            }
            std::unordered_set<NFcore::MoleculeType*> registered;
            for (auto* root : roots) {
                if (registered.insert(root->getMoleculeType()).second)
                    root->getMoleculeType()->addMolObs(
                        static_cast<NFcore::MoleculesObservable*>(created));
            }
        } else {
            created = new NFcore::SpeciesObservable(
                observable.name, roots, relations, quantities);
        }
        system->addObservableForOutput(created);
        if (verbose)
            std::cerr << "[nfsim/compiled] observable " << observable.name << "\n";
    }
    return true;
}

std::size_t seedBondCount(const bng::compile::PatternSiteDescriptor& site) {
    if (site.bondConstraints.empty()) {
        return site.bondKind == bng::compile::BondConstraintKind::Unbound ? 0 : 1;
    }
    return static_cast<std::size_t>(std::count_if(
        site.bondConstraints.begin(), site.bondConstraints.end(), [](const auto& bond) {
            return bond.kind != bng::compile::BondConstraintKind::Unbound;
        }));
}

bool seedComponentLess(const bng::compile::PatternSiteDescriptor& left,
                       const bng::compile::PatternSiteDescriptor& right) {
    if (left.componentName != right.componentName)
        return left.componentName < right.componentName;
    const auto leftState = left.stateConstraint == "?" ? std::string{} : left.stateConstraint;
    const auto rightState = right.stateConstraint == "?" ? std::string{} : right.stateConstraint;
    if (leftState != rightState) {
        if (leftState.empty() != rightState.empty()) return leftState.empty();
        return leftState < rightState;
    }
    const auto leftBonds = seedBondCount(left);
    const auto rightBonds = seedBondCount(right);
    return leftBonds == rightBonds ? false : leftBonds > rightBonds;
}

bool seedMoleculeLess(const bng::compile::PatternMoleculeDescriptor& left,
                      const bng::compile::PatternMoleculeDescriptor& right) {
    if (left.moleculeType != right.moleculeType)
        return left.moleculeType < right.moleculeType;
    if (left.sites.size() != right.sites.size())
        return left.sites.size() < right.sites.size();
    if (left.compartment.empty() != right.compartment.empty())
        return left.compartment.empty();
    if (left.compartment != right.compartment)
        return left.compartment < right.compartment;
    for (std::size_t index = 0; index < left.sites.size(); ++index) {
        if (seedComponentLess(left.sites[index], right.sites[index])) return true;
        if (seedComponentLess(right.sites[index], left.sites[index])) return false;
    }
    return false;
}

std::vector<bng::compile::PatternMoleculeDescriptor> canonicalSeedMolecules(
    const bng::compile::Pattern& pattern) {
    auto molecules = pattern.molecules();
    for (auto& molecule : molecules) {
        std::stable_sort(molecule.sites.begin(), molecule.sites.end(), seedComponentLess);
    }
    std::stable_sort(molecules.begin(), molecules.end(), seedMoleculeLess);
    return molecules;
}

bool addSpeciesFromCompiledWithOverrides(
    const bng::compile::CompiledModel& model, NFcore::System* system,
    bool verbose, const std::map<std::string, double>& seedAmountOverrides) {
    if (system == nullptr) return false;
    for (const auto& seed : model.seeds()) {
        const auto& pattern = seed.pattern;
        if (!pattern.isResolved() || pattern.molecules().empty()) return false;
        const auto molecules = canonicalSeedMolecules(pattern);

        // `$Null()`/`$Trash()` are fixed degradation seeds in BNGL.  They are
        // represented in the compiled model so source/XML provenance remains
        // intact, but the NFsim runtime intentionally has no corresponding
        // molecule type.  Consume the sentinel before looking up runtime
        // molecule types, matching the legacy AST/XML loaders.
        const bool allDiscard = std::all_of(
            molecules.begin(), molecules.end(),
            [](const auto& molecule) {
                const auto name = lowerCase(molecule.moleculeType);
                return name == "null" || name == "trash";
            });
        if (allDiscard && seed.constant) continue;

        int count = 0;
        std::string diagnostic;
        if (!seedCount(seed, seedAmountOverrides, count, diagnostic)) {
            std::cerr << "[nfsim/compiled] cannot materialize seed '"
                      << seed.sourcePattern << "': " << diagnostic << "\n";
            return false;
        }

        bool population = false;
        bool particle = false;
        std::vector<NFcore::MoleculeType*> types;
        std::vector<NFcore::Compartment*> compartments;
        types.reserve(molecules.size());
        compartments.reserve(molecules.size());
        for (const auto& molecule : molecules) {
            if (!molecule.moleculeTypeId.has_value()) return false;
            const auto* declaration = model.moleculeType(*molecule.moleculeTypeId);
            if (declaration == nullptr) return false;
            auto* type = system->getMoleculeTypeByName(declaration->name);
            if (type == nullptr) return false;
            population = population || type->isPopulationType();
            particle = particle || !type->isPopulationType();
            types.push_back(type);
            auto* compartment = compiledCompartment(model, pattern, molecule, *system);
            const bool hasCompartment = !molecule.compartment.empty() ||
                                        molecule.compartmentId.has_value() ||
                                        !pattern.compartment().empty() ||
                                        pattern.compartmentId().has_value();
            if (hasCompartment && compartment == nullptr) return false;
            compartments.push_back(compartment);
        }
        if (population && particle) return false;
        if (population && molecules.size() != 1) return false;

        const int copies = population ? 1 : count;
        std::vector<std::vector<NFcore::Molecule*>> generated(
            molecules.size());
        for (std::size_t moleculeIndex = 0;
             moleculeIndex < molecules.size(); ++moleculeIndex) {
            const auto& molecule = molecules[moleculeIndex];
            generated[moleculeIndex].reserve(static_cast<std::size_t>(copies));
            for (int copy = 0; copy < copies; ++copy) {
                auto* concrete = types[moleculeIndex]->genDefaultMolecule(
                    compartments[moleculeIndex]);
                generated[moleculeIndex].push_back(concrete);
                for (const auto& site : molecule.sites) {
                    if (!site.componentType.has_value()) return false;
                    const auto runtimeName = runtimeComponentName(model, *site.componentType);
                    if (runtimeName.empty()) return false;
                    using StateKind = bng::compile::StateConstraintKind;
                    if (site.stateConstraintResolved.kind == StateKind::Set) {
                        std::cerr << "[nfsim/compiled] seed state-set constraint is not concrete\n";
                        return false;
                    }
                    if (site.stateConstraintResolved.kind == StateKind::Exact) {
                        if (!site.stateConstraintResolved.exact.has_value()) return false;
                        concrete->setComponentState(
                            runtimeName,
                            static_cast<int>(site.stateConstraintResolved.exact->index));
                    }
                    for (const auto& bond : site.bondConstraints) {
                        if (bond.kind == bng::compile::BondConstraintKind::Any) {
                            std::cerr << "[nfsim/compiled] wildcard seed bond is not concrete\n";
                            return false;
                        }
                    }
                }
            }
        }

        struct Endpoint { std::size_t molecule; std::string component; };
        std::unordered_map<std::size_t, std::vector<Endpoint>> bonds;
        for (std::size_t moleculeIndex = 0;
             moleculeIndex < molecules.size(); ++moleculeIndex) {
            for (const auto& site : molecules[moleculeIndex].sites) {
                if (!site.componentType.has_value()) return false;
                const auto runtimeName = runtimeComponentName(model, *site.componentType);
                const auto collect = [&](const bng::compile::PatternBondDescriptor& bond) {
                    if (bond.kind == bng::compile::BondConstraintKind::Exact &&
                        bond.group.value != 0) {
                        bonds[bond.group.value].push_back({moleculeIndex, runtimeName});
                    }
                };
                if (site.bondConstraints.empty()) {
                    collect({site.bondConstraint, site.bondKind, site.bondGroup});
                } else {
                    if (site.bondConstraints.size() > 1) return false;
                    collect(site.bondConstraints.front());
                }
            }
        }
        for (const auto& [group, endpoints] : bonds) {
            (void)group;
            if (endpoints.size() != 2) return false;
            for (int copy = 0; copy < copies; ++copy) {
                NFcore::Molecule::bind(
                    generated[endpoints[0].molecule][copy], endpoints[0].component,
                    generated[endpoints[1].molecule][copy], endpoints[1].component);
            }
        }

        if (population && !generated.front().front()->setPopulation(count)) return false;
        if (seed.constant) {
            if (molecules.size() != 1 || population) return false;
            types.front()->setFixed(true, count, compartments.front());
        }
        if (verbose)
            std::cerr << "[nfsim/compiled] seed " << seed.sourcePattern
                      << " count=" << count << "\n";
    }
    return true;
}

bool addSpeciesFromCompiled(const bng::compile::CompiledModel& model,
                            NFcore::System* system, bool verbose) {
    static const std::map<std::string, double> noOverrides;
    return addSpeciesFromCompiledWithOverrides(model, system, verbose, noOverrides);
}


bool addEnergyPatternsFromCompiled(const bng::compile::CompiledModel& model,
                                   NFcore::System* system, bool verbose) {
    if (system == nullptr) return false;
    if (model.energyFactors().empty()) return true;

    double phi = 0.5;
    double rt = 2.478;
    for (const auto& parameter : model.parameters()) {
        if (!parameter.constantValue.has_value()) continue;
        if (parameter.name == "phi") phi = *parameter.constantValue;
        else if (parameter.name == "RT") rt = *parameter.constantValue;
    }
    if (!std::isfinite(phi) || !std::isfinite(rt) || rt == 0.0) return false;

    auto* energyFunction = new NFcore::EnergyFunction(phi, rt);
    std::set<std::string> ids;
    for (std::size_t patternIndex = 0;
         patternIndex < model.energyFactors().size(); ++patternIndex) {
        const auto& factor = model.energyFactors()[patternIndex];
        NFcore::EnergyPatternInfo info;
        info.id = factor.label.empty() ? "energy_" + std::to_string(patternIndex + 1)
                                      : factor.label;
        if (!ids.insert(info.id).second || !factor.evaluatedValue.has_value() ||
            !std::isfinite(*factor.evaluatedValue)) {
            delete energyFunction;
            return false;
        }
        info.energyValue = *factor.evaluatedValue;
        if (!factor.pattern.isResolved() || factor.pattern.molecules().empty()) {
            delete energyFunction;
            return false;
        }

        struct SitePosition { int molecule = -1; int component = -1; };
        std::unordered_map<std::size_t, std::vector<SitePosition>> bondEndpoints;
        for (std::size_t moleculeIndex = 0;
             moleculeIndex < factor.pattern.molecules().size(); ++moleculeIndex) {
            const auto& molecule = factor.pattern.molecules()[moleculeIndex];
            if (!molecule.moleculeTypeId.has_value()) { delete energyFunction; return false; }
            const auto* typeDecl = model.moleculeType(*molecule.moleculeTypeId);
            if (typeDecl == nullptr) { delete energyFunction; return false; }
            auto* runtimeType = system->getMoleculeTypeByName(typeDecl->name);
            if (runtimeType == nullptr) { delete energyFunction; return false; }

            NFcore::EpMolecule epMolecule;
            epMolecule.typeName = typeDecl->name;
            epMolecule.xmlId = "m" + std::to_string(moleculeIndex + 1);
            for (std::size_t siteIndex = 0; siteIndex < molecule.sites.size(); ++siteIndex) {
                const auto& site = molecule.sites[siteIndex];
                if (!site.componentType.has_value()) { delete energyFunction; return false; }
                const auto runtimeName = runtimeComponentName(model, *site.componentType);
                if (runtimeName.empty()) { delete energyFunction; return false; }
                try { runtimeType->getCompIndexFromName(runtimeName); }
                catch (...) { delete energyFunction; return false; }

                NFcore::EpMolecule::CompInfo component;
                component.name = runtimeName;
                component.isBound = false;
                if (site.stateConstraintResolved.kind ==
                    bng::compile::StateConstraintKind::Exact) {
                    if (!site.stateConstraintResolved.exact.has_value()) {
                        delete energyFunction; return false;
                    }
                    const auto* stateName = model.stateName(*site.stateConstraintResolved.exact);
                    if (stateName == nullptr) { delete energyFunction; return false; }
                    component.stateConstraint = *stateName;
                } else if (site.stateConstraintResolved.kind ==
                           bng::compile::StateConstraintKind::Set) {
                    // NFsim's legacy energy matcher has only one state slot.
                    delete energyFunction;
                    return false;
                }
                epMolecule.components.push_back(std::move(component));

                const auto collect = [&](const bng::compile::PatternBondDescriptor& bond) {
                    if (bond.kind == bng::compile::BondConstraintKind::Exact &&
                        bond.group.value != 0) {
                        bondEndpoints[bond.group.value].push_back(
                            {static_cast<int>(moleculeIndex), static_cast<int>(siteIndex)});
                    }
                };
                if (site.bondConstraints.empty())
                    collect({site.bondConstraint, site.bondKind, site.bondGroup});
                else
                    for (const auto& bond : site.bondConstraints) collect(bond);
            }
            info.molecules.push_back(std::move(epMolecule));
        }

        for (const auto& [group, endpoints] : bondEndpoints) {
            (void)group;
            if (endpoints.size() != 2) { delete energyFunction; return false; }
            NFcore::EnergyPatternInfo::Bond bond;
            bond.mol1 = endpoints[0].molecule;
            bond.comp1 = endpoints[0].component;
            bond.mol2 = endpoints[1].molecule;
            bond.comp2 = endpoints[1].component;
            info.bonds.push_back(bond);
            auto& first = info.molecules[bond.mol1].components[bond.comp1];
            auto& second = info.molecules[bond.mol2].components[bond.comp2];
            first.isBound = true;
            second.isBound = true;
            first.bondPartnerId = info.molecules[bond.mol2].xmlId;
            second.bondPartnerId = info.molecules[bond.mol1].xmlId;
        }

        energyFunction->addEnergyPattern(info);
        if (verbose)
            std::cerr << "[nfsim/compiled] energy pattern " << info.id
                      << " = " << info.energyValue << "\n";
    }
    system->setEnergyFunction(energyFunction);
    return true;
}


bool addFunctionsFromCompiled(const bng::compile::CompiledModel& model,
                              NFcore::System* system, bool verbose,
                              const std::filesystem::path& sourcePath) {
    if (system == nullptr) return false;
    std::unordered_set<std::string> declared;
    for (const auto& function : model.functions()) {
        // reactant_N() declarations are compiler-visible placeholders for
        // CompositeFunction's per-reaction mapping counts, not user-defined
        // runtime functions.  They must not be registered as globals or
        // composites.
        if (function.arguments.empty() && isReactantCountName(function.name)) continue;
        if (function.name.empty() || !declared.insert(function.name).second ||
            function.arguments.size() > 1 ||
            system->getGlobalFunctionByName(function.name) != nullptr ||
            system->getCompositeFunctionByName(function.name) != nullptr ||
            system->getLocalFunctionByName(function.name) != nullptr) {
            return false;
        }
    }

    std::map<std::string, double> legacyParameters;
    for (const auto& parameter : model.parameters()) {
        if (parameter.constantValue.has_value())
            legacyParameters.emplace(parameter.name, *parameter.constantValue);
    }
    std::map<std::string, int> legacyAllowedStates;

    std::vector<const bng::compile::CompiledFunction*> deferredLocalComposites;
    // Build plain one-argument local functions first. A model-function call in
    // the expression makes the function a nested local composite and is
    // handled after base globals/locals are registered.
    for (const auto& function : model.functions()) {
        if (function.arguments.empty()) continue;
        ExpressionDependencies deps;
        collectDependencies(model, function.expression, deps);
        bool hasModelFunctionDependency = false;
        for (const auto& name : deps.functions)
            if (!isReactantCountName(name)) hasModelFunctionDependency = true;
        if (hasModelFunctionDependency) {
            deferredLocalComposites.push_back(&function);
            continue;
        }

        bool renderOk = true;
        const auto expression = expressionText(model, function.expression, renderOk);
        if (!renderOk) return false;
        std::vector<std::pair<std::string, std::string>> references;
        references.emplace_back(function.arguments.front(), "Local");
        for (const auto& parameter : deps.parameters)
            references.emplace_back(parameter, "Constant");
        for (const auto& observable : deps.observables)
            references.emplace_back(observable, "Observable");
        std::stable_sort(references.begin(), references.end(),
                         [](const auto& lhs, const auto& rhs) {
                             return lhs.first.size() > rhs.first.size();
                         });
        std::vector<std::string> referenceNames, referenceTypes;
        for (const auto& [name, type] : references) {
            referenceNames.push_back(name);
            referenceTypes.push_back(type);
        }
        auto argumentNames = function.arguments;
        if (!::createLocalFunction(function.name, expression, argumentNames,
                referenceNames, referenceTypes, system, legacyParameters, nullptr,
                legacyAllowedStates, verbose)) return false;
        auto* local = system->getLocalFunctionByName(function.name);
        if (local == nullptr) return false;
        std::vector<const bng::compile::ResolvedExpression*> tables;
        collectTableFunctions(function.expression, tables);
        if (tables.size() > 1) return false;
        if (!tables.empty()) {
            std::string diagnostic;
            if (!configureTableFunction(model, *tables.front(), sourcePath, system,
                                        nullptr, nullptr, local, diagnostic)) {
                if (verbose) std::cerr << "[nfsim/compiled] " << diagnostic << "\n";
                return false;
            }
        }
        if (deps.usesTime) {
            local->setTimeDependent(true);
            system->setHasTimeDependentFunctions(true);
        }
        std::vector<std::string> functionsCalled{function.name};
        std::vector<std::string> parameterNames;
        auto* wrapper = new NFcore::CompositeFunction(
            system, function.name,
            function.name + "(" + function.arguments.front() + ")",
            functionsCalled, argumentNames, parameterNames);
        if (!system->addCompositeFunction(wrapper)) { delete wrapper; return false; }
        if (verbose) std::cerr << "[nfsim/compiled] local function " << function.name << "\n";
    }

    struct Pending {
        const bng::compile::CompiledFunction* function = nullptr;
        ExpressionDependencies deps;
        std::string expression;
        std::vector<const bng::compile::ResolvedExpression*> tables;
    };
    std::vector<Pending> pending;
    for (const auto& function : model.functions()) {
        if (!function.arguments.empty() || isReactantCountName(function.name)) continue;
        Pending item;
        item.function = &function;
        collectDependencies(model, function.expression, item.deps);
        bool ok = true;
        item.expression = expressionText(model, function.expression, ok);
        if (!ok) return false;
        collectTableFunctions(function.expression, item.tables);
        if (item.tables.size() > 1 || item.deps.hasLocal) return false;
        pending.push_back(std::move(item));
    }

    std::unordered_set<std::string> built;
    for (const auto& function : model.functions())
        if (!function.arguments.empty() &&
            system->getCompositeFunctionByName(function.name) != nullptr)
            built.insert(function.name);

    bool progress = true;
    while (!pending.empty() && progress) {
        progress = false;
        for (auto it = pending.begin(); it != pending.end();) {
            const bool functionsReady = std::all_of(
                it->deps.functions.begin(), it->deps.functions.end(),
                [&](const auto& name) {
                    return isReactantCountName(name) || built.count(name) != 0;
                });
            if (!functionsReady) { ++it; continue; }

            std::vector<std::string> parameterNames(
                it->deps.parameters.begin(), it->deps.parameters.end());
            std::vector<std::string> modelFunctions;
            for (const auto& name : it->deps.functions) modelFunctions.push_back(name);
            if (modelFunctions.empty()) {
                std::vector<std::string> refs(
                    it->deps.observables.begin(), it->deps.observables.end());
                std::vector<std::string> refTypes(refs.size(), "Observable");
                auto* global = new NFcore::GlobalFunction(
                    it->function->name, it->expression, refs, refTypes,
                    parameterNames, system);
                if (!it->tables.empty()) {
                    std::string diagnostic;
                    if (!configureTableFunction(model, *it->tables.front(), sourcePath,
                                                system, global, nullptr, nullptr,
                                                diagnostic)) {
                        delete global; return false;
                    }
                }
                if (!system->addGlobalFunction(global)) { delete global; return false; }
                if (it->deps.usesTime && it->tables.empty()) {
                    global->setCounterFromTime(system);
                    system->setHasTimeDependentFunctions(true);
                }
            } else {
                std::map<std::string, std::string> observableAliases;
                std::size_t aliasIndex = 1;
                for (const auto& observableName : it->deps.observables) {
                    std::string aliasName = "__bng3_function_observable_" +
                                            it->function->name + "_" +
                                            std::to_string(aliasIndex++);
                    std::size_t aliasSuffix = 1;
                    while (system->getGlobalFunctionByName(aliasName) != nullptr ||
                           system->getCompositeFunctionByName(aliasName) != nullptr ||
                           system->getLocalFunctionByName(aliasName) != nullptr) {
                        aliasName = "__bng3_function_observable_" +
                                    it->function->name + "_" +
                                    std::to_string(aliasIndex - 1) + "_" +
                                    std::to_string(aliasSuffix++);
                    }
                    std::vector<std::string> references{observableName};
                    std::vector<std::string> referenceTypes{"Observable"};
                    std::vector<std::string> noParameters;
                    auto* alias = new NFcore::GlobalFunction(
                        aliasName, observableName, references, referenceTypes,
                        noParameters, system);
                    if (!system->addGlobalFunction(alias)) {
                        delete alias;
                        return false;
                    }
                    observableAliases.emplace(observableName, std::move(aliasName));
                }

                std::vector<std::string> functionsCalled;
                for (const auto& name : modelFunctions) functionsCalled.push_back(name);
                for (const auto& [observableName, aliasName] : observableAliases) {
                    (void)observableName;
                    functionsCalled.push_back(aliasName);
                }
                const auto compositeExpression = replaceCompiledObservableNames(
                    it->expression, observableAliases);
                std::vector<std::string> arguments;
                auto* composite = new NFcore::CompositeFunction(
                    system, it->function->name, compositeExpression,
                    functionsCalled, arguments, parameterNames);
                if (!it->tables.empty()) {
                    std::string diagnostic;
                    if (!configureTableFunction(model, *it->tables.front(), sourcePath,
                                                system, nullptr, composite, nullptr,
                                                diagnostic)) {
                        delete composite; return false;
                    }
                }
                if (!system->addCompositeFunction(composite)) { delete composite; return false; }
                if (it->deps.usesTime && it->tables.empty()) {
                    composite->setCounterFromTime(system);
                    system->setHasTimeDependentFunctions(true);
                }

            }
            if (verbose)
                std::cerr << "[nfsim/compiled] function " << it->function->name
                          << " = " << it->expression << "\n";
            built.insert(it->function->name);
            it = pending.erase(it);
            progress = true;
        }
    }
    if (!pending.empty()) return false;

    // Build one-level nested local functions as CompositeFunctions once their
    // plain local/global dependencies exist. This keeps local semantics in the
    // compiled model and avoids reparsing BNGL expression text.
    for (const auto* function : deferredLocalComposites) {
        ExpressionDependencies deps;
        collectDependencies(model, function->expression, deps);
        if (!deps.observables.empty()) return false;
        for (const auto& dependency : deps.functions) {
            if (isReactantCountName(dependency)) continue;
            if (system->getLocalFunctionByName(dependency) == nullptr &&
                system->getGlobalFunctionByName(dependency) == nullptr &&
                system->getCompositeFunctionByName(dependency) == nullptr)
                return false;
        }
        bool ok = true;
        const auto expression = expressionText(model, function->expression, ok);
        if (!ok) return false;
        std::vector<std::string> functionsCalled(deps.functions.begin(), deps.functions.end());
        auto argumentNames = function->arguments;
        std::vector<std::string> parameterNames(deps.parameters.begin(), deps.parameters.end());
        auto* composite = new NFcore::CompositeFunction(
            system, function->name, expression, functionsCalled,
            argumentNames, parameterNames);
        std::vector<const bng::compile::ResolvedExpression*> tables;
        collectTableFunctions(function->expression, tables);
        if (tables.size() > 1) { delete composite; return false; }
        if (!tables.empty()) {
            std::string diagnostic;
            if (!configureTableFunction(model, *tables.front(), sourcePath, system,
                                        nullptr, composite, nullptr, diagnostic)) {
                delete composite; return false;
            }
        }
        if (!system->addCompositeFunction(composite)) { delete composite; return false; }
        if (deps.usesTime && tables.empty()) {
            composite->setCounterFromTime(system);
            system->setHasTimeDependentFunctions(true);
        }
        built.insert(function->name);
    }

    system->finalizeCompositeFunctions();
    return true;
}


} // namespace NFinput
