#include "engine/NetworkGenerator.hpp"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <iostream>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <stdexcept>

#include "compile/LegacyAstLowering.hpp"
#include "compile/PatternLowering.hpp"
#include "engine/NetworkRulePlan.hpp"
#include "io/NetWriter.hpp"

namespace bng::engine {

namespace {

std::optional<std::size_t> parseMaxIter(const compile::SimulationProtocol& protocol) {
    for (const auto& action : protocol.actions) {
        if (action.name != "generate_network") {
            continue;
        }
        const auto found = action.arguments.find("max_iter");
        if (found == action.arguments.end()) {
            continue;
        }
        return static_cast<std::size_t>(std::stoul(found->second));
    }
    return std::nullopt;
}

std::map<std::string, std::size_t> parseMaxStoich(const compile::SimulationProtocol& protocol) {
    for (const auto& action : protocol.actions) {
        if (action.name != "generate_network") {
            continue;
        }
        const auto found = action.arguments.find("max_stoich");
        if (found == action.arguments.end()) {
            continue;
        }

        std::map<std::string, std::size_t> limits;
        std::string text = found->second;
        text.erase(std::remove_if(text.begin(), text.end(), [](unsigned char c) {
            return std::isspace(c) != 0;
        }), text.end());
        if (text.size() >= 2 && text.front() == '{' && text.back() == '}') {
            text = text.substr(1, text.size() - 2);
        }

        std::size_t start = 0;
        while (start < text.size()) {
            const auto comma = text.find(',', start);
            const auto entry = text.substr(start, comma == std::string::npos ? std::string::npos : comma - start);
            const auto arrow = entry.find("=>");
            if (arrow != std::string::npos) {
                std::string key = entry.substr(0, arrow);
                // Strip surrounding quotes from key (e.g., 'R' -> R, "R" -> R)
                if (key.size() >= 2 && ((key.front() == '\'' && key.back() == '\'') ||
                                         (key.front() == '"' && key.back() == '"'))) {
                    key = key.substr(1, key.size() - 2);
                }
                limits.emplace(key, static_cast<std::size_t>(std::stoull(entry.substr(arrow + 2))));
            }
            if (comma == std::string::npos) {
                break;
            }
            start = comma + 1;
        }
        return limits;
    }
    return {};
}

bool parseBooleanLike(std::string text) {
    text.erase(std::remove_if(text.begin(), text.end(), [](unsigned char c) {
        return std::isspace(c) != 0;
    }), text.end());
    if (text.size() >= 2 && ((text.front() == '"' && text.back() == '"') || (text.front() == '\'' && text.back() == '\''))) {
        text = text.substr(1, text.size() - 2);
    }
    const auto caseInsensitiveEqual = [](const std::string& value, std::string_view expected) {
        if (value.size() != expected.size()) return false;
        return std::equal(value.begin(), value.end(), expected.begin(), [](char lhs, char rhs) {
            return std::tolower(static_cast<unsigned char>(lhs)) ==
                   std::tolower(static_cast<unsigned char>(rhs));
        });
    };
    return caseInsensitiveEqual(text, "1") ||
           caseInsensitiveEqual(text, "true") ||
           caseInsensitiveEqual(text, "yes") ||
           caseInsensitiveEqual(text, "on");
}

std::optional<std::size_t> parseMaxAgg(const compile::SimulationProtocol& protocol) {
    for (const auto& action : protocol.actions) {
        if (action.name != "generate_network") {
            continue;
        }
        const auto found = action.arguments.find("max_agg");
        if (found == action.arguments.end()) {
            continue;
        }
        return static_cast<std::size_t>(std::stoul(found->second));
    }
    return std::nullopt;
}

bool parsePrintIter(const compile::SimulationProtocol& protocol) {
    const char* envFlag = std::getenv("BNG_CPP_PROGRESS");
    if (envFlag != nullptr && *envFlag != '\0') {
        return parseBooleanLike(envFlag);
    }

    for (const auto& action : protocol.actions) {
        if (action.name != "generate_network") {
            continue;
        }
        const auto found = action.arguments.find("print_iter");
        if (found != action.arguments.end()) {
            return parseBooleanLike(found->second);
        }
    }
    return false;
}

bool parseOverwrite(const compile::SimulationProtocol& protocol) {
    for (const auto& action : protocol.actions) {
        if (action.name != "generate_network") {
            continue;
        }
        const auto found = action.arguments.find("overwrite");
        if (found == action.arguments.end()) {
            continue;
        }
        return parseBooleanLike(found->second);
    }
    return true;  // default: always regenerate (overwrite=1)
}

bool parseCheckIso(const compile::SimulationProtocol& protocol) {
    for (const auto& action : protocol.actions) {
        if (action.name != "generate_network") {
            continue;
        }
        const auto found = action.arguments.find("check_iso");
        if (found == action.arguments.end()) {
            continue;
        }
        // Default is true (enabled). Only disable if explicitly set to 0/false.
        return parseBooleanLike(found->second);
    }
    return true;  // default: isomorphism checking enabled
}

bool parsePrintRules(const compile::SimulationProtocol& protocol) {
    const char* envFlag = std::getenv("BNG_CPP_PROGRESS_RULES");
    if (envFlag != nullptr && *envFlag != '\0') {
        return parseBooleanLike(envFlag);
    }

    for (const auto& action : protocol.actions) {
        if (action.name != "generate_network") {
            continue;
        }
        const auto found = action.arguments.find("print_rule_progress");
        if (found != action.arguments.end()) {
            return parseBooleanLike(found->second);
        }
    }
    return false;
}

bool isBondNode(const BNGcore::Node& node) {
    return node.get_type().get_type_name() == BNGcore::BOND_NODE_TYPE.get_type_name();
}

bool isComponentNode(const BNGcore::Node& node) {
    if (isBondNode(node)) {
        return false;
    }
    for (auto edge = node.edges_in_begin(); edge != node.edges_in_end(); ++edge) {
        if (!isBondNode(**edge)) {
            return true;
        }
    }
    return false;
}

bool isMoleculeNode(const BNGcore::Node& node) {
    return !isBondNode(node) && !isComponentNode(node);
}

std::map<std::string, std::size_t> countMolecules(const ast::SpeciesGraph& graph) {
    std::map<std::string, std::size_t> counts;
    for (auto nodeIter = graph.getGraph().begin(); nodeIter != graph.getGraph().end(); ++nodeIter) {
        if (isMoleculeNode(**nodeIter)) {
            ++counts[(*nodeIter)->get_type().get_type_name()];
        }
    }
    return counts;
}

bool withinStoichLimits(const ast::SpeciesGraph& graph, const std::map<std::string, std::size_t>& limits) {
    if (limits.empty()) {
        return true;
    }
    const auto counts = countMolecules(graph);
    for (const auto& [name, count] : counts) {
        const auto found = limits.find(name);
        if (found != limits.end() && count > found->second) {
            return false;
        }
    }
    return true;
}

bool withinAggLimit(const ast::SpeciesGraph& graph, std::size_t maxAgg) {
    // Count total number of molecules in the species (regardless of type)
    std::size_t totalMolecules = 0;
    for (auto nodeIter = graph.getGraph().begin(); nodeIter != graph.getGraph().end(); ++nodeIter) {
        if (isMoleculeNode(**nodeIter)) {
            ++totalMolecules;
        }
    }
    return totalMolecules <= maxAgg;
}

} // namespace

NetworkGenerator::NetworkGenerator(ast::Model& model)
    : sourceModel_(&model), document_(model) {}

NetworkGenerator::NetworkGenerator(const compile::Document& document)
    : document_(document) {}

GeneratedNetwork NetworkGenerator::generateNative(std::size_t maxIter) {
    const auto& compiled = document_.model();
    if (!document_.valid()) {
        throw std::runtime_error("cannot generate a network from an invalid compiled BioNetGen model");
    }

    const auto maxStoich = parseMaxStoich(document_.protocol());
    const auto maxAgg = parseMaxAgg(document_.protocol());
    const bool logProgress = parsePrintIter(document_.protocol());
    const bool logRules = parsePrintRules(document_.protocol());
    const bool checkIso = parseCheckIso(document_.protocol());

    // Set compartment maps from the compiled semantic declarations.
    {
        std::unordered_map<std::string, int> compDims;
        std::unordered_map<std::string, std::string> compParents;
        for (const auto& comp : compiled.compartments()) {
            compDims[comp.name] = comp.dimension;
            if (!comp.parentName.empty()) compParents[comp.name] = comp.parentName;
        }
        ast::setCompartmentDimensions(compDims);
        ast::setCompartmentParents(compParents);
    }

    GeneratedNetwork network;
    // Runtime graph types belong to this backend lowering context, not the
    // parser AST. The same context is shared by seeds, filters and all rule
    // plans so graph type identity is stable throughout one generation, and
    // the generated network owns it for as long as its graphs are live.
    network.loweringContext =
        std::make_shared<compile::BNGcoreLoweringContext>(compiled);
    auto& loweringContext = *network.loweringContext;

    auto rulePlans = lowerNetworkRules(compiled, loweringContext);
    for (auto& plan : rulePlans) plan.clearPatternMatchCache();

    network.species.setCheckIso(checkIso);
    for (const auto& seed : compiled.seeds()) {
        if (!seed.evaluatedAmount.has_value()) {
            throw std::runtime_error(
                "network seed amount is not compile-time evaluable for pattern '" +
                seed.sourcePattern + "'");
        }

        auto seedGraph = compile::lowerPatternToSpeciesGraph(seed.pattern, loweringContext);
        const auto& seedComp = seed.compartment;
        if (!seedComp.empty()) {
            for (auto it = seedGraph.getGraph().begin(); it != seedGraph.getGraph().end(); ++it) {
                if ((*it)->in_degree() == 0 && (*it)->get_compartment().empty()) {
                    (*it)->set_compartment(seedComp);
                }
            }
        }
        network.species.add(ast::Species(
            std::move(seedGraph), *seed.evaluatedAmount, seed.constant, seedComp));
    }

    if (logProgress) {
        std::cerr << "[generate_network] start species=" << network.species.size()
                  << " reactions=" << network.reactions.size()
                  << " max_iter=" << maxIter << '\n';
    }

    for (std::size_t iter = 0; iter < maxIter; ++iter) {
        const std::size_t previousSpecies = network.species.size();
        const std::size_t previousReactions = network.reactions.size();
        const std::size_t speciesAtIterStart = network.species.size();

        for (auto& plan : rulePlans) {
            const std::size_t beforeSpecies = network.species.size();
            const std::size_t beforeReactions = network.reactions.size();
            const auto created = plan.expand(
                network.species, network.reactions, iter,
                [&](const ast::SpeciesGraph& graph) {
                    if (!withinStoichLimits(graph, maxStoich)) return false;
                    if (maxAgg.has_value() && !withinAggLimit(graph, *maxAgg)) return false;
                    return true;
                },
                speciesAtIterStart);

            const bool debugRules = std::getenv("BNG_DEBUG_RULES") != nullptr;
            if (debugRules) {
                std::cerr << "[generate_network] iter=" << (iter + 1)
                          << " rule=" << plan.name()
                          << " created=" << created
                          << " species=" << network.species.size()
                          << " reactions=" << network.reactions.size()
                          << " d_species=" << (network.species.size() - beforeSpecies)
                          << " d_rxns=" << (network.reactions.size() - beforeReactions) << '\n';
            } else if (logRules &&
                       (created > 0 || network.species.size() != beforeSpecies ||
                        network.reactions.size() != beforeReactions)) {
                std::cerr << "[generate_network] iter=" << (iter + 1)
                          << " rule=" << plan.name()
                          << " created=" << created
                          << " d_species=" << (network.species.size() - beforeSpecies)
                          << " d_rxns=" << (network.reactions.size() - beforeReactions) << '\n';
            }
        }

        for (std::size_t i = 0; i < speciesAtIterStart; ++i)
            network.species.get(i).setRulesApplied(true);

        if (logProgress) {
            std::cerr << "[generate_network] iter=" << (iter + 1)
                      << " species=" << network.species.size()
                      << " reactions=" << network.reactions.size()
                      << " d_species=" << (network.species.size() - previousSpecies)
                      << " d_rxns=" << (network.reactions.size() - previousReactions) << '\n';
        }

        if (network.species.size() == previousSpecies &&
            network.reactions.size() == previousReactions) {
            if (logProgress)
                std::cerr << "[generate_network] converged at iter=" << (iter + 1) << '\n';
            break;
        }
    }

    return network;
}

GeneratedNetwork NetworkGenerator::generate(const std::filesystem::path& sourcePath) {
    auto network = generateNative(parseMaxIter(document_.protocol()).value_or(100));
    if (!sourcePath.empty()) {
        if (sourceModel_ == nullptr) {
            throw std::runtime_error(
                "source-preserving .net output currently requires the AST compatibility constructor");
        }
        const auto outputPath = sourcePath.parent_path() / (sourcePath.stem().string() + ".net");
        io::NetWriter::write(outputPath, *sourceModel_, network);
    }
    return network;
}

} // namespace bng::engine
