#include "HybridModelGenerator.hpp"

#include <cctype>
#include <fstream>
#include <iostream>
#include <set>
#include <unordered_map>
#include <sstream>
#include <stdexcept>

#include "parser/antlr_compat.hpp"
#include "antlr4-runtime.h"
#include "BNGLexer.h"
#include "BNGParser.h"
#include "parser/BNGAstVisitor.hpp"
#include "parser/PatternGraphBuilder.hpp"
#include "core/PatternMatching.hpp"
#include "core/Ullmann.hpp"
#include "io/BnglWriter.hpp"
#include "ast/RefineRule.hpp"

namespace bng::engine {

namespace {

bool hmgIsBondNode(const BNGcore::Node& node) {
    return node.get_type().get_type_name() == BNGcore::BOND_NODE_TYPE.get_type_name();
}

bool hmgIsComponentNode(const BNGcore::Node& node) {
    if (hmgIsBondNode(node)) return false;
    for (auto edge = node.edges_in_begin(); edge != node.edges_in_end(); ++edge) {
        if (!hmgIsBondNode(**edge)) return true;
    }
    return false;
}

bool hmgIsMoleculeNode(const BNGcore::Node& node) {
    return !hmgIsBondNode(node) && !hmgIsComponentNode(node);
}

bool hmgIsWildcardBondNode(const BNGcore::Node& node) {
    if (!hmgIsBondNode(node) || node.in_degree() != 1) return false;
    const auto st = node.get_state().get_BNG2_string();
    return st == "!+" || st == "!?";
}

bool hmgIsExactPatternAutomorphism(const BNGcore::PatternGraph& pattern,
                                   const BNGcore::Map& map) {
    for (auto it = pattern.begin(); it != pattern.end(); ++it) {
        const auto* source = *it;
        const auto* target = map.mapf(*it);
        if (target == nullptr) return false;
        if (!(source->get_type() == target->get_type())) return false;
        if (source->get_state().get_BNG2_string() != target->get_state().get_BNG2_string())
            return false;
        if (hmgIsMoleculeNode(*source) != hmgIsMoleculeNode(*target)) return false;
        if (hmgIsMoleculeNode(*source) &&
            source->get_compartment() != target->get_compartment())
            return false;
        if (source->in_degree() != target->in_degree() ||
            source->out_degree() != target->out_degree())
            return false;
    }
    return true;
}

std::size_t hmgCountExactPatternAutomorphisms(const BNGcore::PatternGraph& pattern) {
    if (pattern.empty()) return 0;
    BNGcore::UllmannSGIso matcher(pattern, pattern);
    BNGcore::List<BNGcore::Map> maps;
    matcher.find_maps(maps);
    bool hasWildcard = false;
    std::vector<BNGcore::Node*> keyNodes;
    for (auto it = pattern.begin(); it != pattern.end(); ++it) {
        if (hmgIsWildcardBondNode(**it)) hasWildcard = true;
        else keyNodes.push_back(*it);
    }
    if (!hasWildcard) {
        std::size_t count = 0;
        for (auto it = maps.begin(); it != maps.end(); ++it) {
            if (hmgIsExactPatternAutomorphism(pattern, *it)) ++count;
        }
        return count;
    }
    std::set<std::vector<const BNGcore::Node*>> uniqueAuts;
    for (auto it = maps.begin(); it != maps.end(); ++it) {
        if (!hmgIsExactPatternAutomorphism(pattern, *it)) continue;
        std::vector<const BNGcore::Node*> key;
        key.reserve(keyNodes.size());
        for (auto* pn : keyNodes) key.push_back(it->mapf(pn));
        uniqueAuts.insert(std::move(key));
    }
    return uniqueAuts.size();
}

struct ParsedScopePrefix {
    std::string raw;
    std::string name;
    std::string remainder;
};

ParsedScopePrefix splitLeadingScopePrefix(const std::string& text) {
    const std::size_t pos = text.find_first_not_of(" \t\r\n");
    if (pos == std::string::npos || text[pos] != '%') return {{}, {}, text};
    const std::size_t begin = pos + 1;
    if (begin >= text.size() ||
        !(std::isalpha(static_cast<unsigned char>(text[begin])) || text[begin] == '_')) {
        return {{}, {}, text};
    }
    std::size_t end = begin + 1;
    while (end < text.size() &&
           (std::isalnum(static_cast<unsigned char>(text[end])) || text[end] == '_')) {
        ++end;
    }
    if (end < text.size() && text[end] == ':') {
        std::size_t colonEnd = end + 1;
        if (colonEnd < text.size() && text[colonEnd] == ':') ++colonEnd;
        return {text.substr(pos, colonEnd - pos),
                text.substr(begin, end - begin),
                text.substr(colonEnd)};
    }
    return {{}, {}, text};
}

bool exprCanLiveInParameters(const ast::Expression& expr, const ast::Model& model) {
    switch (expr.kind()) {
    case ast::ExpressionKind::Number:
        return true;
    case ast::ExpressionKind::Identifier: {
        const auto& name = expr.name();
        if (name == "time" || name == "t") return false;
        return model.getParameters().contains(name);
    }
    case ast::ExpressionKind::Unary:
    case ast::ExpressionKind::Binary:
        for (const auto& arg : expr.args()) {
            if (!exprCanLiveInParameters(arg, model)) return false;
        }
        return true;
    case ast::ExpressionKind::Function: {
        const auto& fn = expr.name();
        for (const auto& modelFn : model.getFunctions()) {
            if (modelFn.getName() == fn) return false;
        }
        for (const auto& obs : model.getObservables()) {
            if (obs.getName() == fn) return false;
        }
        for (const auto& arg : expr.args()) {
            if (!exprCanLiveInParameters(arg, model)) return false;
        }
        return fn != "time" && fn != "tfun";
    }
    default:
        return false;
    }
}

bool exprMentionsIdentifier(const ast::Expression& expr, const std::string& name) {
    if (expr.kind() == ast::ExpressionKind::Identifier && expr.name() == name) return true;
    for (const auto& arg : expr.args()) {
        if (exprMentionsIdentifier(arg, name)) return true;
    }
    return false;
}

} // namespace

HybridModelGenerator::HybridModelGenerator(ast::Model& model) : model_(model) {}

bool HybridModelGenerator::isIsomorphic(const std::string& pattern1,
                                          const std::string& pattern2) const {
    // Use Ullmann subgraph isomorphism to check if two patterns are isomorphic.
    // Parse both patterns and check for bidirectional matching.
    try {
        auto& mutableModel = const_cast<ast::Model&>(model_);

        antlr4::ANTLRInputStream input1(pattern1);
        BNGLexer lexer1(&input1);
        antlr4::CommonTokenStream tokens1(&lexer1);
        BNGParser parser1(&tokens1);
        auto* species1 = parser1.species_def();
        if (parser1.getNumberOfSyntaxErrors() != 0) return false;
        const auto graph1 = bng::parser::buildPatternGraph(species1, mutableModel, false);

        antlr4::ANTLRInputStream input2(pattern2);
        BNGLexer lexer2(&input2);
        antlr4::CommonTokenStream tokens2(&lexer2);
        BNGParser parser2(&tokens2);
        auto* species2 = parser2.species_def();
        if (parser2.getNumberOfSyntaxErrors() != 0) return false;
        const auto graph2 = bng::parser::buildPatternGraph(species2, mutableModel, false);

        // A population lumps the particles of one compartment: @EC:L(r) and
        // @CP:L(r) are different species even though their graphs match.
        auto comp1 = bng::parser::extractSpeciesCompartment(species1);
        if (comp1.empty()) comp1 = ast::SpeciesGraph(graph1).inferCompartment(model_.getCompartments());
        auto comp2 = bng::parser::extractSpeciesCompartment(species2);
        if (comp2.empty()) comp2 = ast::SpeciesGraph(graph2).inferCompartment(model_.getCompartments());
        if (comp1 != comp2) {
            return false;
        }

        // Check both directions for isomorphism
        BNGcore::UllmannSGIso matcher1(graph1, graph2);
        BNGcore::List<BNGcore::Map> maps1;
        if (matcher1.find_maps(maps1) == 0) return false;

        BNGcore::UllmannSGIso matcher2(graph2, graph1);
        BNGcore::List<BNGcore::Map> maps2;
        if (matcher2.find_maps(maps2) == 0) return false;

        return true;
    } catch (...) {
        return false;
    }
}

std::size_t HybridModelGenerator::countMatches(const std::string& obsPattern,
                                                 const std::string& speciesPattern) const {
    try {
        auto& mutableModel = const_cast<ast::Model&>(model_);

        antlr4::ANTLRInputStream input1(obsPattern);
        BNGLexer lexer1(&input1);
        antlr4::CommonTokenStream tokens1(&lexer1);
        BNGParser parser1(&tokens1);
        auto* species1 = parser1.species_def();
        if (parser1.getNumberOfSyntaxErrors() != 0) return 0;
        const auto pattern = bng::parser::buildPatternGraph(species1, mutableModel, false);

        antlr4::ANTLRInputStream input2(speciesPattern);
        BNGLexer lexer2(&input2);
        antlr4::CommonTokenStream tokens2(&lexer2);
        BNGParser parser2(&tokens2);
        auto* species2 = parser2.species_def();
        if (parser2.getNumberOfSyntaxErrors() != 0) return 0;
        const auto target = bng::parser::buildPatternGraph(species2, mutableModel, false);
        auto observableCompartment =
            bng::parser::extractSpeciesCompartment(species1);
        if (observableCompartment.empty()) {
            observableCompartment =
                ast::SpeciesGraph(pattern).inferCompartment(model_.getCompartments());
        }
        auto targetCompartment =
            bng::parser::extractSpeciesCompartment(species2);
        if (targetCompartment.empty()) {
            targetCompartment =
                ast::SpeciesGraph(target).inferCompartment(model_.getCompartments());
        }
        if (!observableCompartment.empty() &&
            observableCompartment != targetCompartment) {
            return 0;
        }

        return bng::core::countPatternMatches(pattern, target);
    } catch (...) {
        return 0;
    }
}

HybridModelGenerator::GenerateResult
HybridModelGenerator::generate(const std::filesystem::path& sourcePath, const Options& opts) {
    GenerateResult result;

    const std::string indent = "    ";

    std::cerr << "ACTION: generate_hybrid_model( " << model_.getModelName() << " )\n";

    // Print options
    std::cerr << "options = \n";
    if (!opts.prefix.empty())
        std::cerr << "      prefix => " << opts.prefix << "\n";
    std::cerr << "      suffix => " << opts.suffix << "\n";
    std::cerr << "   overwrite => " << opts.overwrite << "\n";
    std::cerr << "     verbose => " << opts.verbose << "\n";
    std::cerr << "        safe => " << opts.safe << "\n";
    std::cerr << "     execute => " << opts.execute << "\n";

    // === Step 0: Validate preconditions ===
    // Check if PopulationMaps exist (equivalent to PopulationTypesList/PopulationList)
    if (model_.getPopulationMaps().empty()) {
        throw std::runtime_error(
            "Nothing to do! Model " + model_.getModelName() +
            " has zero population map definitions.");
    }

    if (model_.getMoleculeTypes().empty()) {
        throw std::runtime_error(
            "Nothing to do! Model " + model_.getModelName() +
            " has zero molecule type definitions.");
    }

    if (model_.getSeedSpecies().empty()) {
        throw std::runtime_error(
            "Nothing to do! Model " + model_.getModelName() +
            " has zero seed species definitions.");
    }

    if (model_.getReactionRules().empty()) {
        throw std::runtime_error(
            "Nothing to do! Model " + model_.getModelName() +
            " has zero reaction rule definitions.");
    }

    // Determine output paths
    // prefix = defined prefix ? model.getOutputPrefix(prefix) : model.getOutputPrefix()
    // prefix += "_" + suffix
    std::string prefix;
    if (!opts.prefix.empty()) {
        const std::filesystem::path prefixPath(opts.prefix);
        if (prefixPath.is_relative() && !sourcePath.parent_path().empty()) {
            prefix = (sourcePath.parent_path() / prefixPath).string();
        } else {
            prefix = opts.prefix;
        }
    } else {
        prefix = (sourcePath.parent_path() / sourcePath.stem()).string();
    }
    prefix += "_" + opts.suffix;

    const std::string modelname = std::filesystem::path(prefix).filename().string();
    const auto outdir = std::filesystem::path(prefix).parent_path();
    const std::string modelfile = prefix + ".bngl";

    result.hybridBnglPath = modelfile;
    result.hybridModelName = modelname;

    // Check if file exists
    if (std::filesystem::exists(modelfile)) {
        if (opts.overwrite) {
            std::cerr << "WARNING: Overwriting older model file: " << modelfile << "\n";
            std::filesystem::remove(modelfile);
        } else {
            throw std::runtime_error(
                "Model file " + modelfile +
                " already exists. Set overwrite=>1 option to force overwrite.");
        }
    }

    // === Create new hybrid model ===
    ast::Model hybridModel;

    // Step 1: Copy metadata
    hybridModel.setModelName(modelname);
    hybridModel.setVersion(model_.getVersion());
    hybridModel.setSubstanceUnits(model_.getSubstanceUnits());

    // Copy options
    for (const auto& [key, value] : model_.getOptions()) {
        hybridModel.setOption(key, value);
    }

    // === Step 2: Copy constant parameters ===
    std::size_t stepIndex = 0;
    std::cerr << indent << stepIndex << ":Fetching model parameters.. ";
    ++stepIndex;

    std::size_t nConstants = 0;
    for (const auto& param : model_.getParameters().all()) {
        // Copy all parameters (constants and expressions, but not observables/functions)
        // In Perl, copyConstant() copies parameters that are Constants or Expressions
        hybridModel.addParameter(ast::Parameter(param.getName(), param.getExpression()));
        ++nConstants;
    }
    result.nParameters = nConstants;
    std::cerr << "found " << nConstants << " constants and expressions.\n";

    // === Step 3: Copy compartments ===
    if (!model_.getCompartments().empty()) {
        std::cerr << indent << stepIndex << ":Fetching compartments.. ";
        ++stepIndex;
        for (const auto& comp : model_.getCompartments()) {
            hybridModel.addCompartment(comp);
        }
        result.nCompartments = model_.getCompartments().size();
        std::cerr << indent << "found " << result.nCompartments << " compartments.\n";
        if (result.nCompartments > 0) {
            // BNG2 warns that it does not support compartments here and fails
            // to build its mapping rules.  BNG3 places each population in the
            // compartment of its mapped species, keeps the compartment on
            // child rule species, and applies BNG2's interacting-set check;
            // there is no BNG2 result to compare this with.
            std::cerr << "WARNING: generate_hybrid_model() with compartments has no BNG2 "
                         "reference: populations are placed in the compartment of their "
                         "mapped species.\n";
        }
    }

    // === Step 4: Copy molecule types + add population types ===
    std::cerr << indent << stepIndex << ":Fetching molecule types..   ";
    ++stepIndex;
    for (const auto& mt : model_.getMoleculeTypes()) {
        hybridModel.addMoleculeType(mt);
    }
    result.nMoleculeTypes = model_.getMoleculeTypes().size();
    std::cerr << "found " << result.nMoleculeTypes << " molecule types.\n";

    // Add population types (derived from population maps)
    // In Perl, population types come from PopulationTypesList. In our C++ model,
    // population types are derived from the population map entries.
    // Each population map has a pattern and a population function.
    // We need to extract unique molecule type names that serve as population types.
    std::cerr << indent << stepIndex << ":Adding population types..   ";
    ++stepIndex;

    std::unordered_map<std::string, bool> existingMtPopulationTypes;
    for (const auto& mt : model_.getMoleculeTypes()) {
        existingMtPopulationTypes.emplace(mt.getName(), mt.isPopulation());
    }

    // Extract population type names from population maps
    // The population function typically creates a new molecule type for the population
    std::set<std::string> popTypeNames;
    std::size_t populationMapRuleIndex = 0;
    for (const auto& pm : model_.getPopulationMaps()) {
        // The population function name is used as a molecule type for the population
        // In Perl: PopulationTypesList->MolTypes contains the population molecule types
        const auto& populationName = !pm.populationName.empty()
            ? pm.populationName : pm.populationFunction;
        if (!populationName.empty()) popTypeNames.insert(populationName);
    }

    std::size_t nPopTypes = 0;
    for (const auto& name : popTypeNames) {
        const auto existing = existingMtPopulationTypes.find(name);
        if (existing != existingMtPopulationTypes.end()) {
            if (!existing->second) {
                throw std::runtime_error(
                    "PopulationType " + name + " clashes with MoleculeType of the same name");
            }
            ++nPopTypes;
            continue;
        }
        // Add a simple population molecule type (no components)
        ast::MoleculeType popMt(name, {}, true);
        hybridModel.addMoleculeType(popMt);
        ++nPopTypes;
    }
    result.nPopulationTypes = nPopTypes;
    result.nMoleculeTypes += nPopTypes;
    std::cerr << "found " << nPopTypes << " population types.\n";

    // === Step 5: Copy seed species, replacing with populations if isomorphic ===
    std::cerr << indent << stepIndex << ":Fetching seed species..\n";
    ++stepIndex;

    // Build a list of population patterns for isomorphism checking
    // Each population map has a patternText (the species) and a populationFunction (the pop variable)
    struct PopInfo {
        std::string speciesPattern;   // The species graph pattern
        std::string populationName;   // The population molecule type name
        std::string compartment;      // Species-level compartment of the pattern
    };
    auto speciesCompartmentOf = [&](const std::string& text) {
        antlr4::ANTLRInputStream input(text);
        BNGLexer lexer(&input);
        antlr4::CommonTokenStream tokens(&lexer);
        BNGParser parser(&tokens);
        auto* species = parser.species_def();
        if (parser.getNumberOfSyntaxErrors() != 0) return std::string();
        auto comp = bng::parser::extractSpeciesCompartment(species);
        if (comp.empty() && !model_.getCompartments().empty()) {
            const auto graph = bng::parser::buildPatternGraph(species, model_, false);
            comp = ast::SpeciesGraph(graph).inferCompartment(model_.getCompartments());
        }
        return comp;
    };
    std::vector<PopInfo> populations;
    for (const auto& pm : model_.getPopulationMaps()) {
        PopInfo pi;
        pi.speciesPattern = pm.patternText;
        pi.populationName = !pm.populationName.empty() ? pm.populationName : pm.populationFunction;
        pi.compartment = speciesCompartmentOf(pm.patternText);
        // Build the population species string: just the population function name with args
        // In Perl: $pop->Population is the population molecule SpeciesGraph
        populations.push_back(pi);
    }

    std::set<std::string> addedPopulations;  // Track population/compartment instances
    const auto populationIdentity = [](const std::string& name,
                                       const std::string& compartment) {
        return name + "\x1f" + compartment;
    };

    for (const auto& species : model_.getSeedSpecies()) {
        const std::string& pattern = species.getPattern();
        const std::string fullPattern = species.getCompartment().empty() ||
                                                pattern.find('@') != std::string::npos
                                            ? pattern
                                            : "@" + species.getCompartment() + ":" + pattern;
        bool isPop = false;

        // Check if this species is isomorphic to any population
        for (const auto& pop : populations) {
            if (isIsomorphic(fullPattern, pop.speciesPattern)) {
                // Replace with population species
                // In Perl: $slist_new->add($pop->Population->copy(), $species->Concentration)
                hybridModel.addSeedSpecies(ast::SeedSpecies(
                    pop.populationName + "()",
                    species.getAmount(),
                    species.isConstant(),
                    species.getCompartment()));
                addedPopulations.insert(
                    populationIdentity(pop.populationName, species.getCompartment()));
                isPop = true;

                if (opts.verbose) {
                    std::cerr << indent << indent
                              << "replaced species " << pattern
                              << " with population " << pop.populationName << "().\n";
                }
                break;
            }
        }

        if (!isPop) {
            // Not a population, add directly
            hybridModel.addSeedSpecies(species);
        }
    }
    result.nSeedSpecies = hybridModel.getSeedSpecies().size();
    std::cerr << indent << "  ..found " << result.nSeedSpecies << " seed species.\n";

    // === Step 6: Add empty populations for populations not yet in seed species ===
    std::cerr << indent << stepIndex
              << ":Adding populations with zero counts to seed species..\n";
    ++stepIndex;

    std::size_t zeroPops = 0;
    for (const auto& pop : populations) {
        const auto identity = populationIdentity(pop.populationName, pop.compartment);
        if (addedPopulations.count(identity) == 0) {
            hybridModel.addSeedSpecies(ast::SeedSpecies(
                pop.populationName + "()",
                ast::Expression::number(0),
                false,
                pop.compartment));
            addedPopulations.insert(identity);
            ++zeroPops;
        }
    }
    result.nZeroPopulations = zeroPops;
    std::cerr << indent << "  ..added " << zeroPops << " populations to seed species list.\n";

    // === Step 7: Copy observables and add population pattern matches ===
    std::cerr << indent << stepIndex
              << ":Fetching observables and adding population matches..\n";
    ++stepIndex;

    struct ObservableCountPredicate {
        std::string pattern;
        std::string relation;
        std::size_t quantity;
    };
    const auto countPredicate = [](const std::string& text)
        -> std::optional<ObservableCountPredicate> {
        antlr4::ANTLRInputStream input(text);
        BNGLexer lexer(&input);
        antlr4::CommonTokenStream tokens(&lexer);
        BNGParser parser(&tokens);
        auto* predicate = parser.observable_pattern();
        if (parser.getNumberOfSyntaxErrors() != 0 || predicate->INT() == nullptr) {
            return std::nullopt;
        }
        std::string relation;
        if (predicate->EQUALS() != nullptr) relation = "==";
        else if (predicate->GTE() != nullptr) relation = ">=";
        else if (predicate->LTE() != nullptr) relation = "<=";
        else if (predicate->GT() != nullptr) relation = ">";
        else if (predicate->LT() != nullptr) relation = "<";
        if (relation.empty()) return std::nullopt;

        std::string pattern;
        if (predicate->species_def() != nullptr) {
            pattern = predicate->species_def()->getText();
        } else if (predicate->STRING() != nullptr) {
            pattern = predicate->STRING()->getText();
            if (predicate->LPAREN() != nullptr) pattern += "()";
        } else {
            return std::nullopt;
        }
        return ObservableCountPredicate {
            std::move(pattern), std::move(relation),
            static_cast<std::size_t>(std::stoull(predicate->INT()->getText()))};
    };
    const auto satisfiesPredicate = [](std::size_t matches,
                                       const ObservableCountPredicate& predicate) {
        if (predicate.relation == "==") return matches == predicate.quantity;
        if (predicate.relation == ">=") return matches >= predicate.quantity;
        if (predicate.relation == "<=") return matches <= predicate.quantity;
        if (predicate.relation == ">") return matches > predicate.quantity;
        if (predicate.relation == "<") return matches < predicate.quantity;
        return false;
    };

    const auto optionValue = [&](const std::string& key) -> std::string {
        const auto found = model_.getOptions().find(key);
        return found != model_.getOptions().end() ? found->second : std::string();
    };
    const bool moleculesCountUnique = optionValue("MoleculesObservables") == "CountUnique";
    const bool speciesCountUnique = optionValue("SpeciesObservables") == "CountUnique";

    const auto patternAutomorphismCount = [&](const std::string& text) -> std::size_t {
        try {
            antlr4::ANTLRInputStream input(text);
            BNGLexer lexer(&input);
            antlr4::CommonTokenStream tokens(&lexer);
            BNGParser parser(&tokens);
            auto* species = parser.species_def();
            if (parser.getNumberOfSyntaxErrors() != 0) return 1;
            const auto graph = bng::parser::buildPatternGraph(species, model_, false);
            const std::size_t aut = hmgCountExactPatternAutomorphisms(graph);
            return aut > 0 ? aut : 1;
        } catch (...) {
            return 1;
        }
    };

    for (const auto& obs : model_.getObservables()) {
        // Copy the observable
        std::vector<std::string> patterns = obs.getPatterns();

        // A Molecules observable counts embeddings (divided by |Aut(pattern)|
        // when MoleculesObservables=CountUnique), while a Species observable
        // contributes once when its pattern (and any stoichiometry predicate)
        // matches the concrete graph represented by a population (short-
        // circuiting across terms when SpeciesObservables=CountUnique).
        const bool speciesObservable = obs.getType() == "Species";
        std::vector<bool> speciesPopTerminated(populations.size(), false);
        for (const auto& obsPattern : obs.getPatterns()) {
            const auto predicate = speciesObservable
                ? countPredicate(obsPattern) : std::nullopt;
            const std::string& sourcePattern = predicate ? predicate->pattern : obsPattern;
            const std::string observableCompartment = speciesCompartmentOf(sourcePattern);
            const std::size_t automorphisms = (!speciesObservable && moleculesCountUnique)
                ? patternAutomorphismCount(sourcePattern)
                : 1;
            std::set<std::string> matchedMappings;
            for (std::size_t popIdx = 0; popIdx < populations.size(); ++popIdx) {
                const auto& pop = populations[popIdx];
                if (speciesObservable && speciesCountUnique && speciesPopTerminated[popIdx]) {
                    continue;
                }
                const std::size_t rawMatches = predicate
                    ? countMatches(predicate->pattern, pop.speciesPattern)
                    : countMatches(obsPattern, pop.speciesPattern);
                const std::size_t matches = (!speciesObservable && moleculesCountUnique &&
                                             automorphisms > 1 && rawMatches % automorphisms == 0)
                    ? (rawMatches / automorphisms)
                    : rawMatches;
                const bool speciesMatch = predicate
                    ? satisfiesPredicate(rawMatches, *predicate)
                    : rawMatches > 0;
                if (speciesObservable && speciesCountUnique &&
                    (predicate.has_value() || speciesMatch)) {
                    speciesPopTerminated[popIdx] = true;
                }
                if (!(speciesObservable ? speciesMatch : matches > 0)) continue;

                std::string populationPattern = pop.populationName + "()";
                if (!observableCompartment.empty()) {
                    populationPattern = "@" + observableCompartment + ":" + populationPattern;
                }
                // An unqualified NFsim population pattern already counts all
                // compartments of one population type. Add it only once when
                // the same type represents that particle pattern in multiple
                // compartments; qualified observables keep compartment-local
                // population patterns distinct.
                std::string mappedParticlePattern = pop.speciesPattern;
                if (!mappedParticlePattern.empty() && mappedParticlePattern.front() == '@') {
                    const auto separator = mappedParticlePattern.find(':');
                    if (separator != std::string::npos) {
                        mappedParticlePattern.erase(0, separator + 1);
                    }
                }
                const std::string mappingIdentity =
                    pop.populationName + "\x1f" + mappedParticlePattern +
                    (observableCompartment.empty() ? "" : "\x1f" + pop.compartment);
                if (!matchedMappings.insert(mappingIdentity).second) continue;

                const std::size_t copies = speciesObservable ? 1 : matches;
                for (std::size_t m = 0; m < copies; ++m) {
                    patterns.push_back(populationPattern);
                }
                if (opts.verbose) {
                    std::cerr << indent << indent
                              << "observable '" << obs.getName() << "':  +"
                              << matches << " match"
                              << (matches > 1 ? "es" : "")
                              << " to " << populationPattern << ".\n";
                }
            }
        }

        hybridModel.addObservable(ast::Observable(
            obs.getName(), obs.getType(), patterns));
    }
    result.nObservables = model_.getObservables().size();
    std::cerr << indent << "  ..found " << result.nObservables << " observables.\n";

    // === Step 8: Copy functions ===
    std::cerr << indent << stepIndex << ":Fetching functions.. ";
    ++stepIndex;

    for (const auto& func : model_.getFunctions()) {
        hybridModel.addFunction(func);
    }
    result.nFunctions = model_.getFunctions().size();
    std::cerr << "found " << result.nFunctions << " functions.\n";

    for (const auto& action : model_.getSimulationProtocol()) {
        hybridModel.addProtocolAction(action);
    }

    // === Step 9: Expand rules w.r.t. populations ===
    std::cerr << indent << stepIndex
              << ":Expanding rules with respect to population objects..\n";
    ++stepIndex;

    // Get the species patterns for each population
    std::vector<ast::SpeciesGraph> popSpeciesPatterns;
    std::vector<ast::SpeciesGraph> populationGraphs;
    for (const auto& pop : populations) {
        antlr4::ANTLRInputStream particleInput(pop.speciesPattern);
        BNGLexer particleLexer(&particleInput);
        antlr4::CommonTokenStream particleTokens(&particleLexer);
        BNGParser particleParser(&particleTokens);
        auto* particleSpecies = particleParser.species_def();
        if (particleParser.getNumberOfSyntaxErrors() != 0) {
            throw std::runtime_error("Invalid population map species pattern: " +
                                     pop.speciesPattern);
        }
        auto particleGraph = bng::parser::buildPatternGraph(particleSpecies, model_, false);
        auto particleComp = bng::parser::extractSpeciesCompartment(particleSpecies);
        if (particleComp.empty() && !model_.getCompartments().empty()) {
            particleComp = ast::SpeciesGraph(particleGraph).inferCompartment(model_.getCompartments());
        }
        popSpeciesPatterns.emplace_back(std::move(particleGraph), std::move(particleComp));

        antlr4::ANTLRInputStream populationInput(pop.populationName + "()");
        BNGLexer populationLexer(&populationInput);
        antlr4::CommonTokenStream populationTokens(&populationLexer);
        BNGParser populationParser(&populationTokens);
        auto* populationSpecies = populationParser.species_def();
        if (populationParser.getNumberOfSyntaxErrors() != 0) {
            throw std::runtime_error("Invalid population species type: " +
                                     pop.populationName);
        }
        populationGraphs.emplace_back(
            bng::parser::buildPatternGraph(populationSpecies, hybridModel, true),
            pop.compartment);
    }

    // Compartment topology for the interacting-set check in restrictRule,
    // as network generation installs it.
    std::unordered_map<std::string, int> compartmentDimensions;
    std::unordered_map<std::string, std::string> compartmentParents;
    for (const auto& compartment : model_.getCompartments()) {
        compartmentDimensions[compartment.getName()] = compartment.getDimension();
        if (!compartment.getParent().empty()) {
            compartmentParents[compartment.getName()] = compartment.getParent();
        }
    }
    ast::CompartmentContextScope compartmentScope(compartmentDimensions, compartmentParents);

    const auto evaluateObservableOnSpeciesPattern =
        [&](const ast::Observable& obs, const std::string& speciesPat) -> std::size_t {
        const bool isSpeciesObs = obs.getType() == "Species";
        std::size_t total = 0;
        for (const auto& obsPattern : obs.getPatterns()) {
            const auto predicate = isSpeciesObs ? countPredicate(obsPattern) : std::nullopt;
            const std::string& sourcePat = predicate ? predicate->pattern : obsPattern;
            const std::size_t rawMatches = countMatches(sourcePat, speciesPat);
            if (isSpeciesObs) {
                const bool matched = predicate
                    ? satisfiesPredicate(rawMatches, *predicate)
                    : rawMatches > 0;
                if (matched) ++total;
                if (speciesCountUnique && (predicate.has_value() || matched)) break;
            } else {
                const std::size_t aut = moleculesCountUnique
                    ? patternAutomorphismCount(sourcePat)
                    : 1;
                total += (aut > 1 && rawMatches % aut == 0) ? (rawMatches / aut) : rawMatches;
            }
        }
        return total;
    };

    const auto specializeScopedExpression =
        [&](const auto& self,
            const ast::Expression& expr,
            const std::unordered_map<std::string, std::string>& scopeToSpecies,
            bool& substituted,
            int depth) -> ast::Expression {
        if (depth > 32) return expr;
        switch (expr.kind()) {
        case ast::ExpressionKind::Number:
        case ast::ExpressionKind::Identifier:
            return expr;
        case ast::ExpressionKind::Unary: {
            if (expr.args().empty()) return expr;
            auto child = self(self, expr.args()[0], scopeToSpecies, substituted, depth + 1);
            return ast::Expression::unary(expr.name(), std::move(child));
        }
        case ast::ExpressionKind::Binary: {
            if (expr.args().size() < 2) return expr;
            auto lhs = self(self, expr.args()[0], scopeToSpecies, substituted, depth + 1);
            auto rhs = self(self, expr.args()[1], scopeToSpecies, substituted, depth + 1);
            return ast::Expression::binary(expr.name(), std::move(lhs), std::move(rhs));
        }
        case ast::ExpressionKind::ObservableRef:
        case ast::ExpressionKind::Function: {
            const auto& fnName = expr.name();
            const auto& args = expr.args();
            // Scoped observable evaluation: Obs(x) where x is bound to a
            // concrete population species pattern.
            if (args.size() == 1 && args[0].kind() == ast::ExpressionKind::Identifier) {
                const auto scopeIt = scopeToSpecies.find(args[0].name());
                if (scopeIt != scopeToSpecies.end()) {
                    for (const auto& obs : model_.getObservables()) {
                        if (obs.getName() == fnName) {
                            substituted = true;
                            const std::size_t count =
                                evaluateObservableOnSpeciesPattern(obs, scopeIt->second);
                            return ast::Expression::number(static_cast<double>(count));
                        }
                    }
                }
            }
            if (expr.kind() == ast::ExpressionKind::ObservableRef) {
                std::vector<ast::Expression> newArgs;
                newArgs.reserve(args.size());
                for (const auto& arg : args) {
                    newArgs.push_back(self(self, arg, scopeToSpecies, substituted, depth + 1));
                }
                return ast::Expression::observableRef(fnName, std::move(newArgs));
            }
            // Scoped user function call: f(x, ...) where at least one argument
            // binds to a concrete population species pattern.
            for (const auto& modelFn : model_.getFunctions()) {
                if (modelFn.getName() != fnName ||
                    modelFn.getArgs().size() != args.size() ||
                    args.empty()) {
                    continue;
                }
                std::unordered_map<std::string, std::string> nestedScopes;
                bool anyBound = false;
                for (std::size_t ai = 0; ai < args.size(); ++ai) {
                    if (args[ai].kind() == ast::ExpressionKind::Identifier) {
                        const auto scopeIt = scopeToSpecies.find(args[ai].name());
                        if (scopeIt != scopeToSpecies.end()) {
                            nestedScopes[modelFn.getArgs()[ai]] = scopeIt->second;
                            anyBound = true;
                        }
                    }
                }
                if (anyBound) {
                    substituted = true;
                    return self(self, modelFn.getExpression(), nestedScopes, substituted, depth + 1);
                }
            }
            std::vector<ast::Expression> newArgs;
            newArgs.reserve(args.size());
            for (const auto& arg : args) {
                newArgs.push_back(self(self, arg, scopeToSpecies, substituted, depth + 1));
            }
            return ast::Expression::function(fnName, std::move(newArgs));
        }
        default:
            return expr;
        }
    };

    const auto findPopulationSpeciesPattern =
        [&](const std::string& popName, const std::string& comp) -> std::optional<std::string> {
        for (const auto& pop : populations) {
            if (pop.populationName == popName &&
                (comp.empty() || pop.compartment.empty() || pop.compartment == comp)) {
                return pop.speciesPattern;
            }
        }
        return std::nullopt;
    };

    std::size_t ruleCount = 0;
    for (const auto& rule : model_.getReactionRules()) {
        ast::RefineRuleParams refineParams;
        refineParams.verbose = opts.verbose;
        refineParams.safe = opts.safe;
        refineParams.populationParticleGraphs = &popSpeciesPatterns;
        refineParams.populationGraphs = &populationGraphs;
        auto expanded = ast::expandRule(
            rule, popSpeciesPatterns, model_, hybridModel, refineParams);
        const std::size_t childCount = expanded.childRules.size();
        for (auto& childRule : expanded.childRules) {
            // If any scoped reactant (%x:Pop()) was specialized to a concrete
            // population type, evaluate scoped functions referencing x against
            // that population's particle graph so the emitted hybrid rule is
            // self-contained and executable.
            std::unordered_map<std::string, std::string> boundPopScopes;
            std::vector<std::string> updatedReactants = childRule.getReactants();
            std::vector<std::string> updatedProducts = childRule.getProducts();
            for (std::size_t ri = 0; ri < updatedReactants.size(); ++ri) {
                const auto parsed = splitLeadingScopePrefix(updatedReactants[ri]);
                if (parsed.name.empty()) continue;
                std::string body = parsed.remainder;
                std::string comp;
                if (!body.empty() && body.front() == '@') {
                    const auto colon = body.find(':');
                    if (colon != std::string::npos) {
                        comp = body.substr(1, colon - 1);
                        body = body.substr(colon + 1);
                        if (!body.empty() && body.front() == ':') body.erase(0, 1);
                    }
                }
                const auto lparen = body.find('(');
                if (lparen != std::string::npos && body.find('.') == std::string::npos) {
                    const std::string molName = body.substr(0, lparen);
                    if (const auto sp = findPopulationSpeciesPattern(molName, comp)) {
                        boundPopScopes[parsed.name] = *sp;
                        updatedReactants[ri] = parsed.remainder;
                    }
                }
            }
            if (!boundPopScopes.empty() && !childRule.getRates().empty()) {
                bool substituted = false;
                const ast::Expression specialized = specializeScopedExpression(
                    specializeScopedExpression,
                    childRule.getRates()[0],
                    boundPopScopes,
                    substituted,
                    0);
                if (substituted) {
                    for (auto& prodStr : updatedProducts) {
                        const auto parsed = splitLeadingScopePrefix(prodStr);
                        if (!parsed.name.empty() &&
                            boundPopScopes.count(parsed.name) != 0 &&
                            !exprMentionsIdentifier(specialized, parsed.name)) {
                            prodStr = parsed.remainder;
                        }
                    }
                    std::string baseRule = childRule.getRuleName();
                    const auto cut = baseRule.rfind("_v");
                    if (cut != std::string::npos) baseRule = baseRule.substr(0, cut);
                    std::vector<ast::Expression> newRates;
                    if (exprCanLiveInParameters(specialized, model_)) {
                        std::string derivedName;
                        for (int suffix = 1;; ++suffix) {
                            derivedName = "_" + baseRule + "_local" + std::to_string(suffix);
                            if (!hybridModel.getParameters().contains(derivedName)) break;
                        }
                        hybridModel.addParameter(ast::Parameter(derivedName, specialized));
                        newRates.push_back(ast::Expression::identifier(derivedName));
                    } else {
                        std::string derivedName;
                        for (int suffix = 1;; ++suffix) {
                            derivedName = "_" + baseRule + "_local" + std::to_string(suffix);
                            bool exists = hybridModel.getParameters().contains(derivedName);
                            for (const auto& fn : hybridModel.getFunctions()) {
                                if (fn.getName() == derivedName) exists = true;
                            }
                            if (!exists) break;
                        }
                        hybridModel.addFunction(ast::Function(derivedName, {}, specialized));
                        newRates.push_back(ast::Expression::function(derivedName, {}));
                    }
                    for (std::size_t ri = 1; ri < childRule.getRates().size(); ++ri) {
                        newRates.push_back(childRule.getRates()[ri]);
                    }
                    ast::ReactionRule specializedRule(
                        childRule.getRuleName(),
                        childRule.getLabel(),
                        std::move(updatedReactants),
                        std::move(updatedProducts),
                        std::move(newRates),
                        childRule.getModifiers(),
                        childRule.isBidirectional(),
                        childRule.getReactantPatterns(),
                        childRule.getProductPatterns());
                    bool stillScoped = false;
                    for (const auto& rStr : specializedRule.getReactants()) {
                        if (!splitLeadingScopePrefix(rStr).name.empty()) stillScoped = true;
                    }
                    specializedRule.setHasScopePrefix(stillScoped);
                    if (childRule.getDelayExpression()) {
                        specializedRule.setDelay(*childRule.getDelayExpression(),
                                                 childRule.isNonConsuming());
                    }
                    if (childRule.hasDrivingWork()) {
                        specializedRule.setDrivingWorkExpression(childRule.drivingWorkExpression());
                    }
                    childRule = std::move(specializedRule);
                }
            }
            hybridModel.addReactionRule(std::move(childRule));
            ++ruleCount;
        }

        if (opts.verbose) {
            std::cerr << indent << indent << "Rule '" << rule.getRuleName()
                      << "': expanded to " << childCount << " child rule"
                      << (childCount == 1 ? "" : "s") << ".\n";
        }
    }
    result.nRules = ruleCount;
    std::cerr << indent << "  ..finished processing " << ruleCount << " reaction rules.\n";

    // === Step 10: Add population mapping rules ===
    std::cerr << indent << stepIndex << ":Fetching population maps.. ";
    ++stepIndex;

    for (const auto& pm : model_.getPopulationMaps()) {
        // In Perl: write rule as string from $pop->MappingRule->toString(),
        // then parse it back. Here we construct mapping rules directly.
        // A population mapping rule maps: species_pattern -> population()
        // Rate is typically 0 (the mapping is applied by the simulator, not kinetics)

        // Build the mapping rule: pattern -> popName()  rate
        // These are typically: species_pattern -> popName()  kmap
        // where kmap is effectively handled by the hybrid simulator
        const auto& populationName = !pm.populationName.empty()
            ? pm.populationName : pm.populationFunction;
        std::string populationPattern = populationName + "(";
        const auto& args = !pm.populationArgs.empty() ? pm.populationArgs : pm.functionArgs;
        for (std::size_t i = 0; i < args.size(); ++i) {
            if (i) populationPattern += ",";
            populationPattern += args[i];
        }
        populationPattern += ")";
        const auto mapCompartment = speciesCompartmentOf(pm.patternText);
        if (!mapCompartment.empty()) {
            populationPattern = "@" + mapCompartment + ":" + populationPattern;
        }

        std::string mapRuleName = "_MapRule" + std::to_string(populationMapRuleIndex++);
        hybridModel.addReactionRule(ast::ReactionRule(
            mapRuleName,
            mapRuleName + ":",
            {pm.patternText},
            {populationPattern},
            {pm.hasExplicitRate ? pm.rateExpression : ast::Expression::number(0)},
            pm.totalRate ? std::vector<std::string>{"TotalRate"} : std::vector<std::string>{},
            false));
    }
    result.nPopulationMaps = model_.getPopulationMaps().size();
    std::cerr << "found " << result.nPopulationMaps << " maps.\n";

    // === Step 11: Create empty reaction list ===
    std::cerr << indent << stepIndex << ":Creating empty reaction list.\n";
    ++stepIndex;
    // No explicit action needed; the hybrid model starts with no generated reactions

    // === Step 12: Write hybrid BNGL file ===
    std::cerr << indent << stepIndex << ":Attempting to write hybrid BNGL.. ";
    ++stepIndex;

    {
        std::ofstream out(modelfile);
        if (!out) {
            throw std::runtime_error("Couldn't write to " + modelfile);
        }

        // Use BnglWriter to serialize the hybrid model
        io::BnglWriter::Options writerOpts;
        writerOpts.includeComments = true;
        writerOpts.includeActions = false;
        writerOpts.evaluateExpressions = false;

        std::string bnglContent = io::BnglWriter::write(hybridModel, nullptr, writerOpts);
        out << bnglContent;

        // Write actions (matching Perl: write each action on its own line)
        if (!opts.actions.empty()) {
            out << "\n\n## model actions ##\n";
            for (const auto& action : opts.actions) {
                out << action << "\n";
            }
            out << "\n";
        }

        out.close();
    }

    std::cerr << "done.\n";
    std::cerr << "Wrote hybrid model to file " << modelfile << ".\n";

    // === Step 13: Optionally execute actions ===
    // In Perl, this calls $hybrid_model->$action for each action.  The
    // generated model records the requested actions in its own action block;
    // the caller (ActionDispatch.cpp) reads the generated model back and runs
    // them against it, so this step must not claim an execution it does not
    // perform.
    if (opts.execute) {
        std::cerr << indent
                  << "Requested actions are recorded in the generated hybrid "
                     "model; the caller executes them against it.\n";
    }

    return result;
}

} // namespace bng::engine
