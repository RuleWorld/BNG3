#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <string>
#include <vector>

namespace bng::compile::energy {

enum class ConditionKind : int {
    Bond,
    State,
};

// A local predicate needed to decide whether an energy factor contributes to
// the free-energy change of a rule firing.  The compiler owns semantic
// discovery of these predicates; simulation backends only evaluate them.
struct EnergyCondition {
    ConditionKind kind = ConditionKind::Bond;
    int reactantIndex = -1;
    std::string moleculeType;
    std::string componentName;

    // Bond predicate fields.
    bool expectedBound = true;
    std::string partnerType;
    std::string partnerComponent;

    // State predicate field.
    std::string expectedState;

    // Optional compiler provenance. Backends do not use this to evaluate the
    // predicate; it lets compatibility adapters and diagnostics trace a
    // predicate to the energy factors that introduced it.
    std::vector<std::size_t> sourceFactorIndices;

    bool operator==(const EnergyCondition& other) const;
};

// A signed contribution to delta-G. conditionMask is a conjunction: the term
// contributes iff every condition bit in the mask is present in the evaluated
// context mask.  Signed values allow the same representation for binding
// (+formation energy) and state changes (+to-state, -from-state).
struct EnergyTerm {
    double energyValue = 0.0;
    std::uint64_t conditionMask = 0;
    std::size_t sourceFactorIndex = std::numeric_limits<std::size_t>::max();

    bool operator==(const EnergyTerm& other) const;
};

enum class EnergyDeltaStrategy {
    Constant,
    BitmaskFactorized,
    MaterializedFallback,
};

class EnergyDeltaPlan {
public:
    static EnergyDeltaPlan constant(double baseEnergy);

    // Construct a factorized local plan. Returns nullopt if the representation
    // would be unsafe (non-finite energy, too many predicates, zero/out-of-range
    // term masks). An empty term list collapses to a Constant plan.
    static std::optional<EnergyDeltaPlan> factorized(
        double baseEnergy,
        std::vector<EnergyCondition> conditions,
        std::vector<EnergyTerm> terms,
        std::size_t maxConditions = 63);

    static EnergyDeltaPlan materializedFallback();

    EnergyDeltaStrategy strategy() const { return strategy_; }
    bool isExecutable() const {
        return strategy_ != EnergyDeltaStrategy::MaterializedFallback;
    }
    bool isConstant() const { return strategy_ == EnergyDeltaStrategy::Constant; }
    bool isFactorized() const {
        return strategy_ == EnergyDeltaStrategy::BitmaskFactorized;
    }

    double baseEnergy() const { return baseEnergy_; }
    const std::vector<EnergyCondition>& conditions() const { return conditions_; }
    const std::vector<EnergyTerm>& terms() const { return terms_; }

    std::uint64_t validConditionMask() const;
    bool maskIsValid(std::uint64_t conditionMask) const;

    // Returns nullopt for a fallback plan or an invalid context mask.
    std::optional<double> tryDeltaG(std::uint64_t conditionMask) const;

    // Arrhenius factor excluding exp(-Ea/RT):
    //   forward: exp(-phi * deltaG / RT)
    //   reverse: exp(-(phi - 1) * deltaG / RT)
    std::optional<double> tryArrheniusFactor(
        std::uint64_t conditionMask,
        double phi,
        double RT,
        bool isForward) const;

    // Precompute a table indexed by the complete condition mask. This is only
    // intended for small local contexts; nullopt means the plan is not safely
    // table-lowerable under maxConditions.
    std::optional<std::vector<double>> buildArrheniusTable(
        double phi,
        double RT,
        bool isForward,
        std::size_t maxConditions = 8) const;

    // Useful for backend lowering: identify whether all predicates are scoped
    // to one reactant. Returns nullopt for no predicates or mixed reactants.
    std::optional<int> singleReactantIndex() const;

    // Bit mask of predicates evaluated on one reactant. This is dependency
    // metadata, not a truth assignment.
    std::uint64_t predicateMaskForReactant(int reactantIndex) const;

private:
    EnergyDeltaPlan() = default;

    EnergyDeltaStrategy strategy_ = EnergyDeltaStrategy::MaterializedFallback;
    double baseEnergy_ = 0.0;
    std::vector<EnergyCondition> conditions_;
    std::vector<EnergyTerm> terms_;
};

} // namespace bng::compile::energy
