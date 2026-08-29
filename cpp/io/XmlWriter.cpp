#include "XmlWriter.hpp"

#include <sstream>
#include <iomanip>
#include <algorithm>
#include <cctype>
#include <cmath>
#include <map>
#include <regex>
#include <set>
#include <stdexcept>
#include <vector>

namespace bng::io {

std::string XmlWriter::escapeXml(const std::string& text) {
    std::string result;
    result.reserve(text.size());
    for (char c : text) {
        switch (c) {
            case '&': result += "&amp;"; break;
            case '<': result += "&lt;"; break;
            case '>': result += "&gt;"; break;
            case '"': result += "&quot;"; break;
            case '\'': result += "&apos;"; break;
            default: result += c; break;
        }
    }
    return result;
}

// Parse a BNGL pattern string into structured molecule/component/bond data
// for XML serialization. This is a lightweight parser that handles:
//   Mol(comp1~state!bond,comp2~state)
//   Mol1(c!1).Mol2(c!1)
//   @Compartment::Mol(c)
namespace {

struct ParsedComponent {
    std::string name;
    std::string state;         // empty if no state
    std::string label;         // empty if no label
    std::vector<int> bonds;    // bond indices, -1 for ?, -2 for +
    std::string compartment;
};

struct ParsedMolecule {
    std::string name;
    std::string compartment;   // per-molecule compartment
    std::string label;
    bool scopePrefix = false;  // true for the species-scoped %x:: spelling
    std::vector<ParsedComponent> components;
};

struct ParsedBond {
    int id;
    int mol1, comp1;  // indices into molecule/component arrays
    int mol2, comp2;
};

struct ParsedPattern {
    std::string compartment;  // species-level compartment
    std::vector<ParsedMolecule> molecules;
    std::vector<ParsedBond> bonds;
};

struct ParsedReactionFilter {
    bool include = false;
    bool products = false;
    std::size_t patternIndex = 0;
    std::vector<std::string> patterns;
};

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
    const auto name = trimText(
        modifier.substr(0, open == std::string::npos ? modifier.size() : open));
    std::string lowerName = name;
    std::transform(lowerName.begin(), lowerName.end(), lowerName.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return lowerName == "include_reactants" || lowerName == "exclude_reactants" ||
           lowerName == "include_products" || lowerName == "exclude_products";
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

    std::string name = trimText(modifier.substr(0, open));
    std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
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

// Minimal BNGL pattern parser
ParsedPattern parsePattern(const std::string& text) {
    ParsedPattern pattern;
    std::string input = text;

    // Strip leading @Compartment:: prefix
    if (!input.empty() && input[0] == '@') {
        auto colonPos = input.find("::");
        if (colonPos != std::string::npos) {
            pattern.compartment = input.substr(1, colonPos - 1);
            input = input.substr(colonPos + 2);
        }
    }

    // Track bond endpoints: bondId -> list of (molIdx, compIdx)
    std::map<int, std::vector<std::pair<int, int>>> bondEndpoints;

    // Split by '.' at top level (not inside parentheses)
    std::vector<std::string> molStrings;
    int depth = 0;
    std::string current;
    for (char c : input) {
        if (c == '(') depth++;
        else if (c == ')') depth--;

        if (c == '.' && depth == 0) {
            if (!current.empty()) molStrings.push_back(current);
            current.clear();
        } else {
            current += c;
        }
    }
    if (!current.empty()) molStrings.push_back(current);

    for (const auto& molStr : molStrings) {
        ParsedMolecule mol;

        // Check for per-molecule compartment: @Comp before the name
        std::string remaining = molStr;

        // Parse molecule name and optional compartment
        auto parenPos = remaining.find('(');
        std::string namepart = (parenPos != std::string::npos)
            ? remaining.substr(0, parenPos) : remaining;

        // A scoped reaction molecule is written as %scope::Molecule(...).
        // Keep the scope as the XML label while exposing the actual molecule
        // type in the name attribute.
        const auto percentPos = namepart.find('%');
        if (percentPos != std::string::npos) {
            const auto scopePos = namepart.find("::", percentPos + 1);
            if (scopePos != std::string::npos && scopePos > percentPos + 1) {
                mol.scopePrefix = true;
                mol.label = namepart.substr(percentPos + 1, scopePos - percentPos - 1);
                namepart = namepart.substr(0, percentPos) +
                           namepart.substr(scopePos + 2);
            }
        }

        // Check for @compartment suffix on molecule name
        auto atPos = namepart.find('@');
        if (atPos != std::string::npos) {
            mol.name = namepart.substr(0, atPos);
            mol.compartment = namepart.substr(atPos + 1);
        } else {
            mol.name = namepart;
        }

        // Strip $ prefix for constant species
        if (!mol.name.empty() && mol.name[0] == '$') {
            mol.name = mol.name.substr(1);
        }

        // Check for %label
        auto pctPos = mol.name.find('%');
        if (pctPos != std::string::npos) {
            mol.label = mol.name.substr(pctPos + 1);
            mol.name = mol.name.substr(0, pctPos);
        }

        // Parse components inside parentheses
        if (parenPos != std::string::npos) {
            auto closePos = remaining.rfind(')');
            if (closePos != std::string::npos && closePos > parenPos) {
                std::string compStr = remaining.substr(parenPos + 1, closePos - parenPos - 1);

                // Split components by ','
                std::vector<std::string> compParts;
                std::string part;
                for (char c : compStr) {
                    if (c == ',') {
                        if (!part.empty()) compParts.push_back(part);
                        part.clear();
                    } else {
                        part += c;
                    }
                }
                if (!part.empty()) compParts.push_back(part);

                for (const auto& cp : compParts) {
                    ParsedComponent comp;

                    std::string rem = cp;
                    // Parse bonds (!) - can have multiple
                    while (true) {
                        auto bangPos = rem.find('!');
                        if (bangPos == std::string::npos) break;

                        std::string beforeBang = rem.substr(0, bangPos);
                        std::string afterBang = rem.substr(bangPos + 1);

                        // Get bond part
                        std::string bondStr;
                        std::size_t bondEnd = 0;
                        for (std::size_t i = 0; i < afterBang.size(); ++i) {
                            if (afterBang[i] == '!' || afterBang[i] == '~' || afterBang[i] == '%') {
                                bondEnd = i;
                                break;
                            }
                            bondEnd = i + 1;
                        }
                        bondStr = afterBang.substr(0, bondEnd);
                        rem = beforeBang + afterBang.substr(bondEnd);

                        if (bondStr == "?") {
                            comp.bonds.push_back(-1);
                        } else if (bondStr == "+") {
                            comp.bonds.push_back(-2);
                        } else {
                            try {
                                comp.bonds.push_back(std::stoi(bondStr));
                            } catch (...) {}
                        }
                    }

                    // Parse state (~)
                    auto tildePos = rem.find('~');
                    if (tildePos != std::string::npos) {
                        comp.name = rem.substr(0, tildePos);

                        // Find end of state (before % if present)
                        std::string stateRem = rem.substr(tildePos + 1);
                        auto pctPos2 = stateRem.find('%');
                        if (pctPos2 != std::string::npos) {
                            comp.state = stateRem.substr(0, pctPos2);
                            comp.label = stateRem.substr(pctPos2 + 1);
                        } else {
                            comp.state = stateRem;
                        }
                    } else {
                        auto pctPos2 = rem.find('%');
                        if (pctPos2 != std::string::npos) {
                            comp.name = rem.substr(0, pctPos2);
                            comp.label = rem.substr(pctPos2 + 1);
                        } else {
                            comp.name = rem;
                        }
                    }

                    // Record bond endpoints
                    int molIdx = static_cast<int>(pattern.molecules.size());
                    int compIdx = static_cast<int>(mol.components.size());
                    for (int bondId : comp.bonds) {
                        if (bondId > 0) {
                            bondEndpoints[bondId].push_back({molIdx, compIdx});
                        }
                    }

                    mol.components.push_back(std::move(comp));
                }

                // Legacy molecule labels may follow the component list:
                // X()%scope.  They carry the same molecule-local scope as
                // the prefix spelling %scope::X().
                const auto trailingAt = remaining.find('@', closePos + 1);
                if (trailingAt != std::string::npos && mol.compartment.empty()) {
                    const auto compartmentEnd = remaining.find('%', trailingAt + 1);
                    const auto end = compartmentEnd == std::string::npos
                                         ? remaining.size()
                                         : compartmentEnd;
                    if (end > trailingAt + 1) {
                        mol.compartment = remaining.substr(
                            trailingAt + 1, end - trailingAt - 1);
                    }
                }

                const auto trailingPercent = remaining.find('%', closePos + 1);
                if (trailingPercent != std::string::npos && mol.label.empty()) {
                    std::size_t labelEnd = trailingPercent + 1;
                    while (labelEnd < remaining.size() &&
                           (std::isalnum(static_cast<unsigned char>(remaining[labelEnd])) ||
                            remaining[labelEnd] == '_')) {
                        ++labelEnd;
                    }
                    if (labelEnd > trailingPercent + 1) {
                        mol.label = remaining.substr(
                            trailingPercent + 1, labelEnd - trailingPercent - 1);
                    }
                }
            }
        }

        pattern.molecules.push_back(std::move(mol));
    }

    // Build bond list from endpoints
    for (auto& [bondId, endpoints] : bondEndpoints) {
        if (endpoints.size() == 2) {
            ParsedBond bond;
            bond.id = bondId;
            bond.mol1 = endpoints[0].first;
            bond.comp1 = endpoints[0].second;
            bond.mol2 = endpoints[1].first;
            bond.comp2 = endpoints[1].second;
            pattern.bonds.push_back(bond);
        }
    }

    return pattern;
}

std::string patternToXml(const ParsedPattern& pattern, const std::string& idPrefix,
                         const std::string& indent) {
    std::ostringstream xml;

    // ListOfMolecules
    xml << indent << "<ListOfMolecules>\n";
    for (std::size_t m = 0; m < pattern.molecules.size(); ++m) {
        const auto& mol = pattern.molecules[m];
        std::string molId = idPrefix + "_M" + std::to_string(m + 1);
        xml << indent << "  <Molecule id=\"" << molId << "\" name=\"" << mol.name << "\"";
        if (!mol.compartment.empty()) {
            xml << " compartment=\"" << mol.compartment << "\"";
        }
        if (!mol.label.empty()) {
            xml << " label=\"" << mol.label << "\"";
        }
        xml << ">\n";

        if (!mol.components.empty()) {
            xml << indent << "    <ListOfComponents>\n";
            for (std::size_t c = 0; c < mol.components.size(); ++c) {
                const auto& comp = mol.components[c];
                std::string compId = molId + "_C" + std::to_string(c + 1);
                xml << indent << "      <Component id=\"" << compId
                    << "\" name=\"" << comp.name << "\"";
                if (!comp.state.empty()) {
                    xml << " state=\"" << comp.state << "\"";
                }
                if (!comp.label.empty()) {
                    xml << " label=\"" << comp.label << "\"";
                }
                // numberOfBonds
                int nBonds = 0;
                std::string bondStr;
                for (int b : comp.bonds) {
                    if (b == -1) { bondStr = "?"; break; }
                    else if (b == -2) { bondStr = "+"; break; }
                    else nBonds++;
                }
                if (bondStr.empty()) bondStr = std::to_string(nBonds);
                xml << " numberOfBonds=\"" << bondStr << "\"";
                xml << "/>\n";
            }
            xml << indent << "    </ListOfComponents>\n";
        }

        xml << indent << "  </Molecule>\n";
    }
    xml << indent << "</ListOfMolecules>\n";

    // ListOfBonds
    if (!pattern.bonds.empty()) {
        xml << indent << "<ListOfBonds>\n";
        for (std::size_t b = 0; b < pattern.bonds.size(); ++b) {
            const auto& bond = pattern.bonds[b];
            std::string bondId = idPrefix + "_B" + std::to_string(b + 1);
            std::string site1 = idPrefix + "_M" + std::to_string(bond.mol1 + 1) +
                               "_C" + std::to_string(bond.comp1 + 1);
            std::string site2 = idPrefix + "_M" + std::to_string(bond.mol2 + 1) +
                               "_C" + std::to_string(bond.comp2 + 1);
            xml << indent << "  <Bond id=\"" << bondId
                << "\" site1=\"" << site1 << "\" site2=\"" << site2 << "\"/>\n";
        }
        xml << indent << "</ListOfBonds>\n";
    }

    return xml.str();
}

bool modelHasFunction(const ast::Model& model, const std::string& name) {
    return std::any_of(model.getFunctions().begin(), model.getFunctions().end(),
                       [&](const auto& function) { return function.getName() == name; });
}

struct GeneratedRateFunction {
    std::string name;
    const ast::Expression* expression = nullptr;
    std::string expandedExpression;
    std::map<std::string, std::string> references;
    const ast::Expression* tableFunction = nullptr;
    std::map<std::string, std::string> observableAliases;
};

std::string lowercaseName(std::string value);

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

void addFunctionReference(std::map<std::string, std::string>& references,
                          const std::string& name, const std::string& type) {
    if (name.empty()) return;

    const auto existing = references.find(name);
    if (existing == references.end()) {
        references.emplace(name, type);
        return;
    }

    // Function arguments shadow parameters with the same spelling.  Keep the
    // most local semantic type if malformed/ambiguous input reaches the writer.
    if (type == "Local" || (type == "Time" && existing->second != "Local")) {
        existing->second = type;
    }
}

void collectFunctionReferences(const ast::Expression& expression,
                               const ast::Model& model,
                               const std::set<std::string>& localNames,
                               std::map<std::string, std::string>& references) {
    using ast::ExpressionKind;

    switch (expression.kind()) {
    case ExpressionKind::Number:
        return;
    case ExpressionKind::Identifier: {
        const auto& name = expression.name();
        if (localNames.count(name) != 0) {
            addFunctionReference(references, name, "Local");
        } else if (name == "time" || name == "t") {
            addFunctionReference(references, name, "Time");
        } else if (model.getParameters().contains(name)) {
            addFunctionReference(references, name, "Constant");
        } else if (modelHasFunction(model, name)) {
            addFunctionReference(references, name, "Function");
        } else {
            const auto isObservable = std::any_of(
                model.getObservables().begin(), model.getObservables().end(),
                [&](const auto& observable) { return observable.getName() == name; });
            if (isObservable) addFunctionReference(references, name, "Observable");
        }
        return;
    }
    case ExpressionKind::Function:
        if ((expression.name() == "time" || expression.name() == "t") &&
            expression.args().empty()) {
            addFunctionReference(references, expression.name(), "Time");
        } else if (modelHasFunction(model, expression.name())) {
            addFunctionReference(references, expression.name(), "Function");
        } else if (expression.args().empty() &&
                   std::any_of(model.getObservables().begin(), model.getObservables().end(),
                               [&](const auto& observable) {
                                   return observable.getName() == expression.name();
                               })) {
            addFunctionReference(references, expression.name(), "Observable");
        }
        for (const auto& child : expression.args()) {
            collectFunctionReferences(child, model, localNames, references);
        }
        return;
    case ExpressionKind::ObservableRef:
        if (modelHasFunction(model, expression.name())) {
            addFunctionReference(references, expression.name(), "Function");
        } else {
            addFunctionReference(references, expression.name(), "Observable");
        }
        for (const auto& child : expression.args()) {
            collectFunctionReferences(child, model, localNames, references);
        }
        return;
    case ExpressionKind::TableFunction:
        if (!expression.args().empty()) {
            collectFunctionReferences(expression.args().front(), model, localNames,
                                      references);
        }
        return;
    case ExpressionKind::Unary:
    case ExpressionKind::Binary:
        for (const auto& child : expression.args()) {
            collectFunctionReferences(child, model, localNames, references);
        }
        return;
    }
}

void collectTableFunctions(const ast::Expression& expression,
                           std::vector<const ast::Expression*>& tables) {
    if (expression.kind() == ast::ExpressionKind::TableFunction) {
        tables.push_back(&expression);
    }
    for (const auto& child : expression.args()) {
        collectTableFunctions(child, tables);
    }
}

std::string expressionForXml(const ast::Expression& expression) {
    using ast::ExpressionKind;
    switch (expression.kind()) {
    case ExpressionKind::Number:
    case ExpressionKind::Identifier:
        return expression.toString();
    case ExpressionKind::Unary:
        return expression.name() + expressionForXml(expression.args().front());
    case ExpressionKind::Binary:
        return "(" + expressionForXml(expression.args()[0]) + " " + expression.name() +
               " " + expressionForXml(expression.args()[1]) + ")";
    case ExpressionKind::Function:
    case ExpressionKind::ObservableRef: {
        std::ostringstream output;
        output << expression.name() << '(';
        for (std::size_t index = 0; index < expression.args().size(); ++index) {
            if (index != 0) output << ',';
            output << expressionForXml(expression.args()[index]);
        }
        output << ')';
        return output.str();
    }
    case ExpressionKind::TableFunction:
        return "__TFUN_VAL__";
    }
    return {};
}

bool expandDynamicRateExpression(
    const ast::Expression& expression,
    const ast::Model& model,
    std::map<std::string, std::string>& references,
    std::vector<const ast::Expression*>& tableFunctions,
    std::set<std::string>& activeFunctions,
    std::string& expanded,
    std::string& diagnostic) {
    using ast::ExpressionKind;

    const auto findFunction = [&](const std::string& name) -> const ast::Function* {
        const auto found = std::find_if(
            model.getFunctions().begin(), model.getFunctions().end(),
            [&](const auto& function) { return function.getName() == name; });
        return found == model.getFunctions().end() ? nullptr : &*found;
    };
    const auto hasObservable = [&](const std::string& name) {
        return std::any_of(
            model.getObservables().begin(), model.getObservables().end(),
            [&](const auto& observable) { return observable.getName() == name; });
    };
    const auto expandModelFunction = [&](const ast::Function& function,
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
            function.getExpression(), model, references, tableFunctions,
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
            findFunction(node.name()) != nullptr) {
            return true;
        }
        return std::any_of(node.args().begin(), node.args().end(),
                           [&](const auto& child) { return self(child, self); });
    };

    switch (expression.kind()) {
    case ExpressionKind::Number:
    case ExpressionKind::Identifier: {
        const auto& name = expression.name();
        if (expression.kind() == ExpressionKind::Identifier &&
            (lowercaseName(name) == "time" || lowercaseName(name) == "t")) {
            addFunctionReference(references, name, "Time");
            expanded = name;
            return true;
        }
        if (expression.kind() == ExpressionKind::Number) {
            expanded = expression.toString();
            return true;
        }
        if (model.getParameters().contains(name)) {
            addFunctionReference(references, name, "Constant");
            expanded = name;
            return true;
        }
        if (const auto* function = findFunction(name)) {
            if (!expressionHasModelFunctionReference(
                    function->getExpression(), expressionHasModelFunctionReference)) {
                addFunctionReference(references, name, "Function");
                expanded = name;
                return true;
            }
            return expandModelFunction(*function, expanded);
        }
        if (hasObservable(name)) {
            addFunctionReference(references, name, "Observable");
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
                expression.args().front(), model, references, tableFunctions,
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
                expression.args()[0], model, references, tableFunctions,
                activeFunctions, lhs, diagnostic) ||
            !expandDynamicRateExpression(
                expression.args()[1], model, references, tableFunctions,
                activeFunctions, rhs, diagnostic)) {
            return false;
        }
        expanded = "(" + lhs + " " + expression.name() + " " + rhs + ")";
        return true;
    }
    case ExpressionKind::Function: {
        const auto& name = expression.name();
        const auto lowerName = lowercaseName(name);
        if (lowerName == "time" || lowerName == "t") {
            if (!expression.args().empty()) {
                diagnostic = name + "() takes no arguments";
                return false;
            }
            addFunctionReference(references, lowerName, "Time");
            expanded = lowerName;
            return true;
        }
        if (const auto* function = findFunction(name)) {
            if (!expression.args().empty()) {
                diagnostic = "dynamic rates cannot call zero-argument model function '" +
                             name + "' with arguments";
                return false;
            }
            if (!expressionHasModelFunctionReference(
                    function->getExpression(), expressionHasModelFunctionReference)) {
                addFunctionReference(references, name, "Function");
                expanded = name + "()";
                return true;
            }
            return expandModelFunction(*function, expanded);
        }
        if (expression.args().empty() && hasObservable(name)) {
            addFunctionReference(references, name, "Observable");
            expanded = name + "()";
            return true;
        }
        std::ostringstream output;
        output << name << '(';
        for (std::size_t index = 0; index < expression.args().size(); ++index) {
            if (index != 0) output << ',';
            std::string argument;
            if (!expandDynamicRateExpression(
                    expression.args()[index], model, references, tableFunctions,
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
        if (const auto* function = findFunction(name)) {
            if (!expression.args().empty()) {
                diagnostic = "dynamic rates cannot call zero-argument model function '" +
                             name + "' with arguments";
                return false;
            }
            if (!expressionHasModelFunctionReference(
                    function->getExpression(), expressionHasModelFunctionReference)) {
                addFunctionReference(references, name, "Function");
                expanded = name + "()";
                return true;
            }
            return expandModelFunction(*function, expanded);
        }
        if (!expression.args().empty() || !hasObservable(name)) {
            diagnostic = "observable reference '" + name +
                         "' is missing or has unsupported arguments";
            return false;
        }
        addFunctionReference(references, name, "Observable");
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
        if (counter.kind() != ExpressionKind::Identifier &&
            counter.kind() != ExpressionKind::Function &&
            counter.kind() != ExpressionKind::ObservableRef) {
            diagnostic = "TFUN counter must be time, a parameter, observable, or function name";
            return false;
        }
        const auto counterName = counter.name();
        const auto lowerCounterName = lowercaseName(counterName);
        if (lowerCounterName == "time" || lowerCounterName == "t") {
            if (!counter.args().empty()) {
                diagnostic = "TFUN time counter cannot take arguments";
                return false;
            }
            addFunctionReference(references, lowerCounterName, "Time");
        } else if (counter.kind() == ExpressionKind::Identifier &&
                   model.getParameters().contains(counterName)) {
            addFunctionReference(references, counterName, "Constant");
        } else if (counter.args().empty() && hasObservable(counterName)) {
            addFunctionReference(references, counterName, "Observable");
        } else if (counter.args().empty() && findFunction(counterName) != nullptr) {
            addFunctionReference(references, counterName, "Function");
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

std::string tableCounterName(const ast::Expression& table) {
    if (table.args().empty()) return {};
    const auto& counter = table.args().front();
    if (counter.kind() == ast::ExpressionKind::Identifier ||
        counter.kind() == ast::ExpressionKind::Function ||
        counter.kind() == ast::ExpressionKind::ObservableRef) {
        return counter.name();
    }
    return {};
}

std::string tableDataCsv(const std::vector<double>& values) {
    std::ostringstream output;
    output << std::setprecision(17);
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (index != 0) output << ',';
        output << values[index];
    }
    return output.str();
}

std::string lowercaseName(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

bool expressionUsesTimeReference(const ast::Expression& expression) {
    if (expression.kind() == ast::ExpressionKind::Identifier &&
        (lowercaseName(expression.name()) == "time" ||
         lowercaseName(expression.name()) == "t")) {
        return true;
    }
    if (expression.kind() == ast::ExpressionKind::Function &&
        (lowercaseName(expression.name()) == "time" ||
         lowercaseName(expression.name()) == "t")) {
        return true;
    }
    return std::any_of(expression.args().begin(), expression.args().end(),
                       [](const auto& child) { return expressionUsesTimeReference(child); });
}

bool expressionCanEvaluateStatically(const ast::Expression& expression,
                                      const ast::Model& model,
                                      double& value) {
    if (expressionUsesTimeReference(expression)) return false;
    for (const auto& dependency : expression.getDependencies()) {
        if (!model.getParameters().contains(dependency)) return false;
    }
    try {
        value = expression.evaluate([&](const std::string& name) {
            return model.getParameters().evaluate(name);
        });
    } catch (...) {
        return false;
    }
    return std::isfinite(value);
}

bool modelContainsFunction(const ast::Model& model, const std::string& name) {
    return std::any_of(model.getFunctions().begin(), model.getFunctions().end(),
                       [&](const auto& function) { return function.getName() == name; });
}

bool needsGeneratedDynamicRateFunction(const ast::Model& model,
                                       const ast::Expression& rate) {
    const bool isCall = rate.kind() == ast::ExpressionKind::Function ||
                        rate.kind() == ast::ExpressionKind::ObservableRef;
    if (isCall && modelContainsFunction(model, rate.name())) return false;
    if (isCall) {
        const auto name = lowercaseName(rate.name());
        if ((name == "functionproduct" && rate.args().size() == 2) ||
            (name == "mm" && rate.args().size() == 2) ||
            (name == "arrhenius" && rate.args().size() >= 2) ||
            (name == "sat" && rate.args().size() == 2) ||
            (name == "hill" && rate.args().size() == 3)) {
            return false;
        }
    }
    double unused = 0.0;
    return !expressionCanEvaluateStatically(rate, model, unused);
}

std::string generatedDynamicRateFunctionName(const std::string& reactionId) {
    return "__bng3_reaction_rate_" + reactionId;
}

} // anonymous namespace

std::string XmlWriter::write(const ast::Model& model, const engine::GeneratedNetwork* network) {
    std::ostringstream xml;

    xml << "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
    xml << "<!-- Created by BioNetGen C++ -->\n";
    xml << "<sbml xmlns=\"http://www.sbml.org/sbml/level3\" level=\"3\" version=\"1\">\n";
    xml << "  <model id=\"" << escapeXml(model.getModelName()) << "\"";
    const auto numberPerQuantity = model.getOptions().find("NumberPerQuantityUnit");
    if (numberPerQuantity != model.getOptions().end()) {
        xml << " NumberPerQuantityUnit=\"" << escapeXml(numberPerQuantity->second) << "\"";
    }
    xml << ">\n";

    xml << writeParameters(model);
    xml << writeMoleculeTypes(model);
    xml << writeCompartments(model);
    xml << writeSpecies(model, network);
    xml << writeReactionRules(model);
    xml << writeObservables(model);
    xml << writeFunctions(model);

    xml << "  </model>\n";
    xml << "</sbml>\n";

    return xml.str();
}

std::string XmlWriter::writeParameters(const ast::Model& model) {
    std::ostringstream xml;
    xml << "    <ListOfParameters>\n";

    for (const auto& param : model.getParameters().all()) {
        xml << "      <Parameter id=\"" << escapeXml(param.getName())
            << "\" type=\"Constant\""
            << " value=\"" << param.getValue()
            << "\" expr=\"" << escapeXml(param.getExpression().toString()) << "\"/>\n";
    }

    xml << "    </ListOfParameters>\n";
    return xml.str();
}

std::string XmlWriter::writeMoleculeTypes(const ast::Model& model) {
    std::ostringstream xml;
    xml << "    <ListOfMoleculeTypes>\n";

    for (const auto& mt : model.getMoleculeTypes()) {
        xml << "      <MoleculeType id=\"" << escapeXml(mt.getName()) << "\">\n";
        xml << "        <ListOfComponentTypes>\n";

        for (const auto& comp : mt.getComponents()) {
            xml << "          <ComponentType id=\"" << escapeXml(comp.name) << "\"";
            if (!comp.allowedStates.empty()) {
                xml << ">\n";
                xml << "            <ListOfAllowedStates>\n";
                for (const auto& state : comp.allowedStates) {
                    xml << "              <AllowedState id=\"" << escapeXml(state) << "\"/>\n";
                }
                xml << "            </ListOfAllowedStates>\n";
                xml << "          </ComponentType>\n";
            } else {
                xml << "/>\n";
            }
        }

        xml << "        </ListOfComponentTypes>\n";
        xml << "      </MoleculeType>\n";
    }

    xml << "    </ListOfMoleculeTypes>\n";
    return xml.str();
}

std::string XmlWriter::writeCompartments(const ast::Model& model) {
    std::ostringstream xml;
    if (model.getCompartments().empty()) return {};

    xml << "    <ListOfCompartments>\n";

    for (const auto& comp : model.getCompartments()) {
        xml << "      <Compartment id=\"" << escapeXml(comp.getName())
            << "\" spatialDimensions=\"" << comp.getDimension()
            << "\" size=\"" << comp.getVolume() << "\"";
        if (!comp.getParent().empty()) {
            xml << " outside=\"" << escapeXml(comp.getParent()) << "\"";
        }
        xml << "/>\n";
    }

    xml << "    </ListOfCompartments>\n";
    return xml.str();
}

std::string XmlWriter::writeSpecies(const ast::Model& model, const engine::GeneratedNetwork* network) {
    std::ostringstream xml;
    xml << "    <ListOfSpecies>\n";

    if (network) {
        for (std::size_t i = 0; i < network->species.size(); ++i) {
            const auto& species = network->species.get(i);
            std::string spId = "S" + std::to_string(i + 1);
            std::string patternStr = species.getSpeciesGraph().toString();

            xml << "      <Species id=\"" << spId
                << "\" concentration=\"" << species.getAmount()
                << "\" name=\"" << escapeXml(patternStr) << "\">\n";

            // Serialize species pattern
            auto parsed = parsePattern(patternStr);
            xml << patternToXml(parsed, spId, "        ");

            xml << "      </Species>\n";
        }
    } else {
        for (std::size_t i = 0; i < model.getSeedSpecies().size(); ++i) {
            const auto& seed = model.getSeedSpecies()[i];
            std::string spId = "S" + std::to_string(i + 1);

            auto amountValue = seed.getAmount().evaluate([&](const std::string& name) {
                return model.getParameters().evaluate(name);
            }, 0.0);

            xml << "      <Species id=\"" << spId
                << "\" concentration=\"" << amountValue
                << "\" name=\"" << escapeXml(seed.getPattern()) << "\">\n";

            auto parsed = parsePattern(seed.getPattern());
            xml << patternToXml(parsed, spId, "        ");

            xml << "      </Species>\n";
        }
    }

    xml << "    </ListOfSpecies>\n";
    return xml.str();
}

std::string XmlWriter::writeReactionRules(const ast::Model& model) {
    std::ostringstream xml;
    xml << "    <ListOfReactionRules>\n";

    const auto lowercase = [](std::string value) {
        std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        });
        return value;
    };
    const auto hasModifier = [&](const std::vector<std::string>& modifiers,
                                 const std::string& wanted) {
        const auto needle = lowercase(wanted);
        return std::any_of(modifiers.begin(), modifiers.end(), [&](const auto& modifier) {
            return lowercase(modifier) == needle;
        });
    };
    const auto modelFunction = [&](const std::string& name) -> const ast::Function* {
        const auto found = std::find_if(
            model.getFunctions().begin(), model.getFunctions().end(),
            [&](const auto& function) { return function.getName() == name; });
        return found == model.getFunctions().end() ? nullptr : &*found;
    };
    const auto moleculeId = [](const std::string& rrId, bool product,
                               const ast::ReactionRule::ComponentRef& ref) {
        return rrId + (product ? "_PP" : "_RP") +
               std::to_string(ref.patternIndex + 1) + "_M" +
               std::to_string(ref.moleculeIndex + 1);
    };
    const auto componentId = [&](const std::string& rrId, bool product,
                                 const ast::ReactionRule::ComponentRef& ref) {
        return moleculeId(rrId, product, ref) + "_C" +
               std::to_string(ref.componentIndex + 1);
    };
    // Find the molecule referenced by a local-function argument.  BNG-XML
    // stores an object reference, while the AST retains either `%x::A()` or
    // the older `M%x(...)` label spelling.
    const auto scopedMoleculeId = [&](const ast::ReactionRule& rule,
                                      const std::string& rrId,
                                      const std::string& argument) {
        const std::string token = "%" + argument + "::";
        for (std::size_t patternIndex = 0; patternIndex < rule.getReactants().size();
             ++patternIndex) {
            const auto parsed = parsePattern(rule.getReactants()[patternIndex]);
            for (std::size_t moleculeIndex = 0; moleculeIndex < parsed.molecules.size();
                 ++moleculeIndex) {
                if (parsed.molecules[moleculeIndex].label == argument) {
                    if (parsed.molecules[moleculeIndex].scopePrefix) {
                        return rrId + "_RP" + std::to_string(patternIndex + 1);
                    }
                    return rrId + "_RP" + std::to_string(patternIndex + 1) + "_M" +
                           std::to_string(moleculeIndex + 1);
                }
            }

            const auto scopePosition = rule.getReactants()[patternIndex].find(token);
            if (scopePosition == std::string::npos) continue;
            std::size_t moleculeIndex = 0;
            int depth = 0;
            for (std::size_t i = 0; i < scopePosition; ++i) {
                if (rule.getReactants()[patternIndex][i] == '(') ++depth;
                else if (rule.getReactants()[patternIndex][i] == ')') --depth;
                else if (rule.getReactants()[patternIndex][i] == '.' && depth == 0) {
                    ++moleculeIndex;
                }
            }
            if (moleculeIndex < parsed.molecules.size()) {
                return rrId + "_RP" + std::to_string(patternIndex + 1) + "_M" +
                       std::to_string(moleculeIndex + 1);
            }
        }
        return std::string();
    };

    const auto writeRateLaw = [&](const ast::ReactionRule& rule,
                                  const std::string& rrId,
                                  const ast::Expression& rate) {
        const bool isCall = rate.kind() == ast::ExpressionKind::Function ||
                            rate.kind() == ast::ExpressionKind::ObservableRef;
        const bool isFunctionProduct =
            isCall && lowercase(rate.name()) == "functionproduct" && rate.args().size() == 2;
        const auto* declaredFunction = modelFunction(rate.name());
        const bool generatedRateFunction =
            needsGeneratedDynamicRateFunction(model, rate);
        std::string type = "Ele";
        if (generatedRateFunction) {
            type = "Function";
        } else if (isFunctionProduct) {
            type = "FunctionProduct";
        } else if (declaredFunction != nullptr) {
            type = "Function";
        } else if (isCall && lowercase(rate.name()) == "mm" && rate.args().size() == 2) {
            type = "MM";
        } else if (isCall && lowercase(rate.name()) == "arrhenius" &&
                   rate.args().size() >= 2) {
            type = "Arrhenius";
        } else if (isCall && lowercase(rate.name()) == "sat" && rate.args().size() == 2) {
            type = "Sat";
        } else if (isCall && lowercase(rate.name()) == "hill" && rate.args().size() == 3) {
            type = "Hill";
        }

        xml << "        <RateLaw id=\"" << rrId << "_RateLaw\" type=\"" << type
            << "\" totalrate=\"0\"";
        if (type == "FunctionProduct") {
            const auto writeOperand = [&](const ast::Expression& operand,
                                           const char* functionAttribute,
                                           const char* argumentListName) {
                if (operand.kind() != ast::ExpressionKind::Function &&
                    operand.kind() != ast::ExpressionKind::ObservableRef) {
                    throw std::runtime_error(
                        "FunctionProduct XML operands must be function calls");
                }
                const auto* function = modelFunction(operand.name());
                if (function == nullptr || function->getArgs().size() != 1 ||
                    operand.args().size() != 1 ||
                    operand.args().front().kind() != ast::ExpressionKind::Identifier) {
                    throw std::runtime_error(
                        "FunctionProduct XML operands must call one-argument local functions");
                }
                xml << " " << functionAttribute << "=\""
                    << escapeXml(operand.name()) << "\"";
                return std::make_pair(operand.args().front().name(), argumentListName);
            };
            const auto argument1 = writeOperand(rate.args()[0], "name1", "ListOfArguments1");
            const auto argument2 = writeOperand(rate.args()[1], "name2", "ListOfArguments2");
            xml << ">\n";
            const auto writeArguments = [&](const std::pair<std::string, const char*>& argument) {
                const auto value = scopedMoleculeId(rule, rrId, argument.first);
                if (value.empty()) {
                    throw std::runtime_error(
                        "FunctionProduct XML argument has no scoped reactant");
                }
                xml << "          <" << argument.second << ">\n"
                    << "            <Argument id=\"" << escapeXml(argument.first)
                    << "\" type=\"ObjectReference\" value=\""
                    << escapeXml(value) << "\"/>\n"
                    << "          </" << argument.second << ">\n";
            };
            writeArguments(argument1);
            writeArguments(argument2);
            xml << "        </RateLaw>\n";
            return;
        }
        if (type == "Function") {
            const auto functionName = generatedRateFunction
                                           ? generatedDynamicRateFunctionName(rrId)
                                           : rate.name();
            xml << " name=\"" << escapeXml(functionName) << "\">\n";
            xml << "          <ListOfArguments>\n";
            if (declaredFunction != nullptr) {
                for (std::size_t index = 0; index < declaredFunction->getArgs().size(); ++index) {
                    const auto& argument = declaredFunction->getArgs()[index];
                    const auto value = scopedMoleculeId(rule, rrId, argument);
                    xml << "            <Argument id=\"" << escapeXml(argument)
                        << "\" type=\"ObjectReference\" value=\""
                        << escapeXml(value) << "\"/>\n";
                }
            }
            xml << "          </ListOfArguments>\n";
            xml << "        </RateLaw>\n";
            return;
        }

        xml << ">\n";
        xml << "          <ListOfRateConstants>\n";
        if (type == "MM" || type == "Arrhenius" || type == "Sat" || type == "Hill") {
            for (const auto& argument : rate.args()) {
                xml << "            <RateConstant value=\""
                    << escapeXml(argument.toString()) << "\"/>\n";
            }
        } else {
            double staticValue = 0.0;
            std::string value = rate.toString();
            if (rate.kind() != ast::ExpressionKind::Identifier &&
                expressionCanEvaluateStatically(rate, model, staticValue)) {
                std::ostringstream numeric;
                numeric << std::setprecision(17) << staticValue;
                value = numeric.str();
            }
            xml << "            <RateConstant value=\"" << escapeXml(value) << "\"/>\n";
        }
        xml << "          </ListOfRateConstants>\n";
        xml << "        </RateLaw>\n";
    };

    const auto writeRule = [&](const ast::ReactionRule& rule,
                               const std::string& rrId,
                               const ast::Expression* rate) {
        xml << "      <ReactionRule id=\"" << rrId
            << "\" name=\"" << escapeXml(rule.getRuleName()) << "\">\n";

        xml << "        <ListOfReactantPatterns>\n";
        for (std::size_t index = 0; index < rule.getReactants().size(); ++index) {
            const auto patternId = rrId + "_RP" + std::to_string(index + 1);
            const auto parsed = parsePattern(rule.getReactants()[index]);
            xml << "          <ReactantPattern id=\"" << patternId << "\"";
            if (!parsed.compartment.empty()) {
                xml << " compartment=\"" << escapeXml(parsed.compartment) << "\"";
            }
            xml << ">\n" << patternToXml(parsed, patternId, "            ")
                << "          </ReactantPattern>\n";
        }
        xml << "        </ListOfReactantPatterns>\n";

        xml << "        <ListOfProductPatterns>\n";
        for (std::size_t index = 0; index < rule.getProducts().size(); ++index) {
            const auto patternId = rrId + "_PP" + std::to_string(index + 1);
            const auto parsed = parsePattern(rule.getProducts()[index]);
            xml << "          <ProductPattern id=\"" << patternId << "\"";
            if (!parsed.compartment.empty()) {
                xml << " compartment=\"" << escapeXml(parsed.compartment) << "\"";
            }
            xml << ">\n" << patternToXml(parsed, patternId, "            ")
                << "          </ProductPattern>\n";
        }
        xml << "        </ListOfProductPatterns>\n";

        const auto writeFilters = [&](const ParsedReactionFilter& filter,
                                      const std::string& listId) {
            const char* listName = filter.include
                                       ? (filter.products ? "ListOfIncludeProducts"
                                                           : "ListOfIncludeReactants")
                                       : (filter.products ? "ListOfExcludeProducts"
                                                           : "ListOfExcludeReactants");
            xml << "        <" << listName << " id=\"" << escapeXml(listId) << "\">\n";
            for (std::size_t index = 0; index < filter.patterns.size(); ++index) {
                const auto parsed = parsePattern(filter.patterns[index]);
                if (parsed.molecules.empty()) {
                    throw std::runtime_error(
                        "reaction filter pattern contains no molecule: '" +
                        filter.patterns[index] + "'");
                }
                const auto patternId = listId + "_P" + std::to_string(index + 1);
                xml << "          <Pattern id=\"" << escapeXml(patternId) << "\">\n"
                    << patternToXml(parsed, patternId, "            ")
                    << "          </Pattern>\n";
            }
            xml << "        </" << listName << ">\n";
        };

        for (const auto& modifier : rule.getModifiers()) {
            if (!isReactionFilterModifier(modifier)) continue;
            ParsedReactionFilter filter;
            std::string diagnostic;
            if (!parseReactionFilterModifier(modifier, filter, diagnostic)) {
                throw std::runtime_error(diagnostic);
            }
            const std::size_t patternCount = filter.products
                                                 ? rule.getProducts().size()
                                                 : rule.getReactants().size();
            if (filter.patternIndex >= patternCount) {
                throw std::runtime_error(
                    "reaction filter refers to an unknown pattern index: '" + modifier + "'");
            }
            const auto prefix = filter.products ? "_PP" : "_RP";
            const auto listId = rrId + prefix + std::to_string(filter.patternIndex + 1);
            writeFilters(filter, listId);
        }

        if (rate != nullptr) writeRateLaw(rule, rrId, *rate);

        xml << "        <Map>\n";
        for (const auto& [product, reactant] : rule.getMoleculeMappings()) {
            xml << "          <MapItem sourceID=\"" << moleculeId(rrId, false, reactant)
                << "\" targetID=\"" << moleculeId(rrId, true, product) << "\"/>\n";
        }
        for (const auto& [product, reactant] : rule.getComponentMappings()) {
            xml << "          <MapItem sourceID=\"" << componentId(rrId, false, reactant)
                << "\" targetID=\"" << componentId(rrId, true, product) << "\"/>\n";
        }
        xml << "        </Map>\n";

        xml << "        <ListOfOperations>\n";
        for (const auto& operation : rule.getOperations()) {
            using Type = ast::ReactionRule::TransformOp::Type;
            switch (operation.type) {
            case Type::ChangeState:
                xml << "          <StateChange site=\""
                    << componentId(rrId, false, operation.source)
                    << "\" finalState=\"" << escapeXml(operation.newState) << "\"/>\n";
                break;
            case Type::AddBond:
                xml << "          <AddBond site1=\""
                    << componentId(rrId, false, operation.source)
                    << "\" site2=\"" << componentId(rrId, false, operation.partner)
                    << "\"/>\n";
                break;
            case Type::DeleteBond:
                xml << "          <DeleteBond site1=\""
                    << componentId(rrId, false, operation.source)
                    << "\" site2=\"" << componentId(rrId, false, operation.partner)
                    << "\"/>\n";
                break;
            case Type::AddMolecule:
                xml << "          <Add id=\""
                    << moleculeId(rrId, true, {operation.patternIndex, operation.moleculeIndex, 0})
                    << "\"/>\n";
                break;
            case Type::DeleteMolecule:
                if (hasModifier(rule.getModifiers(), "DeleteMolecules")) {
                    xml << "          <Delete id=\""
                        << moleculeId(rrId, false,
                                      {operation.patternIndex, operation.moleculeIndex, 0})
                        << "\" DeleteMolecules=\"1\"/>\n";
                } else {
                    // NFsim rejects a single-molecule Delete without the
                    // DeleteMolecules modifier.  BNG2 represents this case as
                    // removal of the complete reactant pattern.
                    xml << "          <Delete id=\"" << rrId << "_RP"
                        << (operation.patternIndex + 1)
                        << "\" DeleteMolecules=\"0\"/>\n";
                }
                break;
            }
        }

        // Cross-bonds and bonds between newly-created molecules are not
        // represented as TransformOp entries because their product endpoints
        // have no reactant mapping.  They still belong in BNG-XML operations.
        for (const auto& [reactant, product] : rule.getCrossBonds()) {
            xml << "          <AddBond site1=\"" << componentId(rrId, false, reactant)
                << "\" site2=\"" << componentId(rrId, true, product) << "\"/>\n";
        }
        for (const auto& [product1, product2] : rule.getNewMoleculeBonds()) {
            xml << "          <AddBond site1=\"" << componentId(rrId, true, product1)
                << "\" site2=\"" << componentId(rrId, true, product2) << "\"/>\n";
        }

        // Pure degradation has no product graph and therefore no TransformOp
        // from ReactionRule::initialize().  Preserve its species-removal
        // operation for the XML compatibility loader.
        if (rule.getProducts().empty() && rule.getOperations().empty()) {
            for (std::size_t index = 0; index < rule.getReactants().size(); ++index) {
                xml << "          <Delete id=\"" << rrId << "_RP" << (index + 1)
                    << "\" DeleteMolecules=\"0\"/>\n";
            }
        }

        // Preserve explicit compartment transport for mapped molecules.  The
        // pattern-level compartment is the fallback when no molecule suffix is
        // present in the source spelling.
        for (const auto& [product, reactant] : rule.getMoleculeMappings()) {
            const auto reactantPattern = parsePattern(rule.getReactants()[reactant.patternIndex]);
            const auto productPattern = parsePattern(rule.getProducts()[product.patternIndex]);
            const auto compartment = [&](const auto& parsed,
                                         const ast::ReactionRule::ComponentRef& ref) {
                if (ref.moleculeIndex < parsed.molecules.size() &&
                    !parsed.molecules[ref.moleculeIndex].compartment.empty()) {
                    return parsed.molecules[ref.moleculeIndex].compartment;
                }
                return parsed.compartment;
            };
            const auto from = compartment(reactantPattern, reactant);
            const auto to = compartment(productPattern, product);
            if (!to.empty() && from != to) {
                xml << "          <ChangeCompartment id=\""
                    << moleculeId(rrId, false, reactant) << "\" destination=\""
                    << escapeXml(to) << "\" moveConnected=\""
                    << (hasModifier(rule.getModifiers(), "MoveConnected") ? "1" : "0")
                    << "\"/>\n";
            }
        }

        xml << "        </ListOfOperations>\n";
        xml << "      </ReactionRule>\n";
    };

    for (std::size_t i = 0; i < model.getReactionRules().size(); ++i) {
        const auto& rule = model.getReactionRules()[i];
        const auto rrId = "RR" + std::to_string(i + 1);
        const auto* forwardRate = rule.getRates().empty() ? nullptr : &rule.getRates().front();
        writeRule(rule, rrId, forwardRate);

        if (rule.isBidirectional() && rule.getRates().size() >= 2) {
            std::vector<std::string> reverseModifiers;
            for (const auto& modifier : rule.getModifiers()) {
                std::string transformed = modifier;
                if (transformed.find("exclude_reactants") == 0) {
                    transformed.replace(0, 17, "exclude_products");
                } else if (transformed.find("include_reactants") == 0) {
                    transformed.replace(0, 17, "include_products");
                } else if (transformed.find("exclude_products") == 0) {
                    transformed.replace(0, 16, "exclude_reactants");
                } else if (transformed.find("include_products") == 0) {
                    transformed.replace(0, 16, "include_reactants");
                }
                reverseModifiers.push_back(std::move(transformed));
            }
            ast::ReactionRule reverse(
                "_reverse__" + rule.getRuleName(),
                rule.getLabel().empty() ? "_reverse" : "_reverse__" + rule.getLabel(),
                rule.getProducts(), rule.getReactants(),
                std::vector<ast::Expression>{rule.getRates()[1]},
                std::move(reverseModifiers), false,
                rule.getProductPatterns(), rule.getReactantPatterns());
            writeRule(reverse, rrId + "r", &reverse.getRates().front());
        }
    }

    xml << "    </ListOfReactionRules>\n";
    return xml.str();
}

std::string XmlWriter::writeObservables(const ast::Model& model) {
    std::ostringstream xml;
    xml << "    <ListOfObservables>\n";

    for (std::size_t i = 0; i < model.getObservables().size(); ++i) {
        const auto& obs = model.getObservables()[i];
        xml << "      <Observable id=\"O" << (i + 1)
            << "\" name=\"" << escapeXml(obs.getName())
            << "\" type=\"" << obs.getType() << "\">\n";
        xml << "        <ListOfPatterns>\n";

        for (std::size_t p = 0; p < obs.getPatterns().size(); ++p) {
            std::string patId = "O" + std::to_string(i + 1) + "_P" + std::to_string(p + 1);
            auto parsed = parsePattern(obs.getPatterns()[p]);
            xml << "          <Pattern id=\"" << patId << "\"";
            if (!parsed.compartment.empty()) {
                xml << " compartment=\"" << parsed.compartment << "\"";
            }
            xml << ">\n";
            xml << patternToXml(parsed, patId, "            ");
            xml << "          </Pattern>\n";
        }

        xml << "        </ListOfPatterns>\n";
        xml << "      </Observable>\n";
    }

    xml << "    </ListOfObservables>\n";
    return xml.str();
}

std::string XmlWriter::writeFunctions(const ast::Model& model) {
    std::ostringstream xml;
    std::vector<GeneratedRateFunction> generatedRateFunctions;
    std::set<std::string> reservedFunctionNames;
    for (const auto& function : model.getFunctions()) {
        reservedFunctionNames.insert(function.getName());
    }

    const auto addGeneratedRateFunction = [&](const std::string& name,
                                               const ast::Expression& expression) {
        GeneratedRateFunction generated;
        generated.name = name;
        generated.expression = &expression;
        const std::string generatedPrefix = "__bng3_reaction_rate_";
        const std::string rateId = name.rfind(generatedPrefix, 0) == 0
                                       ? name.substr(generatedPrefix.size())
                                       : name;
        std::string diagnostic;
        std::set<std::string> activeFunctions;
        std::vector<const ast::Expression*> tableFunctions;
        if (!expandDynamicRateExpression(
                expression, model, generated.references, tableFunctions,
                activeFunctions, generated.expandedExpression, diagnostic)) {
            throw std::runtime_error(diagnostic);
        }
        if (tableFunctions.size() > 1) {
            throw std::runtime_error(
                "dynamic reaction rates support at most one TFUN expression");
        }
        generated.tableFunction = tableFunctions.empty() ? nullptr : tableFunctions.front();
        const bool hasModelFunctionReference = std::any_of(
            generated.references.begin(), generated.references.end(),
            [](const auto& reference) { return reference.second == "Function"; });
        if (hasModelFunctionReference) {
            std::size_t aliasIndex = 1;
            for (const auto& [referenceName, referenceType] : generated.references) {
                if (referenceType != "Observable") continue;

                const std::string aliasBase =
                    "__bng3_reaction_observable_" + rateId + "_" +
                    std::to_string(aliasIndex++);
                std::string aliasName = aliasBase;
                std::size_t aliasSuffix = 1;
                while (reservedFunctionNames.count(aliasName) != 0) {
                    aliasName = aliasBase + "_" + std::to_string(aliasSuffix++);
                }
                reservedFunctionNames.insert(aliasName);
                generated.observableAliases.emplace(referenceName, aliasName);
            }
        }

        reservedFunctionNames.insert(name);
        generatedRateFunctions.push_back(std::move(generated));
    };

    for (std::size_t index = 0; index < model.getReactionRules().size(); ++index) {
        const auto& rule = model.getReactionRules()[index];
        const auto& rates = rule.getRates();
        const auto forwardId = "RR" + std::to_string(index + 1);
        if (!rates.empty() && needsGeneratedDynamicRateFunction(model, rates.front())) {
            addGeneratedRateFunction(
                generatedDynamicRateFunctionName(forwardId), rates.front());
        }
        if (rule.isBidirectional() && rates.size() >= 2 &&
            needsGeneratedDynamicRateFunction(model, rates[1])) {
            addGeneratedRateFunction(
                generatedDynamicRateFunctionName(forwardId + "r"), rates[1]);
        }
    }
    if (model.getFunctions().empty() && generatedRateFunctions.empty()) return {};

    xml << "    <ListOfFunctions>\n";

    for (const auto& func : model.getFunctions()) {
        std::vector<const ast::Expression*> tableFunctions;
        collectTableFunctions(func.getExpression(), tableFunctions);
        const auto* table = tableFunctions.empty() ? nullptr : tableFunctions.front();
        xml << "      <Function id=\"" << escapeXml(func.getName()) << "\"";
        if (table != nullptr) {
            xml << " type=\"TFUN\" mode=\""
                << (table->tableFilePath().empty() ? "inline" : "file")
                << "\" method=\"" << escapeXml(table->tableMethod()) << "\"";
            const auto counterName = tableCounterName(*table);
            if (!counterName.empty()) {
                xml << " ctrName=\"" << escapeXml(counterName) << "\"";
            }
            if (table->tableFilePath().empty()) {
                xml << " xData=\"" << escapeXml(tableDataCsv(table->tableXValues()))
                    << "\" yData=\"" << escapeXml(tableDataCsv(table->tableYValues()))
                    << "\"";
            } else {
                xml << " file=\"" << escapeXml(table->tableFilePath()) << "\"";
            }
        }
        if (!func.getArgs().empty()) {
            xml << " args=\"";
            for (std::size_t a = 0; a < func.getArgs().size(); ++a) {
                if (a > 0) xml << ",";
                xml << escapeXml(func.getArgs()[a]);
            }
            xml << "\"";
        }
        xml << ">\n";
        if (!func.getArgs().empty()) {
            xml << "        <ListOfArguments>\n";
            for (const auto& arg : func.getArgs()) {
                xml << "          <Argument id=\"" << escapeXml(arg) << "\"/>\n";
            }
            xml << "        </ListOfArguments>\n";
        }

        std::set<std::string> localNames(func.getArgs().begin(), func.getArgs().end());
        std::map<std::string, std::string> references;
        for (const auto& arg : func.getArgs()) {
            addFunctionReference(references, arg, "Local");
        }
        collectFunctionReferences(func.getExpression(), model, localNames, references);
        xml << "        <ListOfReferences>\n";
        for (const auto& [name, type] : references) {
            xml << "          <Reference name=\"" << escapeXml(name)
                << "\" type=\"" << escapeXml(type) << "\"/>\n";
        }
        xml << "        </ListOfReferences>\n";
        xml << "        <Expression>" << escapeXml(expressionForXml(func.getExpression()))
            << "</Expression>\n";
        xml << "      </Function>\n";
    }

    // CompositeFunction cannot directly reference observables in the legacy
    // XML loader.  Emit zero-argument global aliases first when a generated
    // dynamic rate mixes an observable with a model function.
    for (const auto& generated : generatedRateFunctions) {
        for (const auto& [observableName, aliasName] : generated.observableAliases) {
            xml << "      <Function id=\"" << escapeXml(aliasName) << "\">\n";
            xml << "        <ListOfReferences>\n"
                << "          <Reference name=\"" << escapeXml(observableName)
                << "\" type=\"Observable\"/>\n"
                << "        </ListOfReferences>\n";
            xml << "        <Expression>" << escapeXml(observableName)
                << "</Expression>\n";
            xml << "      </Function>\n";
        }
    }

    // NFsim's legacy XML schema represents an arbitrary dynamic reaction rate
    // as a zero-argument global function.  Keep the reaction rule readable,
    // but emit the generated function here so the XML compatibility path has
    // the same live observable/time dependencies as the direct adapter.
    for (const auto& generated : generatedRateFunctions) {
        const auto& name = generated.name;
        const auto* table = generated.tableFunction;
        xml << "      <Function id=\"" << escapeXml(name) << "\"";
        if (table != nullptr) {
            xml << " type=\"TFUN\" mode=\""
                << (table->tableFilePath().empty() ? "inline" : "file")
                << "\" method=\"" << escapeXml(table->tableMethod()) << "\"";
            const auto counterName = tableCounterName(*table);
            if (!counterName.empty()) {
                xml << " ctrName=\"" << escapeXml(counterName) << "\"";
            }
            if (table->tableFilePath().empty()) {
                xml << " xData=\"" << escapeXml(tableDataCsv(table->tableXValues()))
                    << "\" yData=\"" << escapeXml(tableDataCsv(table->tableYValues()))
                    << "\"";
            } else {
                xml << " file=\"" << escapeXml(table->tableFilePath()) << "\"";
            }
        }
        xml << ">\n";
        auto references = generated.references;
        for (const auto& [observableName, aliasName] : generated.observableAliases) {
            references.erase(observableName);
            addFunctionReference(references, aliasName, "Function");
        }
        xml << "        <ListOfReferences>\n";
        for (const auto& [referenceName, referenceType] : references) {
            xml << "          <Reference name=\"" << escapeXml(referenceName)
                << "\" type=\"" << escapeXml(referenceType) << "\"/>\n";
        }
        xml << "        </ListOfReferences>\n";
        const auto expressionWithAliases = replaceNamedReferences(
            generated.expandedExpression, generated.observableAliases);
        xml << "        <Expression>" << escapeXml(expressionWithAliases)
            << "</Expression>\n";
        xml << "      </Function>\n";
    }

    xml << "    </ListOfFunctions>\n";
    return xml.str();
}

} // namespace bng::io
