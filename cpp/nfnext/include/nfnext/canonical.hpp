#pragma once

#include "nfnext/nfir.hpp"

#include <cstdint>
#include <string>

namespace nfnext {

enum class ConnectivityPolicy : std::uint8_t {
    Legacy = 0,
    Strict = 1
};

struct CanonicalOptions {
    ConnectivityPolicy connectivity_policy{ConnectivityPolicy::Legacy};
    bool include_model_name_in_semantic_hash{true};
};

struct CanonicalModel {
    ModelIR model;
    CanonicalOptions options;

    std::string canonicalBytes() const;
    std::uint64_t semanticFingerprint() const noexcept;
    std::uint64_t diagnosticFingerprint() const noexcept;
    std::uint64_t compileKey() const noexcept;
};

CanonicalModel canonicalizeModel(const ModelIR& model, const CanonicalOptions& options = {});
CanonicalModel canonicalizeModel(const CanonicalModel& model, const CanonicalOptions& options = {});

} // namespace nfnext
