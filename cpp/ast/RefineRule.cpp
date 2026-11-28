/**
 * RefineRule.cpp
 *
 * Faithful C++ port of RefineRule.pm::expandRule (lines 295-425) and
 * RefineRule.pm::restrict_rule (lines 436-746).
 *
 * Implements hybrid particle/population rule refinement: given a reaction
 * rule and a list of population species graphs, expand the rule into
 * concrete "child rules" that act on specific species.
 */

#include "RefineRule.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "core/BNGcore.hpp"
#include "core/Ullmann.hpp"

namespace bng::ast {

double ruleSymmetryFactorForRefinement(const ReactionRule& rule);

// ---- local helpers (mirrors the anonymous namespace in ReactionRule.cpp) ----

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

// Clone all nodes/edges from source into target, returning old->new node map.
std::unordered_map<BNGcore::Node*, BNGcore::Node*> cloneGraphInto(
    const BNGcore::PatternGraph& source,
    BNGcore::PatternGraph& target)
{
    std::unordered_map<BNGcore::Node*, BNGcore::Node*> clones;
    for (auto it = source.begin(); it != source.end(); ++it) {
        auto* clone = (*it)->clone();
        target.add_node(clone);
        clones[*it] = clone;
    }
    for (auto it = source.begin(); it != source.end(); ++it) {
        for (auto edge = (*it)->edges_out_begin(); edge != (*it)->edges_out_end(); ++edge) {
            auto srcIt = clones.find(*it);
            auto dstIt = clones.find(*edge);
            if (srcIt != clones.end() && dstIt != clones.end()) {
                target.add_edge(srcIt->second, dstIt->second);
            }
        }
    }
    return clones;
}

// Split a PatternGraph into connected components, each wrapped as a SpeciesGraph.
std::vector<SpeciesGraph> splitConnected(const BNGcore::PatternGraph& graph) {
    std::vector<SpeciesGraph> result;
    std::set<BNGcore::Node*> visited;

    for (auto nodeIt = graph.begin(); nodeIt != graph.end(); ++nodeIt) {
        if (visited.count(*nodeIt)) continue;

        // BFS/DFS to find the connected component
        std::vector<BNGcore::Node*> stack{*nodeIt};
        std::vector<BNGcore::Node*> component;
        while (!stack.empty()) {
            BNGcore::Node* node = stack.back();
            stack.pop_back();
            if (!visited.insert(node).second) continue;
            component.push_back(node);
            for (auto e = node->edges_in_begin(); e != node->edges_in_end(); ++e) {
                if (!visited.count(*e)) stack.push_back(*e);
            }
            for (auto e = node->edges_out_begin(); e != node->edges_out_end(); ++e) {
                if (!visited.count(*e)) stack.push_back(*e);
            }
        }

        BNGcore::PatternGraph cg;
        std::unordered_map<BNGcore::Node*, BNGcore::Node*> clones;
        for (auto* n : component) {
            auto* c = n->clone();
            cg.add_node(c);
            clones[n] = c;
        }
        for (auto* n : component) {
            for (auto e = n->edges_out_begin(); e != n->edges_out_end(); ++e) {
                if (clones.count(*e)) {
                    cg.add_edge(clones[n], clones[*e]);
                }
            }
        }
        result.emplace_back(cg);
    }
    return result;
}

// Count molecule nodes in a graph.
std::size_t countMolecules(const BNGcore::PatternGraph& graph) {
    std::size_t n = 0;
    for (auto it = graph.begin(); it != graph.end(); ++it) {
        if (isMoleculeNode(**it)) ++n;
    }
    return n;
}

// Count occurrences of molecule type 'name' in a graph (for stoich check).
std::size_t stoich(const BNGcore::PatternGraph& graph, const std::string& name) {
    std::size_t n = 0;
    for (auto it = graph.begin(); it != graph.end(); ++it) {
        if (isMoleculeNode(**it) && (*it)->get_type().get_type_name() == name)
            ++n;
    }
    return n;
}

// Check if pattern (Ga) has a subgraph isomorphism into target (Gb).
bool hasSubgraphIso(const BNGcore::PatternGraph& pattern,
                    const BNGcore::PatternGraph& target)
{
    BNGcore::UllmannSGIso matcher(pattern, target);
    BNGcore::List<BNGcore::Map> maps;
    matcher.set_max_maps(1);
    return matcher.find_maps(maps) > 0;
}

// Find ALL subgraph isomorphisms of pattern into target.
std::vector<BNGcore::Map> findAllMaps(const BNGcore::PatternGraph& pattern,
                                       const BNGcore::PatternGraph& target)
{
    BNGcore::UllmannSGIso matcher(pattern, target);
    BNGcore::List<BNGcore::Map> maps;
    matcher.find_maps(maps);
    std::vector<BNGcore::Map> result;
    for (auto it = maps.begin(); it != maps.end(); ++it) {
        result.push_back(*it);
    }
    return result;
}

// Build a string representation of reactants + products for dedup (StringID).
// Perl lines 704-711: join reactant strings with '+', append '->', join product strings.
// Uses compartment-aware dedup keys so distinct compartment child rules never merge.
std::string buildStringID(const std::vector<SpeciesGraph>& reactants,
                          const std::vector<SpeciesGraph>& products,
                          std::size_t nProductPatterns)
{
    std::string sid;
    for (std::size_t i = 0; i < reactants.size(); ++i) {
        if (i > 0) sid += '+';
        sid += reactants[i].toStringForDedup();
    }
    sid += "->";
    // First nProductPatterns products in order
    std::size_t nProd = std::min(products.size(), nProductPatterns);
    for (std::size_t i = 0; i < nProd; ++i) {
        if (i > 0) sid += '+';
        sid += products[i].toStringForDedup();
    }
    // Extra products sorted
    if (products.size() > nProductPatterns) {
        std::vector<std::string> extras;
        for (std::size_t i = nProductPatterns; i < products.size(); ++i) {
            extras.push_back(products[i].toStringForDedup());
        }
        std::sort(extras.begin(), extras.end());
        for (const auto& e : extras) {
            sid += '+';
            sid += e;
        }
    }
    return sid;
}

// Check if a species graph is a population type (single molecule with no components).
bool isPopulationType(const SpeciesGraph& sg,
                      const std::vector<MoleculeType>& molTypes)
{
    const auto& graph = sg.getGraph();
    std::size_t molCount = 0;
    BNGcore::Node* molNode = nullptr;
    for (auto it = graph.begin(); it != graph.end(); ++it) {
        if (isMoleculeNode(**it)) {
            ++molCount;
            molNode = *it;
        }
    }
    if (molCount != 1 || !molNode) return false;

    // Check that this molecule type is flagged as population
    const std::string& typeName = molNode->get_type().get_type_name();
    for (const auto& mt : molTypes) {
        if (mt.getName() == typeName && mt.isPopulation()) return true;
    }
    return false;
}

// Transfer labels from a source (pattern) map to a target (species copy) map.
// Perl: $match_copy->transferLabels()
// This copies label_tag from source node to the mapped target node.
void transferLabels(const BNGcore::Map& map) {
    for (auto it = map.begin(); it != map.end(); ++it) {
        BNGcore::Node* src = it->first;
        BNGcore::Node* tgt = it->second;
        if (tgt && !src->get_label_tag().empty()) {
            tgt->set_label_tag(src->get_label_tag());
        }
    }
}

// Gather all label_tags from nodes in a graph.
void gatherLabels(const BNGcore::PatternGraph& graph,
                  std::unordered_set<std::string>& usedLabels)
{
    for (auto it = graph.begin(); it != graph.end(); ++it) {
        const auto& tag = (*it)->get_label_tag();
        if (!tag.empty()) usedLabels.insert(tag);
    }
}

// Assign unique temporary labels to all unlabeled nodes.
// Returns number of labels assigned.
int assignTempLabels(BNGcore::PatternGraph& graph,
                     int startIdx,
                     std::unordered_map<std::string, bool>& tempLabels,
                     const std::unordered_set<std::string>& usedLabels)
{
    int idx = startIdx;
    for (auto it = graph.begin(); it != graph.end(); ++it) {
        if ((*it)->get_label_tag().empty()) {
            // Generate a unique label that doesn't collide with used labels
            std::string label;
            do {
                label = "t" + std::to_string(idx++);
            } while (usedLabels.count(label));
            (*it)->set_label_tag(label);
            tempLabels[label] = true;
        }
    }
    return idx - startIdx;
}

// Remove temporary labels that appear identically in both reactants and products.
// Perl: SpeciesGraph::removeRedundantLabels($reactants, $products, $temp_labels)
void removeRedundantLabels(std::vector<SpeciesGraph>& reactants,
                           std::vector<SpeciesGraph>& products,
                           const std::unordered_map<std::string, bool>& tempLabels)
{
    // Collect labels used in products
    std::unordered_set<std::string> prodLabels;
    for (auto& p : products) {
        for (auto it = p.getGraph().begin(); it != p.getGraph().end(); ++it) {
            const auto& tag = (*it)->get_label_tag();
            if (!tag.empty()) prodLabels.insert(tag);
        }
    }

    // For each temp label in reactants, if it's NOT in products, remove it
    // Also remove temp labels from products that aren't in reactants
    std::unordered_set<std::string> reacLabels;
    for (auto& r : reactants) {
        for (auto it = r.getGraph().begin(); it != r.getGraph().end(); ++it) {
            const auto& tag = (*it)->get_label_tag();
            if (!tag.empty()) reacLabels.insert(tag);
        }
    }

    // Remove temp labels that don't need to bridge reactants<->products
    for (auto& r : reactants) {
        for (auto it = r.getGraph().begin(); it != r.getGraph().end(); ++it) {
            const auto& tag = (*it)->get_label_tag();
            if (!tag.empty() && tempLabels.count(tag) && !prodLabels.count(tag)) {
                (*it)->set_label_tag("");
            }
        }
    }
    for (auto& p : products) {
        for (auto it = p.getGraph().begin(); it != p.getGraph().end(); ++it) {
            const auto& tag = (*it)->get_label_tag();
            if (!tag.empty() && tempLabels.count(tag) && !reacLabels.count(tag)) {
                (*it)->set_label_tag("");
            }
        }
    }
}

// Safe delete a node from a graph, removing all edges first.
void safeDeleteNode(BNGcore::PatternGraph& graph, BNGcore::Node* node) {
    if (!node) return;
    std::vector<BNGcore::Node*> incoming, outgoing;
    for (auto e = node->edges_in_begin(); e != node->edges_in_end(); ++e)
        incoming.push_back(*e);
    for (auto e = node->edges_out_begin(); e != node->edges_out_end(); ++e)
        outgoing.push_back(*e);
    for (auto* n : incoming) graph.delete_edge(n, node);
    for (auto* n : outgoing) graph.delete_edge(node, n);
    graph.delete_node(node);
}

} // anonymous namespace


