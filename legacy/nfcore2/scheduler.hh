#pragma once
#include "compiled_model.hh"
#include <cstddef>
#include <cstdint>
#include <vector>
#include <stdexcept>

namespace NFcore2 {

class FenwickTree {
public:
    FenwickTree() {}
    explicit FenwickTree(std::size_t n) { reset(n); }
    void reset(std::size_t n);
    void set(std::size_t index, double value);
    double value(std::size_t index) const { return values_.at(index); }
    double total() const;
    double prefix(std::size_t count) const; // sum of [0,count)
    std::size_t sample(double target) const;
    std::size_t size() const { return values_.size(); }
private:
    std::vector<double> tree_, values_;
};

struct EventChoice { RuleFamilyId family; std::uint32_t member; };
class HierarchicalScheduler {
public:
    explicit HierarchicalScheduler(const CompiledModel& model);
    void setMemberActivity(RuleFamilyId family, std::uint32_t member, double activity);
    void setMemberMultiplicity(RuleFamilyId family, std::uint32_t member, double multiplicity);
    void setMemberMatched(RuleFamilyId family, std::uint32_t member, bool matched) { setMemberMultiplicity(family, member, matched ? 1.0 : 0.0); }
    double totalActivity() const { return family_tree_.total(); }
    EventChoice sample(double unit_interval) const;
private:
    const CompiledModel& model_;
    FenwickTree family_tree_;
    std::vector<FenwickTree> member_trees_;
};

} // namespace NFcore2
