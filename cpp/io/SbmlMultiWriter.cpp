#include "SbmlMultiWriter.hpp"

#include "EnergyExportGuard.hpp"

#include <algorithm>
#include <iomanip>
#include <sstream>
#include <cctype>
#include <stdexcept>
#include <utility>

#include "compile/CompiledModel.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/DelayedSemanticsGuard.hpp"
#include "SbmlUnitWriter.hpp"
#include "SbmlWriter.hpp"
#include "compile/TotalRate.hpp"
#include "compile/Pattern.hpp"
#include <map>
#include <set>

namespace bng::io {

namespace {
using MultiPattern = bng::compile::Pattern;
using BondKind = bng::compile::BondConstraintKind;

const bng::ast::MoleculeType& multiMoleculeType(
    const bng::ast::Model& model, const std::string& name) {
    for (const auto& type : model.getMoleculeTypes()) {
        if (type.getName() == name) return type;
    }
    throw std::invalid_argument("SBML-Multi pattern references unknown molecule type " + name);
}

std::vector<std::size_t> multiComponentIndexes(
    const bng::ast::Model& model,
    const bng::compile::PatternMoleculeDescriptor& molecule) {
    const auto& components = multiMoleculeType(model, molecule.moleculeType).getComponents();
    std::vector<std::size_t> result;
    for (const auto& site : molecule.sites) {
        std::size_t index = 0;
        while (index < components.size() &&
               (components[index].name != site.componentName ||
                std::find(result.begin(), result.end(), index) != result.end())) ++index;
        if (index == components.size()) {
            throw std::invalid_argument("SBML-Multi pattern has an unknown component " + site.componentName);
        }
        result.push_back(index);
    }
    return result;
}

std::string multiTypeId(const MultiPattern& pattern, const std::string& id) {
    return pattern.moleculeCount() == 1
        ? "st_" + pattern.molecules().front().moleculeType : "st_" + id;
}

std::string multiComponentId(const std::string& type, std::size_t molecule,
                             std::size_t component, bool complex) {
    return complex
        ? type + "_M" + std::to_string(molecule + 1) + "_C" + std::to_string(component + 1)
        : type + "_component_" + std::to_string(component + 1);
}

// SBML Multi species below are amount-valued. An elementary BNGL rule with m
// reactant patterns in one compartment has extent flux k * product(n_i) / V^(m-1).
// Keep that volume factor in the exported kinetic law, not just the source
// BNGL simulator. Multi-compartment encounter geometry needs a separate
// lowering and must not be silently treated as a single-compartment rule.
std::string multiMassActionVolume(const bng::ast::Model& model,
                                  const std::vector<std::string>& reactants) {
    if (reactants.size() < 2 || model.getCompartments().empty()) return {};
    std::string common;
    for (const auto& text : reactants) {
        const auto pattern = MultiPattern::parse(text);
        for (const auto& molecule : pattern.molecules()) {
            const auto compartment = molecule.compartment.empty()
                ? pattern.compartment() : molecule.compartment;
            if (compartment.empty()) {
                return {};
            }
            if (!common.empty() && compartment != common) {
                throw std::invalid_argument(
                    "SBML-Multi mass-action volume cannot use one compartment for mixed reactants");
            }
            common = compartment;
        }
    }
    if (std::none_of(model.getCompartments().begin(), model.getCompartments().end(),
                     [&](const auto& compartment) { return compartment.getName() == common; })) {
        throw std::invalid_argument(
            "SBML-Multi mass-action volume references an undeclared compartment");
    }
    return common;
}

std::string multiObservableSpeciesId(std::size_t observable, std::size_t pattern) {
    return "O" + std::to_string(observable + 1) + "_P" + std::to_string(pattern + 1);
}

// A stoichiometry or count comparison (R==1, A()>5) is not a species pattern.
bool multiObservablePatternSupported(const std::string& text) {
    if (text.find_first_of("<>=") != std::string::npos) return false;
    try {
        return MultiPattern::parse(text).moleculeCount() > 0;
    } catch (const std::exception&) {
        return false;
    }
}

// The species each observable sums.  A pattern written exactly like a seed
// species or a rule pattern refers to that species, as BNG2's species set
// (keyed by the exact pattern string) does; any other pattern adds a species.
struct MultiObservableSpecies {
    std::vector<std::vector<std::string>> terms;              // per observable
    std::vector<std::pair<std::string, std::string>> added;   // (text, id)
};

std::string multiPatternIdentityKey(const bng::ast::Model& model,
                                    const std::string& pattern) {
    const auto key = [](const bng::ast::SpeciesGraph& graph,
                        const std::string& compartment,
                        bool compartmentPrefix) {
        return graph.canonicalLabel() + "|graph=" +
               graph.getGraph().get_BNG2_string_with_compartments() +
               "|compartment=" + compartment +
               "|prefix=" + (compartmentPrefix ? "1" : "0");
    };
    for (const auto& seed : model.getSeedSpecies()) {
        if (seed.getPattern() == pattern) {
            return key(bng::ast::SpeciesGraph(seed.getGraph()), seed.getCompartment(), false);
        }
    }
    for (const auto& rule : model.getReactionRules()) {
        const auto find = [&](const std::vector<std::string>& texts,
                              const std::vector<bng::ast::SpeciesGraph>& graphs)
            -> std::optional<std::string> {
            for (std::size_t index = 0; index < texts.size() && index < graphs.size(); ++index) {
                if (texts[index] == pattern) {
                    return key(graphs[index], graphs[index].getCompartment(),
                               graphs[index].isCompartmentPrefix());
                }
            }
            return std::nullopt;
        };
        if (const auto found = find(rule.getReactants(), rule.getReactantPatterns())) return *found;
        if (const auto found = find(rule.getProducts(), rule.getProductPatterns())) return *found;
    }
    return "text=" + pattern;
}

std::string multiPatternSpeciesId(const bng::ast::Model& model,
                                  const std::string& pattern,
                                  const std::string& fallback) {
    const auto identity = multiPatternIdentityKey(model, pattern);
    for (std::size_t index = 0; index < model.getSeedSpecies().size(); ++index) {
        if (multiPatternIdentityKey(model, model.getSeedSpecies()[index].getPattern()) == identity) {
            return "S" + std::to_string(index + 1);
        }
    }
    for (std::size_t index = 0; index < model.getReactionRules().size(); ++index) {
        const auto& rule = model.getReactionRules()[index];
        const auto prefix = "RR" + std::to_string(index + 1);
        for (std::size_t p = 0; p < rule.getReactants().size(); ++p) {
            if (multiPatternIdentityKey(model, rule.getReactants()[p]) == identity) {
                return prefix + "_R" + std::to_string(p + 1);
            }
        }
        for (std::size_t p = 0; p < rule.getProducts().size(); ++p) {
            if (multiPatternIdentityKey(model, rule.getProducts()[p]) == identity) {
                return prefix + "_P" + std::to_string(p + 1);
            }
        }
    }
    return fallback;
}

MultiObservableSpecies multiObservableSpecies(const bng::ast::Model& model) {
    std::map<std::string, std::string> known;
    for (std::size_t index = 0; index < model.getSeedSpecies().size(); ++index) {
        known.emplace(multiPatternIdentityKey(model, model.getSeedSpecies()[index].getPattern()),
                      "S" + std::to_string(index + 1));
    }
    for (std::size_t index = 0; index < model.getReactionRules().size(); ++index) {
        const auto& rule = model.getReactionRules()[index];
        const auto prefix = "RR" + std::to_string(index + 1);
        for (std::size_t p = 0; p < rule.getReactants().size(); ++p) {
            known.emplace(multiPatternIdentityKey(model, rule.getReactants()[p]),
                          prefix + "_R" + std::to_string(p + 1));
        }
        for (std::size_t p = 0; p < rule.getProducts().size(); ++p) {
            known.emplace(multiPatternIdentityKey(model, rule.getProducts()[p]),
                          prefix + "_P" + std::to_string(p + 1));
        }
    }
    MultiObservableSpecies result;
    for (std::size_t index = 0; index < model.getObservables().size(); ++index) {
        const auto& patterns = model.getObservables()[index].getPatterns();
        std::vector<std::string> terms;
        for (std::size_t p = 0; p < patterns.size(); ++p) {
            if (!multiObservablePatternSupported(patterns[p])) continue;
            const auto identity = multiPatternIdentityKey(model, patterns[p]);
            auto found = known.find(identity);
            if (found == known.end()) {
                const auto id = multiObservableSpeciesId(index, p);
                found = known.emplace(identity, id).first;
                result.added.emplace_back(patterns[p], id);
            }
            terms.push_back(found->second);
        }
        result.terms.push_back(std::move(terms));
    }
    return result;
}

// Every pattern location has a stable species object. Reverse directions reuse
// those objects, so component maps can refer to the same structural types.
template<class Visitor>
void visitMultiPatterns(const bng::ast::Model& model, Visitor visit) {
    std::set<std::string> visited;
    const auto visitUnique = [&](const std::string& text, const std::string& id) {
        if (visited.insert(multiPatternIdentityKey(model, text)).second) visit(text, id);
    };
    for (std::size_t index = 0; index < model.getSeedSpecies().size(); ++index) {
        visitUnique(model.getSeedSpecies()[index].getPattern(), "S" + std::to_string(index + 1));
    }
    for (std::size_t index = 0; index < model.getReactionRules().size(); ++index) {
        const auto& rule = model.getReactionRules()[index];
        const auto prefix = "RR" + std::to_string(index + 1);
        for (std::size_t p = 0; p < rule.getReactants().size(); ++p) {
            visitUnique(rule.getReactants()[p], prefix + "_R" + std::to_string(p + 1));
        }
        for (std::size_t p = 0; p < rule.getProducts().size(); ++p) {
            visitUnique(rule.getProducts()[p], prefix + "_P" + std::to_string(p + 1));
        }
    }
    // Observable patterns are species too: an SBML-Multi species that leaves
    // sites unspecified stands for every species it matches, and BNG2 sums
    // those pattern species in each observable's assignment rule
    // (BNGOutput.pm writeSBMLMulti, "Assignment rules (for observables)").
    for (const auto& [text, id] : multiObservableSpecies(model).added) visitUnique(text, id);
}
// The components that take part in a bond somewhere in the model (an exact
// bond, !+ or !?), by molecule type and component name.  BNG2 calls them the
// binding components (SBMLMultiAux.pm extractBindingComponents); a binding
// component that also has states is a binding-site species type carrying its
// own species feature type (ComponentType.pm toSBMLMultiSpeciesTypeBinding).
std::map<std::string, std::set<std::string>> multiBindingComponents(
    const bng::ast::Model& model) {
    std::map<std::string, std::set<std::string>> binding;
    visitMultiPatterns(model, [&](const std::string& text, const std::string&) {
        const auto pattern = MultiPattern::parse(text);
        for (const auto& molecule : pattern.molecules()) {
            for (const auto& site : molecule.sites) {
                if (site.bondKind == BondKind::Exact || site.bondKind == BondKind::Bound ||
                    site.bondKind == BondKind::Any) {
                    binding[molecule.moleculeType].insert(site.componentName);
                }
            }
        }
    });
    return binding;
}

// A component is a binding site when it has no states (a pure binding site)
// or when it has states and binds somewhere in the model.
bool isMultiBindingSite(const std::map<std::string, std::set<std::string>>& binding,
                        const std::string& moleculeType,
                        const bng::ast::ComponentType& component) {
    if (component.allowedStates.empty()) return true;
    const auto found = binding.find(moleculeType);
    return found != binding.end() && found->second.count(component.name) != 0;
}

std::string multiBindingSiteId(const std::string& validMolecule,
                               const std::string& validComponent, std::size_t index) {
    return "bst_" + validMolecule + "_" + validComponent + "_" + std::to_string(index + 1);
}

std::string multiValidId(const std::string& text) {
    std::string result;
    bool first = true;
    for (char c : text) {
        if (std::isalnum(static_cast<unsigned char>(c)) || c == '_') {
            result += c;
            first = false;
        } else if (!first) {
            result += '_';
        }
    }
    if (!result.empty() && std::isdigit(static_cast<unsigned char>(result.front()))) result.insert(0, "_");
    return result.empty() ? "species" : result;
}

std::vector<bool> multiRoleClonedMolecules(const bng::ast::Model& model,
                                           const MultiPattern& pattern) {
    std::vector<bool> cloned(pattern.moleculeCount(), false);
    std::map<std::size_t, std::vector<std::pair<std::size_t, std::size_t>>> bonds;
    for (std::size_t m = 0; m < pattern.moleculeCount(); ++m) {
        const auto& molecule = pattern.molecules()[m];
        const auto indexes = multiComponentIndexes(model, molecule);
        for (std::size_t site = 0; site < molecule.sites.size(); ++site) {
            if (molecule.sites[site].bondKind == BondKind::Exact) {
                bonds[molecule.sites[site].bondGroup.value].emplace_back(m, indexes[site]);
            }
        }
    }
    for (const auto& [group, endpoints] : bonds) {
        (void)group;
        if (endpoints.size() != 2 || endpoints[0].first == endpoints[1].first) continue;
        const auto& a = pattern.molecules()[endpoints[0].first];
        const auto& b = pattern.molecules()[endpoints[1].first];
        const auto& aComponent = multiMoleculeType(model, a.moleculeType).getComponents()[endpoints[0].second];
        const auto& bComponent = multiMoleculeType(model, b.moleculeType).getComponents()[endpoints[1].second];
        const bool sameType = multiBindingSiteId(
            multiValidId(a.moleculeType), multiValidId(aComponent.name), endpoints[0].second) ==
            multiBindingSiteId(multiValidId(b.moleculeType),
                               multiValidId(bComponent.name), endpoints[1].second);
        if (sameType) cloned[std::max(endpoints[0].first, endpoints[1].first)] = true;
    }
    return cloned;
}

std::string multiRoleSpeciesTypeId(const std::string& moleculeType,
                                   const std::string& patternType,
                                   std::size_t molecule) {
    return "st_" + multiValidId(moleculeType) + "_role_" +
           multiValidId(patternType) + "_M" + std::to_string(molecule + 1);
}

std::string multiRoleId(const std::string& base, const std::string& roleType) {
    return base + "_role_" + roleType.substr(3);
}
} // namespace

std::string SbmlMultiWriter::escapeXml(const std::string& text) {
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

std::string SbmlMultiWriter::makeValidSBMLId(const std::string& text) {
    std::string result;
    result.reserve(text.size());

    bool firstChar = true;
    for (char c : text) {
        if (std::isalnum(static_cast<unsigned char>(c))) {
            result += c;
            firstChar = false;
        } else if (c == '_') {
            result += '_';
            firstChar = false;
        } else if (!firstChar) {
            result += '_';
        }
    }

    if (!result.empty() && std::isdigit(static_cast<unsigned char>(result[0]))) {
        result = "_" + result;
    }

    return result.empty() ? "species" : result;
}

std::string SbmlMultiWriter::write(const ast::Model& model) {
    Options options;
    return write(model, options);
}

std::string SbmlMultiWriter::write(const ast::Model& model, const Options& options) {
    engine::requireNoDelayedRuleSemantics(model, "SBML-Multi export");
    requireNoEnergySemantics(model, "SBML-multi");
    compile::requireNoNativeEvents(model, "SBML-Multi export");
    const compile::CompiledModel compiled(model);
    if (sbml_units::enabled(compiled) && !model.getReactionRules().empty()) {
        throw std::invalid_argument(
            "SBML-Multi cannot preserve unit-aware reaction-rule rates because "
            "the writer emits authored rate expressions without converting them "
            "to the exported item/time basis");
    }
    std::ostringstream sbml;

    // SBML L3V1 header with Multi package namespace
    sbml << "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
    sbml << "<!-- Created by BioNetGen C++ (writeSBMLMulti) -->\n";
    sbml << "<sbml xmlns=\"http://www.sbml.org/sbml/level3/version1/core\"\n";
    sbml << "      xmlns:multi=\"http://www.sbml.org/sbml/level3/version1/multi/version1\"\n";
    sbml << "      level=\"" << options.level << "\" version=\"" << options.version
         << "\" multi:required=\"true\">\n";

    sbml << "  <model id=\"" << escapeXml(makeValidSBMLId(model.getModelName())) << "\" name=\""
         << escapeXml(model.getModelName()) << "\""
         << sbml_units::modelAttributes(compiled) << ">\n";

    // SBML Multi reuses SBML Core's unit system.  Emit the exact same Core
    // unit definitions as the flattened writer; no Multi-specific aliases
    // or conversion rules are introduced here.
    sbml << sbml_units::writeUnitDefinitions(compiled);

    // Species types (molecule types with components and states)
    sbml << writeSpeciesTypes(model);

    // Compartments
    sbml << writeCompartments(model, compiled);

    // Parameters
    sbml << writeParameters(model, compiled);

    // Seed species with multi:speciesType references
    sbml << writeSeedSpecies(model, compiled);

    // Observable projections as Core assignment rules
    sbml << writeObservableRules(model);

    // Reaction rules with pattern matching
    sbml << writeReactionRules(model);

    sbml << "  </model>\n";
    sbml << "</sbml>\n";

    return sbml.str();
}

std::string SbmlMultiWriter::writeCompartments(
    const ast::Model& model, const compile::CompiledModel& compiled) {
    std::ostringstream sbml;

    if (model.getCompartments().empty()) {
        sbml << "    <listOfCompartments>\n";
        sbml << "      <compartment id=\"default\" spatialDimensions=\"3\" "
                "size=\"1\" constant=\"true\" multi:isType=\"false\"/>\n";
        sbml << "    </listOfCompartments>\n";
        return sbml.str();
    }

    sbml << "    <listOfCompartments>\n";
    for (const auto& comp : model.getCompartments()) {
        sbml << "      <compartment id=\"" << makeValidSBMLId(comp.getName())
             << "\" name=\"" << escapeXml(comp.getName())
             << "\" spatialDimensions=\"" << comp.getDimension()
             << "\" size=\"" << comp.getVolume()
             << "\" constant=\"true\""
             << sbml_units::attribute(compiled, comp.getUnitName());

        if (!comp.getParent().empty()) {
            sbml << " outside=\"" << makeValidSBMLId(comp.getParent()) << "\"";
        }

        sbml << " multi:isType=\"false\"/>\n";
    }
    sbml << "    </listOfCompartments>\n";
    return sbml.str();
}

std::string SbmlMultiWriter::writeSpeciesTypes(const ast::Model& model) {
    std::ostringstream sbml;

    if (model.getMoleculeTypes().empty()) {
        return {};
    }

    // Multi distinguishes a bindingSiteSpeciesType from a state-bearing
    // speciesFeatureType.  Build stable binding-site type ids first so every
    // molecule component can reference the correct package object.
    const auto binding = multiBindingComponents(model);
    std::vector<std::vector<std::string>> bindingSiteIds;
    bindingSiteIds.reserve(model.getMoleculeTypes().size());
    for (const auto& molType : model.getMoleculeTypes()) {
        std::vector<std::string> ids;
        ids.reserve(molType.getComponents().size());
        for (std::size_t index = 0; index < molType.getComponents().size(); ++index) {
            const auto& component = molType.getComponents()[index];
            if (isMultiBindingSite(binding, molType.getName(), component)) {
                ids.push_back(multiBindingSiteId(makeValidSBMLId(molType.getName()),
                                                 makeValidSBMLId(component.name), index));
            } else {
                ids.emplace_back();
            }
        }
        bindingSiteIds.push_back(std::move(ids));
    }

    sbml << "    <multi:listOfSpeciesTypes>\n";

    for (std::size_t molIndex = 0; molIndex < model.getMoleculeTypes().size(); ++molIndex) {
        const auto& molType = model.getMoleculeTypes()[molIndex];
        for (std::size_t componentIndex = 0;
             componentIndex < molType.getComponents().size();
             ++componentIndex) {
            const auto& component = molType.getComponents()[componentIndex];
            const auto& bindingId = bindingSiteIds[molIndex][componentIndex];
            if (bindingId.empty()) continue;
            if (component.allowedStates.empty()) {
                sbml << "      <multi:bindingSiteSpeciesType multi:id=\""
                     << bindingId << "\" multi:name=\""
                     << escapeXml(component.name) << "\"/>\n";
                continue;
            }
            // A binding site that also has states: its states are a species
            // feature type of the binding-site species type itself.
            const std::string featureId = bindingId + "_state";
            sbml << "      <multi:bindingSiteSpeciesType multi:id=\""
                 << bindingId << "\" multi:name=\"" << escapeXml(component.name) << "\">\n"
                 << "        <multi:listOfSpeciesFeatureTypes>\n"
                 << "          <multi:speciesFeatureType multi:id=\"" << featureId
                 << "\" multi:name=\"" << escapeXml(component.name)
                 << "\" multi:occur=\"1\">\n"
                 << "            <multi:listOfPossibleSpeciesFeatureValues>\n";
            for (const auto& state : component.allowedStates) {
                sbml << "              <multi:possibleSpeciesFeatureValue multi:id=\""
                     << featureId << "_" << makeValidSBMLId(state) << "\" multi:name=\""
                     << escapeXml(state) << "\"/>\n";
            }
            sbml << "            </multi:listOfPossibleSpeciesFeatureValues>\n"
                 << "          </multi:speciesFeatureType>\n"
                 << "        </multi:listOfSpeciesFeatureTypes>\n"
                 << "      </multi:bindingSiteSpeciesType>\n";
        }
    }

    for (std::size_t molIndex = 0; molIndex < model.getMoleculeTypes().size(); ++molIndex) {
        const auto& molType = model.getMoleculeTypes()[molIndex];
        std::string stId = "st_" + makeValidSBMLId(molType.getName());
        sbml << "      <multi:speciesType multi:id=\"" << stId
             << "\" multi:name=\"" << escapeXml(molType.getName()) << "\">\n";

        // State-bearing components are represented by speciesFeatureTypes.
        bool hasStateComponents = false;
        for (std::size_t componentIndex = 0;
             componentIndex < molType.getComponents().size(); ++componentIndex) {
            hasStateComponents = hasStateComponents ||
                bindingSiteIds[molIndex][componentIndex].empty();
        }
        if (hasStateComponents) {
            sbml << "        <multi:listOfSpeciesFeatureTypes>\n";

            for (std::size_t componentIndex = 0;
                 componentIndex < molType.getComponents().size();
                 ++componentIndex) {
                const auto& component = molType.getComponents()[componentIndex];
                // Binding sites, with or without states, are instances below.
                if (!bindingSiteIds[molIndex][componentIndex].empty()) {
                    continue;
                }
                std::string compId = stId + "_" + makeValidSBMLId(component.name) +
                    "_" + std::to_string(componentIndex + 1);
                sbml << "          <multi:speciesFeatureType multi:id=\"" << compId
                     << "\" multi:name=\"" << escapeXml(component.name)
                     << "\" multi:occur=\"1\">\n";
                sbml << "            <multi:listOfPossibleSpeciesFeatureValues>\n";
                for (const auto& state : component.allowedStates) {
                    std::string stateId = compId + "_" + makeValidSBMLId(state);
                    sbml << "              <multi:possibleSpeciesFeatureValue multi:id=\""
                         << stateId << "\" multi:name=\"" << escapeXml(state) << "\"/>\n";
                }
                sbml << "            </multi:listOfPossibleSpeciesFeatureValues>\n";
                sbml << "          </multi:speciesFeatureType>\n";
            }

            sbml << "        </multi:listOfSpeciesFeatureTypes>\n";
        }

        // Binding sites are component instances of their binding-site types.
        bool hasBindingSites = false;
        for (const auto& bindingId : bindingSiteIds[molIndex]) {
            hasBindingSites = hasBindingSites || !bindingId.empty();
        }
        if (hasBindingSites) {
            sbml << "        <multi:listOfSpeciesTypeInstances>\n";
            for (std::size_t componentIndex = 0;
                 componentIndex < molType.getComponents().size();
                 ++componentIndex) {
                const auto& bindingId = bindingSiteIds[molIndex][componentIndex];
                if (bindingId.empty()) {
                    continue;
                }
                const auto& component = molType.getComponents()[componentIndex];
                sbml << "          <multi:speciesTypeInstance multi:id=\""
                     << stId << "_component_" << (componentIndex + 1)
                     << "\" multi:name=\"" << escapeXml(component.name)
                     << "\" multi:speciesType=\"" << bindingId << "\"/>\n";
            }
            sbml << "        </multi:listOfSpeciesTypeInstances>\n";
        }

        sbml << "      </multi:speciesType>\n";
    }

    // Multi requires the two ends of an InSpeciesTypeBond to resolve to
    // different BindingSiteSpeciesType objects.  When a BNGL homodimer uses
    // the same site type twice, emit a role-specific copy for the second
    // molecular instance.  Its multi:name remains the original molecule name,
    // so import reconstructs the same BNGL molecule type.
    visitMultiPatterns(model, [&](const std::string& text, const std::string& id) {
        const auto pattern = MultiPattern::parse(text);
        if (pattern.moleculeCount() < 2) return;
        const auto patternType = multiTypeId(pattern, id);
        const auto cloned = multiRoleClonedMolecules(model, pattern);
        for (std::size_t m = 0; m < cloned.size(); ++m) {
            if (!cloned[m]) continue;
            const auto& molecule = pattern.molecules()[m];
            const auto& molType = multiMoleculeType(model, molecule.moleculeType);
            const auto roleType = multiRoleSpeciesTypeId(molecule.moleculeType, patternType, m);
            const auto molIndex = static_cast<std::size_t>(
                &molType - model.getMoleculeTypes().data());
            std::vector<std::string> roleBindingIds(molType.getComponents().size());
            for (std::size_t c = 0; c < molType.getComponents().size(); ++c) {
                if (bindingSiteIds[molIndex][c].empty()) continue;
                const auto base = multiBindingSiteId(makeValidSBMLId(molecule.moleculeType),
                    makeValidSBMLId(molType.getComponents()[c].name), c);
                roleBindingIds[c] = multiRoleId(base, roleType);
                const auto& component = molType.getComponents()[c];
                if (component.allowedStates.empty()) {
                    sbml << "      <multi:bindingSiteSpeciesType multi:id=\"" << roleBindingIds[c]
                         << "\" multi:name=\"" << escapeXml(component.name) << "\"/>\n";
                } else {
                    const auto feature = roleBindingIds[c] + "_state";
                    sbml << "      <multi:bindingSiteSpeciesType multi:id=\"" << roleBindingIds[c]
                         << "\" multi:name=\"" << escapeXml(component.name) << "\">\n"
                         << "        <multi:listOfSpeciesFeatureTypes>\n"
                         << "          <multi:speciesFeatureType multi:id=\"" << feature
                         << "\" multi:name=\"" << escapeXml(component.name)
                         << "\" multi:occur=\"1\">\n"
                         << "            <multi:listOfPossibleSpeciesFeatureValues>\n";
                    for (const auto& state : component.allowedStates) {
                        sbml << "              <multi:possibleSpeciesFeatureValue multi:id=\""
                             << feature << "_" << makeValidSBMLId(state) << "\" multi:name=\""
                             << escapeXml(state) << "\"/>\n";
                    }
                    sbml << "            </multi:listOfPossibleSpeciesFeatureValues>\n"
                         << "          </multi:speciesFeatureType>\n"
                         << "        </multi:listOfSpeciesFeatureTypes>\n"
                         << "      </multi:bindingSiteSpeciesType>\n";
                }
            }
            sbml << "      <multi:speciesType multi:id=\"" << roleType << "\" multi:name=\""
                 << escapeXml(molecule.moleculeType) << "\">\n";
            bool hasFeatures = false;
            for (std::size_t c = 0; c < molType.getComponents().size(); ++c) {
                hasFeatures = hasFeatures || (roleBindingIds[c].empty() &&
                    !molType.getComponents()[c].allowedStates.empty());
            }
            if (hasFeatures) {
                sbml << "        <multi:listOfSpeciesFeatureTypes>\n";
                for (std::size_t c = 0; c < molType.getComponents().size(); ++c) {
                    const auto& component = molType.getComponents()[c];
                    if (!roleBindingIds[c].empty() || component.allowedStates.empty()) continue;
                    const auto feature = roleType + "_" + makeValidSBMLId(component.name) + "_" +
                        std::to_string(c + 1);
                    sbml << "          <multi:speciesFeatureType multi:id=\"" << feature
                         << "\" multi:name=\"" << escapeXml(component.name)
                         << "\" multi:occur=\"1\">\n"
                         << "            <multi:listOfPossibleSpeciesFeatureValues>\n";
                    for (const auto& state : component.allowedStates) {
                        sbml << "              <multi:possibleSpeciesFeatureValue multi:id=\""
                             << feature << "_" << makeValidSBMLId(state) << "\" multi:name=\""
                             << escapeXml(state) << "\"/>\n";
                    }
                    sbml << "            </multi:listOfPossibleSpeciesFeatureValues>\n"
                         << "          </multi:speciesFeatureType>\n";
                }
                sbml << "        </multi:listOfSpeciesFeatureTypes>\n";
            }
            if (std::any_of(roleBindingIds.begin(), roleBindingIds.end(),
                            [](const auto& value) { return !value.empty(); })) {
                sbml << "        <multi:listOfSpeciesTypeInstances>\n";
                for (std::size_t c = 0; c < molType.getComponents().size(); ++c) {
                    if (roleBindingIds[c].empty()) continue;
                    sbml << "          <multi:speciesTypeInstance multi:id=\"" << roleType
                         << "_component_" << c + 1 << "\" multi:name=\""
                         << escapeXml(molType.getComponents()[c].name)
                         << "\" multi:speciesType=\"" << roleBindingIds[c] << "\"/>\n";
                }
                sbml << "        </multi:listOfSpeciesTypeInstances>\n";
            }
            sbml << "      </multi:speciesType>\n";
        }
    });

    visitMultiPatterns(model, [&](const std::string& text, const std::string& id) {
        const auto pattern = MultiPattern::parse(text);
        if (pattern.moleculeCount() < 2) return;
        const auto type = multiTypeId(pattern, id);
        const auto cloned = multiRoleClonedMolecules(model, pattern);
        sbml << "      <multi:speciesType multi:id=\"" << type << "\">\n"
             << "        <multi:listOfSpeciesTypeInstances>\n";
        for (std::size_t m = 0; m < pattern.moleculeCount(); ++m) {
            sbml << "          <multi:speciesTypeInstance multi:id=\"" << type << "_M" << m + 1
                 << "\" multi:speciesType=\""
                 << (cloned[m] ? multiRoleSpeciesTypeId(pattern.molecules()[m].moleculeType, type, m)
                               : "st_" + escapeXml(pattern.molecules()[m].moleculeType))
                 << "\"/>\n";
        }
        sbml << "        </multi:listOfSpeciesTypeInstances>\n"
             << "        <multi:listOfSpeciesTypeComponentIndexes>\n";
        std::map<std::size_t, std::vector<std::string>> bonds;
        std::map<std::size_t, std::vector<std::string>> bondSiteTypes;
        for (std::size_t m = 0; m < pattern.moleculeCount(); ++m) {
            const auto& molecule = pattern.molecules()[m];
            const auto& declaration = multiMoleculeType(model, molecule.moleculeType);
            for (std::size_t c = 0; c < declaration.getComponents().size(); ++c) {
                if (!isMultiBindingSite(binding, molecule.moleculeType,
                                        declaration.getComponents()[c])) {
                    continue;
                }
                sbml << "          <multi:speciesTypeComponentIndex multi:id=\""
                     << multiComponentId(type, m, c, true)
                     << "\" multi:component=\""
                     << (cloned[m] ? multiRoleSpeciesTypeId(molecule.moleculeType, type, m)
                                    : "st_" + escapeXml(molecule.moleculeType))
                     << "_component_" << c + 1 << "\" multi:identifyingParent=\""
                     << type << "_M" << m + 1 << "\"/>\n";
            }
            const auto indexes = multiComponentIndexes(model, molecule);
            for (std::size_t site = 0; site < molecule.sites.size(); ++site) {
                if (molecule.sites[site].bondKind == BondKind::Exact) {
                    bonds[molecule.sites[site].bondGroup.value].push_back(
                        multiComponentId(type, m, indexes[site], true));
                    const auto& component = declaration.getComponents()[indexes[site]];
                    const auto baseSiteType = multiBindingSiteId(
                            makeValidSBMLId(molecule.moleculeType),
                            makeValidSBMLId(component.name), indexes[site]);
                    bondSiteTypes[molecule.sites[site].bondGroup.value].push_back(
                        cloned[m] ? multiRoleId(baseSiteType,
                            multiRoleSpeciesTypeId(molecule.moleculeType, type, m)) : baseSiteType);
                }
            }
        }
        sbml << "        </multi:listOfSpeciesTypeComponentIndexes>\n";
        if (!bonds.empty()) sbml << "        <multi:listOfInSpeciesTypeBonds>\n";
        for (const auto& [group, endpoints] : bonds) {
            if (endpoints.size() != 2) throw std::invalid_argument("SBML-Multi bond requires two endpoints");
            const auto& siteTypes = bondSiteTypes.at(group);
            if (siteTypes.size() != 2 || siteTypes[0] == siteTypes[1]) {
                throw std::invalid_argument(
                    "SBML-Multi cannot encode a bond between the same "
                    "BindingSiteSpeciesType at both endpoints (Multi section 3.13.2)");
            }
            sbml << "          <multi:inSpeciesTypeBond multi:bindingSite1=\"" << endpoints[0]
                 << "\" multi:bindingSite2=\"" << endpoints[1] << "\"/>\n";
        }
        if (!bonds.empty()) sbml << "        </multi:listOfInSpeciesTypeBonds>\n";
        sbml << "      </multi:speciesType>\n";
    });
    sbml << "    </multi:listOfSpeciesTypes>\n";
    return sbml.str();
}

std::string SbmlMultiWriter::writeParameters(
    const ast::Model& model, const compile::CompiledModel& compiled) {
    if (model.getParameters().all().empty() && model.getObservables().empty()) return {};
    std::ostringstream sbml;
    sbml << "    <listOfParameters>\n";

    for (const auto& param : model.getParameters().all()) {
        sbml << "      <parameter id=\"" << makeValidSBMLId(param.getName())
             << "\" name=\"" << escapeXml(param.getName())
             << "\" value=\"" << param.getValue()
             << "\" constant=\"true\""
             << sbml_units::attribute(compiled, param.getUnitName()) << "/>\n";
    }
    // Observables are Core parameters that assignment rules keep equal to
    // the sum of their pattern species (BNG2 writeSBMLParameters).
    for (const auto& observable : model.getObservables()) {
        sbml << "      <parameter id=\"" << makeValidSBMLId(observable.getName())
             << "\" name=\"" << escapeXml(observable.getName())
             << "\" value=\"0\" constant=\"false\"/>\n";
    }

    sbml << "    </listOfParameters>\n";
    return sbml.str();
}

std::string SbmlMultiWriter::writeSeedSpecies(
    const ast::Model& model, const compile::CompiledModel& compiled) {
    if (model.getSeedSpecies().empty() && model.getReactionRules().empty()) return {};
    std::ostringstream sbml;
    sbml << std::setprecision(17) << "    <listOfSpecies>\n";
    const auto binding = multiBindingComponents(model);
    visitMultiPatterns(model, [&](const std::string& text, const std::string& id) {
        const auto pattern = MultiPattern::parse(text);
        if (pattern.moleculeCount() == 0) return;
        const auto type = multiTypeId(pattern, id);
        const auto cloned = pattern.moleculeCount() > 1
            ? multiRoleClonedMolecules(model, pattern)
            : std::vector<bool>(pattern.moleculeCount(), false);
        double amount = 0;
        bool constant = false;
        std::string compartment = pattern.compartment().empty() ? "default" : pattern.compartment();
        const auto identity = multiPatternIdentityKey(model, text);
        for (std::size_t index = 0; index < model.getSeedSpecies().size(); ++index) {
            const auto& seed = model.getSeedSpecies()[index];
            if (multiPatternIdentityKey(model, seed.getPattern()) != identity) continue;
            double seedAmount = seed.getAmount().evaluate([&](const std::string& name) {
                return model.getParameters().evaluate(name);
            }, 0.0);
            if (sbml_units::enabled(compiled)) {
                seedAmount = engine::NetworkGenerator::normalizeSeedAmount(compiled, compiled.seeds()[index]);
            }
            amount += seedAmount;
            if (!seed.getCompartment().empty()) compartment = seed.getCompartment();
            constant = constant || seed.isConstant();
        }
        sbml << "      <species id=\"" << id << "\" name=\"" << escapeXml(text)
             << "\" compartment=\"" << makeValidSBMLId(compartment)
             << "\" initialAmount=\"" << amount << "\" hasOnlySubstanceUnits=\"true\""
             << " constant=\"" << (constant ? "true" : "false")
             << "\" boundaryCondition=\"" << (constant ? "true" : "false")
             << "\" multi:speciesType=\"" << type << "\""
             << (sbml_units::enabled(compiled) ? sbml_units::speciesAttribute(compiled, "item") : std::string{})
             << ">\n";
        std::vector<std::string> features;
        std::ostringstream outward;
        for (std::size_t m = 0; m < pattern.moleculeCount(); ++m) {
            const auto& molecule = pattern.molecules()[m];
            const auto& declaration = multiMoleculeType(model, molecule.moleculeType);
            const auto indexes = multiComponentIndexes(model, molecule);
            for (std::size_t c = 0; c < declaration.getComponents().size(); ++c) {
                const auto& component = declaration.getComponents()[c];
                const compile::PatternSiteDescriptor* site = nullptr;
                for (std::size_t p = 0; p < indexes.size(); ++p) {
                    if (indexes[p] == c) site = &molecule.sites[p];
                }
                const bool bindingSite = isMultiBindingSite(binding, molecule.moleculeType, component);
                if (!component.allowedStates.empty() && bindingSite) {
                    // The state is a feature of the binding-site instance; the
                    // bond status is an outward binding site, as for any site.
                    if (site != nullptr && !site->stateConstraint.empty() &&
                        site->stateConstraint != "?" && site->stateConstraint != "*") {
                        if (std::find(component.allowedStates.begin(), component.allowedStates.end(),
                                      site->stateConstraint) == component.allowedStates.end()) {
                            throw std::invalid_argument("SBML-Multi requires a single declared state in a species feature");
                        }
                        const auto baseFeature = multiBindingSiteId(
                            makeValidSBMLId(molecule.moleculeType),
                            makeValidSBMLId(component.name), c);
                        const auto feature = (cloned[m]
                            ? multiRoleId(baseFeature, multiRoleSpeciesTypeId(
                                  molecule.moleculeType, type, m))
                            : baseFeature) + "_state";
                        features.push_back("          <multi:speciesFeature multi:speciesFeatureType=\"" + feature +
                            "\" multi:occur=\"1\" multi:component=\"" +
                            multiComponentId(type, m, c, pattern.moleculeCount() > 1) +
                            "\"><multi:listOfSpeciesFeatureValues>"
                            "<multi:speciesFeatureValue multi:value=\"" + feature + "_" +
                            makeValidSBMLId(site->stateConstraint) +
                            "\"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>\n");
                    }
                }
                if (!component.allowedStates.empty() && !bindingSite) {
                    if (site != nullptr && !site->stateConstraint.empty() && site->stateConstraint != "?" && site->stateConstraint != "*") {
                        if (std::find(component.allowedStates.begin(), component.allowedStates.end(),
                                      site->stateConstraint) == component.allowedStates.end()) {
                            throw std::invalid_argument("SBML-Multi requires a single declared state in a species feature");
                        }
                        const auto baseFeature = "st_" + makeValidSBMLId(molecule.moleculeType) + "_" +
                            makeValidSBMLId(component.name) + "_" + std::to_string(c + 1);
                        const auto feature = cloned[m]
                            ? multiRoleSpeciesTypeId(molecule.moleculeType, type, m) + "_" +
                                  makeValidSBMLId(component.name) + "_" + std::to_string(c + 1)
                            : baseFeature;
                        const auto parent = pattern.moleculeCount() > 1
                            ? " multi:component=\"" + type + "_M" + std::to_string(m + 1) + "\"" : "";
                        features.push_back("          <multi:speciesFeature multi:speciesFeatureType=\"" + feature +
                            "\" multi:occur=\"1\"" + parent + "><multi:listOfSpeciesFeatureValues>"
                            "<multi:speciesFeatureValue multi:value=\"" + feature + "_" + makeValidSBMLId(site->stateConstraint) +
                            "\"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>\n");
                    }
                    // A state component that never binds in this model is only
                    // a feature; an explicitly unbound site says nothing more.
                    if (site != nullptr && site->bondKind != BondKind::Unspecified &&
                        site->bondKind != BondKind::Unbound) {
                        throw std::invalid_argument("SBML-Multi state component binds but is not a binding site");
                    }
                    continue;
                }
                if (site != nullptr && site->bondKind == BondKind::Exact) continue;
                const auto status = site == nullptr || site->bondKind == BondKind::Any
                    ? "either" : site->bondKind == BondKind::Bound ? "bound" : "unbound";
                outward << "          <multi:outwardBindingSite multi:component=\""
                     << multiComponentId(type, m, c, pattern.moleculeCount() > 1)
                     << "\" multi:bindingStatus=\"" << status << "\"/>\n";
            }
        }
        if (!outward.str().empty()) {
            sbml << "        <multi:listOfOutwardBindingSites>\n" << outward.str()
                 << "        </multi:listOfOutwardBindingSites>\n";
        }
        if (!features.empty()) {
            sbml << "        <multi:listOfSpeciesFeatures>\n";
            for (const auto& feature : features) sbml << feature;
            sbml << "        </multi:listOfSpeciesFeatures>\n";
        }
        sbml << "      </species>\n";
    });
    sbml << "    </listOfSpecies>\n";
    return sbml.str();
}

std::string SbmlMultiWriter::writeObservableRules(const ast::Model& model) {
    if (model.getObservables().empty()) return {};
    std::ostringstream sbml;
    sbml << "    <listOfRules>\n";
    const auto species = multiObservableSpecies(model);
    for (std::size_t index = 0; index < model.getObservables().size(); ++index) {
        const auto& observable = model.getObservables()[index];
        const auto& terms = species.terms[index];
        sbml << "      <assignmentRule variable=\"" << makeValidSBMLId(observable.getName())
             << "\">\n        <math xmlns=\"http://www.w3.org/1998/Math/MathML\">\n";
        if (terms.empty()) {
            sbml << "          <cn> 0 </cn>\n";
        } else if (terms.size() == 1) {
            sbml << "          <ci> " << terms.front() << " </ci>\n";
        } else {
            sbml << "          <apply>\n            <plus/>\n";
            for (const auto& term : terms) sbml << "            <ci> " << term << " </ci>\n";
            sbml << "          </apply>\n";
        }
        sbml << "        </math>\n      </assignmentRule>\n";
    }
    sbml << "    </listOfRules>\n";
    return sbml.str();
}

std::string SbmlMultiWriter::writeReactionRules(const ast::Model& model) {
    if (model.getReactionRules().empty()) return {};
    std::ostringstream sbml;
    const auto symbols = SbmlWriter::computeSymbolIds(model, nullptr, {});
    sbml << "    <listOfReactions>\n";
    for (std::size_t index = 0; index < model.getReactionRules().size(); ++index) {
        const auto& rule = model.getReactionRules()[index];
        if (compile::isTotalRateRule(rule) && !rule.isAbsoluteFlux()) {
            throw std::invalid_argument(
                "SBML-Multi cannot lower BNGL TotalRate match normalization "
                "without a complete absolute-flux rate law");
        }
        const std::string patternPrefix = "RR" + std::to_string(index + 1);
        const auto direction = [&](bool reverse) {
            const auto& reactants = reverse ? rule.getProducts() : rule.getReactants();
            const auto& products = reverse ? rule.getReactants() : rule.getProducts();
            const auto& reactantPatterns = reverse
                ? rule.getProductPatterns() : rule.getReactantPatterns();
            const auto rateIndex = reverse ? 1u : 0u;
            if (rule.getRates().size() <= rateIndex) {
                throw std::invalid_argument("SBML-Multi rule direction has no rate law");
            }
            const bool absolute = rule.isAbsoluteFlux() && compile::isTotalRateRule(rule);
            const double permutationFactor = absolute ? 1.0
                : bng::ast::identicalReactantPatternPermutationFactor(reactantPatterns);
            const auto id = patternPrefix + (reverse ? "r" : "");
            auto name = rule.getRuleName().empty() ? rule.getLabel() : rule.getRuleName();
            if (name.empty()) name = patternPrefix;
            if (reverse) name = "_reverse__" + name;
            sbml << "      <reaction id=\"" << id << "\" name=\""
                 << escapeXml(name) << "\" reversible=\"false\" fast=\"false\">\n";
            std::vector<std::string> reactantIds;
            const auto writeSide = [&](const std::vector<std::string>& patterns,
                                       bool product) {
                if (patterns.empty()) return;
                sbml << (product ? "        <listOfProducts>\n" : "        <listOfReactants>\n");
                for (std::size_t position = 0; position < patterns.size(); ++position) {
                    // Both directions reference the same pattern-species objects.
                    const auto patternId = patternPrefix + ((product != reverse) ? "_P" : "_R") +
                                           std::to_string(position + 1);
                    const auto species = multiPatternSpeciesId(model, patterns[position], patternId);
                    const auto reference = "ref_" + id + (product ? "_P" : "_R") +
                                           std::to_string(position + 1);
                    if (!product) reactantIds.push_back(species);
                    sbml << "          <speciesReference id=\"" << reference
                         << "\" species=\"" << species << "\" stoichiometry=\"1\" constant=\"false\"";
                    std::vector<std::string> maps;
                    if (product) {
                        for (const auto& mapping : rule.getMoleculeMappings()) {
                            const auto& target = reverse ? mapping.second : mapping.first;
                            const auto& source = reverse ? mapping.first : mapping.second;
                            if (target.patternIndex != position) continue;
                            const auto sourcePatternId = patternPrefix + (reverse ? "_P" : "_R") +
                                std::to_string(source.patternIndex + 1);
                            const auto sourceSpecies = multiPatternSpeciesId(
                                model, reactants.at(source.patternIndex), sourcePatternId);
                            const auto sourcePattern = MultiPattern::parse(reactants.at(source.patternIndex));
                            const auto targetPattern = MultiPattern::parse(products.at(target.patternIndex));
                            const auto component = [&](const MultiPattern& pattern,
                                                       const std::string& patternId, std::size_t molecule) {
                                const auto type = multiTypeId(pattern, patternId);
                                return pattern.moleculeCount() == 1 ? type
                                    : type + "_M" + std::to_string(molecule + 1);
                            };
                            maps.push_back("              <multi:speciesTypeComponentMapInProduct multi:reactant=\"ref_" +
                                id + "_R" + std::to_string(source.patternIndex + 1) +
                                "\" multi:reactantComponent=\"" +
                                component(sourcePattern, sourceSpecies, source.moleculeIndex) +
                                "\" multi:productComponent=\"" +
                                component(targetPattern, species, target.moleculeIndex) + "\"/>\n");
                        }
                    }
                    if (maps.empty()) {
                        sbml << "/>\n";
                    } else {
                        sbml << ">\n            <multi:listOfSpeciesTypeComponentMapsInProduct>\n";
                        for (const auto& map : maps) sbml << map;
                        sbml << "            </multi:listOfSpeciesTypeComponentMapsInProduct>\n"
                             << "          </speciesReference>\n";
                    }
                }
                sbml << (product ? "        </listOfProducts>\n" : "        </listOfReactants>\n");
            };
            writeSide(reactants, false);
            writeSide(products, true);
            sbml << "        <kineticLaw>\n"
                 << "          <math xmlns=\"http://www.w3.org/1998/Math/MathML\">\n";
            // The semantic flag belongs to this exact rule, including
            // unnamed rules.  A name-based lookup loses absolute-flux
            // semantics when no rule name was authored.
            const auto volume = absolute ? std::string{} : multiMassActionVolume(model, reactants);
            if (!volume.empty()) sbml << "            <apply><divide/>\n";
            if (!absolute && (!reactantIds.empty() || permutationFactor != 1.0)) {
                sbml << "            <apply><times/>\n";
            }
            if (permutationFactor != 1.0) {
                sbml << "              <cn> " << std::setprecision(17)
                     << permutationFactor << " </cn>\n";
            }
            sbml << SbmlWriter::exprToMathML(rule.getRates()[rateIndex], "              ", symbols);
            if (!absolute) {
                for (const auto& species : reactantIds) {
                    sbml << "              <ci>" << species << "</ci>\n";
                }
            }
            if (!absolute && (!reactantIds.empty() || permutationFactor != 1.0)) {
                sbml << "            </apply>\n";
            }
            if (!volume.empty()) {
                if (reactantIds.size() == 2) {
                    sbml << "              <ci>" << makeValidSBMLId(volume) << "</ci>\n";
                } else {
                    sbml << "              <apply><power/><ci>" << makeValidSBMLId(volume)
                         << "</ci><cn>" << (reactantIds.size() - 1) << "</cn></apply>\n";
                }
                sbml << "            </apply>\n";
            }
            sbml << "          </math>\n        </kineticLaw>\n      </reaction>\n";
        };
        direction(false);
        if (rule.isBidirectional()) direction(true);
    }
    sbml << "    </listOfReactions>\n";
    return sbml.str();
}

} // namespace bng::io
