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

LegacyPredicateIR predicate(LegacyPredicateKind k,std::uint16_t target,
                            std::uint32_t component,
                            std::uint32_t owner=std::numeric_limits<std::uint32_t>::max()) {
    LegacyPredicateIR p; p.kind=k; p.target=target; p.owner=owner; p.a=component; return p;
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
    for (const auto& compartment : source.compartments) {
        CompartmentDescriptor d;
        d.id=compartment.id; d.parent=compartment.parent;
        d.dimensions=compartment.dimensions; d.size=compartment.size;
        out.compartments.push_back(d);
    }

    for (std::size_t ri=0;ri<source.rules.size();++ri) {
        const NativeReactionSnapshot& nr=source.rules[ri];
        if (!std::isfinite(nr.base_rate) || nr.base_rate < 0.0) throw std::invalid_argument("invalid NFsim base rate");
        LegacyRuleIR r; r.name=nr.name; r.rate=nr.base_rate; r.parameter_index=nr.parameter_index; r.coordinate=nr.coordinate;
        r.uses_local_function=nr.uses_local_function; r.uses_connected_to=nr.uses_connected_to;

        for (const auto& nativeGraph : nr.graph_patterns) {
            GraphPattern graph;
            graph.nodes.reserve(nativeGraph.nodes.size());
            for (const auto& node : nativeGraph.nodes) {
                if (node.molecule_type >= source.molecule_types.size())
                    throw std::out_of_range("NFsim graph molecule type");
                if (node.reactant != std::numeric_limits<std::uint16_t>::max()) {
                    if (node.reactant >= nr.reactant_types.size() || nr.reactant_types[node.reactant] != node.molecule_type)
                        throw std::invalid_argument("NFsim graph anchor does not match reactant");
                }
                if (node.state_component != std::numeric_limits<std::uint32_t>::max())
                    validateComponent(source, node.molecule_type, node.state_component);
                GraphNodePattern outNode;
                outNode.molecule_type=node.molecule_type;
                outNode.anchor_reactant=node.reactant;
                outNode.state_component=node.state_component;
                outNode.compartment=node.compartment;
                outNode.free_components=node.free_components;
                outNode.bound_components=node.bound_components;
                outNode.state_value=node.state;
                for (const auto& state : node.state_constraints) {
                    validateComponent(source, node.molecule_type, state.first);
                    if (state.second < 0)
                        throw std::invalid_argument("NFsim graph state constraint is negative");
                    outNode.state_constraints.push_back(state);
                }
                for (const auto& excluded : node.excluded_states) {
                    validateComponent(source, node.molecule_type, excluded.first);
                    if (excluded.second < 0)
                        throw std::invalid_argument("NFsim graph state exclusion is negative");
                    outNode.excluded_states.push_back(excluded);
                }
                // Older producers only populated the scalar state fields.
                // Preserve that representation when no vector payload is
                // available, while preferring the complete vector form.
                if (outNode.state_constraints.empty() &&
                    node.state_component != std::numeric_limits<std::uint32_t>::max() &&
                    node.state >= 0) {
                    validateComponent(source, node.molecule_type, node.state_component);
                    outNode.state_constraints.push_back(
                        std::make_pair(node.state_component, node.state));
                }
                for (const auto component : outNode.free_components)
                    validateComponent(source, node.molecule_type, component);
                for (const auto component : outNode.bound_components)
                    validateComponent(source, node.molecule_type, component);
                for (const auto& nativeSymmetric : node.symmetric_constraints) {
                    if (nativeSymmetric.components.empty() || nativeSymmetric.state < -1 ||
                        (nativeSymmetric.bond_state != -1 && nativeSymmetric.bond_state != 0 &&
                         nativeSymmetric.bond_state != 1))
                        throw std::invalid_argument("NFsim symmetric graph constraint is malformed");
                    SymmetricConstraintPattern symmetric;
                    symmetric.state_value = nativeSymmetric.state;
                    symmetric.bond_state = nativeSymmetric.bond_state;
                    symmetric.partner_node = nativeSymmetric.partner_node;
                    symmetric.partner_symmetric = nativeSymmetric.partner_symmetric;
                    for (const auto component : nativeSymmetric.components) {
                        validateComponent(source, node.molecule_type, component);
                        symmetric.components.push_back(component);
                    }
                    if (symmetric.partner_node != std::numeric_limits<std::uint32_t>::max()) {
                        if (symmetric.partner_node >= nativeGraph.nodes.size() ||
                            symmetric.partner_node == graph.nodes.size())
                            throw std::invalid_argument("NFsim symmetric graph partner node out of range");
                    }
                    if (symmetric.partner_symmetric && nativeSymmetric.partner_components.empty())
                        throw std::invalid_argument("NFsim symmetric graph partner class is empty");
                    if (symmetric.partner_node != std::numeric_limits<std::uint32_t>::max()) {
                        const std::uint32_t partnerType = nativeGraph.nodes[symmetric.partner_node].molecule_type;
                        for (const auto component : nativeSymmetric.partner_components)
                            validateComponent(source, partnerType, component);
                    } else if (!nativeSymmetric.partner_components.empty()) {
                        throw std::invalid_argument("NFsim symmetric graph partner component without partner node");
                    }
                    symmetric.partner_components = nativeSymmetric.partner_components;
                    outNode.symmetric_constraints.push_back(symmetric);
                }
                graph.nodes.push_back(outNode);
            }
            if (graph.nodes.empty()) throw std::invalid_argument("NFsim graph expression has no nodes");
            for (const auto& edge : nativeGraph.edges) {
                if (edge.first_node >= graph.nodes.size() || edge.second_node >= graph.nodes.size() || edge.first_node == edge.second_node)
                    throw std::invalid_argument("NFsim graph edge node out of range");
                validateComponent(source, graph.nodes[edge.first_node].molecule_type, edge.first_component);
                validateComponent(source, graph.nodes[edge.second_node].molecule_type, edge.second_component);
                GraphEdgePattern outEdge;
                outEdge.first_node=edge.first_node; outEdge.first_component=edge.first_component;
                outEdge.second_node=edge.second_node; outEdge.second_component=edge.second_component;
                graph.edges.push_back(outEdge);
            }
            for (const auto& connected : nativeGraph.connected_to) {
                if (connected.first_node >= graph.nodes.size() ||
                    connected.second_node >= graph.nodes.size() ||
                    connected.first_node == connected.second_node)
                    throw std::invalid_argument("NFsim connectedTo graph node out of range");
                graph.connected_to.push_back(
                    GraphConnectivityPattern(connected.first_node, connected.second_node));
            }
            r.graph_patterns.push_back(graph);
        }

        if (nr.rate_law == NATIVE_RATE_EXPRESSION) {
            if (nr.rate_expression.empty()) throw std::invalid_argument("expression rate law requires an expression");
            if (nr.rate_expression_components.size() > nr.reactant_types.size()) throw std::invalid_argument("expression rate-law component map exceeds reactants");
            for (std::size_t component = 0; component < nr.rate_expression_components.size(); ++component) {
                const std::uint32_t type = reactantType(source, nr, component);
                if (source.molecule_types[type].population)
                    throw std::invalid_argument("expression rate law cannot read a population type state");
                validateComponent(source, type, nr.rate_expression_components[component]);
            }
            r.rate_law.kind=LEGACY_RATE_EXPRESSION;
            r.rate_law.expression=nr.rate_expression;
            r.rate_law.expression_components=nr.rate_expression_components;
            for (const auto& nativeBinding : nr.rate_expression_bindings) {
                RateExpressionBinding binding;
                binding.name = nativeBinding.name;
                binding.target = nativeBinding.reactant;
                binding.component = nativeBinding.component;
                binding.molecule_type = nativeBinding.molecule_type;
                binding.scope = nativeBinding.scope;
                binding.value = nativeBinding.value;
                if (binding.name.empty()) throw std::invalid_argument("expression binding name is empty");
                for (const auto& prior : r.rate_law.expression_bindings)
                    if (prior.name == binding.name)
                        throw std::invalid_argument("duplicate expression binding name");
                if (nativeBinding.kind == NATIVE_RATE_EXPRESSION_STATE) {
                    binding.kind = RATE_EXPRESSION_STATE;
                    const std::uint32_t type = reactantType(source, nr, binding.target);
                    if (source.molecule_types[type].population)
                        throw std::invalid_argument("expression binding cannot read a population type state");
                    validateComponent(source, type, binding.component);
                } else if (nativeBinding.kind == NATIVE_RATE_EXPRESSION_CONSTANT) {
                    binding.kind = RATE_EXPRESSION_CONSTANT;
                    if (!std::isfinite(binding.value))
                        throw std::invalid_argument("expression constant binding is not finite");
                } else if (nativeBinding.kind == NATIVE_RATE_EXPRESSION_REACTANT_COUNT) {
                    if (binding.target >= nr.reactant_types.size())
                        throw std::out_of_range("reactant-count binding target");
                    binding.kind = RATE_EXPRESSION_REACTANT_COUNT;
                } else if (nativeBinding.kind == NATIVE_RATE_EXPRESSION_SPECIES_MOLECULE_COUNT) {
                    if (binding.target >= nr.reactant_types.size())
                        throw std::out_of_range("species-scope binding target");
                    const std::uint32_t scopeType = reactantType(source, nr, binding.target);
                    if (source.molecule_types[scopeType].population)
                        throw std::invalid_argument("species-scope binding cannot read a population type");
                    if (binding.molecule_type != std::numeric_limits<std::uint32_t>::max()) {
                        if (binding.molecule_type >= source.molecule_types.size() ||
                            source.molecule_types[binding.molecule_type].population)
                            throw std::invalid_argument("scoped observable binding molecule type");
                        if (binding.scope != 0 && binding.scope != 1)
                            throw std::invalid_argument("scoped observable binding scope");
                    }
                    binding.kind = RATE_EXPRESSION_SPECIES_MOLECULE_COUNT;
                } else if (nativeBinding.kind == NATIVE_RATE_EXPRESSION_COMPARTMENT_VOLUME) {
                    if (binding.target >= nr.reactant_types.size())
                        throw std::out_of_range("compartment-volume binding target");
                    const std::uint32_t compartmentType = reactantType(source, nr, binding.target);
                    if (source.molecule_types[compartmentType].population)
                        throw std::invalid_argument("compartment-volume binding cannot read a population type");
                    binding.kind = RATE_EXPRESSION_COMPARTMENT_VOLUME;
                } else {
                    throw std::invalid_argument("unknown expression binding kind");
                }
                r.rate_law.expression_bindings.push_back(binding);
            }
            r.uses_local_function=false;
        } else if (nr.rate_law == NATIVE_RATE_LOCAL_LINEAR) {
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
            // Population types are represented by PopulationStore entries, not
            // particle handles. Requiring a TYPE_EXISTS particle predicate
            // would make every population rule unmatchable in the direct
            // engine; match the population store count instead.
            if (nr.reactant_types[reactant] < source.molecule_types.size() &&
                source.molecule_types[nr.reactant_types[reactant]].population) {
                LegacyPredicateIR population;
                population.kind = LEGACY_PRED_POPULATION_AT_LEAST;
                population.target = static_cast<std::uint16_t>(reactant);
                population.a = populationIndex(source, nr.reactant_types[reactant]);
                population.value = 1;
                r.predicates.push_back(population);
                continue;
            }
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
                    p=predicate(LEGACY_PRED_STATE_MASK,d.reactant,d.component,type);p.mask=~std::uint64_t(0);p.value=static_cast<std::uint64_t>(d.state);r.predicates.push_back(p);break;
                case NATIVE_STATE_EXCLUDED:
                    p=predicate(LEGACY_PRED_STATE_NOT_EQUAL,d.reactant,d.component,type);p.value=static_cast<std::uint64_t>(d.state);r.predicates.push_back(p);break;
                case NATIVE_BOND_FREE:r.predicates.push_back(predicate(LEGACY_PRED_BOND_FREE,d.reactant,d.component,type));break;
                case NATIVE_BOND_BOUND:r.predicates.push_back(predicate(LEGACY_PRED_BOND_PRESENT,d.reactant,d.component,type));break;
                case NATIVE_BOND_TO:
                    if (d.partner_reactant >= nr.reactant_types.size()) throw std::out_of_range("NFsim adapter bond partner reactant");
                    validateComponent(source,reactantType(source,nr,d.partner_reactant),d.partner_component);
                    p=predicate(LEGACY_PRED_BOND_TO,d.reactant,d.component,type);
                    p.b=d.partner_reactant;
                    p.value=d.partner_component;
                    p.has_partner_component=true;
                    p.partner_feature=fmap.bond[reactantType(source,nr,d.partner_reactant)][d.partner_component];
                    r.predicates.push_back(p);
                    break;
                case NATIVE_TOPOLOGY:
                    if (d.partner_reactant < nr.reactant_types.size()) {
                        p=predicate(d.partner_component==NATIVE_INFER_PARTNER_COMPONENT?LEGACY_PRED_CONNECTED_TO:LEGACY_PRED_BOND_TO,d.reactant,d.component,type);
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
                        p=predicate(d.kind==NATIVE_PARTNER_STATE_REQUIRED?LEGACY_PRED_STATE_MASK:LEGACY_PRED_STATE_NOT_EQUAL,d.partner_reactant,d.partner_state_component,partner_type);
                        p.mask=~std::uint64_t(0); p.value=static_cast<std::uint64_t>(d.state); r.predicates.push_back(p);
                    } else r.uses_connected_to=true;
                    break;
                case NATIVE_COMPARTMENT_REQUIRED:
                    p=predicate(d.compartment_ancestry ? LEGACY_PRED_COMPARTMENT_INSIDE : LEGACY_PRED_COMPARTMENT,d.reactant,type);p.value=d.compartment;r.predicates.push_back(p);break;
                default:r.uses_connected_to=true;break;
            }
        }

        for (std::size_t xi=0;xi<nr.transforms.size();++xi) {
            const NativeTransformSnapshot& x=nr.transforms[xi];
            if (x.kind == NATIVE_REMOVE && nr.reactant_types.empty())
                throw std::invalid_argument("NFsim molecule removal requires a reactant");
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
                    else if (x.removal_type==NATIVE_DELETE_MOLECULE_CONDITIONAL) {t=transform(LEGACY_TRANSFORM_DELETE_MOLECULE_CONDITIONAL,x.reactant,0,fmap.existence[type]);r.transforms.push_back(t);r.topology_change_is_local=true;}
                    else {t.kind=LEGACY_TRANSFORM_UNSUPPORTED;r.transforms.push_back(t);r.topology_change_is_local=false;}
                    break;
                case NATIVE_EMPTY: break;
                case NATIVE_LOCAL_FUNCTION_REFERENCE:
                    if (x.local_function_pointer.empty() ||
                        (x.local_function_scope != 0 && x.local_function_scope != 1))
                        throw std::invalid_argument("NFsim local-function reference scope is malformed");
                    // A simple scoped local function is already represented
                    // by the executable expression descriptor. The transform
                    // is only a legacy bookkeeping marker in that case.
                    if (nr.rate_law != NATIVE_RATE_EXPRESSION)
                        r.uses_local_function=true;
                    break;
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
                    if (x.move_connected) {
                        t=transform(LEGACY_TRANSFORM_MOVE_SPECIES,x.reactant,0,fmap.compartment[type]);
                        t.a=x.destination_compartment;
                        r.transforms.push_back(t);
                        r.changes_topology=true;
                        r.topology_change_is_local=true;
                    } else {
                        t=transform(LEGACY_TRANSFORM_MOVE_MOLECULE,x.reactant,0,fmap.compartment[type]);
                        t.a=x.destination_compartment;
                        r.transforms.push_back(t);
                    }
                    break;
                default:t.kind=LEGACY_TRANSFORM_UNSUPPORTED;r.transforms.push_back(t);break;
            }
        }
        out.rules.push_back(r);
    }
    return out;
}

} // namespace NFcore2
