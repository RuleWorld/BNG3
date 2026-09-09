#include "legacy_bridge.hh"
#include <map>
#include <sstream>
#include <stdexcept>
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <functional>
#include <unordered_map>
#include "parser/BNGAstVisitor.hpp"

namespace NFcore2 {

double RateLawDescriptor::evaluate(const SimulationState& state,
                                   const MatchContext& context,
                                   double base_rate) const {
    if (kind == LEGACY_RATE_CONSTANT) {
        if (!std::isfinite(base_rate) || base_rate < 0.0)
            throw std::domain_error("constant rate produced invalid propensity");
        return base_rate;
    }
    if (kind == LEGACY_RATE_EXPRESSION) {
        if (expression.empty()) throw std::invalid_argument("empty expression rate law");
        const auto parsed = bng::parser::parseExpression(expression);
        const auto bondMatches = [&](const MoleculeStore& store,
                                     MoleculeHandle handle,
                                     const RateExpressionBinding& binding) {
            if (binding.bond_component == std::numeric_limits<std::uint32_t>::max())
                return true;
            if (binding.bond_component > std::numeric_limits<std::uint16_t>::max() ||
                binding.bond_state < 0 || binding.bond_state > 1 ||
                binding.bond_component >= store.bondSlotCount())
                throw std::out_of_range("expression binding bond component");
            const bool occupied = store.bondRef(
                handle, static_cast<std::uint16_t>(binding.bond_component)).valid();
            return binding.bond_state == (occupied ? 1 : 0);
        };
        const auto compartmentMatches = [&](const MoleculeStore& store,
                                             MoleculeHandle handle,
                                             const RateExpressionBinding& binding) {
            if (binding.compartment == std::numeric_limits<std::uint32_t>::max())
                return true;
            const std::uint32_t actual = store.compartment(handle);
            return binding.compartment_ancestry
                ? state.model().compartmentInside(actual, binding.compartment)
                : actual == binding.compartment;
        };
        const auto interpolate = [](const RateExpressionFunction& function, double counter) {
            if (function.table_x.empty() || function.table_x.size() != function.table_y.size())
                throw std::invalid_argument("TFUN table is empty or has mismatched columns");
            if (function.table_x.size() == 1) return function.table_y.front();
            for (std::size_t i = 1; i < function.table_x.size(); ++i)
                if (!std::isfinite(function.table_x[i]) || function.table_x[i] <= function.table_x[i - 1])
                    throw std::invalid_argument("TFUN table counter must be strictly increasing");
            if (counter <= function.table_x.front()) return function.table_y.front();
            if (counter >= function.table_x.back()) return function.table_y.back();
            std::size_t upper = 1;
            while (upper < function.table_x.size() && counter > function.table_x[upper]) ++upper;
            const std::size_t lower = upper - 1;
            if (function.table_method == "step") return function.table_y[lower];
            const double span = function.table_x[upper] - function.table_x[lower];
            const double fraction = (counter - function.table_x[lower]) / span;
            return function.table_y[lower] + fraction *
                (function.table_y[upper] - function.table_y[lower]);
        };
        std::function<double(const std::string&, const std::vector<double>&)> resolveFunction;
        std::function<double(const std::string&)> resolve;
        resolveFunction = [&](const std::string& name,
                              const std::vector<double>& arguments) -> double {
            const RateExpressionFunction* definition = nullptr;
            for (const auto& candidate : expression_functions) {
                if (candidate.name == name) {
                    definition = &candidate;
                    break;
                }
            }
            if (definition == nullptr) {
                // Observable references in legacy local functions are emitted
                // as calls such as atotal(x). Their binding already captures
                // the scoped count; the parser callback only needs to ignore
                // the scope argument.
                if (!arguments.empty()) return resolve(name);
                throw std::out_of_range("unknown expression function '" + name + "'");
            }
            if (arguments.size() > definition->arguments.size())
                throw std::invalid_argument("expression function argument count mismatch");
            const auto functionExpression = bng::parser::parseExpression(definition->expression);
            std::unordered_map<std::string, double> local;
            for (std::size_t i = 0; i < arguments.size(); ++i)
                local.emplace(definition->arguments[i], arguments[i]);
            // Legacy DOR wrappers often expose the scoped function as a
            // zero-argument identifier even though its LocalFunction carries
            // one scope argument. The scope is already encoded in the
            // observable bindings, so unused formal arguments can be zero.
            for (std::size_t i = arguments.size(); i < definition->arguments.size(); ++i)
                local.emplace(definition->arguments[i], 0.0);
            const auto tableValue = [&]() {
                if (definition->table_x.empty()) return 0.0;
                const double counter = definition->table_counter.empty() ||
                    definition->table_counter == "time" || definition->table_counter == "Time"
                    ? state.time() : resolve(definition->table_counter);
                return interpolate(*definition, counter);
            };
            const auto functionResolve = [&](const std::string& symbol) -> double {
                const auto it = local.find(symbol);
                if (it != local.end()) return it->second;
                if (symbol == "__TFUN_VAL__" || symbol == "__TFUN__VAL__")
                    return tableValue();
                return resolve(symbol);
            };
            return functionExpression.evaluateWithFunctions(
                functionResolve, state.time(), resolveFunction);
        };
        resolve = [&](const std::string& name) -> double {
            for (const auto& binding : expression_bindings) {
                if (binding.name != name) continue;
                if (binding.kind == RATE_EXPRESSION_CONSTANT) {
                    if (!std::isfinite(binding.value))
                        throw std::domain_error("expression binding is not finite");
                    return binding.value;
                }
                if (binding.kind == RATE_EXPRESSION_REACTANT_COUNT) {
                    if (binding.target >= context.reactant_counts.size())
                        throw std::out_of_range("expression reactant-count binding missing");
                    return static_cast<double>(context.reactant_counts[binding.target]);
                }
                if (binding.kind == RATE_EXPRESSION_GLOBAL_MOLECULE_COUNT) {
                    if (binding.molecule_type >= state.model().moleculeTypes().size())
                        throw std::out_of_range("global observable molecule type");
                    const MoleculeStore& store = state.molecules(
                        MoleculeTypeId(binding.molecule_type));
                    if (binding.state_component == std::numeric_limits<std::uint32_t>::max() &&
                        binding.bond_component == std::numeric_limits<std::uint32_t>::max() &&
                        binding.compartment == std::numeric_limits<std::uint32_t>::max())
                        return static_cast<double>(store.liveCount());
                    if (binding.state_component > std::numeric_limits<std::uint16_t>::max() &&
                        binding.state_component != std::numeric_limits<std::uint32_t>::max())
                        throw std::out_of_range("global observable state component");
                    double count = 0.0;
                    for (const auto handle : store.liveHandles()) {
                        const bool state_match = binding.state_component ==
                            std::numeric_limits<std::uint32_t>::max() ||
                            store.stateWord(handle, static_cast<std::uint16_t>(binding.state_component)) ==
                                static_cast<std::uint64_t>(binding.state_value);
                        if (state_match && bondMatches(store, handle, binding) &&
                            compartmentMatches(store, handle, binding)) count += 1.0;
                    }
                    return count;
                }
                if (binding.kind == RATE_EXPRESSION_COMPLEX_MOLECULE_COUNT) {
                    if (binding.molecule_type >= state.model().moleculeTypes().size() ||
                        binding.partner_molecule_type >= state.model().moleculeTypes().size())
                        throw std::out_of_range("complex observable molecule type");
                    const auto rootMatches = [&](MoleculeRef root) {
                        if (!root.valid() || root.type.value() != binding.molecule_type ||
                            !state.molecules(root.type).alive(root.handle))
                            return false;
                        const MoleculeStore& rootStore = state.molecules(root.type);
                        if (binding.state_component != std::numeric_limits<std::uint32_t>::max() &&
                            rootStore.stateWord(root.handle,
                                static_cast<std::uint16_t>(binding.state_component)) !=
                                static_cast<std::uint64_t>(binding.state_value))
                            return false;
                        if (!compartmentMatches(rootStore, root.handle, binding)) return false;
                        const MoleculeRef partner = rootStore.bondRef(
                            root.handle, static_cast<std::uint16_t>(binding.component));
                        if (!partner.valid() || partner.type.value() != binding.partner_molecule_type ||
                            !state.molecules(partner.type).alive(partner.handle))
                            return false;
                        const MoleculeStore& partnerStore = state.molecules(partner.type);
                        if (!(partnerStore.bondRef(partner.handle,
                                static_cast<std::uint16_t>(binding.partner_component)) == root))
                            return false;
                        if (binding.partner_state_component != std::numeric_limits<std::uint32_t>::max() &&
                            partnerStore.stateWord(partner.handle,
                                static_cast<std::uint16_t>(binding.partner_state_component)) !=
                                static_cast<std::uint64_t>(binding.partner_state_value))
                            return false;
                        return true;
                    };
                    if (binding.scope == 1) {
                        const MoleculeRef ref = context.moleculeAt(binding.target);
                        return rootMatches(ref) ? 1.0 : 0.0;
                    }
                    if (binding.scope == 0) {
                        const MoleculeRef ref = context.moleculeAt(binding.target);
                        if (!ref.valid()) throw std::out_of_range("complex observable reactant missing");
                        double count = 0.0;
                        for (const auto& member : state.connectedComponent(ref))
                            if (rootMatches(member)) count += 1.0;
                        return count;
                    }
                    if (binding.scope != -1)
                        throw std::invalid_argument("invalid complex observable binding scope");
                    double count = 0.0;
                    const MoleculeStore& store = state.molecules(
                        MoleculeTypeId(binding.molecule_type));
                    for (const auto handle : store.liveHandles())
                        if (rootMatches(MoleculeRef(MoleculeTypeId(binding.molecule_type), handle)))
                            count += 1.0;
                    return count;
                }
                const MoleculeRef ref = context.moleculeAt(binding.target);
                if (!ref.valid()) throw std::out_of_range("expression binding reactant missing");
                if (binding.kind == RATE_EXPRESSION_SPECIES_MOLECULE_COUNT) {
                    const std::vector<MoleculeRef> members = state.connectedComponent(ref);
                    if (binding.molecule_type != std::numeric_limits<std::uint32_t>::max()) {
                        if (binding.scope == 1) {
                            const MoleculeStore& store = state.molecules(ref.type);
                            return ref.type.value() == binding.molecule_type &&
                                   (binding.state_component == std::numeric_limits<std::uint32_t>::max() ||
                                    store.stateWord(ref.handle, static_cast<std::uint16_t>(binding.state_component)) ==
                                        static_cast<std::uint64_t>(binding.state_value)) &&
                                   bondMatches(store, ref.handle, binding) &&
                                   compartmentMatches(store, ref.handle, binding) ? 1.0 : 0.0;
                        }
                        if (binding.scope != 0)
                            throw std::invalid_argument("invalid scoped observable binding");
                        double count = 0.0;
                        for (const auto& member : members) {
                            const MoleculeStore& store = state.molecules(member.type);
                            if (member.type.value() == binding.molecule_type &&
                                (binding.state_component == std::numeric_limits<std::uint32_t>::max() ||
                                 store.stateWord(member.handle, static_cast<std::uint16_t>(binding.state_component)) ==
                                     static_cast<std::uint64_t>(binding.state_value)) &&
                                bondMatches(store, member.handle, binding) &&
                                compartmentMatches(store, member.handle, binding))
                                count += 1.0;
                        }
                        return count;
                    }
                    return static_cast<double>(members.size());
                }
                if (binding.kind == RATE_EXPRESSION_COMPARTMENT_VOLUME) {
                    return state.compartmentSize(
                        state.molecules(ref.type).compartment(ref.handle));
                }
                if (binding.kind == RATE_EXPRESSION_TRANSPORT_VOLUME_RATIO) {
                    return state.transportVolumeRatio(
                        state.molecules(ref.type).compartment(ref.handle),
                        binding.destination_compartment);
                }
                if (binding.component > std::numeric_limits<std::uint16_t>::max())
                    throw std::out_of_range("expression binding state component overflow");
                return static_cast<double>(state.molecules(ref.type).stateWord(
                    ref.handle, static_cast<std::uint16_t>(binding.component)));
            }
            if (name.size() > 1 && name[0] == 's') {
                char* end = nullptr; const unsigned long index = std::strtoul(name.c_str()+1, &end, 10);
                if (*end == '\0' && index < expression_components.size()) {
                    const MoleculeRef ref = context.moleculeAt(index);
                    if (!ref.valid()) throw std::out_of_range("expression reactant missing");
                    if (expression_components[index] > std::numeric_limits<std::uint16_t>::max())
                        throw std::out_of_range("expression state component overflow");
                    return static_cast<double>(state.molecules(ref.type).stateWord(ref.handle, static_cast<std::uint16_t>(expression_components[index])));
                }
            }
            for (const auto& function : expression_functions)
                if (function.name == name)
                    return resolveFunction(name, {});
            throw std::out_of_range("unknown expression rate-law symbol '" + name + "'");
        };
        const double result = parsed.evaluateWithFunctions(resolve, state.time(), resolveFunction);
        if (!std::isfinite(result) || result < 0.0) throw std::domain_error("expression rate law produced invalid propensity");
        const double propensity = base_rate * result;
        if (!std::isfinite(propensity) || propensity < 0.0)
            throw std::domain_error("expression rate law produced invalid propensity");
        return propensity;
    }
    const MoleculeRef left = context.moleculeAt(target);
    if (!left.valid()) throw std::out_of_range("rate-law target missing");
    if (component > std::numeric_limits<std::uint16_t>::max())
        throw std::out_of_range("rate-law state component overflow");
    const double left_value = static_cast<double>(
        state.molecules(left.type).stateWord(left.handle, static_cast<std::uint16_t>(component)));
    double result = base_rate;
    if (kind == LEGACY_RATE_LOCAL_LINEAR)
        result = base_rate * (offset + slope * left_value);
    if (kind == LEGACY_RATE_DOR_PRODUCT) {
        const MoleculeRef right = context.moleculeAt(partner_target);
        if (!right.valid()) throw std::out_of_range("DOR partner target missing");
        if (partner_component > std::numeric_limits<std::uint16_t>::max())
            throw std::out_of_range("DOR partner state component overflow");
        const double right_value = static_cast<double>(
            state.molecules(right.type).stateWord(right.handle, static_cast<std::uint16_t>(partner_component)));
        result = base_rate * weight * (offset + slope * left_value) *
            (offset + slope * right_value);
    } else if (kind != LEGACY_RATE_LOCAL_LINEAR) {
        throw std::logic_error("unknown rate-law kind");
    }
    if (!std::isfinite(result) || result < 0.0)
        throw std::domain_error("rate law produced invalid propensity");
    return result;
}

namespace {

LoweringFallbackReason unsupportedReason(const LegacyRuleIR& r) {
    // NFsim's native reader emits executable expression/function descriptors
    // and graph patterns for these cases.  Keep fallback only when extraction
    // really failed, so direct LocalFunction/DOR and connectedTo rules reach
    // the same matcher/rate paths as ordinary reactions.
    if (r.uses_local_function && r.rate_law.kind != LEGACY_RATE_EXPRESSION)
        return LOWERING_LOCAL_FUNCTION;
    if (r.uses_connected_to && r.graph_patterns.empty())
        return LOWERING_CONNECTED_TO;
    if (r.changes_topology && !r.topology_change_is_local) return LOWERING_TOPOLOGY_CHANGE;
    for (std::size_t i=0;i<r.predicates.size();++i)
        if (r.predicates[i].kind == LEGACY_PRED_UNSUPPORTED) return LOWERING_UNSUPPORTED_PREDICATE;
    for (std::size_t i=0;i<r.transforms.size();++i)
        if (r.transforms[i].kind == LEGACY_TRANSFORM_UNSUPPORTED) return LOWERING_UNSUPPORTED_TRANSFORM;
    return LOWERING_SUPPORTED;
}

MatchInstruction lowerPredicate(const LegacyPredicateIR& p) {
    MatchOpcode op = MATCH_END;
    switch (p.kind) {
        case LEGACY_PRED_TYPE_EXISTS: op=MATCH_TYPE_EXISTS; break;
        case LEGACY_PRED_STATE_MASK: op=MATCH_STATE_MASK; break;
        case LEGACY_PRED_STATE_NOT_EQUAL: op=MATCH_STATE_NOT_EQUAL; break;
        case LEGACY_PRED_BOND_PRESENT: op=MATCH_BOND_PRESENT; break;
        case LEGACY_PRED_BOND_FREE: op=MATCH_BOND_FREE; break;
        case LEGACY_PRED_BOND_TO: op=MATCH_BOND_TO; break;
        case LEGACY_PRED_POPULATION_AT_LEAST: op=MATCH_POPULATION_AT_LEAST; break;
        case LEGACY_PRED_COMPARTMENT: op=MATCH_COMPARTMENT; break;
        case LEGACY_PRED_COMPARTMENT_INSIDE: op=MATCH_COMPARTMENT_INSIDE; break;
        case LEGACY_PRED_CONNECTED_TO: op=MATCH_CONNECTED_TO; break;
        case LEGACY_PRED_SCAFFOLD_STATE: op=MATCH_SCAFFOLD_STATE; break;
        case LEGACY_PRED_SCAFFOLD_FREE: op=MATCH_SCAFFOLD_FREE; break;
        default: throw std::logic_error("unsupported legacy predicate reached lowerer");
    }
    MatchInstruction x(op); x.target=p.target; x.a=p.a; x.b=p.b; x.mask=p.mask; x.value=p.value; x.check_partner_component=p.has_partner_component; x.negate=p.negate; return x;
}

TransformInstruction lowerTransform(const LegacyTransformIR& t) {
    TransformOpcode op = TRANSFORM_END;
    switch (t.kind) {
        case LEGACY_TRANSFORM_SET_STATE_WORD: op=TRANSFORM_SET_STATE_WORD; break;
        case LEGACY_TRANSFORM_ADD_STATE_WORD: op=TRANSFORM_ADD_STATE_WORD; break;
        case LEGACY_TRANSFORM_SET_SCAFFOLD_STATE: op=TRANSFORM_SET_SCAFFOLD_STATE; break;
        case LEGACY_TRANSFORM_MOVE_OCCUPANT: op=TRANSFORM_MOVE_OCCUPANT; break;
        case LEGACY_TRANSFORM_POPULATION_ADD: op=TRANSFORM_POPULATION_ADD; break;
        case LEGACY_TRANSFORM_BIND: op=TRANSFORM_BIND; break;
        case LEGACY_TRANSFORM_UNBIND: op=TRANSFORM_UNBIND; break;
        case LEGACY_TRANSFORM_CREATE_MOLECULE: op=TRANSFORM_CREATE_MOLECULE; break;
        case LEGACY_TRANSFORM_DELETE_MOLECULE: op=TRANSFORM_DELETE_MOLECULE; break;
        case LEGACY_TRANSFORM_DELETE_SPECIES: op=TRANSFORM_DELETE_SPECIES; break;
        case LEGACY_TRANSFORM_MOVE_MOLECULE: op=TRANSFORM_MOVE_MOLECULE; break;
        case LEGACY_TRANSFORM_MOVE_SPECIES: op=TRANSFORM_MOVE_SPECIES; break;
        case LEGACY_TRANSFORM_DELETE_MOLECULE_CONDITIONAL: op=TRANSFORM_DELETE_MOLECULE_CONDITIONAL; break;
        default: throw std::logic_error("unsupported legacy transform reached lowerer");
    }
    TransformInstruction x(op); x.target=t.target; x.other=t.other; x.a=t.a; x.b=t.b; x.feature=t.changed_feature;
    // Existing bytecode stores both unsigned state values and signed population
    // deltas in the 64-bit payload; preserve the bit pattern here.
    x.value=static_cast<std::uint64_t>(t.value);
    if (t.kind == LEGACY_TRANSFORM_SET_STATE_WORD || t.kind == LEGACY_TRANSFORM_ADD_STATE_WORD || t.kind == LEGACY_TRANSFORM_SET_SCAFFOLD_STATE)
        x.b=t.changed_feature.value();
    else if (t.kind == LEGACY_TRANSFORM_MOVE_OCCUPANT)
        x.value=t.changed_feature.value();
    else if (t.kind == LEGACY_TRANSFORM_POPULATION_ADD)
        x.b=t.changed_feature.value();
    return x;
}

}

std::string LegacyLowerer::matcherSignature(const LegacyRuleIR& r) {
    std::ostringstream os;
    for (std::size_t i=0;i<r.predicates.size();++i) {
        const LegacyPredicateIR& p=r.predicates[i];
        os << static_cast<int>(p.kind) << ':' << p.target << ':' << p.owner << ':' << p.a << ':' << p.b << ':'
           << p.mask << ':' << p.value << ':' << p.has_partner_component << ':' << p.negate << ':'
           << p.partner_feature.value() << ';';
    }
    for (const auto& graph : r.graph_patterns) {
        os << "graph:" << graph.nodes.size() << ':' << graph.edges.size() << ':' << graph.connected_to.size() << ';';
        for (const auto& node : graph.nodes) {
            os << node.molecule_type << ':' << node.anchor_reactant << ':' << node.state_component << ':'
               << node.compartment << ':' << node.state_value << ':'
               << node.min_bound_components << ':' << node.max_bound_components << ':';
            os << "states:";
            for (const auto& state : node.state_constraints)
                os << state.first << '=' << state.second << ',';
            os << "excluded:";
            for (const auto& state : node.excluded_states)
                os << state.first << '!' << state.second << ',';
            for (const auto component : node.free_components) os << 'f' << component << ',';
            os << ':';
            for (const auto component : node.bound_components) os << 'b' << component << ',';
            for (const auto& symmetric : node.symmetric_constraints) {
                os << ":s" << symmetric.state_value << ':' << symmetric.bond_state << ':'
                   << symmetric.partner_node << ':' << symmetric.partner_symmetric << ':';
                for (const auto component : symmetric.components) os << component << ',';
                os << '/';
                for (const auto component : symmetric.partner_components) os << component << ',';
            }
            os << ';';
        }
        for (const auto& edge : graph.edges)
            os << edge.first_node << ':' << edge.first_component << ':' << edge.second_node << ':' << edge.second_component << ':' << edge.negate << ';';
        for (const auto& connected : graph.connected_to)
            os << "connected:" << connected.first_node << ':' << connected.second_node << ':' << connected.negate << ';';
    }
    return os.str();
}

std::string LegacyLowerer::transformSignature(const LegacyRuleIR& r) {
    std::ostringstream os;
    for (std::size_t i=0;i<r.transforms.size();++i) {
        const LegacyTransformIR& t=r.transforms[i];
        os << static_cast<int>(t.kind) << ':' << t.target << ':' << t.other << ':' << t.a << ':' << t.b << ':'
           << t.value << ':' << t.changed_feature.value() << ';';
    }
    os << "rate:" << static_cast<int>(r.rate_law.kind) << ':' << r.rate_law.target << ':'
       << r.rate_law.partner_target << ':' << r.rate_law.component << ':'
       << r.rate_law.partner_component << ':' << r.rate_law.offset << ':'
       << r.rate_law.slope << ':' << r.rate_law.weight << ':' << r.rate_law.expression << ':';
    for (const auto component : r.rate_law.expression_components) os << component << ',';
    os << ':';
    for (const auto& binding : r.rate_law.expression_bindings)
        os << static_cast<int>(binding.kind) << ':' << binding.name << ':' << binding.target << ':'
           << binding.component << ':' << binding.state_component << ':' << binding.state_value << ':'
           << binding.bond_component << ':' << binding.bond_state << ':'
           << binding.molecule_type << ':' << binding.scope << ':'
           << binding.partner_molecule_type << ':' << binding.partner_component << ':'
           << binding.partner_state_component << ':' << binding.partner_state_value << ':'
           << binding.compartment << ':' << binding.compartment_ancestry << ':'
           << binding.destination_compartment << ':' << binding.value << ';';
    os << "functions:";
    for (const auto& function : r.rate_law.expression_functions) {
        os << function.name << ':' << function.expression << ':';
        for (const auto& argument : function.arguments) os << argument << ',';
        os << "x:";
        for (const auto value : function.table_x) os << value << ',';
        os << "y:";
        for (const auto value : function.table_y) os << value << ',';
        os << ':' << function.table_method << ':' << function.table_counter;
        os << ';';
    }
    os << ';';
    return os.str();
}

LegacyLoweringResult LegacyLowerer::lower(const LegacyModelIR& legacy) {
    LegacyLoweringResult out;
    CompiledModel& metadata=out.executable.buildMetadata();
    for (std::size_t i=0;i<legacy.molecule_types.size();++i) metadata.addMoleculeType(legacy.molecule_types[i]);
    for (const auto& compartment : legacy.compartments) metadata.addCompartment(compartment);
    for (std::size_t i=0;i<legacy.features.size();++i) metadata.addFeature(legacy.features[i]);

    std::vector<RuleInstanceIR> instances;
    std::vector<std::size_t> original_index;
    out.rules.resize(legacy.rules.size());

    // Deduplicate matcher/transform programs before family canonicalization.
    std::map<std::string,MatcherId> matcher_ids;
    std::map<std::string,TransformProgramId> transform_ids;

    for (std::size_t i=0;i<legacy.rules.size();++i) {
        const LegacyRuleIR& r=legacy.rules[i];
        const LoweringFallbackReason reason=unsupportedReason(r);
        out.rules[i].reason=reason;
        if (reason != LOWERING_SUPPORTED) { ++out.fallback_rule_count; continue; }

        const std::string ms=matcherSignature(r), ts=transformSignature(r);
        MatcherId mid;
        std::map<std::string,MatcherId>::const_iterator mi=matcher_ids.find(ms);
        if (mi==matcher_ids.end()) {
            MatcherProgram p;
            for (std::size_t j=0;j<r.predicates.size();++j) p.add(lowerPredicate(r.predicates[j]));
            for (std::size_t j=0;j<r.graph_patterns.size();++j) {
                const std::uint32_t graphId=p.addGraphPattern(r.graph_patterns[j]);
                MatchInstruction graph(MATCH_GRAPH); graph.a=graphId; p.add(graph);
            }
            p.add(MatchInstruction(MATCH_END));
            mid=out.executable.buildMatchers().add(p); matcher_ids[ms]=mid;
        } else mid=mi->second;

        TransformProgramId tid;
        std::map<std::string,TransformProgramId>::const_iterator ti=transform_ids.find(ts);
        if (ti==transform_ids.end()) {
            TransformProgram p;
            for (std::size_t j=0;j<r.transforms.size();++j) p.add(lowerTransform(r.transforms[j]));
            p.add(TransformInstruction(TRANSFORM_END));
            tid=out.executable.buildTransforms().add(p); transform_ids[ts]=tid;
        } else tid=ti->second;

        RuleInstanceIR x; x.name=r.name; x.matcher_signature=ms; x.transform_signature=ts;
        x.matcher=mid; x.transform=tid; x.rate=r.rate; x.rate_law=r.rate_law; x.parameter_index=r.parameter_index; x.coordinate=r.coordinate;
        instances.push_back(x); original_index.push_back(i); ++out.supported_rule_count;
    }

    RuleFamilyCompilation families=RuleFamilyCompiler::compile(instances);
    for (std::size_t i=0;i<families.families.size();++i) metadata.addRuleFamily(families.families[i]);
    for (std::size_t i=0;i<instances.size();++i) {
        LoweredRuleInfo& info=out.rules[original_index[i]];
        info.family=families.instance_to_family[i]; info.member=families.instance_to_member[i];
    }

    // Build exact feature -> matcher invalidation edges from matcher reads.
    std::vector<std::vector<MatcherId> > deps(metadata.features().size());
    // Conservative but safe: a changed feature invalidates every matcher that
    // explicitly reads that same feature descriptor class/owner/index.
    for (std::size_t fi=0;fi<legacy.features.size();++fi) {
        const FeatureDescriptor& fd=legacy.features[fi];
        for (std::size_t ri=0;ri<legacy.rules.size();++ri) {
            if (!out.rules[ri].supported()) continue;
            bool reads=false;
            for (std::size_t pi=0;pi<legacy.rules[ri].predicates.size();++pi) {
                const LegacyPredicateIR& p=legacy.rules[ri].predicates[pi];
                if (fd.kind==FEATURE_MOLECULE_STATE && (p.kind==LEGACY_PRED_STATE_MASK || p.kind==LEGACY_PRED_STATE_NOT_EQUAL) && fd.index==p.a && (p.owner==std::numeric_limits<std::uint32_t>::max() || fd.owner==p.owner)) reads=true;
                else if (fd.kind==FEATURE_MOLECULE_BOND && (p.kind==LEGACY_PRED_BOND_PRESENT || p.kind==LEGACY_PRED_BOND_FREE || p.kind==LEGACY_PRED_BOND_TO) && fd.index==p.a && (p.owner==std::numeric_limits<std::uint32_t>::max() || fd.owner==p.owner)) reads=true;
                else if (fd.kind==FEATURE_MOLECULE_BOND && p.kind==LEGACY_PRED_CONNECTED_TO) reads=true;
                if (p.kind==LEGACY_PRED_BOND_TO && p.partner_feature.valid() && FeatureId(static_cast<std::uint32_t>(fi))==p.partner_feature) reads=true;
                else if (fd.kind==FEATURE_POPULATION && p.kind==LEGACY_PRED_POPULATION_AT_LEAST && fd.owner==p.a) reads=true;
                else if (fd.kind==FEATURE_MOLECULE_COMPARTMENT && p.kind==LEGACY_PRED_COMPARTMENT && fd.owner==p.a) reads=true;
                else if (fd.kind==FEATURE_MOLECULE_EXISTENCE && p.kind==LEGACY_PRED_TYPE_EXISTS && fd.owner==p.a) reads=true;
                else if (fd.kind==FEATURE_SCAFFOLD_OCCUPANCY && p.kind==LEGACY_PRED_SCAFFOLD_FREE) reads=true;
                else if (fd.kind==FEATURE_SCAFFOLD_OCCUPANCY && p.kind==LEGACY_PRED_SCAFFOLD_STATE) reads=true;
            }
            if (!legacy.rules[ri].graph_patterns.empty()) {
                // Graph predicates read existence, bond topology, states, and
                // compartments across every participating molecule.  Keep the
                // invalidation conservative: a changed member can alter an
                // automorphism or a transitive connectedTo result.
                if (fd.kind == FEATURE_MOLECULE_EXISTENCE ||
                    fd.kind == FEATURE_MOLECULE_BOND ||
                    fd.kind == FEATURE_MOLECULE_STATE ||
                    fd.kind == FEATURE_MOLECULE_COMPARTMENT)
                    reads = true;
            }
            const RateLawDescriptor& law=legacy.rules[ri].rate_law;
            if (fd.kind==FEATURE_MOLECULE_STATE &&
                ((law.kind==LEGACY_RATE_LOCAL_LINEAR && fd.index==law.component) ||
                 (law.kind==LEGACY_RATE_DOR_PRODUCT &&
                  (fd.index==law.component || fd.index==law.partner_component)))) reads=true;
            if (law.kind == LEGACY_RATE_EXPRESSION) {
                if (fd.kind == FEATURE_TIME)
                    reads = true;
                for (const auto& binding : law.expression_bindings) {
                    if (binding.kind == RATE_EXPRESSION_COMPLEX_MOLECULE_COUNT) {
                        const bool rootOwner = fd.owner == binding.molecule_type;
                        const bool partnerOwner = fd.owner == binding.partner_molecule_type;
                        if (!rootOwner && !partnerOwner) continue;
                        if (fd.kind == FEATURE_MOLECULE_EXISTENCE)
                            reads = true;
                        if (fd.kind == FEATURE_MOLECULE_BOND &&
                            ((rootOwner && fd.index == binding.component) ||
                             (partnerOwner && fd.index == binding.partner_component)))
                            reads = true;
                        if (fd.kind == FEATURE_MOLECULE_STATE &&
                            ((rootOwner && binding.state_component != std::numeric_limits<std::uint32_t>::max() &&
                              fd.index == binding.state_component) ||
                             (partnerOwner && binding.partner_state_component != std::numeric_limits<std::uint32_t>::max() &&
                              fd.index == binding.partner_state_component)))
                            reads = true;
                        if (fd.kind == FEATURE_MOLECULE_COMPARTMENT &&
                            binding.compartment != std::numeric_limits<std::uint32_t>::max())
                            reads = true;
                        continue;
                    }
                    const bool scopedCount =
                        binding.kind == RATE_EXPRESSION_GLOBAL_MOLECULE_COUNT ||
                        binding.kind == RATE_EXPRESSION_SPECIES_MOLECULE_COUNT;
                    if (scopedCount &&
                        binding.molecule_type != std::numeric_limits<std::uint32_t>::max() &&
                        fd.owner != binding.molecule_type)
                        continue;
                    if (scopedCount &&
                        binding.molecule_type == std::numeric_limits<std::uint32_t>::max() &&
                        fd.kind != FEATURE_MOLECULE_EXISTENCE)
                        continue;
                    if (scopedCount) {
                        // Every counted molecule type contributes existence;
                        // state/bond/compartment filters add the corresponding
                        // narrower invalidation edge.
                        if (fd.kind == FEATURE_MOLECULE_EXISTENCE)
                            reads = true;
                        if (binding.state_component != std::numeric_limits<std::uint32_t>::max() &&
                            fd.kind == FEATURE_MOLECULE_STATE &&
                            fd.index == binding.state_component)
                            reads = true;
                        if (binding.bond_component != std::numeric_limits<std::uint32_t>::max() &&
                            fd.kind == FEATURE_MOLECULE_BOND &&
                            fd.index == binding.bond_component)
                            reads = true;
                        if (binding.compartment != std::numeric_limits<std::uint32_t>::max() &&
                            fd.kind == FEATURE_MOLECULE_COMPARTMENT)
                            reads = true;
                    } else if (binding.kind == RATE_EXPRESSION_COMPARTMENT_VOLUME ||
                               binding.kind == RATE_EXPRESSION_TRANSPORT_VOLUME_RATIO) {
                        if (fd.kind == FEATURE_MOLECULE_COMPARTMENT)
                            reads = true;
                    }
                }
            }
            if (reads) deps[fi].push_back(metadata.ruleFamilies().at(out.rules[ri].family.value()).matcher);
        }
    }
    for (std::size_t fi=0; fi<deps.size(); ++fi) {
        std::sort(deps[fi].begin(),deps[fi].end());
        deps[fi].erase(std::unique(deps[fi].begin(),deps[fi].end()),deps[fi].end());
    }
    metadata.setFeatureDependencies(deps);
    return out;
}

} // namespace NFcore2
