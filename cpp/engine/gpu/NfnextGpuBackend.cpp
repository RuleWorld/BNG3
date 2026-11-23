#include "engine/gpu/NfnextGpuBackend.hpp"

#include "engine/gpu/GpuSsaBackend.hpp"
#include "engine/gpu/NfnextUnaryStateKernel.hpp"
#include "compile/CompiledModel.hpp"
#include "nfnext/from_bng.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>

namespace bng::engine {
namespace {

[[noreturn]] void refuse(const std::string& reason) {
    throw std::runtime_error("NFnext GPU unsupported: " + reason);
}

bool noBondConstraint(const bng::compile::PatternSiteDescriptor& site) {
    using Kind = bng::compile::BondConstraintKind;
    const auto allowed = [](Kind kind) {
        return kind == Kind::Unspecified || kind == Kind::Unbound;
    };
    if (!allowed(site.bondKind)) return false;
    return std::all_of(site.bondConstraints.begin(), site.bondConstraints.end(),
                       [&](const auto& bond) { return allowed(bond.kind); });
}

detail::NfnextUnaryStatePlan compileUnaryStatePlan(
    const bng::compile::CompiledModel& source, std::size_t maxParticles) {
    const auto lowered = nfnext::lowerFromBioNetGen(source);
    if (!lowered.ok()) {
        for (const auto& issue : lowered.issues) {
            if (issue.severity == nfnext::BngLoweringSeverity::Error)
                refuse("CompiledModel to NFIR lowering failed: " + issue.message);
        }
    }
    const auto& model = lowered.model;
    if (!source.events().empty() || source.metadata().hasNativeEvents)
        refuse("event-triggered protocols are outside the unary single-site state-change slice");
    if (!source.compartments().empty() || !model.compartments.empty())
        refuse("compartments are outside the unary single-site state-change slice");
    if (!source.energyFactors().empty() || !source.barrierFactors().empty() ||
        !model.energy_patterns.empty())
        refuse("energy-modulated rules are outside the unary single-site state-change slice");
    if (!source.populationMaps().empty() || !model.population_maps.empty())
        refuse("population maps are outside the unary single-site state-change slice");
    for (const auto& parameter : source.parameters()) {
        if (parameter.timeDependent)
            refuse("time-dependent parameters are outside the unary single-site state-change slice");
    }
    if (model.molecule_types.size() != 1 || model.molecule_types.front().is_population ||
        model.molecule_types.front().sites.size() != 1 ||
        model.molecule_types.front().sites.front().states.size() < 2) {
        refuse("requires one molecule type with one stateful site and the unary single-site state-change family");
    }

    const auto moleculeType = model.molecule_types.front().id;
    const auto stateCount = model.molecule_types.front().sites.front().states.size();
    if (stateCount > static_cast<std::size_t>(std::numeric_limits<std::int32_t>::max()))
        refuse("state count exceeds the unary single-site state-change index capacity");

    std::size_t expectedRuleCount = 0;
    for (const auto& rule : source.rules()) {
        ++expectedRuleCount;
        if (rule.reverse()) ++expectedRuleCount;
        if (rule.delayExpression() || rule.resolvedDelayExpression())
            refuse("delayed rules are outside the unary single-site state-change slice");
        if (!rule.modifiers().empty() || !rule.forward().filters.empty() ||
            !rule.forward().localScopes.empty() ||
            (rule.reverse() && (!rule.reverse()->filters.empty() ||
                                !rule.reverse()->localScopes.empty())))
            refuse("rule modifiers and local scopes are outside the unary single-site state-change slice");
    }
    if (model.expanded_rules.size() != expectedRuleCount)
        refuse("NFIR did not preserve every rule direction for the unary single-site state-change slice");

    detail::NfnextUnaryStatePlan plan;
    constexpr std::size_t maxExactFloatCount = 1U << 24U;
    std::vector<std::vector<std::pair<std::int32_t, float>>> transitions(stateCount);
    for (const auto& rule : model.expanded_rules) {
        const auto& pattern = rule.pattern;
        const bool invalidShape = pattern.nodes.size() != 1 || !pattern.bonds.empty() ||
            !pattern.molecularity.empty() || !pattern.aliases.empty() ||
            !pattern.connected_to.empty() || !pattern.interchangeable.empty() ||
            (pattern.nodes.size() == 1 && pattern.nodes.front().compartment.has_value()) ||
            (pattern.nodes.size() == 1 && pattern.nodes.front().molecule_type != moleculeType) ||
            (pattern.nodes.size() == 1 && pattern.nodes.front().constraints.size() > 2);
        if (invalidShape) {
            std::ostringstream detail;
            detail << "rules must be unary single-site state-change reactions without bonds, topology, or compartments"
                   << " (nodes=" << pattern.nodes.size() << ", bonds=" << pattern.bonds.size()
                   << ", molecularity=" << pattern.molecularity.size()
                   << ", aliases=" << pattern.aliases.size()
                   << ", connected=" << pattern.connected_to.size()
                   << ", interchangeable=" << pattern.interchangeable.size();
            if (pattern.nodes.size() == 1)
                detail << ", type=" << pattern.nodes.front().molecule_type
                       << ", expected_type=" << moleculeType
                       << ", constraints=" << pattern.nodes.front().constraints.size()
                       << ", has_compartment=" << pattern.nodes.front().compartment.has_value();
            detail << ')';
            refuse(detail.str());
        }
        const nfnext::PatternIR::SiteConstraint* stateConstraint = nullptr;
        bool hasFreeConstraint = false;
        for (const auto& constraint : pattern.nodes.front().constraints) {
            if (constraint.site != 0) {
                refuse("rule constraints must refer only to the unary single-site state-change site");
            }
            if (constraint.kind == nfnext::PatternIR::SiteConstraintKind::State &&
                stateConstraint == nullptr) {
                stateConstraint = &constraint;
            } else if (constraint.kind == nfnext::PatternIR::SiteConstraintKind::Free &&
                       !hasFreeConstraint) {
                hasFreeConstraint = true;
            } else {
                refuse("rules may match one state and an optional invariant free-site constraint only");
            }
        }
        if (!stateConstraint || pattern.nodes.front().constraints.size() > 2 ||
            stateConstraint->state < 0 ||
            static_cast<std::size_t>(stateConstraint->state) >= stateCount) {
            refuse("rules must match exactly one declared state on the unary single-site state-change site");
        }
        if (rule.actions.size() != 1 ||
            rule.actions.front().kind != nfnext::ActionKind::SetSiteState ||
            rule.actions.front().target_node != 0 ||
            rule.actions.front().molecule_type != moleculeType ||
            rule.actions.front().site != 0 || rule.actions.front().value < 0 ||
            static_cast<std::size_t>(rule.actions.front().value) >= stateCount) {
            refuse("rules must perform one unary single-site state-change action and no graph edit");
        }
        if (rule.rate_law.kind != nfnext::RateLawKind::Elementary ||
            !std::isfinite(rule.rate) || rule.rate < 0.0 || rule.volume_factor != 1.0 ||
            rule.match_once || rule.total_rate || rule.move_connected ||
            !rule.filters.empty()) {
            refuse("rules must have finite static elementary rates in the unary single-site state-change slice");
        }
        const float rate = static_cast<float>(rule.rate);
        if (!std::isfinite(rate) || (rule.rate > 0.0 && rate == 0.0f))
            refuse("rule rate is not representable as finite Metal single precision");
        transitions[static_cast<std::size_t>(stateConstraint->state)].push_back(
            {rule.actions.front().value, rate});
    }

    plan.transitionOffsets.reserve(stateCount + 1);
    for (const auto& outgoing : transitions) {
        plan.transitionOffsets.push_back(static_cast<std::uint32_t>(plan.transitionRates.size()));
        double sum = 0.0;
        float deviceSum = 0.0f;
        for (const auto& [destination, rate] : outgoing) {
            plan.transitionDestinations.push_back(destination);
            plan.transitionRates.push_back(rate);
            sum += rate;
            deviceSum += rate;
            if (!std::isfinite(deviceSum))
                refuse("outgoing rate sum exceeds finite Metal single precision");
        }
        if (!std::isfinite(sum) || sum > std::numeric_limits<float>::max())
            refuse("outgoing rate sum exceeds finite Metal single precision");
    }
    plan.transitionOffsets.push_back(static_cast<std::uint32_t>(plan.transitionRates.size()));

    for (const auto& seed : source.seeds()) {
        if (seed.declaredUnit || seed.compartmentId || seed.pattern.compartmentId() ||
            !seed.evaluatedAmount || !std::isfinite(*seed.evaluatedAmount) ||
            *seed.evaluatedAmount < 0.0 || std::floor(*seed.evaluatedAmount) != *seed.evaluatedAmount ||
            *seed.evaluatedAmount > static_cast<double>(maxParticles)) {
            refuse("seeds must be bounded static integer populations without units or compartments");
        }
        if (seed.pattern.molecules().size() != 1) {
            refuse("seeds must contain only unary single-site state-change particles");
        }
        const auto& molecule = seed.pattern.molecules().front();
        if (!molecule.moleculeTypeId ||
            static_cast<nfnext::TypeId>(molecule.moleculeTypeId->value()) != moleculeType ||
            molecule.compartmentId || molecule.sites.size() != 1) {
            refuse("seeds must use the unary single-site state-change molecule type without compartments");
        }
        const auto& site = molecule.sites.front();
        if (!site.componentType || site.componentType->index != 0 ||
            site.stateConstraintResolved.kind != bng::compile::StateConstraintKind::Exact ||
            !site.stateConstraintResolved.exact || !noBondConstraint(site)) {
            refuse("seeds must initialize one exact state on an unbound unary single-site state-change particle");
        }
        const auto state = site.stateConstraintResolved.exact->index;
        if (state >= stateCount) refuse("seed state is outside the unary single-site state-change declaration");
        const auto count = static_cast<std::size_t>(*seed.evaluatedAmount);
        if (count > maxParticles - plan.initialStates.size())
            refuse("initial population exceeds the unary single-site state-change particle budget");
        if (count > maxExactFloatCount - plan.initialStates.size())
            refuse("initial population exceeds exact Metal single-precision observable counts");
        plan.initialStates.insert(plan.initialStates.end(), count,
                                  static_cast<std::int32_t>(state));
    }

    std::set<std::string> observableNames;
    for (const auto& observable : source.observables()) {
        if (observable.kind != bng::compile::ObservableKind::Molecules ||
            observable.terms.size() != 1 || !observableNames.insert(observable.name).second) {
            refuse("observables must be unique one-term Molecules counts in the unary single-site state-change slice");
        }
        const auto& pattern = observable.terms.front().pattern;
        if (!observable.terms.front().relation.empty() || pattern.molecules().size() != 1 ||
            pattern.compartmentId()) {
            refuse("observables must be unqualified unary single-site state-change molecule counts");
        }
        const auto& molecule = pattern.molecules().front();
        if (!molecule.moleculeTypeId ||
            static_cast<nfnext::TypeId>(molecule.moleculeTypeId->value()) != moleculeType ||
            molecule.compartmentId || !noBondConstraint(
                molecule.sites.empty() ? bng::compile::PatternSiteDescriptor{} : molecule.sites.front())) {
            refuse("observables must count the unary single-site state-change molecule type without bond filters");
        }
        std::int32_t state = -1;
        if (!molecule.sites.empty()) {
            if (molecule.sites.size() != 1 || !molecule.sites.front().componentType ||
                molecule.sites.front().componentType->index != 0) {
                refuse("observable site constraints must refer only to the unary single-site state-change site");
            }
            const auto& stateConstraint = molecule.sites.front().stateConstraintResolved;
            if (stateConstraint.kind == bng::compile::StateConstraintKind::Exact &&
                stateConstraint.exact) {
                if (stateConstraint.exact->index >= stateCount)
                    refuse("observable state is outside the unary single-site state-change declaration");
                state = static_cast<std::int32_t>(stateConstraint.exact->index);
            } else if (stateConstraint.kind != bng::compile::StateConstraintKind::Any) {
                refuse("observables require an exact state or all states on the unary single-site state-change site");
            }
        }
        plan.observableNames.push_back(observable.name);
        plan.observableStates.push_back(state);
    }
    return plan;
}

std::size_t checkedProduct(std::size_t a, std::size_t b) {
    if (a != 0 && b > std::numeric_limits<std::size_t>::max() / a)
        refuse("batch output dimensions overflow native address capacity");
    return a * b;
}

} // namespace

NfnextGpuResult simulateNfnextGpu(const bng::compile::CompiledModel& source,
                                  const NfnextGpuRequest& request) {
    if (request.sampleTimes.empty()) refuse("sample_times must not be empty");
    double previous = -1.0;
    for (const double time : request.sampleTimes) {
        if (!std::isfinite(time) || time < 0.0 || time <= previous)
            refuse("sample_times must be finite, nonnegative, and strictly increasing");
        const float deviceTime = static_cast<float>(time);
        if (!std::isfinite(deviceTime) || static_cast<double>(deviceTime) != time)
            refuse("sample_times must be exactly representable as finite Metal single precision");
        previous = time;
    }
    if (request.batchSize == 0 || request.batchSize > std::numeric_limits<std::uint32_t>::max())
        refuse("batch_size must fit the positive native GPU trajectory range");
    if (request.maxEvents == 0 || request.maxEvents > std::numeric_limits<std::uint32_t>::max())
        refuse("max_events must fit the positive native GPU event range");
    if (request.maxParticles > std::numeric_limits<std::uint32_t>::max())
        refuse("max_particles exceeds native GPU particle indexing");

    const auto plan = compileUnaryStatePlan(source, request.maxParticles);
    const auto expectedValues = checkedProduct(
        checkedProduct(request.batchSize, request.sampleTimes.size()),
        plan.observableNames.size());
    if (expectedValues > std::numeric_limits<std::uint32_t>::max())
        refuse("batch output element count exceeds Metal kernel indexing capacity");
    if (request.backend != "metal") {
        if (request.backend == "cuda")
            refuse("network-free CUDA execution is not implemented");
        refuse("backend must explicitly select the implemented 'metal' route");
    }

    const auto inventory = gpuBackendInventory();
    const auto metal = std::find_if(inventory.begin(), inventory.end(), [](const auto& item) {
        return item.kind == GpuBackendKind::Metal;
    });
    if (metal == inventory.end() || !metal->compiled)
        refuse("Metal backend is not compiled into this build");
    if (!metal->available)
        refuse("Metal backend has no usable device: " + metal->detail);

#ifdef BNG3_HAS_METAL
    const auto output = detail::simulateNfnextUnaryStateMetal(plan, request);
    NfnextGpuResult result;
    result.sampleTimes = request.sampleTimes;
    result.observableNames = plan.observableNames;
    result.observables = output.observables;
    result.eventCounts = output.eventCounts;
    result.batchSize = request.batchSize;
    result.backend = "metal";
    result.device = output.device;
    result.wallTimeMs = output.wallTimeMs;
    result.dispatchWaitTimeMs = output.dispatchWaitTimeMs;
    if (result.observables.size() != expectedValues ||
        result.eventCounts.size() != request.batchSize) {
        refuse("Metal kernel returned output with an invalid batch shape");
    }
    return result;
#else
    refuse("Metal backend is not compiled into this build");
#endif
}

} // namespace bng::engine
