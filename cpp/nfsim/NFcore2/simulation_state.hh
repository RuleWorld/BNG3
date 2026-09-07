#pragma once
#include "compiled_model.hh"
#include <cstdint>
#include <vector>
#include <stdexcept>

namespace NFcore2 {

struct FeatureDelta {
    std::vector<FeatureId> changed;
    void clear() { changed.clear(); }
    void add(FeatureId id) { changed.push_back(id); }
};

class MoleculeStore {
public:
    explicit MoleculeStore(const MoleculeTypeDescriptor& descriptor);
    MoleculeHandle create();
    bool erase(MoleculeHandle handle);
    bool alive(MoleculeHandle handle) const;
    std::uint64_t stateWord(MoleculeHandle handle, std::uint16_t word) const;
    void setStateWord(MoleculeHandle handle, std::uint16_t word, std::uint64_t value);
    MoleculeHandle bond(MoleculeHandle handle, std::uint16_t slot) const;
    MoleculeRef bondRef(MoleculeHandle handle, std::uint16_t slot) const;
    void setBond(MoleculeHandle handle, std::uint16_t slot, MoleculeHandle other);
    void setBondRef(MoleculeHandle handle, std::uint16_t slot, MoleculeRef other);
    std::size_t liveCount() const { return live_count_; }
    std::uint16_t bondSlotCount() const { return bond_slots_; }
private:
    void requireAlive(MoleculeHandle handle) const;
    std::uint16_t state_words_;
    std::uint16_t bond_slots_;
    std::vector<std::uint32_t> generation_;
    std::vector<std::uint8_t> alive_;
    std::vector<std::uint32_t> free_;
    std::vector<std::uint64_t> states_;
    std::vector<MoleculeRef> bonds_;
    std::size_t live_count_;
};

class PopulationStore {
public:
    PopulationId add(std::int64_t initial = 0);
    std::int64_t value(PopulationId id) const;
    void addTo(PopulationId id, std::int64_t delta);
private:
    std::vector<std::int64_t> counts_;
};

class SimulationState {
public:
    explicit SimulationState(const CompiledModel& model);
    const CompiledModel& model() const { return model_; }
    MoleculeStore& molecules(MoleculeTypeId type) { return molecule_stores_.at(type.value()); }
    const MoleculeStore& molecules(MoleculeTypeId type) const { return molecule_stores_.at(type.value()); }
    PopulationStore& populations() { return populations_; }
    const PopulationStore& populations() const { return populations_; }
    double time() const { return time_; }
    void setTime(double value);
    bool eraseMolecule(MoleculeRef ref);
private:
    const CompiledModel& model_;
    std::vector<MoleculeStore> molecule_stores_;
    PopulationStore populations_;
    double time_;
};

} // namespace NFcore2
