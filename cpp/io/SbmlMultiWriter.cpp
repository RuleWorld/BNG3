#include "SbmlMultiWriter.hpp"

#include <algorithm>
#include <sstream>
#include <cctype>
#include <utility>

namespace bng::io {

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
    std::ostringstream sbml;

    // SBML L3V1 header with Multi package namespace
    sbml << "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
    sbml << "<!-- Created by BioNetGen C++ (writeSBMLMulti) -->\n";
    sbml << "<sbml xmlns=\"http://www.sbml.org/sbml/level3/version1/core\"\n";
    sbml << "      xmlns:multi=\"http://www.sbml.org/sbml/level3/version1/multi/version1\"\n";
    sbml << "      level=\"" << options.level << "\" version=\"" << options.version
         << "\" multi:required=\"true\">\n";

    sbml << "  <model id=\"" << escapeXml(makeValidSBMLId(model.getModelName())) << "\" name=\""
         << escapeXml(model.getModelName()) << "\">\n";

    // Species types (molecule types with components and states)
    sbml << writeSpeciesTypes(model);

    // Compartments
    sbml << writeCompartments(model);

    // Parameters
    sbml << writeParameters(model);

    // Seed species with multi:speciesType references
    sbml << writeSeedSpecies(model);

    // Reaction rules with pattern matching
    sbml << writeReactionRules(model);

    sbml << "  </model>\n";
    sbml << "</sbml>\n";

    return sbml.str();
}

