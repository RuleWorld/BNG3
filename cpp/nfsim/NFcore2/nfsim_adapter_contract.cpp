#include "nfsim_adapter_contract.hh"
#include <cmath>
#include <limits>
#include <stdexcept>

namespace NFcore2 {
namespace {
struct FeatureMap {
    std::vector<std::vector<FeatureId> > state;
    std::vector<std::vector<FeatureId> > bond;
    std::vector<FeatureId> population;
    std::vector<FeatureId> existence;
    std::vector<FeatureId> compartment;
};

std::uint32_t reactantType(const NativeModelSnapshot& m,const NativeReactionSnapshot& r,std::size_t reactant) {
    if (!r.reactant_types.empty()) {
        if (reactant >= r.reactant_types.size()) throw std::out_of_range("NFsim adapter reactant index");
        if (r.reactant_types[reactant] >= m.molecule_types.size()) throw std::out_of_range("NFsim adapter molecule type");
        return r.reactant_types[reactant];
    }
    if (reactant < m.molecule_types.size()) return static_cast<std::uint32_t>(reactant);
    if (m.molecule_types.size()==1 && reactant==0) return 0;
    throw std::out_of_range("NFsim adapter reactant type unavailable");
}

std::uint32_t populationIndex(const NativeModelSnapshot& m, std::uint32_t type) {
    if (type >= m.molecule_types.size() || !m.molecule_types[type].population)
        throw std::invalid_argument("NFsim population transform requires a population type");
    std::uint32_t index = 0;
    for (std::uint32_t i = 0; i < type; ++i)
        if (m.molecule_types[i].population) ++index;
    return index;
}

void validateComponent(const NativeModelSnapshot& m,std::uint32_t type,std::uint32_t component) {
    if (type >= m.molecule_types.size() || component >= m.molecule_types[type].component_count)
        throw std::out_of_range("NFsim adapter component index");
}

LegacyPredicateIR predicate(LegacyPredicateKind k,std::uint16_t target,std::uint32_t component) {
    LegacyPredicateIR p; p.kind=k; p.target=target; p.a=component; return p;
}
LegacyTransformIR transform(LegacyTransformKind k,std::uint16_t target,std::uint32_t component,FeatureId f) {
    LegacyTransformIR t; t.kind=k; t.target=target; t.a=component; t.changed_feature=f; return t;
}
}

LegacyModelIR NFsimSnapshotAdapter::toLegacy(const NativeModelSnapshot& source) {
    LegacyModelIR out;
    FeatureMap fmap;
    fmap.state.resize(source.molecule_types.size());
    fmap.bond.resize(source.molecule_types.size());
    fmap.population.resize(source.molecule_types.size());
    fmap.existence.resize(source.molecule_types.size());
    fmap.compartment.resize(source.molecule_types.size());

    for (std::size_t ti=0; ti<source.molecule_types.size(); ++ti) {
        const NativeMoleculeTypeSnapshot& n=source.molecule_types[ti];
        MoleculeTypeDescriptor d; d.name=n.name;
        d.population=n.population;
        if (n.component_count > std::numeric_limits<std::uint16_t>::max()) throw std::invalid_argument("too many NFsim components");
        d.state_words=n.population?0:static_cast<std::uint16_t>(n.component_count);
        d.bond_slots=n.population?0:static_cast<std::uint16_t>(n.component_count);
        out.molecule_types.push_back(d);
        if (n.population) {
            fmap.population[ti]=FeatureId(static_cast<std::uint32_t>(out.features.size()));
            out.features.push_back(FeatureDescriptor(FEATURE_POPULATION,static_cast<std::uint32_t>(ti),0));
        } else {
            fmap.state[ti].resize(n.component_count);
            fmap.bond[ti].resize(n.component_count);
            for (std::uint32_t c=0;c<n.component_count;++c) {
                fmap.state[ti][c]=FeatureId(static_cast<std::uint32_t>(out.features.size()));
                out.features.push_back(FeatureDescriptor(FEATURE_MOLECULE_STATE,static_cast<std::uint32_t>(ti),c));
            }
            for (std::uint32_t c=0;c<n.component_count;++c) {
                fmap.bond[ti][c]=FeatureId(static_cast<std::uint32_t>(out.features.size()));
                out.features.push_back(FeatureDescriptor(FEATURE_MOLECULE_BOND,static_cast<std::uint32_t>(ti),c));
            }
        }
    }
    for (std::size_t ti=0; ti<source.molecule_types.size(); ++ti) {
        if (source.molecule_types[ti].population) continue;
        fmap.existence[ti]=FeatureId(static_cast<std::uint32_t>(out.features.size()));
        out.features.push_back(FeatureDescriptor(FEATURE_MOLECULE_EXISTENCE,static_cast<std::uint32_t>(ti),0));
        fmap.compartment[ti]=FeatureId(static_cast<std::uint32_t>(out.features.size()));
        out.features.push_back(FeatureDescriptor(FEATURE_MOLECULE_COMPARTMENT,static_cast<std::uint32_t>(ti),0));
    }

    for (std::size_t ri=0;ri<source.rules.size();++ri) {
        const NativeReactionSnapshot& nr=source.rules[ri];
        if (!std::isfinite(nr.base_rate) || nr.base_rate < 0.0) throw std::invalid_argument("invalid NFsim base rate");
        LegacyRuleIR r; r.name=nr.name; r.rate=nr.base_rate; r.parameter_index=nr.parameter_index; r.coordinate=nr.coordinate;
        r.uses_local_function=nr.uses_local_function; r.uses_connected_to=nr.uses_connected_to;

        if (nr.rate_law == NATIVE_RATE_LOCAL_LINEAR) {
            if (nr.reactant_types.empty()) throw std::invalid_argument("local rate law requires a reactant");
            const std::uint32_t type = reactantType(source,nr,0);
            validateComponent(source,type,nr.local_state_component);
            r.rate_law.kind=LEGACY_RATE_LOCAL_LINEAR;
            r.rate_law.target=0; r.rate_law.component=nr.local_state_component;
            r.rate_law.offset=nr.local_offset; r.rate_law.slope=nr.local_slope;
            r.uses_local_function=false;
        } else if (nr.rate_law == NATIVE_RATE_DOR_PRODUCT) {
            if (nr.reactant_types.size() < 2 || nr.dor_partner_reactant >= nr.reactant_types.size())
                throw std::invalid_argument("DOR product requires two reactants");
            const std::uint32_t left=reactantType(source,nr,0), right=reactantType(source,nr,nr.dor_partner_reactant);
            validateComponent(source,left,nr.dor_state_component);
            validateComponent(source,right,nr.dor_partner_state_component);
            r.rate_law.kind=LEGACY_RATE_DOR_PRODUCT;
            r.rate_law.target=0; r.rate_law.component=nr.dor_state_component;
            r.rate_law.partner_target=static_cast<std::uint16_t>(nr.dor_partner_reactant);
            r.rate_law.partner_component=nr.dor_partner_state_component;
            r.rate_law.offset=1.0; r.rate_law.slope=0.0; r.rate_law.weight=nr.dor_weight;
            r.uses_local_function=false;
        }

        // Root templates with no state, bond, or occupancy constraint still
        // require a live molecule at every mapped reactant position.
        for (std::size_t reactant = 0; reactant < nr.reactant_types.size(); ++reactant) {
            LegacyPredicateIR exists;
            exists.kind = LEGACY_PRED_TYPE_EXISTS;
            exists.target = static_cast<std::uint16_t>(reactant);
            exists.a = nr.reactant_types[reactant];
            r.predicates.push_back(exists);
        }

        for (std::size_t di=0;di<nr.dependencies.size();++di) {
            const NativeDependencySnapshot& d=nr.dependencies[di];
            std::uint32_t type=reactantType(source,nr,d.reactant);
            validateComponent(source,type,d.component);
            LegacyPredicateIR p;
            switch(d.kind) {
                case NATIVE_STATE_REQUIRED:
                    p=predicate(LEGACY_PRED_STATE_MASK,d.reactant,d.component);p.mask=~std::uint64_t(0);p.value=static_cast<std::uint64_t>(d.state);r.predicates.push_back(p);break;
                case NATIVE_STATE_EXCLUDED:
                    p=predicate(LEGACY_PRED_STATE_NOT_EQUAL,d.reactant,d.component);p.value=static_cast<std::uint64_t>(d.state);r.predicates.push_back(p);break;
                case NATIVE_BOND_FREE:r.predicates.push_back(predicate(LEGACY_PRED_BOND_FREE,d.reactant,d.component));break;
                case NATIVE_BOND_BOUND:r.predicates.push_back(predicate(LEGACY_PRED_BOND_PRESENT,d.reactant,d.component));break;
                case NATIVE_BOND_TO:
                    if (d.partner_reactant >= nr.reactant_types.size()) throw std::out_of_range("NFsim adapter bond partner reactant");
                    validateComponent(source,reactantType(source,nr,d.partner_reactant),d.partner_component);
                    p=predicate(LEGACY_PRED_BOND_TO,d.reactant,d.component);
                    p.b=d.partner_reactant;
                    p.value=d.partner_component;
                    p.has_partner_component=true;
                    p.partner_feature=fmap.bond[reactantType(source,nr,d.partner_reactant)][d.partner_component];
                    r.predicates.push_back(p);
                    break;
                case NATIVE_TOPOLOGY:
                    if (d.partner_reactant < nr.reactant_types.size()) {
                        p=predicate(d.partner_component==NATIVE_INFER_PARTNER_COMPONENT?LEGACY_PRED_CONNECTED_TO:LEGACY_PRED_BOND_TO,d.reactant,d.component);
                        p.b=d.partner_reactant;
                        if (d.partner_component==NATIVE_INFER_PARTNER_COMPONENT) r.predicates.push_back(p);
                        else {
                            validateComponent(source,reactantType(source,nr,d.partner_reactant),d.partner_component);
                            p.value=d.partner_component; p.has_partner_component=true;
                            p.partner_feature=fmap.bond[reactantType(source,nr,d.partner_reactant)][d.partner_component];
                            r.predicates.push_back(p);
                        }
                    } else r.uses_connected_to=true;
                    break;
                case NATIVE_PARTNER_STATE_REQUIRED:
                case NATIVE_PARTNER_STATE_EXCLUDED:
                    if (d.partner_reactant < nr.reactant_types.size()) {
                        const std::uint32_t partner_type=reactantType(source,nr,d.partner_reactant);
                        validateComponent(source,partner_type,d.partner_state_component);
                        p=predicate(d.kind==NATIVE_PARTNER_STATE_REQUIRED?LEGACY_PRED_STATE_MASK:LEGACY_PRED_STATE_NOT_EQUAL,d.partner_reactant,d.partner_state_component);
                        p.mask=~std::uint64_t(0); p.value=static_cast<std::uint64_t>(d.state); r.predicates.push_back(p);
                    } else r.uses_connected_to=true;
                    break;
                case NATIVE_COMPARTMENT_REQUIRED:
                    p=predicate(LEGACY_PRED_COMPARTMENT,d.reactant,0);p.value=d.compartment;r.predicates.push_back(p);break;
                default:r.uses_connected_to=true;break;
            }
        }

        for (std::size_t xi=0;xi<nr.transforms.size();++xi) {
            const NativeTransformSnapshot& x=nr.transforms[xi];
            const bool zero_reactant_population_transform =
                nr.reactant_types.empty() &&
                (x.kind == NATIVE_INCREMENT_POPULATION ||
                 x.kind == NATIVE_DECREMENT_POPULATION);
            const bool has_reactant =
                x.kind != NATIVE_ADD && !zero_reactant_population_transform;
            std::uint32_t type = 0;
            if (has_reactant) {
                type=reactantType(source,nr,x.reactant);
                if (x.kind!=NATIVE_EMPTY && x.kind!=NATIVE_LOCAL_FUNCTION_REFERENCE && x.kind!=NATIVE_MOVE &&
                    x.kind!=NATIVE_INCREMENT_POPULATION && x.kind!=NATIVE_DECREMENT_POPULATION)
                    validateComponent(source,type,x.component);
            } else if (zero_reactant_population_transform) {
                type = x.added_molecule_type;
                if (type >= source.molecule_types.size())
                    throw std::out_of_range("NFsim population transform molecule type");
            }
            LegacyTransformIR t;
            switch(x.kind) {
                case NATIVE_STATE_CHANGE:
                    t=transform(LEGACY_TRANSFORM_SET_STATE_WORD,x.reactant,x.component,fmap.state[type][x.component]);t.value=x.new_value;r.transforms.push_back(t);break;
                case NATIVE_BINDING:{
                    std::uint32_t ot=reactantType(source,nr,x.other_reactant);validateComponent(source,ot,x.other_component);
                    t=transform(LEGACY_TRANSFORM_BIND,x.reactant,x.component,fmap.bond[type][x.component]);t.other=x.other_reactant;t.b=x.other_component;r.transforms.push_back(t);r.changes_topology=true;r.topology_change_is_local=true;break;}
                case NATIVE_UNBINDING:
                    t=transform(LEGACY_TRANSFORM_UNBIND,x.reactant,x.component,fmap.bond[type][x.component]);t.b=x.other_component;r.transforms.push_back(t);r.changes_topology=true;r.topology_change_is_local=true;break;
                case NATIVE_REMOVE:
                    r.changes_topology=true;
                    if (x.removal_type==NATIVE_DELETE_MOLECULE_ONLY) {t=transform(LEGACY_TRANSFORM_DELETE_MOLECULE,x.reactant,0,fmap.existence[type]);r.transforms.push_back(t);r.topology_change_is_local=true;}
                    else if (x.removal_type==NATIVE_DELETE_COMPLETE_SPECIES) {t=transform(LEGACY_TRANSFORM_DELETE_SPECIES,x.reactant,0,FeatureId());r.transforms.push_back(t);r.topology_change_is_local=true;}
                    else {t.kind=LEGACY_TRANSFORM_UNSUPPORTED;r.transforms.push_back(t);r.topology_change_is_local=false;}
                    break;
                case NATIVE_EMPTY: break;
                case NATIVE_LOCAL_FUNCTION_REFERENCE:r.uses_local_function=true;break;
                case NATIVE_INCREMENT_STATE:
                    t=transform(LEGACY_TRANSFORM_ADD_STATE_WORD,x.reactant,x.component,fmap.state[type][x.component]);t.value=1;r.transforms.push_back(t);break;
                case NATIVE_DECREMENT_STATE:
                    t=transform(LEGACY_TRANSFORM_ADD_STATE_WORD,x.reactant,x.component,fmap.state[type][x.component]);t.value=-1;r.transforms.push_back(t);break;
                case NATIVE_ADD:
                    if (x.added_molecule_type >= source.molecule_types.size() || source.molecule_types[x.added_molecule_type].population)
                        throw std::invalid_argument("NFsim synthesis molecule type");
                    t=transform(LEGACY_TRANSFORM_CREATE_MOLECULE,x.reactant,x.added_molecule_type,fmap.existence[x.added_molecule_type]);
                    r.transforms.push_back(t);break;
                case NATIVE_INCREMENT_POPULATION:
                    t=transform(LEGACY_TRANSFORM_POPULATION_ADD,x.reactant,0,fmap.population[type]);
                    t.a=populationIndex(source,type);t.value=x.population_delta==0?1:x.population_delta;r.transforms.push_back(t);break;
                case NATIVE_DECREMENT_POPULATION:
                    t=transform(LEGACY_TRANSFORM_POPULATION_ADD,x.reactant,0,fmap.population[type]);
                    t.a=populationIndex(source,type);t.value=-(x.population_delta==0?1:x.population_delta);r.transforms.push_back(t);break;
                case NATIVE_MOVE:
                    t=transform(LEGACY_TRANSFORM_MOVE_MOLECULE,x.reactant,0,fmap.compartment[type]);t.a=x.destination_compartment;r.transforms.push_back(t);break;
                default:t.kind=LEGACY_TRANSFORM_UNSUPPORTED;r.transforms.push_back(t);break;
            }
        }
        out.rules.push_back(r);
    }
    return out;
}

} // namespace NFcore2
