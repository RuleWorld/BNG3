#pragma once

// Fail-closed guard for export formats that cannot represent eBNGL energy
// semantics.
//
// A generated reaction network carries `Arrhenius(phi, Ea)` as the rate law
// text of every energy-derived reaction. `NetWriter` resolves those into
// per-reaction numeric rate parameters; no other exporter does. So an exporter
// that simply copies the rate law emits either a literal `Arrhenius(...)` call
// the target language has never heard of, or silently omits the energy
// contribution. Either way the exported model does not reproduce the source
// kinetics.
//
// Per the project rule that an explicitly unsupported model beats one that runs
// with changed semantics, these exporters now refuse such a model instead of
// producing plausible-looking but wrong output.
//
// This guard is only for formats that encode *kinetics*. Structural and
// visualization outputs (contact maps, regulatory/influence/process graphs,
// rule visualization) legitimately ignore rate laws, so they are not guarded:
// dropping an energy annotation does not misrepresent what they claim to show.

#include <string>

namespace bng::ast {
class Model;
}

namespace bng::io {

// Throws std::runtime_error naming `formatName` and the offending construct
// when the model uses energy semantics the format cannot express:
//
//   * energy patterns (ground-state free energies),
//   * barrier patterns (transition-state contributions),
//   * `driven_by()` reservoir work,
//   * an Arrhenius rate law on any rule.
//
// The Arrhenius check is deliberately separate from the energy-pattern check.
// A rule can carry an Arrhenius rate law in a model whose energy patterns were
// dropped or were never present, and that rule is still inexpressible.
void requireNoEnergySemantics(const ast::Model& model, const std::string& formatName);

// True when the model uses any of the above. Exposed so a caller that wants to
// degrade rather than throw can make that choice explicitly.
bool usesEnergySemantics(const ast::Model& model);

} // namespace bng::io
