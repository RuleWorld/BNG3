#include "SbmlReader.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "nfsim/NFinput/TinyXML/tinyxml.h"

namespace bng::io {

namespace {

std::string trim(const std::string& value) {
    auto first = std::find_if_not(value.begin(), value.end(), [](unsigned char c) {
        return std::isspace(c) != 0;
    });
    auto last = std::find_if_not(value.rbegin(), value.rend(), [](unsigned char c) {
        return std::isspace(c) != 0;
    }).base();
    if (first >= last) {
        return {};
    }
    return std::string(first, last);
}

std::string attribute(const TiXmlElement* element, const char* name,
                      const std::string& fallback = {}) {
    if (element == nullptr || element->Attribute(name) == nullptr) {
        return fallback;
    }
    return element->Attribute(name);
}

std::string elementText(const TiXmlElement* element) {
    return element == nullptr || element->GetText() == nullptr
        ? std::string{}
        : trim(element->GetText());
}

std::string sanitizeName(std::string name) {
    std::string result;
    for (const unsigned char c : name) {
        if (c == '(' || c == ')') {
            // Historical BNG2 flat-SBML conversion reserves two underscores
            // for each pattern delimiter: A() -> A____.
            result += "__";
        } else if (std::isalnum(c) != 0 || c == '_') {
            result += static_cast<char>(c);
        } else if (c == '-' || std::isspace(c) != 0) {
            result += '_';
        }
    }
    if (result.empty()) {
        result = "species";
    }
    if (std::isdigit(static_cast<unsigned char>(result.front())) != 0) {
        result.insert(0, "s");
    }
    return result;
}

bool parseBool(const std::string& value) {
    std::string lower;
    lower.reserve(value.size());
    for (const unsigned char c : value) {
        lower += static_cast<char>(std::tolower(c));
    }
    return lower == "1" || lower == "true" || lower == "yes";
}

std::string mathExpression(const TiXmlElement* element);

std::vector<const TiXmlElement*> childElements(const TiXmlElement* element) {
    std::vector<const TiXmlElement*> children;
    if (element == nullptr) {
        return children;
    }
    for (auto* child = element->FirstChildElement(); child != nullptr;
         child = child->NextSiblingElement()) {
        children.push_back(child);
    }
    return children;
}

std::string join(const std::vector<std::string>& values, const std::string& op) {
    std::ostringstream result;
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i != 0) {
            result << op;
        }
        result << values[i];
    }
    return result.str();
}

std::string mathExpression(const TiXmlElement* element) {
    if (element == nullptr) {
        return {};
    }
    const std::string tag = element->Value();
    if (tag == "math") {
        return mathExpression(element->FirstChildElement());
    }
    if (tag == "ci" || tag == "cn") {
        return elementText(element);
    }
    if (tag != "apply") {
        return {};
    }

    const auto children = childElements(element);
    if (children.empty()) {
        return {};
    }
    const std::string op = children.front()->Value();
    std::vector<std::string> args;
    for (std::size_t i = 1; i < children.size(); ++i) {
        const auto value = mathExpression(children[i]);
        if (!value.empty()) {
            args.push_back(value);
        }
    }
    if (op == "plus") {
        return join(args, "+");
    }
    if (op == "times") {
        return join(args, "*");
    }
    if (op == "divide" && args.size() == 2) {
        return args[0] + "/" + args[1];
    }
    if (op == "power" && args.size() == 2) {
        return args[0] + "^" + args[1];
    }
    if (op == "minus") {
        return args.size() == 1 ? "-" + args[0] : join(args, "-");
    }
    if (args.size() == 1 &&
        (op == "abs" || op == "exp" || op == "ln" || op == "log" ||
         op == "sqrt" || op == "sin" || op == "cos" || op == "tan")) {
        return op + "(" + args.front() + ")";
    }
    throw std::runtime_error("unsupported MathML operator: " + op);
}

std::vector<std::string> splitTopLevel(const std::string& expression, char delimiter) {
    std::vector<std::string> result;
    std::size_t start = 0;
    int depth = 0;
    for (std::size_t i = 0; i < expression.size(); ++i) {
        if (expression[i] == '(') {
            ++depth;
        } else if (expression[i] == ')') {
            --depth;
        } else if (expression[i] == delimiter && depth == 0) {
            result.push_back(trim(expression.substr(start, i - start)));
            start = i + 1;
        }
    }
    result.push_back(trim(expression.substr(start)));
    return result;
}

