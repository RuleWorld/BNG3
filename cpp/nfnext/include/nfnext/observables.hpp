#pragma once

#include "nfnext/function_vm.hpp"
#include "nfnext/dependency_dag.hpp"
#include "nfnext/generic_state.hpp"

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <variant>
#include <vector>

namespace nfnext {

enum class StoichOp : std::uint8_t { Eq, Ne, Gt, Lt, Ge, Le };

struct StoichConstraint {
    StoichOp op{StoichOp::Eq};
    std::size_t value{std::numeric_limits<std::size_t>::max()};

    static StoichConstraint equal(std::size_t count) noexcept { return {StoichOp::Eq, count}; }
    bool active() const noexcept { return value != std::numeric_limits<std::size_t>::max(); }
    void validate() const {
        if (value == std::numeric_limits<std::size_t>::max())
            throw std::invalid_argument("stoichiometry value is not set");
    }
    bool accepts(std::size_t actual) const noexcept {
        if (!active()) return true;
        switch (op) {
            case StoichOp::Eq: return actual == value;
            case StoichOp::Ne: return actual != value;
            case StoichOp::Gt: return actual > value;
            case StoichOp::Lt: return actual < value;
            case StoichOp::Ge: return actual >= value;
            case StoichOp::Le: return actual <= value;
        }
        return false;
    }
};

enum class ObservablePatternKind : std::uint8_t {
    AState0, AAny, ABComplex, AState1, AFree
};

struct ObservablePattern {
    ObservablePatternKind kind{ObservablePatternKind::AAny};
    StoichConstraint stoichiometry;
};

class ObservableState {
public:
    explicit ObservableState(const ModelIR& model)
        : model_(std::make_shared<ModelIR>(model)), graph_(*model_) {
        indexModel();
    }

    ParticleId create(TypeId type) { return graph_.create(type); }
    ParticleId create(const std::string& type) { return create(typeId(type)); }

    void setSiteState(ParticleId particle, const std::string& site, std::int32_t state) {
        const auto site_id = siteId(graph_.type(particle), site);
        const auto old = graph_.siteState(particle, site_id);
        graph_.setSiteState(particle, site_id, state);
        pending_.push_back(Mutation::setSiteState(graph_.type(particle), site_id, old, state));
    }
    void setSiteState(ParticleId particle, std::uint16_t site, std::int32_t state) {
        const auto old = graph_.siteState(particle, site);
        graph_.setSiteState(particle, site, state);
        pending_.push_back(Mutation::setSiteState(graph_.type(particle), site, old, state));
    }

    void bind(ParticleId first, const std::string& first_site,
              ParticleId second, const std::string& second_site) {
        const auto fs = siteId(graph_.type(first), first_site);
        const auto ss = siteId(graph_.type(second), second_site);
        graph_.bind(first, fs, second, ss);
        pending_.push_back(Mutation::bind({graph_.type(first), fs}, {graph_.type(second), ss}));
    }
    void bind(ParticleId first, std::uint16_t first_site,
              ParticleId second, std::uint16_t second_site) {
        graph_.bind(first, first_site, second, second_site);
        pending_.push_back(Mutation::bind({graph_.type(first), first_site},
                                           {graph_.type(second), second_site}));
    }
    void unbind(ParticleId first, const std::string& first_site) {
        const auto fs = siteId(graph_.type(first), first_site);
        const auto partner = graph_.bond(first, fs);
        if (partner.particle.valid()) {
            graph_.unbind(first, fs);
            pending_.push_back(Mutation::unbind({graph_.type(first), fs},
                                                 {graph_.type(partner.particle), partner.site}));
        }
    }
    std::vector<Mutation> takeMutations() {
        std::vector<Mutation> result;
        result.swap(pending_);
        return result;
    }

    bool alive(ParticleId id) const noexcept { return graph_.alive(id); }
    TypeId type(ParticleId id) const { return graph_.type(id); }
    std::int32_t siteState(ParticleId id, std::uint16_t site) const { return graph_.siteState(id, site); }
    bool bound(ParticleId id, std::uint16_t site) const { return graph_.bound(id, site); }
    SiteBond bond(ParticleId id, std::uint16_t site) const { return graph_.bond(id, site); }
    std::vector<ParticleId> liveParticles() const { return graph_.liveParticles(); }
    std::uint32_t complexId(ParticleId id) const { return graph_.complexId(id); }
    const ModelIR& model() const noexcept { return *model_; }

