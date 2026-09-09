#include "nfsim_transform_decoder.hh"
namespace NFcore2 {
std::vector<NativeTransformSnapshot> NFsimTransformDecoder::decode(const std::vector<std::vector<NFsimPublicTransformView> >& by_reactant){
    std::vector<NativeTransformSnapshot> out;
    for(std::size_t ri=0;ri<by_reactant.size();++ri){
        const std::vector<NFsimPublicTransformView>& row=by_reactant[ri];
        for(std::size_t mi=0;mi<row.size();++mi){
            const NFsimPublicTransformView& x=row[mi];
            if(x.kind==NATIVE_EMPTY || x.second_binding_half) continue;
            NativeTransformSnapshot n;n.kind=static_cast<NativeTransformKind>(x.kind);n.reactant=x.reactant;n.component=x.component;n.new_value=x.final_state;n.removal_type=x.removal_type;
            n.population_delta=x.population_delta;n.added_molecule_type=x.added_molecule_type;n.destination_compartment=x.destination_compartment;n.move_connected=x.move_connected;
            n.local_function_pointer=x.local_function_pointer;n.local_function_scope=x.local_function_scope;
            if(x.kind==NATIVE_UNBINDING)n.other_component=NATIVE_INFER_PARTNER_COMPONENT;
            if(x.kind==NATIVE_BINDING){
                if(x.other_reactant<0 || static_cast<std::size_t>(x.other_reactant)>=by_reactant.size())throw std::out_of_range("binding partner reactant");
                const std::vector<NFsimPublicTransformView>& other=by_reactant[static_cast<std::size_t>(x.other_reactant)];
                if(x.other_mapping_index<0 || static_cast<std::size_t>(x.other_mapping_index)>=other.size())throw std::out_of_range("binding partner mapping");
                const NFsimPublicTransformView& second=other[static_cast<std::size_t>(x.other_mapping_index)];
                if(!second.second_binding_half)throw std::logic_error("binding partner mapping is not second half");
                n.other_reactant=static_cast<std::uint16_t>(x.other_reactant);n.other_component=second.component;
            }
            out.push_back(n);
        }
    }
    return out;
}
}
