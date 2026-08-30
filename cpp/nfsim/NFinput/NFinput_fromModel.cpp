/// NFinput_fromModel.cpp
///
/// Implements NFinput::initializeFromModel(), which constructs an NFcore::System
/// directly from a bng::ast::Model without touching the filesystem.
///
/// Strategy:
///   1. Serialize the ast::Model to a BNG-XML string in memory using XmlWriter.
///   2. Parse that string with TiXmlDocument::Parse() (no disk I/O).
///   3. Drive the same internal NFinput initialisation steps (parameters,
///      compartments, molecule types, species, observables, functions, rules)
///      from the in-memory document.
///
/// This eliminates ~4000 lines of XML-file I/O that the original
/// initializeFromXML() uses to bridge two C++ objects in the same process.

#include "NFinput.hh"
#include "NFinput_energy.hh"
#include "../NFcore/compartment.hh"

// ast & io headers (include paths added to nfsim_core in CMakeLists.txt)
#include "ast/Model.hpp"
#include "io/XmlWriter.hpp"

#include <iostream>
#include <string>

using namespace std;
using namespace NFcore;

namespace NFinput {

/// Construct an NFcore::System directly from a parsed ast::Model, bypassing
/// the filesystem XML round-trip.
///
/// @param model_ptr   Pointer to a fully-constructed bng::ast::Model.
/// @param blockSameComplexBinding  Block binding within the same complex.
/// @param globalMoleculeLimit      Maximum molecule count per type.
/// @param verbose                  Emit detailed progress messages.
/// @param suggestedTraversalLimit  Output: recommended traversal depth.
/// @return Newly allocated System (caller takes ownership), or nullptr on error.
System* initializeFromModel(
        void*  model_ptr,
        bool   blockSameComplexBinding,
        int    globalMoleculeLimit,
        bool   verbose,
        int&   suggestedTraversalLimit)
{
    if (!model_ptr) {
        cerr << "[nfsim] initializeFromModel: null model_ptr — falling back to XML path.\n";
        return nullptr;
    }

    auto* model = static_cast<bng::ast::Model*>(model_ptr);

    // -----------------------------------------------------------------------
    // Step 1: Serialise the model to a BNG-XML string (in-process, no disk).
    // -----------------------------------------------------------------------
    if (verbose) {
        cerr << "[nfsim] initializeFromModel: serialising model '"
             << model->getModelName() << "' to in-memory XML.\n";
    }

    std::string xmlStr;
    try {
        xmlStr = bng::io::XmlWriter::write(*model);
    } catch (const std::exception& e) {
        cerr << "[nfsim] initializeFromModel: XmlWriter threw: " << e.what()
             << " — falling back to XML path.\n";
        return nullptr;
    }

    if (xmlStr.empty()) {
        cerr << "[nfsim] initializeFromModel: XmlWriter returned empty string"
                " — falling back to XML path.\n";
        return nullptr;
    }

    // -----------------------------------------------------------------------
    // Step 2: Parse the XML string in-memory with TinyXML (no file open).
    // -----------------------------------------------------------------------
    TiXmlDocument doc;
    doc.Parse(xmlStr.c_str(), nullptr, TIXML_ENCODING_UTF8);
    if (doc.Error()) {
        cerr << "[nfsim] initializeFromModel: TinyXML parse error: "
             << doc.ErrorDesc() << " at row " << doc.ErrorRow()
             << " — falling back to XML path.\n";
        return nullptr;
    }

    if (verbose) {
        cerr << "[nfsim] initializeFromModel: in-memory XML parse succeeded ("
             << xmlStr.size() << " bytes).\n";
    }

    // -----------------------------------------------------------------------
    // Step 3: Drive the same initialisation logic as initializeFromXML(),
    //         but from the in-memory document rather than from disk.
    // -----------------------------------------------------------------------

    // Locate the <model> element (same structure as on-disk BNG-XML).
    TiXmlHandle hDoc(&doc);
    TiXmlElement* pModel =
        hDoc.FirstChildElement().Node()->FirstChildElement("model");
    if (!pModel) {
        cerr << "[nfsim] initializeFromModel: no <model> element in generated"
                " XML — falling back to XML path.\n";
        return nullptr;
    }

    // Create the System object.
    const std::string& modelName = model->getModelName();
    System* s = new System(
        modelName.empty() ? "model" : modelName,
        blockSameComplexBinding,
        globalMoleculeLimit
    );
    // initializeFromModel has no separate -nocslf parameter.  Match the
    // command-line loader's default and make species-scoped local functions
    // evaluate rather than depending on an uninitialised System flag.
    s->setEvaluateComplexScopedLocalFunctions(true);
    if (verbose) {
        cerr << "[nfsim] initializeFromModel: created System '" << s->getName() << "'.\n";
    }

    // Carry over substance-unit scaling if present.
    if (pModel->Attribute("NumberPerQuantityUnit")) {
        double npqu = NFutil::convertToDouble(pModel->Attribute("NumberPerQuantityUnit"));
        s->setNumberPerQuantityUnit(npqu);
    }

    // Locate the major list elements.
    TiXmlElement* pListOfParameters =
        pModel->FirstChildElement("ListOfParameters");
    if (!pListOfParameters) {
        cerr << "[nfsim] initializeFromModel: missing <ListOfParameters>.\n";
        delete s; return nullptr;
    }
    TiXmlElement* pListOfFunctions =
        pModel->FirstChildElement("ListOfFunctions");
    TiXmlElement* pListOfMoleculeTypes =
        pListOfParameters->NextSiblingElement("ListOfMoleculeTypes");
    if (!pListOfMoleculeTypes) {
        cerr << "[nfsim] initializeFromModel: missing <ListOfMoleculeTypes>.\n";
        delete s; return nullptr;
    }
    TiXmlElement* pListOfCompartments =
        pModel->FirstChildElement("ListOfCompartments");
    TiXmlElement* pListOfSpecies =
        pListOfMoleculeTypes->NextSiblingElement("ListOfSpecies");
    if (!pListOfSpecies) {
        cerr << "[nfsim] initializeFromModel: missing <ListOfSpecies>.\n";
        delete s; return nullptr;
    }
    TiXmlElement* pListOfReactionRules =
        pListOfSpecies->NextSiblingElement("ListOfReactionRules");
    if (!pListOfReactionRules) {
        cerr << "[nfsim] initializeFromModel: missing <ListOfReactionRules>.\n";
        delete s; return nullptr;
    }
    TiXmlElement* pListOfObservables =
        pListOfReactionRules->NextSiblingElement("ListOfObservables");
    if (!pListOfObservables) {
        cerr << "[nfsim] initializeFromModel: missing <ListOfObservables>.\n";
        delete s; return nullptr;
    }

    // --- Parameters ---
    if (verbose) cerr << "[nfsim] initializeFromModel: parsing parameters.\n";
    map<string, double> parameter;
    if (!initParameters(pListOfParameters, s, parameter, verbose)) {
        cerr << "[nfsim] initializeFromModel: parameter parsing failed.\n";
        delete s; return nullptr;
    }

    // --- Molecule types ---
    if (verbose) cerr << "[nfsim] initializeFromModel: parsing molecule types.\n";
    map<string, int> allowedStates;
    if (!initMoleculeTypes(pListOfMoleculeTypes, s, allowedStates, verbose)) {
        cerr << "[nfsim] initializeFromModel: molecule type parsing failed.\n";
        delete s; return nullptr;
    }

    // --- Compartments (optional) ---
    if (pListOfCompartments) {
        if (verbose) cerr << "[nfsim] initializeFromModel: parsing compartments.\n";
        if (!initCompartments(pListOfCompartments, s, verbose)) {
            cerr << "[nfsim] initializeFromModel: compartment parsing failed.\n";
            delete s; return nullptr;
        }
    }

    // --- Seed species ---
    if (verbose) cerr << "[nfsim] initializeFromModel: parsing seed species.\n";
    string logstr = initStartSpecies(pListOfSpecies, s, parameter, allowedStates, verbose);
    if (logstr.empty()) {
        cerr << "[nfsim] initializeFromModel: species parsing failed.\n";
        delete s; return nullptr;
    }
    s->setSpeciesLog(logstr);

    // --- Observables ---
    if (verbose) cerr << "[nfsim] initializeFromModel: parsing observables.\n";
    if (!initObservables(pListOfObservables, s, parameter, allowedStates,
                         verbose, suggestedTraversalLimit)) {
        cerr << "[nfsim] initializeFromModel: observable parsing failed.\n";
        delete s; return nullptr;
    }

    // --- Functions (optional) ---
    if (pListOfFunctions) {
        if (verbose) cerr << "[nfsim] initializeFromModel: parsing functions.\n";
        if (!initFunctions(pListOfFunctions, s, parameter,
                           pListOfObservables, allowedStates, verbose)) {
            cerr << "[nfsim] initializeFromModel: function parsing failed.\n";
            delete s; return nullptr;
        }
    }

    // --- Energy patterns (eBNGL, optional) ---
    if (!NFinput::parseEnergyPatterns(pModel, s, parameter, verbose)) {
        cerr << "[nfsim] initializeFromModel: energy pattern parsing failed.\n";
        delete s; return nullptr;
    }

    // --- Reaction rules ---
    if (verbose) cerr << "[nfsim] initializeFromModel: parsing reaction rules.\n";
    if (!initReactionRules(pListOfReactionRules, s, parameter, allowedStates,
                           blockSameComplexBinding, verbose, suggestedTraversalLimit)) {
        cerr << "[nfsim] initializeFromModel: reaction rule parsing failed.\n";
        delete s; return nullptr;
    }

    if (verbose) {
        cerr << "[nfsim] initializeFromModel: System '" << s->getName()
             << "' initialised successfully (no disk I/O).\n";
    }

    return s;
}

} // namespace NFinput
