#pragma once
#include <cstdint>
#include <limits>

namespace NFcore2 {

template <typename Tag>
class Id {
public:
    typedef std::uint32_t value_type;
    Id() : value_(invalid_value()) {}
    explicit Id(value_type value) : value_(value) {}
    value_type value() const { return value_; }
    bool valid() const { return value_ != invalid_value(); }
    static value_type invalid_value() { return std::numeric_limits<value_type>::max(); }
    friend bool operator==(Id a, Id b) { return a.value_ == b.value_; }
    friend bool operator!=(Id a, Id b) { return !(a == b); }
    friend bool operator<(Id a, Id b) { return a.value_ < b.value_; }
private:
    value_type value_;
};

struct MoleculeTag {}; struct MoleculeTypeTag {}; struct MatcherTag {};
struct RuleFamilyTag {}; struct ScaffoldTag {}; struct PopulationTag {};
struct FeatureTag {}; struct TransformProgramTag {};

typedef Id<MoleculeTag> MoleculeId;
typedef Id<MoleculeTypeTag> MoleculeTypeId;
typedef Id<MatcherTag> MatcherId;
typedef Id<RuleFamilyTag> RuleFamilyId;
typedef Id<ScaffoldTag> ScaffoldId;
typedef Id<PopulationTag> PopulationId;
typedef Id<FeatureTag> FeatureId;
typedef Id<TransformProgramTag> TransformProgramId;

struct MoleculeHandle {
    std::uint32_t slot;
    std::uint32_t generation;
    MoleculeHandle() : slot(Id<MoleculeTag>::invalid_value()), generation(0) {}
    MoleculeHandle(std::uint32_t s, std::uint32_t g) : slot(s), generation(g) {}
    bool valid() const { return slot != Id<MoleculeTag>::invalid_value(); }
    friend bool operator==(const MoleculeHandle& a, const MoleculeHandle& b) {
        return a.slot == b.slot && a.generation == b.generation;
    }
};


struct MoleculeRef {
    MoleculeTypeId type;
    MoleculeHandle handle;
    MoleculeRef() : type(), handle() {}
    MoleculeRef(MoleculeTypeId t, MoleculeHandle h) : type(t), handle(h) {}
    bool valid() const { return type.valid() && handle.valid(); }
    friend bool operator==(const MoleculeRef& a, const MoleculeRef& b) {
        return a.type == b.type && a.handle == b.handle;
    }
};

} // namespace NFcore2
