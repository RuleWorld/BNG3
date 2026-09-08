#include "compiled_model.hh"
#include <stdexcept>
#include <cmath>

namespace NFcore2 {

void DependencyIndex::build(std::size_t feature_count,
                            const std::vector<std::vector<MatcherId> >& adjacency) {
    if (adjacency.size() != feature_count) {
        throw std::invalid_argument("dependency adjacency size must match feature count");
    }
    offsets.assign(feature_count + 1, 0);
    std::size_t total = 0;
    for (std::size_t i = 0; i < adjacency.size(); ++i) {
        total += adjacency[i].size();
        offsets[i + 1] = static_cast<std::uint32_t>(total);
    }
    matchers.clear(); matchers.reserve(total);
    for (std::size_t i = 0; i < adjacency.size(); ++i)
        matchers.insert(matchers.end(), adjacency[i].begin(), adjacency[i].end());
}

std::pair<const MatcherId*, const MatcherId*> DependencyIndex::dependents(FeatureId feature) const {
    const std::uint32_t f = feature.value();
    if (f + 1 >= offsets.size()) return std::make_pair((const MatcherId*)0, (const MatcherId*)0);
    const MatcherId* base = matchers.empty() ? (const MatcherId*)0 : &matchers[0];
    if (!base) return std::make_pair(base, base);
    return std::make_pair(base + offsets[f], base + offsets[f + 1]);
}

MoleculeTypeId CompiledModel::addMoleculeType(const MoleculeTypeDescriptor& d) {
    molecule_types_.push_back(d);
    return MoleculeTypeId(static_cast<std::uint32_t>(molecule_types_.size() - 1));
}
void CompiledModel::addCompartment(const CompartmentDescriptor& d) {
    if (!std::isfinite(d.size) || d.size < 0.0)
        throw std::invalid_argument("compartment size must be finite and nonnegative");
    for (std::size_t i = 0; i < compartments_.size(); ++i)
        if (compartments_[i].id == d.id)
            throw std::invalid_argument("duplicate compartment id");
    compartments_.push_back(d);
}
bool CompiledModel::hasCompartment(std::uint32_t id) const {
    for (const auto& compartment : compartments_)
        if (compartment.id == id) return true;
    return false;
}
bool CompiledModel::compartmentInside(std::uint32_t child, std::uint32_t ancestor) const {
    if (!hasCompartment(child) || !hasCompartment(ancestor)) return false;
    if (child == ancestor) return true;
    std::uint32_t current = child;
    for (std::size_t depth = 0; depth <= compartments_.size(); ++depth) {
        std::uint32_t parent = std::numeric_limits<std::uint32_t>::max();
        bool found = false;
        for (std::size_t i = 0; i < compartments_.size(); ++i) {
            if (compartments_[i].id == current) { parent = compartments_[i].parent; found = true; break; }
        }
        if (!found || parent == std::numeric_limits<std::uint32_t>::max()) return false;
        if (parent == ancestor) return true;
        current = parent;
    }
    throw std::logic_error("compartment hierarchy contains a cycle");
}
FeatureId CompiledModel::addFeature(const FeatureDescriptor& d) {
    features_.push_back(d);
    return FeatureId(static_cast<std::uint32_t>(features_.size() - 1));
}
RuleFamilyId CompiledModel::addRuleFamily(const RuleFamilyDescriptor& d) {
    if (!d.matcher.valid()) throw std::invalid_argument("rule family matcher id is invalid");
    if (!d.transform.valid()) throw std::invalid_argument("rule family transform id is invalid");
    for (std::size_t i=0;i<d.members.size();++i) {
        if (!std::isfinite(d.members[i].rate) || d.members[i].rate < 0.0)
            throw std::invalid_argument("rule family member rate must be finite and nonnegative");
    }
    rule_families_.push_back(d);
    RuleFamilyId id(static_cast<std::uint32_t>(rule_families_.size() - 1));
    if (d.matcher.valid()) {
        if (matcher_families_.size() <= d.matcher.value()) matcher_families_.resize(d.matcher.value()+1);
        matcher_families_[d.matcher.value()].push_back(id);
    }
    return id;
}
void CompiledModel::setFeatureDependencies(const std::vector<std::vector<MatcherId> >& a) {
    dependencies_.build(features_.size(), a);
}

const std::vector<RuleFamilyId>& CompiledModel::familiesForMatcher(MatcherId matcher) const {
    static const std::vector<RuleFamilyId> empty;
    if (!matcher.valid() || matcher.value() >= matcher_families_.size()) return empty;
    return matcher_families_[matcher.value()];
}

} // namespace NFcore2
