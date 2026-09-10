#pragma once

#include "nfnext/rule_family.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace nfnext {

struct FamilyRejection {
    RuleId first_rule{0};
    RuleId second_rule{0};
    std::string reason;
};

struct FamilyCompileOptions {
    bool explain_rejections{false};
};

struct FamilyCompileResult {
    std::vector<RuleFamilyIR> families;
    FamilyCollapseStats stats;
    std::vector<FamilyRejection> rejections;

    std::uint64_t semanticFingerprint() const noexcept;
};

// Compile expanded rules into conservative coordinate-parameterized families.
// Only semantically identical rule shapes with a consecutive coordinate run
// are collapsed; all other rules remain explicit singleton families.
FamilyCompileResult compileRuleFamilies(
    const std::vector<ExpandedRuleIR>& rules,
    const FamilyCompileOptions& options = {});

// Expand a compiled family set into its exact rule-shape oracle. Source rule
// identifiers determine the returned order; names and source metadata are not
// part of semantic equality.
std::vector<ExpandedRuleIR> expandFamilies(const std::vector<RuleFamilyIR>& families);

bool semanticRuleEqual(const ExpandedRuleIR& a, const ExpandedRuleIR& b) noexcept;
bool semanticRuleSequenceEqual(const std::vector<ExpandedRuleIR>& a,
                               const std::vector<ExpandedRuleIR>& b) noexcept;

} // namespace nfnext
