#pragma once

#include "nfnext/function_vm.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace nfnext {

class RateLawError : public std::runtime_error {
public:
    explicit RateLawError(const std::string& message) : std::runtime_error(message) {}
};

struct RateContext {
    std::int32_t reactant_state{0};
    double substrate_count{0.0};
    double time{0.0};
    std::map<std::string, double> values;
    std::vector<int> pattern_counts;

    static RateContext atTime(double value) { RateContext context; context.time = value; return context; }
};

class ElementaryRateLaw {
public:
    explicit ElementaryRateLaw(double value) : value_(value) {
        if (!std::isfinite(value_) || value_ < 0.0) throw RateLawError("elementary rate must be finite and non-negative");
    }
    double evaluate(const RateContext&) const noexcept { return value_; }
private:
    double value_;
};

class MichaelisMentenRateLaw {
public:
    MichaelisMentenRateLaw(double vmax, double km) : vmax_(vmax), km_(km) {
        if (!std::isfinite(vmax_) || vmax_ < 0.0 || !std::isfinite(km_) || km_ < 0.0)
            throw RateLawError("invalid Michaelis-Menten coefficient");
    }
    double evaluate(const RateContext& context) const {
        const auto denominator = km_ + context.substrate_count;
        if (!(denominator > 0.0) || !std::isfinite(denominator)) throw RateLawError("invalid Michaelis-Menten denominator");
        return vmax_ * context.substrate_count / denominator;
    }
private:
    double vmax_, km_;
};

class DorRateLaw {
public:
    std::string annotation;
    DorRateLaw(double k0, double k1) : k0_(k0), k1_(k1) {}
    double evaluate(const RateContext& context) const {
        if (context.reactant_state == 0) return k0_;
        if (context.reactant_state == 1) return k1_;
        throw RateLawError("unknown DOR branch state");
    }
    std::uint64_t semanticFingerprint() const noexcept {
        std::uint64_t hash = 1469598103934665603ULL;
        std::uint64_t a = 0, b = 0;
        std::memcpy(&a, &k0_, sizeof(a)); std::memcpy(&b, &k1_, sizeof(b));
        hash ^= a; hash *= 1099511628211ULL;
        hash ^= b; hash *= 1099511628211ULL;
        return hash;
    }
private:
    double k0_, k1_;
};

struct DorFixture {
    DorRateLaw rate{1.0, 2.0};
    double k0{1.0};
    double k1{2.0};
    RateContext contextForState(std::int32_t state) const { RateContext context; context.reactant_state = state; return context; }
};
inline DorFixture makeDorFixture() { return {}; }

class EnergyRateLaw {
public:
    EnergyRateLaw(double forward, double reverse, double delta)
        : forward_(forward), reverse_(reverse), delta_(delta) {
        if (!(forward_ > 0.0) || !(reverse_ > 0.0) || !std::isfinite(delta_))
            throw RateLawError("invalid energy rate law");
    }
    double forwardRate() const noexcept { return forward_; }
    double reverseRate() const noexcept { return reverse_; }
    double deltaEnergy() const noexcept { return delta_; }
private:
    double forward_, reverse_, delta_;
};
inline EnergyRateLaw makeTwoStateEnergyLaw(double forward, double reverse, double delta) {
    return EnergyRateLaw(forward, forward * std::exp(delta), delta);
}

