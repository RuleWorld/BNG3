#pragma once

// Source-level normalization for the nonequilibrium thermodynamic extensions.
//
// Two surface constructs are accepted:
//
//   begin barrier patterns
//     A(s~U) -> A(s~P) Gbar
//   end barrier patterns
//
//   begin reaction rules
//     A(s~U) <-> A(s~P) Arrhenius(phi,Ea) driven_by(muATP)
//   end reaction rules
//
// Both are rewritten into constructs the checked-in generated ANTLR parser
// already accepts, so no grammar regeneration is required:
//
//   * a barrier patterns block becomes a reaction rules block whose entries
//     carry the synthetic label `__bng3_barrier_<N>`. The trailing barrier
//     energy lands in the rate-law position of an ordinary rule, which lets
//     the existing graph-diff machinery compute the reaction center instead of
//     requiring a second transition detector. A post-parse pass moves those
//     rules out of the model's reaction rules and into its barrier patterns.
//
//   * `driven_by(W)` is stripped from a reaction rule line and re-emitted as
//     `setOption("__bng3_driving_work:<k>", "W")`, where k is the index of the
//     rule among the model's ordinary (non-barrier) rules in source order.
//     Indexing over ordinary rules only keeps the annotation stable no matter
//     where the synthetic barrier block is placed.
//
// Everything here is a pure string-to-string transformation with no ANTLR, AST
// or graph dependency, so the surface syntax can be tested on its own.

#include <string>

namespace bng::parser {

// Synthetic markers shared between the normalizer and the AST visitor.
inline constexpr const char* kBarrierRuleLabelPrefix = "__bng3_barrier_";
inline constexpr const char* kBarrierLabelOptionPrefix = "__bng3_barrier_label:";
inline constexpr const char* kDrivingWorkOptionPrefix = "__bng3_driving_work:";

// Throws std::runtime_error for malformed barrier blocks or malformed
// `driven_by` annotations rather than dropping them, so an unsupported or
// mistyped construct can never be silently reinterpreted as an ordinary rule.
std::string normalizeThermodynamicSyntax(const std::string& source);

} // namespace bng::parser
