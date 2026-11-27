#pragma once
#include "engine.hh"
#include <cstdint>
#include <string>
#include <vector>

namespace NFcore2 {

// Backend-neutral event/state record. The existing NFsim backend can populate
// this without exposing pointers to NFcore2, while NFcore2 has native helpers.
struct ShadowObservable {
    std::string name;
    double value;
};

struct ShadowState {
    double time;
    std::vector<std::int64_t> populations;
    std::vector<ShadowObservable> observables;
    std::uint64_t semantic_hash;
    ShadowState() : time(0.0), semantic_hash(0) {}
};

struct ShadowEvent {
    std::string rule_name;
    std::uint32_t logical_member;
    double propensity;
    ShadowState before;
    ShadowState after;
};

struct ShadowMismatch {
    bool mismatch;
    std::string field;
    std::string detail;
    ShadowMismatch() : mismatch(false) {}
};

class ShadowComparator {
public:
    static ShadowMismatch compareState(const ShadowState& legacy, const ShadowState& optimized,
                                       double absolute_tolerance=0.0);
    static ShadowMismatch compareEvent(const ShadowEvent& legacy, const ShadowEvent& optimized,
                                       double absolute_tolerance=0.0);
};

// Stable, allocation-free hash helpers for adapters. This is deliberately not
// a hash of pointer identity; callers feed canonical semantic integers/strings.
class SemanticHasher {
public:
    SemanticHasher();
    void addU64(std::uint64_t value);
    void addI64(std::int64_t value);
    void addString(const std::string& value);
    std::uint64_t value() const { return hash_; }
private:
    std::uint64_t hash_;
};

} // namespace NFcore2
