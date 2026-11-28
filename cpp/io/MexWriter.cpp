#include "compile/CompiledModel.hpp"
#include "compile/TotalRate.hpp"
#include "MexWriter.hpp"

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

std::string sanitizeCBlockComment(const std::string& text) {
    std::string out;
    out.reserve(text.size());
    for (char c : text) {
        if (c == '\r' || c == '\n') out += ' ';
        else out += c;
    }
    std::size_t pos = 0;
    while ((pos = out.find("*/", pos)) != std::string::npos) {
        out.replace(pos, 2, "* /");
        pos += 3;
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

std::string renderExprToC(
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
        if (name == "_pi" || name == "pi" || name == "_PI") return "M_PI";
        if (name == "_e" || name == "e") return "M_E";
        return name;
    }
    case Kind::Unary: {
        const auto arg = renderExprToC(expr.args().front(), paramIndex, obsIndex);
        if (expr.name() == "-" || expr.name() == "+") {
            return "(" + expr.name() + "(" + arg + "))";
        }
        if (expr.name() == "!" || expr.name() == "~") {
            return "((" + arg + ") == 0.0 ? 1.0 : 0.0)";
        }
        return arg;
    }
    case Kind::Binary: {
        const auto lhs = renderExprToC(expr.args()[0], paramIndex, obsIndex);
        const auto rhs = renderExprToC(expr.args()[1], paramIndex, obsIndex);
        const auto& op = expr.name();
        if (op == "^" || op == "**") {
            return "pow(" + lhs + ", " + rhs + ")";
        }
        if (op == "%") {
            return "fmod(" + lhs + ", " + rhs + ")";
        }
        if (op == "~=") {
            return "(" + lhs + " != " + rhs + ")";
        }
        if (op == "^^") {
            return "(((" + lhs + ") != 0.0) != ((" + rhs + ") != 0.0) ? 1.0 : 0.0)";
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
            rendered.push_back(renderExprToC(a, paramIndex, obsIndex));
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
                   ")) + sqrt(pow((" + st + ") - (" + km + ") - (" + et + "), 2.0) + 4.0 * (" + st + ") * (" + km + "))))";
        }
        if (lowerName == "hill" && rendered.size() == 4) {
            const auto& vmax = rendered[0];
            const auto& kh = rendered[1];
            const auto& n = rendered[2];
            const auto& s = rendered[3];
            return "((" + vmax + ") * pow(" + s + ", " + n + ") / (pow(" + kh + ", " + n + ") + pow(" + s + ", " + n + ")))";
        }
        if (name == "if" && rendered.size() == 3) {
            return "((" + rendered[0] + ") != 0.0 ? (" + rendered[1] + ") : (" + rendered[2] + "))";
        }
        if (name == "ln" && rendered.size() == 1) return "log(" + rendered[0] + ")";
        if (name == "abs" && rendered.size() == 1) return "fabs(" + rendered[0] + ")";
        if (name == "rint" && rendered.size() == 1) return "floor((" + rendered[0] + ") + 0.5)";
        if (name == "sign" && rendered.size() == 1) {
            return "((" + rendered[0] + ") > 0.0 ? 1.0 : ((" + rendered[0] + ") < 0.0 ? -1.0 : 0.0))";
        }
        if ((name == "min" || name == "max") && !rendered.empty()) {
            const std::string fn = (name == "min") ? "fmin" : "fmax";
            std::string acc = rendered[0];
            for (std::size_t i = 1; i < rendered.size(); ++i) {
                acc = fn + "(" + acc + ", " + rendered[i] + ")";
            }
            return acc;
        }
        if (name == "sum") {
            if (rendered.empty()) return "0.0";
            std::string acc = "(" + rendered[0];
            for (std::size_t i = 1; i < rendered.size(); ++i) acc += " + " + rendered[i];
            return acc + ")";
        }
        if (name == "avg" && !rendered.empty()) {
            std::string acc = "((" + rendered[0];
            for (std::size_t i = 1; i < rendered.size(); ++i) acc += " + " + rendered[i];
            return acc + ") / " + std::to_string(rendered.size()) + ".0)";
        }
        std::string cName = name;
        if (name == "ceiling") cName = "ceil";
        std::ostringstream call;
        call << cName << "(";
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

// Rewrite infix `a ^ b` / `a ** b` in C string fallback to `pow(a, b)`
std::string rewritePowOperatorToC(std::string text) {
    while (true) {
        std::size_t opPos = std::string::npos;
        std::size_t opLen = 0;
        for (std::size_t i = 0; i < text.size(); ++i) {
            if (text[i] == '^') {
                opPos = i;
                opLen = 1;
                break;
            }
            if (i + 1 < text.size() && text[i] == '*' && text[i + 1] == '*') {
                opPos = i;
                opLen = 2;
                break;
            }
        }
        if (opPos == std::string::npos) break;

        // Scan left operand
        std::size_t lhsEnd = opPos;
        while (lhsEnd > 0 && std::isspace(static_cast<unsigned char>(text[lhsEnd - 1])) != 0) {
            --lhsEnd;
        }
        std::size_t lhsStart = lhsEnd;
        if (lhsStart > 0 && text[lhsStart - 1] == ')') {
            int depth = 0;
            do {
                --lhsStart;
                if (text[lhsStart] == ')') ++depth;
                else if (text[lhsStart] == '(') --depth;
            } while (lhsStart > 0 && depth > 0);
            while (lhsStart > 0 &&
                   (std::isalnum(static_cast<unsigned char>(text[lhsStart - 1])) != 0 ||
                    text[lhsStart - 1] == '_')) {
                --lhsStart;
            }
        } else {
            int bracketDepth = 0;
            while (lhsStart > 0) {
                const char c = text[lhsStart - 1];
                if (c == ']') { ++bracketDepth; --lhsStart; continue; }
                if (c == '[') { --bracketDepth; --lhsStart; continue; }
                if (bracketDepth > 0 ||
                    std::isalnum(static_cast<unsigned char>(c)) != 0 ||
                    c == '_' || c == '.') {
                    --lhsStart;
                } else {
                    break;
                }
            }
        }

        // Scan right operand
        std::size_t rhsStart = opPos + opLen;
        while (rhsStart < text.size() && std::isspace(static_cast<unsigned char>(text[rhsStart])) != 0) {
            ++rhsStart;
        }
        std::size_t rhsEnd = rhsStart;
        if (rhsEnd < text.size() && (text[rhsEnd] == '-' || text[rhsEnd] == '+')) {
            ++rhsEnd;
        }
        if (rhsEnd < text.size() && text[rhsEnd] == '(') {
            int depth = 0;
            do {
                if (text[rhsEnd] == '(') ++depth;
                else if (text[rhsEnd] == ')') --depth;
                ++rhsEnd;
            } while (rhsEnd < text.size() && depth > 0);
        } else {
            int bracketDepth = 0;
            while (rhsEnd < text.size()) {
                const char c = text[rhsEnd];
                if (c == '[') { ++bracketDepth; ++rhsEnd; continue; }
                if (c == ']') { --bracketDepth; ++rhsEnd; continue; }
                if (c == '(') {
                    int depth = 0;
                    do {
                        if (text[rhsEnd] == '(') ++depth;
                        else if (text[rhsEnd] == ')') --depth;
                        ++rhsEnd;
                    } while (rhsEnd < text.size() && depth > 0);
                    break;
                }
                if (bracketDepth > 0 ||
                    std::isalnum(static_cast<unsigned char>(c)) != 0 ||
                    c == '_' || c == '.') {
                    ++rhsEnd;
                } else {
                    break;
                }
            }
        }

        if (lhsStart >= lhsEnd || rhsStart >= rhsEnd) break;
        const std::string lhs = text.substr(lhsStart, lhsEnd - lhsStart);
        const std::string rhs = text.substr(rhsStart, rhsEnd - rhsStart);
        text.replace(lhsStart, rhsEnd - lhsStart, "pow(" + lhs + ", " + rhs + ")");
    }
    return text;
}

} // namespace

std::string MexWriter::write(const ast::Model& model, const engine::GeneratedNetwork& network) {
    Options opts;
    return write(model, network, opts);
}

std::string MexWriter::write(const ast::Model& model, const engine::GeneratedNetwork& network, const Options& opts) {
    engine::requireNoDelayedSemantics(model, network, "MEX export");
    requireNoEnergySemantics(model, "MEX");
    compile::requireNoNativeEvents(model, "MEX export");
    std::ostringstream out;

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

    // ===== Header comment =====
    const std::string safeModelName = sanitizeCBlockComment(modelName);
    out << "/*\n";
    out << "**   " << safeModelName << "_mex.c\n";
    out << "**\n";
    out << "**   MATLAB MEX implementation of BioNetGen model '" << safeModelName << "'.\n";
    out << "**\n";
    out << "**   Compile in MATLAB with:\n";
    out << "**     mex " << safeModelName << "_mex.c\n";
    out << "**\n";
    out << "**   Usage in MATLAB:\n";
    out << "**     [species_out, observables_out] = " << safeModelName << "_mex(timepoints, species_init, parameters)\n";
    out << "**\n";
    out << "**   Uses a built-in RK4 integrator (no external solver dependencies).\n";
    out << "*/\n\n";

    // ===== Includes =====
    out << "#include \"mex.h\"\n";
    out << "#include <math.h>\n";
    out << "#include <string.h>\n";
    out << "#include <stdlib.h>\n\n";

    // ===== Problem dimensions =====
    out << "/* Problem Dimensions */\n";
    out << "#define N_PARAMETERS   " << nParams << "\n";
    out << "#define N_EXPRESSIONS  " << nParams << "\n";
    out << "#define N_OBSERVABLES  " << groups.size() << "\n";
    out << "#define N_RATELAWS     " << nRxns << "\n";
    out << "#define N_SPECIES      " << nSpecies << "\n\n";

    std::unordered_map<std::string, std::size_t> paramIndex;
    for (std::size_t i = 0; i < nParams; ++i) {
        paramIndex[paramNames[i]] = i;
    }
    std::unordered_map<std::string, std::size_t> obsIndex;
    for (std::size_t g = 0; g < groups.size(); ++g) {
        obsIndex[groups[g].name] = g;
    }

    // ===== calc_expressions =====
    out << "/* Calculate expressions */\n";
    out << "static void calc_expressions(double *expressions, const double *parameters)\n";
    out << "{\n";
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
                out << "    expressions[" << i << "] = "
                    << renderExprToC(expandedParam, paramIndex, obsIndex) << ";";
            } else {
                out << "    expressions[" << i << "] = parameters[" << i << "];";
            }
            out << "   /* " << sanitizeCBlockComment(paramNames[i]) << " */\n";
        }
    }
    out << "}\n\n";

    // ===== calc_observables =====
    out << "/* Calculate observables */\n";
    out << "static void calc_observables(double *observables, const double *species, const double *expressions)\n";
    out << "{\n";
    for (std::size_t g = 0; g < groups.size(); ++g) {
        if (groups[g].entries.empty()) {
            out << "    observables[" << g << "] = 0;";
        } else {
            out << "    observables[" << g << "] = ";
            bool first = true;
            for (const auto& [specIdx, weight] : groups[g].entries) {
                if (!first) out << " + ";
                if (weight > 1) {
                    out << weight << "*";
                }
                out << "species[" << specIdx << "]";
                first = false;
            }
            out << ";";
        }
        out << "   /* " << sanitizeCBlockComment(groups[g].name) << " */\n";
    }
    out << "}\n\n";

    // ===== calc_ratelaws =====
    out << "/* Calculate ratelaws */\n";
    out << "static void calc_ratelaws(double *ratelaws, const double *species, const double *expressions, const double *observables, double t)\n";
    out << "{\n";
    out << "    (void)t;\n";
    for (std::size_t r = 0; r < nRxns; ++r) {
        const auto& rxn = network.reactions.all()[r];
        out << "    ratelaws[" << r << "] = ";

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
                out << std::setprecision(17) << (statFactor * expanded.numberValue());
            } else {
                const std::string rateRef = renderExprToC(expanded, paramIndex, obsIndex);
                const bool willMultiply =
                    (std::abs(statFactor - 1.0) > 1e-12) ||
                    (!absoluteFlux && !consumedReactants && !rxn.getReactants().empty());
                const std::string safeRef = willMultiply ? wrapIfNeeded(rateRef) : rateRef;
                if (std::abs(statFactor - 1.0) > 1e-12) {
                    out << std::setprecision(17) << statFactor << "*" << safeRef;
                } else {
                    out << safeRef;
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
                out << std::setprecision(17) << combined;
            } else {
                std::string rateRef = convertRateToC(cleanRate, paramNames);
                const bool willMultiply =
                    (std::abs(statFactor - 1.0) > 1e-12) ||
                    (!absoluteFlux && !consumedReactants && !rxn.getReactants().empty());
                const std::string safeRef = willMultiply ? wrapIfNeeded(rateRef) : rateRef;
                if (std::abs(statFactor - 1.0) > 1e-12) {
                    out << std::setprecision(17) << statFactor << "*" << safeRef;
                } else {
                    out << safeRef;
                }
            }
        }

        // Multiply by reactant concentrations (unless absoluteFlux or special rate law already includes them)
        if (!absoluteFlux && !consumedReactants) {
            for (const auto idx : rxn.getReactants()) {
                out << "*species[" << idx << "]";
            }
        }

        out << ";\n";
    }
    out << "}\n\n";

    // ===== calc_species_deriv =====
    out << "/* Calculate species derivatives */\n";
    out << "static void calc_species_deriv(double t, const double *species, double *dydt,\n";
    out << "                               const double *expressions)\n";
    out << "{\n";
    out << "    double observables[N_OBSERVABLES > 0 ? N_OBSERVABLES : 1];\n";
    out << "    double ratelaws[N_RATELAWS > 0 ? N_RATELAWS : 1];\n\n";
    out << "    /* calculate observables */\n";
    out << "    calc_observables(observables, species, expressions);\n\n";
    out << "    /* calculate ratelaws */\n";
    out << "    calc_ratelaws(ratelaws, species, expressions, observables, t);\n\n";
    out << "    /* calculate derivatives */\n";

    for (std::size_t i = 0; i < nSpecies; ++i) {
        out << "    dydt[" << i << "] = ";
        if (fixedSpecies[i]) {
            out << "0; /* fixed species */\n";
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
                            out << "ratelaws[" << rxnIdx << "]";
                        } else if (coeff == -1) {
                            out << "-ratelaws[" << rxnIdx << "]";
                        } else {
                            out << coeff << "*ratelaws[" << rxnIdx << "]";
                        }
                    } else {
                        if (coeff == 1) {
                            out << " + ratelaws[" << rxnIdx << "]";
                        } else if (coeff == -1) {
                            out << " - ratelaws[" << rxnIdx << "]";
                        } else if (coeff > 0) {
                            out << " + " << coeff << "*ratelaws[" << rxnIdx << "]";
                        } else {
                            out << " - " << (-coeff) << "*ratelaws[" << rxnIdx << "]";
                        }
                    }
                    first = false;
                }
                break;
            }
        }
        if (!found) {
            out << "0";
        }
        out << ";\n";
    }

    out << "}\n\n";

    // ===== RK4 integrator =====
    out << "/* Built-in RK4 integrator */\n";
    out << "static void rk4_step(double t, double dt, double *y, double *y_out,\n";
    out << "                     int n, const double *expressions)\n";
    out << "{\n";
    out << "    int i;\n";
    out << "    double *k1, *k2, *k3, *k4, *ytmp;\n\n";
    out << "    k1   = (double *)mxMalloc(n * sizeof(double));\n";
    out << "    k2   = (double *)mxMalloc(n * sizeof(double));\n";
    out << "    k3   = (double *)mxMalloc(n * sizeof(double));\n";
    out << "    k4   = (double *)mxMalloc(n * sizeof(double));\n";
    out << "    ytmp = (double *)mxMalloc(n * sizeof(double));\n\n";
    out << "    /* k1 */\n";
    out << "    calc_species_deriv(t, y, k1, expressions);\n\n";
    out << "    /* k2 */\n";
    out << "    for (i = 0; i < n; i++) ytmp[i] = y[i] + 0.5 * dt * k1[i];\n";
    out << "    calc_species_deriv(t + 0.5 * dt, ytmp, k2, expressions);\n\n";
    out << "    /* k3 */\n";
    out << "    for (i = 0; i < n; i++) ytmp[i] = y[i] + 0.5 * dt * k2[i];\n";
    out << "    calc_species_deriv(t + 0.5 * dt, ytmp, k3, expressions);\n\n";
    out << "    /* k4 */\n";
    out << "    for (i = 0; i < n; i++) ytmp[i] = y[i] + dt * k3[i];\n";
    out << "    calc_species_deriv(t + dt, ytmp, k4, expressions);\n\n";
    out << "    /* combine */\n";
    out << "    for (i = 0; i < n; i++)\n";
    out << "        y_out[i] = y[i] + (dt / 6.0) * (k1[i] + 2.0*k2[i] + 2.0*k3[i] + k4[i]);\n\n";
    out << "    mxFree(k1);\n";
    out << "    mxFree(k2);\n";
    out << "    mxFree(k3);\n";
    out << "    mxFree(k4);\n";
    out << "    mxFree(ytmp);\n";
    out << "}\n\n";

    // ===== Adaptive RK4 driver =====
    out << "/* Adaptive RK4 driver: integrate from t0 to tf with sub-stepping */\n";
    out << "static void integrate_rk4(double t0, double tf, double *y, int n,\n";
    out << "                          const double *expressions, int max_steps)\n";
    out << "{\n";
    out << "    double dt = (tf - t0) / (double)max_steps;\n";
    out << "    double t  = t0;\n";
    out << "    double *y_new = (double *)mxMalloc(n * sizeof(double));\n";
    out << "    int step;\n\n";
    out << "    for (step = 0; step < max_steps; step++) {\n";
    out << "        if (t + dt > tf) dt = tf - t;\n";
    out << "        rk4_step(t, dt, y, y_new, n, expressions);\n";
    out << "        memcpy(y, y_new, n * sizeof(double));\n";
    out << "        t += dt;\n";
    out << "        if (t >= tf) break;\n";
    out << "    }\n\n";
    out << "    mxFree(y_new);\n";
    out << "}\n\n";

    // ===== mexFunction gateway =====
    out << "/*\n";
    out << "** Gateway function\n";
    out << "**   [species_out, observables_out] = " << safeModelName << "_mex(timepoints, species_init, parameters)\n";
    out << "**\n";
    out << "**   timepoints   : 1 x T or T x 1 double array\n";
    out << "**   species_init : 1 x " << nSpecies << " or " << nSpecies << " x 1 double array\n";
    out << "**   parameters   : 1 x " << nParams << " or " << nParams << " x 1 double array\n";
    out << "**\n";
    out << "**   species_out     : " << nSpecies << " x T double array\n";
    out << "**   observables_out : " << groups.size() << " x T double array\n";
    out << "*/\n";
    out << "void mexFunction(int nlhs, mxArray *plhs[], int nrhs, const mxArray *prhs[])\n";
    out << "{\n";
    out << "    int i, j, n_timepoints, n_substeps;\n";
    out << "    double *timepoints, *species_init, *parameters;\n";
    out << "    double *species_out, *observables_out;\n";
    out << "    double *y;\n";
    out << "    double expressions[N_EXPRESSIONS > 0 ? N_EXPRESSIONS : 1];\n";
    out << "    double observables[N_OBSERVABLES > 0 ? N_OBSERVABLES : 1];\n\n";

    // Input validation
    out << "    /* Validate inputs */\n";
    out << "    if (nrhs < 3)\n";
    out << "        mexErrMsgTxt(\"Three inputs required: timepoints, species_init, parameters.\");\n";
    out << "    if (nlhs > 2)\n";
    out << "        mexErrMsgTxt(\"Too many output arguments (max 2).\");\n\n";

    out << "    /* Get input pointers */\n";
    out << "    timepoints   = mxGetPr(prhs[0]);\n";
    out << "    species_init = mxGetPr(prhs[1]);\n";
    out << "    parameters   = mxGetPr(prhs[2]);\n\n";

    out << "    n_timepoints = (int)mxGetNumberOfElements(prhs[0]);\n\n";

    out << "    /* Validate dimensions */\n";
    out << "    if (mxGetNumberOfElements(prhs[1]) != N_SPECIES)\n";
    out << "        mexErrMsgTxt(\"species_init must have " << nSpecies << " elements.\");\n";
    out << "    if (mxGetNumberOfElements(prhs[2]) != N_PARAMETERS)\n";
    out << "        mexErrMsgTxt(\"parameters must have " << nParams << " elements.\");\n";
    out << "    if (n_timepoints < 2)\n";
    out << "        mexErrMsgTxt(\"timepoints must have at least 2 elements.\");\n\n";

    // Create output arrays
    out << "    /* Create output arrays */\n";
    out << "    plhs[0] = mxCreateDoubleMatrix(N_SPECIES, n_timepoints, mxREAL);\n";
    out << "    species_out = mxGetPr(plhs[0]);\n";
    out << "    if (nlhs > 1) {\n";
    out << "        plhs[1] = mxCreateDoubleMatrix(N_OBSERVABLES, n_timepoints, mxREAL);\n";
    out << "        observables_out = mxGetPr(plhs[1]);\n";
    out << "    } else {\n";
    out << "        observables_out = NULL;\n";
    out << "    }\n\n";

    // Initialize
    out << "    /* Calculate expressions (constant, do once) */\n";
    out << "    calc_expressions(expressions, parameters);\n\n";

    out << "    /* Copy initial conditions */\n";
    out << "    y = (double *)mxMalloc(N_SPECIES * sizeof(double));\n";
    out << "    for (i = 0; i < N_SPECIES; i++) y[i] = species_init[i];\n\n";

    out << "    /* Store initial state */\n";
    out << "    for (i = 0; i < N_SPECIES; i++)\n";
    out << "        species_out[i] = y[i];  /* column 0 */\n";
    out << "    if (observables_out) {\n";
    out << "        calc_observables(observables, y, expressions);\n";
    out << "        for (i = 0; i < N_OBSERVABLES; i++)\n";
    out << "            observables_out[i] = observables[i];\n";
    out << "    }\n\n";

    // Integration loop
    out << "    /* Number of RK4 sub-steps per output interval */\n";
    out << "    n_substeps = " << opts.maxNumSteps << ";\n\n";
    out << "    /* Integrate to each timepoint */\n";
    out << "    for (j = 1; j < n_timepoints; j++) {\n";
    out << "        integrate_rk4(timepoints[j-1], timepoints[j], y, N_SPECIES,\n";
    out << "                      expressions, n_substeps);\n\n";
    out << "        /* Store species (column-major: row i, col j -> index j*N_SPECIES + i) */\n";
    out << "        for (i = 0; i < N_SPECIES; i++)\n";
    out << "            species_out[j * N_SPECIES + i] = y[i];\n\n";
    out << "        /* Store observables */\n";
    out << "        if (observables_out) {\n";
    out << "            calc_observables(observables, y, expressions);\n";
    out << "            for (i = 0; i < N_OBSERVABLES; i++)\n";
    out << "                observables_out[j * N_OBSERVABLES + i] = observables[i];\n";
    out << "        }\n";
    out << "    }\n\n";

    out << "    mxFree(y);\n";
    out << "}\n";

    return out.str();
}

std::string MexWriter::convertRateToC(const std::string& rate, const std::vector<std::string>& paramNames) {
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

    // Translate BNGL math syntax (`^`/`**`, `ln`, `abs`) to C99 `<math.h>`
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
        while ((pos = result.find("abs(", pos)) != std::string::npos) {
            const bool validStart = (pos == 0 || (!std::isalnum(static_cast<unsigned char>(result[pos - 1])) && result[pos - 1] != '_'));
            if (validStart) {
                result.replace(pos, 3, "fabs");
                pos += 5;
            } else {
                pos += 4;
            }
        }
    }
    result = rewritePowOperatorToC(std::move(result));

    return result;
}

std::vector<MexWriter::ObservableGroup> MexWriter::computeObservableGroups(
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

std::vector<MexWriter::StoichEntry> MexWriter::computeStoichiometry(
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
