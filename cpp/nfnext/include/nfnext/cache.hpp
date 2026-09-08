#pragma once

#include "nfnext/nfir.hpp"

#include <string>

namespace nfnext {

class ModelCache {
public:
    static void save(const ModelIR& model, const std::string& path);
    static ModelIR load(const std::string& path);
};

} // namespace nfnext