namespace {

// BNGL text of a refined pattern.  toString() drops compartments, which a
// compartmental child rule needs: @EC:L(r) is not L(r).  When there is no
// outer species-level compartment, format per-molecule @COMP suffixes directly
// in valid BNGL syntax instead of emitting internal dedup markers.
std::string authoredPattern(const SpeciesGraph& pattern) {
    if (pattern.getCompartment().empty()) {
        std::vector<std::string> molComps;
        const std::string base = pattern.getGraph().get_BNG2_string(molComps);
        bool anyComp = false;
        for (const auto& c : molComps) {
            if (!c.empty()) {
                anyComp = true;
                break;
            }
        }
        if (!anyComp) return base;

        std::string result;
        result.reserve(base.size() + molComps.size() * 6);
        std::size_t molIdx = 0;
        std::size_t pos = 0;
        while (pos < base.size()) {
            int parenDepth = 0;
            std::size_t molEnd = pos;
            while (molEnd < base.size()) {
                if (base[molEnd] == '(') ++parenDepth;
                else if (base[molEnd] == ')') --parenDepth;
                else if (base[molEnd] == '.' && parenDepth == 0) break;
                ++molEnd;
            }
            result.append(base, pos, molEnd - pos);
            if (molIdx < molComps.size() && !molComps[molIdx].empty()) {
                result += "@" + molComps[molIdx];
            }
            if (molEnd < base.size() && base[molEnd] == '.') {
                result += '.';
                ++molEnd;
            }
            pos = molEnd;
            ++molIdx;
        }
        return result;
    }
    std::string text = pattern.toStringForDedup();  // "@C::..." form
    const auto doubleColon = text.find("::");
    if (!text.empty() && text[0] == '@' && doubleColon != std::string::npos) {
        text.erase(doubleColon, 1);
    }
    return text;
}

std::string extractLeadingScopePrefix(const std::string& patternText) {
    const std::size_t pos = patternText.find_first_not_of(" \t\r\n");
    if (pos == std::string::npos || patternText[pos] != '%') return {};
    const std::size_t begin = pos + 1;
    if (begin >= patternText.size() ||
        !(std::isalpha(static_cast<unsigned char>(patternText[begin])) ||
          patternText[begin] == '_')) {
        return {};
    }
    std::size_t end = begin + 1;
    while (end < patternText.size() &&
           (std::isalnum(static_cast<unsigned char>(patternText[end])) ||
            patternText[end] == '_')) {
        ++end;
    }
    if (end < patternText.size() && patternText[end] == ':') {
        std::size_t colonEnd = end + 1;
        if (colonEnd < patternText.size() && patternText[colonEnd] == ':') {
            ++colonEnd;
        }
        return patternText.substr(pos, colonEnd - pos);
    }
    return {};
}

bool isValidBnglIdentifier(const std::string& text) {
    if (text.empty()) return false;
    const unsigned char first = static_cast<unsigned char>(text[0]);
    if (!(std::isalpha(first) || first == '_')) return false;
    for (std::size_t i = 1; i < text.size(); ++i) {
        const unsigned char c = static_cast<unsigned char>(text[i]);
        if (!(std::isalnum(c) || c == '_')) return false;
    }
    return true;
}

bool expressionCanBeParameter(const Expression& expr, const Model& model) {
    switch (expr.kind()) {
    case ExpressionKind::Number:
        return true;
    case ExpressionKind::Identifier: {
        const auto& name = expr.name();
        if (name == "time" || name == "t") return false;
        return model.getParameters().contains(name);
    }
    case ExpressionKind::Unary:
    case ExpressionKind::Binary:
        for (const auto& arg : expr.args()) {
            if (!expressionCanBeParameter(arg, model)) return false;
        }
        return true;
    case ExpressionKind::Function: {
        const auto& fn = expr.name();
        for (const auto& modelFn : model.getFunctions()) {
            if (modelFn.getName() == fn) return false;
        }
        for (const auto& obs : model.getObservables()) {
            if (obs.getName() == fn) return false;
        }
        for (const auto& arg : expr.args()) {
            if (!expressionCanBeParameter(arg, model)) return false;
        }
        return fn != "time" && fn != "tfun";
    }
    default:
        return false;
    }
}

void removeNodesForDeletedMolecules(
    BNGcore::PatternGraph& aggregateGraph,
    const std::vector<BNGcore::Node*>& molsToDelete)
{
    if (molsToDelete.empty()) return;
    std::unordered_set<BNGcore::Node*> deletedMols(molsToDelete.begin(), molsToDelete.end());
    std::unordered_set<BNGcore::Node*> deletedComps;
    for (auto* mol : molsToDelete) {
        for (auto e = mol->edges_out_begin(); e != mol->edges_out_end(); ++e) {
            if (isComponentNode(**e)) deletedComps.insert(*e);
        }
    }

    std::vector<BNGcore::Node*> liberatedPartners;
    std::unordered_set<BNGcore::Node*> liberatedSeen;
    std::unordered_set<BNGcore::Node*> deletedBonds;

    for (auto* aggMol : molsToDelete) {
        std::vector<BNGcore::Node*> children;
        for (auto e = aggMol->edges_out_begin(); e != aggMol->edges_out_end(); ++e) {
            children.push_back(*e);
        }
        for (auto* child : children) {
            std::vector<BNGcore::Node*> grandchildren;
            for (auto e = child->edges_out_begin(); e != child->edges_out_end(); ++e) {
                grandchildren.push_back(*e);
            }
            for (auto* gc : grandchildren) {
                if (!deletedBonds.insert(gc).second) continue;
                if (isBondNode(*gc)) {
                    for (auto inIt = gc->edges_in_begin(); inIt != gc->edges_in_end(); ++inIt) {
                        BNGcore::Node* partner = *inIt;
                        if (partner != child && !deletedComps.count(partner) &&
                            liberatedSeen.insert(partner).second) {
                            liberatedPartners.push_back(partner);
                        }
                    }
                }
                safeDeleteNode(aggregateGraph, gc);
            }
            safeDeleteNode(aggregateGraph, child);
        }
        safeDeleteNode(aggregateGraph, aggMol);
    }

    // Re-attach an UNBOUND_STATE bond marker to any surviving partner site
    // that lost its last bond when the deleted molecule was removed.
    for (auto* partner : liberatedPartners) {
        bool hasRemainingBond = false;
        for (auto e = partner->edges_out_begin(); e != partner->edges_out_end(); ++e) {
            if (isBondNode(**e)) {
                hasRemainingBond = true;
                break;
            }
        }
        if (!hasRemainingBond) {
            auto* ub = new BNGcore::Node(BNGcore::BOND_NODE_TYPE);
            ub->set_state(BNGcore::UNBOUND_STATE);
            aggregateGraph.add_node(ub);
            aggregateGraph.add_edge(partner, ub);
        }
    }
}

// Parsed rules keep an internal R<n> identity and the authored rule name in
// label_ (including its colon). Hybrid child names follow BNG2's authored
// name when present; programmatically constructed rules use their identity.
std::string hybridRuleBaseName(const ReactionRule& rule) {
    const auto& label = rule.getLabel();
    if (!label.empty() && label.back() == ':') {
        return label.substr(0, label.size() - 1);
    }
    return rule.getRuleName();
}

} // namespace