std::string stripReactantFactors(
    const std::string& expression, const std::vector<std::string>& reactants) {
    auto factors = splitTopLevel(expression, '*');
    std::map<std::string, std::size_t> required;
    for (const auto& reactant : reactants) {
        ++required[reactant];
    }
    for (auto& factor : factors) {
        auto candidate = factor;
        if (candidate.size() >= 2 && candidate.front() == '(' &&
            candidate.back() == ')') {
            candidate = candidate.substr(1, candidate.size() - 2);
        }
        const auto found = required.find(candidate);
        if (found != required.end() && found->second > 0) {
            factor.clear();
            --found->second;
        }
    }
    for (const auto& [reactant, count] : required) {
        if (count != 0) {
            throw std::runtime_error(
                "kinetic law does not expose mass-action factor for " + reactant);
        }
    }
    std::vector<std::string> remaining;
    for (const auto& factor : factors) {
        if (!factor.empty()) {
            remaining.push_back(factor);
        }
    }
    return remaining.empty() ? "1" : join(remaining, "*");
}

void collectIdentifiers(const TiXmlElement* element, std::vector<std::string>& ids) {
    if (element == nullptr) {
        return;
    }
    if (std::string(element->Value()) == "ci") {
        const auto value = elementText(element);
        if (!value.empty()) {
            ids.push_back(value);
        }
    }
    for (auto* child = element->FirstChildElement(); child != nullptr;
         child = child->NextSiblingElement()) {
        collectIdentifiers(child, ids);
    }
}

std::string indexList(const std::vector<int>& indices) {
    if (indices.empty()) {
        return "0";
    }
    std::ostringstream result;
    for (std::size_t i = 0; i < indices.size(); ++i) {
        if (i != 0) {
            result << ',';
        }
        result << indices[i];
    }
    return result.str();
}

std::string weightedList(const std::map<int, int>& entries) {
    std::ostringstream result;
    bool first = true;
    for (const auto& [index, weight] : entries) {
        if (!first) {
            result << ',';
        }
        first = false;
        if (weight != 1) {
            result << weight << '*';
        }
        result << index;
    }
    return result.str();
}

}  // namespace

