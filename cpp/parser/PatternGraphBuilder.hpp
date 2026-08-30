#pragma once

#include "ast/Model.hpp"
#include "generated/BNGParser.h"

namespace bng::parser {

BNGcore::PatternGraph buildPatternGraph(
	BNGParser::Species_defContext* ctx,
	ast::Model& model,
	bool treatUnspecifiedBondAsWildcard = false);

/// Convert a molecule pattern into the inferred type fragment it contributes.
/// The parser prepass uses this to collect states before any pattern graph is
/// materialized, matching BNG2's model-wide inference for omitted type blocks.
ast::MoleculeType inferMoleculeTypeFromPattern(BNGParser::Molecule_patternContext* ctx);

std::string extractSpeciesCompartment(BNGParser::Species_defContext* ctx);
bool isSpeciesCompartmentPrefix(BNGParser::Species_defContext* ctx);

} // namespace bng::parser
