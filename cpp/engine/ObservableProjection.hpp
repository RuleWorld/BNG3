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
        // Number of automorphisms of `pattern`, i.e. the count of embeddings
        // of the pattern into itself. Computed once at construction because it
        // depends only on the pattern. Used by the Molecules CountUnique mode;
        // 1 for an asymmetric pattern, which makes that mode a no-op.
        std::size_t automorphisms = 1;
    };
    struct Observable {
        std::string name;
        compile::ObservableKind kind = compile::ObservableKind::Unknown;
        std::vector<Term> terms;
    };

    // BNG2's two counting modes. Oracle: legacy/perl/Perl2/Observable.pm:236
    // (Molecules) and :260 (Species). They are NOT the same operation, despite
    // sharing the CountUnique/CountAll spelling:
    //
    //   Molecules + CountAll     total += match_count
    //   Molecules + CountUnique  total += match_count / automorphisms
    //   Species   + CountAll     total += 1 for every matching term
    //   Species   + CountUnique  total += 1, then stop scanning terms
    //                            (`last if ($mode)`), so a species counts once
    //                            no matter how many of the observable's
    //                            patterns it matches
    //
    // Note the asymmetry: symmetry correction is commented out on the Species
    // branch in BNG2, where the flag instead short-circuits the term loop.
    enum class CountMode { CountAll, CountUnique };

    CountMode moleculesMode_ = CountMode::CountAll;
    CountMode speciesMode_ = CountMode::CountAll;

    compile::BNGcoreLoweringContext loweringContext_;
    std::vector<Observable> observables_;
};

} // namespace bng::engine