std::string SbmlMultiWriter::writeCompartments(const ast::Model& model) {
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
             << "\" constant=\"true\"";

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
    std::vector<std::vector<std::string>> bindingSiteIds;
    bindingSiteIds.reserve(model.getMoleculeTypes().size());
    for (const auto& molType : model.getMoleculeTypes()) {
        std::vector<std::string> ids;
        ids.reserve(molType.getComponents().size());
        for (std::size_t index = 0; index < molType.getComponents().size(); ++index) {
            const auto& component = molType.getComponents()[index];
            if (component.allowedStates.empty()) {
                ids.push_back(
                    "bst_" + makeValidSBMLId(molType.getName()) + "_" +
                    makeValidSBMLId(component.name) + "_" + std::to_string(index + 1));
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
            if (!bindingId.empty()) {
                sbml << "      <multi:bindingSiteSpeciesType multi:id=\""
                     << bindingId << "\" multi:name=\""
                     << escapeXml(component.name) << "\"/>\n";
            }
        }
    }

    for (std::size_t molIndex = 0; molIndex < model.getMoleculeTypes().size(); ++molIndex) {
        const auto& molType = model.getMoleculeTypes()[molIndex];
        std::string stId = "st_" + makeValidSBMLId(molType.getName());
        sbml << "      <multi:speciesType multi:id=\"" << stId
             << "\" multi:name=\"" << escapeXml(molType.getName()) << "\">\n";

        // State-bearing components are represented by speciesFeatureTypes.
        bool hasStateComponents = false;
        for (const auto& component : molType.getComponents()) {
            hasStateComponents = hasStateComponents || !component.allowedStates.empty();
        }
        if (hasStateComponents) {
            sbml << "        <multi:listOfSpeciesFeatureTypes>\n";

            for (std::size_t componentIndex = 0;
                 componentIndex < molType.getComponents().size();
                 ++componentIndex) {
                const auto& component = molType.getComponents()[componentIndex];
                if (component.allowedStates.empty()) {
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

    sbml << "    </multi:listOfSpeciesTypes>\n";
    return sbml.str();
}

std::string SbmlMultiWriter::writeParameters(const ast::Model& model) {
    std::ostringstream sbml;
    sbml << "    <listOfParameters>\n";

    for (const auto& param : model.getParameters().all()) {
        sbml << "      <parameter id=\"" << makeValidSBMLId(param.getName())
             << "\" name=\"" << escapeXml(param.getName())
             << "\" value=\"" << param.getValue()
             << "\" constant=\"true\"/>\n";
    }

    sbml << "    </listOfParameters>\n";
    return sbml.str();
}

std::string SbmlMultiWriter::writeSeedSpecies(const ast::Model& model) {
    std::ostringstream sbml;

    if (model.getSeedSpecies().empty() && model.getReactionRules().empty()) {
        return {};
    }

    sbml << "    <listOfSpecies>\n";

    for (std::size_t i = 0; i < model.getSeedSpecies().size(); ++i) {
        const auto& seed = model.getSeedSpecies()[i];
        std::string speciesId = "S" + std::to_string(i + 1);
        std::string compartmentId = seed.getCompartment().empty()
            ? "default" : makeValidSBMLId(seed.getCompartment());

        auto amountValue = seed.getAmount().evaluate([&](const std::string& name) {
            return model.getParameters().evaluate(name);
        }, 0.0);

        // A single-molecule seed can carry its concrete states and outward
        // binding status in the Multi vocabulary.  Keep richer complexes as
        // core pattern names: Multi v1 has no reaction-rule element and the
        // importer will reconstruct them only when the BNGL name is valid.
        const std::string& pattern = seed.getPattern();
        const auto& graph = seed.getGraph();
        std::vector<const BNGcore::Node*> moleculeNodes;
        std::vector<const BNGcore::Node*> componentNodes;
        for (auto node = graph.begin(); node != graph.end(); ++node) {
            const auto& nodeType = (*node)->get_type();
            if (nodeType < BNGcore::COMPONENT_NODE_TYPE) {
                componentNodes.push_back(*node);
            } else if (nodeType < BNGcore::ENTITY_NODE_TYPE) {
                moleculeNodes.push_back(*node);
            }
        }

        const ast::MoleculeType* moleculeType = nullptr;
        if (moleculeNodes.size() == 1) {
            for (const auto& candidate : model.getMoleculeTypes()) {
                if (candidate.getName() == moleculeNodes.front()->get_type().get_type_name()) {
                    moleculeType = &candidate;
                    break;
                }
            }
        }
        const std::string speciesTypeRef = moleculeType == nullptr
            ? std::string()
            : "st_" + makeValidSBMLId(moleculeType->getName());

        sbml << "      <species id=\"" << speciesId
             << "\" name=\"" << escapeXml(pattern)
             << "\" compartment=\"" << compartmentId
             << "\" initialAmount=\"" << amountValue
             << "\" hasOnlySubstanceUnits=\"true\"";

        if (seed.isConstant()) {
            sbml << " constant=\"true\" boundaryCondition=\"true\"";
        } else {
            sbml << " constant=\"false\" boundaryCondition=\"false\"";
        }

        if (!speciesTypeRef.empty()) {
            sbml << " multi:speciesType=\"" << speciesTypeRef << "\"";
        }

        std::vector<std::string> stateFeatures;
        std::vector<std::string> outwardSites;
        if (moleculeType != nullptr) {
            std::vector<std::size_t> componentIndexes;
            for (const auto* componentNode : componentNodes) {
                const auto componentName = componentNode->get_type().get_type_name();
                std::size_t componentIndex = moleculeType->getComponents().size();
                for (std::size_t index = 0; index < moleculeType->getComponents().size(); ++index) {
                    if (moleculeType->getComponents()[index].name != componentName) {
                        continue;
                    }
                    if (std::find(componentIndexes.begin(), componentIndexes.end(), index) ==
                        componentIndexes.end()) {
                        componentIndex = index;
                        break;
                    }
                }
                if (componentIndex >= moleculeType->getComponents().size()) {
                    continue;
                }
                componentIndexes.push_back(componentIndex);
                const auto& component = moleculeType->getComponents()[componentIndex];
                const auto stateText = componentNode->get_state().get_BNG2_string();
                if (!component.allowedStates.empty() && stateText.size() > 1 &&
                    stateText.front() == '~' && stateText.substr(1) != "?") {
                    const auto state = stateText.substr(1);
                    if (std::find(component.allowedStates.begin(),
                                  component.allowedStates.end(), state) !=
                        component.allowedStates.end()) {
                        const auto featureId = "st_" + makeValidSBMLId(moleculeType->getName()) +
                            "_" + makeValidSBMLId(component.name) + "_" +
                            std::to_string(componentIndex + 1);
                        const auto valueId = featureId + "_" + makeValidSBMLId(state);
                        stateFeatures.push_back(
                            "        <multi:speciesFeature multi:speciesFeatureType=\"" +
                            featureId + "\" multi:occur=\"1\"><multi:listOfSpeciesFeatureValues>"
                            "<multi:speciesFeatureValue multi:value=\"" + valueId +
                            "\"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>\n");
                    }
                }
                if (component.allowedStates.empty()) {
                    std::string bindingStatus;
                    for (auto edge = componentNode->edges_out_begin();
                         edge != componentNode->edges_out_end(); ++edge) {
                        if ((*edge)->get_type() != BNGcore::BOND_NODE_TYPE) {
                            continue;
                        }
                        const auto bond = (*edge)->get_state().get_BNG2_string();
                        if (bond == "!+") bindingStatus = "bound";
                        else if (bond == "!?") bindingStatus = "either";
                        else if (bond == "!0" || bond == "!-") bindingStatus = "unbound";
                    }
                    if (!bindingStatus.empty()) {
                        const auto componentId = "st_" + makeValidSBMLId(moleculeType->getName()) +
                            "_component_" + std::to_string(componentIndex + 1);
                        outwardSites.push_back(
                            "        <multi:outwardBindingSite multi:component=\"" +
                            componentId + "\" multi:bindingStatus=\"" + bindingStatus +
                            "\"/>\n");
                    }
                }
            }
        }
        if (stateFeatures.empty() && outwardSites.empty()) {
            sbml << "/>\n";
        } else {
            sbml << ">\n";
            if (!stateFeatures.empty()) {
                sbml << "        <multi:listOfSpeciesFeatures>\n";
                for (const auto& feature : stateFeatures) sbml << feature;
                sbml << "        </multi:listOfSpeciesFeatures>\n";
            }
            if (!outwardSites.empty()) {
                sbml << "        <multi:listOfOutwardBindingSites>\n";
                for (const auto& site : outwardSites) sbml << site;
                sbml << "        </multi:listOfOutwardBindingSites>\n";
            }
            sbml << "      </species>\n";
        }
    }

    // Reaction-rule patterns become ordinary core species references.  This
    // keeps the exported document within the SBML Multi v1 grammar; consumers
    // that understand the pattern name can reconstruct the richer rule view.
    for (std::size_t ruleIndex = 0; ruleIndex < model.getReactionRules().size(); ++ruleIndex) {
        const auto& rule = model.getReactionRules()[ruleIndex];
        const std::string ruleId = "RR" + std::to_string(ruleIndex + 1);
        auto writePatternSpecies = [&](const std::string& speciesId,
                                       const std::string& pattern) {
            sbml << "      <species id=\"" << speciesId
                 << "\" name=\"" << escapeXml(pattern)
                 << "\" compartment=\"default\" initialAmount=\"0\""
                 << " hasOnlySubstanceUnits=\"true\" constant=\"false\""
                 << " boundaryCondition=\"false\"";
            if (pattern.find('.') == std::string::npos) {
                const auto end = pattern.find_first_of("(@");
                const std::string moleculeName = pattern.substr(0, end);
                for (const auto& moleculeType : model.getMoleculeTypes()) {
                    if (moleculeType.getName() == moleculeName) {
                        sbml << " multi:speciesType=\"st_"
                             << makeValidSBMLId(moleculeName) << "\"";
                        break;
                    }
                }
            }
            sbml << "/>\n";
        };
        for (std::size_t index = 0; index < rule.getReactants().size(); ++index) {
            writePatternSpecies(
                ruleId + "_R" + std::to_string(index + 1), rule.getReactants()[index]);
        }
        for (std::size_t index = 0; index < rule.getProducts().size(); ++index) {
            writePatternSpecies(
                ruleId + "_P" + std::to_string(index + 1), rule.getProducts()[index]);
        }
    }

    sbml << "    </listOfSpecies>\n";
    return sbml.str();
}

std::string SbmlMultiWriter::writeReactionRules(const ast::Model& model) {
    std::ostringstream sbml;

    if (model.getReactionRules().empty()) {
        return {};
    }

    // SBML Multi v1 does not define a reactionRule/listOfReactionRules
    // vocabulary.  Rule-based patterns are represented as Multi species in
    // the core listOfSpecies and connected by ordinary core Reactions.
    sbml << "    <listOfReactions>\n";

    for (std::size_t r = 0; r < model.getReactionRules().size(); ++r) {
        const auto& rule = model.getReactionRules()[r];
        std::string ruleId = "RR" + std::to_string(r + 1);

        // Use rule name/label if available, fall back to generated id
        std::string ruleName = rule.getRuleName();
        if (ruleName.empty()) {
            ruleName = rule.getLabel();
        }
        if (ruleName.empty()) {
            ruleName = ruleId;
        }

        sbml << "      <reaction id=\"" << makeValidSBMLId(ruleId)
             << "\" name=\"" << escapeXml(ruleName)
             << "\" reversible=\"" << (rule.isBidirectional() ? "true" : "false")
             << "\" fast=\"false\">\n";

        // Pattern species are emitted by writeSeedSpecies with deterministic
        // ids.  Simple patterns receive Multi speciesType references; richer
        // patterns remain core species names because Multi v1 has no rule
        // element.  The modern importer reconstructs these only when the name
        // is a valid BNGL pattern.
        if (!rule.getReactants().empty()) {
            sbml << "        <listOfReactants>\n";
            for (std::size_t i = 0; i < rule.getReactants().size(); ++i) {
                sbml << "          <speciesReference id=\"" << ruleId << "_R"
                     << (i + 1) << "\" species=\"" << ruleId << "_R"
                     << (i + 1) << "\" constant=\"false\"/>\n";
            }
            sbml << "        </listOfReactants>\n";
        }

        // Product pattern species use the same ids as the species list above.
        if (!rule.getProducts().empty()) {
            sbml << "        <listOfProducts>\n";
            for (std::size_t i = 0; i < rule.getProducts().size(); ++i) {
                sbml << "          <speciesReference id=\"" << ruleId << "_P"
                     << (i + 1) << "\" species=\"" << ruleId << "_P"
                     << (i + 1) << "\" constant=\"false\"/>\n";
            }
            sbml << "        </listOfProducts>\n";
        }

        // Rate law
        const auto& rates = rule.getRates();
        if (!rates.empty()) {
            sbml << "        <kineticLaw>\n";
            sbml << "          <math xmlns=\"http://www.w3.org/1998/Math/MathML\">\n";

            const auto& rateExpr = rates[0];
            if (rateExpr.kind() == ast::ExpressionKind::Number) {
                sbml << "            <cn> " << rateExpr.name() << " </cn>\n";
            } else if (rateExpr.kind() == ast::ExpressionKind::Identifier) {
                sbml << "            <ci> " << escapeXml(rateExpr.name()) << " </ci>\n";
            } else {
                // For complex expressions, emit the top-level name/value
                sbml << "            <ci> " << escapeXml(rateExpr.name()) << " </ci>\n";
            }

            sbml << "          </math>\n";

            // If bidirectional, also emit reverse rate
            if (rule.isBidirectional() && rates.size() > 1) {
                sbml << "          <!-- Reverse rate -->\n";
                sbml << "          <!-- ";
                if (rates[1].kind() == ast::ExpressionKind::Number) {
                    sbml << rates[1].name();
                } else {
                    sbml << escapeXml(rates[1].name());
                }
                sbml << " -->\n";
            }

            sbml << "        </kineticLaw>\n";
        }

        sbml << "      </reaction>\n";
    }

    sbml << "    </listOfReactions>\n";
    return sbml.str();
}

} // namespace bng::io