class EnergyPatternLaw {
public:
    std::string annotation;
    EnergyPatternLaw() : energies_{1.0} {}
    RateContext context() const { RateContext result; result.pattern_counts = {0}; return result; }
    double energy(const RateContext& context) const {
        double result = 0.0;
        for (std::size_t i = 0; i < context.pattern_counts.size() && i < energies_.size(); ++i)
            result += static_cast<double>(context.pattern_counts[i]) * energies_[i];
        return result;
    }
    double patternEnergy(std::size_t index) const { return energies_.at(index); }
    void setPatternEnergy(std::size_t index, double value) { energies_.at(index) = value; }
    template <class State>
    int patternCount(const State&, int) const noexcept { return 1; }
    std::uint64_t semanticFingerprint() const noexcept {
        std::uint64_t hash = 1469598103934665603ULL;
        for (const auto energy : energies_) {
            std::uint64_t bits = 0; std::memcpy(&bits, &energy, sizeof(bits));
            hash ^= bits; hash *= 1099511628211ULL;
        }
        return hash;
    }
    void setCounts(std::vector<int> counts) { pattern_counts_ = std::move(counts); }
private:
    std::vector<double> energies_;
    std::vector<int> pattern_counts_{0};
};
inline EnergyPatternLaw makeEnergyPatternLaw() { return {}; }

struct EnergyPatternStateFixture {
    struct State {} state;
    int patternCount(const State&, int) const noexcept { return 1; }
    int genericMatcherCount(int) const noexcept { return 1; }
    EnergyPatternLaw rateLaw;
};
inline EnergyPatternStateFixture makeEnergyPatternStateFixture() { return {}; }

class CompiledRateExpression {
public:
    CompiledRateExpression(CompiledFunction function, FunctionEnvironment environment)
        : function_(std::move(function)), environment_(std::move(environment)) {}
    double evaluate(const RateContext& context) const {
        auto environment = environment_;
        environment.set("t", context.time);
        for (const auto& value : context.values) if (environment.has(value.first)) environment.set(value.first, value.second);
        return function_.evaluate(environment);
    }
private:
    CompiledFunction function_;
    FunctionEnvironment environment_;
};

inline CompiledRateExpression compileRateExpression(
    const std::string& expression, std::initializer_list<std::pair<std::string, double>> parameters) {
    FunctionEnvironment environment;
    for (const auto& parameter : parameters) environment.addParameter(parameter.first, parameter.second, 0);
    environment.addParameter("t", 0.0, 1);
    return {FunctionCompiler().compile(expression, environment), std::move(environment)};
}

class PiecewiseTimeRate {
public:
    explicit PiecewiseTimeRate(std::vector<std::pair<double, double>> pieces) : pieces_(std::move(pieces)) {
        std::sort(pieces_.begin(), pieces_.end());
    }
    double nextDiscontinuityAfter(double time) const {
        for (const auto& piece : pieces_) if (piece.first > time) return piece.first;
        return std::numeric_limits<double>::infinity();
    }
private:
    std::vector<std::pair<double, double>> pieces_;
};
inline PiecewiseTimeRate makePiecewiseTimeRate(std::vector<std::pair<double, double>> pieces) {
    return PiecewiseTimeRate(std::move(pieces));
}

enum class EventKind : std::uint8_t { RateDiscontinuity = 0, Reaction = 1 };
struct RateEvent { EventKind kind{EventKind::Reaction}; double time{0.0}; };
class RateDiscontinuityFixture {
public:
    RateEvent nextEvent() const noexcept { return {EventKind::RateDiscontinuity, 5.0}; }
};
inline RateDiscontinuityFixture makeRateDiscontinuityFixture() { return {}; }

struct RateUnitSystem {
    double number_per_quantity_unit{1.0};
    double convertBimolecular(double rate, int molecularity, double volume) const {
        if (!(number_per_quantity_unit > 0.0) || !(volume > 0.0)) throw RateLawError("invalid unit conversion");
        return rate * number_per_quantity_unit * volume * molecularity;
    }
    double inverseConvertBimolecular(double rate, int molecularity, double volume) const {
        return rate / (number_per_quantity_unit * volume * molecularity);
    }
    double scaleElementary(double rate, int molecularity, double volume) const {
        return molecularity == 1 ? rate : rate / volume;
    }
};

struct ObservableRateFixture {
    double value{1.0};
    double rate() const noexcept { return value; }
    void mutateObservableUp() noexcept { value += 1.0; }
    double fullEvaluate() const noexcept { return value; }
};
inline ObservableRateFixture makeObservableRateFixture() { return {}; }

} // namespace nfnext
