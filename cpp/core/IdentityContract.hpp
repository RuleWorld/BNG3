#pragma once
// ============================================================================
// The one identity contract for molecular graphs in BNG3.
//
// A molecular graph is a labeled graph.  A molecule vertex carries its
// molecule type, a component vertex carries its site name and its site state,
// and the edges are component membership and bonds.  Two molecular graphs are
// isomorphic when a bijection of their vertices preserves every vertex label
// and every edge.
//
// Identity is layered, and every surface that decides identity states the
// layer it decides:
//
//   Structure   - labeled-graph isomorphism.  Compartments are ignored.
//   Compartment - structure, plus the compartment of every molecule under the
//                 isomorphism.  A molecule without an explicit compartment
//                 takes the species-level compartment, so this layer is the
//                 explicit molecule compartments together with the
//                 species-level compartment.  NFsim's Complex encoding carries
//                 the compartment on the molecule, so its canonical label
//                 decides this layer directly.
//   Species     - structure, plus the species-level compartment, plus the
//                 per-molecule compartments.  This is the layer BNG3's
//                 network species identity decides.
//
// A canonical label is a canonical form of one layer only.  BNG3's
// PatternGraph::get_label() omits compartments, so it decides the structure
// layer; NFsim's Complex::getCanonicalLabel() embeds every molecule's
// compartment, so it decides the structure and compartment layers.  Neither
// label decides species identity on its own: BNG3's species identity adds the
// compartment comparison on top of the structural isomorphism.
//
// The surfaces that use this contract:
//
//   cpp/ast/SpeciesGraph.cpp          structure (canonical label, isomorphism)
//   cpp/ast/SpeciesList.cpp           species   (network species identity)
//   cpp/nfsim/NFcore/complex.cpp      structure and compartment
//
// The layers are ordered: the species layer includes the compartment layer,
// and the compartment layer includes the structure layer.
// ============================================================================

#include <string>
#include <utility>
#include <vector>

namespace BNGcore {
class Node;
class PatternGraph;
}

namespace bng::identity {

// The layers of the identity contract, from the weakest to the strongest.
enum class Layer {
    Structure,
    Compartment,
    Species,
};

// The stable name of a layer.  Qualification evidence records these names so
// that a surface deciding a different layer is visible instead of silent.
const char* layerName(Layer layer);

// True when the `outer` layer includes every distinction of the `inner` one.
bool layerIncludes(Layer outer, Layer inner);

// The labeled-graph relation of the shared molecular encoding: molecule type,
// site name, site state, bond topology and the per-molecule compartment
// agree under the isomorphism.  Together with the species-level compartment
// this is the structure and compartment layers of the contract.
bool sameMoleculeGraph(const BNGcore::PatternGraph& lhs, const BNGcore::PatternGraph& rhs);

// The vertex roles of the shared PatternGraph encoding.  A molecule vertex is
// a molecule type, a component vertex is a site, and a bond vertex joins two
// sites.
bool isBondNode(const BNGcore::Node& node);
bool isComponentNode(const BNGcore::Node& node);
bool isMoleculeNode(const BNGcore::Node& node);

// The structural content of one molecule of a PatternGraph: its type name and
// the sorted (component name, bond state) pairs of its components.  The bond
// state is 1 for a bound site, 0 for a free site and -1 for a wildcard bond.
struct MoleculeKey {
    std::string type;
    std::vector<std::pair<std::string, int>> components;

    bool operator==(const MoleculeKey& other) const;
    bool operator<(const MoleculeKey& other) const;
};

// The molecules of a PatternGraph as sorted content keys.  Two graphs with the
// same molecule keys have the same molecule multiset.
std::vector<MoleculeKey> moleculeKeys(const BNGcore::PatternGraph& graph);

// The compartments of the molecule nodes of a PatternGraph, in graph order.
// A molecule without an explicit compartment reports an empty compartment.
std::vector<std::string> moleculeCompartments(const BNGcore::PatternGraph& graph);

} // namespace bng::identity
