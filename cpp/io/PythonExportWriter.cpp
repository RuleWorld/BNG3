#include "compile/CompiledModel.hpp"
#include "compile/TotalRate.hpp"
#include "PythonExportWriter.hpp"

#include "EnergyExportGuard.hpp"
#include "NetWriter.hpp"
#include "engine/DelayedSemanticsGuard.hpp"

#include <sstream>
#include <iomanip>
#include <algorithm>
#include <cctype>
#include <cmath>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <unordered_map>

#include "engine/ObservableProjection.hpp"
#include "parser/BNGAstVisitor.hpp"

namespace bng::io {

namespace {

std::string toLowerAscii(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return s;
}

std::string sanitizePyComment(const std::string& text) {
    std::string out;
    out.reserve(text.size());
    for (char c : text) {
        if (c == '\r' || c == '\n') out += ' ';
        else out += c;
    }
    return out;
}

std::string escapePyString(const std::string& text) {
    std::string out;
    out.reserve(text.size() + 8);
    for (char c : text) {
        switch (c) {
            case '\\': out += "\\\\"; break;
            case '\'': out += "\\'"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            default: out += c; break;
        }
    }
    return out;
}

bool isBalancedOuterParen(const std::string& s) {
    if (s.size() < 2 || s.front() != '(' || s.back() != ')') return false;
    int depth = 0;
    for (std::size_t i = 0; i < s.size(); ++i) {
        if (s[i] == '(') ++depth;
        else if (s[i] == ')') --depth;
        if (depth == 0 && i + 1 < s.size()) return false;
    }
    return depth == 0;
}

bool needsOuterParens(const std::string& s) {
    if (s.empty() || isBalancedOuterParen(s)) return false;
    int parenDepth = 0;
    int bracketDepth = 0;
    for (std::size_t i = 0; i < s.size(); ++i) {
        const char c = s[i];
        if (c == '(') { ++parenDepth; continue; }
        if (c == ')') { --parenDepth; continue; }
        if (c == '[') { ++bracketDepth; continue; }
        if (c == ']') { --bracketDepth; continue; }
        if (parenDepth == 0 && bracketDepth == 0) {
            if (!(std::isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '.')) {
                return true;
            }
        }
    }
    return false;
}

std::string wrapIfNeeded(const std::string& s) {
    return needsOuterParens(s) ? ("(" + s + ")") : s;
}

ast::Expression substituteExprArgs(
    const ast::Expression& expr,
    const std::unordered_map<std::string, ast::Expression>& argMap) {
    using Kind = ast::ExpressionKind;
    switch (expr.kind()) {
    case Kind::Number:
    case Kind::TableFunction:
        return expr;
    case Kind::Identifier: {
        if (auto it = argMap.find(expr.name()); it != argMap.end()) {
            return it->second;
        }
        return expr;
    }
    case Kind::Unary:
        return ast::Expression::unary(
            expr.name(), substituteExprArgs(expr.args().front(), argMap));
    case Kind::Binary:
        return ast::Expression::binary(
            expr.name(),
            substituteExprArgs(expr.args()[0], argMap),
            substituteExprArgs(expr.args()[1], argMap));
    case Kind::Function:
    case Kind::ObservableRef: {
        if (expr.args().empty()) {
            if (auto it = argMap.find(expr.name()); it != argMap.end()) {
                return it->second;
            }
        }
        std::vector<ast::Expression> args;
        args.reserve(expr.args().size());
        for (const auto& a : expr.args()) {
            args.push_back(substituteExprArgs(a, argMap));
        }
        return expr.kind() == Kind::Function
            ? ast::Expression::function(expr.name(), std::move(args))
            : ast::Expression::observableRef(expr.name(), std::move(args));
    }
    }
    return expr;
}

ast::Expression inlineModelFunctions(
    const ast::Expression& expr,
    const std::vector<ast::Function>& functions,
    const std::unordered_map<std::string, std::size_t>& paramIndex,
    const std::unordered_map<std::string, std::size_t>& obsIndex,
    int depth = 0) {
    if (depth >= 32) return expr;
    auto findFn = [&](const std::string& name, std::size_t arity) -> const ast::Function* {
        for (const auto& fn : functions) {
            if (fn.getName() == name && fn.getArgs().size() == arity) {
                return &fn;
            }
        }
        return nullptr;
    };
    using Kind = ast::ExpressionKind;
    switch (expr.kind()) {
    case Kind::Number:
    case Kind::TableFunction:
        return expr;
    case Kind::Identifier: {
        if (paramIndex.find(expr.name()) == paramIndex.end() &&
            obsIndex.find(expr.name()) == obsIndex.end()) {
            if (const auto* fn = findFn(expr.name(), 0)) {
                return inlineModelFunctions(fn->getExpression(), functions, paramIndex, obsIndex, depth + 1);
            }
        }
        return expr;
    }
    case Kind::Unary:
        return ast::Expression::unary(
            expr.name(),
            inlineModelFunctions(expr.args().front(), functions, paramIndex, obsIndex, depth));
    case Kind::Binary:
        return ast::Expression::binary(
            expr.name(),
            inlineModelFunctions(expr.args()[0], functions, paramIndex, obsIndex, depth),
            inlineModelFunctions(expr.args()[1], functions, paramIndex, obsIndex, depth));
    case Kind::Function:
    case Kind::ObservableRef: {
        std::vector<ast::Expression> inlinedArgs;
        inlinedArgs.reserve(expr.args().size());
        for (const auto& a : expr.args()) {
            inlinedArgs.push_back(inlineModelFunctions(a, functions, paramIndex, obsIndex, depth));
        }
        const bool shadowedBySymbol =
            inlinedArgs.empty() &&
            (obsIndex.find(expr.name()) != obsIndex.end() ||
             paramIndex.find(expr.name()) != paramIndex.end());
        if (!shadowedBySymbol) {
            if (const auto* fn = findFn(expr.name(), inlinedArgs.size())) {
                std::unordered_map<std::string, ast::Expression> argMap;
                for (std::size_t i = 0; i < fn->getArgs().size(); ++i) {
                    argMap.emplace(fn->getArgs()[i], inlinedArgs[i]);
                }
                const auto body = substituteExprArgs(fn->getExpression(), argMap);
                return inlineModelFunctions(body, functions, paramIndex, obsIndex, depth + 1);
            }
        }
        return expr.kind() == Kind::Function
            ? ast::Expression::function(expr.name(), std::move(inlinedArgs))
            : ast::Expression::observableRef(expr.name(), std::move(inlinedArgs));
    }
    }
    return expr;
}

std::optional<ast::Expression> parseRateLawExpression(const std::string& rawRate) {
    auto first = rawRate.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return std::nullopt;
    auto last = rawRate.find_last_not_of(" \t\r\n");
    std::string trimmed = rawRate.substr(first, last - first + 1);

    // Support .net space-separated special rate laws: "Sat k1 k2", "MM kcat Km", "Hill Vmax Kh n"
    std::string lower = toLowerAscii(trimmed);
    for (const char* kw : {"sat", "mm", "hill"}) {
        const std::size_t kwLen = std::char_traits<char>::length(kw);
        if (lower.rfind(kw, 0) == 0 && trimmed.size() > kwLen &&
            std::isspace(static_cast<unsigned char>(trimmed[kwLen])) != 0) {
            std::istringstream iss(trimmed.substr(kwLen));
            std::string tok;
            std::vector<std::string> toks;
            while (iss >> tok) toks.push_back(tok);
            if (!toks.empty() && toks.front().front() != '(') {
                std::ostringstream norm;
                norm << trimmed.substr(0, kwLen) << "(";
                for (std::size_t i = 0; i < toks.size(); ++i) {
                    if (i > 0) norm << ", ";
                    norm << toks[i];
                }
                norm << ")";
                trimmed = norm.str();
            }
            break;
        }
    }

    try {
        return bng::parser::parseExpression(trimmed);
    } catch (...) {
        return std::nullopt;
    }
}

ast::Expression expandTopLevelRateExpression(
    const ast::Expression& rawExpr,
    const ast::Rxn& rxn,
    const std::vector<ast::Function>& functions,
    const std::unordered_map<std::string, std::size_t>& paramIndex,
    const std::unordered_map<std::string, std::size_t>& obsIndex,
    bool& consumedReactants) {
    consumedReactants = false;
    if (rawExpr.kind() == ast::ExpressionKind::Function) {
        const std::string lower = toLowerAscii(rawExpr.name());
        const auto& reactants = rxn.getReactants();
        auto spRef = [](std::size_t idx) {
            return ast::Expression::identifier("__bng_sp_" + std::to_string(idx));
        };
        if ((lower == "sat" || lower == "mm" || lower == "hill") && !rawExpr.args().empty()) {
            std::vector<ast::Expression> args;
            args.reserve(rawExpr.args().size());
            for (const auto& a : rawExpr.args()) {
                args.push_back(inlineModelFunctions(a, functions, paramIndex, obsIndex));
            }
            if (lower == "sat") {
                if (args.size() == 1) {
                    consumedReactants = true;
                    return args[0];
                }
                if (!reactants.empty()) {
                    consumedReactants = true;
                    const std::size_t nDenom = std::min(args.size() - 1, reactants.size());
                    ast::Expression res = ast::Expression::function("Sat", {args[0], args[1], spRef(reactants[0])});
                    for (std::size_t ri = 1; ri < nDenom; ++ri) {
                        auto denom = ast::Expression::binary("+", args[ri + 1], spRef(reactants[ri]));
                        res = ast::Expression::binary(
                            "*", std::move(res),
                            ast::Expression::binary("/", spRef(reactants[ri]), std::move(denom)));
                    }
                    for (std::size_t ri = nDenom; ri < reactants.size(); ++ri) {
                        res = ast::Expression::binary("*", std::move(res), spRef(reactants[ri]));
                    }
                    return res;
                }
            } else if (lower == "mm" && args.size() >= 2 && !reactants.empty()) {
                consumedReactants = true;
                if (args.size() >= 3) {
                    ast::Expression res = ast::Expression::function("Sat", {args[0], args[1], args[2]});
                    for (std::size_t ri = 1; ri < reactants.size(); ++ri) {
                        res = ast::Expression::binary("*", std::move(res), spRef(reactants[ri]));
                    }
                    return res;
                }
                if (reactants.size() >= 2) {
                    ast::Expression res = ast::Expression::function(
                        "MM", {args[0], args[1], spRef(reactants[0]), spRef(reactants[1])});
                    for (std::size_t ri = 2; ri < reactants.size(); ++ri) {
                        res = ast::Expression::binary("*", std::move(res), spRef(reactants[ri]));
                    }
                    return res;
                }
                return ast::Expression::function("Sat", {args[0], args[1], spRef(reactants[0])});
            } else if (lower == "hill" && args.size() >= 2 && !reactants.empty()) {
                consumedReactants = true;
                const auto nExpr = (args.size() >= 3) ? args[2] : ast::Expression::number(1.0);
                ast::Expression res = ast::Expression::function(
                    "Hill", {args[0], args[1], nExpr, spRef(reactants[0])});
                for (std::size_t ri = 1; ri < reactants.size(); ++ri) {
                    res = ast::Expression::binary("*", std::move(res), spRef(reactants[ri]));
                }
                return res;
            }
        }
    }
    return inlineModelFunctions(rawExpr, functions, paramIndex, obsIndex);
}

std::string renderExprToPython(
    const ast::Expression& expr,
    const std::unordered_map<std::string, std::size_t>& paramIndex,
    const std::unordered_map<std::string, std::size_t>& obsIndex) {
    using Kind = ast::ExpressionKind;
    switch (expr.kind()) {
    case Kind::Number: {
        std::ostringstream out;
        out << std::setprecision(17) << expr.numberValue();
        return out.str();
    }
    case Kind::Identifier: {
        const auto& name = expr.name();
        if (name.rfind("__bng_sp_", 0) == 0) {
            return "species[" + name.substr(9) + "]";
        }
        if (auto it = paramIndex.find(name); it != paramIndex.end()) {
            return "expressions[" + std::to_string(it->second) + "]";
        }
        if (auto it = obsIndex.find(name); it != obsIndex.end()) {
            return "observables[" + std::to_string(it->second) + "]";
        }
        if (name == "time") return "t";
        if (name == "_pi" || name == "pi" || name == "_PI") return "math.pi";
        if (name == "_e" || name == "e") return "math.e";
        return name;
    }
    case Kind::Unary: {
        const auto arg = renderExprToPython(expr.args().front(), paramIndex, obsIndex);
        if (expr.name() == "-" || expr.name() == "+") {
            return "(" + expr.name() + "(" + arg + "))";
        }
        if (expr.name() == "!" || expr.name() == "~") {
            return "(1.0 if (" + arg + ") == 0.0 else 0.0)";
        }
        return arg;
    }
    case Kind::Binary: {
        const auto lhs = renderExprToPython(expr.args()[0], paramIndex, obsIndex);
        const auto rhs = renderExprToPython(expr.args()[1], paramIndex, obsIndex);
        const auto& op = expr.name();
        if (op == "^" || op == "**") {
            return "((" + lhs + ") ** (" + rhs + "))";
        }
        if (op == "%") {
            return "math.fmod(" + lhs + ", " + rhs + ")";
        }
        if (op == "~=") {
            return "(1.0 if (" + lhs + ") != (" + rhs + ") else 0.0)";
        }
        if (op == "&&") {
            return "(1.0 if ((" + lhs + ") != 0.0 and (" + rhs + ") != 0.0) else 0.0)";
        }
        if (op == "||") {
            return "(1.0 if ((" + lhs + ") != 0.0 or (" + rhs + ") != 0.0) else 0.0)";
        }
        if (op == "^^") {
            return "(1.0 if (((" + lhs + ") != 0.0) != ((" + rhs + ") != 0.0)) else 0.0)";
        }
        if (op == "==" || op == "!=" || op == "<" || op == "<=" || op == ">" || op == ">=") {
            return "(1.0 if ((" + lhs + ") " + op + " (" + rhs + ")) else 0.0)";
        }
        return "(" + lhs + " " + op + " " + rhs + ")";
    }
    case Kind::Function:
    case Kind::ObservableRef: {
        const auto& name = expr.name();
        if (expr.args().empty()) {
            if (auto it = obsIndex.find(name); it != obsIndex.end()) {
                return "observables[" + std::to_string(it->second) + "]";
            }
            if (auto it = paramIndex.find(name); it != paramIndex.end()) {
                return "expressions[" + std::to_string(it->second) + "]";
            }
            if (name == "time") return "t";
        }
        std::vector<std::string> rendered;
        rendered.reserve(expr.args().size());
        for (const auto& a : expr.args()) {
            rendered.push_back(renderExprToPython(a, paramIndex, obsIndex));
        }
        const std::string lowerName = toLowerAscii(name);
        if ((lowerName == "sat" || lowerName == "mm") && rendered.size() == 3) {
            return "((" + rendered[0] + ") * (" + rendered[2] + ") / ((" + rendered[1] + ") + (" + rendered[2] + ")))";
        }
        if (lowerName == "mm" && rendered.size() == 4) {
            const auto& kcat = rendered[0];
            const auto& km = rendered[1];
            const auto& st = rendered[2];
            const auto& et = rendered[3];
            return "(2.0 * (" + kcat + ") * (" + st + ") * (" + et + ") / (((" + st + ") + (" + km + ") + (" + et +
                   ")) + math.sqrt((((" + st + ") - (" + km + ") - (" + et + ")) ** 2.0) + 4.0 * (" + st + ") * (" + km + "))))";
        }
        if (lowerName == "hill" && rendered.size() == 4) {
            const auto& vmax = rendered[0];
            const auto& kh = rendered[1];
            const auto& n = rendered[2];
            const auto& s = rendered[3];
            return "((" + vmax + ") * ((" + s + ") ** (" + n + ")) / (((" + kh + ") ** (" + n + ")) + ((" + s + ") ** (" + n + "))))";
        }
        auto joinArgs = [&]() {
            std::ostringstream oss;
            for (std::size_t i = 0; i < rendered.size(); ++i) {
                if (i > 0) oss << ", ";
                oss << rendered[i];
            }
            return oss.str();
        };
        if (name == "if" && rendered.size() == 3) {
            return "((" + rendered[1] + ") if ((" + rendered[0] + ") != 0.0) else (" + rendered[2] + "))";
        }
        if ((name == "ln" || name == "log") && rendered.size() == 1) {
            return "math.log(" + rendered[0] + ")";
        }
        if (name == "ceiling" && rendered.size() == 1) {
            return "math.ceil(" + rendered[0] + ")";
        }
        if (name == "abs" && rendered.size() == 1) {
            return "abs(" + rendered[0] + ")";
        }
        if (name == "rint" && rendered.size() == 1) {
            return "math.floor((" + rendered[0] + ") + 0.5)";
        }
        if (name == "sign" && rendered.size() == 1) {
            return "(1.0 if (" + rendered[0] + ") > 0.0 else (-1.0 if (" + rendered[0] + ") < 0.0 else 0.0))";
        }
        if ((name == "min" || name == "max") && !rendered.empty()) {
            if (rendered.size() == 1) return rendered[0];
            return name + "(" + joinArgs() + ")";
        }
        if (name == "sum") {
            if (rendered.empty()) return "0.0";
            return "sum([" + joinArgs() + "])";
        }
        if (name == "avg" && !rendered.empty()) {
            return "(sum([" + joinArgs() + "]) / " + std::to_string(rendered.size()) + ".0)";
        }
        static const std::set<std::string> kMathFuncs = {
            "exp", "log10", "log2", "sqrt",
            "sin", "cos", "tan", "asin", "acos", "atan",
            "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
            "floor", "ceil", "fabs"
        };
        if (kMathFuncs.count(name) > 0) {
            return "math." + name + "(" + joinArgs() + ")";
        }
        return name + "(" + joinArgs() + ")";
    }
    case Kind::TableFunction:
        return expr.toString();
    }
    return expr.toString();
}

} // namespace

std::string PythonExportWriter::write(const ast::Model& model, const engine::GeneratedNetwork& network) {
    Options opts;
    return write(model, network, opts);
}

std::string PythonExportWriter::write(const ast::Model& model, const engine::GeneratedNetwork& network, const Options& opts) {
    const auto rxnDelays = engine::collectConstantReactionDelays(model, network, "Python export");
    const bool hasDelayedRxns = std::any_of(
        rxnDelays.begin(), rxnDelays.end(), [](double d) { return d > 0.0; });
    requireNoEnergySemantics(model, "Python export");
    compile::requireNoNativeEvents(model, "Python export");
    std::ostringstream py;

    const std::string modelName = model.getModelName();
    const std::size_t nSpecies = network.species.size();
    const std::size_t nRxns = network.reactions.size();

    // Compute observable groups and stoichiometry
    auto groups = computeObservableGroups(model, network);
    auto stoich = computeStoichiometry(network, nSpecies);

    // Collect parameter info
    std::vector<std::string> paramNames;
    std::vector<double> paramValues;
    for (const auto& param : model.getParameters().all()) {
        paramNames.push_back(param.getName());
        paramValues.push_back(param.getValue());
    }
    const std::size_t nParams = paramNames.size();

    // Detect fixed species
    std::vector<bool> fixedSpecies(nSpecies, false);
    for (std::size_t i = 0; i < nSpecies; ++i) {
        fixedSpecies[i] = network.species.get(i).isConstant();
    }

    // ===== Header =====
    const std::string safeCommentName = sanitizePyComment(modelName);
    py << "# " << safeCommentName << "_pyode.py\n";
    py << "#\n";
    py << "# Python " << (hasDelayedRxns ? "DDE" : "ODE") << " simulation of BioNetGen model '" << safeCommentName << "'.\n";
    py << "# Generated by BioNetGen C++\n";
    py << "#\n";
    py << "# Requires: numpy, scipy\n";
    py << "#   pip install numpy scipy\n";
    py << "#\n";
    py << "# Usage:\n";
    py << "#   python " << safeCommentName << "_pyode.py\n";
    py << "#\n\n";

    // ===== Imports =====
    py << "import math\n";
    py << "import numpy as np\n";
    if (hasDelayedRxns) {
        py << "from scipy.integrate import solve_ivp\n";
    } else {
        py << "from scipy.integrate import odeint\n";
    }
    py << "import sys\n";
    py << "import os\n\n";

    // ===== Parameters =====
    py << "# Model dimensions\n";
    py << "N_SPECIES = " << nSpecies << "\n";
    py << "N_OBSERVABLES = " << groups.size() << "\n";
    py << "N_REACTIONS = " << nRxns << "\n";
    py << "N_PARAMETERS = " << nParams << "\n\n";

    py << "# Parameter names\n";
    py << "param_names = [\n";
    for (std::size_t i = 0; i < nParams; ++i) {
        py << "    '" << escapePyString(paramNames[i]) << "',\n";
    }
    py << "]\n\n";

    py << "# Default parameters\n";
    py << "default_parameters = np.array([\n";
    for (std::size_t i = 0; i < nParams; ++i) {
        py << "    " << std::setprecision(17) << paramValues[i] << ",";
        py << "  # " << sanitizePyComment(paramNames[i]) << "\n";
    }
    py << "])\n\n";

    // ===== Species names and initial conditions =====
    py << "# Species names\n";
    py << "species_names = [\n";
    for (std::size_t i = 0; i < nSpecies; ++i) {
        const auto& sp = network.species.get(i);
        py << "    '" << escapePyString(sp.getSpeciesGraph().toString()) << "',\n";
    }
    py << "]\n\n";

    py << "# Default initial species concentrations\n";
    py << "default_y0 = np.array([\n";
    for (std::size_t i = 0; i < nSpecies; ++i) {
        const auto& sp = network.species.get(i);
        py << "    " << std::setprecision(17) << sp.getAmount() << ",";
        py << "  # " << sanitizePyComment(sp.getSpeciesGraph().toString()) << "\n";
    }
    py << "])\n\n";

    // ===== Observable names =====
    py << "# Observable names\n";
    py << "observable_names = [\n";
    for (std::size_t g = 0; g < groups.size(); ++g) {
        py << "    '" << escapePyString(groups[g].name) << "',\n";
    }
    py << "]\n\n";

    std::unordered_map<std::string, std::size_t> paramIndex;
    for (std::size_t i = 0; i < nParams; ++i) {
        paramIndex[paramNames[i]] = i;
    }
    std::unordered_map<std::string, std::size_t> obsIndex;
    for (std::size_t g = 0; g < groups.size(); ++g) {
        obsIndex[groups[g].name] = g;
    }

    // ===== calc_expressions =====
    py << "def calc_expressions(parameters):\n";
    py << "    \"\"\"Calculate expressions from parameters.\"\"\"\n";
    py << "    expressions = np.zeros(" << nParams << ")\n";
    {
        const auto& allParams = model.getParameters().all();
        std::vector<int> state(nParams, 0);
        std::vector<std::size_t> order;
        std::function<void(std::size_t)> visit = [&](std::size_t idx) {
            if (state[idx] != 0) return;
            state[idx] = 1;
            for (const auto& dep : allParams[idx].getExpression().getDependencies()) {
                auto it = paramIndex.find(dep);
                if (it != paramIndex.end()) visit(it->second);
            }
            state[idx] = 2;
            order.push_back(idx);
        };
        for (std::size_t i = 0; i < nParams; ++i) visit(i);
        for (const std::size_t i : order) {
            const auto& expr = allParams[i].getExpression();
            const auto deps = expr.getDependencies();
            bool allKnown = !deps.empty();
            for (const auto& dep : deps) {
                if (paramIndex.find(dep) == paramIndex.end()) {
                    allKnown = false;
                    break;
                }
            }
            if (allKnown) {
                const auto expandedParam = inlineModelFunctions(
                    expr, model.getFunctions(), paramIndex, obsIndex);
                py << "    expressions[" << i << "] = "
                   << renderExprToPython(expandedParam, paramIndex, obsIndex);
            } else {
                py << "    expressions[" << i << "] = parameters[" << i << "]";
            }
            py << "  # " << sanitizePyComment(paramNames[i]) << "\n";
        }
    }
    py << "    return expressions\n\n";

    // ===== calc_observables =====
    py << "def calc_observables(species, expressions):\n";
    py << "    \"\"\"Calculate observables from species concentrations.\"\"\"\n";
    py << "    observables = np.zeros(" << groups.size() << ")\n";
    for (std::size_t g = 0; g < groups.size(); ++g) {
        if (groups[g].entries.empty()) {
            py << "    observables[" << g << "] = 0";
        } else {
            py << "    observables[" << g << "] = ";
            bool first = true;
            for (const auto& [specIdx, weight] : groups[g].entries) {
                if (!first) py << " + ";
                if (weight > 1) {
                    py << weight << "*";
                }
                py << "species[" << specIdx << "]";
                first = false;
            }
        }
        py << "  # " << sanitizePyComment(groups[g].name) << "\n";
    }
    py << "    return observables\n\n";

    // ===== calc_ratelaws =====
    py << "def calc_ratelaws(species, expressions, observables, t=0.0):\n";
    py << "    \"\"\"Calculate rate laws.\"\"\"\n";
    py << "    ratelaws = np.zeros(" << nRxns << ")\n";
    for (std::size_t r = 0; r < nRxns; ++r) {
        const auto& rxn = network.reactions.all()[r];
        py << "    ratelaws[" << r << "] = ";

        const std::string& rateLaw = rxn.getRateLaw();
        std::string cleanRate = rateLaw;
        auto localPos = cleanRate.find("|local:");
        if (localPos != std::string::npos) {
            cleanRate = cleanRate.substr(0, localPos);
        }

        const bool absoluteFlux = compile::isAbsoluteFluxReaction(model, rxn);
        const bool totalRate =
            compile::isTotalRateReaction(model, rxn.getOriginRuleName()) ||
            absoluteFlux;
        double statFactor = totalRate ? 1.0 : rxn.getFactor();
        if (!totalRate && !absoluteFlux) {
            if (const auto unitFactor = NetWriter::computeUnitConversionFactor(rxn, model, network);
                unitFactor.has_value()) {
                statFactor *= *unitFactor;
            }
        }

        bool consumedReactants = false;
        std::optional<ast::Expression> parsedRate = rxn.getRateExpression();
        if (!parsedRate.has_value()) {
            parsedRate = parseRateLawExpression(cleanRate);
        }

        if (parsedRate.has_value()) {
            const auto expanded = ast::partialEvaluate(
                expandTopLevelRateExpression(
                    *parsedRate, rxn, model.getFunctions(), paramIndex, obsIndex, consumedReactants),
                model.getFunctions());
            if (expanded.kind() == ast::ExpressionKind::Number) {
                py << std::setprecision(17) << (statFactor * expanded.numberValue());
            } else {
                const std::string rateRef = renderExprToPython(expanded, paramIndex, obsIndex);
                const bool willMultiply =
                    (std::abs(statFactor - 1.0) > 1e-12) ||
                    (!absoluteFlux && !consumedReactants && !rxn.getReactants().empty());
                const std::string safeRef = willMultiply ? wrapIfNeeded(rateRef) : rateRef;
                if (std::abs(statFactor - 1.0) > 1e-12) {
                    py << std::setprecision(17) << statFactor << "*" << safeRef;
                } else {
                    py << safeRef;
                }
            }
        } else {
            bool isNumeric = false;
            double rateVal = 0.0;
            try {
                std::size_t pos = 0;
                rateVal = std::stod(cleanRate, &pos);
                if (pos == cleanRate.size()) isNumeric = true;
            } catch (...) {}

            if (isNumeric) {
                double combined = statFactor * rateVal;
                py << std::setprecision(17) << combined;
            } else {
                std::string rateRef = convertRateToPython(cleanRate, paramNames);
                const bool willMultiply =
                    (std::abs(statFactor - 1.0) > 1e-12) ||
                    (!absoluteFlux && !consumedReactants && !rxn.getReactants().empty());
                const std::string safeRef = willMultiply ? wrapIfNeeded(rateRef) : rateRef;
                if (std::abs(statFactor - 1.0) > 1e-12) {
                    py << std::setprecision(17) << statFactor << "*" << safeRef;
                } else {
                    py << safeRef;
                }
            }
        }

        // Multiply by reactant concentrations (unless absoluteFlux or special rate law already includes them)
        if (!absoluteFlux && !consumedReactants) {
            for (const auto idx : rxn.getReactants()) {
                py << "*species[" << idx << "]";
            }
        }

        py << "\n";
    }
    py << "    return ratelaws\n\n";

    // ===== dydt / DDE RHS and simulation =====
    if (hasDelayedRxns) {
        // Group positive delays into unique lag slots.
        std::vector<std::string> lagExprs;
        std::vector<int> rxnLagIdx(nRxns, -1);
        std::map<std::string, int> lagExprMap;
        for (std::size_t r = 0; r < nRxns; ++r) {
            if (rxnDelays[r] > 0.0) {
                const auto& rxn = network.reactions.all()[r];
                std::string exprPy;
                if (rxn.getDelayExpression()) {
                    const auto expandedDelay = ast::partialEvaluate(*rxn.getDelayExpression(), model.getFunctions());
                    exprPy = renderExprToPython(expandedDelay, paramIndex, {});
                } else {
                    std::ostringstream ds;
                    ds << std::setprecision(17) << rxnDelays[r];
                    exprPy = ds.str();
                }
                auto it = lagExprMap.find(exprPy);
                if (it == lagExprMap.end()) {
                    const int idx = static_cast<int>(lagExprs.size());
                    lagExprMap.emplace(exprPy, idx);
                    lagExprs.push_back(exprPy);
                    rxnLagIdx[r] = idx;
                } else {
                    rxnLagIdx[r] = it->second;
                }
            }
        }

        // Split stoichiometry into immediate (current state) and delayed (lag k) terms.
        // Ordinary (delay==0): both reactants (-) and products (+) are immediate.
        // Consuming delayed: reactants (-) are immediate; products (+) are delayed at lag k.
        // NonConsuming delayed: both reactants (-) and products (+) are delayed at lag k.
        std::vector<std::map<std::size_t, int>> immStoich(nSpecies);
        std::vector<std::vector<std::map<std::size_t, int>>> delStoich(
            nSpecies, std::vector<std::map<std::size_t, int>>(lagExprs.size()));
        for (std::size_t r = 0; r < nRxns; ++r) {
            const auto& rxn = network.reactions.all()[r];
            const int lag = rxnLagIdx[r];
            if (lag < 0) {
                for (const auto idx : rxn.getReactants()) immStoich[idx][r] -= 1;
                for (const auto idx : rxn.getProducts()) immStoich[idx][r] += 1;
            } else if (!rxn.isNonConsuming()) {
                for (const auto idx : rxn.getReactants()) immStoich[idx][r] -= 1;
                for (const auto idx : rxn.getProducts()) delStoich[idx][static_cast<std::size_t>(lag)][r] += 1;
            } else {
                for (const auto idx : rxn.getReactants()) delStoich[idx][static_cast<std::size_t>(lag)][r] -= 1;
                for (const auto idx : rxn.getProducts()) delStoich[idx][static_cast<std::size_t>(lag)][r] += 1;
            }
        }

        py << "def calc_lags(expressions):\n";
        py << "    \"\"\"Calculate constant reaction delay lags from parameters.\"\"\"\n";
        py << "    return np.array([\n";
        for (std::size_t k = 0; k < lagExprs.size(); ++k) {
            py << "        float(" << lagExprs[k] << "),\n";
        }
        py << "    ], dtype=float)\n\n";

        py << "def dydt_dde(t, species, history_fn, expressions, lags, active_lags):\n";
        py << "    \"\"\"DDE right-hand side: species derivatives with constant reaction delays.\"\"\"\n";
        py << "    observables = calc_observables(species, expressions)\n";
        py << "    ratelaws = calc_ratelaws(species, expressions, observables, t)\n";
        py << "    delayed_ratelaws = []\n";
        py << "    for lag, is_active in zip(lags, active_lags):\n";
        py << "        if is_active:\n";
        py << "            y_del = history_fn(t - lag)\n";
        py << "            obs_del = calc_observables(y_del, expressions)\n";
        py << "            delayed_ratelaws.append(calc_ratelaws(y_del, expressions, obs_del, t - lag))\n";
        py << "        else:\n";
        py << "            delayed_ratelaws.append(np.zeros(N_REACTIONS))\n";
        py << "\n";
        py << "    Dspecies = np.zeros(" << nSpecies << ")\n";
        for (std::size_t i = 0; i < nSpecies; ++i) {
            py << "    Dspecies[" << i << "] = ";
            if (fixedSpecies[i]) {
                py << "0  # fixed species\n";
                continue;
            }
            bool first = true;
            auto emitTerm = [&](const std::string& arrExpr, int coeff) {
                if (coeff == 0) return;
                if (first) {
                    if (coeff == 1) py << arrExpr;
                    else if (coeff == -1) py << "-" << arrExpr;
                    else py << coeff << "*" << arrExpr;
                } else {
                    if (coeff == 1) py << " + " << arrExpr;
                    else if (coeff == -1) py << " - " << arrExpr;
                    else if (coeff > 0) py << " + " << coeff << "*" << arrExpr;
                    else py << " - " << (-coeff) << "*" << arrExpr;
                }
                first = false;
            };
            for (const auto& [rxnIdx, coeff] : immStoich[i]) {
                emitTerm("ratelaws[" + std::to_string(rxnIdx) + "]", coeff);
            }
            for (std::size_t k = 0; k < lagExprs.size(); ++k) {
                for (const auto& [rxnIdx, coeff] : delStoich[i][k]) {
                    emitTerm("delayed_ratelaws[" + std::to_string(k) + "][" + std::to_string(rxnIdx) + "]", coeff);
                }
            }
            if (first) py << "0";
            py << "\n";
        }
        py << "\n";
        py << "    return Dspecies\n\n";

        py << "def _dde_breakpoints(t0, t_end, lags):\n";
        py << "    \"\"\"Collect exact method-of-steps discontinuity breakpoints and sub-intervals <= min(lags).\"\"\"\n";
        py << "    pos_lags = sorted(set(float(d) for d in lags if d > 0.0))\n";
        py << "    if not pos_lags:\n";
        py << "        return [t0, t_end]\n";
        py << "    min_lag = pos_lags[0]\n";
        py << "    pts = {t0, t_end}\n";
        py << "    frontier = [t0]\n";
        py << "    while frontier and len(pts) < 4096:\n";
        py << "        cur = frontier.pop(0)\n";
        py << "        for lag in pos_lags:\n";
        py << "            nxt = cur + lag\n";
        py << "            if nxt < t_end - 1e-12:\n";
        py << "                if all(abs(nxt - existing) > 1e-12 for existing in pts):\n";
        py << "                    pts.add(nxt)\n";
        py << "                    frontier.append(nxt)\n";
        py << "    ordered = sorted(pts)\n";
        py << "    refined = [ordered[0]]\n";
        py << "    for nxt in ordered[1:]:\n";
        py << "        cur = refined[-1]\n";
        py << "        while nxt - cur > min_lag + 1e-12:\n";
        py << "            cur = min(cur + min_lag, nxt)\n";
        py << "            refined.append(cur)\n";
        py << "        if nxt > refined[-1] + 1e-15:\n";
        py << "            refined.append(nxt)\n";
        py << "    return refined\n\n";

        py << "def simulate(timepoints=None, species_init=None, parameters=None):\n";
        py << "    \"\"\"Run method-of-steps DDE simulation and return (timepoints, species_out, observables_out).\"\"\"\n";
        py << "    if timepoints is None:\n";
        py << "        timepoints = np.linspace(" << opts.tStart << ", " << opts.tEnd << ", " << (opts.nSteps + 1) << ")\n";
        py << "    timepoints = np.asarray(timepoints, dtype=float)\n";
        py << "    if species_init is None:\n";
        py << "        species_init = default_y0.copy()\n";
        py << "    else:\n";
        py << "        species_init = np.asarray(species_init, dtype=float).copy()\n";
        py << "    if parameters is None:\n";
        py << "        parameters = default_parameters.copy()\n";
        py << "    else:\n";
        py << "        parameters = np.asarray(parameters, dtype=float).copy()\n\n";
        py << "    expressions = calc_expressions(parameters)\n";
        py << "    lags = calc_lags(expressions)\n";
        py << "    if not np.all(np.isfinite(lags)) or np.any(lags < 0.0):\n";
        py << "        raise ValueError('Delayed reaction times must be finite and nonnegative')\n\n";
        py << "    t0 = float(timepoints[0])\n";
        py << "    t_end = float(timepoints[-1])\n";
        py << "    segments = []  # (t_a, t_b, OdeSolution)\n";
        py << "    y_curr = species_init.copy()\n\n";
        py << "    def history_fn(t_query):\n";
        py << "        if t_query <= t0 or not segments:\n";
        py << "            return species_init\n";
        py << "        for seg_a, seg_b, seg_sol in segments:\n";
        py << "            if t_query <= seg_b + 1e-12:\n";
        py << "                return seg_sol(min(max(t_query, seg_a), seg_b))\n";
        py << "        return segments[-1][2](segments[-1][1])\n\n";
        py << "    if t_end > t0:\n";
        py << "        knots = _dde_breakpoints(t0, t_end, lags)\n";
        py << "        for seg_a, seg_b in zip(knots[:-1], knots[1:]):\n";
        py << "            seg_mid = 0.5 * (seg_a + seg_b)\n";
        py << "            active_lags = [seg_mid >= t0 + float(lag) for lag in lags]\n";
        py << "            sol = solve_ivp(\n";
        py << "                lambda t, y, _al=active_lags: dydt_dde(t, y, history_fn, expressions, lags, _al),\n";
        py << "                (seg_a, seg_b),\n";
        py << "                y_curr,\n";
        py << "                method='RK45',\n";
        py << "                dense_output=True,\n";
        py << "                atol=" << std::scientific << opts.atol << ",\n";
        py << "                rtol=" << opts.rtol << ",\n";
        py << std::defaultfloat;
        py << "            )\n";
        py << "            if not sol.success:\n";
        py << "                raise RuntimeError(f'DDE integration failed on [{seg_a}, {seg_b}]: {sol.message}')\n";
        py << "            segments.append((seg_a, seg_b, sol.sol))\n";
        py << "            y_curr = sol.y[:, -1].copy()\n\n";
        py << "    species_out = np.zeros((len(timepoints), N_SPECIES))\n";
        py << "    for i, tp in enumerate(timepoints):\n";
        py << "        species_out[i, :] = history_fn(float(tp))\n\n";
        py << "    observables_out = np.zeros((len(timepoints), N_OBSERVABLES))\n";
        py << "    for i in range(len(timepoints)):\n";
        py << "        observables_out[i, :] = calc_observables(species_out[i, :], expressions)\n\n";
        py << "    return timepoints, species_out, observables_out\n\n";
    } else {
        // ===== dydt =====
        py << "def dydt(species, t, parameters):\n";
        py << "    \"\"\"ODE right-hand side: species derivatives.\"\"\"\n";
        py << "    expressions = calc_expressions(parameters)\n";
        py << "    observables = calc_observables(species, expressions)\n";
        py << "    ratelaws = calc_ratelaws(species, expressions, observables, t)\n";
        py << "\n";
        py << "    Dspecies = np.zeros(" << nSpecies << ")\n";

        for (std::size_t i = 0; i < nSpecies; ++i) {
            py << "    Dspecies[" << i << "] = ";
            if (fixedSpecies[i]) {
                py << "0  # fixed species\n";
                continue;
            }

            bool found = false;
            for (const auto& entry : stoich) {
                if (entry.speciesIndex == i) {
                    found = true;
                    bool first = true;
                    for (const auto& [rxnIdx, coeff] : entry.rxnCoeffs) {
                        if (first) {
                            if (coeff == 1) {
                                py << "ratelaws[" << rxnIdx << "]";
                            } else if (coeff == -1) {
                                py << "-ratelaws[" << rxnIdx << "]";
                            } else {
                                py << coeff << "*ratelaws[" << rxnIdx << "]";
                            }
                        } else {
                            if (coeff == 1) {
                                py << " + ratelaws[" << rxnIdx << "]";
                            } else if (coeff == -1) {
                                py << " - ratelaws[" << rxnIdx << "]";
                            } else if (coeff > 0) {
                                py << " + " << coeff << "*ratelaws[" << rxnIdx << "]";
                            } else {
                                py << " - " << (-coeff) << "*ratelaws[" << rxnIdx << "]";
                            }
                        }
                        first = false;
                    }
                    break;
                }
            }
            if (!found) {
                py << "0";
            }
            py << "\n";
        }

        py << "\n";
        py << "    return Dspecies\n\n";

        // ===== Main simulation =====
        py << "def simulate(timepoints=None, species_init=None, parameters=None):\n";
        py << "    \"\"\"Run ODE simulation and return (timepoints, species_out, observables_out).\"\"\"\n";
        py << "    if timepoints is None:\n";
        py << "        timepoints = np.linspace(" << opts.tStart << ", " << opts.tEnd << ", " << (opts.nSteps + 1) << ")\n";
        py << "    if species_init is None:\n";
        py << "        species_init = default_y0.copy()\n";
        py << "    if parameters is None:\n";
        py << "        parameters = default_parameters.copy()\n";
        py << "\n";
        py << "    # Integrate ODEs\n";
        py << "    species_out = odeint(dydt, species_init, timepoints, args=(parameters,),\n";
        py << "                        atol=" << std::scientific << opts.atol << ", rtol=" << opts.rtol << ")\n";
        py << std::defaultfloat;
        py << "\n";
        py << "    # Calculate observables at each timepoint\n";
        py << "    expressions = calc_expressions(parameters)\n";
        py << "    observables_out = np.zeros((len(timepoints), N_OBSERVABLES))\n";
        py << "    for i in range(len(timepoints)):\n";
        py << "        observables_out[i, :] = calc_observables(species_out[i, :], expressions)\n";
        py << "\n";
        py << "    return timepoints, species_out, observables_out\n\n";
    }

    // ===== Main block =====
    py << "if __name__ == '__main__':\n";
    py << "    # Parse optional command-line arguments: t_end n_steps\n";
    py << "    t_end = " << opts.tEnd << "\n";
    py << "    n_steps = " << opts.nSteps << "\n";
    py << "    if len(sys.argv) > 1:\n";
    py << "        t_end = float(sys.argv[1])\n";
    py << "    if len(sys.argv) > 2:\n";
    py << "        n_steps = int(sys.argv[2])\n";
    py << "\n";
    py << "    timepoints = np.linspace(" << opts.tStart << ", t_end, n_steps + 1)\n";
    py << "    timepoints_sim, species_out, observables_out = simulate(timepoints)\n";
    py << "\n";
    py << "    # Write .cdat file (time + species concentrations)\n";
    if (modelName.empty()) {
        py << "    model_name = os.path.splitext(os.path.basename(__file__))[0]\n";
        py << "    if model_name.endswith('_pyode'):\n";
        py << "        model_name = model_name[:-len('_pyode')]\n";
    } else {
        py << "    model_name = '" << escapePyString(modelName) << "'\n";
    }
    py << "    cdat_path = model_name + '.cdat'\n";
    py << "    with open(cdat_path, 'w') as f:\n";
    py << "        # Header\n";
    py << "        header = '{:<18s}'.format('#') + '  '.join('{:<18s}'.format('time') if i == 0 else '{:<18s}'.format(species_names[i-1]) for i in range(N_SPECIES + 1))\n";
    py << "        f.write(header + '\\n')\n";
    py << "        # Actually write: first column is time\n";
    py << "        for i in range(len(timepoints_sim)):\n";
    py << "            line = '{:<18.12e}'.format(timepoints_sim[i])\n";
    py << "            for j in range(N_SPECIES):\n";
    py << "                line += '  {:<18.12e}'.format(species_out[i, j])\n";
    py << "            f.write(line + '\\n')\n";
    py << "    print(f'Wrote species output to {cdat_path}')\n";
    py << "\n";
    py << "    # Write .gdat file (time + observables)\n";
    py << "    gdat_path = model_name + '.gdat'\n";
    py << "    with open(gdat_path, 'w') as f:\n";
    py << "        # Header\n";
    py << "        header = '{:<18s}'.format('#          time')\n";
    py << "        for name in observable_names:\n";
    py << "            header += '  {:<18s}'.format(name)\n";
    py << "        f.write(header + '\\n')\n";
    py << "        for i in range(len(timepoints_sim)):\n";
    py << "            line = '{:<18.12e}'.format(timepoints_sim[i])\n";
    py << "            for j in range(N_OBSERVABLES):\n";
    py << "                line += '  {:<18.12e}'.format(observables_out[i, j])\n";
    py << "            f.write(line + '\\n')\n";
    py << "    print(f'Wrote observables output to {gdat_path}')\n";

    return py.str();
}

std::string PythonExportWriter::convertRateToPython(const std::string& rate, const std::vector<std::string>& paramNames) {
    std::string result = rate;

    // Replace parameter names with expressions[i] - longer names first
    std::vector<std::pair<std::size_t, std::string>> sorted;
    for (std::size_t i = 0; i < paramNames.size(); ++i) {
        sorted.push_back({i, paramNames[i]});
    }
    std::sort(sorted.begin(), sorted.end(), [](const auto& a, const auto& b) {
        return a.second.size() > b.second.size();
    });

    for (const auto& [idx, name] : sorted) {
        std::string paramRef = "expressions[" + std::to_string(idx) + "]";
        std::size_t pos = 0;
        while ((pos = result.find(name, pos)) != std::string::npos) {
            bool validStart = (pos == 0 || (!std::isalnum(static_cast<unsigned char>(result[pos - 1])) && result[pos - 1] != '_'));
            bool validEnd = (pos + name.length() >= result.length() ||
                           (!std::isalnum(static_cast<unsigned char>(result[pos + name.length()])) && result[pos + name.length()] != '_'));
            if (validStart && validEnd) {
                result.replace(pos, name.length(), paramRef);
                pos += paramRef.length();
            } else {
                pos += name.length();
            }
        }
    }

    // Replace ^ with ** for Python exponentiation
    std::size_t pos = 0;
    while ((pos = result.find('^', pos)) != std::string::npos) {
        result.replace(pos, 1, "**");
        pos += 2;
    }

    // Prefix bare math function calls with math. so exported Python never throws NameError
    static const std::vector<std::pair<std::string, std::string>> kMathCalls = {
        {"ceiling", "math.ceil"},
        {"asinh", "math.asinh"},
        {"acosh", "math.acosh"},
        {"atanh", "math.atanh"},
        {"log10", "math.log10"},
        {"floor", "math.floor"},
        {"sinh", "math.sinh"},
        {"cosh", "math.cosh"},
        {"tanh", "math.tanh"},
        {"asin", "math.asin"},
        {"acos", "math.acos"},
        {"atan", "math.atan"},
        {"sqrt", "math.sqrt"},
        {"log2", "math.log2"},
        {"ceil", "math.ceil"},
        {"fabs", "math.fabs"},
        {"exp", "math.exp"},
        {"log", "math.log"},
        {"sin", "math.sin"},
        {"cos", "math.cos"},
        {"tan", "math.tan"},
        {"ln", "math.log"},
    };
    for (const auto& [fn, replacement] : kMathCalls) {
        std::size_t fpos = 0;
        while ((fpos = result.find(fn, fpos)) != std::string::npos) {
            const bool validStart = (fpos == 0 ||
                (!std::isalnum(static_cast<unsigned char>(result[fpos - 1])) &&
                 result[fpos - 1] != '_' && result[fpos - 1] != '.'));
            std::size_t after = fpos + fn.size();
            const bool validEnd = (after >= result.size() ||
                (!std::isalnum(static_cast<unsigned char>(result[after])) &&
                 result[after] != '_'));
            std::size_t parenPos = after;
            while (parenPos < result.size() &&
                   std::isspace(static_cast<unsigned char>(result[parenPos])) != 0) {
                ++parenPos;
            }
            const bool isCall = (parenPos < result.size() && result[parenPos] == '(');
            if (validStart && validEnd && isCall) {
                result.replace(fpos, fn.size(), replacement);
                fpos += replacement.size();
            } else {
                fpos += fn.size();
            }
        }
    }

    return result;
}

std::vector<PythonExportWriter::ObservableGroup> PythonExportWriter::computeObservableGroups(
    const ast::Model& model, const engine::GeneratedNetwork& network) {
    std::vector<ObservableGroup> groups;
    std::unique_ptr<compile::CompiledModel> compiledModel;
    std::unique_ptr<engine::ObservableProjection> projection;
    const auto ensureProjection = [&]() {
        if (!projection) {
            compiledModel = std::make_unique<compile::CompiledModel>(model);
            projection = std::make_unique<engine::ObservableProjection>(*compiledModel);
        }
    };

    const auto& observables = model.getObservables();
    groups.reserve(observables.size());

    for (std::size_t observableIndex = 0; observableIndex < observables.size(); ++observableIndex) {
        const auto& observable = observables[observableIndex];
        ObservableGroup group;
        group.name = observable.getName();
        group.type = observable.getType();

        if (const auto& indexed = observable.getIndexedSpeciesWeights(); indexed.has_value()) {
            for (const auto& [speciesIndex, rawWeight] : *indexed) {
                if (speciesIndex < network.species.size() && rawWeight > 0.0) {
                    const auto w = static_cast<std::size_t>(std::llround(rawWeight));
                    if (w > 0) {
                        group.entries.push_back({speciesIndex, w});
                    }
                }
            }
            groups.push_back(std::move(group));
            continue;
        }

        ensureProjection();
        for (std::size_t speciesIndex = 0; speciesIndex < network.species.size(); ++speciesIndex) {
            const auto& species = network.species.get(speciesIndex);
            const auto weight = projection->weight(
                observableIndex,
                species.getSpeciesGraph().getGraph(),
                species.getCompartment());
            if (weight > 0) {
                group.entries.push_back({speciesIndex, static_cast<std::size_t>(weight)});
            }
        }

        groups.push_back(std::move(group));
    }

    return groups;
}

std::vector<PythonExportWriter::StoichEntry> PythonExportWriter::computeStoichiometry(
    const engine::GeneratedNetwork& network, std::size_t nSpecies) {
    std::map<std::size_t, std::map<std::size_t, int>> stoichMap;

    for (std::size_t r = 0; r < network.reactions.size(); ++r) {
        const auto& rxn = network.reactions.all()[r];
        for (const auto idx : rxn.getReactants()) {
            stoichMap[idx][r] -= 1;
        }
        for (const auto idx : rxn.getProducts()) {
            stoichMap[idx][r] += 1;
        }
    }

    std::vector<StoichEntry> result;
    for (auto& [specIdx, rxnMap] : stoichMap) {
        StoichEntry entry;
        entry.speciesIndex = specIdx;
        for (auto& [rxnIdx, coeff] : rxnMap) {
            if (coeff != 0) {
                entry.rxnCoeffs.push_back({rxnIdx, coeff});
            }
        }
        if (!entry.rxnCoeffs.empty()) {
            result.push_back(std::move(entry));
        }
    }

    return result;
}

} // namespace bng::io