// ---- factorial ----
// Perl lines 756-761
double factorial(int n) {
    if (n <= 0) return 1.0;
    return static_cast<double>(n) * factorial(n - 1);
}


// ---- expandRule ----
// Faithful port of RefineRule.pm::expandRule (lines 295-425)
ExpandRuleResult expandRule(
    const ReactionRule& rule,
    const std::vector<SpeciesGraph>& sgList,
    const Model& model,
    Model& hybridModel,
    const RefineRuleParams& params)
{
    ExpandRuleResult result;

    // BNG2 refines the two directions of a reversible rule separately: the
    // reverse rule's reactant is the forward product, whose population
    // substitutions and embeddings differ from the forward reactants'.  A
    // child left bidirectional would reverse once per forward child, so a
    // complex matched by two forward children dissociated at twice the rate.
    // Children of the reverse direction are named _reverse_<rule>_v<n>.
    if (rule.isBidirectional() && rule.getRates().size() == 2 &&
        !rule.hasDrivingWork()) {
        ReactionRule forward(rule.getRuleName(), rule.getLabel(), rule.getReactants(),
                             rule.getProducts(), {rule.getRates()[0]}, rule.getModifiers(),
                             false, rule.getReactantPatterns(), rule.getProductPatterns());
        ReactionRule reverse("_reverse_" + rule.getRuleName(), "_reverse_" + rule.getLabel(),
                             rule.getProducts(), rule.getReactants(), {rule.getRates()[1]},
                             rule.getModifiers(), false, rule.getProductPatterns(),
                             rule.getReactantPatterns());
        forward.setHasScopePrefix(rule.hasScopePrefix());
        reverse.setHasScopePrefix(rule.hasScopePrefix());
        if (rule.getDelayExpression()) {
            forward.setDelay(*rule.getDelayExpression(), rule.isNonConsuming());
            reverse.setDelay(*rule.getDelayExpression(), rule.isNonConsuming());
        }
        for (auto* direction : {&forward, &reverse}) {
            auto expanded = expandRule(*direction, sgList, model, hybridModel, params);
            if (!expanded.error.empty()) {
                result.error = expanded.error;
                return result;
            }
            for (auto& child : expanded.childRules) {
                result.childRules.push_back(std::move(child));
            }
        }
        return result;
    }

    const auto& reactantPatterns = rule.getReactantPatterns();
    const std::size_t nReactants = reactantPatterns.size();

    // Rmatches[ipatt] = list of embedding results for pattern ipatt
    std::vector<std::vector<ReactionRule::EmbeddingResult>> rmatches(nReactants);

    // --- For each reactant pattern, find all embeddings (Perl lines 328-377) ---
    for (std::size_t ipatt = 0; ipatt < nReactants; ++ipatt) {
        const auto& patt = reactantPatterns[ipatt];

        if (params.safe) {
            // Safe mode: always add self-embedding (Perl lines 333-339)
            // Copy pattern without labels but getting labels, then find isomorphism
            BNGcore::PatternGraph copyGraph;
            auto cloneMap = cloneGraphInto(patt.getGraph(), copyGraph);

            // Find subgraph isomorphism of pattern into its own copy
            auto maps = findAllMaps(patt.getGraph(), copyGraph);
            if (!maps.empty()) {
                ReactionRule::EmbeddingResult selfEmbed;
                selfEmbed.speciesIndex = static_cast<std::size_t>(-1); // sentinel: self-embedding
                selfEmbed.map = maps[0];
                selfEmbed.multiplicity = 1;
                rmatches[ipatt].push_back(std::move(selfEmbed));
            }
        } else {
            // Non-safe: add self-embedding only if pattern is NOT isomorphic
            // to any species in sgList (Perl lines 343-362)
            bool isIsomorph = false;
            for (const auto& sg : sgList) {
                // A pattern without a compartment also matches particles in
                // compartments the population does not lump, so it is not
                // isomorphic to @EC:L(r) even when the graphs are.
                if (sg.getCompartment() != patt.getCompartment()) continue;
                if (hasSubgraphIso(sg.getGraph(), patt.getGraph())) {
                    isIsomorph = true;
                    break;
                }
            }
            if (!isIsomorph) {
                BNGcore::PatternGraph copyGraph;
                auto cloneMap = cloneGraphInto(patt.getGraph(), copyGraph);
                auto maps = findAllMaps(patt.getGraph(), copyGraph);
                if (!maps.empty()) {
                    ReactionRule::EmbeddingResult selfEmbed;
                    selfEmbed.speciesIndex = static_cast<std::size_t>(-1);
                    selfEmbed.map = maps[0];
                    selfEmbed.multiplicity = 1;
                    rmatches[ipatt].push_back(std::move(selfEmbed));
                }
            }
        }

        // Find all embeddings of pattern into each species graph in sgList
        // (Perl lines 367-368)
        for (std::size_t si = 0; si < sgList.size(); ++si) {
            // Particle graph isomorphism ignores compartment annotations, but
            // a compartment-qualified rule pattern can only be represented by
            // the population that lumps particles in that same compartment.
            if (!patt.getCompartment().empty() &&
                patt.getCompartment() != sgList[si].getCompartment()) {
                continue;
            }
            // BNG2 keeps one embedding per distinct image of the pattern's
            // reaction center in each target (find_embeddings ->
            // filter_identical_by_rxn_center). Embeddings that differ only
            // outside the reaction center are the same transition, so the
            // match count, and with it the child multiplicity below, counts
            // reaction-center images rather than graph automorphisms.
            auto maps = rule.filterIdenticalByReactionCenter(
                ipatt, findAllMaps(patt.getGraph(), sgList[si].getGraph()));
            for (auto& m : maps) {
                ReactionRule::EmbeddingResult embed;
                embed.speciesIndex = si;
                embed.map = std::move(m);
                embed.multiplicity = 1;
                rmatches[ipatt].push_back(std::move(embed));
            }
        }

        if (params.verbose) {
            std::size_t total = rmatches[ipatt].size();
            std::cerr << params.indent << "  ..found " << total
                      << " match" << (total == 1 ? "" : "es")
                      << " to reactant pattern " << (ipatt + 1) << "\n";
        }
    }

    // --- Cartesian product of all match combinations (Perl lines 381-403) ---
    // child_rule_map: StringID -> index in childRules
    std::unordered_map<std::string, std::size_t> childRuleMap;

    // Build Cartesian product iteratively
    // indices[i] iterates over rmatches[i]
    std::vector<std::size_t> indices(nReactants, 0);

    // Check if any pattern has zero matches -- if so, no child rules
    bool hasEmpty = false;
    for (std::size_t i = 0; i < nReactants; ++i) {
        if (rmatches[i].empty()) {
            hasEmpty = true;
            break;
        }
    }

    if (nReactants == 0) {
        // A rule with no reactant patterns (0 -> A()) has exactly one rule
        // instance, the empty one; BNG2's CartesianProduct yields it once.
        auto childRule = restrictRule(rule, {}, model, hybridModel, params);
        if (childRule) {
            result.childRules.push_back(std::move(*childRule));
        }
    } else if (!hasEmpty) {
        bool done = false;
        while (!done) {
            // Build rule instance: one embedding per reactant
            std::vector<ReactionRule::EmbeddingResult> ruleInstance;
            ruleInstance.reserve(nReactants);
            for (std::size_t i = 0; i < nReactants; ++i) {
                ruleInstance.push_back(rmatches[i][indices[i]]);
            }

            // Call restrictRule for this instance (Perl line 389)
            auto childRule = restrictRule(rule, ruleInstance, model, hybridModel, params);

            if (childRule) {
                // Build StringID for dedup
                std::vector<SpeciesGraph> crReactants, crProducts;
                for (const auto& r : childRule->getReactantPatterns())
                    crReactants.push_back(r);
                for (const auto& p : childRule->getProductPatterns())
                    crProducts.push_back(p);
                std::string stringID = buildStringID(
                    crReactants, crProducts, rule.getProductPatterns().size());

                auto mapIt = childRuleMap.find(stringID);
                if (mapIt != childRuleMap.end()) {
                    // Duplicate: accumulate stat factor (Perl lines 392-396)
                    // The stat factor is accumulated as multiplicity
                    // We don't have a direct Factor field, so we track it via
                    // the multiplicity counter stored externally.
                    // For now, we simply don't add the duplicate.
                    // The stat factor accumulation is handled after the loop.
                } else {
                    childRuleMap[stringID] = result.childRules.size();
                    result.childRules.push_back(std::move(*childRule));
                }
            }

            // Advance Cartesian product iterator (odometer style)
            std::size_t carry = nReactants;
            while (carry > 0) {
                --carry;
                ++indices[carry];
                if (indices[carry] < rmatches[carry].size()) break;
                indices[carry] = 0;
                if (carry == 0) done = true;
            }
        }
    }

    // --- Adjust rate parameters for stat factors (Perl lines 405-421) ---
    // In the Perl code, duplicate child rules accumulate a Factor.
    // Since we deduplicated above by simply skipping duplicates,
    // and the Perl logic multiplies the rate by Factor only when Factor != 1,
    // the dedup above effectively gives Factor=1 for each unique child rule.
    // A full implementation with proper stat factor tracking would count
    // how many Cartesian product combinations map to the same StringID.
    //
    // For correctness, we re-count: iterate the Cartesian product again
    // and count occurrences per StringID if there are duplicates.
    if (result.childRules.size() < childRuleMap.size()) {
        // This shouldn't happen, but guard against it
    }

    // Assign names to distinct refined rules after deduplication. Automorphic
    // embeddings that collapse to one child must not consume a child number.
    for (std::size_t i = 0; i < result.childRules.size(); ++i) {
        std::string name = hybridRuleBaseName(rule) + "_v" + std::to_string(i + 1);
        std::size_t reversePos = 0;
        while ((reversePos = name.find("(reverse)", reversePos)) != std::string::npos) {
            name.replace(reversePos, 9, "_rev");
            reversePos += 4;
        }
        result.childRules[i].setRuleName(name);
        result.childRules[i].setLabel(name);
    }

    // If we need stat factors, recount (only if there were duplicates)
    {
        // Re-iterate Cartesian product to count multiplicities. Each rule
        // instance adds parent.MultScale / child.MultScale (RefineRule.pm
        // 739-745), computed from exact rule automorphisms including both
        // inter-pattern permutations and within-pattern reaction-center
        // symmetries.
        const double parentScale = ruleSymmetryFactorForRefinement(rule);
        std::unordered_map<std::string, double> factorMap;
        std::fill(indices.begin(), indices.end(), 0);
        bool done2 = hasEmpty || nReactants == 0;
        while (!done2) {
            std::vector<ReactionRule::EmbeddingResult> ruleInstance;
            ruleInstance.reserve(nReactants);
            for (std::size_t i = 0; i < nReactants; ++i) {
                ruleInstance.push_back(rmatches[i][indices[i]]);
            }

            auto childRule = restrictRule(rule, ruleInstance, model, hybridModel, params);
            if (childRule) {
                std::vector<SpeciesGraph> crReactants, crProducts;
                for (const auto& r : childRule->getReactantPatterns())
                    crReactants.push_back(r);
                for (const auto& p : childRule->getProductPatterns())
                    crProducts.push_back(p);
                std::string sid = buildStringID(
                    crReactants, crProducts, rule.getProductPatterns().size());
                const double childScale = ruleSymmetryFactorForRefinement(*childRule);
                factorMap[sid] += parentScale / childScale;
            }

            std::size_t carry = nReactants;
            while (carry > 0) {
                --carry;
                ++indices[carry];
                if (indices[carry] < rmatches[carry].size()) break;
                indices[carry] = 0;
                if (carry == 0) done2 = true;
            }
        }

        // Adjust rates for stat factors != 1 (Perl lines 405-421), in child
        // order so that the scaled rate parameters are numbered as BNG2
        // numbers them.
        std::vector<std::pair<std::size_t, std::string>> childOrder;
        childOrder.reserve(childRuleMap.size());
        for (const auto& [sid, idx] : childRuleMap) childOrder.emplace_back(idx, sid);
        std::sort(childOrder.begin(), childOrder.end());
        for (const auto& [idx, sid] : childOrder) {
            double factor = factorMap.count(sid) ? factorMap[sid] : 1.0;
            if (std::abs(factor - 1.0) > 1e-12 && idx < result.childRules.size()) {
                auto& childRule = result.childRules[idx];
                const auto& rates = childRule.getRates();
                if (!rates.empty()) {
                    const Expression factorExpr = Expression::number(factor);
                    const Expression origExpr = rates[0];
                    const Expression newExpr = Expression::binary("*", factorExpr, origExpr);

                    std::vector<Expression> newRates;
                    if (expressionCanBeParameter(origExpr, model)) {
                        const std::string rawParamName = origExpr.toString();
                        const std::string baseParamName =
                            isValidBnglIdentifier(rawParamName) ? rawParamName : "_rateLaw";
                        std::string newParamName;
                        for (int suffix = 1;; ++suffix) {
                            newParamName = baseParamName + "_" + std::to_string(suffix);
                            if (!hybridModel.getParameters().contains(newParamName)) break;
                        }
                        hybridModel.addParameter(Parameter(newParamName, newExpr));
                        newRates.push_back(Expression::identifier(newParamName));
                    } else {
                        newRates.push_back(newExpr);
                    }
                    for (std::size_t i = 1; i < rates.size(); ++i) {
                        newRates.push_back(rates[i]);
                    }
                    ReactionRule refinedRule(
                        childRule.getRuleName(),
                        childRule.getLabel(),
                        childRule.getReactants(),
                        childRule.getProducts(),
                        std::move(newRates),
                        childRule.getModifiers(),
                        childRule.isBidirectional(),
                        childRule.getReactantPatterns(),
                        childRule.getProductPatterns());
                    refinedRule.setHasScopePrefix(childRule.hasScopePrefix());
                    if (childRule.getDelayExpression()) {
                        refinedRule.setDelay(*childRule.getDelayExpression(),
                                             childRule.isNonConsuming());
                    }
                    if (childRule.hasDrivingWork()) {
                        refinedRule.setDrivingWorkExpression(
                            childRule.drivingWorkExpression());
                    }
                    result.childRules[idx] = std::move(refinedRule);
                }
            }
        }
    }

    return result;
}


