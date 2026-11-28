#include "compile/CompiledModel.hpp"
#include "compile/TotalRate.hpp"
#include "MatlabWriter.hpp"

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

std::string sanitizeMatlabComment(const std::string& text) {
    std::string out;
    out.reserve(text.size());
    for (char c : text) {
        if (c == '\r' || c == '\n') out += ' ';
        else out += c;
    }
    return out;
}

std::string escapeMatlabString(const std::string& text) {
    std::string out;
    out.reserve(text.size() + 8);
    for (char c : text) {
        if (c == '\'') out += "''";
        else if (c == '\r' || c == '\n') out += ' ';
        else out += c;
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
    for (std::size_t i = 0; i < s.size(); ++i) {
        const char c = s[i];
        if (c == '(') { ++parenDepth; continue; }
        if (c == ')') { --parenDepth; continue; }
        if (parenDepth == 0) {
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

std::string renderExprToMatlab(
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
            const std::size_t idx = std::stoull(name.substr(9));
            return "species(" + std::to_string(idx + 1) + ")";
        }
        if (auto it = paramIndex.find(name); it != paramIndex.end()) {
            return "expressions(" + std::to_string(it->second + 1) + ")";
        }
        if (auto it = obsIndex.find(name); it != obsIndex.end()) {
            return "observables(" + std::to_string(it->second + 1) + ")";
        }
        if (name == "time") return "t";
        if (name == "_pi" || name == "pi" || name == "_PI") return "pi";
        if (name == "_e" || name == "e") return "exp(1)";
        return name;
    }
    case Kind::Unary: {
        const auto arg = renderExprToMatlab(expr.args().front(), paramIndex, obsIndex);
        if (expr.name() == "-" || expr.name() == "+") {
            return "(" + expr.name() + "(" + arg + "))";
        }
        if (expr.name() == "!" || expr.name() == "~") {
            return "double((" + arg + ") == 0)";
        }
        return arg;
    }
    case Kind::Binary: {
        const auto lhs = renderExprToMatlab(expr.args()[0], paramIndex, obsIndex);
        const auto rhs = renderExprToMatlab(expr.args()[1], paramIndex, obsIndex);
        const auto& op = expr.name();
        if (op == "^" || op == "**") {
            return "((" + lhs + ") ^ (" + rhs + "))";
        }
        if (op == "%") {
            return "mod(" + lhs + ", " + rhs + ")";
        }
        if (op == "!=" || op == "~=") {
            return "double((" + lhs + ") ~= (" + rhs + "))";
        }
        if (op == "&&") {
            return "double(((" + lhs + ") ~= 0) && ((" + rhs + ") ~= 0))";
        }
        if (op == "||") {
            return "double(((" + lhs + ") ~= 0) || ((" + rhs + ") ~= 0))";
        }
        if (op == "^^") {
            return "double(xor((" + lhs + ") ~= 0, (" + rhs + ") ~= 0))";
        }
        if (op == "==" || op == "<" || op == "<=" || op == ">" || op == ">=") {
            return "double((" + lhs + ") " + op + " (" + rhs + "))";
        }
        return "(" + lhs + " " + op + " " + rhs + ")";
    }
    case Kind::Function:
    case Kind::ObservableRef: {
        const auto& name = expr.name();
        if (expr.args().empty()) {
            if (auto it = obsIndex.find(name); it != obsIndex.end()) {
                return "observables(" + std::to_string(it->second + 1) + ")";
            }
            if (auto it = paramIndex.find(name); it != paramIndex.end()) {
                return "expressions(" + std::to_string(it->second + 1) + ")";
            }
            if (name == "time") return "t";
        }
        std::vector<std::string> rendered;
        rendered.reserve(expr.args().size());
        for (const auto& a : expr.args()) {
            rendered.push_back(renderExprToMatlab(a, paramIndex, obsIndex));
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
                   ")) + sqrt((((" + st + ") - (" + km + ") - (" + et + ")) ^ 2) + 4.0 * (" + st + ") * (" + km + "))))";
        }
        if (lowerName == "hill" && rendered.size() == 4) {
            const auto& vmax = rendered[0];
            const auto& kh = rendered[1];
            const auto& n = rendered[2];
            const auto& s = rendered[3];
            return "((" + vmax + ") * ((" + s + ") ^ (" + n + ")) / (((" + kh + ") ^ (" + n + ")) + ((" + s + ") ^ (" + n + "))))";
        }
        if (name == "if" && rendered.size() == 3) {
            return "bng_if(" + rendered[0] + ", " + rendered[1] + ", " + rendered[2] + ")";
        }
        if (name == "ln" && rendered.size() == 1) return "log(" + rendered[0] + ")";
        if (name == "ceiling" && rendered.size() == 1) return "ceil(" + rendered[0] + ")";
        if (name == "fabs" && rendered.size() == 1) return "abs(" + rendered[0] + ")";
        if (name == "rint" && rendered.size() == 1) return "round(" + rendered[0] + ")";
        if (name == "sum") {
            if (rendered.empty()) return "0";
            std::string acc = "(" + rendered[0];
            for (std::size_t i = 1; i < rendered.size(); ++i) acc += " + " + rendered[i];
            return acc + ")";
        }
        if (name == "avg" && !rendered.empty()) {
            std::string acc = "((" + rendered[0];
            for (std::size_t i = 1; i < rendered.size(); ++i) acc += " + " + rendered[i];
            return acc + ") / " + std::to_string(rendered.size()) + ")";
        }
        if ((name == "min" || name == "max") && rendered.size() > 2) {
            std::string acc = name + "(" + rendered[0] + ", " + rendered[1] + ")";
            for (std::size_t i = 2; i < rendered.size(); ++i) {
                acc = name + "(" + acc + ", " + rendered[i] + ")";
            }
            return acc;
        }
        std::ostringstream call;
        call << name << "(";
        for (std::size_t i = 0; i < rendered.size(); ++i) {
            if (i > 0) call << ", ";
            call << rendered[i];
        }
        call << ")";
        return call.str();
    }
    case Kind::TableFunction:
        return expr.toString();
    }
    return expr.toString();
}

} // namespace

