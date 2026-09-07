#pragma once

#include "nfnext/nfir.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace nfnext {

struct FamilyCollapseStats {
    std::size_t input_rules{0};
    std::size_t output_families{0};
    std::size_t collapsed_rules{0};
    std::size_t singleton_families{0};
};

struct FamilyCollapseResult {
    std::vector<RuleFamilyIR> families;
    FamilyCollapseStats stats;
};

// Collapse rules such as elongate_1, elongate_2, ... when their structure is
// identical modulo a coordinate-like integer. The compiler stays conservative:
// non-consecutive or structurally different rules remain singleton families.
FamilyCollapseResult collapseIndexedRuleFamilies(const std::vector<ExpandedRuleIR>& rules);

std::string stripTrailingIndex(const std::string& name, std::uint32_t* index = nullptr);

} // namespace nfnext
