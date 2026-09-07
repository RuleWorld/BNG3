#include "legacy_bridge.hh"
#include <map>
#include <sstream>
#include <stdexcept>
#include <algorithm>
#include <cmath>

namespace NFcore2 {

double RateLawDescriptor::evaluate(const SimulationState& state,
                                   const MatchContext& context,
                                   double base_rate) const {
    if (kind == LEGACY_RATE_CONSTANT) return base_rate;
    const MoleculeRef left = context.moleculeAt(target);
    if (!left.valid()) throw std::out_of_range("rate-law target missing");
    const double left_value = static_cast<double>(
        state.molecules(left.type).stateWord(left.handle, static_cast<std::uint16_t>(component)));
    double result = base_rate;
    if (kind == LEGACY_RATE_LOCAL_LINEAR)
        result = base_rate * (offset + slope * left_value);
    if (kind == LEGACY_RATE_DOR_PRODUCT) {
        const MoleculeRef right = context.moleculeAt(partner_target);
        if (!right.valid()) throw std::out_of_range("DOR partner target missing");
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
    if (r.uses_local_function) return LOWERING_LOCAL_FUNCTION;
    if (r.uses_connected_to) return LOWERING_CONNECTED_TO;
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
        case LEGACY_PRED_CONNECTED_TO: op=MATCH_CONNECTED_TO; break;
        case LEGACY_PRED_SCAFFOLD_STATE: op=MATCH_SCAFFOLD_STATE; break;
        case LEGACY_PRED_SCAFFOLD_FREE: op=MATCH_SCAFFOLD_FREE; break;
        default: throw std::logic_error("unsupported legacy predicate reached lowerer");
    }
    MatchInstruction x(op); x.target=p.target; x.a=p.a; x.b=p.b; x.mask=p.mask; x.value=p.value; x.check_partner_component=p.has_partner_component; return x;
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
        os << static_cast<int>(p.kind) << ':' << p.target << ':' << p.a << ':' << p.b << ':'
           << p.mask << ':' << p.value << ':' << p.has_partner_component << ';';
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
       << r.rate_law.slope << ':' << r.rate_law.weight << ';';
    return os.str();
}

LegacyLoweringResult LegacyLowerer::lower(const LegacyModelIR& legacy) {
    LegacyLoweringResult out;
    CompiledModel& metadata=out.executable.buildMetadata();
    for (std::size_t i=0;i<legacy.molecule_types.size();++i) metadata.addMoleculeType(legacy.molecule_types[i]);
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
                if (fd.kind==FEATURE_MOLECULE_STATE && (p.kind==LEGACY_PRED_STATE_MASK || p.kind==LEGACY_PRED_STATE_NOT_EQUAL) && fd.index==p.a) reads=true;
                else if (fd.kind==FEATURE_MOLECULE_BOND && (p.kind==LEGACY_PRED_BOND_PRESENT || p.kind==LEGACY_PRED_BOND_FREE || p.kind==LEGACY_PRED_BOND_TO) && fd.index==p.a) reads=true;
                else if (fd.kind==FEATURE_MOLECULE_BOND && p.kind==LEGACY_PRED_CONNECTED_TO) reads=true;
                if (p.kind==LEGACY_PRED_BOND_TO && p.partner_feature.valid() && FeatureId(static_cast<std::uint32_t>(fi))==p.partner_feature) reads=true;
                else if (fd.kind==FEATURE_POPULATION && p.kind==LEGACY_PRED_POPULATION_AT_LEAST && fd.owner==p.a) reads=true;
                else if (fd.kind==FEATURE_MOLECULE_COMPARTMENT && p.kind==LEGACY_PRED_COMPARTMENT && fd.owner==p.target) reads=true;
                else if (fd.kind==FEATURE_MOLECULE_EXISTENCE && p.kind==LEGACY_PRED_TYPE_EXISTS && fd.owner==p.a) reads=true;
                else if (fd.kind==FEATURE_SCAFFOLD_OCCUPANCY && p.kind==LEGACY_PRED_SCAFFOLD_FREE) reads=true;
                else if (fd.kind==FEATURE_SCAFFOLD_OCCUPANCY && p.kind==LEGACY_PRED_SCAFFOLD_STATE) reads=true;
            }
            const RateLawDescriptor& law=legacy.rules[ri].rate_law;
            if (fd.kind==FEATURE_MOLECULE_STATE &&
                ((law.kind==LEGACY_RATE_LOCAL_LINEAR && fd.index==law.component) ||
                 (law.kind==LEGACY_RATE_DOR_PRODUCT &&
                  (fd.index==law.component || fd.index==law.partner_component)))) reads=true;
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
