#include "ContactMapWriter.hpp"

#include <sstream>
#include <algorithm>
#include <set>
#include <tuple>

#include "compile/Document.hpp"

namespace bng::io {

namespace {

using ContactKey = std::tuple<std::string, std::string, std::string, std::string>;

ContactKey canonicalContact(std::string mol1, std::string comp1,
                            std::string mol2, std::string comp2) {
    if (std::tie(mol2, comp2) < std::tie(mol1, comp1)) {
        std::swap(mol1, mol2);
        std::swap(comp1, comp2);
    }
    return {std::move(mol1), std::move(comp1), std::move(mol2), std::move(comp2)};
}

void collectPatternContacts(const compile::Pattern& pattern, std::set<ContactKey>& contacts) {
    struct Endpoint { std::string molecule; std::string component; };
    std::map<std::size_t, std::vector<Endpoint>> groups;
    for (const auto& molecule : pattern.molecules()) {
        for (const auto& site : molecule.sites) {
            const auto add = [&](compile::BondConstraintKind kind,
                                 compile::PatternBondGroupId group) {
                if (kind == compile::BondConstraintKind::Exact)
                    groups[group.value].push_back({molecule.moleculeType, site.componentName});
            };
            if (site.bondConstraints.empty()) add(site.bondKind, site.bondGroup);
            else for (const auto& bond : site.bondConstraints) add(bond.kind, bond.group);
        }
    }
    for (const auto& [group, endpoints] : groups) {
        (void)group;
        if (endpoints.size() != 2) continue;
        contacts.insert(canonicalContact(endpoints[0].molecule, endpoints[0].component,
                                         endpoints[1].molecule, endpoints[1].component));
    }
}

const compile::PatternSiteDescriptor* siteForRef(
    const compile::CompiledRuleDirection& direction,
    const compile::PatternSiteRef& ref,
    const compile::PatternMoleculeDescriptor** moleculeOut) {
    const auto& patterns = ref.side == compile::PatternSide::Reactant
        ? direction.reactantPatterns : direction.productPatterns;
    if (ref.patternIndex >= patterns.size()) return nullptr;
    const auto& molecules = patterns[ref.patternIndex].molecules();
    if (ref.moleculeIndex >= molecules.size()) return nullptr;
    const auto& molecule = molecules[ref.moleculeIndex];
    if (ref.siteIndex >= molecule.sites.size()) return nullptr;
    if (moleculeOut) *moleculeOut = &molecule;
    return &molecule.sites[ref.siteIndex];
}

void collectMutationContacts(const compile::CompiledRuleDirection& direction,
                             std::set<ContactKey>& contacts) {
    for (const auto& mutation : direction.mutations) {
        if (mutation.kind != compile::MutationKind::AddBond) continue;
        const compile::PatternMoleculeDescriptor* leftMol = nullptr;
        const compile::PatternMoleculeDescriptor* rightMol = nullptr;
        const auto* left = siteForRef(direction, mutation.source, &leftMol);
        const auto* right = siteForRef(direction, mutation.partner, &rightMol);
        if (!left || !right || !leftMol || !rightMol) continue;
        contacts.insert(canonicalContact(leftMol->moleculeType, left->componentName,
                                         rightMol->moleculeType, right->componentName));
    }
}

} // namespace

ContactMapWriter::ContactMap ContactMapWriter::buildContactMap(
    const compile::CompiledModel& model) {
    ContactMap map;
    for (const auto& molecule : model.moleculeTypes()) map.moleculeTypes.insert(molecule.name);

    std::set<ContactKey> contacts;
    for (const auto& rule : model.rules()) {
        for (const auto& pattern : rule.forward().reactantPatterns) collectPatternContacts(pattern, contacts);
        for (const auto& pattern : rule.forward().productPatterns) collectPatternContacts(pattern, contacts);
        collectMutationContacts(rule.forward(), contacts);
        if (rule.reverse().has_value()) {
            for (const auto& pattern : rule.reverse()->reactantPatterns) collectPatternContacts(pattern, contacts);
            for (const auto& pattern : rule.reverse()->productPatterns) collectPatternContacts(pattern, contacts);
            collectMutationContacts(*rule.reverse(), contacts);
        }
    }
    for (const auto& [mol1, comp1, mol2, comp2] : contacts)
        map.edges.push_back(Edge{mol1, mol2, comp1, comp2});
    return map;
}

ContactMapWriter::ContactMap ContactMapWriter::buildContactMap(const ast::Model& model) {
    compile::Document document(model);
    if (!document.valid())
        throw std::runtime_error("cannot build contact map from invalid compiled model");
    return buildContactMap(document.model());
}

std::string ContactMapWriter::toGML(const ContactMap& contactMap) {
    std::ostringstream gml;

    gml << "graph [\n";
    gml << "  directed 0\n";

    // Write nodes
    int nodeId = 0;
    std::map<std::string, int> nodeIds;
    for (const auto& molType : contactMap.moleculeTypes) {
        gml << "  node [\n";
        gml << "    id " << nodeId << "\n";
        gml << "    label \"" << molType << "\"\n";
        gml << "  ]\n";
        nodeIds[molType] = nodeId++;
    }

    // Write edges
    for (const auto& edge : contactMap.edges) {
        gml << "  edge [\n";
        gml << "    source " << nodeIds[edge.mol1] << "\n";
        gml << "    target " << nodeIds[edge.mol2] << "\n";
        gml << "    label \"" << edge.comp1 << "--" << edge.comp2 << "\"\n";
        gml << "  ]\n";
    }

    gml << "]\n";
    return gml.str();
}

std::string ContactMapWriter::toDOT(const ContactMap& contactMap) {
    std::ostringstream dot;

    dot << "graph ContactMap {\n";
    dot << "  node [shape=box];\n\n";

    // Write nodes
    for (const auto& molType : contactMap.moleculeTypes) {
        dot << "  \"" << molType << "\";\n";
    }

    dot << "\n";

    // Write edges
    for (const auto& edge : contactMap.edges) {
        dot << "  \"" << edge.mol1 << "\" -- \"" << edge.mol2
            << "\" [label=\"" << edge.comp1 << "--" << edge.comp2 << "\"];\n";
    }

    dot << "}\n";
    return dot.str();
}

} // namespace bng::io
