#pragma once
#include "ids.hh"
#include <cstdint>
#include <string>
#include <vector>

namespace NFcore2 {

enum FeatureKind {
    FEATURE_MOLECULE_STATE,
    FEATURE_MOLECULE_BOND,
    FEATURE_SCAFFOLD_OCCUPANCY,
    FEATURE_POPULATION,
    FEATURE_TIME
};

struct FeatureDescriptor {
    FeatureKind kind;
    std::uint32_t owner;
    std::uint32_t index;
    FeatureDescriptor() : kind(FEATURE_MOLECULE_STATE), owner(0), index(0) {}
    FeatureDescriptor(FeatureKind k, std::uint32_t o, std::uint32_t i)
        : kind(k), owner(o), index(i) {}
};

struct MoleculeTypeDescriptor {
    std::string name;
    std::uint16_t state_words;
    std::uint16_t bond_slots;
    MoleculeTypeDescriptor() : state_words(1), bond_slots(0) {}
};

struct RuleMember {
    double rate;
    std::uint32_t parameter_index;
    std::uint32_t coordinate;
    RuleMember() : rate(0.0), parameter_index(0), coordinate(0) {}
};

struct RuleFamilyDescriptor {
    std::string name;
    MatcherId matcher;
    TransformProgramId transform;
    std::vector<RuleMember> members;
    bool uniform_rate;
    RuleFamilyDescriptor() : uniform_rate(false) {}
};

struct DependencyIndex {
    std::vector<std::uint32_t> offsets;
    std::vector<MatcherId> matchers;
    void build(std::size_t feature_count,
               const std::vector<std::vector<MatcherId> >& adjacency);
    std::pair<const MatcherId*, const MatcherId*> dependents(FeatureId feature) const;
};

class CompiledModel {
public:
    MoleculeTypeId addMoleculeType(const MoleculeTypeDescriptor& descriptor);
    FeatureId addFeature(const FeatureDescriptor& descriptor);
    RuleFamilyId addRuleFamily(const RuleFamilyDescriptor& descriptor);
    void setFeatureDependencies(const std::vector<std::vector<MatcherId> >& adjacency);

    const std::vector<MoleculeTypeDescriptor>& moleculeTypes() const { return molecule_types_; }
    const std::vector<FeatureDescriptor>& features() const { return features_; }
    const std::vector<RuleFamilyDescriptor>& ruleFamilies() const { return rule_families_; }
    const DependencyIndex& dependencies() const { return dependencies_; }
    const std::vector<RuleFamilyId>& familiesForMatcher(MatcherId matcher) const;

private:
    std::vector<MoleculeTypeDescriptor> molecule_types_;
    std::vector<FeatureDescriptor> features_;
    std::vector<RuleFamilyDescriptor> rule_families_;
    DependencyIndex dependencies_;
    std::vector<std::vector<RuleFamilyId> > matcher_families_;
};

} // namespace NFcore2