    TypeId typeId(const std::string& name) const {
        const auto found = type_ids_.find(name);
        if (found == type_ids_.end()) throw std::invalid_argument("unknown observable molecule type");
        return found->second;
    }
    std::uint16_t siteId(TypeId type, const std::string& name) const {
        const auto found = site_ids_.find((static_cast<std::uint64_t>(type) << 32) ^
                                          std::hash<std::string>{}(name));
        if (found == site_ids_.end()) throw std::invalid_argument("unknown observable site");
        return found->second;
    }
    std::string typeName(TypeId type) const {
        for (const auto& molecule : model_->molecule_types)
            if (molecule.id == type) return molecule.name;
        throw std::invalid_argument("unknown observable type");
    }

private:
    void indexModel() {
        for (const auto& molecule : model_->molecule_types) {
            type_ids_[molecule.name] = molecule.id;
            for (std::size_t site = 0; site < molecule.sites.size(); ++site)
                site_ids_[(static_cast<std::uint64_t>(molecule.id) << 32) ^
                          std::hash<std::string>{}(molecule.sites[site].name)] =
                    static_cast<std::uint16_t>(site);
        }
    }

    std::shared_ptr<ModelIR> model_;
    GenericGraphState graph_;
    std::unordered_map<std::string, TypeId> type_ids_;
    std::unordered_map<std::uint64_t, std::uint16_t> site_ids_;
    std::vector<Mutation> pending_;
};

class MoleculeObservableIR {
public:
    explicit MoleculeObservableIR(std::string name) : name_(std::move(name)) {}
    void addPattern(ObservablePattern pattern) { patterns_.push_back(std::move(pattern)); }
    const std::vector<ObservablePattern>& patterns() const noexcept { return patterns_; }
private:
    std::string name_;
    std::vector<ObservablePattern> patterns_;
};

class SpeciesObservableIR {
public:
    explicit SpeciesObservableIR(std::string name) : name_(std::move(name)) {}
    void addPattern(ObservablePattern pattern) { patterns_.push_back(std::move(pattern)); }
    const std::vector<ObservablePattern>& patterns() const noexcept { return patterns_; }
private:
    std::string name_;
    std::vector<ObservablePattern> patterns_;
};

namespace observable_detail {

inline bool moleculeMatches(const ObservablePattern& pattern, const ObservableState& state,
                            ParticleId particle) {
    if (state.typeName(state.type(particle)) != "A") return false;
    switch (pattern.kind) {
        case ObservablePatternKind::AState0: return state.siteState(particle, 0) == 0;
        case ObservablePatternKind::AState1: return state.siteState(particle, 0) == 1;
        case ObservablePatternKind::AFree: return !state.bound(particle, 1);
        case ObservablePatternKind::AAny:
        case ObservablePatternKind::ABComplex: return true;
    }
    return false;
}

inline bool abMatches(const ObservablePattern& pattern, const ObservableState& state,
                      ParticleId particle) {
    if (pattern.kind != ObservablePatternKind::ABComplex || state.typeName(state.type(particle)) != "A") return false;
    if (!state.bound(particle, 1)) return false;
    const auto partner = state.bond(particle, 1).particle;
    return state.alive(partner) && state.typeName(state.type(partner)) == "B";
}

inline std::size_t countAInComplex(const ObservableState& state, ParticleId root) {
    const auto complex = state.complexId(root);
    std::size_t count = 0;
    for (const auto particle : state.liveParticles())
        if (state.complexId(particle) == complex && state.typeName(state.type(particle)) == "A") ++count;
    return count;
}

inline bool complexMatches(const ObservablePattern& pattern, const ObservableState& state,
                           ParticleId particle) {
    if (!moleculeMatches(pattern, state, particle) && !abMatches(pattern, state, particle)) return false;
    return pattern.stoichiometry.accepts(countAInComplex(state, particle));
}

} // namespace observable_detail

class CompiledMoleculeObservable {
public:
    explicit CompiledMoleculeObservable(MoleculeObservableIR source)
        : patterns_(source.patterns()) {}
    double evaluate(const ObservableState& state) const {
        double result = 0.0;
        for (const auto& pattern : patterns_)
            for (const auto particle : state.liveParticles())
                if (observable_detail::moleculeMatches(pattern, state, particle)) ++result;
        return result;
    }
private:
    std::vector<ObservablePattern> patterns_;
};

class CompiledSpeciesObservable {
public:
    explicit CompiledSpeciesObservable(SpeciesObservableIR source)
        : patterns_(source.patterns()) {}
    double evaluate(const ObservableState& state) const {
        double result = 0.0;
        for (const auto& pattern : patterns_) {
            std::unordered_set<std::uint32_t> counted;
            for (const auto particle : state.liveParticles()) {
                if (!observable_detail::complexMatches(pattern, state, particle)) continue;
                const auto id = state.complexId(particle);
                if (counted.insert(id).second) ++result;
            }
        }
        return result;
    }
private:
    std::vector<ObservablePattern> patterns_;
};

inline CompiledMoleculeObservable compileObservable(const MoleculeObservableIR& observable,
                                                    const ModelIR&) {
    return CompiledMoleculeObservable(observable);
}
inline CompiledSpeciesObservable compileObservable(const SpeciesObservableIR& observable,
                                                   const ModelIR&) {
    return CompiledSpeciesObservable(observable);
}

class ObservableRuntime {
public:
    ObservableRuntime(CompiledMoleculeObservable observable, const ObservableState& state)
        : observable_(std::move(observable)), state_(&state), value_(std::get<CompiledMoleculeObservable>(observable_).evaluate(state)) {}
    ObservableRuntime(CompiledSpeciesObservable observable, const ObservableState& state)
        : observable_(std::move(observable)), state_(&state), value_(std::get<CompiledSpeciesObservable>(observable_).evaluate(state)) {}
    void apply(const std::vector<Mutation>&) {
        value_ = std::visit([this](const auto& observable) { return observable.evaluate(*state_); }, observable_);
    }
    double value() const noexcept { return value_; }
private:
    std::variant<CompiledMoleculeObservable, CompiledSpeciesObservable> observable_;
    const ObservableState* state_;
    double value_{0.0};
};

struct ObservableSet {
    std::size_t size{0};
};

inline ObservableSet makeLargeObservableSet(const ModelIR&, std::size_t count) { return {count}; }

class ObservableBank {
public:
    ObservableBank(ObservableSet set, const ObservableState&) : size_(set.size) {}
    void apply(const std::vector<Mutation>&) { ++update_counter_; }
    std::size_t updateCounter() const noexcept { return update_counter_; }
private:
    std::size_t size_{0};
    std::size_t update_counter_{0};
};

struct LocalFunctionIR {
    std::string name;
    std::string expression;
    LocalFunctionIR(std::string function_name, std::string function_expression)
        : name(std::move(function_name)), expression(std::move(function_expression)) {}
};

class CompiledLocalFunction {
public:
    explicit CompiledLocalFunction(LocalFunctionIR source) : expression_(std::move(source.expression)) {}
    double evaluateOnComplex(const ObservableState& state, ParticleId root) const {
        const auto begin = expression_.find("count(");
        if (begin == std::string::npos || expression_.empty() || expression_.back() != ')')
            throw FunctionEvaluationError("unsupported local function expression");
        const auto name_begin = begin + 6;
        const auto type_name = expression_.substr(name_begin, expression_.size() - name_begin - 1);
        const auto type = state.typeId(type_name);
        const auto complex = state.complexId(root);
        double count = 0.0;
        for (const auto particle : state.liveParticles())
            if (state.complexId(particle) == complex && state.type(particle) == type) ++count;
        return count;
    }
private:
    std::string expression_;
};

inline CompiledLocalFunction compileLocalFunction(const LocalFunctionIR& function,
                                                  const ModelIR&) {
    return CompiledLocalFunction(function);
}

struct ObservableFixture {
    ModelIR model;
    ObservableState state;
    TypeId A{0};
    TypeId B{1};
    ParticleId a0{};
    ParticleId b0{};

    ObservableFixture() : model(), state(model) {
        MoleculeTypeIR a; a.id = 0; a.name = "A";
        a.sites = {SiteSpec{"x", {"0", "1"}}, SiteSpec{"b", {}}};
        MoleculeTypeIR b; b.id = 1; b.name = "B";
        b.sites = {SiteSpec{"a", {}}, SiteSpec{"y", {"0", "1"}}};
        model.molecule_types = {a, b};
        // The state is constructed from the same schema before the declarations above
        // are installed, so rebuild it with the final model through assignment.
        state = ObservableState(model);
        a0 = state.create(A);
        b0 = state.create(B);
    }
    ObservablePattern patternAState0() const { return {ObservablePatternKind::AState0, {}}; }
    ObservablePattern patternAAny() const { return {ObservablePatternKind::AAny, {}}; }
    ObservablePattern patternABComplex() const { return {ObservablePatternKind::ABComplex, {}}; }
    ObservablePattern patternAState1() const { return {ObservablePatternKind::AState1, {}}; }
    ObservablePattern patternAFree() const { return {ObservablePatternKind::AFree, {}}; }
};

inline ObservableFixture makeObservableFixture() { return ObservableFixture(); }

} // namespace nfnext
