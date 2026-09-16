#pragma once

#include <string>
#include <unordered_map>
#include <vector>
#include "ast/Model.hpp"
#include "engine/NetworkGenerator.hpp"

namespace bng::io {

/**
 * SbmlWriter - Export to SBML (Systems Biology Markup Language)
 *
 * Generates SBML Level 3 Version 2 output from BioNetGen models.  This is
 * the current SBML core version and permits the complete MathML vocabulary
 * needed by modern curated models.
 *
 * Features:
 * - Parameters (constants + expressions + observables as non-constant)
 * - Compartments (2D/3D, nesting via 'outside')
 * - Species with compartment references
 * - Reactions with full MathML kinetic laws
 * - Observable assignment rules (weighted species sums)
 * - Global function assignment rules
 * - Unit definitions (substance=item)
 * - Volume correction for compartmental rate laws
 *
 * Reference:
 * - BNG2/bng2/Perl2/BNGOutput.pm::writeSBML()
 * - BNG2/bng2/Perl2/RateLaw.pm::toMathMLString()
 * - BNG2/bng2/Perl2/Observable.pm::toMathMLString()
 * - SBML spec: http://sbml.org/
 */
class SbmlWriter {
public:
    struct Options {
        int level = 3;               // SBML level (current core)
        int version = 2;             // SBML version (current core)
        bool networksExport = true;  // Export generated network (vs rules)
        // Optional opaque source metadata payload supplied by the modern
        // SBML importer.  It is encoded in a namespaced SBML annotation so
        // notes/CVTerms/package declarations survive the executable export
        // without being interpreted as kinetic state.
        std::string sourceMetadata;
    };

    static std::string write(
        const ast::Model& model,
        const engine::GeneratedNetwork* network
    );

    static std::string write(
        const ast::Model& model,
        const engine::GeneratedNetwork* network,
        const Options& options
    );

private:
    struct SymbolIds {
        std::unordered_map<std::string, std::string> parameters;
        std::unordered_map<std::string, std::string> functions;
        std::unordered_map<std::string, std::string> observables;
    };

    // Observable-to-species weight mapping
    struct ObservableGroup {
        std::string name;
        std::string sbmlId;
        std::string type;
        std::vector<std::pair<std::size_t, std::size_t>> entries; // (speciesIndex, weight)
    };

    static std::string escapeXml(const std::string& text);
    static std::string makeValidSBMLId(const std::string& text);
    static SymbolIds computeSymbolIds(
        const ast::Model& model,
        const engine::GeneratedNetwork* network,
        const std::vector<ObservableGroup>& groups);

    static std::string writeUnitDefinitions(int level);
    static std::string writeSourceMetadata(const std::string& payload);
    static std::string writeCompartments(const ast::Model& model, int level);
    static std::string writeParameters(
        const ast::Model& model,
        const std::vector<ObservableGroup>& groups,
        const SymbolIds& symbolIds);
    static std::string writeSpecies(const ast::Model& model, const engine::GeneratedNetwork* network);
    static std::string writeInitialAssignments(const ast::Model& model);
    static std::string writeAssignmentRules(
        const ast::Model& model,
        const std::vector<ObservableGroup>& groups,
        const SymbolIds& symbolIds);
    static std::string writeReactions(
        const engine::GeneratedNetwork& network,
        const ast::Model& model,
        const SymbolIds& symbolIds,
        int level);

    static std::vector<ObservableGroup> computeObservableGroups(
        const ast::Model& model, const engine::GeneratedNetwork& network);

    // MathML generation helpers
    static std::string exprToMathML(
        const ast::Expression& expr,
        const std::string& indent,
        const SymbolIds& symbolIds);
    static std::string rateLawToMathML(
        const ast::Rxn& rxn,
        const ast::Model& model,
        const engine::GeneratedNetwork& network,
        const std::string& indent,
        const SymbolIds& symbolIds);
};

} // namespace bng::io
