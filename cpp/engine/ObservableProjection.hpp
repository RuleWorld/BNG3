#pragma once

#include <cstddef>
#include <string>
#include <vector>

#include "compile/CompiledModel.hpp"
#include "compile/PatternLowering.hpp"
#include "core/BNGcore.hpp"

namespace bng::engine {

// Shared structural observable projection used by network exporters/backends.
// Patterns are lowered exactly once from CompiledModel and then matched using
// the backend-neutral BioNetGen matcher; no BNGL reparsing occurs here.
class ObservableProjection {
public:
    explicit ObservableProjection(const compile::CompiledModel& model);

    std::size_t size() const noexcept { return observables_.size(); }
    const std::string& name(std::size_t index) const { return observables_.at(index).name; }

    int weight(std::size_t observableIndex, const BNGcore::PatternGraph& species) const;
    std::vector<int> weights(const BNGcore::PatternGraph& species) const;

private:
    struct Term {
        BNGcore::PatternGraph pattern;
        std::string relation;
        int quantity = 0;
    };
    struct Observable {
        std::string name;
        compile::ObservableKind kind = compile::ObservableKind::Unknown;
        std::vector<Term> terms;
    };

    compile::BNGcoreLoweringContext loweringContext_;
    std::vector<Observable> observables_;
};

} // namespace bng::engine
