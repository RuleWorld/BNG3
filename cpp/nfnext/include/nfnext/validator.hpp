#pragma once

#include "nfnext/nfir.hpp"

#include <stdexcept>
#include <string>

namespace nfnext {

class ValidationError : public std::runtime_error {
public:
    explicit ValidationError(const std::string& message) : std::runtime_error(message) {}
};

void validateModel(const ModelIR& model);

} // namespace nfnext
