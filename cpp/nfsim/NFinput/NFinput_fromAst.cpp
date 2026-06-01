/// NFinput_fromAst.cpp
///
/// WO-2 direct ast -> NFcore::System construction. See NFinput_fromAst.hh for
/// the migration contract.
///
/// Design that keeps every intermediate state correct and shippable:
///   buildSystemFromAst() runs each per-section builder in order. A builder
///   that is not yet implemented returns false; buildSystemFromAst then deletes
///   the partial System and returns nullptr, and bind_nfsim falls back to the
///   in-memory-XML path. The direct path therefore activates only once ALL
///   sections are implemented — never half-built. An agent flips one builder
///   from `return false` to a real implementation at a time, each gated by
///   test_parity_nfsim (ast-direct must equal in-memory-XML under one seed).
///
/// IMPLEMENTED here: parameters (the section whose ast API is unambiguous).
/// STUBBED here:     molecule types, functions, observables, species, rules —
///                   each cites the TiXml init* function that is its behavioral
///                   specification. Port those, do not reinvent them.

#include "NFinput_fromAst.hh"
#include "NFinput.hh"

#include "ast/Model.hpp"
#include "ast/Parameter.hpp"
#include "ast/ParameterList.hpp"

#include <cstdlib>
#include <iostream>

using namespace NFcore;

namespace NFinput {

// --------------------------------------------------------------------------- //
// Parameters — implemented directly from ast::ParameterList.
// Mirrors NFinput::initParameters (NFinput.cpp:286). The ast list already holds
// evaluated numeric values via ParameterList::evaluate(); no expression parsing
// is needed at this layer.
// --------------------------------------------------------------------------- //
bool addParametersFromAst(const bng::ast::Model& model, System* s,
                          std::map<std::string, double>& parameters, bool verbose) {
    const auto& plist = model.getParameters();
    for (const auto& p : plist.all()) {
        const std::string& name = p.getName();
        double value = plist.evaluate(name, 0.0);  // resolves inter-parameter refs
        parameters[name] = value;
        s->addParameter(name, value);
        if (verbose) {
            std::cerr << "[nfsim/ast] parameter " << name << " = " << value << "\n";
        }
    }
    return true;
}

// --------------------------------------------------------------------------- //
// The following sections are not yet ported to the direct path. Each returns
// false, which makes buildSystemFromAst fall back to the in-memory-XML path.
// Behavioral specification = the cited TiXml init function; port it field for
// field, then return true and let the gate confirm parity.
// --------------------------------------------------------------------------- //

bool addMoleculeTypesFromAst(const bng::ast::Model& model, System* s, bool verbose) {
    (void)model; (void)s; (void)verbose;
    // SPEC: the molecule-type loop inside NFinput::initializeFromXML
    //       (NFcore::MoleculeType construction; component names; allowed states).
    // ast source: model.getMoleculeTypes() -> vector<MoleculeType>.
    return false;  // not yet implemented -> fall back
}

bool addFunctionsFromAst(const bng::ast::Model& model, System* s,
                         const std::map<std::string, double>& parameters, bool verbose) {
    (void)model; (void)s; (void)parameters; (void)verbose;
    // SPEC: NFinput::initFunctions (parseFuncXML.cpp:488).
    // WO-3 INTERSECTION: build the function bodies through the shared evaluator
    //       (see ast/ExpressionEval.hpp), NOT exprtk. ast source:
    //       model.getFunctions() -> vector<Function>.
    return false;
}

bool addObservablesFromAst(const bng::ast::Model& model, System* s,
                           const std::map<std::string, double>& parameters,
                           bool verbose, int& suggestedTraversalLimit) {
    (void)model; (void)s; (void)parameters; (void)verbose; (void)suggestedTraversalLimit;
    // SPEC: NFinput::initObservables (NFinput.cpp:2935) +
    //       readObservableForTemplateMolecules (NFinput.cpp:2814).
    // ast source: model.getObservables() -> vector<Observable>.
    return false;
}

bool addSpeciesFromAst(const bng::ast::Model& model, System* s,
                       const std::map<std::string, double>& parameters, bool verbose) {
    (void)model; (void)s; (void)parameters; (void)verbose;
    // SPEC: the seed-species/ListOfSpecies loop in NFinput::initializeFromXML
    //       (instantiates initial Molecule populations into the System).
    // ast source: model.getSeedSpecies() -> vector<SeedSpecies>.
    return false;
}

bool addReactionRulesFromAst(const bng::ast::Model& model, System* s,
                             const std::map<std::string, double>& parameters,
                             bool blockSameComplexBinding, bool verbose,
                             int& suggestedTraversalLimit) {
    (void)model; (void)s; (void)parameters; (void)blockSameComplexBinding;
    (void)verbose; (void)suggestedTraversalLimit;
    // SPEC: NFinput::initReactionRules (NFinput.cpp:1266) — the largest section;
    //       TransformationSet construction, reactant template molecules, rate
    //       laws (incl. Arrhenius via NFinput_energy). Port last.
    // ast source: model.getReactionRules() -> vector<ReactionRule>.
    return false;
}

// --------------------------------------------------------------------------- //
// Orchestrator.
// --------------------------------------------------------------------------- //
System* buildSystemFromAst(const bng::ast::Model& model,
                           bool blockSameComplexBinding,
                           int globalMoleculeLimit,
                           bool verbose,
                           int& suggestedTraversalLimit) {
    // Migration escape hatch used by the parity gate: force the XML path.
    if (std::getenv("BNG_NFSIM_FORCE_XML")) {
        if (verbose) std::cerr << "[nfsim/ast] BNG_NFSIM_FORCE_XML set -> XML path\n";
        return nullptr;  // caller falls back to initializeFromModel (in-memory XML)
    }

    const std::string& name = model.getModelName();
    System* s = new System(name.empty() ? "model" : name,
                           blockSameComplexBinding, globalMoleculeLimit);

    std::map<std::string, double> parameters;
    suggestedTraversalLimit = 0;

    const bool ok =
        addParametersFromAst(model, s, parameters, verbose) &&
        addMoleculeTypesFromAst(model, s, verbose) &&
        addFunctionsFromAst(model, s, parameters, verbose) &&
        addObservablesFromAst(model, s, parameters, verbose, suggestedTraversalLimit) &&
        addSpeciesFromAst(model, s, parameters, verbose) &&
        addReactionRulesFromAst(model, s, parameters, blockSameComplexBinding,
                                verbose, suggestedTraversalLimit);

    if (!ok) {
        // Some section is not yet ported. Discard the partial System and let the
        // caller use the in-memory-XML path. This is the expected state until
        // every builder above returns true.
        delete s;
        if (verbose) {
            std::cerr << "[nfsim/ast] direct path incomplete -> XML fallback\n";
        }
        return nullptr;
    }

    // s->prepareForSimulation() is the caller's responsibility, matching the
    // XML path in bind_nfsim.
    return s;
}

} // namespace NFinput