std::string MatlabWriter::makeMatlabFunctionName(const std::string& modelName) {
    std::string name = modelName;
    std::transform(name.begin(), name.end(), name.begin(), [](char c) {
        return std::isalnum(static_cast<unsigned char>(c)) ? c : '_';
    });
    if (!name.empty() && std::isdigit(static_cast<unsigned char>(name[0]))) {
        name = "model_" + name;
    }
    return name.empty() ? "bng_model" : name;
}

std::string MatlabWriter::write(const ast::Model& model, const engine::GeneratedNetwork& network) {
    Options opts;
    return write(model, network, opts);
}

std::string MatlabWriter::write(const ast::Model& model, const engine::GeneratedNetwork& network, const Options& opts) {
    const auto rxnDelays = engine::collectConstantReactionDelays(model, network, "MATLAB export");
    const bool hasDelayedRxns = std::any_of(
        rxnDelays.begin(), rxnDelays.end(), [](double d) { return d > 0.0; });
    requireNoEnergySemantics(model, "MATLAB M-file");
    compile::requireNoNativeEvents(model, "MATLAB export");
    std::ostringstream m;

    std::string funcName = makeMatlabFunctionName(model.getModelName());
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
    std::unordered_map<std::string, std::size_t> paramIndex;
    for (std::size_t i = 0; i < paramNames.size(); ++i) {
        paramIndex[paramNames[i]] = i;
    }
    std::unordered_map<std::string, std::size_t> obsIndex;
    for (std::size_t g = 0; g < groups.size(); ++g) {
        obsIndex[groups[g].name] = g;
    }

    // Detect fixed species ($ prefix)
    std::vector<bool> fixedSpecies(nSpecies, false);
    for (std::size_t i = 0; i < nSpecies; ++i) {
        fixedSpecies[i] = network.species.get(i).isConstant();
    }

    // Function header (Perl parity: 4 outputs, 4 inputs)
    m << "function [err, timepoints, species_out, observables_out] = " << funcName
      << "(timepoints, species_init, parameters, suppress_plot)\n";
    m << "%% " << funcName << " - MATLAB " << (hasDelayedRxns ? "DDE" : "ODE") << " model\n";
    m << "%% Generated by BioNetGen C++\n";
    m << "%%\n";
    m << "%% Usage:\n";
    m << "%%   [err, timepoints, species_out, observables_out] = " << funcName << "()\n";
    m << "%%   [err, timepoints, species_out, observables_out] = " << funcName << "(timepoints, species_init, parameters)\n\n";

    // Default input handling
    m << "%% Default parameters, initial conditions, and calculation handlers\n";
    m << "if (nargin < 1)\n";
    m << "    timepoints = linspace(" << opts.tStart << ", " << opts.tEnd << ", " << (opts.nSteps + 1) << ")';\n";
    m << "end\n";
    m << "if (nargin < 2)\n";
    m << "    species_init = getInitialSpecies();\n";
    m << "end\n";
    m << "if (nargin < 3)\n";
    m << "    parameters = getDefaultParameters();\n";
    m << "end\n";
    m << "if (nargin < 4)\n";
    m << "    suppress_plot = 0;\n";
    m << "end\n\n";

    // Validate dimensions
    m << "%% Validate input dimensions\n";
    m << "if (length(parameters) ~= " << paramNames.size() << ")\n";
    m << "    error('parameters must have " << paramNames.size() << " elements');\n";
    m << "end\n";
    m << "if (length(species_init) ~= " << nSpecies << ")\n";
    m << "    error('species_init must have " << nSpecies << " elements');\n";
    m << "end\n\n";

    // Number of observables and species
    m << "%% Model dimensions\n";
    m << "n_species = " << nSpecies << ";\n";
    m << "n_observables = " << groups.size() << ";\n";
    m << "n_ratelaws = " << nRxns << ";\n\n";

    // Collect distinct positive delay lag expressions when DDE mode is active.
    std::vector<std::string> lagExprs;
    std::vector<int> rxnLagIdx(nRxns, -1);
    if (hasDelayedRxns) {
        std::map<std::string, int> lagExprMap;
        for (std::size_t r = 0; r < nRxns; ++r) {
            if (rxnDelays[r] > 0.0) {
                const auto& rxn = network.reactions.all()[r];
                std::string exprMat;
                if (rxn.getDelayExpression()) {
                    exprMat = convertRateToMatlab(rxn.getDelayExpression()->toString(), paramNames);
                } else {
                    std::ostringstream ds;
                    ds << std::setprecision(15) << rxnDelays[r];
                    exprMat = ds.str();
                }
                auto it = lagExprMap.find(exprMat);
                if (it == lagExprMap.end()) {
                    const int idx = static_cast<int>(lagExprs.size());
                    lagExprMap.emplace(exprMat, idx);
                    lagExprs.push_back(exprMat);
                    rxnLagIdx[r] = idx;
                } else {
                    rxnLagIdx[r] = it->second;
                }
            }
        }
    }

    if (hasDelayedRxns) {
        // DDE solver options (constant delays via dde23)
        m << "%% DDE solver options\n";
        m << "expressions = calc_expressions(parameters);\n";
        m << "lags = [";
        for (std::size_t k = 0; k < lagExprs.size(); ++k) {
            if (k > 0) m << ", ";
            m << lagExprs[k];
        }
        m << "];\n";
        m << "if any(~isfinite(lags)) || any(lags <= 0)\n";
        m << "    error('Delayed reaction times must be finite and positive');\n";
        m << "end\n";
        m << "t0 = timepoints(1);\n";
        m << "dde_jumps = unique([t0 + lags, t0 + 2*lags]);\n";
        m << "dde_jumps = dde_jumps(dde_jumps > t0 & dde_jumps < timepoints(end));\n";
        m << "ddeopts = ddeset(";
        m << "'RelTol', " << opts.rtol;
        m << ", 'AbsTol', " << opts.atol;
        m << ", 'Stats', '" << (opts.stats ? "on" : "off") << "'";
        m << ", 'Jumps', dde_jumps";
        if (opts.maxStep > 0.0) {
            m << ", 'MaxStep', " << opts.maxStep;
        }
        m << ");\n\n";

        // Solve DDE
        m << "%% Solve DDE\n";
        m << "try\n";
        m << "    sol = dde23(@(t, y, Z) calc_species_deriv_dde(t, y, Z, parameters, t0, lags), "
          << "lags, @(t) species_init(:), [timepoints(1), timepoints(end)], ddeopts);\n";
        m << "    species_out = deval(sol, timepoints)';\n";
        m << "catch e\n";
        m << "    err = 1;\n";
        m << "    fprintf('Integration error: %s\\n', e.message);\n";
        m << "    timepoints = [];\n";
        m << "    species_out = [];\n";
        m << "    observables_out = [];\n";
        m << "    return;\n";
        m << "end\n\n";
    } else {
        // ODE solver options
        m << "%% ODE solver options\n";
        m << "odeopts = odeset(";
        m << "'RelTol', " << opts.rtol;
        m << ", 'AbsTol', " << opts.atol;
        m << ", 'Stats', '" << (opts.stats ? "on" : "off") << "'";
        m << ", 'BDF', '" << (opts.bdf ? "on" : "off") << "'";
        m << ", 'MaxOrder', " << opts.maxOrder;
        if (opts.maxStep > 0.0) {
            m << ", 'MaxStep', " << opts.maxStep;
        }
        m << ");\n\n";

        // Solve
        m << "%% Solve ODE\n";
        m << "try\n";
        m << "    [~, species_out] = ode15s(@(t,y) calc_species_deriv(t, y, parameters), timepoints, species_init, odeopts);\n";
        m << "catch e\n";
        m << "    err = 1;\n";
        m << "    fprintf('Integration error: %s\\n', e.message);\n";
        m << "    timepoints = [];\n";
        m << "    species_out = [];\n";
        m << "    observables_out = [];\n";
        m << "    return;\n";
        m << "end\n\n";
    }

    // Compute observables at each time point
    m << "%% Compute observables at each time point\n";
    m << "observables_out = zeros(length(timepoints), n_observables);\n";
    m << "for t_idx = 1:length(timepoints)\n";
    m << "    observables_out(t_idx, :) = calc_observables(species_out(t_idx, :)', parameters);\n";
    m << "end\n\n";

    // Plot
    m << "%% Plot results\n";
    m << "if (~suppress_plot)\n";
    m << "    figure;\n";
    if (!groups.empty()) {
        m << "    plot(timepoints, observables_out);\n";
        m << "    legend(";
        for (std::size_t i = 0; i < groups.size(); ++i) {
            if (i > 0) m << ", ";
            m << "'" << escapeMatlabString(groups[i].name) << "'";
        }
        m << ", 'Location', 'best');\n";
        m << "    ylabel('Number', 'FontSize', 12);\n";
    } else {
        m << "    plot(timepoints, species_out);\n";
        m << "    ylabel('Species Count', 'FontSize', 12);\n";
    }
    m << "    xlabel('Time', 'FontSize', 12);\n";
    m << "    title('" << escapeMatlabString(model.getModelName()) << "', 'FontSize', 14);\n";
    m << "end\n\n";

    m << "err = 0;\n";
    m << "return;\n\n";

    // ===== Nested function: getDefaultParameters =====
    m << "%% Default parameters\n";
    m << "function p = getDefaultParameters()\n";
    m << "    p = zeros(" << paramNames.size() << ", 1);\n";
    for (std::size_t i = 0; i < paramNames.size(); ++i) {
        m << "    p(" << (i + 1) << ") = " << std::setprecision(15) << paramValues[i]
          << "; % " << paramNames[i] << "\n";
    }
    m << "end\n\n";

    // ===== Nested function: getInitialSpecies =====
    m << "%% Default initial species concentrations\n";
    m << "function y0 = getInitialSpecies()\n";
    m << "    y0 = zeros(" << nSpecies << ", 1);\n";
    for (std::size_t i = 0; i < nSpecies; ++i) {
        const auto& sp = network.species.get(i);
        m << "    y0(" << (i + 1) << ") = " << sp.getAmount()
          << "; % " << sp.getSpeciesGraph().toString() << "\n";
    }
    m << "end\n\n";

    // ===== Nested function: calc_expressions =====
    m << "%% Calculate expressions from parameters\n";
    m << "function expressions = calc_expressions(parameters)\n";
    m << "    expressions = zeros(" << paramNames.size() << ", 1);\n";
    {
        const auto& allParams = model.getParameters().all();
        // Topological order so derived parameters evaluate after their dependencies
        std::vector<int> state(paramNames.size(), 0);
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
        for (std::size_t i = 0; i < paramNames.size(); ++i) visit(i);
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
                m << "    expressions(" << (i + 1) << ") = "
                  << renderExprToMatlab(expandedParam, paramIndex, obsIndex)
                  << "; % " << sanitizeMatlabComment(paramNames[i]) << "\n";
            } else {
                m << "    expressions(" << (i + 1) << ") = parameters(" << (i + 1)
                  << "); % " << sanitizeMatlabComment(paramNames[i]) << "\n";
            }
        }
    }
    m << "end\n\n";

    // ===== Nested function: calc_observables =====
    m << "%% Calculate observables from species\n";
    m << "function observables = calc_observables(species, parameters)\n";
    m << "    observables = zeros(" << groups.size() << ", 1);\n";
    for (std::size_t g = 0; g < groups.size(); ++g) {
        if (groups[g].entries.empty()) {
            m << "    observables(" << (g + 1) << ") = 0; % " << sanitizeMatlabComment(groups[g].name) << "\n";
        } else {
            m << "    observables(" << (g + 1) << ") = ";
            bool first = true;
            for (const auto& [specIdx, weight] : groups[g].entries) {
                if (!first) m << " + ";
                if (weight > 1) {
                    m << weight << "*";
                }
                m << "species(" << (specIdx + 1) << ")";
                first = false;
            }
            m << "; % " << sanitizeMatlabComment(groups[g].name) << "\n";
        }
    }
    m << "end\n\n";

    // ===== Nested function: calc_ratelaws =====
    m << "%% Calculate rate laws\n";
    m << "function ratelaws = calc_ratelaws(species, expressions, observables, t)\n";
    m << "    if (nargin < 4)\n";
    m << "        t = 0;\n";
    m << "    end\n";
    m << "    ratelaws = zeros(" << nRxns << ", 1);\n";
    for (std::size_t r = 0; r < nRxns; ++r) {
        const auto& rxn = network.reactions.all()[r];
        m << "    ratelaws(" << (r + 1) << ") = ";

        // Rate constant
        const std::string& rateLaw = rxn.getRateLaw();
        // Strip |local: suffix
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
                m << std::setprecision(17) << (statFactor * expanded.numberValue());
            } else {
                const std::string rateRef = renderExprToMatlab(expanded, paramIndex, obsIndex);
                const bool willMultiply =
                    (std::abs(statFactor - 1.0) > 1e-12) ||
                    (!absoluteFlux && !consumedReactants && !rxn.getReactants().empty());
                const std::string safeRef = willMultiply ? wrapIfNeeded(rateRef) : rateRef;
                if (std::abs(statFactor - 1.0) > 1e-12) {
                    m << std::setprecision(17) << statFactor << "*" << safeRef;
                } else {
                    m << safeRef;
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
                m << std::setprecision(17) << combined;
            } else {
                std::string rateRef = convertRateToMatlab(cleanRate, paramNames);
                const bool willMultiply =
                    (std::abs(statFactor - 1.0) > 1e-12) ||
                    (!absoluteFlux && !consumedReactants && !rxn.getReactants().empty());
                const std::string safeRef = willMultiply ? wrapIfNeeded(rateRef) : rateRef;
                if (std::abs(statFactor - 1.0) > 1e-12) {
                    m << std::setprecision(17) << statFactor << "*" << safeRef;
                } else {
                    m << safeRef;
                }
            }
        }

        // Multiply by reactant concentrations (unless absoluteFlux or special rate law already includes them)
        if (!absoluteFlux && !consumedReactants) {
            for (const auto idx : rxn.getReactants()) {
                m << "*species(" << (idx + 1) << ")";
            }
        }

        m << ";\n";
    }
    m << "end\n\n";

    if (hasDelayedRxns) {
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

        // ===== Nested function: calc_species_deriv_dde =====
        m << "%% Species derivative function with constant reaction delays\n";
        m << "function Dspecies = calc_species_deriv_dde(t, species, Z, parameters, t0, lags)\n";
        m << "    expressions = calc_expressions(parameters);\n";
        m << "    observables = calc_observables(species, parameters);\n";
        m << "    ratelaws = calc_ratelaws(species, expressions, observables, t);\n";
        m << "    delayed_ratelaws = zeros(" << nRxns << ", " << lagExprs.size() << ");\n";
        m << "    for lag_i = 1:" << lagExprs.size() << "\n";
        m << "        if (t >= t0 + lags(lag_i))\n";
        m << "            y_del = Z(:, lag_i);\n";
        m << "            obs_del = calc_observables(y_del, parameters);\n";
        m << "            delayed_ratelaws(:, lag_i) = calc_ratelaws(y_del, expressions, obs_del, t - lags(lag_i));\n";
        m << "        end\n";
        m << "    end\n\n";
        m << "    Dspecies = zeros(" << nSpecies << ", 1);\n\n";

        for (std::size_t i = 0; i < nSpecies; ++i) {
            if (fixedSpecies[i]) {
                m << "    Dspecies(" << (i + 1) << ") = 0; % fixed species\n";
                continue;
            }
            bool anyTerm = !immStoich[i].empty();
            for (std::size_t k = 0; k < lagExprs.size() && !anyTerm; ++k) {
                if (!delStoich[i][k].empty()) anyTerm = true;
            }
            if (!anyTerm) continue;

            m << "    Dspecies(" << (i + 1) << ") = ";
            bool first = true;
            auto emitTerm = [&](const std::string& arrExpr, int coeff) {
                if (coeff == 0) return;
                if (first) {
                    if (coeff == 1) m << arrExpr;
                    else if (coeff == -1) m << "-" << arrExpr;
                    else m << coeff << "*" << arrExpr;
                } else {
                    if (coeff == 1) m << " + " << arrExpr;
                    else if (coeff == -1) m << " - " << arrExpr;
                    else if (coeff > 0) m << " + " << coeff << "*" << arrExpr;
                    else m << " - " << (-coeff) << "*" << arrExpr;
                }
                first = false;
            };
            for (const auto& [rxnIdx, coeff] : immStoich[i]) {
                emitTerm("ratelaws(" + std::to_string(rxnIdx + 1) + ")", coeff);
            }
            for (std::size_t k = 0; k < lagExprs.size(); ++k) {
                for (const auto& [rxnIdx, coeff] : delStoich[i][k]) {
                    emitTerm("delayed_ratelaws(" + std::to_string(rxnIdx + 1) + ", " +
                             std::to_string(k + 1) + ")", coeff);
                }
            }
            if (first) m << "0";
            m << ";\n";
        }
        m << "end\n\n";
    } else {
        // ===== Nested function: calc_species_deriv =====
        m << "%% Species derivative function\n";
        m << "function Dspecies = calc_species_deriv(t, species, parameters)\n";
        m << "    expressions = calc_expressions(parameters);\n";
        m << "    observables = calc_observables(species, parameters);\n";
        m << "    ratelaws = calc_ratelaws(species, expressions, observables, t);\n\n";
        m << "    Dspecies = zeros(" << nSpecies << ", 1);\n\n";

        // Use stoichiometry to build derivatives
        for (const auto& entry : stoich) {
            if (fixedSpecies[entry.speciesIndex]) {
                m << "    Dspecies(" << (entry.speciesIndex + 1) << ") = 0; % fixed species\n";
            } else if (entry.rxnCoeffs.empty()) {
                // No reactions affect this species - derivative is 0
                continue;
            } else {
                m << "    Dspecies(" << (entry.speciesIndex + 1) << ") = ";
                bool first = true;
                for (const auto& [rxnIdx, coeff] : entry.rxnCoeffs) {
                    if (first) {
                        if (coeff == 1) {
                            m << "ratelaws(" << (rxnIdx + 1) << ")";
                        } else if (coeff == -1) {
                            m << "-ratelaws(" << (rxnIdx + 1) << ")";
                        } else {
                            m << coeff << "*ratelaws(" << (rxnIdx + 1) << ")";
                        }
                    } else {
                        if (coeff == 1) {
                            m << " + ratelaws(" << (rxnIdx + 1) << ")";
                        } else if (coeff == -1) {
                            m << " - ratelaws(" << (rxnIdx + 1) << ")";
                        } else if (coeff > 0) {
                            m << " + " << coeff << "*ratelaws(" << (rxnIdx + 1) << ")";
                        } else {
                            m << " - " << (-coeff) << "*ratelaws(" << (rxnIdx + 1) << ")";
                        }
                    }
                    first = false;
                }
                m << ";\n";
            }
        }

        m << "end\n\n";
    }

    if (m.str().find("bng_if(") != std::string::npos) {
        m << "%% Conditional helper for BNGL if(cond, a, b)\n";
        m << "function val = bng_if(cond, a, b)\n";
        m << "    if (cond ~= 0)\n";
        m << "        val = a;\n";
        m << "    else\n";
        m << "        val = b;\n";
        m << "    end\n";
        m << "end\n\n";
    }

    m << "end % main function\n";

    return m.str();
}

