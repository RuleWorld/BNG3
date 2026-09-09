#include "nfsim_system_reader.hh"
#include <set>
#include <stdexcept>

namespace NFcore2 {
NativeModelSnapshot readNFsimSystem(const NFsimSystemReader& reader) {
    NativeModelSnapshot out;
    reader.collectCompartments(out.compartments);
    const std::size_t mt_count=reader.moleculeTypeCount();
    out.molecule_types.reserve(mt_count);
    std::set<std::string> names;
    for(std::size_t i=0;i<mt_count;++i){
        NativeMoleculeTypeSnapshot m=reader.moleculeType(i);
        if(m.name.empty())throw std::invalid_argument("empty NFsim molecule type name");
        if(!names.insert(m.name).second)throw std::invalid_argument("duplicate NFsim molecule type name");
        out.molecule_types.push_back(m);
    }
    const std::size_t nr=reader.reactionCount();
    out.rules.reserve(nr);
    for(std::size_t i=0;i<nr;++i){
        NativeReactionHeader h=reader.reactionHeader(i);
        if(h.name.empty())throw std::invalid_argument("empty NFsim reaction name");
        for(std::size_t j=0;j<h.reactant_types.size();++j)
            if(h.reactant_types[j]>=mt_count)throw std::out_of_range("NFsim reactant type outside model");
        NativeReactionSnapshot r;
        r.name=h.name;r.base_rate=h.base_rate;r.parameter_index=h.parameter_index;r.coordinate=h.coordinate;
        r.reactant_types=h.reactant_types;r.uses_local_function=h.uses_local_function;r.uses_connected_to=h.uses_connected_to;
        r.rate_law=h.rate_law;r.local_offset=h.local_offset;r.local_slope=h.local_slope;
        r.local_state_component=h.local_state_component;r.dor_weight=h.dor_weight;
        r.dor_state_component=h.dor_state_component;r.dor_partner_reactant=h.dor_partner_reactant;
        r.dor_partner_state_component=h.dor_partner_state_component;
        r.rate_expression=h.rate_expression;r.rate_expression_components=h.rate_expression_components;
        r.rate_expression_bindings=h.rate_expression_bindings;
        reader.collectDependencies(i,r.dependencies);
        reader.collectTransforms(i,r.transforms);
        reader.collectGraphPatterns(i,r.graph_patterns);
        out.rules.push_back(r);
    }
    return out;
}
} // namespace NFcore2
