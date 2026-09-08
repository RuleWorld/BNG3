#pragma once

#include <filesystem>

#include "io/NetReader.hpp"

namespace bng::io {

/**
 * Read the flattened SBML dialect emitted by BioNetGen.
 *
 * This reader intentionally handles network SBML, not SBML Multi atomization.
 * Multi/atomized conversion remains owned by the Python atomizer path.
 */
class SbmlReader {
public:
    static NetReader::ParseResult parse(
        const std::filesystem::path& filepath, bool atomize = false);
};

}  // namespace bng::io
