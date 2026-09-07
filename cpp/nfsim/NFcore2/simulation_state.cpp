#include "simulation_state.hh"
#include <limits>
#include <cmath>

namespace NFcore2 {

MoleculeStore::MoleculeStore(const MoleculeTypeDescriptor& d)
    : state_words_(d.state_words), bond_slots_(d.bond_slots), live_count_(0) {}

MoleculeHandle MoleculeStore::create() {
    std::uint32_t slot;
    if (!free_.empty()) { slot = free_.back(); free_.pop_back(); alive_[slot] = 1; }
    else {
        slot = static_cast<std::uint32_t>(generation_.size());
        generation_.push_back(1); alive_.push_back(1);
        states_.resize((slot + 1) * state_words_, 0);
        bonds_.resize((slot + 1) * bond_slots_);
        compartments_.resize(slot + 1, 0);
    }
    for (std::uint16_t i=0;i<state_words_;++i) states_[slot*state_words_+i]=0;
    for (std::uint16_t i=0;i<bond_slots_;++i) bonds_[slot*bond_slots_+i]=MoleculeRef();
    compartments_[slot] = 0;
    ++live_count_;
    return MoleculeHandle(slot, generation_[slot]);
}

bool MoleculeStore::erase(MoleculeHandle h) {
    if (!alive(h)) return false;
    alive_[h.slot] = 0;
    ++generation_[h.slot]; if (generation_[h.slot] == 0) ++generation_[h.slot];
    free_.push_back(h.slot); --live_count_; return true;
}
bool MoleculeStore::alive(MoleculeHandle h) const {
    return h.slot < alive_.size() && alive_[h.slot] && generation_[h.slot] == h.generation;
}
std::uint32_t MoleculeStore::compartment(MoleculeHandle h) const {
    requireAlive(h);
    return compartments_.at(h.slot);
}
void MoleculeStore::setCompartment(MoleculeHandle h, std::uint32_t compartment) {
    requireAlive(h);
    compartments_.at(h.slot) = compartment;
}
void MoleculeStore::requireAlive(MoleculeHandle h) const { if (!alive(h)) throw std::out_of_range("stale molecule handle"); }
std::uint64_t MoleculeStore::stateWord(MoleculeHandle h, std::uint16_t w) const {
    requireAlive(h); if (w>=state_words_) throw std::out_of_range("state word"); return states_[h.slot*state_words_+w];
}
void MoleculeStore::setStateWord(MoleculeHandle h, std::uint16_t w, std::uint64_t v) {
    requireAlive(h); if (w>=state_words_) throw std::out_of_range("state word"); states_[h.slot*state_words_+w]=v;
}
MoleculeHandle MoleculeStore::bond(MoleculeHandle h, std::uint16_t s) const {
    requireAlive(h); if (s>=bond_slots_) throw std::out_of_range("bond slot"); return bonds_[h.slot*bond_slots_+s].handle;
}
MoleculeRef MoleculeStore::bondRef(MoleculeHandle h, std::uint16_t s) const {
    requireAlive(h); if (s>=bond_slots_) throw std::out_of_range("bond slot"); return bonds_[h.slot*bond_slots_+s];
}
void MoleculeStore::setBond(MoleculeHandle h, std::uint16_t s, MoleculeHandle other) {
    requireAlive(h); if (s>=bond_slots_) throw std::out_of_range("bond slot"); bonds_[h.slot*bond_slots_+s]=MoleculeRef(MoleculeTypeId(),other);
}
void MoleculeStore::setBondRef(MoleculeHandle h, std::uint16_t s, MoleculeRef other) {
    requireAlive(h); if (s>=bond_slots_) throw std::out_of_range("bond slot"); bonds_[h.slot*bond_slots_+s]=other;
}

PopulationId PopulationStore::add(std::int64_t initial) {
    if (initial < 0) throw std::invalid_argument("population count cannot be negative");
    counts_.push_back(initial);
    return PopulationId(static_cast<std::uint32_t>(counts_.size()-1));
}
std::int64_t PopulationStore::value(PopulationId id) const { return counts_.at(id.value()); }
void PopulationStore::addTo(PopulationId id, std::int64_t d) {
    std::int64_t& v=counts_.at(id.value());
    if (d < 0 && d < -v) throw std::underflow_error("population count below zero");
    if (d > 0 && v > std::numeric_limits<std::int64_t>::max() - d)
        throw std::overflow_error("population count overflow");
    v += d;
}

void SimulationState::setTime(double value) {
    if (!std::isfinite(value) || value < 0.0)
        throw std::invalid_argument("simulation time must be finite and nonnegative");
    time_ = value;
}

bool SimulationState::eraseMolecule(MoleculeRef ref) {
    if (!ref.valid() || !molecules(ref.type).alive(ref.handle)) return false;
    MoleculeStore& source=molecules(ref.type);
    for (std::uint16_t slot=0; slot<source.bondSlotCount(); ++slot) {
        MoleculeRef partner=source.bondRef(ref.handle,slot);
        if (!partner.valid() || !molecules(partner.type).alive(partner.handle)) continue;
        MoleculeStore& target=molecules(partner.type);
        for (std::uint16_t other=0; other<target.bondSlotCount(); ++other) {
            if (target.bondRef(partner.handle,other)==ref)
                target.setBondRef(partner.handle,other,MoleculeRef());
        }
    }
    return source.erase(ref.handle);
}

std::vector<MoleculeRef> SimulationState::eraseSpecies(MoleculeRef ref) {
    std::vector<MoleculeRef> component;
    if (!ref.valid() || !molecules(ref.type).alive(ref.handle)) return component;
    component.push_back(ref);
    for (std::size_t i = 0; i < component.size(); ++i) {
        const MoleculeRef current = component[i];
        const MoleculeStore& store = molecules(current.type);
        for (std::uint16_t slot = 0; slot < store.bondSlotCount(); ++slot) {
            const MoleculeRef partner = store.bondRef(current.handle, slot);
            if (!partner.valid() || !molecules(partner.type).alive(partner.handle)) continue;
            bool seen = false;
            for (std::size_t j = 0; j < component.size(); ++j)
                if (component[j] == partner) { seen = true; break; }
            if (!seen) component.push_back(partner);
        }
    }
    for (std::size_t i = 0; i < component.size(); ++i) eraseMolecule(component[i]);
    return component;
}

SimulationState::SimulationState(const CompiledModel& model) : model_(model), time_(0.0) {
    const std::vector<MoleculeTypeDescriptor>& types=model.moleculeTypes();
    molecule_stores_.reserve(types.size());
    for (std::size_t i=0;i<types.size();++i) {
        molecule_stores_.push_back(MoleculeStore(types[i]));
        if (types[i].population) populations_.add(0);
    }
}

} // namespace NFcore2
