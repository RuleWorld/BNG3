#pragma once
#include "ids.hh"
#include <cstdint>
#include <unordered_map>
#include <vector>
#include <stdexcept>

namespace NFcore2 {

enum ScaffoldStorageKind { SCAFFOLD_DENSE, SCAFFOLD_SPARSE };

class ScaffoldStore {
public:
    struct Scaffold {
        std::uint32_t length;
        std::uint8_t default_state;
        ScaffoldStorageKind storage;
        std::vector<std::uint8_t> dense_state;
        std::vector<MoleculeHandle> dense_occupant;
        std::unordered_map<std::uint32_t,std::uint8_t> state_exceptions;
        std::unordered_map<std::uint32_t,MoleculeHandle> sparse_occupant;
    };
    ScaffoldId create(std::uint32_t length, std::uint8_t default_state = 0,
                      ScaffoldStorageKind storage = SCAFFOLD_SPARSE);
    std::uint8_t state(ScaffoldId id, std::uint32_t position) const;
    void setState(ScaffoldId id, std::uint32_t position, std::uint8_t value);
    MoleculeHandle occupant(ScaffoldId id, std::uint32_t position) const;
    void setOccupant(ScaffoldId id, std::uint32_t position, MoleculeHandle handle);
    std::uint32_t length(ScaffoldId id) const;
    std::size_t materializedStateCount(ScaffoldId id) const;
    std::size_t occupiedCount(ScaffoldId id) const;
private:
    std::vector<Scaffold> scaffolds_;
};

} // namespace NFcore2
