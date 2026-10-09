#pragma once

#include <string>

namespace bng::compile { class CompiledModel; }

namespace bng::io::sbml_units {

bool enabled(const compile::CompiledModel& model);

// Returns the complete listOfUnitDefinitions element.  Unit definitions are
// emitted from the same unit table used by the BNGL parser and compiler.
std::string writeUnitDefinitions(const compile::CompiledModel& model, int level = 3);

// Returns model-level Core unit attributes, including the leading spaces
// needed when appending them to a <model> start tag.
std::string modelAttributes(const compile::CompiledModel& model, int level = 3);

// Returns an SBML UnitSId for an authored unit expression.  Built-in SBML
// units are canonicalized; compound expressions receive stable generated IDs.
std::string reference(const compile::CompiledModel& model, const std::string& authored);

std::string attribute(const compile::CompiledModel& model, const std::string& authored);

// SBML Level 2 and Level 3 use `substanceUnits` on Species; the legacy
// `units` attribute is reserved for Level 1.
std::string speciesAttribute(const compile::CompiledModel& model,
                             const std::string& authored, int level = 3);

} // namespace bng::io::sbml_units
