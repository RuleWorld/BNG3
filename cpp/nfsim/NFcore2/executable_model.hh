#pragma once
#include "compiled_model.hh"
#include "matcher.hh"
#include "transform.hh"

namespace NFcore2 {

// Immutable-after-build executable model. Multiple trajectories share this
// object while owning independent SimulationState/ScaffoldStore instances.
class ExecutableModel {
public:
    CompiledModel& buildMetadata() { return metadata_; }
    MatcherRegistry& buildMatchers() { return matchers_; }
    TransformRegistry& buildTransforms() { return transforms_; }

    const CompiledModel& metadata() const { return metadata_; }
    const MatcherRegistry& matchers() const { return matchers_; }
    const TransformRegistry& transforms() const { return transforms_; }
    void validate() const;
private:
    CompiledModel metadata_;
    MatcherRegistry matchers_;
    TransformRegistry transforms_;
};

} // namespace NFcore2
