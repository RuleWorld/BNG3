#pragma once
#include "nfsim_system_reader.hh"
namespace NFcore { class System; class LocalFunction; }
namespace NFcore2 {
class NativeNFsimSystemReader : public NFsimSystemReader {
public:
    explicit NativeNFsimSystemReader(NFcore::System& system);
    virtual std::size_t moleculeTypeCount() const;
    virtual NativeMoleculeTypeSnapshot moleculeType(std::size_t index) const;
    virtual std::size_t reactionCount() const;
    virtual NativeReactionHeader reactionHeader(std::size_t index) const;
    virtual void collectDependencies(std::size_t reaction_index,std::vector<NativeDependencySnapshot>& out) const;
    virtual void collectTransforms(std::size_t reaction_index,std::vector<NativeTransformSnapshot>& out) const;
    virtual void collectCompartments(std::vector<NativeCompartmentSnapshot>& out) const;
    virtual void collectGraphPatterns(std::size_t reaction_index,std::vector<NativeGraphPatternSnapshot>& out) const;
private:
    NFcore::System& system_;
};
NativeModelSnapshot snapshotLegacyNFsim(NFcore::System& system);
// ruleworld/nfsim#104: a local function that reads both a locally-scoped
// observable and a global observable goes stale under legacy evaluation
// (fire() only re-evaluates type-II molecules on product complexes).
// Throws instead of silently falling back to the stale evaluation.
// Testable directly; both native append paths call it.
void requireNoMixedLocalGlobalScopes(NFcore::LocalFunction* local);
// Build the executable NFcore2 representation from the real NFsim object
// graph. Unsupported legacy semantics remain represented in the returned
// per-rule fallback records; callers must route those rules to NFsim.
LegacyLoweringResult lowerLegacyNFsim(NFcore::System& system);
}
