#include "SbmlReader.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <map>
#include <limits>
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

bool looksLikeBnglPattern(const std::string& rawName) {
    const auto name = trim(rawName);
    if (name.empty() || name.back() != ')' || name.find('(') == std::string::npos) {
        return false;
    }

    int depth = 0;
    bool sawMolecule = false;
    for (const unsigned char c : name) {
        if (c == '(') {
            ++depth;
            sawMolecule = true;
        } else if (c == ')') {
            if (depth == 0) {
                return false;
            }
            --depth;
        } else if (std::isalnum(c) != 0 || c == '_' || c == '@' || c == ':' ||
                   c == '$' || c == '~' || c == '!' || c == ',' || c == '.' ||
                   c == '-') {
            continue;
        } else {
            return false;
        }
    }
    return sawMolecule && depth == 0;
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
    if (tag == "ci" || tag == "cn" || tag == "csymbol") {
        return elementText(element);
    }
    if (tag == "piecewise") {
        std::string result = "0";
        std::vector<std::pair<std::string, std::string>> pieces;
        for (auto* part = element->FirstChildElement(); part != nullptr;
             part = part->NextSiblingElement()) {
            if (std::string(part->Value()) == "otherwise") {
                result = mathExpression(part->FirstChildElement());
                continue;
            }
            if (std::string(part->Value()) != "piece") {
                continue;
            }
            const auto children = childElements(part);
            if (children.size() != 2) {
                throw std::runtime_error("malformed MathML piecewise expression");
            }
            const auto value = mathExpression(children[0]);
            const auto condition = mathExpression(children[1]);
            pieces.emplace_back(condition, value);
        }
        for (auto part = pieces.rbegin(); part != pieces.rend(); ++part) {
            result = "if(" + part->first + "," + part->second + "," + result + ")";
        }
        return result;
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
    const auto parenthesized = [](const std::string& value) {
        return "(" + value + ")";
    };
    if (op == "plus") {
        return args.size() > 1 ? parenthesized(join(args, "+")) : join(args, "+");
    }
    if (op == "times") {
        return join(args, "*");
    }
    if (op == "divide" && args.size() == 2) {
        return parenthesized(args[0] + "/" + args[1]);
    }
    if (op == "power" && args.size() == 2) {
        return parenthesized(args[0] + "^" + args[1]);
    }
    if (op == "minus") {
        return args.size() == 1 ? "-" + args[0]
                                : parenthesized(join(args, "-"));
    }
    const std::map<std::string, std::string> binaryOperators = {
        {"rem", "%"}, {"eq", "=="}, {"neq", "!="}, {"gt", ">"},
        {"geq", ">="}, {"lt", "<"}, {"leq", "<="}, {"and", "&&"},
        {"or", "||"}, {"xor", "^^"},
    };
    if (const auto found = binaryOperators.find(op);
        found != binaryOperators.end() && args.size() >= 2) {
        return parenthesized(join(args, found->second));
    }
    if (op == "not" && args.size() == 1) {
        return "!" + parenthesized(args.front());
    }
    if (args.size() == 1 &&
        (op == "abs" || op == "exp" || op == "ln" || op == "log" ||
         op == "sqrt" || op == "root" || op == "sin" || op == "cos" ||
         op == "tan" || op == "asin" || op == "acos" || op == "atan" ||
         op == "arcsin" || op == "arccos" || op == "arctan" ||
         op == "sinh" || op == "cosh" || op == "tanh" || op == "asinh" ||
         op == "acosh" || op == "atanh" || op == "arcsinh" ||
         op == "arccosh" || op == "arctanh" || op == "floor" ||
         op == "ceiling" || op == "factorial")) {
        const std::map<std::string, std::string> bnglNames = {
            {"root", "sqrt"}, {"arcsin", "asin"}, {"arccos", "acos"},
            {"arctan", "atan"}, {"arcsinh", "asinh"},
            {"arccosh", "acosh"}, {"arctanh", "atanh"},
        };
        const auto found = bnglNames.find(op);
        const auto& bnglName = found == bnglNames.end() ? op : found->second;
        return bnglName + "(" + args.front() + ")";
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

int stoichiometry(const TiXmlElement* reference) {
    const auto text = attribute(reference, "stoichiometry");
    if (text.empty()) {
        return 1;
    }
    std::size_t consumed = 0;
    const double value = std::stod(text, &consumed);
    if (consumed != text.size() || !std::isfinite(value) || value < 1.0 ||
        std::floor(value) != value ||
        value > static_cast<double>(std::numeric_limits<int>::max())) {
        throw std::runtime_error(
            "SBML stoichiometry must be a finite positive integer: " + text);
    }
    return static_cast<int>(value);
}

struct StructuredSpeciesName {
    std::vector<std::string> molecules;
    std::string state;
};

bool isMoleculeName(const std::string& name) {
    if (name.empty() || std::isalpha(static_cast<unsigned char>(name.front())) == 0) {
        return false;
    }
    return std::all_of(name.begin() + 1, name.end(), [](unsigned char c) {
        return std::isalnum(c) != 0;
    });
}

std::string lowerName(std::string name) {
    std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return name;
}

bool parseStructuredSpeciesName(
    const std::string& rawName, StructuredSpeciesName& parsed) {
    const auto name = trim(rawName);
    if (name.empty()) {
        return false;
    }

    if (name.front() == '(') {
        const auto close = name.find(')');
        if (close == std::string::npos || close <= 1 || close + 1 >= name.size() ||
            !isMoleculeName(name.substr(1, close - 1))) {
            return false;
        }
        const auto countText = name.substr(close + 1);
        if (!std::all_of(countText.begin(), countText.end(), [](unsigned char c) {
                return std::isdigit(c) != 0;
            })) {
            return false;
        }
        const auto count = std::stoul(countText);
        if (count < 2 || count > 64) {
            return false;
        }
        parsed.molecules.assign(count, name.substr(1, close - 1));
        return true;
    }

    const auto parts = splitTopLevel(name, '_');
    if (parts.empty()) {
        return false;
    }
    for (const auto& part : parts) {
        if (part.empty()) {
            return false;
        }
        const auto dash = part.find('-');
        if (dash != std::string::npos) {
            if (parts.size() != 1 || !parsed.state.empty() || dash == 0 ||
                dash + 1 >= part.size() ||
                !isMoleculeName(part.substr(0, dash)) ||
                !isMoleculeName(part.substr(dash + 1))) {
                return false;
            }
            parsed.molecules.push_back(part.substr(0, dash));
            parsed.state = "_" + sanitizeName(part.substr(dash + 1));
        } else {
            if (!isMoleculeName(part)) {
                return false;
            }
            parsed.molecules.push_back(part);
        }
    }
    return !parsed.molecules.empty();
}

bool isStructuredBng2Sbml(const TiXmlElement* model) {
    // Native atomization is deliberately limited to the BNG2 structured-SBML
    // naming convention.  Unlike the old implementation, admission is based
    // on a complete semantic grammar and reaction shape, not one fixture's
    // model/species IDs.  Inputs outside this grammar belong to the modern
    // Python Playground-derived Atomizer.
    const auto* speciesList = model->FirstChildElement("listOfSpecies");
    if (speciesList == nullptr) {
        return false;
    }
    std::map<std::string, std::string> idToName;
    std::set<std::string> names;
    std::map<std::string, StructuredSpeciesName> parsedNames;
    for (auto* species = speciesList->FirstChildElement("species"); species != nullptr;
         species = species->NextSiblingElement("species")) {
        const auto id = attribute(species, "id");
        const auto name = attribute(species, "name", id);
        StructuredSpeciesName parsed;
        if (id.empty() || !idToName.emplace(id, name).second ||
            !names.insert(name).second ||
            !parseStructuredSpeciesName(name, parsed)) {
            return false;
        }
        parsedNames.emplace(name, std::move(parsed));
    }

    const auto* rules = model->FirstChildElement("listOfRules");
    if (rules != nullptr) {
        for (auto* rule = rules->FirstChildElement(); rule != nullptr;
             rule = rule->NextSiblingElement()) {
            if (std::string(rule->Value()) != "assignmentRule") {
                return false;
            }
        }
    }

    const auto* reactions = model->FirstChildElement("listOfReactions");
    if (reactions == nullptr) {
        return false;
    }
    for (auto* reaction = reactions->FirstChildElement("reaction"); reaction != nullptr;
         reaction = reaction->NextSiblingElement("reaction")) {
        if (parseBool(attribute(reaction, "reversible")) ||
            parseBool(attribute(reaction, "fast"))) {
            return false;
        }
        const auto collect = [&](const char* listName, std::vector<std::string>& out) {
            const auto* list = reaction->FirstChildElement(listName);
            if (list == nullptr) {
                return;
            }
            for (auto* reference = list->FirstChildElement("speciesReference");
                 reference != nullptr;
                 reference = reference->NextSiblingElement("speciesReference")) {
                const auto found = idToName.find(attribute(reference, "species"));
                if (found == idToName.end()) {
                    throw std::runtime_error("structured SBML references unknown species");
                }
                for (int copy = 0; copy < stoichiometry(reference); ++copy) {
                    out.push_back(found->second);
                }
            }
        };
        std::vector<std::string> reactants;
        std::vector<std::string> products;
        collect("listOfReactants", reactants);
        collect("listOfProducts", products);
        const auto* kineticLaw = reaction->FirstChildElement("kineticLaw");
        const auto* math = kineticLaw == nullptr
            ? nullptr : kineticLaw->FirstChildElement("math");
        if (math == nullptr) {
            return false;
        }
        try {
            (void)mathExpression(math);
        } catch (const std::exception&) {
            return false;
        }
    }
    return !parsedNames.empty();
}

struct StructuredMoleculeType {
    std::set<std::string> sites;
    std::set<std::string> states;
};

std::string renderStructuredMolecule(
    const std::string& name, const StructuredMoleculeType& type,
    const std::string& state, const std::map<std::string, int>& bonds) {
    std::ostringstream result;
    result << name << '(';
    bool first = true;
    if (!type.states.empty()) {
        result << "_p~" << (state.empty() ? "0" : state);
        first = false;
    }
    for (const auto& site : type.sites) {
        if (!first) {
            result << ',';
        }
        first = false;
        result << site;
        const auto found = bonds.find(site);
        if (found != bonds.end()) {
            result << '!' << found->second;
        }
    }
    result << ')';
    return result.str();
}

std::string lowerStructuredSpecies(
    const StructuredSpeciesName& parsed,
    const std::map<std::string, StructuredMoleculeType>& moleculeTypes) {
    std::vector<std::string> molecules;
    for (std::size_t i = 0; i < parsed.molecules.size(); ++i) {
        const auto& moleculeName = parsed.molecules[i];
        const auto type = moleculeTypes.find(moleculeName);
        if (type == moleculeTypes.end()) {
            throw std::runtime_error("structured SBML molecule type inference failed");
        }
        std::map<std::string, int> bonds;
        if (parsed.molecules.size() > 1) {
            if (i > 0) {
                bonds[lowerName(parsed.molecules[i - 1])] = static_cast<int>(i);
            }
            if (i + 1 < parsed.molecules.size()) {
                bonds[lowerName(parsed.molecules[i + 1])] = static_cast<int>(i + 1);
            }
        }
        const auto state = parsed.molecules.size() == 1 && !parsed.state.empty()
            ? parsed.state : std::string{};
        molecules.push_back(renderStructuredMolecule(
            moleculeName, type->second, state, bonds));
    }
    return join(molecules, ".");
}

void lowerStructuredBng2Sbml(
    const TiXmlElement* model,
    NetReader::ParseResult& result,
    const std::unordered_map<std::string, int>& speciesIndices) {
    const auto* speciesList = model->FirstChildElement("listOfSpecies");
    std::map<std::string, std::string> idToName;
    std::map<std::string, StructuredSpeciesName> parsedNames;
    std::map<std::string, StructuredMoleculeType> moleculeTypes;
    std::vector<std::string> ids;
    for (auto* species = speciesList->FirstChildElement("species"); species != nullptr;
         species = species->NextSiblingElement("species")) {
        const auto id = attribute(species, "id");
        const auto name = attribute(species, "name", id);
        StructuredSpeciesName parsed;
        if (!parseStructuredSpeciesName(name, parsed)) {
            throw std::runtime_error(
                "SBML atomize=true could not infer molecule boundaries from species name " +
                name);
        }
        idToName[id] = name;
        parsedNames[name] = parsed;
        ids.push_back(id);
        for (const auto& molecule : parsed.molecules) {
            moleculeTypes[molecule];
        }
        if (!parsed.state.empty()) {
            moleculeTypes[parsed.molecules.front()].states.insert("0");
            moleculeTypes[parsed.molecules.front()].states.insert(parsed.state);
        }
    }

    for (const auto& [name, parsed] : parsedNames) {
        for (std::size_t i = 1; i < parsed.molecules.size(); ++i) {
            const auto& left = parsed.molecules[i - 1];
            const auto& right = parsed.molecules[i];
            moleculeTypes[left].sites.insert(lowerName(right));
            moleculeTypes[right].sites.insert(lowerName(left));
        }
    }

    std::vector<std::string> loweredSpecies;
    loweredSpecies.reserve(ids.size());
    std::map<std::string, std::string> groupNames;
    for (auto* species = speciesList->FirstChildElement("species"); species != nullptr;
         species = species->NextSiblingElement("species")) {
        const auto id = attribute(species, "id");
        const auto name = idToName.at(id);
        std::string pattern;
        const auto compartment = attribute(species, "compartment");
        if (!compartment.empty()) {
            pattern = "@" + compartment + "::";
        }
        if (parseBool(attribute(species, "constant")) ||
            parseBool(attribute(species, "boundaryCondition"))) {
            pattern += '$';
        }
        pattern += lowerStructuredSpecies(parsedNames.at(name), moleculeTypes);
        auto amount = attribute(species, "initialAmount");
        if (amount.empty()) {
            amount = attribute(species, "initialConcentration", "0");
        }
        loweredSpecies.emplace_back(pattern + "\t" + amount);
        auto groupName = sanitizeName(name);
        if (!compartment.empty()) {
            groupName += "_" + sanitizeName(compartment);
        }
        if (!groupNames.emplace(id, groupName).second) {
            throw std::runtime_error("duplicate structured SBML species id " + id);
        }
    }
    result.species.clear();
    for (const auto& entry : loweredSpecies) {
        const auto tab = entry.find('\t');
        result.species.emplace_back(entry.substr(0, tab), entry.substr(tab + 1));
    }

    result.reactions.clear();
    result.rawFunctionLines.erase(
        std::remove_if(result.rawFunctionLines.begin(), result.rawFunctionLines.end(),
                       [](const std::string& line) {
                           return line.find("functionRate") != std::string::npos;
                       }),
        result.rawFunctionLines.end());
    int reactionIndex = 0;
    int generatedFunctionIndex = 1;
    for (auto* reaction = model->FirstChildElement("listOfReactions")
             ->FirstChildElement("reaction");
         reaction != nullptr; reaction = reaction->NextSiblingElement("reaction")) {
        ++reactionIndex;
        std::vector<int> reactantIndices;
        std::vector<std::string> reactantIds;
        std::vector<int> productIndices;
        const auto collect = [&](const char* listName, std::vector<int>& indices,
                                 std::vector<std::string>* names) {
            const auto* list = reaction->FirstChildElement(listName);
            if (list == nullptr) {
                return;
            }
            for (auto* reference = list->FirstChildElement("speciesReference");
                 reference != nullptr;
                 reference = reference->NextSiblingElement("speciesReference")) {
                const auto id = attribute(reference, "species");
                const auto found = speciesIndices.find(id);
                if (found == speciesIndices.end()) {
                    throw std::runtime_error("structured SBML references unknown species " + id);
                }
                const auto copies = stoichiometry(reference);
                for (int copy = 0; copy < copies; ++copy) {
                    indices.push_back(found->second);
                    if (names != nullptr) {
                        names->push_back(id);
                    }
                }
            }
        };
        collect("listOfReactants", reactantIndices, &reactantIds);
        collect("listOfProducts", productIndices, nullptr);
        const auto* kineticLaw = reaction->FirstChildElement("kineticLaw");
        const auto* math = kineticLaw == nullptr
            ? nullptr : kineticLaw->FirstChildElement("math");
        if (math == nullptr) {
            throw std::runtime_error("reaction has no kinetic law");
        }
        auto rate = stripReactantFactors(mathExpression(math), reactantIds);
        std::map<int, int> counts;
        for (const auto index : reactantIndices) {
            ++counts[index];
        }
        if (counts.size() < reactantIndices.size()) {
            if (reactantIndices.size() != 2 || counts.size() != 1 || rate.empty()) {
                throw std::runtime_error(
                    "SBML atomize=true supports only binary duplicate-reactant symmetry factors");
            }
            const auto functionName = "functionRate" + std::to_string(generatedFunctionIndex++);
            result.functions.emplace_back(functionName, rate + "*2");
            result.rawFunctionLines.push_back(
                std::to_string(generatedFunctionIndex - 1) + " " + functionName + "() " + rate + "*2");
            rate = "0.5*" + functionName;
        }
        std::ostringstream line;
        line << reactionIndex << ' ' << indexList(reactantIndices) << ' '
             << indexList(productIndices) << ' ' << rate;
        const auto id = attribute(reaction, "id");
        if (!id.empty()) {
            line << " #" << id;
        }
        result.reactions.push_back(line.str());
    }

    result.rawGroupLines.clear();
    int groupIndex = 0;
    for (auto* species = speciesList->FirstChildElement("species"); species != nullptr;
         species = species->NextSiblingElement("species")) {
        ++groupIndex;
        const auto id = attribute(species, "id");
        result.rawGroupLines.push_back(
            std::to_string(groupIndex) + " " + groupNames.at(id) + " " +
            std::to_string(speciesIndices.at(id)));
    }
}

}  // namespace

NetReader::ParseResult SbmlReader::parse(
    const std::filesystem::path& filepath, bool atomize) {
    NetReader::ParseResult result;

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
                const auto rawName = attribute(species, "name", id);
                auto standardized = looksLikeBnglPattern(rawName)
                    ? trim(rawName) : sanitizeName(rawName);
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
                pattern += looksLikeBnglPattern(rawName)
                    ? standardized : standardized + "()";
                speciesIndices[id] = index;
                std::string amount = attribute(species, "initialAmount");
                if (amount.empty()) {
                    amount = attribute(species, "initialConcentration", "0");
                }
                result.species.emplace_back(pattern, amount);
            }
        }
        // A valid SBML model may contain only compartments, parameters, rules,
        // or annotations.  Keep the native readback result successful for this
        // zero-species case; callers can still distinguish it by the returned
        // empty species/reaction counts.

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
                        const int stoich = stoichiometry(reference);
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
                        const int stoich = stoichiometry(reference);
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
                bool totalRate = false;
                const auto* annotation = reaction->FirstChildElement("annotation");
                if (annotation != nullptr) {
                    for (auto* marker = annotation->FirstChildElement(); marker != nullptr;
                         marker = marker->NextSiblingElement()) {
                        if (std::string(marker->Value()).find("totalRate") != std::string::npos) {
                            totalRate = true;
                            break;
                        }
                    }
                }
                const auto expression = totalRate
                    ? mathExpression(math)
                    : stripReactantFactors(mathExpression(math), reactantIds);
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

        if (atomize) {
            if (!isStructuredBng2Sbml(model)) {
                throw std::runtime_error(
                    "SBML atomize=true could not infer the supported BNG2 structured "
                    "dialect; use the Python Atomizer for arbitrary SBML");
            }
            lowerStructuredBng2Sbml(model, result, speciesIndices);
        }

        result.success = true;
    } catch (const std::exception& error) {
        result.error = error.what();
    }
    return result;
}

}  // namespace bng::io