NetReader::ParseResult SbmlReader::parse(
    const std::filesystem::path& filepath, bool atomize) {
    NetReader::ParseResult result;
    if (atomize) {
        result.error =
            "SBML atomize=true requires the Python atomizer conversion path";
        return result;
    }

    const auto filename = filepath.string();
    TiXmlDocument document(filename.c_str());
    if (!document.LoadFile()) {
        result.error = "Failed to parse SBML: " + std::string(document.ErrorDesc());
        return result;
    }
    const auto* root = document.RootElement();
    const auto* model = root == nullptr ? nullptr : root->FirstChildElement("model");
    if (root == nullptr || std::string(root->Value()) != "sbml" || model == nullptr) {
        result.error = "SBML document has no model element";
        return result;
    }

    try {
        std::unordered_map<std::string, int> speciesIndices;
        std::set<std::string> usedNames;

        const auto* compartments = model->FirstChildElement("listOfCompartments");
        if (compartments != nullptr) {
            for (auto* compartment = compartments->FirstChildElement("compartment");
                 compartment != nullptr;
                 compartment = compartment->NextSiblingElement("compartment")) {
                result.compartments.push_back(attribute(compartment, "id"));
            }
        }

        const auto* speciesList = model->FirstChildElement("listOfSpecies");
        if (speciesList != nullptr) {
            int index = 0;
            for (auto* species = speciesList->FirstChildElement("species");
                 species != nullptr;
                 species = species->NextSiblingElement("species")) {
                ++index;
                const auto id = attribute(species, "id");
                auto standardized = sanitizeName(attribute(species, "name", id));
                if (!usedNames.insert(standardized).second) {
                    standardized += "_" + id;
                    usedNames.insert(standardized);
                }
                const auto compartment = attribute(species, "compartment");
                std::string pattern;
                if (!compartment.empty()) {
                    pattern = "@" + compartment + "::";
                }
                if (parseBool(attribute(species, "constant")) ||
                    parseBool(attribute(species, "boundaryCondition"))) {
                    pattern += '$';
                }
                pattern += standardized + "()";
                speciesIndices[id] = index;
                std::string amount = attribute(species, "initialAmount");
                if (amount.empty()) {
                    amount = attribute(species, "initialConcentration", "0");
                }
                result.species.emplace_back(pattern, amount);
            }
        }
        if (result.species.empty()) {
            throw std::runtime_error("SBML model has no species");
        }

        const auto* parameterList = model->FirstChildElement("listOfParameters");
        if (parameterList != nullptr) {
            for (auto* parameter = parameterList->FirstChildElement("parameter");
                 parameter != nullptr;
                 parameter = parameter->NextSiblingElement("parameter")) {
                const auto id = attribute(parameter, "id");
                const auto value = attribute(parameter, "value");
                if (!id.empty() && !value.empty()) {
                    result.parameters[id] = std::stod(value);
                }
            }
        }

        const auto* reactionList = model->FirstChildElement("listOfReactions");
        if (reactionList != nullptr) {
            int index = 0;
            for (auto* reaction = reactionList->FirstChildElement("reaction");
                 reaction != nullptr;
                 reaction = reaction->NextSiblingElement("reaction")) {
                ++index;
                std::vector<int> reactantIndices;
                std::vector<std::string> reactantIds;
                const auto* reactants = reaction->FirstChildElement("listOfReactants");
                if (reactants != nullptr) {
                    for (auto* reference = reactants->FirstChildElement("speciesReference");
                         reference != nullptr;
                         reference = reference->NextSiblingElement("speciesReference")) {
                        const auto id = attribute(reference, "species");
                        const auto found = speciesIndices.find(id);
                        if (found == speciesIndices.end()) {
                            throw std::runtime_error(
                                "reaction references unknown species " + id);
                        }
                        int stoich = 1;
                        const auto stoichText = attribute(reference, "stoichiometry");
                        if (!stoichText.empty()) {
                            stoich = std::max(
                                1, static_cast<int>(std::stod(stoichText)));
                        }
                        for (int copy = 0; copy < stoich; ++copy) {
                            reactantIndices.push_back(found->second);
                            reactantIds.push_back(id);
                        }
                    }
                }

                std::vector<int> productIndices;
                const auto* products = reaction->FirstChildElement("listOfProducts");
                if (products != nullptr) {
                    for (auto* reference = products->FirstChildElement("speciesReference");
                         reference != nullptr;
                         reference = reference->NextSiblingElement("speciesReference")) {
                        const auto id = attribute(reference, "species");
                        const auto found = speciesIndices.find(id);
                        if (found == speciesIndices.end()) {
                            throw std::runtime_error(
                                "reaction references unknown species " + id);
                        }
                        int stoich = 1;
                        const auto stoichText = attribute(reference, "stoichiometry");
                        if (!stoichText.empty()) {
                            stoich = std::max(
                                1, static_cast<int>(std::stod(stoichText)));
                        }
                        for (int copy = 0; copy < stoich; ++copy) {
                            productIndices.push_back(found->second);
                        }
                    }
                }

                const auto* kineticLaw = reaction->FirstChildElement("kineticLaw");
                const auto* math = kineticLaw == nullptr
                    ? nullptr : kineticLaw->FirstChildElement("math");
                if (math == nullptr) {
                    throw std::runtime_error("reaction has no kinetic law");
                }
                const auto expression = stripReactantFactors(
                    mathExpression(math), reactantIds);
                std::ostringstream line;
                line << index << ' ' << indexList(reactantIndices) << ' '
                     << indexList(productIndices) << ' ' << expression;
                const auto id = attribute(reaction, "id");
                if (!id.empty()) {
                    line << " #" << id;
                }
                result.reactions.push_back(line.str());
            }
        }

        const auto* rules = model->FirstChildElement("listOfRules");
        if (rules != nullptr) {
            int groupIndex = 0;
            int functionIndex = 1;
            for (auto* rule = rules->FirstChildElement("assignmentRule");
                 rule != nullptr;
                 rule = rule->NextSiblingElement("assignmentRule")) {
                std::vector<std::string> identifiers;
                collectIdentifiers(rule->FirstChildElement("math"), identifiers);
                std::map<int, int> entries;
                for (const auto& identifier : identifiers) {
                    const auto found = speciesIndices.find(identifier);
                    if (found != speciesIndices.end()) {
                        ++entries[found->second];
                    }
                }
                if (entries.empty()) {
                    const auto variable = attribute(rule, "variable");
                    const auto expression = mathExpression(
                        rule->FirstChildElement("math"));
                    if (!variable.empty() && !expression.empty()) {
                        result.functions.emplace_back(variable, expression);
                        std::ostringstream line;
                        line << functionIndex++ << ' ' << variable << "() "
                             << expression;
                        result.rawFunctionLines.push_back(line.str());
                    }
                    continue;
                }
                ++groupIndex;
                const auto variable = attribute(rule, "variable", "group");
                std::ostringstream line;
                line << groupIndex << ' ' << sanitizeName(variable) << ' '
                     << weightedList(entries);
                result.rawGroupLines.push_back(line.str());
            }
        }

        result.success = true;
    } catch (const std::exception& error) {
        result.error = error.what();
    }
    return result;
}

}  // namespace bng::io
