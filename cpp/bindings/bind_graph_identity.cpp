// Private validation hook: report the identity observations that the two
// native graph encodings make about a model's seed species.
//
// The network encoding (BNGcore::PatternGraph plus its nauty canonical
// label) and the NFsim encoding (NFcore::Complex plus its own nauty
// canonical label) decide different layers of the shared identity contract
// (cpp/core/IdentityContract.hpp).  Qualification evidence needs both
// observations next to the independent contract, so this hook exposes the
// native implementation instead of re-deriving it in Python.
//
// This is not part of the supported Python API.

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "ast/Model.hpp"
#include "ast/SeedSpecies.hpp"
#include "ast/SpeciesGraph.hpp"
#include "ast/SpeciesList.hpp"
#include "core/IdentityContract.hpp"
#include "NFcore.hh"
#include "NFinput/NFinput_fromAst.hh"

namespace py = pybind11;
using namespace bng::ast;

namespace {

// The content key of one NFsim molecule: its type name and the sorted
// (component name, bond count) pairs of its components.  It mirrors
// bng::identity::moleculeKeys so that the seed's graph and the molecules
// NFsim allocated for it can be compared.
bng::identity::MoleculeKey nfsimMoleculeKey(const NFcore::Molecule* molecule) {
    const auto* type = molecule->getMoleculeType();
    bng::identity::MoleculeKey key;
    key.type = type->getName();
    const int components = type->getNumOfComponents();
    for (int component = 0; component < components; ++component) {
        const int bonds = molecule->isBindingSiteBonded(component) ? 1 : 0;
        key.components.emplace_back(type->getComponentName(component), bonds);
    }
    std::sort(key.components.begin(), key.components.end());
    return key;
}

// Every molecule of the system, grouped by molecule type and ordered by the
// slot NFsim activated it in.  MoleculeList preallocates its Molecule objects
// when the molecule type is built, so the unique id does not order the
// activation; the list slot does.
std::map<std::string, std::vector<NFcore::Molecule*>> activatedMolecules(
    NFcore::System* system) {
    std::map<std::string, std::vector<NFcore::Molecule*>> molecules;
    for (int index = 0; index < system->getNumOfMoleculeTypes(); ++index) {
        auto* type = system->getMoleculeType(index);
        std::vector<NFcore::Molecule*> active;
        for (int molecule = 0; molecule < type->getMoleculeCount(); ++molecule) {
            active.push_back(type->getMolecule(molecule));
        }
        std::sort(active.begin(), active.end(),
                  [](const NFcore::Molecule* left, const NFcore::Molecule* right) {
                      return left->getMolListId() < right->getMolListId();
                  });
        molecules.emplace(type->getName(), std::move(active));
    }
    return molecules;
}

std::string describeKeys(const std::vector<bng::identity::MoleculeKey>& keys) {
    std::string text;
    for (const auto& key : keys) {
        if (!text.empty()) {
            text += "; ";
        }
        text += key.type + "(";
        for (std::size_t index = 0; index < key.components.size(); ++index) {
            if (index != 0) {
                text += ",";
            }
            text += key.components[index].first + ":" +
                    std::to_string(key.components[index].second);
        }
        text += ")";
    }
    return text;
}

} // namespace

void bind_graph_identity(py::module_& m) {
    m.def(
        "_validation_species_identity_labels",
        [](const Model& model) {
            int suggestedTraversalLimit = 0;
            std::string unavailableReason;
            std::unique_ptr<NFcore::System> system(NFinput::buildSystemFromAst(
                model,
                true,   // useComplex
                false,  // blockSameComplexBinding
                100,    // globalMoleculeLimit
                false,  // verbose
                suggestedTraversalLimit, {}, &unavailableReason));
            if (!system) {
                throw std::runtime_error(
                    "NFsim system unavailable: " + unavailableReason);
            }

            // NFsim activates the molecules of the seed species in seed order.
            // Each seed species is matched against the next activated
            // molecules of every molecule type and the match is verified by
            // content, so an unexpected activation order refuses instead of
            // reporting a label for the wrong species.
            auto molecules = activatedMolecules(system.get());
            std::map<std::string, std::size_t> cursors;

            py::list species;
            for (const auto& seed : model.getSeedSpecies()) {
                const auto expected = bng::identity::moleculeKeys(seed.getGraph());
                if (expected.empty()) {
                    throw std::runtime_error(
                        "seed species '" + seed.getPattern() +
                        "' contains no molecule graph");
                }

                std::map<std::string, std::size_t> required;
                for (const auto& key : expected) {
                    for (const auto& component : key.components) {
                        if (component.second < 0) {
                            throw std::runtime_error(
                                "seed species '" + seed.getPattern() +
                                "' uses a wildcard bond; NFsim cannot represent "
                                "it as a concrete molecule");
                        }
                    }
                    ++required[key.type];
                }

                std::vector<NFcore::Molecule*> assigned;
                for (const auto& [type, count] : required) {
                    const auto found = molecules.find(type);
                    if (found == molecules.end()) {
                        throw std::runtime_error(
                            "seed species '" + seed.getPattern() +
                            "' names a molecule type NFsim did not create: " + type);
                    }
                    const std::size_t cursor = cursors[type];
                    if (cursor + count > found->second.size()) {
                        throw std::runtime_error(
                            "seed species '" + seed.getPattern() +
                            "' has no matching NFsim molecules of type " + type);
                    }
                    for (std::size_t index = 0; index < count; ++index) {
                        assigned.push_back(found->second[cursor + index]);
                    }
                    cursors[type] = cursor + count;
                }

                std::vector<bng::identity::MoleculeKey> observed;
                observed.reserve(assigned.size());
                for (const auto* molecule : assigned) {
                    observed.push_back(nfsimMoleculeKey(molecule));
                }
                std::sort(observed.begin(), observed.end());
                if (observed != expected) {
                    throw std::runtime_error(
                        "seed species '" + seed.getPattern() +
                        "' does not match the molecules NFsim allocated for it: "
                        "expected " + describeKeys(expected) + ", observed " +
                        describeKeys(observed));
                }

                NFcore::Complex* complex = assigned.front()->getComplex();
                for (const auto* molecule : assigned) {
                    if (molecule->getComplex() != complex) {
                        throw std::runtime_error(
                            "seed species '" + seed.getPattern() +
                            "' spans more than one NFsim complex");
                    }
                }

                py::dict entry;
                entry["pattern"] = seed.getPattern();
                entry["species_compartment"] = seed.getCompartment();
                entry["molecule_compartments"] =
                    bng::identity::moleculeCompartments(seed.getGraph());
                entry["network_label"] = seed.getCanonicalLabel();
                entry["nfsim_label"] = complex->getCanonicalLabel();
                species.append(entry);
            }
            for (const auto& [type, activated] : molecules) {
                const std::size_t cursor = cursors[type];
                if (cursor != activated.size()) {
                    throw std::runtime_error(
                        "NFsim activated molecules of type " + type +
                        " that no seed species accounts for");
                }
            }

            py::dict layers;
            layers["network-canonical-label"] =
                bng::ast::SpeciesGraph::identityLayer();
            layers["nfsim-canonical-label"] = NFcore::Complex::identityLayer();
            layers["network-species-identity"] = bng::ast::SpeciesList::identityLayer();

            py::dict result;
            result["species"] = species;
            result["layers"] = layers;
            return result;
        },
        py::arg("model"),
        "Internal qualification hook: the identity labels of the two native "
        "graph encodings for every seed species of a model");
}
