#include "NetReader.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace bng::io {

namespace {

std::string trim(const std::string& str) {
    auto start = std::find_if_not(str.begin(), str.end(), [](unsigned char c) {
        return std::isspace(c) != 0;
    });
    auto end = std::find_if_not(str.rbegin(), str.rend(), [](unsigned char c) {
        return std::isspace(c) != 0;
    }).base();
    return (start < end) ? std::string(start, end) : std::string();
}

std::vector<std::string> split(const std::string& str, char delim) {
    std::vector<std::string> tokens;
    std::stringstream ss(str);
    std::string token;
    while (std::getline(ss, token, delim)) {
        tokens.push_back(token);
    }
    return tokens;
}

std::vector<std::string> splitWhitespace(const std::string& str) {
    std::vector<std::string> tokens;
    std::size_t i = 0;
    const std::size_t n = str.size();
    while (i < n) {
        while (i < n && std::isspace(static_cast<unsigned char>(str[i])) != 0) {
            ++i;
        }
        if (i >= n) break;
        const std::size_t start = i;
        while (i < n && std::isspace(static_cast<unsigned char>(str[i])) == 0) {
            ++i;
        }
        tokens.push_back(str.substr(start, i - start));
    }
    return tokens;
}

std::pair<std::string, std::string> extractParameterNameAndExpression(const std::string& line) {
    // Format: <index> <name> <expression...>
    const std::size_t n = line.size();
    std::size_t pos = 0;
    while (pos < n && std::isspace(static_cast<unsigned char>(line[pos])) != 0) ++pos;
    const std::size_t idxEnd = pos;
    while (pos < n && std::isspace(static_cast<unsigned char>(line[pos])) == 0) ++pos;
    if (pos == idxEnd) {
        throw std::runtime_error("Invalid parameter format: " + line);
    }
    while (pos < n && std::isspace(static_cast<unsigned char>(line[pos])) != 0) ++pos;
    const std::size_t nameStart = pos;
    while (pos < n && std::isspace(static_cast<unsigned char>(line[pos])) == 0) ++pos;
    if (pos == nameStart) {
        throw std::runtime_error("Invalid parameter format: " + line);
    }
    std::string name = line.substr(nameStart, pos - nameStart);
    std::string exprText = trim(line.substr(pos));
    if (exprText.empty()) {
        throw std::runtime_error("Invalid parameter format: " + line);
    }
    return {std::move(name), std::move(exprText)};
}

class SimpleNetExprParser {
public:
    explicit SimpleNetExprParser(const std::string& input) : text_(input) {}

    ast::Expression parse() {
        ast::Expression expr = parseAddSub(0);
        skipWs();
        if (pos_ != text_.size()) {
            throw std::runtime_error("Unexpected trailing token in parameter expression: " + text_);
        }
        return expr;
    }

private:
    static constexpr int kMaxDepth = 256;
    const std::string& text_;
    std::size_t pos_ = 0;

    void skipWs() {
        while (pos_ < text_.size() && std::isspace(static_cast<unsigned char>(text_[pos_])) != 0) {
            ++pos_;
        }
    }

    bool match(const char* tok) {
        skipWs();
        const std::size_t len = std::char_traits<char>::length(tok);
        if (pos_ + len <= text_.size() && text_.compare(pos_, len, tok) == 0) {
            pos_ += len;
            return true;
        }
        return false;
    }

    ast::Expression parseAddSub(int depth) {
        if (depth > kMaxDepth) throw std::runtime_error("Expression depth limit exceeded");
        auto lhs = parseMulDiv(depth + 1);
        for (;;) {
            skipWs();
            if (pos_ < text_.size() && (text_[pos_] == '+' || text_[pos_] == '-')) {
                const std::string op(1, text_[pos_++]);
                auto rhs = parseMulDiv(depth + 1);
                lhs = ast::Expression::binary(op, std::move(lhs), std::move(rhs));
            } else {
                break;
            }
        }
        return lhs;
    }

    ast::Expression parseMulDiv(int depth) {
        if (depth > kMaxDepth) throw std::runtime_error("Expression depth limit exceeded");
        auto lhs = parseUnary(depth + 1);
        for (;;) {
            skipWs();
            if (pos_ < text_.size() && (text_[pos_] == '*' || text_[pos_] == '/')) {
                if (text_[pos_] == '*' && pos_ + 1 < text_.size() && text_[pos_ + 1] == '*') {
                    break;
                }
                const std::string op(1, text_[pos_++]);
                auto rhs = parseUnary(depth + 1);
                lhs = ast::Expression::binary(op, std::move(lhs), std::move(rhs));
            } else {
                break;
            }
        }
        return lhs;
    }