std::string MatlabWriter::convertRateToMatlab(const std::string& rate, const std::vector<std::string>& paramNames) {
    std::string result = rate;

    // Replace parameter names with expressions(i) - longer names first to avoid partial matches
    std::vector<std::pair<std::size_t, std::string>> sorted;
    for (std::size_t i = 0; i < paramNames.size(); ++i) {
        sorted.push_back({i, paramNames[i]});
    }
    // Sort by name length descending to prevent partial matches
    std::sort(sorted.begin(), sorted.end(), [](const auto& a, const auto& b) {
        return a.second.size() > b.second.size();
    });

    for (const auto& [idx, name] : sorted) {
        std::string paramRef = "expressions(" + std::to_string(idx + 1) + ")";
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

    // MATLAB uses `log` for natural logarithm and `^` for exponentiation
    {
        std::size_t pos = 0;
        while ((pos = result.find("ln(", pos)) != std::string::npos) {
            const bool validStart = (pos == 0 || (!std::isalnum(static_cast<unsigned char>(result[pos - 1])) && result[pos - 1] != '_'));
            if (validStart) {
                result.replace(pos, 2, "log");
                pos += 4;
            } else {
                pos += 3;
            }
        }
    }
    {
        std::size_t pos = 0;
        while ((pos = result.find("**", pos)) != std::string::npos) {
            result.replace(pos, 2, "^");
            pos += 1;
        }
    }

    return result;
}

std::vector<MatlabWriter::ObservableGroup> MatlabWriter::computeObservableGroups(
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

std::vector<MatlabWriter::StoichEntry> MatlabWriter::computeStoichiometry(
    const engine::GeneratedNetwork& network, std::size_t nSpecies) {
    // Build stoichiometry map: species -> list of (rxn, coeff)
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

std::string MatlabWriter::writeInitSpecies(
    const ast::Model& model,
    const engine::GeneratedNetwork& network
) {
    (void)engine::collectConstantReactionDelays(model, network, "MATLAB export");
    requireNoEnergySemantics(model, "MATLAB M-file");
    compile::requireNoNativeEvents(model, "MATLAB export");
    const std::size_t nSpecies = network.species.size();
    std::ostringstream m;
    m << "function [species_init] = initialize_species( params )\n\n";
    m << "    species_init = zeros(1," << nSpecies << ");\n";
    for (std::size_t i = 0; i < nSpecies; ++i) {
        const auto& sp = network.species.get(i);
        m << "    species_init(" << (i + 1) << ") = " << std::setprecision(15)
          << sp.getAmount() << "; % " << sp.getSpeciesGraph().toString() << "\n";
    }
    m << "end\n";
    return m.str();
}

std::string MatlabWriter::writeBngModel(
    const ast::Model& model,
    const engine::GeneratedNetwork& network,
    const std::string& filebase
) {
    (void)engine::collectConstantReactionDelays(model, network, "MATLAB export");
    requireNoEnergySemantics(model, "MATLAB M-file");
    compile::requireNoNativeEvents(model, "MATLAB export");
    const std::string safeBase = makeMatlabFunctionName(filebase);
    const std::string className = "bngModel_" + safeBase;
    std::ostringstream m;
    m << "classdef " << className << " < bngModel\n\n";
    m << "    properties\n";
    m << "    end\n\n";
    m << "    methods\n\n";
    m << "    function obj = " << className << "\n";
    m << "        obj = obj@bngModel;\n\n";

    m << "        species_labels = { ";
    for (std::size_t i = 0; i < network.species.size(); ++i) {
        if (i > 0) m << ", ";
        m << "'" << escapeMatlabString(network.species.get(i).getSpeciesGraph().toString()) << "'";
    }
    m << " };\n";

    const auto& params = model.getParameters().all();
    m << "        param_labels = { ";
    for (std::size_t i = 0; i < params.size(); ++i) {
        if (i > 0) m << ", ";
        m << "'" << escapeMatlabString(params[i].getName()) << "'";
    }
    m << " };\n";

    m << "        param_defaults = [ ";
    for (std::size_t i = 0; i < params.size(); ++i) {
        if (i > 0) m << ", ";
        m << std::setprecision(15) << params[i].getValue();
    }
    m << " ];\n";

    const auto& obs = model.getObservables();
    m << "        obs_labels = { ";
    for (std::size_t i = 0; i < obs.size(); ++i) {
        if (i > 0) m << ", ";
        m << "'" << escapeMatlabString(obs[i].getName()) << "'";
    }
    m << " };\n";

    m << "        simulators = { '" << safeBase << "' };\n\n";
    m << "        obj.Param = bngParam(param_labels,param_defaults);\n";
    m << "        obj.Obs = bngObs(obs_labels);\n";
    m << "        obj.Species = bngSpecies(species_labels,'initSpecies_" << safeBase << "');\n";
    m << "        obj.simulators = simulators;\n";
    m << "    end\n\n";
    m << "    end\n\n";
    m << "end\n";
    return m.str();
}

} // namespace bng::io
