#pragma once
#include "compiled_model.hh"
#include <cstdint>
#include <string>
#include <vector>

namespace NFcore2 {

// Parser-independent normalized rule instance. The legacy XML/BNGL layer can
// lower each syntactic ReactionClass into this compact representation before
// family canonicalization.
struct RuleInstanceIR {
    std::string name;
    std::string matcher_signature;
    std::string transform_signature;
    MatcherId matcher;
    TransformProgramId transform;
    double rate;
    std::uint32_t parameter_index;
    std::uint32_t coordinate;
};

struct RuleFamilyCompilation {
    std::vector<RuleFamilyDescriptor> families;
    std::vector<RuleFamilyId> instance_to_family;
    std::vector<std::uint32_t> instance_to_member;
};

class RuleFamilyCompiler {
public:
    static RuleFamilyCompilation compile(const std::vector<RuleInstanceIR>& instances);
};

} // namespace NFcore2
