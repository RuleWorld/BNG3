#include "nfnext/compiler.hpp"
#include "nfnext/family_compiler.hpp"

#include <algorithm>

namespace nfnext {

void ModelCompiler::buildDependencies(ModelIR& model) {
    model.dependencies.feature_to_families.clear();
    for (const auto& f : model.rule_families) {
        for (const auto& p : f.predicates) {
            auto& ids = model.dependencies.feature_to_families[encodeFeature(p.molecule_type, p.site, p.kind, p.value)];
            if (std::find(ids.begin(), ids.end(), f.id) == ids.end()) ids.push_back(f.id);
        }
    }
}

bool ModelCompiler::latticeCompatible(const ModelIR& model) noexcept {
    if (model.lattice_length == 0 || model.rule_families.empty()) return false;
    bool has_move = false;
    for (const auto& f : model.rule_families) {
        for (const auto& a : f.actions) {
            switch (a.kind) {
                case ActionKind::MovePosition: has_move = true; break;
                case ActionKind::SetSiteState:
                case ActionKind::Create:
                case ActionKind::Destroy:
                    break;
                default:
                    return false;
            }
        }
        for (const auto& p : f.predicates) {
            switch (p.kind) {
                case PredicateKind::PositionEq:
                case PredicateKind::PositionRange:
                case PredicateKind::NeighborFree:
                case PredicateKind::NeighborOccupied:
                case PredicateKind::SiteStateEq:
                    break;
                default:
                    return false;
            }
        }
    }
    return has_move;
}

CompileReport ModelCompiler::compile(ModelIR& model, const CompileOptions& options) const {
    CompileReport report;
    if (options.collapse_indexed_rules) {
        auto result = compileRuleFamilies(model.expanded_rules);
        model.rule_families = std::move(result.families);
        report.family_stats = result.stats;
    } else {
        model.rule_families.clear();
        FamilyId id = 0;
        for (const auto& r : model.expanded_rules) {
            RuleFamilyIR f; f.id = id++; f.name = r.name; f.default_rate = r.rate;
            f.rate_law = r.rate_law;
            f.predicates = r.predicates; f.actions = r.actions;
            f.pattern = r.pattern; f.source_rules.push_back(r.id);
            model.rule_families.push_back(std::move(f));
        }
        report.family_stats = {model.expanded_rules.size(), model.rule_families.size(), 0, model.rule_families.size()};
    }
    if (options.build_dependency_index) buildDependencies(model);
    report.dependency_features = model.dependencies.feature_to_families.size();
    model.preferred_backend = options.prefer_lattice_when_compatible && latticeCompatible(model)
        ? BackendKind::Lattice : BackendKind::Generic;
    report.selected_backend = model.preferred_backend;
    return report;
}

} // namespace nfnext
