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
        states_.resize((static_cast<std::size_t>(slot) + 1u) * static_cast<std::size_t>(state_words_), 0);
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
std::vector<MoleculeHandle> MoleculeStore::liveHandles() const {
    std::vector<MoleculeHandle> out;
    out.reserve(live_count_);
    for (std::uint32_t slot = 0; slot < generation_.size(); ++slot)
        if (alive_[slot]) out.push_back(MoleculeHandle(slot, generation_[slot]));
    return out;
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
    std::vector<MoleculeRef> component = connectedComponent(ref);
    for (std::size_t i = 0; i < component.size(); ++i) eraseMolecule(component[i]);
    return component;
}

std::vector<MoleculeRef> SimulationState::connectedComponent(MoleculeRef ref) const {
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
    return component;
}

double SimulationState::compartmentSize(std::uint32_t id) const {
    for (const auto& compartment : model_.compartments()) {
        if (compartment.id != id) continue;
        if (!std::isfinite(compartment.size) || compartment.size <= 0.0)
            throw std::domain_error("compartment volume must be finite and positive");
        return compartment.size;
    }
    throw std::out_of_range("compartment is unknown");
}

double SimulationState::transportVolumeRatio(std::uint32_t source,
                                             std::uint32_t destination) const {
    if (model_.compartments().empty()) return 1.0;
    const CompartmentDescriptor* sourceDescriptor = nullptr;
    const CompartmentDescriptor* destinationDescriptor = nullptr;
    for (const auto& compartment : model_.compartments()) {
        if (compartment.id == source) sourceDescriptor = &compartment;
        if (compartment.id == destination) destinationDescriptor = &compartment;
    }
    if (!sourceDescriptor || !destinationDescriptor)
        throw std::out_of_range("transport compartment is unknown");
    if (source == destination) {
        (void)compartmentSize(source);
        return 1.0;
    }
    if (sourceDescriptor->dimensions != destinationDescriptor->dimensions)
        throw std::invalid_argument("transport dimensions do not match");
    // A compartment hierarchy still transports through the concrete region
    // volumes; the model validates parent chains whenever an inside query is
    // required by a matcher or expression binding.
    const double sourceSize = compartmentSize(source);
    const double destinationSize = compartmentSize(destination);
    const double ratio = destinationSize / sourceSize;
    if (!std::isfinite(ratio) || ratio <= 0.0)
        throw std::domain_error("transport volume ratio is invalid");
    return ratio;
}

void SimulationState::moveMolecule(MoleculeRef ref, std::uint32_t destination) {
    if (!ref.valid() || !molecules(ref.type).alive(ref.handle))
        throw std::out_of_range("move target missing");
    if (!model_.compartments().empty()) {
        if (!model_.hasCompartment(destination))
            throw std::out_of_range("move destination compartment is unknown");
        const std::uint32_t source = molecules(ref.type).compartment(ref.handle);
        if (model_.hasCompartment(source)) {
            const CompartmentDescriptor* sourceDescriptor = nullptr;
            const CompartmentDescriptor* destinationDescriptor = nullptr;
            for (const auto& compartment : model_.compartments()) {
                if (compartment.id == source) sourceDescriptor = &compartment;
                if (compartment.id == destination) destinationDescriptor = &compartment;
            }
            if (sourceDescriptor && destinationDescriptor &&
                sourceDescriptor->dimensions != destinationDescriptor->dimensions)
                throw std::invalid_argument("move dimensions do not match");
        }
        (void)compartmentSize(destination);
    }
    molecules(ref.type).setCompartment(ref.handle, destination);
}

void SimulationState::moveSpecies(MoleculeRef ref, std::uint32_t destination) {
    if (!ref.valid() || !molecules(ref.type).alive(ref.handle))
        throw std::out_of_range("move target missing");
    // Models without an explicit compartment table retain the historical
    // scalar-id behavior. Once a hierarchy is present, reject unknown
    // destinations before mutating any member so the move is atomic.
    if (!model_.compartments().empty() && !model_.hasCompartment(destination))
        throw std::out_of_range("move destination compartment is unknown");
    if (!model_.compartments().empty()) (void)compartmentSize(destination);
    const std::vector<MoleculeRef> members = connectedComponent(ref);
    for (const auto& member : members)
        if (!member.valid() || !molecules(member.type).alive(member.handle))
            throw std::logic_error("species contains a stale molecule");
    if (!model_.compartments().empty()) {
        const CompartmentDescriptor* destinationDescriptor = nullptr;
        for (const auto& compartment : model_.compartments())
            if (compartment.id == destination) { destinationDescriptor = &compartment; break; }
        if (!destinationDescriptor) throw std::out_of_range("move destination compartment is unknown");
        for (const auto& member : members) {
            const std::uint32_t source = molecules(member.type).compartment(member.handle);
            for (const auto& compartment : model_.compartments()) {
                if (compartment.id == source &&
                    compartment.dimensions != destinationDescriptor->dimensions)
                    throw std::invalid_argument("species move dimensions do not match");
            }
        }
    }
    for (const auto& member : members)
        molecules(member.type).setCompartment(member.handle, destination);
}

bool SimulationState::wouldEraseSplitSpecies(MoleculeRef ref) const {
    if (!ref.valid() || !molecules(ref.type).alive(ref.handle)) return false;
    const MoleculeStore& source = molecules(ref.type);
    const auto reciprocallyBound = [&](MoleculeRef from, std::uint16_t slot,
                                      MoleculeRef partner) {
        if (!partner.valid() || !molecules(partner.type).alive(partner.handle)) return false;
        const MoleculeStore& partnerStore = molecules(partner.type);
        for (std::uint16_t partnerSlot = 0; partnerSlot < partnerStore.bondSlotCount(); ++partnerSlot)
            if (partnerStore.bondRef(partner.handle, partnerSlot) == from) return true;
        (void)slot;
        return false;
    };
    std::vector<MoleculeRef> neighbors;
    for (std::uint16_t slot = 0; slot < source.bondSlotCount(); ++slot) {
        MoleculeRef p = source.bondRef(ref.handle, slot);
        if (!p.valid()) continue;
        if (!reciprocallyBound(ref, slot, p)) return true;
        neighbors.push_back(p);
    }
    if (neighbors.size() < 2) return false;
    std::size_t components = 0;
    std::vector<MoleculeRef> assigned;
    for (const auto& neighbor : neighbors) {
        bool known = false; for (const auto& x : assigned) if (x == neighbor) { known = true; break; }
        if (known) continue;
        ++components;
        std::vector<MoleculeRef> pending(1, neighbor); assigned.push_back(neighbor);
        for (std::size_t i = 0; i < pending.size(); ++i) {
            const MoleculeRef cur = pending[i];
            const MoleculeStore& store = molecules(cur.type);
            for (std::uint16_t slot = 0; slot < store.bondSlotCount(); ++slot) {
                MoleculeRef p = store.bondRef(cur.handle, slot);
                if (!p.valid() || p == ref) continue;
                if (!molecules(p.type).alive(p.handle)) return true;
                if (!reciprocallyBound(cur, slot, p)) return true;
                bool k = false; for (const auto& x : assigned) if (x == p) { k = true; break; }
                if (!k) { assigned.push_back(p); pending.push_back(p); }
            }
        }
    }
    return components > 1;
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
