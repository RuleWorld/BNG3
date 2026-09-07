#pragma once
#include "executable_model.hh"
#include "scheduler.hh"
#include <vector>

namespace NFcore2 {

class Engine {
public:
    explicit Engine(const ExecutableModel& executable)
        : executable_(executable), state_(executable.metadata()), scheduler_(executable.metadata()) {
        executable_.validate();
    }

    // Copying an Engine creates an independent trajectory while sharing only
    // immutable executable-model metadata/programs.
    Engine(const Engine& other)
        : executable_(other.executable_), state_(other.state_), scaffolds_(other.scaffolds_),
          scheduler_(other.scheduler_), counters_(other.counters_) {}

    SimulationState& state(){return state_;}
    const SimulationState& state() const{return state_;}
    ScaffoldStore& scaffolds(){return scaffolds_;}
    const ScaffoldStore& scaffolds() const{return scaffolds_;}
    HierarchicalScheduler& scheduler(){return scheduler_;}

    struct Counters {
        std::uint64_t events;
        std::uint64_t matcher_evaluations;
        std::uint64_t rejected_fires;
        std::uint64_t feature_deltas;
        Counters() : events(0), matcher_evaluations(0), rejected_fires(0), feature_deltas(0) {}
    };
    const Counters& counters() const { return counters_; }

    std::vector<MatcherId> affectedMatchers(const FeatureDelta& delta) const;
    std::vector<RuleFamilyId> affectedFamilies(const FeatureDelta& delta) const;
    bool fire(RuleFamilyId family, std::uint32_t member, MatchContext& context, FeatureDelta& delta);
private:
    const ExecutableModel& executable_;
    SimulationState state_;
    ScaffoldStore scaffolds_;
    HierarchicalScheduler scheduler_;
    Counters counters_;
};

} // namespace NFcore2