    ast::Expression parseUnary(int depth) {
        if (depth > kMaxDepth) throw std::runtime_error("Expression depth limit exceeded");
        skipWs();
        if (pos_ < text_.size() && (text_[pos_] == '+' || text_[pos_] == '-')) {
            const std::string op(1, text_[pos_++]);
            return ast::Expression::unary(op, parseUnary(depth + 1));
        }
        return parsePower(depth + 1);
    }

    ast::Expression parsePower(int depth) {
        if (depth > kMaxDepth) throw std::runtime_error("Expression depth limit exceeded");
        auto base = parsePrimary(depth + 1);
        skipWs();
        if (match("**") || match("^")) {
            auto exp = parseUnary(depth + 1);
            return ast::Expression::binary("^", std::move(base), std::move(exp));
        }
        return base;
    }

    ast::Expression parsePrimary(int depth) {
        if (depth > kMaxDepth) throw std::runtime_error("Expression depth limit exceeded");
        skipWs();
        if (pos_ >= text_.size()) {
            throw std::runtime_error("Unexpected end of parameter expression: " + text_);
        }
        if (text_[pos_] == '(') {
            ++pos_;
            auto inner = parseAddSub(depth + 1);
            if (!match(")")) {
                throw std::runtime_error("Missing ')' in parameter expression: " + text_);
            }
            return inner;
        }
        const char ch = text_[pos_];
        if (std::isdigit(static_cast<unsigned char>(ch)) != 0 || ch == '.') {
            const char* startPtr = text_.c_str() + pos_;
            char* endPtr = nullptr;
            const double val = std::strtod(startPtr, &endPtr);
            if (endPtr == startPtr || !std::isfinite(val)) {
                throw std::runtime_error("Invalid numeric literal in parameter expression: " + text_);
            }
            pos_ = static_cast<std::size_t>(endPtr - text_.c_str());
            return ast::Expression::number(val);
        }
        if (std::isalpha(static_cast<unsigned char>(ch)) != 0 || ch == '_') {
            const std::size_t start = pos_;
            while (pos_ < text_.size() &&
                   (std::isalnum(static_cast<unsigned char>(text_[pos_])) != 0 || text_[pos_] == '_')) {
                ++pos_;
            }
            std::string ident = text_.substr(start, pos_ - start);
            if (match("(")) {
                std::vector<ast::Expression> args;
                if (!match(")")) {
                    do {
                        args.push_back(parseAddSub(depth + 1));
                    } while (match(","));
                    if (!match(")")) {
                        throw std::runtime_error("Missing ')' after function arguments: " + text_);
                    }
                }
                return ast::Expression::function(std::move(ident), std::move(args));
            }
            return ast::Expression::identifier(std::move(ident));
        }
        throw std::runtime_error("Unexpected character in parameter expression: " + text_);
    }
};

ast::Expression parseNetParameterExpression(const std::string& exprText) {
    try {
        std::size_t consumed = 0;
        const double value = std::stod(exprText, &consumed);
        if (consumed == exprText.size() && std::isfinite(value)) {
            return ast::Expression::number(value);
        }
    } catch (...) {
        // Fall through to symbolic arithmetic expression parser.
    }
    SimpleNetExprParser parser(exprText);
    return parser.parse();
}

} // anonymous namespace

