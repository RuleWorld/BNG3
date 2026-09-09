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
    std::int64_t population_delta;
    std::uint32_t added_molecule_type;
    std::uint32_t destination_compartment;
    bool move_connected;
    std::string local_function_pointer;
    int local_function_scope;
    NFsimPublicTransformView():kind(NATIVE_EMPTY),reactant(0),component(0),final_state(0),removal_type(-1),other_reactant(-1),other_mapping_index(-1),second_binding_half(false),population_delta(0),added_molecule_type(0),destination_compartment(0),move_connected(false),local_function_scope(-1){}
};
class NFsimTransformDecoder {
public:
    static std::vector<NativeTransformSnapshot> decode(const std::vector<std::vector<NFsimPublicTransformView> >& by_reactant);
};
}
