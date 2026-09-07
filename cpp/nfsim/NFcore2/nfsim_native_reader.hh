#pragma once
#include "nfsim_system_reader.hh"
namespace NFcore { class System; }
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
private:
    NFcore::System& system_;
};
NativeModelSnapshot snapshotLegacyNFsim(NFcore::System& system);
}
