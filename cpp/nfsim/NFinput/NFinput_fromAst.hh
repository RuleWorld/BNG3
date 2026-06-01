/// NFinput_fromAst.hh
///
/// WO-2 — Construct an NFcore::System DIRECTLY from a bng::ast::Model, with no
/// XML serialization or re-parse at any point.
///
/// State of play this gives an agent a head start on:
///   - NFinput::initializeFromXML(filename, ...)  reads BNG-XML from disk.
///   - NFinput::initializeFromModel(void*, ...)    already exists but is a
///     half-measure: it calls XmlWriter::write(model) to a std::string, then
///     TiXmlDocument::Parse()s that string, then runs the same TiXml-driven
///     init steps. It removed the *tempfile*, not the XML model. Two data
///     models and a full serialize/parse round-trip remain.
///
/// The functions below replace that with a direct path: each reads ast::Model
/// accessors and drives the SAME NFcore::System construction the TiXml init
/// functions perform, with no intermediate document.
///
/// MIGRATION CONTRACT (how the gate proves correctness):
///   - bind_nfsim routes through buildSystemFromAst() by default.
///   - Setting the env var BNG_NFSIM_FORCE_XML=1 forces the old in-memory-XML
///     path (initializeFromModel). The harness test
///     test_parity_nfsim::test_nf_ast_direct_matches_xml runs the model both
///     ways under one fixed seed and requires identical trajectories. The
///     in-memory-XML path is therefore the behavioral oracle for the direct
///     path, in addition to the native NFsim binary.
///   - Implement one init function at a time; keep the others delegating to the
///     XML path until their direct version is green. (See buildSystemFromAst.)

#pragma once

#include <map>
#include <string>

namespace bng::ast { class Model; }

namespace NFcore { class System; }

namespace NFinput {

/// Build an NFcore::System directly from a parsed ast::Model.
///
/// @param model                    fully-constructed model (network-free target).
/// @param blockSameComplexBinding  block binding within the same complex.
/// @param globalMoleculeLimit      max molecules per type.
/// @param verbose                  progress messages.
/// @param suggestedTraversalLimit  out: recommended traversal depth.
/// @return owned System, or nullptr on error (caller may fall back to XML).
NFcore::System* buildSystemFromAst(
        const bng::ast::Model& model,
        bool   blockSameComplexBinding,
        int    globalMoleculeLimit,
        bool   verbose,
        int&   suggestedTraversalLimit);

// --- Per-section direct builders (mirror the TiXml-based init* functions) ---
// Each returns false on error. Implement incrementally; until a builder is
// done, buildSystemFromAst delegates that section to the in-memory-XML path.

bool addParametersFromAst(const bng::ast::Model& model, NFcore::System* s,
                          std::map<std::string, double>& parameters, bool verbose);

bool addMoleculeTypesFromAst(const bng::ast::Model& model, NFcore::System* s,
                             bool verbose);

bool addFunctionsFromAst(const bng::ast::Model& model, NFcore::System* s,
                         const std::map<std::string, double>& parameters, bool verbose);

bool addObservablesFromAst(const bng::ast::Model& model, NFcore::System* s,
                           const std::map<std::string, double>& parameters,
                           bool verbose, int& suggestedTraversalLimit);

bool addSpeciesFromAst(const bng::ast::Model& model, NFcore::System* s,
                       const std::map<std::string, double>& parameters, bool verbose);

bool addReactionRulesFromAst(const bng::ast::Model& model, NFcore::System* s,
                             const std::map<std::string, double>& parameters,
                             bool blockSameComplexBinding, bool verbose,
                             int& suggestedTraversalLimit);

} // namespace NFinput
