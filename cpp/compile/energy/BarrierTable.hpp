#pragma once

// Barrier patterns contribute to the transition state of a rule, not to the
// free energy of either ground state. They are therefore keyed by reaction
// center rather than by species pattern, and they are symmetric under
// reversal: forward and reverse traversals of a transition cross the same
// barrier.
//
// This file owns only the keying and accumulation. Extracting a reaction
// center from an ast::BarrierPattern lives in BarrierCompiler.hpp so that this
// unit stays free of AST and graph dependencies and can be tested directly.

#include <cstddef>
#include <map>
#include <string>
#include <vector>

namespace bng::compile::energy {

enum class ReactionCenterKind {
    Binding,
    StateChange,
};

// Canonical identity of a reaction center.
//
//   Binding:     the unordered pair of (moleculeType, componentName) endpoints
//                of the bond being formed or broken.
//   StateChange: (moleculeType, componentName) plus the unordered pair of
//                endpoint states.
//
// Both are stored in sorted order, which is what makes a barrier symmetric
// under reversal without the caller having to normalize anything.
struct ReactionCenterKey {
    ReactionCenterKind kind = ReactionCenterKind::StateChange;
    std::string firstType;
    std::string firstName;
    std::string secondType;
    std::string secondName;

    static ReactionCenterKey binding(
        std::string typeA, std::string siteA,
        std::string typeB, std::string siteB);

    static ReactionCenterKey stateChange(
        std::string moleculeType, std::string componentName,
        std::string stateA, std::string stateB);

    bool operator==(const ReactionCenterKey& other) const;
    bool operator<(const ReactionCenterKey& other) const;

    // Stable human-readable form, used in diagnostics and XML metadata.
    //   binding:      "bond:<type>.<site>|<type>.<site>"
    //   state change: "state:<type>.<comp>~<state>|<type>.<comp>~<state>"
    // Both halves are already in canonical (sorted) order.
    std::string toString() const;

    // Inverse of toString(). Returns false for anything it cannot parse
    // exactly, so a malformed key in a serialized model fails closed instead
    // of producing a barrier on the wrong reaction center.
    static bool parse(const std::string& text, ReactionCenterKey& key);
};

// Accumulated barrier energy per reaction center.
//
// Several barrier patterns may match the same center; like energy patterns,
// their contributions add. The table stores the running sum together with the
// number of contributing patterns so diagnostics can report both.
class BarrierTable {
public:
    struct Entry {
        double barrier = 0.0;
        std::size_t contributingPatterns = 0;
        // Labels of the barrier patterns that produced this entry, in
        // insertion order. Used for provenance in diagnostics and XML.
        std::vector<std::string> sources;
    };

    // Returns false and sets `diagnostic` when the value is not finite. A
    // non-finite barrier is rejected rather than silently dropped because it
    // would otherwise produce a zero or infinite rate.
    bool add(
        const ReactionCenterKey& key,
        double barrier,
        const std::string& sourceLabel,
        std::string& diagnostic);

    // Summed barrier for a center, or 0.0 when no pattern matches. Zero is the
    // correct neutral element: exp(-(Ea + 0)/RT) is the unmodified rate.
    double lookup(const ReactionCenterKey& key) const;

    bool contains(const ReactionCenterKey& key) const;
    const Entry* find(const ReactionCenterKey& key) const;

    bool empty() const { return entries_.empty(); }
    std::size_t size() const { return entries_.size(); }
    const std::map<ReactionCenterKey, Entry>& entries() const { return entries_; }

private:
    std::map<ReactionCenterKey, Entry> entries_;
};

} // namespace bng::compile::energy
