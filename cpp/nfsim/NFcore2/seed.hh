#pragma once

#include "nfsim_adapter_contract.hh"
#include "simulation_state.hh"

namespace NFcore {
class System;
} // namespace NFcore

namespace NFcore2 {

// Seeds an empty SimulationState from a live NFcore System (built from BNGL,
// prepared or not — only molecules, states, bonds, and compartments are
// read; propensities are recomputed by SsaDriver::initialize).
//
// Contract with the lowering (must hold for matcher semantics to agree):
// - NFcore2 type index == snapshot order == NFcore type_id (verified by
//   name; mismatch throws);
// - state word index == NFcore component index, values in the NFcore int
//   domain (equality semantics are preserved by the cast);
// - bond slot index == NFcore component index (both numberings cover all
//   components; NFcore bond[] is component-sized and null for non-sites);
// - compartment id == nativeCompartmentId(NFcore compartment id).
//
// v1 fail-closed scope: population types throw (lumped counts are not
// particles and have no seeding source yet).
//
// Note: takes a non-const System& only because NFcore accessors
// (getMoleculeTypeByName) are not const-qualified; seeding never mutates.
void seedStateFromSystem(NFcore::System& system,
                         const NativeModelSnapshot& snapshot,
                         SimulationState& state);

} // namespace NFcore2