NetReader::ParseResult NetReader::parse(const std::filesystem::path& filepath) {
    ParseResult result;

    std::ifstream infile(filepath);
    if (!infile) {
        result.error = "Failed to open file: " + filepath.string();
        return result;
    }

    std::string line;
    std::string currentSection;
    ast::ParameterList parsedParameters;
    int lineNum = 0;

    try {
        while (std::getline(infile, line)) {
            lineNum++;

            // Remove comments (everything after #)
            auto commentPos = line.find('#');
            const auto inlineComment = commentPos == std::string::npos
                ? std::string() : trim(line.substr(commentPos));
            if (commentPos != std::string::npos) {
                line = line.substr(0, commentPos);
            }

            line = trim(line);
            if (line.empty()) continue;

            if (currentSection.empty() &&
                line.find("BNG3AbsoluteFluxReactionIndices") != std::string::npos) {
                const auto firstQuote = line.find('"');
                const auto secondQuote = firstQuote == std::string::npos
                    ? std::string::npos : line.find('"', firstQuote + 1);
                const auto thirdQuote = secondQuote == std::string::npos
                    ? std::string::npos : line.find('"', secondQuote + 1);
                const auto fourthQuote = thirdQuote == std::string::npos
                    ? std::string::npos : line.find('"', thirdQuote + 1);
                if (line.rfind("setOption(", 0) != 0 ||
                    firstQuote == std::string::npos ||
                    secondQuote == std::string::npos ||
                    thirdQuote == std::string::npos ||
                    fourthQuote == std::string::npos ||
                    secondQuote <= firstQuote || thirdQuote <= secondQuote ||
                    fourthQuote <= thirdQuote ||
                    trim(line.substr(fourthQuote + 1)) != ")") {
                    throw std::runtime_error(
                        "malformed BNG3AbsoluteFluxReactionIndices option");
                }
                const auto key = line.substr(firstQuote + 1,
                                             secondQuote - firstQuote - 1);
                if (key != "BNG3AbsoluteFluxReactionIndices") {
                    throw std::runtime_error(
                        "malformed BNG3AbsoluteFluxReactionIndices option");
                }
                const auto value = line.substr(thirdQuote + 1,
                                               fourthQuote - thirdQuote - 1);
                for (const auto& rawToken : split(value, ',')) {
                    const auto token = trim(rawToken);
                    std::size_t parsedLength = 0;
                    const auto index = std::stoull(token, &parsedLength);
                    if (parsedLength != token.size() || index == 0 ||
                        !result.absoluteFluxReactionIndices.insert(
                            static_cast<std::size_t>(index)).second) {
                        throw std::runtime_error(
                            "invalid or duplicate absolute-flux reaction index");
                    }
                }
            }

            // Check for section headers (handling spaces and tabs)
            const auto headerTokens = splitWhitespace(line);
            if (!headerTokens.empty() && headerTokens[0] == "begin") {
                if (headerTokens.size() >= 2) {
                    currentSection = headerTokens[1];
                }
                continue;
            }

            if (!headerTokens.empty() && headerTokens[0] == "end") {
                currentSection.clear();
                continue;
            }

            // Parse section content
            if (currentSection == "parameters") {
                auto [name, exprText] = extractParameterNameAndExpression(line);
                parsedParameters.add(
                    ast::Parameter(name, parseNetParameterExpression(exprText)));
                if (!inlineComment.empty()) {
                    result.parameterComments[name] = inlineComment;
                }
            } else if (currentSection == "compartments") {
                parseCompartmentLine(line, result);
            } else if (currentSection == "species") {
                parseSpeciesLine(line, result.species);
            } else if (currentSection == "reactions") {
                parseReactionLine(line, result.reactions);
            } else if (currentSection == "groups") {
                parseGroupLine(line, result);
                result.rawGroupLines.push_back(line);
            } else if (currentSection == "functions") {
                // Parse function: <index> <name>(<args>) <expression>
                // e.g. "1 michment() kcat/(Km+Sa0)"
                result.rawFunctionLines.push_back(line);
                const std::size_t n = line.size();
                std::size_t pos = 0;
                while (pos < n && std::isspace(static_cast<unsigned char>(line[pos])) == 0) ++pos;
                while (pos < n && std::isspace(static_cast<unsigned char>(line[pos])) != 0) ++pos;
                const std::size_t nameStart = pos;
                while (pos < n && std::isspace(static_cast<unsigned char>(line[pos])) == 0) ++pos;
                if (pos > nameStart && pos < n) {
                    auto name = line.substr(nameStart, pos - nameStart);
                    auto expr = trim(line.substr(pos));
                    if (!expr.empty()) {
                        result.functions.emplace_back(std::move(name), std::move(expr));
                    }
                }
            } else if (currentSection == "molecule") {
                result.rawMoleculeTypeLines.push_back(line);
            } else if (currentSection == "reaction") {
                // "reaction rules" section - store raw lines for passthrough
                result.rawReactionRuleLines.push_back(line);
            }
        }

        if (parsedParameters.size() > 0) {
            parsedParameters.evaluateAll();
            for (const auto& param : parsedParameters.all()) {
                const double val = param.getValue();
                if (!std::isfinite(val)) {
                    throw std::runtime_error(
                        "Non-finite parameter value for '" + param.getName() + "'");
                }
                result.parameters[param.getName()] = val;
            }
        }

        for (const auto index : result.absoluteFluxReactionIndices) {
            if (index > result.reactions.size()) {
                throw std::runtime_error(
                    "absolute-flux reaction index is outside the reaction table");
            }
            std::istringstream row(result.reactions[index - 1]);
            std::size_t rowIndex = 0;
            if (!(row >> rowIndex) || rowIndex != index) {
                throw std::runtime_error(
                    "absolute-flux reaction index does not match its channel row");
            }
        }

        result.success = true;

    } catch (const std::exception& e) {
        result.success = false;
        result.error = "Parse error at line " + std::to_string(lineNum) + ": " + e.what();
    }

    return result;
}

