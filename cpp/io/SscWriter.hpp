#pragma once

#include <string>
#include <vector>
#include "ast/Model.hpp"
#include "engine/NetworkGenerator.hpp"

namespace bng::io {

/**
 * SscWriter - Export model to SSC (Stochastic Simulation Compiler) format
 *
 * Generates a simple text file with:
 * - Parameter definitions as const declarations
 * - Species declarations with initial counts
 * - Reaction definitions with rate law references
 * Reference: BNG2/bng2/Perl2/BNGOutput.pm::writeSSC() (the .rxn artifact).
 * The .cfg artifact that `writeSSCcfg` produces is a *different* file -- the
 * parameter block only -- and is written by writeConfig() below.
 */
class SscWriter {
public:
    static std::string write(
        const ast::Model& model,
        const engine::GeneratedNetwork& network
    );

    // BNG2 `writeSSCcfg`: the parameter block only, in a .cfg file. This is
    // not a prefix of write()'s output and must not be derived from it, since
    // the two artifacts serve different tools.
    static std::string writeConfig(const ast::Model& model);
};

} // namespace bng::io
