#include "PatternDescriptor.hpp"

#include "ast/SpeciesGraph.hpp"
#include "core/BNGcore.hpp"

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>

namespace bng::compile {
namespace {

std::string trim(std::string value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) {
        return {};
    }
    const auto last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

std::vector<std::string> splitMolecules(std::string_view text) {
    std::vector<std::string> result;
    std::size_t start = 0;
    int depth = 0;
    for (std::size_t i = 0; i < text.size(); ++i) {
        if (text[i] == '(') {
            ++depth;
        } else if (text[i] == ')') {
            --depth;
            if (depth < 0) {
                throw std::invalid_argument("unbalanced pattern parentheses");
            }
        } else if (text[i] == '.' && depth == 0) {
            result.push_back(trim(std::string(text.substr(start, i - start))));
            start = i + 1;
        }
    }
    if (depth != 0) {
        throw std::invalid_argument("unbalanced pattern parentheses");
    }
    result.push_back(trim(std::string(text.substr(start))));
    result.erase(std::remove_if(result.begin(), result.end(),
                                [](const std::string& item) { return item.empty(); }),
                 result.end());
    return result;
}

bool isDelimiter(char c) {
    return c == '~' || c == '!' || c == '%' || c == ',' ||
           c == ')' || std::isspace(static_cast<unsigned char>(c));
}

BondConstraintKind classifyBondConstraint(std::string_view constraint) {
    if (constraint.empty()) return BondConstraintKind::Unspecified;
    if (constraint == "-") return BondConstraintKind::Unbound;
    if (constraint == "+") return BondConstraintKind::Bound;
    if (constraint == "?") return BondConstraintKind::Any;
    return BondConstraintKind::Exact;
}

PatternMoleculeDescriptor parseMolecule(std::string moleculeText) {
    moleculeText = trim(std::move(moleculeText));
    PatternMoleculeDescriptor molecule;
    if (moleculeText.empty()) {
        throw std::invalid_argument("empty molecule pattern");
    }

    const auto open = moleculeText.find('(');
    const auto firstAt = moleculeText.find('@');
    const auto nameEnd = std::min(open == std::string::npos ? moleculeText.size() : open,
                                  firstAt == std::string::npos ? moleculeText.size() : firstAt);
    molecule.moleculeType = trim(moleculeText.substr(0, nameEnd));
    if (molecule.moleculeType.empty()) {
        throw std::invalid_argument("molecule pattern has no type name");
    }

    std::size_t cursor = nameEnd;
    if (cursor < moleculeText.size() && moleculeText[cursor] == '@') {
        const auto compStart = ++cursor;
        while (cursor < moleculeText.size() && moleculeText[cursor] != '(' &&
               !std::isspace(static_cast<unsigned char>(moleculeText[cursor]))) {
            ++cursor;
        }
        molecule.compartment = moleculeText.substr(compStart, cursor - compStart);
    }

    const auto componentOpen = moleculeText.find('(', cursor);
    if (componentOpen == std::string::npos) {
        return molecule;
    }
    const auto componentClose = moleculeText.rfind(')');
    if (componentClose == std::string::npos || componentClose < componentOpen) {
        throw std::invalid_argument("molecule pattern has malformed component list");
    }

    const auto componentText = moleculeText.substr(componentOpen + 1,
                                                    componentClose - componentOpen - 1);
    std::size_t start = 0;
    for (std::size_t i = 0; i <= componentText.size(); ++i) {
        if (i != componentText.size() && componentText[i] != ',') {
            continue;
        }
        auto siteText = trim(componentText.substr(start, i - start));
        start = i + 1;
        if (siteText.empty()) {
            continue;
        }

        PatternSiteDescriptor site;
        std::size_t pos = 0;
        while (pos < siteText.size() && !isDelimiter(siteText[pos])) {
            ++pos;
        }
        site.componentName = siteText.substr(0, pos);
        if (site.componentName.empty()) {
            throw std::invalid_argument("component pattern has no name");
        }
        while (pos < siteText.size()) {
            const char marker = siteText[pos++];
            if (marker == '~') {
                const auto valueStart = pos;
                while (pos < siteText.size() && !isDelimiter(siteText[pos])) {
                    ++pos;
                }
                site.stateConstraint = siteText.substr(valueStart, pos - valueStart);
            } else if (marker == '!') {
                const auto valueStart = pos;
                while (pos < siteText.size() && !isDelimiter(siteText[pos])) {
                    ++pos;
                }
                PatternBondDescriptor bond;
                bond.constraint = siteText.substr(valueStart, pos - valueStart);
                if (bond.constraint.empty()) {
                    bond.constraint = "-";
                }
                bond.kind = classifyBondConstraint(bond.constraint);
                site.bondConstraints.push_back(std::move(bond));
            } else if (marker == '%') {
                const auto valueStart = pos;
                while (pos < siteText.size() && !isDelimiter(siteText[pos])) {
                    ++pos;
                }
                site.label = siteText.substr(valueStart, pos - valueStart);
            } else if (!std::isspace(static_cast<unsigned char>(marker))) {
                throw std::invalid_argument("unrecognized component constraint");
            }
        }
        molecule.sites.push_back(std::move(site));
    }

    const auto suffixAt = moleculeText.find('@', componentClose + 1);
    if (suffixAt != std::string::npos) {
        molecule.compartment = trim(moleculeText.substr(suffixAt + 1));
    }
    return molecule;
}

bool isBondNode(const BNGcore::Node& node) {
    return node.get_type().get_type_name() == BNGcore::BOND_NODE_TYPE.get_type_name();
}

std::vector<const BNGcore::Node*> nonBondNeighbors(const BNGcore::Node& node) {
    std::vector<const BNGcore::Node*> neighbors;
    for (auto edge = node.edges_in_begin(); edge != node.edges_in_end(); ++edge) {
        if (!isBondNode(**edge)) {
            neighbors.push_back(*edge);
        }
    }
    for (auto edge = node.edges_out_begin(); edge != node.edges_out_end(); ++edge) {
        if (!isBondNode(**edge) &&
            std::find(neighbors.begin(), neighbors.end(), *edge) == neighbors.end()) {
            neighbors.push_back(*edge);
        }
    }
    return neighbors;
}

bool isMoleculeNode(const BNGcore::Node& node) {
    // PatternGraphBuilder directs molecule -> component edges.  A molecule
    // therefore has no incoming non-bond entity edge; this also handles a
    // molecule with no components.
    for (auto edge = node.edges_in_begin(); edge != node.edges_in_end(); ++edge) {
        if (!isBondNode(**edge)) {
            return false;
        }
    }
    return !isBondNode(node);
}

std::vector<const BNGcore::Node*> allBonds(const BNGcore::Node& component) {
    std::vector<const BNGcore::Node*> bonds;
    for (auto edge = component.edges_in_begin(); edge != component.edges_in_end(); ++edge) {
        if (isBondNode(**edge)) {
            bonds.push_back(*edge);
        }
    }
    for (auto edge = component.edges_out_begin(); edge != component.edges_out_end(); ++edge) {
        if (isBondNode(**edge) &&
            std::find(bonds.begin(), bonds.end(), *edge) == bonds.end()) {
            bonds.push_back(*edge);
        }
    }
    return bonds;
}

std::string componentState(const BNGcore::Node& component) {
    const auto encoded = component.get_state().get_BNG2_string();
    if (!encoded.empty() && encoded.front() == '~') {
        return encoded.substr(1);
    }
    return encoded;
}

} // namespace

Pattern Pattern::parse(std::string_view text) {
    Pattern result;
    result.sourceText_ = trim(std::string(text));
    std::unordered_map<std::string, PatternBondGroupId> bondGroups;
    std::size_t nextBondGroup = 1;
    for (auto& molecule : splitMolecules(result.sourceText_)) {
        auto descriptor = parseMolecule(std::move(molecule));
        descriptor.occurrence.value = result.molecules_.size();
        for (std::size_t siteIndex = 0; siteIndex < descriptor.sites.size(); ++siteIndex) {
            auto& site = descriptor.sites[siteIndex];
            site.occurrence.value = siteIndex;
            for (auto& bond : site.bondConstraints) {
                if (bond.kind != BondConstraintKind::Exact) continue;
                auto [it, inserted] = bondGroups.emplace(
                    bond.constraint, PatternBondGroupId{nextBondGroup});
                if (inserted) ++nextBondGroup;
                bond.group = it->second;
            }
            if (!site.bondConstraints.empty()) {
                const auto& firstBond = site.bondConstraints.front();
                site.bondConstraint = firstBond.constraint;
                site.bondKind = firstBond.kind;
                site.bondGroup = firstBond.group;
            }
        }
        result.molecules_.push_back(std::move(descriptor));
    }
    return result;
}

Pattern Pattern::fromPatternGraph(const BNGcore::PatternGraph& graph,
                                   std::string_view compartment) {
    Pattern result;
    result.compartment_ = std::string(compartment);

    std::unordered_map<const BNGcore::Node*, PatternBondGroupId> bondGroups;
    int nextBond = 1;
    for (auto node = graph.begin(); node != graph.end(); ++node) {
        if (isBondNode(**node) && (**node).get_state().get_label() ==
            BNGcore::BOUND_STATE.get_label()) {
            bondGroups[*node] = PatternBondGroupId{static_cast<std::size_t>(nextBond++)};
        }
    }

    for (auto node = graph.begin(); node != graph.end(); ++node) {
        if (!isMoleculeNode(**node)) {
            continue;
        }
        PatternMoleculeDescriptor molecule;
        molecule.occurrence.value = result.molecules_.size();
        molecule.moleculeType = (**node).get_type().get_type_name();
        molecule.compartment = (**node).get_compartment();

        for (const auto* neighbor : nonBondNeighbors(**node)) {
            PatternSiteDescriptor site;
            site.occurrence.value = molecule.sites.size();
            site.componentName = neighbor->get_type().get_type_name();
            site.stateConstraint = componentState(*neighbor);
            site.label = neighbor->get_label_tag();
            for (const auto* bond : allBonds(*neighbor)) {
                PatternBondDescriptor bondDescriptor;
                const auto bondState = bond->get_state().get_label();
                if (bondState == BNGcore::BOUND_STATE.get_label()) {
                    std::size_t endpointCount = 0;
                    for (auto edge = bond->edges_in_begin();
                         edge != bond->edges_in_end(); ++edge) {
                        if (!isBondNode(**edge)) ++endpointCount;
                    }
                    for (auto edge = bond->edges_out_begin();
                         edge != bond->edges_out_end(); ++edge) {
                        if (!isBondNode(**edge)) ++endpointCount;
                    }
                    if (endpointCount == 1) {
                        bondDescriptor.kind = BondConstraintKind::Bound;
                        bondDescriptor.constraint = "+";
                    } else {
                        bondDescriptor.kind = BondConstraintKind::Exact;
                        bondDescriptor.group = bondGroups.at(bond);
                        bondDescriptor.constraint =
                            std::to_string(bondDescriptor.group.value);
                    }
                } else if (bondState == BNGcore::UNBOUND_STATE.get_label()) {
                    bondDescriptor.kind = BondConstraintKind::Unbound;
                    bondDescriptor.constraint = "-";
                } else {
                    bondDescriptor.kind = BondConstraintKind::Any;
                    bondDescriptor.constraint = "?";
                }
                site.bondConstraints.push_back(std::move(bondDescriptor));
            }
            if (!site.bondConstraints.empty()) {
                const auto& firstBond = site.bondConstraints.front();
                site.bondKind = firstBond.kind;
                site.bondConstraint = firstBond.constraint;
                site.bondGroup = firstBond.group;
            }
            molecule.sites.push_back(std::move(site));
        }
        result.molecules_.push_back(std::move(molecule));
    }
    return result;
}

Pattern Pattern::fromSpeciesGraph(const ast::SpeciesGraph& graph) {
    auto result = fromPatternGraph(graph.getGraph(), graph.getCompartment());
    result.sourceText_ = graph.toString();
    return result;
}

bool Pattern::semanticEqual(const Pattern& other) const noexcept {
    if (molecules_.size() != other.molecules_.size()) {
        return false;
    }

    // Exact bond numbers are syntax, not identity. Normalize each group's
    // first occurrence while comparing so !1 and !17 remain equivalent.
    using GroupMap = std::unordered_map<std::size_t, std::size_t>;
    const auto bondList = [](const PatternSiteDescriptor& site) {
        if (!site.bondConstraints.empty()) return site.bondConstraints;
        return std::vector<PatternBondDescriptor>{
            {site.bondConstraint, site.bondKind, site.bondGroup}};
    };
    const auto normalizedKind = [](BondConstraintKind kind) {
        return kind == BondConstraintKind::Unspecified
                   ? BondConstraintKind::Unbound
                   : kind;
    };
    const auto normalizedGroup = [](const PatternBondDescriptor& bond,
                                    GroupMap& groups) {
        if (bond.kind != BondConstraintKind::Exact) return std::size_t{0};
        const auto [it, inserted] = groups.emplace(bond.group.value,
                                                    groups.size() + 1);
        return it->second;
    };

    GroupMap leftGroups;
    GroupMap rightGroups;
    for (std::size_t moleculeIndex = 0; moleculeIndex < molecules_.size();
         ++moleculeIndex) {
        const auto& left = molecules_[moleculeIndex];
        const auto& right = other.molecules_[moleculeIndex];
        const auto effectiveCompartment = [&](const PatternMoleculeDescriptor& molecule,
                                              const Pattern& pattern) {
            return molecule.compartment.empty() ? pattern.compartment_ : molecule.compartment;
        };
        if (left.moleculeType != right.moleculeType ||
            effectiveCompartment(left, *this) != effectiveCompartment(right, other) ||
            left.sites.size() != right.sites.size()) {
            return false;
        }
        for (std::size_t siteIndex = 0; siteIndex < left.sites.size(); ++siteIndex) {
            const auto& leftSite = left.sites[siteIndex];
            const auto& rightSite = right.sites[siteIndex];
            const auto leftSiteBonds = bondList(leftSite);
            const auto rightSiteBonds = bondList(rightSite);
            if (leftSiteBonds.size() != rightSiteBonds.size()) return false;
            if (leftSite.componentName != rightSite.componentName ||
                leftSite.stateConstraint != rightSite.stateConstraint ||
                leftSite.label != rightSite.label) {
                return false;
            }
            for (std::size_t bondIndex = 0; bondIndex < leftSiteBonds.size();
                 ++bondIndex) {
                const auto& leftBond = leftSiteBonds[bondIndex];
                const auto& rightBond = rightSiteBonds[bondIndex];
                if (normalizedKind(leftBond.kind) != normalizedKind(rightBond.kind) ||
                    normalizedGroup(leftBond, leftGroups) !=
                        normalizedGroup(rightBond, rightGroups)) {
                    return false;
                }
            }
        }
    }
    return leftGroups.size() == rightGroups.size();
}

bool Pattern::hasSite(std::string_view moleculeType,
                      std::string_view componentName) const noexcept {
    return std::any_of(molecules_.begin(), molecules_.end(), [&](const auto& molecule) {
        if (molecule.moleculeType != moleculeType) {
            return false;
        }
        return std::any_of(molecule.sites.begin(), molecule.sites.end(),
                           [&](const auto& site) { return site.componentName == componentName; });
    });
}

std::string Pattern::stateConstraint(std::string_view moleculeType,
                                     std::string_view componentName) const {
    for (const auto& molecule : molecules_) {
        if (molecule.moleculeType != moleculeType) {
            continue;
        }
        for (const auto& site : molecule.sites) {
            if (site.componentName == componentName) {
                return site.stateConstraint;
            }
        }
    }
    return {};
}

} // namespace bng::compile
