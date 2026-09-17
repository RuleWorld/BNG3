#include "RegulatoryGraphWriter.hpp"

#include <algorithm>
#include <cmath>
#include <map>
#include <sstream>

#include "compile/Document.hpp"
#include "engine/ObservableProjection.hpp"


namespace bng::io {

RegulatoryGraphWriter::RegulatoryGraph RegulatoryGraphWriter::build(
    const compile::CompiledModel& model, const engine::GeneratedNetwork& network) {

    RegulatoryGraph graph;

    // Collect unique rule names from reactions
    std::map<std::string, std::size_t> ruleNameToIndex;
    for (const auto& rxn : network.reactions.all()) {
        const std::string& ruleName = rxn.getOriginRuleName();
        std::string name = ruleName.empty() ? rxn.getLabel() : ruleName;
        if (ruleNameToIndex.find(name) == ruleNameToIndex.end()) {
            ruleNameToIndex[name] = graph.ruleNames.size();
            graph.ruleNames.push_back(name);
        }
    }

    // Project observables from the already-resolved semantic model. Patterns
    // are lowered once and shared across every species rather than reparsed.
    engine::ObservableProjection projection(model);
    for (std::size_t o = 0; o < projection.size(); ++o)
        graph.observableNames.push_back(projection.name(o));

    const std::size_t nObs = projection.size();
    const std::size_t nSpecies = network.species.size();
    std::vector<std::map<std::size_t, int>> observableWeights(nObs);
    for (std::size_t s = 0; s < nSpecies; ++s) {
        const auto weights = projection.weights(network.species.get(s).getSpeciesGraph().getGraph());
        for (std::size_t o = 0; o < weights.size(); ++o) {
            if (weights[o] != 0) observableWeights[o][s] = weights[o];
        }
    }

    // For each reaction, compute stoichiometry: how each species changes
    // Then determine how each rule affects each observable
    // ruleObsEffect[ruleIndex][obsIndex] = net effect sign
    std::map<std::size_t, std::map<std::size_t, int>> ruleObsEffect;

    for (const auto& rxn : network.reactions.all()) {
        const std::string& ruleName = rxn.getOriginRuleName();
        std::string name = ruleName.empty() ? rxn.getLabel() : ruleName;
        std::size_t ruleIdx = ruleNameToIndex[name];

        // Compute per-species stoichiometry for this reaction
        std::map<std::size_t, int> speciesDelta;
        for (const auto idx : rxn.getReactants()) {
            speciesDelta[idx] -= 1;
        }
        for (const auto idx : rxn.getProducts()) {
            speciesDelta[idx] += 1;
        }

        // For each observable, compute the net effect of this reaction
        for (std::size_t o = 0; o < nObs; ++o) {
            int netEffect = 0;
            for (const auto& [specIdx, delta] : speciesDelta) {
                if (delta != 0 && observableWeights[o].count(specIdx)) {
                    netEffect += delta * observableWeights[o][specIdx];
                }
            }
            if (netEffect != 0) {
                ruleObsEffect[ruleIdx][o] += netEffect;
            }
        }
    }

    // Convert to edges
    for (const auto& [ruleIdx, obsMap] : ruleObsEffect) {
        for (const auto& [obsIdx, effect] : obsMap) {
            if (effect != 0) {
                RegulatoryGraph::Edge edge;
                edge.ruleIndex = ruleIdx;
                edge.observableIndex = obsIdx;
                edge.effect = (effect > 0) ? 1 : -1;
                graph.edges.push_back(edge);
            }
        }
    }

    return graph;
}

RegulatoryGraphWriter::RegulatoryGraph RegulatoryGraphWriter::build(
    const ast::Model& model, const engine::GeneratedNetwork& network) {
    compile::Document document(model);
    if (!document.valid())
        throw std::runtime_error("cannot build regulatory graph from invalid compiled model");
    return build(document.model(), network);
}

std::string RegulatoryGraphWriter::toGML(const RegulatoryGraph& graph) {
    std::ostringstream gml;

    gml << "graph [\n";
    gml << "  directed 1\n";

    int nodeId = 0;

    // Rule nodes
    std::map<std::size_t, int> ruleNodeIds;
    for (std::size_t i = 0; i < graph.ruleNames.size(); ++i) {
        gml << "  node [\n";
        gml << "    id " << nodeId << "\n";
        gml << "    label \"" << graph.ruleNames[i] << "\"\n";
        gml << "    isGroup 0\n";
        gml << "    type \"rule\"\n";
        gml << "    graphics [\n";
        gml << "      type \"roundrectangle\"\n";
        gml << "      fill \"#FFCC00\"\n";
        gml << "    ]\n";
        gml << "  ]\n";
        ruleNodeIds[i] = nodeId++;
    }

    // Observable nodes
    std::map<std::size_t, int> obsNodeIds;
    for (std::size_t i = 0; i < graph.observableNames.size(); ++i) {
        gml << "  node [\n";
        gml << "    id " << nodeId << "\n";
        gml << "    label \"" << graph.observableNames[i] << "\"\n";
        gml << "    isGroup 0\n";
        gml << "    type \"observable\"\n";
        gml << "    graphics [\n";
        gml << "      type \"ellipse\"\n";
        gml << "      fill \"#99CCFF\"\n";
        gml << "    ]\n";
        gml << "  ]\n";
        obsNodeIds[i] = nodeId++;
    }

    // Edges
    for (const auto& edge : graph.edges) {
        gml << "  edge [\n";
        gml << "    source " << ruleNodeIds[edge.ruleIndex] << "\n";
        gml << "    target " << obsNodeIds[edge.observableIndex] << "\n";
        if (edge.effect > 0) {
            gml << "    label \"activating\"\n";
            gml << "    graphics [\n";
            gml << "      fill \"#00CC00\"\n";
            gml << "      targetArrow \"standard\"\n";
            gml << "    ]\n";
        } else {
            gml << "    label \"inhibiting\"\n";
            gml << "    graphics [\n";
            gml << "      fill \"#CC0000\"\n";
            gml << "      targetArrow \"t_shape\"\n";
            gml << "    ]\n";
        }
        gml << "  ]\n";
    }

    gml << "]\n";
    return gml.str();
}

} // namespace bng::io
