#include "seed.hh"

#include "../NFcore/NFcore.hh"

#include <map>
#include <stdexcept>

namespace NFcore2 {

void seedStateFromSystem(NFcore::System& system,
                         const NativeModelSnapshot& snapshot,
                         SimulationState& state) {
    const std::size_t nTypes = snapshot.molecule_types.size();
    if (state.model().moleculeTypes().size() != nTypes)
        throw std::invalid_argument(
            "seeder model/snapshot type count mismatch");
    for (std::size_t i = 0; i < nTypes; ++i) {
        if (state.model().moleculeTypes()[i].name !=
            snapshot.molecule_types[i].name)
            throw std::invalid_argument(
                "seeder model/snapshot type order mismatch");
    }

    std::map<const NFcore::Molecule*, MoleculeRef> handleOf;
    for (std::size_t i = 0; i < nTypes; ++i) {
        const NativeMoleculeTypeSnapshot& spec = snapshot.molecule_types[i];
        if (spec.population)
            throw std::invalid_argument(
                "seeder v1 rejects population types: " +
                spec.name);
        NFcore::MoleculeType* mt =
            system.getMoleculeTypeByName(spec.name);
        if (mt == nullptr)
            throw std::invalid_argument(
                "seeder cannot find NFcore molecule type: " + spec.name);
        if (mt->getTypeID() != static_cast<int>(i))
            throw std::invalid_argument(
                "seeder NFcore type_id/order mismatch: " + spec.name);
        const int nComp = mt->getNumOfComponents();
        if (static_cast<std::uint32_t>(nComp) != spec.component_count)
            throw std::invalid_argument(
                "seeder NFcore component count mismatch: " + spec.name);
        const MoleculeTypeId tid(static_cast<std::uint32_t>(i));
        const int count = mt->getMoleculeCount();
        for (int j = 0; j < count; ++j) {
            NFcore::Molecule* m = mt->getMolecule(j);
            if (m == nullptr)
                throw std::runtime_error("seeder hit null NFcore molecule");
            const MoleculeHandle h = state.molecules(tid).create();
            for (int c = 0; c < nComp; ++c)
                state.molecules(tid).setStateWord(
                    h, static_cast<std::uint16_t>(c),
                    static_cast<std::uint64_t>(m->getComponentState(c)));
            state.molecules(tid).setCompartment(
                h, nativeCompartmentId(m->getCompartmentId()));
            handleOf[m] = MoleculeRef(tid, h);
        }
    }

    for (std::size_t i = 0; i < nTypes; ++i) {
        const NativeMoleculeTypeSnapshot& spec = snapshot.molecule_types[i];
        NFcore::MoleculeType* mt =
            system.getMoleculeTypeByName(spec.name);
        const MoleculeTypeId tid(static_cast<std::uint32_t>(i));
        const int nComp = mt->getNumOfComponents();
        const int count = mt->getMoleculeCount();
        for (int j = 0; j < count; ++j) {
            NFcore::Molecule* m = mt->getMolecule(j);
            const MoleculeRef self = handleOf[m];
            for (int c = 0; c < nComp; ++c) {
                NFcore::Molecule* partner = m->getBondedMolecule(c);
                if (partner == nullptr)
                    continue;
                const std::map<const NFcore::Molecule*, MoleculeRef>::const_iterator
                    it = handleOf.find(partner);
                if (it == handleOf.end())
                    throw std::runtime_error(
                        "seeder bond partner outside seeded system");
                state.molecules(tid).setBondRef(
                    self.handle, static_cast<std::uint16_t>(c), it->second);
            }
        }
    }
}

} // namespace NFcore2
