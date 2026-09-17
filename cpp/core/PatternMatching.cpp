#include "core/PatternMatching.hpp"

#include "ast/SpeciesGraph.hpp"
#include "core/BNGcore.hpp"
#include "core/Ullmann.hpp"

namespace bng::core {
namespace {

bool isBondNode(const BNGcore::Node& node) {
    return node.get_type().get_type_name() == BNGcore::BOND_NODE_TYPE.get_type_name();
}

bool isComponentNode(const BNGcore::Node& node) {
    if (isBondNode(node)) return false;
    for (auto edge = node.edges_in_begin(); edge != node.edges_in_end(); ++edge) {
        if (!isBondNode(**edge)) return true;
    }
    return false;
}

bool isMoleculeNode(const BNGcore::Node& node) {
    return !isBondNode(node) && !isComponentNode(node);
}

bool nodeCompatible(const BNGcore::Node& patternNode, const BNGcore::Node& targetNode) {
    if (!(patternNode.get_type() == targetNode.get_type())) return false;
    return patternNode.get_state() == targetNode.get_state();
}

bool embeddingRespectsBioNetGenSemantics(const BNGcore::PatternGraph& pattern,
                                         const BNGcore::Map& map) {
    for (auto nodeIter = pattern.begin(); nodeIter != pattern.end(); ++nodeIter) {
        auto* target = map.mapf(*nodeIter);
        if (target == nullptr || !nodeCompatible(**nodeIter, *target)) return false;

        if (isMoleculeNode(**nodeIter)) {
            const auto& patternComp = (*nodeIter)->get_compartment();
            if (!patternComp.empty()) {
                const auto& targetComp = target->get_compartment();
                if (!targetComp.empty() && patternComp != targetComp) return false;
            }
        }

        if (isComponentNode(**nodeIter)) {
            std::vector<BNGcore::Node*> patternBonds;
            std::vector<BNGcore::Node*> targetBonds;
            for (auto edge = (*nodeIter)->edges_out_begin();
                 edge != (*nodeIter)->edges_out_end(); ++edge) {
                if (isBondNode(**edge)) patternBonds.push_back(*edge);
            }
            for (auto edge = target->edges_out_begin();
                 edge != target->edges_out_end(); ++edge) {
                if (isBondNode(**edge)) targetBonds.push_back(*edge);
            }
            if (patternBonds.size() == 1) {
                const auto patternBondState = patternBonds.front()->get_state().get_BNG2_string();
                if (patternBondState == "!?") {
                    // Any target bond cardinality is valid.
                } else if (patternBondState == "!+") {
                    if (targetBonds.empty()) return false;
                } else if (targetBonds.size() != patternBonds.size()) {
                    return false;
                }
            } else if (patternBonds.size() != targetBonds.size()) {
                return false;
            }
        }
    }
    return true;
}

} // namespace

bool patternMatchesSpecies(const BNGcore::PatternGraph& pattern,
                           const BNGcore::PatternGraph& target) {
    if (pattern.empty()) return true;
    if (target.empty()) return false;
    BNGcore::UllmannSGIso matcher(pattern, target);
    BNGcore::List<BNGcore::Map> maps;
    matcher.find_maps(maps);
    for (auto it = maps.begin(); it != maps.end(); ++it) {
        if (embeddingRespectsBioNetGenSemantics(pattern, *it)) return true;
    }
    return false;
}

bool patternMatchesSpecies(const ast::SpeciesGraph& patternSpecies,
                           const ast::SpeciesGraph& species) {
    return patternMatchesSpecies(patternSpecies.getGraph(), species.getGraph());
}

std::size_t countPatternMatches(const BNGcore::PatternGraph& pattern,
                                const BNGcore::PatternGraph& target) {
    if (pattern.empty() || target.empty()) return 0;
    BNGcore::UllmannSGIso matcher(pattern, target);
    BNGcore::List<BNGcore::Map> maps;
    matcher.find_maps(maps);
    std::size_t count = 0;
    for (auto it = maps.begin(); it != maps.end(); ++it) {
        if (embeddingRespectsBioNetGenSemantics(pattern, *it)) ++count;
    }
    return count;
}

std::size_t countPatternMatches(const ast::SpeciesGraph& patternSpecies,
                                const BNGcore::PatternGraph& target) {
    return countPatternMatches(patternSpecies.getGraph(), target);
}

std::size_t countPatternMatchesForScopedMolecule(
    const ast::SpeciesGraph& patternSpecies,
    const ast::SpeciesGraph& species,
    const BNGcore::Node* scopedMolecule) {
    return countPatternMatchesForScopedMolecule(
        patternSpecies, species.getGraph(), scopedMolecule);
}

std::size_t countPatternMatchesForScopedMolecule(
    const ast::SpeciesGraph& patternSpecies,
    const BNGcore::PatternGraph& target,
    const BNGcore::Node* scopedMolecule) {
    if (scopedMolecule == nullptr) return 0;
    const auto& pattern = patternSpecies.getGraph();
    if (pattern.empty() || target.empty()) return 0;

    BNGcore::Node* firstPatternMolecule = nullptr;
    for (auto it = pattern.begin(); it != pattern.end(); ++it) {
        if (isMoleculeNode(**it)) {
            firstPatternMolecule = *it;
            break;
        }
    }
    if (firstPatternMolecule == nullptr) return 0;

    BNGcore::UllmannSGIso matcher(pattern, target);
    BNGcore::List<BNGcore::Map> maps;
    matcher.find_maps(maps);
    std::size_t count = 0;
    for (auto it = maps.begin(); it != maps.end(); ++it) {
        if (!embeddingRespectsBioNetGenSemantics(pattern, *it)) continue;
        if (it->mapf(firstPatternMolecule) == scopedMolecule) ++count;
    }
    return count;
}

} // namespace bng::core
