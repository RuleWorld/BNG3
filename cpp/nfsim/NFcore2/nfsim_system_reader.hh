#pragma once
#include "nfsim_adapter_contract.hh"
#include <cstddef>
#include <string>
#include <vector>

namespace NFcore2 {

struct NativeReactionHeader {
    std::string name;
    double base_rate;
    std::uint32_t parameter_index;
    std::uint32_t coordinate;
    std::vector<std::uint32_t> reactant_types;
    bool uses_local_function;
    bool uses_connected_to;
    NativeReactionHeader() : base_rate(0.0), parameter_index(0), coordinate(0),
        uses_local_function(false), uses_connected_to(false) {}
};

class NFsimSystemReader {
public:
    virtual ~NFsimSystemReader() {}
    virtual std::size_t moleculeTypeCount() const = 0;
    virtual NativeMoleculeTypeSnapshot moleculeType(std::size_t index) const = 0;
    virtual std::size_t reactionCount() const = 0;
    virtual NativeReactionHeader reactionHeader(std::size_t index) const = 0;
    virtual void collectDependencies(std::size_t reaction_index,
        std::vector<NativeDependencySnapshot>& out) const = 0;
    virtual void collectTransforms(std::size_t reaction_index,
        std::vector<NativeTransformSnapshot>& out) const = 0;
    virtual void collectCompartments(std::vector<NativeCompartmentSnapshot>&) const {}
    virtual void collectGraphPatterns(std::size_t, std::vector<NativeGraphPatternSnapshot>&) const {}
};

NativeModelSnapshot readNFsimSystem(const NFsimSystemReader& reader);

} // namespace NFcore2
