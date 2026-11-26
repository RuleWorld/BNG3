#include "executable_model.hh"
#include <stdexcept>

namespace NFcore2 {

void ExecutableModel::validate() const {
    const std::vector<MatcherProgram>& matcher_programs=matchers_.programs();
    for (std::size_t i=0;i<matcher_programs.size();++i) {
        const std::vector<MatchInstruction>& code=matcher_programs[i].code();
        for (std::size_t j=0;j<code.size();++j) {
            if (code[j].opcode < MATCH_TYPE_EXISTS || code[j].opcode > MATCH_END)
                throw std::invalid_argument("executable model contains invalid matcher opcode");
        }
    }

    const std::vector<TransformProgram>& transform_programs=transforms_.programs();
    for (std::size_t i=0;i<transform_programs.size();++i) {
        const std::vector<TransformInstruction>& code=transform_programs[i].code();
        for (std::size_t j=0;j<code.size();++j) {
            if (code[j].opcode < TRANSFORM_SET_STATE_WORD || code[j].opcode > TRANSFORM_END)
                throw std::invalid_argument("executable model contains invalid transform opcode");
        }
    }

    const std::vector<RuleFamilyDescriptor>& families=metadata_.ruleFamilies();
    for (std::size_t i=0;i<families.size();++i) {
        if (!families[i].matcher.valid() || families[i].matcher.value() >= matcher_programs.size())
            throw std::invalid_argument("rule family references matcher outside registry");
        if (!families[i].transform.valid() || families[i].transform.value() >= transform_programs.size())
            throw std::invalid_argument("rule family references transform outside registry");
    }

    const DependencyIndex& deps=metadata_.dependencies();
    for (std::size_t i=0;i<deps.matchers.size();++i) {
        if (!deps.matchers[i].valid() || deps.matchers[i].value() >= matcher_programs.size())
            throw std::invalid_argument("dependency index references matcher outside registry");
    }
}

} // namespace NFcore2
