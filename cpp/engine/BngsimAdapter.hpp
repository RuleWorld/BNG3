#pragma once

#include <memory>

#include "NetworkGenerator.hpp"

namespace bngsim {
class NetworkModel;
}

namespace bng::engine {

// Build BNGsim's native model directly from BNG3's generated network. This is
// deliberately bounded: unsupported semantic forms throw before solver use.
// No .net serialization is involved.
std::unique_ptr<bngsim::NetworkModel> buildBngsimNetwork(
    const ast::Model& model,
    const GeneratedNetwork& network);

} // namespace bng::engine
