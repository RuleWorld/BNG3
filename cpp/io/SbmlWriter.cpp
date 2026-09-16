#include "SbmlWriter.hpp"

#include <sstream>
#include <iomanip>
#include <algorithm>
#include <cctype>
#include <cmath>
#include <functional>
#include <map>
#include <stdexcept>
#include <unordered_set>

#include "parser/antlr_compat.hpp"
#include <antlr4-runtime.h>
#include "generated/BNGLexer.h"
#include "generated/BNGParser.h"
#include "parser/PatternGraphBuilder.hpp"
#include "core/Ullmann.hpp"
#include "io/NetWriter.hpp"

namespace bng::io {

namespace {

std::string base64Encode(const std::string& input) {
    static constexpr char alphabet[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string output;
    output.reserve(((input.size() + 2) / 3) * 4);
    std::size_t index = 0;
    while (index + 2 < input.size()) {
        const auto a = static_cast<unsigned char>(input[index++]);
        const auto b = static_cast<unsigned char>(input[index++]);
        const auto c = static_cast<unsigned char>(input[index++]);
        output.push_back(alphabet[a >> 2]);
        output.push_back(alphabet[((a & 0x03U) << 4) | (b >> 4)]);
        output.push_back(alphabet[((b & 0x0fU) << 2) | (c >> 6)]);
        output.push_back(alphabet[c & 0x3fU]);
    }
    const auto remaining = input.size() - index;
    if (remaining == 1) {
        const auto a = static_cast<unsigned char>(input[index]);
        output.push_back(alphabet[a >> 2]);
        output.push_back(alphabet[(a & 0x03U) << 4]);
        output += "==";
    } else if (remaining == 2) {
        const auto a = static_cast<unsigned char>(input[index++]);
        const auto b = static_cast<unsigned char>(input[index]);
        output.push_back(alphabet[a >> 2]);
        output.push_back(alphabet[((a & 0x03U) << 4) | (b >> 4)]);
        output.push_back(alphabet[(b & 0x0fU) << 2]);
        output.push_back('=');
    }
    return output;
}

bool isInternalFunction(const std::string& name) {
    return name.rfind("__assign_rule__", 0) == 0 ||
           name.rfind("__rate_rule_in_", 0) == 0 ||
           name.rfind("__rate_rule_out_", 0) == 0;
}

bool hasTotalRateModifier(const ast::Model& model, const std::string& origin) {
    for (const auto& rule : model.getReactionRules()) {
        if (rule.getRuleName() != origin) continue;
        for (const auto& modifier : rule.getModifiers()) {
            std::string lowerModifier = modifier;
            std::transform(lowerModifier.begin(), lowerModifier.end(), lowerModifier.begin(),
                           [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            if (lowerModifier == "totalrate") return true;
        }
        break;
    }
    return false;
}

}  // namespace

std::string SbmlWriter::escapeXml(const std::string& text) {
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

std::string SbmlWriter::makeValidSBMLId(const std::string& text) {
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

SbmlWriter::SymbolIds SbmlWriter::computeSymbolIds(
    const ast::Model& model,
    const engine::GeneratedNetwork* network,
    const std::vector<ObservableGroup>& groups) {
    SymbolIds result;
    std::unordered_set<std::string> used;
    if (network) {
        for (std::size_t i = 0; i < network->species.size(); ++i) {
            used.insert("S" + std::to_string(i + 1));
        }
    }
    used.insert("default");
    used.insert("time");
    for (const auto& compartment : model.getCompartments()) {
        used.insert(makeValidSBMLId(compartment.getName()));
    }

    const auto allocate = [&](const std::string& source, const std::string& prefix) {
        const std::string base = makeValidSBMLId(source);
        std::string candidate = base;
        if (used.count(candidate) != 0) {
            candidate = prefix + base;
            std::size_t suffix = 2;
            while (used.count(candidate) != 0) {
                candidate = prefix + base + "_" + std::to_string(suffix++);
            }
        }
        used.insert(candidate);
        return candidate;
    };

    // SBML has one identifier namespace for species and parameters.  Network
    // species are deliberately named S1, S2, ...; preserve parameter names
    // but allocate a stable parameter_* ID when one collides.
    for (const auto& parameter : model.getParameters().all()) {
        const auto id = allocate(parameter.getName(), "param_");
        result.parameters.emplace(parameter.getName(), id);
        result.parameters.emplace(makeValidSBMLId(parameter.getName()), id);
    }
    for (const auto& function : model.getFunctions()) {
        if (function.getArgs().empty() && !isInternalFunction(function.getName())) {
            const auto id = allocate(function.getName(), "func_");
            result.functions.emplace(function.getName(), id);
            result.functions.emplace(makeValidSBMLId(function.getName()), id);
        }
    }
    for (const auto& group : groups) {
        result.observables.emplace(group.name, group.sbmlId);
        result.observables.emplace(makeValidSBMLId(group.name), group.sbmlId);
    }
    return result;
}

std::string SbmlWriter::write(const ast::Model& model, const engine::GeneratedNetwork* network) {
    Options options;
    return write(model, network, options);
}

std::string SbmlWriter::write(const ast::Model& model, const engine::GeneratedNetwork* network, const Options& options) {
    std::ostringstream sbml;
    // Preserve enough precision for a numerical round trip. The default
    // stream precision (six digits) changes compartment conversion factors
    // such as 1/0.3 and is visible in small-concentration trajectories.
    sbml << std::setprecision(17);

    // Compute observable groups (needs network for species matching)
    std::vector<ObservableGroup> groups;
    if (network && options.networksExport) {
        groups = computeObservableGroups(model, *network);
    }
    const auto symbolIds = computeSymbolIds(model, network, groups);

    // SBML header: current SBML core version by default (L3V2).
    sbml << "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
    sbml << "<!-- Created by BioNetGen C++ -->\n";
    sbml << "<sbml xmlns=\"http://www.sbml.org/sbml/level" << options.level
         << "/version" << options.version
         << (options.level >= 3 ? "/core" : "") << "\" "
         << "level=\"" << options.level << "\" version=\"" << options.version << "\">\n";

    sbml << "  <model id=\"" << escapeXml(makeValidSBMLId(model.getModelName())) << "\" name=\""
         << escapeXml(model.getModelName()) << "\">\n";

    if (!options.sourceMetadata.empty()) {
        sbml << writeSourceMetadata(options.sourceMetadata);
    }

    // Unit definitions (Perl: substance = item)
    sbml << writeUnitDefinitions(options.level);

    // Compartments
    sbml << writeCompartments(model, options.level);

    // Species
    sbml << writeSpecies(model, network);

    // Keep parameters after species and rules before reactions.  This order
    // is accepted by both SBML L2 and L3 and keeps generated documents stable.
    sbml << writeParameters(model, groups, symbolIds);

    // Assignment rules (observables + global functions)
    if (network && options.networksExport) {
        sbml << writeAssignmentRules(model, groups, symbolIds);
    }

    // Reactions
    if (network && options.networksExport) {
        sbml << writeReactions(*network, model, symbolIds, options.level);
    }

    sbml << "  </model>\n";
    sbml << "</sbml>\n";

    return sbml.str();
}

std::string SbmlWriter::writeSourceMetadata(const std::string& payload) {
    std::ostringstream sbml;
    sbml << "    <annotation>\n"
         << "      <bng:sourceMetadata xmlns:bng=\"https://bionetgen.org/sbml\" "
            "encoding=\"base64\" schemaVersion=\"1\">\n"
         << "        " << base64Encode(payload) << "\n"
         << "      </bng:sourceMetadata>\n"
         << "    </annotation>\n";
    return sbml.str();
}

std::string SbmlWriter::writeUnitDefinitions(int level) {
    std::ostringstream sbml;
    // Perl BNG2 convention: substance unit = item (molecule count)
    sbml << "    <listOfUnitDefinitions>\n";
    sbml << "      <unitDefinition id=\"substance\" name=\"substance\">\n";
    sbml << "        <listOfUnits>\n";
    sbml << "          <unit kind=\"item\" exponent=\"1\"";
    if (level >= 3) {
        sbml << " scale=\"0\"";
    }
    sbml << " multiplier=\"1\"/>\n";
    sbml << "        </listOfUnits>\n";
    sbml << "      </unitDefinition>\n";
    sbml << "    </listOfUnitDefinitions>\n";
    return sbml.str();
}

std::string SbmlWriter::writeCompartments(const ast::Model& model, int level) {
    std::ostringstream sbml;
    sbml << std::setprecision(17);

    if (model.getCompartments().empty()) {
        // Perl convention: default compartment named "default" with volume 1
        sbml << "    <listOfCompartments>\n";
        sbml << "      <compartment id=\"default\" spatialDimensions=\"3\" size=\"1\" constant=\"true\"/>\n";
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

        if (!comp.getParent().empty() && level < 3) {
            sbml << " outside=\"" << makeValidSBMLId(comp.getParent()) << "\"";
        }

        if (!comp.getParent().empty() && level >= 3) {
            // SBML L3V2 removed the core `outside` attribute. Preserve the
            // hierarchy as explicit writer provenance while keeping the
            // document valid; the current BNG3 compartment model has no
            // SBML comp-package lowering for hierarchical submodels.
            sbml << ">\n"
                 << "        <annotation><bng:outside "
                    "xmlns:bng=\"https://bionetgen.org/sbml\">"
                 << escapeXml(makeValidSBMLId(comp.getParent()))
                 << "</bng:outside></annotation>\n"
                 << "      </compartment>\n";
        } else {
            sbml << "/>\n";
        }
    }
    sbml << "    </listOfCompartments>\n";
    return sbml.str();
}

std::string SbmlWriter::writeParameters(
    const ast::Model& model,
    const std::vector<ObservableGroup>& groups,
    const SymbolIds& symbolIds) {
    std::ostringstream sbml;
    sbml << std::setprecision(17);
    bool hasParameters = !model.getParameters().all().empty() || !groups.empty();
    if (!hasParameters) {
        for (const auto& func : model.getFunctions()) {
            if (func.getArgs().empty() && !isInternalFunction(func.getName())) {
                hasParameters = true;
                break;
            }
        }
    }
    if (!hasParameters) return {};

    sbml << "    <listOfParameters>\n";

    // Model parameters (constant=true)
    for (const auto& param : model.getParameters().all()) {
        const auto idIt = symbolIds.parameters.find(param.getName());
        const auto id = idIt == symbolIds.parameters.end()
            ? makeValidSBMLId(param.getName()) : idIt->second;
        sbml << "      <parameter id=\"" << id
             << "\" name=\"" << escapeXml(param.getName())
             << "\" value=\"" << param.getValue()
             << "\" constant=\"true\"/>\n";
    }

    // Observables as non-constant parameters (Perl: constant=false)
    for (const auto& group : groups) {
        sbml << "      <parameter id=\"" << group.sbmlId
             << "\" name=\"" << escapeXml(group.name)
             << "\" value=\"0\" constant=\"false\"/>\n";
    }

    // Global functions (no args) as non-constant parameters
    for (const auto& func : model.getFunctions()) {
        if (func.getArgs().empty() && !isInternalFunction(func.getName())) {
            const auto idIt = symbolIds.functions.find(func.getName());
            const auto id = idIt == symbolIds.functions.end()
                ? makeValidSBMLId(func.getName()) : idIt->second;
            sbml << "      <parameter id=\"" << id
                 << "\" name=\"" << escapeXml(func.getName())
                 << "\" value=\"0\" constant=\"false\"/>\n";
        }
    }

    sbml << "    </listOfParameters>\n";
    return sbml.str();
}

std::string SbmlWriter::writeSpecies(const ast::Model& model, const engine::GeneratedNetwork* network) {
    std::ostringstream sbml;
    sbml << std::setprecision(17);
    const std::size_t speciesCount = network ? network->species.size() : model.getSeedSpecies().size();
    if (speciesCount == 0) return {};

    sbml << "    <listOfSpecies>\n";

    if (network) {
        for (std::size_t i = 0; i < network->species.size(); ++i) {
            const auto& species = network->species.get(i);
            std::string speciesId = "S" + std::to_string(i + 1);
            std::string compartmentId = species.getCompartment().empty()
                ? "default" : makeValidSBMLId(species.getCompartment());

            sbml << "      <species id=\"" << speciesId
                 << "\" name=\"" << escapeXml(species.getSpeciesGraph().toString())
                 << "\" compartment=\"" << compartmentId
                 << "\" initialAmount=\"" << species.getAmount()
                 << "\" hasOnlySubstanceUnits=\"true\"";

            if (species.isConstant()) {
                sbml << " constant=\"true\" boundaryCondition=\"true\"";
            } else {
                sbml << " constant=\"false\" boundaryCondition=\"false\"";
            }

            sbml << "/>\n";
        }
    } else {
        for (std::size_t i = 0; i < model.getSeedSpecies().size(); ++i) {
            const auto& seed = model.getSeedSpecies()[i];
            std::string speciesId = "S" + std::to_string(i + 1);
            std::string compartmentId = seed.getCompartment().empty()
                ? "default" : makeValidSBMLId(seed.getCompartment());

            auto amountValue = seed.getAmount().evaluate([&](const std::string& name) {
                return model.getParameters().evaluate(name);
            }, 0.0);

            sbml << "      <species id=\"" << speciesId
                 << "\" name=\"" << escapeXml(seed.getPattern())
                 << "\" compartment=\"" << compartmentId
                 << "\" initialAmount=\"" << amountValue
                 << "\" hasOnlySubstanceUnits=\"true\"";

            if (seed.isConstant()) {
                sbml << " constant=\"true\" boundaryCondition=\"true\"";
            } else {
                sbml << " constant=\"false\" boundaryCondition=\"false\"";
            }

            sbml << "/>\n";
        }
    }

    sbml << "    </listOfSpecies>\n";
    return sbml.str();
}

std::string SbmlWriter::writeAssignmentRules(
    const ast::Model& model,
    const std::vector<ObservableGroup>& groups,
    const SymbolIds& symbolIds) {
    std::ostringstream sbml;
    sbml << std::setprecision(17);

    bool hasRules = !groups.empty();
    for (const auto& func : model.getFunctions()) {
        if (func.getArgs().empty()) { hasRules = true; break; }
    }
    if (!hasRules) return {};

    sbml << "    <listOfRules>\n";

    // Observable assignment rules: each observable = weighted sum of species
    for (const auto& group : groups) {
        sbml << "      <assignmentRule variable=\"" << group.sbmlId << "\">\n";
        sbml << "        <math xmlns=\"http://www.w3.org/1998/Math/MathML\">\n";

        if (group.entries.empty()) {
            // No matching species - observable = 0
            sbml << "          <cn> 0 </cn>\n";
        } else if (group.entries.size() == 1) {
            // Single species
            const auto& [idx, weight] = group.entries[0];
            if (weight == 1) {
                sbml << "          <ci> S" << (idx + 1) << " </ci>\n";
            } else {
                sbml << "          <apply>\n";
                sbml << "            <times/>\n";
                sbml << "            <cn> " << weight << " </cn>\n";
                sbml << "            <ci> S" << (idx + 1) << " </ci>\n";
                sbml << "          </apply>\n";
            }
        } else {
            // Multiple species - sum them
            sbml << "          <apply>\n";
            sbml << "            <plus/>\n";
            for (const auto& [idx, weight] : group.entries) {
                if (weight == 1) {
                    sbml << "            <ci> S" << (idx + 1) << " </ci>\n";
                } else {
                    sbml << "            <apply>\n";
                    sbml << "              <times/>\n";
                    sbml << "              <cn> " << weight << " </cn>\n";
                    sbml << "              <ci> S" << (idx + 1) << " </ci>\n";
                    sbml << "            </apply>\n";
                }
            }
            sbml << "          </apply>\n";
        }

        sbml << "        </math>\n";
        sbml << "      </assignmentRule>\n";
    }

    // Global function assignment rules (functions with no arguments)
    for (const auto& func : model.getFunctions()) {
        if (!func.getArgs().empty() || isInternalFunction(func.getName())) continue;

        const auto idIt = symbolIds.functions.find(func.getName());
        const auto id = idIt == symbolIds.functions.end()
            ? makeValidSBMLId(func.getName()) : idIt->second;
        sbml << "      <assignmentRule variable=\"" << id << "\">\n";
        sbml << "        <math xmlns=\"http://www.w3.org/1998/Math/MathML\">\n";
        sbml << exprToMathML(func.getExpression(), "          ", symbolIds);
        sbml << "        </math>\n";
        sbml << "      </assignmentRule>\n";
    }

    sbml << "    </listOfRules>\n";
    return sbml.str();
}

std::string SbmlWriter::writeReactions(
    const engine::GeneratedNetwork& network,
    const ast::Model& model,
    const SymbolIds& symbolIds,
    int level) {
    std::ostringstream sbml;
    sbml << std::setprecision(17);
    if (network.reactions.all().empty()) {
        return {};
    }
    sbml << "    <listOfReactions>\n";

    const auto& reactions = network.reactions.all();
    for (std::size_t r = 0; r < reactions.size(); ++r) {
        const auto& rxn = reactions[r];
        std::string reactionId = "R" + std::to_string(r + 1);

        sbml << "      <reaction id=\"" << reactionId << "\" reversible=\"false\">\n";

        // Reactants
        if (!rxn.getReactants().empty()) {
            sbml << "        <listOfReactants>\n";
            std::map<std::size_t, std::size_t> reactantStoichiometry;
            for (const auto idx : rxn.getReactants()) {
                ++reactantStoichiometry[idx];
            }
            for (const auto& [idx, stoich] : reactantStoichiometry) {
                sbml << "          <speciesReference species=\"S" << (idx + 1) << "\"";
                if (level >= 3) {
                    sbml << " constant=\"true\"";
                }
                if (stoich != 1) {
                    sbml << " stoichiometry=\"" << stoich << "\"";
                }
                sbml << "/>\n";
            }
            sbml << "        </listOfReactants>\n";
        }

        // Products
        if (!rxn.getProducts().empty()) {
            sbml << "        <listOfProducts>\n";
            std::map<std::size_t, std::size_t> productStoichiometry;
            for (const auto idx : rxn.getProducts()) {
                ++productStoichiometry[idx];
            }
            for (const auto& [idx, stoich] : productStoichiometry) {
                sbml << "          <speciesReference species=\"S" << (idx + 1) << "\"";
                if (level >= 3) {
                    sbml << " constant=\"true\"";
                }
                if (stoich != 1) {
                    sbml << " stoichiometry=\"" << stoich << "\"";
                }
                sbml << "/>\n";
            }
            sbml << "        </listOfProducts>\n";
        }

        // Kinetic law with MathML
        if (hasTotalRateModifier(model, rxn.getOriginRuleName())) {
            sbml << "        <annotation><bng:totalRate "
                    "xmlns:bng=\"https://bionetgen.org/sbml\"/></annotation>\n";
        }
        sbml << "        <kineticLaw>\n";
        sbml << "          <math xmlns=\"http://www.w3.org/1998/Math/MathML\">\n";
        sbml << rateLawToMathML(rxn, model, network, "            ", symbolIds);
        sbml << "          </math>\n";
        sbml << "        </kineticLaw>\n";

        sbml << "      </reaction>\n";
    }

    sbml << "    </listOfReactions>\n";
    return sbml.str();
}

std::vector<SbmlWriter::ObservableGroup> SbmlWriter::computeObservableGroups(
    const ast::Model& model, const engine::GeneratedNetwork& network) {
    std::vector<ObservableGroup> groups;
    auto& mutableModel = const_cast<ast::Model&>(model);

    for (const auto& observable : model.getObservables()) {
        ObservableGroup group;
        group.name = observable.getName();
        group.type = observable.getType();

        group.sbmlId = makeValidSBMLId(group.name);
        std::unordered_set<std::string> usedIds;
        for (std::size_t i = 0; i < network.species.size(); ++i) {
            usedIds.insert("S" + std::to_string(i + 1));
        }
        // SBML reserves the time symbol; it is represented as a csymbol in
        // MathML and cannot also be an assignment-rule variable.
        usedIds.insert("time");
        for (const auto& parameter : model.getParameters().all()) {
            usedIds.insert(makeValidSBMLId(parameter.getName()));
        }
        for (const auto& function : model.getFunctions()) {
            if (function.getArgs().empty() && !isInternalFunction(function.getName())) {
                usedIds.insert(makeValidSBMLId(function.getName()));
            }
        }
        for (const auto& prior : groups) {
            usedIds.insert(prior.sbmlId);
        }
        if (usedIds.count(group.sbmlId) != 0) {
            group.sbmlId = "obs_" + group.sbmlId;
            while (usedIds.count(group.sbmlId) != 0) {
                group.sbmlId += "_obs";
            }
        }

        for (std::size_t speciesIndex = 0; speciesIndex < network.species.size(); ++speciesIndex) {
            std::size_t weight = 0;

            for (const auto& patternText : observable.getPatterns()) {
                try {
                    antlr4::ANTLRInputStream input(patternText);
                    BNGLexer lexer(&input);
                    antlr4::CommonTokenStream tokens(&lexer);
                    BNGParser parser(&tokens);
                    auto* species = parser.species_def();

                    if (parser.getNumberOfSyntaxErrors() == 0) {
                        // A species-level compartment prefix/suffix is a
                        // filter on the observable pattern, not a molecule
                        // node attribute.  Ullmann matching alone therefore
                        // otherwise counts the same graph in every
                        // compartment (for example GLCo and GLCi in the
                        // glycolysis BioModel), corrupting the SBML
                        // assignment rules on round-trip.
                        const auto patternCompartment =
                            bng::parser::extractSpeciesCompartment(species);
                        if (!patternCompartment.empty() &&
                            network.species.get(speciesIndex).getCompartment() !=
                                patternCompartment) {
                            continue;
                        }
                        const auto pattern = bng::parser::buildPatternGraph(species, mutableModel);
                        BNGcore::UllmannSGIso matcher(pattern,
                            network.species.get(speciesIndex).getSpeciesGraph().getGraph());
                        BNGcore::List<BNGcore::Map> maps;
                        weight += matcher.find_maps(maps);
                    }
                } catch (...) {
                    // Skip patterns that fail to parse
                }
            }

            if (observable.getType() == "Species" && weight > 0) {
                weight = 1;
            }

            if (weight > 0) {
                group.entries.push_back({speciesIndex, weight});
            }
        }

        groups.push_back(std::move(group));
    }

    return groups;
}

std::string SbmlWriter::exprToMathML(
    const ast::Expression& expr,
    const std::string& indent,
    const SymbolIds& symbolIds) {
    std::ostringstream out;

    switch (expr.kind()) {
        case ast::ExpressionKind::Number:
            out << indent << "<cn> " << std::setprecision(17)
                << expr.numberValue() << " </cn>\n";
            break;

        case ast::ExpressionKind::Identifier:
            if (expr.name() == "time") {
                out << indent
                    << "<csymbol encoding=\"text\" "
                    << "definitionURL=\"http://www.sbml.org/sbml/symbols/time\">"
                    << " time </csymbol>\n";
            } else {
                std::string id = expr.name();
                if (const auto it = symbolIds.parameters.find(expr.name());
                    it != symbolIds.parameters.end()) {
                    id = it->second;
                } else if (const auto it = symbolIds.functions.find(expr.name());
                           it != symbolIds.functions.end()) {
                    id = it->second;
                } else if (const auto it = symbolIds.observables.find(expr.name());
                           it != symbolIds.observables.end()) {
                    id = it->second;
                }
                out << indent << "<ci> " << escapeXml(id) << " </ci>\n";
            }
            break;

        case ast::ExpressionKind::Unary:
            if (expr.name() == "-") {
                out << indent << "<apply>\n";
                out << indent << "  <minus/>\n";
                out << exprToMathML(expr.args()[0], indent + "  ", symbolIds);
                out << indent << "</apply>\n";
            } else if (expr.name() == "!") {
                out << indent << "<apply>\n";
                out << indent << "  <not/>\n";
                out << exprToMathML(expr.args()[0], indent + "  ", symbolIds);
                out << indent << "</apply>\n";
            } else {
                out << exprToMathML(expr.args()[0], indent, symbolIds);
            }
            break;

        case ast::ExpressionKind::Binary: {
            out << indent << "<apply>\n";
            const auto& op = expr.name();
            if (op == "+") out << indent << "  <plus/>\n";
            else if (op == "-") out << indent << "  <minus/>\n";
            else if (op == "*") out << indent << "  <times/>\n";
            else if (op == "/") out << indent << "  <divide/>\n";
            else if (op == "^" || op == "**") out << indent << "  <power/>\n";
            else if (op == "%") out << indent << "  <rem/>\n";
            else if (op == "==") out << indent << "  <eq/>\n";
            else if (op == "!=" || op == "~=") out << indent << "  <neq/>\n";
            else if (op == ">") out << indent << "  <gt/>\n";
            else if (op == ">=") out << indent << "  <geq/>\n";
            else if (op == "<") out << indent << "  <lt/>\n";
            else if (op == "<=") out << indent << "  <leq/>\n";
            else if (op == "&&") out << indent << "  <and/>\n";
            else if (op == "||") out << indent << "  <or/>\n";
            else if (op == "^^") out << indent << "  <xor/>\n";
            else out << indent << "  <times/>\n";

            out << exprToMathML(expr.args()[0], indent + "  ", symbolIds);
            out << exprToMathML(expr.args()[1], indent + "  ", symbolIds);
            out << indent << "</apply>\n";
            break;
        }

        case ast::ExpressionKind::Function:
        case ast::ExpressionKind::ObservableRef: {
            const auto& funcName = expr.name();
            if (funcName == "time" && expr.args().empty()) {
                out << indent
                    << "<csymbol encoding=\"text\" "
                    << "definitionURL=\"http://www.sbml.org/sbml/symbols/time\">"
                    << " time </csymbol>\n";
                break;
            }
            // Built-in math functions
            if (funcName == "exp" || funcName == "log" || funcName == "ln" ||
                funcName == "sin" || funcName == "cos" || funcName == "tan" ||
                funcName == "asin" || funcName == "acos" || funcName == "atan" ||
                funcName == "sinh" || funcName == "cosh" || funcName == "tanh" ||
                funcName == "asinh" || funcName == "acosh" || funcName == "atanh" ||
                funcName == "abs" || funcName == "sqrt" || funcName == "floor" ||
                funcName == "ceil" || funcName == "ceiling" ||
                funcName == "min" || funcName == "max") {
                // SBML Level 2 does not permit the Level 3 <min/> and
                // <max/> MathML operators.  Lower an n-ary extremum to
                // nested piecewise expressions so the declared L2V3
                // document remains valid without changing the writer's
                // historical output level.  This must happen before opening
                // <apply>: piecewise is an expression, not an operator.
                if (funcName == "min" || funcName == "max") {
                    const auto& args = expr.args();
                    if (args.empty()) {
                        out << indent << "<cn> NaN </cn>\n";
                    } else {
                        const bool isMin = funcName == "min";
                        const std::function<std::string(std::size_t, std::size_t, const std::string&)>
                            emitExtremum = [&](std::size_t first, std::size_t last,
                                               const std::string& levelIndent) {
                                if (first == last) {
                                    return exprToMathML(args[first], levelIndent, symbolIds);
                                }
                                std::ostringstream nested;
                                nested << levelIndent << "<piecewise>\n";
                                nested << levelIndent << "  <piece>\n";
                                nested << emitExtremum(first, last - 1, levelIndent + "    ");
                                nested << levelIndent << "    <apply>\n";
                                nested << levelIndent << "      <"
                                       << (isMin ? "lt" : "gt") << "/>\n";
                                nested << emitExtremum(first, last - 1, levelIndent + "      ");
                                nested << exprToMathML(args[last], levelIndent + "      ", symbolIds);
                                nested << levelIndent << "    </apply>\n";
                                nested << levelIndent << "  </piece>\n";
                                nested << levelIndent << "  <otherwise>\n";
                                nested << exprToMathML(args[last], levelIndent + "    ", symbolIds);
                                nested << levelIndent << "  </otherwise>\n";
                                nested << levelIndent << "</piecewise>\n";
                                return nested.str();
                            };
                        out << emitExtremum(0, args.size() - 1, indent);
                    }
                    break;
                }
                out << indent << "<apply>\n";
                if (funcName == "ln" || funcName == "log") {
                    out << indent << "  <ln/>\n";
                } else if (funcName == "exp") {
                    out << indent << "  <exp/>\n";
                } else if (funcName == "sqrt") {
                    out << indent << "  <root/>\n";
                } else if (funcName == "abs") {
                    out << indent << "  <abs/>\n";
                } else if (funcName == "floor") {
                    out << indent << "  <floor/>\n";
                } else if (funcName == "ceil" || funcName == "ceiling") {
                    out << indent << "  <ceiling/>\n";
                } else {
                    const auto sbmlFunctionName = [&]() -> const char* {
                        if (funcName == "asin") return "arcsin";
                        if (funcName == "acos") return "arccos";
                        if (funcName == "atan") return "arctan";
                        if (funcName == "asinh") return "arcsinh";
                        if (funcName == "acosh") return "arccosh";
                        if (funcName == "atanh") return "arctanh";
                        return funcName.c_str();
                    }();
                    out << indent << "  <" << sbmlFunctionName << "/>\n";
                }
                for (const auto& arg : expr.args()) {
                    out << exprToMathML(arg, indent + "  ", symbolIds);
                }
                out << indent << "</apply>\n";
            } else if (funcName == "if" && expr.args().size() == 3) {
                // Piecewise for if(cond, then, else)
                out << indent << "<piecewise>\n";
                out << indent << "  <piece>\n";
                out << exprToMathML(expr.args()[1], indent + "    ", symbolIds);
                out << exprToMathML(expr.args()[0], indent + "    ", symbolIds);
                out << indent << "  </piece>\n";
                out << indent << "  <otherwise>\n";
                out << exprToMathML(expr.args()[2], indent + "    ", symbolIds);
                out << indent << "  </otherwise>\n";
                out << indent << "</piecewise>\n";
            } else {
                // Reference to model-defined function or observable
                std::string id = funcName;
                if (expr.kind() == ast::ExpressionKind::ObservableRef) {
                    if (const auto it = symbolIds.observables.find(funcName);
                        it != symbolIds.observables.end()) {
                        id = it->second;
                    }
                } else if (const auto it = symbolIds.functions.find(funcName);
                           it != symbolIds.functions.end()) {
                    id = it->second;
                } else if (const auto it = symbolIds.observables.find(funcName);
                           it != symbolIds.observables.end()) {
                    id = it->second;
                } else if (const auto it = symbolIds.parameters.find(funcName);
                           it != symbolIds.parameters.end()) {
                    id = it->second;
                }
                out << indent << "<ci> " << escapeXml(id) << " </ci>\n";
            }
            break;
        }

        case ast::ExpressionKind::TableFunction: {
            // SBML Core has no table-function primitive.  Lower the finite
            // BNGL table to a MathML piecewise expression.  The interval
            // boundaries match Expression::evaluate: values below the first
            // point clamp to y[0], values at x[i] select that point, and
            // values above the last point clamp to y.back().
            const auto& xValues = expr.tableXValues();
            const auto& yValues = expr.tableYValues();
            if (xValues.empty() || xValues.size() != yValues.size()) {
                throw std::invalid_argument(
                    "SBML writer cannot lower an empty or mismatched BNGL table function");
            }
            for (std::size_t index = 0; index < xValues.size(); ++index) {
                if (!std::isfinite(xValues[index]) || !std::isfinite(yValues[index]) ||
                    (index > 0 && xValues[index] <= xValues[index - 1])) {
                    throw std::invalid_argument(
                        "SBML writer cannot lower a non-finite or non-monotone BNGL table function");
                }
            }
            if (expr.args().size() != 1) {
                throw std::invalid_argument(
                    "SBML writer cannot lower a table function without one counter expression");
            }

            auto emitNumber = [&](double value, const std::string& numberIndent) {
                std::ostringstream number;
                number << numberIndent << "<cn> " << std::setprecision(17)
                       << value << " </cn>\n";
                return number.str();
            };
            const auto& counter = expr.args().front();
            if (xValues.size() == 1) {
                out << emitNumber(yValues.front(), indent);
                break;
            }

            auto emitCondition = [&](double upper, const std::string& conditionIndent) {
                std::ostringstream condition;
                condition << conditionIndent << "<apply>\n"
                          << conditionIndent << "  <lt/>\n"
                          << exprToMathML(counter, conditionIndent + "  ", symbolIds)
                          << emitNumber(upper, conditionIndent + "  ")
                          << conditionIndent << "</apply>\n";
                return condition.str();
            };

            out << indent << "<piecewise>\n";
            // Match the native table evaluator below the first breakpoint.
            // The interval pieces use only an upper bound so that an exact
            // breakpoint belongs to the interval starting at that point.
            {
                const std::string pieceIndent = indent + "  ";
                out << pieceIndent << "<piece>\n";
                const std::string valueIndent = pieceIndent + "  ";
                out << emitNumber(yValues.front(), valueIndent)
                    << emitCondition(xValues.front(), valueIndent)
                    << pieceIndent << "</piece>\n";
            }
            for (std::size_t index = 0; index + 1 < xValues.size(); ++index) {
                const std::string pieceIndent = indent + "  ";
                out << pieceIndent << "<piece>\n";
                const std::string valueIndent = pieceIndent + "  ";
                if (expr.tableMethod() == "step") {
                    out << emitNumber(yValues[index], valueIndent);
                } else {
                    const double denominator = xValues[index + 1] - xValues[index];
                    out << valueIndent << "<apply>\n"
                        << valueIndent << "  <plus/>\n"
                        << emitNumber(yValues[index], valueIndent + "  ")
                        << valueIndent << "  <apply>\n"
                        << valueIndent << "    <times/>\n"
                        << valueIndent << "      <apply>\n"
                        << valueIndent << "        <divide/>\n"
                        << valueIndent << "          <apply>\n"
                        << valueIndent << "            <minus/>\n"
                        << exprToMathML(counter, valueIndent + "            ", symbolIds)
                        << emitNumber(xValues[index], valueIndent + "            ")
                        << valueIndent << "          </apply>\n"
                        << emitNumber(denominator, valueIndent + "          ")
                        << valueIndent << "        </apply>\n"
                        << valueIndent << "        <apply>\n"
                        << valueIndent << "          <minus/>\n"
                        << emitNumber(yValues[index + 1], valueIndent + "          ")
                        << emitNumber(yValues[index], valueIndent + "          ")
                        << valueIndent << "        </apply>\n"
                        << valueIndent << "      </apply>\n"
                        << valueIndent << "    </apply>\n"
                        << valueIndent << "  </apply>\n";
                }
                out << emitCondition(xValues[index + 1], valueIndent)
                    << pieceIndent << "</piece>\n";
            }
            out << indent << "  <otherwise>\n"
                << emitNumber(yValues.back(), indent + "    ")
                << indent << "  </otherwise>\n"
                << indent << "</piecewise>\n";
            break;
        }
    }

    return out.str();
}

std::string SbmlWriter::rateLawToMathML(
    const ast::Rxn& rxn,
    const ast::Model& model,
    const engine::GeneratedNetwork& network,
    const std::string& indent,
    const SymbolIds& symbolIds) {
    std::ostringstream out;
    out << std::setprecision(17);

    // Build rate expression: unitFactor * statFactor * rateConstant * reactants.
    // The ODE engine and NetWriter apply compartment conversion to the
    // generated network rate. SBML must carry the same factor or a
    // round-trip changes bimolecular/zero-order kinetics.
    // If the rate law has a functional expression, use that; otherwise parse the rate string

    std::vector<std::string> terms;
    const auto unitFactor = NetWriter::computeUnitConversionFactor(rxn, model, network);
    const bool totalRate = hasTotalRateModifier(model, rxn.getOriginRuleName());
    // A TotalRate rule already carries the complete SBML flux.  Preserve the
    // network statistical factor, however: repeated identical reactants use
    // it to account for reaction multiplicity (for example 1/4! for four
    // identical reactants).  Only the compartment/unit conversion is already
    // present in the complete TotalRate expression.
    double combinedFactor = rxn.getFactor();
    if (!totalRate && unitFactor.has_value()) combinedFactor *= *unitFactor;

    // Handle the rate expression
    const auto& rateExpr = rxn.getRateExpression();
    // Preserve the complete parsed rate expression for compound laws.  Treating
    // a binary expression as an SBML identifier silently produced an undefined
    // symbol such as ``_2_5____c_A...`` and made SBML -> BNGL -> SBML lossy.
    // A bare identifier still uses the elementary branch below so model
    // parameters and zero-argument user functions retain their existing
    // representation.
    bool hasExpressionRate = rateExpr.has_value() &&
        rateExpr->kind() != ast::ExpressionKind::Identifier;

    if (hasExpressionRate) {
        // Functional or compound rate law - emit the expression with reactant
        // multiplication.  Model-defined functions and observables are emitted
        // as references by exprToMathML and are declared by assignment rules.
        out << indent << "<apply>\n";
        out << indent << "  <times/>\n";

        if (std::abs(combinedFactor - 1.0) > 1e-12) {
            out << indent << "  <cn> " << combinedFactor << " </cn>\n";
        }

        // Function call in MathML - just reference the function name
        out << exprToMathML(*rateExpr, indent + "  ", symbolIds);

        // TotalRate expressions already contain the complete SBML flux.
        // Ordinary BNGL rate expressions are coefficients and retain the
        // mass-action reactant factors in the SBML kinetic law.
        if (!totalRate) {
            for (const auto idx : rxn.getReactants()) {
                out << indent << "  <ci> S" << (idx + 1) << " </ci>\n";
            }
        }

        out << indent << "</apply>\n";
    } else {
        // Elementary mass-action rate law
        // Try to parse rate as number, or reference parameter
        const std::string& rateLaw = rxn.getRateLaw();

        // Strip any |local: suffix from rate law
        std::string cleanRate = rateLaw;
        auto localPos = cleanRate.find("|local:");
        if (localPos != std::string::npos) {
            cleanRate = cleanRate.substr(0, localPos);
        }

        bool isNumeric = false;
        double rateVal = 0.0;
        try {
            std::size_t pos = 0;
            rateVal = std::stod(cleanRate, &pos);
            if (pos == cleanRate.size()) isNumeric = true;
        } catch (...) {}

        // Count total multiplication terms
        int termCount = 0;
        if (std::abs(combinedFactor - 1.0) > 1e-12) termCount++;
        termCount++; // rate constant
        if (!totalRate) {
            termCount += static_cast<int>(rxn.getReactants().size());
        }

        if (termCount <= 1) {
            // Just the rate constant
            if (isNumeric) {
                double combined = combinedFactor * rateVal;
                out << indent << "<cn> " << combined << " </cn>\n";
            } else {
                std::string id = makeValidSBMLId(cleanRate);
                if (const auto it = symbolIds.parameters.find(cleanRate);
                    it != symbolIds.parameters.end()) {
                    id = it->second;
                } else if (const auto it = symbolIds.functions.find(cleanRate);
                           it != symbolIds.functions.end()) {
                    id = it->second;
                }
                out << indent << "<ci> " << escapeXml(id) << " </ci>\n";
            }
        } else {
            out << indent << "<apply>\n";
            out << indent << "  <times/>\n";

            if (isNumeric) {
                double combined = combinedFactor * rateVal;
                out << indent << "  <cn> " << combined << " </cn>\n";
            } else {
                if (std::abs(combinedFactor - 1.0) > 1e-12) {
                    out << indent << "  <cn> " << combinedFactor << " </cn>\n";
                }
                std::string id = makeValidSBMLId(cleanRate);
                if (const auto it = symbolIds.parameters.find(cleanRate);
                    it != symbolIds.parameters.end()) {
                    id = it->second;
                } else if (const auto it = symbolIds.functions.find(cleanRate);
                           it != symbolIds.functions.end()) {
                    id = it->second;
                }
                out << indent << "  <ci> " << escapeXml(id) << " </ci>\n";
            }

            // Ordinary BNGL rates are coefficients and need their reactant
            // factors. TotalRate laws already contain the complete flux.
            if (!totalRate) {
                for (const auto idx : rxn.getReactants()) {
                    out << indent << "  <ci> S" << (idx + 1) << " </ci>\n";
                }
            }

            out << indent << "</apply>\n";
        }
    }

    return out.str();
}

} // namespace bng::io
