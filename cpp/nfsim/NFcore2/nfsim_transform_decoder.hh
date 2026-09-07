#pragma once
#include "nfsim_adapter_contract.hh"
#include <cstdint>
#include <stdexcept>
#include <vector>
namespace NFcore2 {
struct NFsimPublicTransformView {
    int kind;
    std::uint16_t reactant;
    std::uint32_t component;
    int final_state;
    int removal_type;
    int other_reactant;
    int other_mapping_index;
    bool second_binding_half;
    NFsimPublicTransformView():kind(NATIVE_EMPTY),reactant(0),component(0),final_state(0),removal_type(-1),other_reactant(-1),other_mapping_index(-1),second_binding_half(false){}
};
class NFsimTransformDecoder {
public:
    static std::vector<NativeTransformSnapshot> decode(const std::vector<std::vector<NFsimPublicTransformView> >& by_reactant);
};
}