void NetReader::parseParameterLine(const std::string& line, ParseResult& result) {
    // Format: <index> <name> <expression...>
    // Example: "1 NA 6.02e+23" or "2 k2 2*k1"
    auto [name, exprText] = extractParameterNameAndExpression(line);
    const auto expr = parseNetParameterExpression(exprText);
    const double value = expr.evaluate([&](const std::string& dep) {
        const auto it = result.parameters.find(dep);
        if (it == result.parameters.end()) {
            throw std::runtime_error("Unknown parameter '" + dep + "' in .net file");
        }
        return it->second;
    }, 0.0);
    if (!std::isfinite(value)) {
        throw std::runtime_error("Non-finite parameter value for '" + name + "'");
    }
    result.parameters[name] = value;
}

void NetReader::parseCompartmentLine(const std::string& line, ParseResult& result) {
    // Format: <index> <name> <dimension> <size> [<parent>]
    // Example: "1 EC 3 1.0e-10"
    // Just store the line for now
    result.compartments.push_back(line);
}

void NetReader::parseSpeciesLine(const std::string& line, std::vector<std::pair<std::string, std::string>>& species) {
    // Format: <index> <pattern> <concentration>
    // Example: "1 EGFR(L,CR1,Y1068~U) 1.8e5" or "1 S(a~0,c~R) S0"
    // Note: concentration can be a numeric literal or a parameter reference

    // Split at the first whitespace after the species pattern. Concentrations
    // may be expressions containing whitespace, so they must remain intact.
    auto indexEnd = line.find_first_of(" \t");
    if (indexEnd == std::string::npos) {
        throw std::runtime_error("Invalid species format: " + line);
    }

    const auto patternStart = line.find_first_not_of(" \t", indexEnd);
    if (patternStart == std::string::npos) {
        throw std::runtime_error("Invalid species format: " + line);
    }
    const auto patternEnd = line.find_first_of(" \t", patternStart);
    if (patternEnd == std::string::npos) {
        throw std::runtime_error("Invalid species format: " + line);
    }

    std::string pattern = line.substr(patternStart, patternEnd - patternStart);
    std::string concentration = trim(line.substr(patternEnd + 1));
    if (concentration.empty()) {
        throw std::runtime_error("Invalid species format: " + line);
    }

    species.emplace_back(pattern, concentration);
}

void NetReader::parseReactionLine(const std::string& line, std::vector<std::string>& reactions) {
    // Format: <index> <reactants> <products> <rate> [<label>]
    // Example: "1 S1,S2 S3 k1*S1*S2"

    // Just store the raw line for now - full parsing needs more complex handling
    reactions.push_back(line);
}

void NetReader::parseGroupLine(const std::string& line, ParseResult& result) {
    // Two formats are supported:
    // Format A (from BNGL): <index> <name> <type> <patterns...>
    //   Example: "1 Dimers Molecules EGFR(CR1!+)"
    // Format B (from .net):  <index> <name> <weights>
    //   Example: "1 Sa0  1,4"  (weight-based species references)

    auto filtered = splitWhitespace(line);

    if (filtered.size() < 2) {
        throw std::runtime_error("Invalid observable format: " + line);
    }

    std::string name = filtered[1];

    if (filtered.size() == 2) {
        // Empty observables have a name but no species weights in .net files.
        result.observables.emplace_back(name, std::vector<std::string>{});
    } else if (filtered.size() >= 4) {
        // Format A: <index> <name> <type> <patterns...>
        std::vector<std::string> patterns;
        for (std::size_t i = 3; i < filtered.size(); ++i) {
            patterns.push_back(filtered[i]);
        }
        result.observables.emplace_back(name, patterns);
    } else {
        // Format B: <index> <name> <weights>
        // Third token is comma-separated species indices (possibly with weight multipliers)
        // e.g., "1,4" or "2*1,3*2"
        std::vector<std::string> weights;
        weights.push_back(filtered[2]);
        result.observables.emplace_back(name, weights);
    }
}

} // namespace bng::io