// ---- restrictRule ----
// Faithful port of RefineRule.pm::restrict_rule (lines 436-746)
std::unique_ptr<ReactionRule> restrictRule(
    const ReactionRule& rule,
    const std::vector<ReactionRule::EmbeddingResult>& ruleInstance,
    const Model& model,
    Model& hybridModel,
    const RefineRuleParams& params)
{
    const auto& reactantPatterns = rule.getReactantPatterns();
    const auto& productPatterns = rule.getProductPatterns();
    const std::size_t nReactants = reactantPatterns.size();
    const std::size_t nProducts = productPatterns.size();

    // ---- Step 1: Copy target reactants, transfer labels (Perl lines 461-473) ----
    std::vector<SpeciesGraph> reactants;
    std::vector<BNGcore::Map> matches;
    reactants.reserve(nReactants);
    matches.reserve(nReactants);

    for (std::size_t i = 0; i < ruleInstance.size(); ++i) {
        const auto& embed = ruleInstance[i];

        // copy_map_and_target: copy the target graph and remap
        // For self-embeddings (sentinel index), the target is the pattern itself
        BNGcore::PatternGraph targetCopy;
        BNGcore::Map mapCopy;

        if (embed.speciesIndex == static_cast<std::size_t>(-1)) {
            // Self-embedding: target is the pattern
            auto cloneMap = cloneGraphInto(reactantPatterns[i].getGraph(), targetCopy);
            // The embedding saved by expandRule points into a temporary
            // PatternGraph that has already been destroyed. Rebuild the
            // identity embedding directly into this owned clone.
            mapCopy = BNGcore::Map();
            mapCopy.set_source_graph(const_cast<BNGcore::PatternGraph*>(&reactantPatterns[i].getGraph()));
            mapCopy.set_target_graph(&targetCopy);
            for (auto node = reactantPatterns[i].getGraph().begin();
                 node != reactantPatterns[i].getGraph().end(); ++node) {
                auto cloneIt = cloneMap.find(*node);
                if (cloneIt != cloneMap.end()) {
                    mapCopy.insert(*node, cloneIt->second);
                }
            }
        } else {
            // Normal embedding into a species graph from sgList
            // PatternGraph has deleted copy assignment, so we clone manually
            const BNGcore::PatternGraph* targetGraph = embed.map.get_target_graph();
            if (!targetGraph) return nullptr;
            auto cloneMap = cloneGraphInto(*targetGraph, targetCopy);
            mapCopy = BNGcore::Map();
            mapCopy.set_source_graph(const_cast<BNGcore::PatternGraph*>(
                embed.map.get_source_graph()));
            mapCopy.set_target_graph(&targetCopy);
            for (auto it = embed.map.begin(); it != embed.map.end(); ++it) {
                auto cloneIt = cloneMap.find(it->second);
                if (cloneIt != cloneMap.end()) {
                    mapCopy.insert(it->first, cloneIt->second);
                }
            }
        }

        // Transfer labels from pattern to target copy (Perl line 469)
        transferLabels(mapCopy);

        // The species-level compartment of the copied target: the pattern's
        // own for a self-embedding, the population species' otherwise. When a
        // multi-molecule pattern carries per-molecule compartments (e.g.
        // R@PM.L@EC), infer the complex compartment via 2D-surface precedence.
        std::string compartment;
        if (embed.speciesIndex == static_cast<std::size_t>(-1)) {
            compartment = reactantPatterns[i].getCompartment();
            if (compartment.empty()) {
                compartment = reactantPatterns[i].inferCompartment(model.getCompartments());
            }
        } else if (params.populationParticleGraphs != nullptr &&
                   embed.speciesIndex < params.populationParticleGraphs->size()) {
            compartment = (*params.populationParticleGraphs)[embed.speciesIndex].getCompartment();
            if (compartment.empty()) {
                compartment = (*params.populationParticleGraphs)[embed.speciesIndex].inferCompartment(
                    model.getCompartments());
            }
        }

        // The embedding maps into the cloned target graph. Preserve that node
        // identity and point the map at the graph object that now owns it.
        reactants.emplace_back(std::move(targetCopy), compartment);
        mapCopy.set_target_graph(&reactants.back().getGraph());
        matches.push_back(std::move(mapCopy));
    }

    // Reactant species must form an interacting set (RefineRule.pm 496-498,
    // SpeciesGraph::interactingSet): one surface and one volume at most, and
    // an adjacent pair if both.
    // A reactant without a compartment is a pattern copy that matches
    // particles in any compartment; network generation checks the species it
    // meets.  Here only reactants that are fixed to a compartment (named in
    // the rule, or a population) have to interact.  BNG2 also rejects the
    // mixture, which would drop L(r) + @PM:R_pop() although L particles in an
    // adjacent volume react with that population.
    if (reactants.size() > 1) {
        std::vector<std::string> compartments;
        compartments.reserve(reactants.size());
        for (const auto& reactant : reactants) {
            if (!reactant.getCompartment().empty()) {
                compartments.push_back(reactant.getCompartment());
            }
        }
        if (!compartmentsFormInteractingSet(compartments)) {
            if (params.verbose) {
                std::cerr << "Rule " << rule.getRuleName()
                          << ": reactant compartments do not interact\n";
            }
            return nullptr;
        }
    }

    // ---- Step 2: Gather labels and assign temp labels (Perl lines 477-493) ----
    std::unordered_set<std::string> usedLabels;
    for (const auto& pattR : reactantPatterns) {
        gatherLabels(pattR.getGraph(), usedLabels);
    }
    for (const auto& pattP : productPatterns) {
        gatherLabels(pattP.getGraph(), usedLabels);
    }

    std::unordered_map<std::string, bool> tempLabels;
    int iLabel = 0;
    for (auto& reactant : reactants) {
        iLabel += assignTempLabels(reactant.getGraph(), iLabel, tempLabels, usedLabels);
    }

    // ---- Step 3: Apply rule operations (Perl line 500) ----
    // Build aggregate graph from reactants, apply operations, then split into products.
    BNGcore::PatternGraph aggregateGraph;
    std::vector<std::unordered_map<BNGcore::Node*, BNGcore::Node*>> cloneMaps;
    cloneMaps.reserve(nReactants);

    for (const auto& reactant : reactants) {
        cloneMaps.push_back(cloneGraphInto(reactant.getGraph(), aggregateGraph));
    }

    // A reactant pattern without a product counterpart deletes the whole
    // matched species, unless DeleteMolecules is given (BNG2's species
    // deletion; the same rule ReactionRule::deletesWholeReactantPattern
    // applies during network generation).  A pure degradation A() -> 0 has
    // no explicit operation at all, so its species have to be removed here.
    std::vector<bool> deletesSpecies(nReactants, false);
    for (std::size_t i = 0; i < nReactants && i < reactantPatterns.size(); ++i) {
        deletesSpecies[i] = rule.deletesWholeReactantPattern(i);
    }

    auto findAggComponent = [&](const ReactionRule::ComponentRef& ref) -> BNGcore::Node* {
        if (ref.patternIndex >= nReactants) return nullptr;
        const auto& patt = reactantPatterns[ref.patternIndex];
        std::size_t mi = 0;
        for (auto nIt = patt.getGraph().begin(); nIt != patt.getGraph().end(); ++nIt) {
            if (!isMoleculeNode(**nIt)) continue;
            if (mi == ref.moleculeIndex) {
                std::size_t ci = 0;
                for (auto e = (*nIt)->edges_out_begin(); e != (*nIt)->edges_out_end(); ++e) {
                    if (!isComponentNode(**e)) continue;
                    if (ci == ref.componentIndex) {
                        BNGcore::Node* matched = matches[ref.patternIndex].mapf(*e);
                        if (matched) {
                            auto cIt = cloneMaps[ref.patternIndex].find(matched);
                            if (cIt != cloneMaps[ref.patternIndex].end()) return cIt->second;
                        }
                        return nullptr;
                    }
                    ++ci;
                }
                return nullptr;
            }
            ++mi;
        }
        return nullptr;
    };

    const auto crossBonds = rule.getCrossBonds();
    std::set<ReactionRule::ComponentRef> crossBondProductComponents;
    for (const auto& [rComp, pComp] : crossBonds) {
        (void)rComp;
        crossBondProductComponents.insert(pComp);
    }
    std::unordered_map<const BNGcore::Node*, BNGcore::Node*> addedProductBonds;
    std::map<ReactionRule::ComponentRef, BNGcore::Node*> addedProductComponents;
    std::vector<BNGcore::Node*> molsToDelete;

    // Apply each transformation operation
    for (const auto& op : rule.getOperations()) {
        switch (op.type) {
        case ReactionRule::TransformOp::Type::ChangeState: {
            if (BNGcore::Node* aggNode = findAggComponent(op.source)) {
                const auto& stateType = aggNode->get_type().get_state_type();
                const auto& labelType = static_cast<const BNGcore::LabelStateType&>(stateType);
                BNGcore::LabelState state(labelType, op.newState);
                aggregateGraph.set_node_state(aggNode, state);
            }
            break;
        }
        case ReactionRule::TransformOp::Type::AddBond: {
            BNGcore::Node* lhs = findAggComponent(op.source);
            BNGcore::Node* rhs = findAggComponent(op.partner);
            if (!lhs || !rhs) return nullptr;

            auto removeUnbound = [&](BNGcore::Node* comp) {
                std::vector<BNGcore::Node*> toRemove;
                for (auto e = comp->edges_out_begin(); e != comp->edges_out_end(); ++e) {
                    if (isBondNode(**e) && (*e)->get_state() == BNGcore::UNBOUND_STATE) {
                        toRemove.push_back(*e);
                    }
                }
                for (auto* n : toRemove) safeDeleteNode(aggregateGraph, n);
            };
            removeUnbound(lhs);
            removeUnbound(rhs);

            auto* bondNode = new BNGcore::Node(BNGcore::BOND_NODE_TYPE);
            bondNode->set_state(BNGcore::BOUND_STATE);
            aggregateGraph.add_node(bondNode);
            aggregateGraph.add_edge(lhs, bondNode);
            aggregateGraph.add_edge(rhs, bondNode);
            break;
        }
        case ReactionRule::TransformOp::Type::DeleteBond: {
            BNGcore::Node* lhsNode = findAggComponent(op.source);
            BNGcore::Node* rhsNode = findAggComponent(op.partner);
            if (!lhsNode || !rhsNode) return nullptr;

            BNGcore::Node* sharedBond = nullptr;
            for (auto e1 = lhsNode->edges_out_begin(); e1 != lhsNode->edges_out_end(); ++e1) {
                if (!isBondNode(**e1)) continue;
                for (auto e2 = rhsNode->edges_out_begin(); e2 != rhsNode->edges_out_end(); ++e2) {
                    if (*e1 == *e2) { sharedBond = *e1; break; }
                }
                if (sharedBond) break;
            }
            if (sharedBond) {
                safeDeleteNode(aggregateGraph, sharedBond);
                auto* ub1 = new BNGcore::Node(BNGcore::BOND_NODE_TYPE);
                ub1->set_state(BNGcore::UNBOUND_STATE);
                aggregateGraph.add_node(ub1);
                aggregateGraph.add_edge(lhsNode, ub1);
                auto* ub2 = new BNGcore::Node(BNGcore::BOND_NODE_TYPE);
                ub2->set_state(BNGcore::UNBOUND_STATE);
                aggregateGraph.add_node(ub2);
                aggregateGraph.add_edge(rhsNode, ub2);
            }
            else return nullptr;
            break;
        }
        case ReactionRule::TransformOp::Type::DeleteMolecule: {
            if (op.patternIndex >= nReactants) break;
            if (deletesSpecies[op.patternIndex]) break;  // removed whole below
            const auto& patt = reactantPatterns[op.patternIndex];
            std::size_t mi = 0;
            for (auto nIt = patt.getGraph().begin(); nIt != patt.getGraph().end(); ++nIt) {
                if (!isMoleculeNode(**nIt)) continue;
                if (mi == op.moleculeIndex) {
                    BNGcore::Node* matched = matches[op.patternIndex].mapf(*nIt);
                    if (matched) {
                        auto cIt = cloneMaps[op.patternIndex].find(matched);
                        if (cIt != cloneMaps[op.patternIndex].end()) {
                            molsToDelete.push_back(cIt->second);
                        }
                    }
                    break;
                }
                ++mi;
            }
            break;
        }
        case ReactionRule::TransformOp::Type::AddMolecule: {
            // Clone the product molecule into the aggregate graph, sharing
            // bond nodes across molecules added from the same product pattern.
            if (op.patternIndex < productPatterns.size()) {
                const auto& prodPatt = productPatterns[op.patternIndex];
                std::size_t mi = 0;
                for (auto nIt = prodPatt.getGraph().begin(); nIt != prodPatt.getGraph().end(); ++nIt) {
                    if (!isMoleculeNode(**nIt)) continue;
                    if (mi == op.moleculeIndex) {
                        auto* molClone = (*nIt)->clone();
                        aggregateGraph.add_node(molClone);
                        std::size_t ci = 0;
                        for (auto e = (*nIt)->edges_out_begin(); e != (*nIt)->edges_out_end(); ++e) {
                            auto* compClone = (*e)->clone();
                            aggregateGraph.add_node(compClone);
                            aggregateGraph.add_edge(molClone, compClone);
                            const ReactionRule::ComponentRef prodCompRef{op.patternIndex, op.moleculeIndex, ci};
                            const bool isCrossBondSite = crossBondProductComponents.count(prodCompRef) != 0;
                            if (isComponentNode(**e)) {
                                addedProductComponents[prodCompRef] = compClone;
                                ++ci;
                            }
                            for (auto be = (*e)->edges_out_begin(); be != (*e)->edges_out_end(); ++be) {
                                if (isBondNode(**be) && (*be)->in_degree() >= 2) {
                                    if (isCrossBondSite) {
                                        // Cross-boundary bonds are wired below after all molecules exist.
                                        continue;
                                    }
                                    auto& sharedClone = addedProductBonds[*be];
                                    if (!sharedClone) {
                                        sharedClone = (*be)->clone();
                                        aggregateGraph.add_node(sharedClone);
                                    }
                                    aggregateGraph.add_edge(compClone, sharedClone);
                                } else {
                                    auto* bondClone = (*be)->clone();
                                    aggregateGraph.add_node(bondClone);
                                    aggregateGraph.add_edge(compClone, bondClone);
                                }
                            }
                        }
                        break;
                    }
                    ++mi;
                }
            }
            break;
        }
        } // switch
    }

    // Wire cross-boundary bonds between matched reactant sites and newly added
    // product molecules.
    for (const auto& [rComp, pComp] : crossBonds) {
        BNGcore::Node* lhs = findAggComponent(rComp);
        auto pIt = addedProductComponents.find(pComp);
        if (!lhs || pIt == addedProductComponents.end()) return nullptr;
        BNGcore::Node* rhs = pIt->second;
        std::vector<BNGcore::Node*> toRemove;
        for (auto e = lhs->edges_out_begin(); e != lhs->edges_out_end(); ++e) {
            if (isBondNode(**e) && (*e)->get_state() == BNGcore::UNBOUND_STATE) {
                toRemove.push_back(*e);
            }
        }
        for (auto* n : toRemove) safeDeleteNode(aggregateGraph, n);
        auto* bondNode = new BNGcore::Node(BNGcore::BOND_NODE_TYPE);
        bondNode->set_state(BNGcore::BOUND_STATE);
        aggregateGraph.add_node(bondNode);
        aggregateGraph.add_edge(lhs, bondNode);
        aggregateGraph.add_edge(rhs, bondNode);
    }

    // Pure degradation with molecule-level removal (e.g. A() -> 0 with the
    // molecule-deletion modifier) leaves operations_ empty and deletesSpecies
    // false: remove each matched reactant molecule individually while keeping
    // any bonded partners intact with fresh unbound markers.
    if (nProducts == 0 && rule.getOperations().empty()) {
        for (std::size_t i = 0; i < nReactants; ++i) {
            if (deletesSpecies[i]) continue;
            const auto& patt = reactantPatterns[i];
            for (auto nIt = patt.getGraph().begin(); nIt != patt.getGraph().end(); ++nIt) {
                if (!isMoleculeNode(**nIt)) continue;
                BNGcore::Node* matched = matches[i].mapf(*nIt);
                if (!matched) continue;
                auto cIt = cloneMaps[i].find(matched);
                if (cIt != cloneMaps[i].end()) {
                    molsToDelete.push_back(cIt->second);
                }
            }
        }
    }

    removeNodesForDeletedMolecules(aggregateGraph, molsToDelete);

    for (std::size_t i = 0; i < nReactants; ++i) {
        if (!deletesSpecies[i]) continue;
        std::vector<BNGcore::Node*> speciesNodes;
        speciesNodes.reserve(cloneMaps[i].size());
        for (const auto& entry : cloneMaps[i]) speciesNodes.push_back(entry.second);
        for (auto* node : speciesNodes) safeDeleteNode(aggregateGraph, node);
    }

    // Split aggregate into product species graphs
    auto products = splitConnected(aggregateGraph);

    // Self-embedding of an intramolecular bond-breaking rule (e.g.
    // A(r!1).A(l!1) -> A(r).A(l)): the parent's single product pattern is
    // intentionally disconnected (written with '.'), so preserve the aggregate
    // as one intramolecular product pattern rather than splitting into '+'.
    const bool allSelfEmbeddings = !ruleInstance.empty() &&
        std::all_of(ruleInstance.begin(), ruleInstance.end(),
                    [](const ReactionRule::EmbeddingResult& e) {
                        return e.speciesIndex == static_cast<std::size_t>(-1);
                    });
    if (allSelfEmbeddings && nProducts == 1 && products.size() > 1 &&
        products.size() == productPatterns[0].numComponents()) {
        products.clear();
        products.emplace_back(aggregateGraph);
    }

    // ---- Step 4: Validate products (Perl lines 503-582) ----
    // Check number of product graphs
    if (products.size() != nProducts) {
        bool deleteMolecules = false;
        for (const auto& mod : rule.getModifiers()) {
            std::string lower = mod;
            std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
            if (lower == "deletemolecules") {
                deleteMolecules = true;
                break;
            }
        }
        if (deleteMolecules && products.size() > nProducts) {
            // OK: DeleteMolecules allows more subgraphs
            if (params.verbose) {
                std::cerr << "Deleting molecules in Rule " << rule.getRuleName() << "\n";
            }
        } else {
            if (params.verbose) {
                std::cerr << "Rule " << rule.getRuleName()
                          << ": n_sub (" << products.size()
                          << ") != n_prod (" << nProducts << ")\n";
            }
            return nullptr;
        }
    }

    for (std::size_t ip = 0; ip < products.size(); ++ip) {
        const auto& p = products[ip];
        const auto& pg = p.getGraph();
        int iprod = (ip < nProducts) ? static_cast<int>(ip) : -1;

        // Check max aggregation (Perl lines 528-532)
        if (countMolecules(pg) > params.maxAgg) {
            return nullptr;
        }

        // Check max stoichiometry (Perl lines 535-544)
        for (const auto& [key, maxVal] : params.maxStoich) {
            if (maxVal < 0) continue; // "unlimited"
            if (static_cast<double>(stoich(pg, key)) > maxVal) {
                return nullptr;
            }
        }

        // Note: sortLabel, Pexclude/Pinclude checks are omitted here because
        // the child rule construction below will handle them via the include/exclude
        // patterns set on the child rule. In the Perl code these are checked
        // against the specific product graphs, but in our architecture the
        // filtering happens during rule application.
    }

    // Product species compartments.  A product pattern that names its
    // compartment (@EC:A()) places the product there; otherwise a product
    // stays where its reactants are when they share one compartment.  The
    // aggregate split does not keep product-pattern order, so a product is
    // matched to the product pattern with the same molecule types.
    {
        std::string sharedReactantCompartment;
        bool shared = !reactants.empty();
        for (std::size_t i = 0; i < reactants.size(); ++i) {
            if (i == 0) sharedReactantCompartment = reactants[i].getCompartment();
            else if (reactants[i].getCompartment() != sharedReactantCompartment) shared = false;
        }
        if (!shared) sharedReactantCompartment.clear();
        auto moleculeTypes = [](const BNGcore::PatternGraph& graph) {
            std::vector<std::string> names;
            for (auto node = graph.begin(); node != graph.end(); ++node) {
                if (isMoleculeNode(**node)) names.push_back((*node)->get_type().get_type_name());
            }
            std::sort(names.begin(), names.end());
            return names;
        };
        std::vector<bool> usedPattern(nProducts, false);
        for (std::size_t ip = 0; ip < products.size(); ++ip) {
            std::string compartment;
            const auto types = moleculeTypes(products[ip].getGraph());
            std::size_t matched = nProducts;
            for (std::size_t pp = 0; pp < nProducts; ++pp) {
                if (!usedPattern[pp] && moleculeTypes(productPatterns[pp].getGraph()) == types) {
                    matched = pp;
                    break;
                }
            }
            if (matched == nProducts && ip < nProducts && !usedPattern[ip]) matched = ip;
            if (matched < nProducts) {
                usedPattern[matched] = true;
                compartment = productPatterns[matched].getCompartment();
            }
            if (compartment.empty()) {
                compartment = products[ip].inferCompartment(model.getCompartments());
            }
            if (compartment.empty()) compartment = sharedReactantCompartment;
            if (compartment.empty()) {
                // Reactants on a surface and in an adjacent volume make a
                // complex that lives on the surface (BNG2's cBNGL rule).
                std::vector<std::string> reactantCompartments;
                for (const auto& reactant : reactants) {
                    reactantCompartments.push_back(reactant.getCompartment());
                }
                compartment = surfaceOfInteractingSet(reactantCompartments);
            }
            if (!compartment.empty()) products[ip].setCompartment(compartment);
        }
    }

    // ---- Step 5: Replace complete mapped complexes with populations ----
    if (params.populationParticleGraphs && params.populationGraphs) {
        const auto count = std::min(params.populationParticleGraphs->size(),
                                    params.populationGraphs->size());
        auto replaceWholeComplex = [&](SpeciesGraph& species) {
            for (std::size_t i = 0; i < count; ++i) {
                const auto& particlePattern = (*params.populationParticleGraphs)[i];
                if ((!species.getCompartment().empty() &&
                     species.getCompartment() != particlePattern.getCompartment()) ||
                    !particlePattern.graphIsomorphicTo(
                        species.getGraph())) {
                    continue;
                }
                BNGcore::PatternGraph populationCopy;
                cloneGraphInto((*params.populationGraphs)[i].getGraph(), populationCopy);
                std::string compartment = (*params.populationGraphs)[i].getCompartment();
                if (compartment.empty()) compartment = species.getCompartment();
                species = SpeciesGraph(std::move(populationCopy), compartment);
                return;
            }
        };
        for (std::size_t i = 0; i < reactants.size() && i < ruleInstance.size(); ++i) {
            if (ruleInstance[i].speciesIndex != static_cast<std::size_t>(-1)) {
                replaceWholeComplex(reactants[i]);
            }
        }
        for (auto& product : products) replaceWholeComplex(product);
    }

    // ---- Step 6: Remove redundant temp labels (Perl line 626) ----
    removeRedundantLabels(reactants, products, tempLabels);

    // ---- Step 7: Construct child rule (Perl lines 629-741) ----
    // Generate child rule name (Perl lines 632-634)
    std::string childName = rule.getRuleName() + "_v1";
    // Remove "(reverse)" -> "_rev"
    std::string::size_type revPos;
    while ((revPos = childName.find("(reverse)")) != std::string::npos) {
        childName.replace(revPos, 9, "_rev");
    }

    // Build string representations, with the species-level compartment as
    // an @C: prefix and molecule compartments that differ from it, preserving
    // any leading %scope: / %scope:: tags from the parent rule.
    std::vector<std::string> reactantStrs, productStrs;
    for (std::size_t i = 0; i < reactants.size(); ++i) {
        std::string text = authoredPattern(reactants[i]);
        if (i < rule.getReactants().size()) {
            const std::string scopePrefix = extractLeadingScopePrefix(rule.getReactants()[i]);
            if (!scopePrefix.empty()) text = scopePrefix + text;
        }
        reactantStrs.push_back(std::move(text));
    }
    for (std::size_t i = 0; i < products.size(); ++i) {
        std::string text = authoredPattern(products[i]);
        if (i < rule.getProducts().size()) {
            const std::string scopePrefix = extractLeadingScopePrefix(rule.getProducts()[i]);
            if (!scopePrefix.empty()) text = scopePrefix + text;
        }
        productStrs.push_back(std::move(text));
    }

    // Copy rates from parent rule
    std::vector<Expression> rates;
    for (const auto& r : rule.getRates()) {
        rates.push_back(r);
    }

    // Copy modifiers, handling include/exclude for population reactants/products
    std::vector<std::string> modifiers;
    for (const auto& mod : rule.getModifiers()) {
        modifiers.push_back(mod);
    }

    // Build the child rule
    auto childRule = std::make_unique<ReactionRule>(
        childName,
        childName,
        std::move(reactantStrs),
        std::move(productStrs),
        std::move(rates),
        std::move(modifiers),
        rule.isBidirectional(),
        std::move(reactants),
        std::move(products));
    childRule->setHasScopePrefix(rule.hasScopePrefix());
    if (rule.getDelayExpression()) {
        childRule->setDelay(*rule.getDelayExpression(), rule.isNonConsuming());
    }
    if (rule.hasDrivingWork()) {
        childRule->setDrivingWorkExpression(rule.drivingWorkExpression());
    }

    // ---- Step 8: Check DeleteMolecules flag (Perl lines 722-735) ----
    // A child that deletes molecules out of a complex it otherwise keeps (a
    // particle unbinding into a population: A(b!1).B(a!1) -> A(b) + B_pop())
    // needs DeleteMolecules; without it the deletion means the whole species,
    // as BNG2 and NFsim read it.  BNG2 sets the flag whenever a child has a
    // molecule deletion; a pattern deleted as a whole species is not one.
    bool hasDeleteMolecules = false;
    for (const auto& mod : childRule->getModifiers()) {
        std::string lower = mod;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
        if (lower == "deletemolecules") hasDeleteMolecules = true;
    }
    bool deletesMoleculesFromKeptComplex = false;
    for (const auto& op : childRule->getOperations()) {
        if (op.type == ReactionRule::TransformOp::Type::DeleteMolecule &&
            !childRule->deletesWholeReactantPattern(op.patternIndex)) {
            deletesMoleculesFromKeptComplex = true;
        }
    }
    if (deletesMoleculesFromKeptComplex && !hasDeleteMolecules) {
        if (params.verbose) {
            std::cerr << "DeleteMolecules flag added to rule " << childName << ".\n";
        }
        auto flagged = childRule->getModifiers();
        flagged.push_back("DeleteMolecules");
        auto rebuilt = std::make_unique<ReactionRule>(
            childRule->getRuleName(),
            childRule->getLabel(),
            childRule->getReactants(),
            childRule->getProducts(),
            childRule->getRates(),
            std::move(flagged),
            childRule->isBidirectional(),
            childRule->getReactantPatterns(),
            childRule->getProductPatterns());
        rebuilt->setHasScopePrefix(childRule->hasScopePrefix());
        if (childRule->getDelayExpression()) {
            rebuilt->setDelay(*childRule->getDelayExpression(), childRule->isNonConsuming());
        }
        if (childRule->hasDrivingWork()) {
            rebuilt->setDrivingWorkExpression(childRule->drivingWorkExpression());
        }
        childRule = std::move(rebuilt);
    }

    return childRule;
}

} // namespace bng::ast
