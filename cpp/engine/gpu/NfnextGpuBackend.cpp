#include "engine/gpu/NfnextGpuBackend.hpp"

#include "engine/gpu/GpuSsaBackend.hpp"
#include "engine/gpu/NfnextGraphKernel.hpp"
#include "engine/gpu/NfnextUnaryStateKernel.hpp"
#include "compile/CompiledModel.hpp"
#include "nfnext/from_bng.hpp"
#include "nfnext/function_vm.hpp"
#include "nfnext/generic_matcher.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <numeric>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>

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
            refuse("initial population exceeds exact GPU single-precision observable counts");
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

// Compute all permutations of site indices that only permute sites sharing the
// same declared site name on a molecule type (e.g. L(r,r,r) -> 3! = 6).
std::vector<std::vector<std::uint16_t>> sitePermutationsForType(
    const nfnext::MoleculeTypeIR& type) {
    const std::size_t n = type.sites.size();
    std::vector<std::uint16_t> identity(n);
    std::iota(identity.begin(), identity.end(), static_cast<std::uint16_t>(0));
    std::map<std::string, std::vector<std::uint16_t>> groups;
    for (std::size_t i = 0; i < n; ++i) {
        groups[type.sites[i].name].push_back(static_cast<std::uint16_t>(i));
    }
    std::vector<std::vector<std::uint16_t>> perms{identity};
    for (auto& [_, indices] : groups) {
        if (indices.size() <= 1) continue;
        std::vector<std::uint16_t> sorted = indices;
        std::sort(sorted.begin(), sorted.end());
        std::vector<std::vector<std::uint16_t>> next;
        do {
            for (const auto& base : perms) {
                auto copy = base;
                for (std::size_t k = 0; k < indices.size(); ++k) {
                    copy[indices[k]] = sorted[k];
                }
                next.push_back(std::move(copy));
            }
        } while (std::next_permutation(sorted.begin(), sorted.end()));
        perms = std::move(next);
        if (perms.size() > 256) {
            refuse("site symmetry group exceeds bounded GPU graph expansion limit");
        }
    }
    return perms;
}

struct CanonicalConstraintKey {
    std::uint16_t site{0};
    std::uint8_t kind{0};
    std::int32_t state{0};
    bool operator<(const CanonicalConstraintKey& o) const noexcept {
        return std::tie(site, kind, state) < std::tie(o.site, o.kind, o.state);
    }
    bool operator==(const CanonicalConstraintKey& o) const noexcept {
        return site == o.site && kind == o.kind && state == o.state;
    }
};

std::vector<CanonicalConstraintKey> canonicalizeNodeConstraints(
    const nfnext::PatternIR::Node& node,
    const std::vector<std::uint16_t>& perm) {
    std::vector<CanonicalConstraintKey> out;
    out.reserve(node.constraints.size());
    for (const auto& c : node.constraints) {
        std::uint8_t k = detail::kGpuConstraintState;
        std::int32_t st = 0;
        if (c.kind == nfnext::PatternIR::SiteConstraintKind::State) {
            k = detail::kGpuConstraintState;
            st = c.state;
        } else if (c.kind == nfnext::PatternIR::SiteConstraintKind::Free) {
            k = detail::kGpuConstraintFree;
        } else if (c.kind == nfnext::PatternIR::SiteConstraintKind::Bound) {
            k = detail::kGpuConstraintBound;
        } else {
            refuse("state-set site constraints are outside the GPU graph kernel slice");
        }
        out.push_back({perm.at(c.site), k, st});
    }
    std::sort(out.begin(), out.end());
    out.erase(std::unique(out.begin(), out.end()), out.end());
    return out;
}

std::uint32_t observableAutomorphismWeight(
    const nfnext::PatternIR& pattern, const nfnext::ModelIR& model) {
    std::size_t weight = nfnext::compileMatchPlan(pattern, model).automorphismCount();
    for (const auto& node : pattern.nodes) {
        const auto& type = model.molecule_types.at(node.molecule_type);
        std::map<std::string, std::size_t> classes;
        for (const auto& constraint : node.constraints) {
            std::ostringstream key;
            const std::string siteName =
                constraint.site < type.sites.size()
                    ? type.sites[constraint.site].name
                    : std::to_string(constraint.site);
            key << siteName << ':' << static_cast<int>(constraint.kind) << ':';
            for (const auto state : constraint.states) key << state << ',';
            key << constraint.state;
            ++classes[key.str()];
        }
        for (const auto& [_, count] : classes) {
            for (std::size_t f = 2; f <= count; ++f) weight *= f;
        }
    }
    return static_cast<std::uint32_t>(weight);
}

// Convert a CompiledModel observable pattern term into NFIR PatternIR (1..4 nodes).
nfnext::PatternIR lowerObservablePatternToIr(
    const bng::compile::PatternDescriptor& pattern,
    const nfnext::ModelIR& model) {
    if (pattern.compartmentId()) {
        refuse("compartmental observables are outside the GPU graph kernel slice");
    }
    if (pattern.molecules().empty() ||
        pattern.molecules().size() > detail::kGpuMaxObsPatternNodes) {
        refuse("observable pattern node count exceeds bounded GPU graph kernel capacity");
    }
    nfnext::PatternIR ir;
    std::map<std::string, std::vector<std::pair<std::size_t, std::uint32_t>>> bondLabels;
    for (std::size_t mIdx = 0; mIdx < pattern.molecules().size(); ++mIdx) {
        const auto& mol = pattern.molecules()[mIdx];
        if (!mol.moleculeTypeId || mol.compartmentId) {
            refuse("observable molecule lacks resolved type or uses compartments");
        }
        const auto typeId = static_cast<nfnext::TypeId>(mol.moleculeTypeId->value());
        if (typeId >= model.molecule_types.size()) {
            refuse("observable molecule type out of range");
        }
        const auto& typeIr = model.molecule_types[typeId];
        const auto nodeId = ir.addNode(typeId);
        std::vector<bool> usedSite(typeIr.sites.size(), false);
        for (const auto& site : mol.sites) {
            if (!site.componentType) {
                refuse("observable site lacks resolved component type");
            }
            // Pick the first unused site with matching name (supports same-name sites).
            std::uint32_t siteIdx = static_cast<std::uint32_t>(site.componentType->index);
            if (siteIdx < typeIr.sites.size() && usedSite[siteIdx]) {
                const std::string& targetName = typeIr.sites[siteIdx].name;
                bool found = false;
                for (std::uint32_t alt = 0; alt < typeIr.sites.size(); ++alt) {
                    if (!usedSite[alt] && typeIr.sites[alt].name == targetName) {
                        siteIdx = alt;
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    refuse("observable specifies more instances of a site than declared");
                }
            }
            if (siteIdx >= typeIr.sites.size()) {
                refuse("observable site index out of range");
            }
            usedSite[siteIdx] = true;
            if (site.stateConstraintResolved.kind == bng::compile::StateConstraintKind::Exact &&
                site.stateConstraintResolved.exact) {
                ir.node(nodeId).siteState(
                    siteIdx, static_cast<std::int32_t>(site.stateConstraintResolved.exact->index));
            } else if (site.stateConstraintResolved.kind != bng::compile::StateConstraintKind::Any) {
                refuse("unsupported observable site state constraint in GPU graph kernel");
            }
            using BK = bng::compile::BondConstraintKind;
            auto handleBond = [&](const BK kind, const std::string& label) {
                if (kind == BK::Unspecified || kind == BK::Unbound) {
                    ir.node(nodeId).siteFree(siteIdx);
                } else if (kind == BK::Bound) {
                    ir.node(nodeId).siteBound(siteIdx);
                } else if (kind == BK::Any) {
                    // Any bond status (free or bound) => no bond constraint.
                } else if (kind == BK::Exact) {
                    bondLabels[label].emplace_back(nodeId, siteIdx);
                } else {
                    refuse("unsupported observable bond constraint in GPU graph kernel");
                }
            };
            if (!site.bondConstraints.empty()) {
                if (site.bondConstraints.size() != 1) {
                    refuse("multi-bond site constraints are outside GPU graph kernel");
                }
                handleBond(
                    site.bondConstraints.front().kind, site.bondConstraints.front().constraint);
            } else {
                handleBond(site.bondKind, site.bondConstraint);
            }
        }
    }
    for (const auto& [label, endpoints] : bondLabels) {
        if (endpoints.size() != 2) {
            refuse("observable bond label does not connect exactly two endpoints");
        }
        ir.requireBond(endpoints[0].first, endpoints[0].second,
                       endpoints[1].first, endpoints[1].second);
    }
    if (ir.bonds.size() > detail::kGpuMaxObsPatternBonds) {
        refuse("observable bond count exceeds GPU graph kernel capacity");
    }
    return ir;
}

detail::NfnextGraphPlan compileGraphPlan(
    const bng::compile::CompiledModel& source, std::size_t maxParticles) {
    const auto lowered = nfnext::lowerFromBioNetGen(source);
    if (!lowered.ok()) {
        for (const auto& issue : lowered.issues) {
            if (issue.severity == nfnext::BngLoweringSeverity::Error) {
                refuse("CompiledModel to NFIR lowering failed: " + issue.message);
            }
        }
    }
    const auto& model = lowered.model;
    if (!source.events().empty() || source.metadata().hasNativeEvents)
        refuse("event-triggered protocols are outside the GPU graph kernel slice");
    if (!source.compartments().empty() || !model.compartments.empty())
        refuse("compartments are outside the GPU graph kernel slice");
    if (!source.populationMaps().empty() || !model.population_maps.empty())
        refuse("population maps are outside the GPU graph kernel slice");
    for (const auto& parameter : source.parameters()) {
        if (parameter.timeDependent)
            refuse("time-dependent parameters are outside the GPU graph kernel slice");
    }
    if (model.molecule_types.empty()) {
        refuse("model defines no molecule types");
    }

    detail::NfnextGraphPlan plan;
    plan.numTypes = static_cast<std::uint32_t>(model.molecule_types.size());
    plan.maxSites = 1;
    plan.typeSiteCounts.resize(plan.numTypes, 0);
    for (std::size_t t = 0; t < model.molecule_types.size(); ++t) {
        const auto& mt = model.molecule_types[t];
        if (mt.is_population) refuse("population molecule types are outside GPU graph kernel");
        if (mt.sites.size() > detail::kGpuMaxSitesPerMolecule) {
            refuse("molecule type exceeds maximum GPU site count (8)");
        }
        plan.typeSiteCounts[t] = static_cast<std::uint32_t>(mt.sites.size());
        plan.maxSites = std::max(plan.maxSites, plan.typeSiteCounts[t]);
    }
    plan.typeDefaultStates.assign(
        static_cast<std::size_t>(plan.numTypes) * plan.maxSites, 0);

    // Identify fixed single-molecule seed species (e.g. $Trash()) and initial counts.
    std::set<std::uint32_t> fixedTypes;
    std::vector<std::uint32_t> initialTypeCounts(plan.numTypes, 0);
    struct InitialComplex {
        std::vector<std::uint32_t> molTypes;
        std::vector<std::vector<std::int32_t>> siteStates;
        std::vector<std::tuple<std::size_t, std::uint32_t, std::size_t, std::uint32_t>> bonds;
        std::uint32_t copies{0};
    };
    std::vector<InitialComplex> initComplexes;

    for (const auto& seed : source.seeds()) {
        if (seed.declaredUnit || seed.compartmentId || seed.pattern.compartmentId() ||
            !seed.evaluatedAmount || !std::isfinite(*seed.evaluatedAmount) ||
            *seed.evaluatedAmount < 0.0 ||
            std::floor(*seed.evaluatedAmount) != *seed.evaluatedAmount ||
            *seed.evaluatedAmount > static_cast<double>(maxParticles)) {
            refuse("seeds must be bounded static integer populations without units or compartments");
        }
        if (seed.constant && seed.pattern.molecules().size() == 1 &&
            seed.pattern.molecules().front().moleculeTypeId) {
            fixedTypes.insert(
                static_cast<std::uint32_t>(seed.pattern.molecules().front().moleculeTypeId->value()));
        }
        const auto copies = static_cast<std::uint32_t>(*seed.evaluatedAmount);
        if (copies == 0) continue;

        const auto seedIr = lowerObservablePatternToIr(seed.pattern, model);
        InitialComplex cx;
        cx.copies = copies;
        for (const auto& node : seedIr.nodes) {
            cx.molTypes.push_back(node.molecule_type);
            std::vector<std::int32_t> st(plan.maxSites, 0);
            for (const auto& c : node.constraints) {
                if (c.kind == nfnext::PatternIR::SiteConstraintKind::State) {
                    st[c.site] = c.state;
                }
            }
            cx.siteStates.push_back(std::move(st));
            initialTypeCounts[node.molecule_type] += copies;
        }
        for (const auto& b : seedIr.bonds) {
            cx.bonds.emplace_back(b.first, b.first_site, b.second, b.second_site);
        }
        initComplexes.push_back(std::move(cx));
    }

    // Track which molecule types can be dynamically created by rules.
    std::set<std::uint32_t> createdTypes;
    std::size_t expectedRuleCount = 0;
    const bool hasEnergyFactors =
        !source.energyFactors().empty() || !source.barrierFactors().empty() ||
        !model.energy_patterns.empty();
    for (const auto& rule : source.rules()) {
        ++expectedRuleCount;
        if (rule.reverse()) ++expectedRuleCount;
        if (rule.delayExpression() || rule.resolvedDelayExpression()) {
            refuse("delayed rules are outside the GPU graph kernel slice");
        }
        auto checkFilters = [&](const bng::compile::CompiledRuleDirection& dir) {
            for (const auto& filter : dir.filters) {
                if (filter.products) {
                    refuse("product include/exclude filters are outside the GPU graph kernel slice");
                }
            }
        };
        checkFilters(rule.forward());
        if (rule.reverse()) checkFilters(*rule.reverse());
    }
    if (!hasEnergyFactors && model.expanded_rules.size() != expectedRuleCount) {
        refuse("NFIR did not preserve every rule direction for the GPU graph kernel");
    }
    if (hasEnergyFactors && model.expanded_rules.size() < expectedRuleCount) {
        refuse("NFIR did not preserve every energy-expanded rule direction for the GPU graph kernel");
    }
    for (const auto& rule : model.expanded_rules) {
        for (const auto& action : rule.actions) {
            if (action.kind == nfnext::ActionKind::Create &&
                fixedTypes.count(action.molecule_type) == 0) {
                createdTypes.insert(action.molecule_type);
            }
        }
    }

    // Verify local-scope exactness: if any rule direction defines localScopes
    // (%x::A()), global observable evaluation equals complex-scoped local evaluation
    // iff every molecule type used in a localScope can have at most 1 live instance.
    std::set<std::uint32_t> localScopedTypes;
    for (const auto& rule : source.rules()) {
        auto checkDir = [&](const bng::compile::CompiledRuleDirection& dir) {
            for (const auto& scope : dir.localScopes) {
                if (scope.side == bng::compile::PatternSide::Reactant &&
                    scope.patternIndex < dir.reactantPatterns.size()) {
                    const auto& pat = dir.reactantPatterns[scope.patternIndex];
                    if (scope.moleculeOccurrence) {
                        if (*scope.moleculeOccurrence < pat.molecules().size() &&
                            pat.molecules()[*scope.moleculeOccurrence].moleculeTypeId) {
                            localScopedTypes.insert(static_cast<std::uint32_t>(
                                pat.molecules()[*scope.moleculeOccurrence]
                                    .moleculeTypeId->value()));
                        } else {
                            refuse(
                                "unresolved local scope is outside GPU graph kernel slice");
                        }
                    } else {
                        for (const auto& mol : pat.molecules()) {
                            if (!mol.moleculeTypeId) {
                                refuse(
                                    "unresolved local scope is outside GPU graph kernel slice");
                            }
                            localScopedTypes.insert(
                                static_cast<std::uint32_t>(mol.moleculeTypeId->value()));
                        }
                    }
                }
            }
        };
        checkDir(rule.forward());
        if (rule.reverse()) checkDir(*rule.reverse());
    }
    for (const auto scopedType : localScopedTypes) {
        if (initialTypeCounts.at(scopedType) > 1 || createdTypes.count(scopedType) != 0) {
            refuse("multi-copy local scoping is outside GPU graph kernel slice");
        }
    }

    // Partition molecule pool contiguously by molecule type so match lists only
    // allocate slots for their anchor molecule type.
    plan.typeOffsets.resize(plan.numTypes, 0);
    plan.typeCapacities.resize(plan.numTypes, 0);
    std::uint64_t totalInitial = 0;
    for (std::uint32_t t = 0; t < plan.numTypes; ++t) totalInitial += initialTypeCounts[t];
    if (totalInitial > maxParticles) {
        refuse("initial population exceeds max_particles budget");
    }
    const std::uint64_t headroomBudget =
        createdTypes.empty()
            ? 0
            : std::min<std::uint64_t>(
                  maxParticles - totalInitial,
                  static_cast<std::uint64_t>(createdTypes.size()) * 2048ULL);
    const std::uint64_t perCreatedHeadroom =
        createdTypes.empty() ? 0 : (headroomBudget / createdTypes.size());

    std::uint64_t runningOffset = 0;
    for (std::uint32_t t = 0; t < plan.numTypes; ++t) {
        plan.typeOffsets[t] = static_cast<std::uint32_t>(runningOffset);
        std::uint64_t cap = initialTypeCounts[t];
        if (createdTypes.count(t)) {
            cap += std::max<std::uint64_t>(perCreatedHeadroom, 64ULL);
        }
        if (cap == 0) cap = 1; // keep non-empty valid range
        runningOffset += cap;
        plan.typeCapacities[t] = static_cast<std::uint32_t>(cap);
    }
    constexpr std::uint64_t kMaxExactFloat = 1ULL << 24ULL;
    if (runningOffset > maxParticles && !createdTypes.empty()) {
        // Clamp headroom to stay within maxParticles.
        runningOffset = 0;
        for (std::uint32_t t = 0; t < plan.numTypes; ++t) {
            plan.typeOffsets[t] = static_cast<std::uint32_t>(runningOffset);
            std::uint64_t cap = initialTypeCounts[t];
            if (createdTypes.count(t)) cap += perCreatedHeadroom;
            if (cap == 0) cap = 1;
            runningOffset += cap;
            plan.typeCapacities[t] = static_cast<std::uint32_t>(cap);
        }
    }
    if (runningOffset > kMaxExactFloat ||
        runningOffset > std::numeric_limits<std::uint32_t>::max()) {
        refuse("total GPU molecule capacity exceeds exact float32 / uint32 kernel indexing");
    }
    plan.totalCapacity = static_cast<std::uint32_t>(runningOffset);

    // Populate initial particle arrays.
    plan.initAlive.assign(plan.totalCapacity, 0);
    plan.initMolType.assign(plan.totalCapacity, -1);
    plan.initSiteState.assign(
        static_cast<std::size_t>(plan.totalCapacity) * plan.maxSites, 0);
    plan.initSiteBondMol.assign(
        static_cast<std::size_t>(plan.totalCapacity) * plan.maxSites, -1);
    plan.initSiteBondSite.assign(
        static_cast<std::size_t>(plan.totalCapacity) * plan.maxSites, -1);

    std::vector<std::uint32_t> nextFreeSlot = plan.typeOffsets;
    for (const auto& cx : initComplexes) {
        for (std::uint32_t c = 0; c < cx.copies; ++c) {
            std::vector<std::uint32_t> assigned;
            assigned.reserve(cx.molTypes.size());
            for (std::size_t i = 0; i < cx.molTypes.size(); ++i) {
                const auto t = cx.molTypes[i];
                const auto slot = nextFreeSlot[t]++;
                plan.initAlive[slot] = 1;
                plan.initMolType[slot] = static_cast<std::int32_t>(t);
                for (std::uint32_t s = 0; s < plan.maxSites; ++s) {
                    plan.initSiteState[static_cast<std::size_t>(slot) * plan.maxSites + s] =
                        cx.siteStates[i][s];
                }
                assigned.push_back(slot);
            }
            for (const auto& [n0, s0, n1, s1] : cx.bonds) {
                const auto m0 = assigned[n0];
                const auto m1 = assigned[n1];
                plan.initSiteBondMol[static_cast<std::size_t>(m0) * plan.maxSites + s0] =
                    static_cast<std::int32_t>(m1);
                plan.initSiteBondSite[static_cast<std::size_t>(m0) * plan.maxSites + s0] =
                    static_cast<std::int32_t>(s1);
                plan.initSiteBondMol[static_cast<std::size_t>(m1) * plan.maxSites + s1] =
                    static_cast<std::int32_t>(m0);
                plan.initSiteBondSite[static_cast<std::size_t>(m1) * plan.maxSites + s1] =
                    static_cast<std::int32_t>(s0);
            }
        }
    }

    // Helper to append site constraints and deduplicate.
    auto appendConstraints = [&](const std::vector<CanonicalConstraintKey>& keys)
        -> std::pair<std::uint32_t, std::uint32_t> {
        const auto offset = static_cast<std::uint32_t>(plan.constraints.size());
        for (const auto& k : keys) {
            plan.constraints.push_back({k.site, k.kind, 0, k.state});
        }
        return {offset, static_cast<std::uint32_t>(keys.size())};
    };

    // Helper to expand a PatternIR (observable term or reactant filter pattern)
    // across same-name site permutations and append canonical GpuObsTermDef rows.
    auto appendPatternTerms = [&](const nfnext::PatternIR& basePat, bool isSpecies,
                                  std::uint32_t baseWeight) -> std::size_t {
        if (basePat.nodes.empty() || basePat.nodes.size() > detail::kGpuMaxObsPatternNodes ||
            basePat.bonds.size() > detail::kGpuMaxObsPatternBonds) {
            refuse("pattern node/bond count exceeds bounded GPU graph kernel capacity");
        }
        for (const auto& nd : basePat.nodes) {
            if (nd.compartment.has_value()) {
                refuse("compartmental pattern is outside the GPU graph kernel slice");
            }
        }
        if (!basePat.molecularity.empty() || !basePat.aliases.empty() ||
            !basePat.connected_to.empty()) {
            refuse("topological pattern constraints are outside the GPU graph kernel slice");
        }
        std::vector<std::vector<std::vector<std::uint16_t>>> nodePerms(basePat.nodes.size());
        for (std::size_t ni = 0; ni < basePat.nodes.size(); ++ni) {
            nodePerms[ni] = sitePermutationsForType(
                model.molecule_types.at(basePat.nodes[ni].molecule_type));
        }
        std::vector<std::size_t> idx(basePat.nodes.size(), 0);
        using ObsTermKey = std::tuple<
            std::vector<std::pair<std::int32_t, std::vector<CanonicalConstraintKey>>>,
            std::vector<std::tuple<std::uint16_t, std::uint16_t, std::uint16_t, std::uint16_t>>>;
        std::set<ObsTermKey> seenTerms;

        for (;;) {
            std::vector<std::pair<std::int32_t, std::vector<CanonicalConstraintKey>>> nodeKeys;
            nodeKeys.reserve(basePat.nodes.size());
            for (std::size_t ni = 0; ni < basePat.nodes.size(); ++ni) {
                nodeKeys.emplace_back(
                    static_cast<std::int32_t>(basePat.nodes[ni].molecule_type),
                    canonicalizeNodeConstraints(basePat.nodes[ni], nodePerms[ni][idx[ni]]));
            }
            std::vector<std::tuple<std::uint16_t, std::uint16_t, std::uint16_t, std::uint16_t>> bondKeys;
            bondKeys.reserve(basePat.bonds.size());
            for (const auto& b : basePat.bonds) {
                auto n0 = static_cast<std::uint16_t>(b.first);
                auto s0 = nodePerms[b.first][idx[b.first]][b.first_site];
                auto n1 = static_cast<std::uint16_t>(b.second);
                auto s1 = nodePerms[b.second][idx[b.second]][b.second_site];
                if (std::tie(n1, s1) < std::tie(n0, s0)) {
                    std::swap(n0, n1);
                    std::swap(s0, s1);
                }
                bondKeys.emplace_back(n0, s0, n1, s1);
            }
            std::vector<std::tuple<std::uint16_t, std::uint16_t, std::uint16_t, std::uint16_t>> canonBonds = bondKeys;
            if (basePat.nodes.size() >= 3) {
                bool tailIdentical = true;
                for (std::size_t ni = 2; ni < basePat.nodes.size(); ++ni) {
                    if (nodeKeys[ni] != nodeKeys[1]) {
                        tailIdentical = false;
                        break;
                    }
                }
                if (tailIdentical) {
                    bool allStarTo0 = true;
                    for (const auto& [n0, s0, n1, s1] : canonBonds) {
                        if (n0 != 0 || n1 == 0) {
                            allStarTo0 = false;
                            break;
                        }
                    }
                    if (allStarTo0) {
                        std::sort(canonBonds.begin(), canonBonds.end(),
                                  [](const auto& a, const auto& b) {
                                      return std::tie(std::get<1>(a), std::get<3>(a)) <
                                             std::tie(std::get<1>(b), std::get<3>(b));
                                  });
                        for (std::size_t bi = 0; bi < canonBonds.size(); ++bi) {
                            std::get<2>(canonBonds[bi]) = static_cast<std::uint16_t>(bi + 1);
                        }
                    }
                }
            }
            std::sort(canonBonds.begin(), canonBonds.end());
            ObsTermKey key{nodeKeys, canonBonds};
            if (seenTerms.insert(key).second) {
                detail::GpuObsTermDef tdef;
                tdef.nodeOffset = static_cast<std::uint32_t>(plan.obsNodes.size());
                tdef.nodeCount = static_cast<std::uint32_t>(nodeKeys.size());
                for (const auto& [mtype, ckeys] : nodeKeys) {
                    const auto [cOff, cCnt] = appendConstraints(ckeys);
                    plan.obsNodes.push_back({mtype, cOff, cCnt});
                }
                tdef.bondOffset = static_cast<std::uint32_t>(plan.obsBonds.size());
                tdef.bondCount = static_cast<std::uint32_t>(canonBonds.size());
                for (const auto& [n0, s0, n1, s1] : canonBonds) {
                    plan.obsBonds.push_back({n0, s0, n1, s1});
                }
                tdef.weight = baseWeight;
                plan.obsTerms.push_back(tdef);
            }

            std::size_t pos = basePat.nodes.size();
            while (pos > 0) {
                --pos;
                if (++idx[pos] < nodePerms[pos].size()) break;
                idx[pos] = 0;
                if (pos == 0) goto done_pat_perms;
            }
            if (basePat.nodes.empty()) break;
        }
    done_pat_perms:
        if (!isSpecies && seenTerms.size() > 1 && baseWeight > 1) {
            const std::size_t added = seenTerms.size();
            if (baseWeight % added == 0) {
                for (std::size_t k = plan.obsTerms.size() - added;
                     k < plan.obsTerms.size(); ++k) {
                    plan.obsTerms[k].weight =
                        static_cast<std::uint32_t>(baseWeight / added);
                }
            }
        }
        return seenTerms.size();
    };

    // Compile Observables first so dynamic rate laws can bind observable indices!
    std::unordered_map<nfnext::ObservableId, std::uint32_t> obsIdToGpuIndex;
    nfnext::FunctionEnvironment funcEnv;
    std::set<std::string> obsNames;
    for (std::size_t oi = 0; oi < source.observables().size(); ++oi) {
        const auto& obs = source.observables()[oi];
        if (obs.kind != bng::compile::ObservableKind::Molecules &&
            obs.kind != bng::compile::ObservableKind::Species) {
            refuse("only Molecules and Species observables are supported in GPU graph kernel");
        }
        if (obs.terms.empty() || !obsNames.insert(obs.name).second) {
            refuse("observables must be unique and non-empty in GPU graph kernel");
        }
        const auto obsId = static_cast<nfnext::ObservableId>(obs.id.value());
        obsIdToGpuIndex[obsId] = static_cast<std::uint32_t>(oi);
        funcEnv.addObservable("observable_" + std::to_string(obsId), 0.0, obsId);

        detail::GpuObsDef def;
        def.termOffset = static_cast<std::uint32_t>(plan.obsTerms.size());
        def.isSpecies = (obs.kind == bng::compile::ObservableKind::Species) ? 1 : 0;

        for (const auto& term : obs.terms) {
            if (!term.relation.empty()) {
                refuse("observable stoichiometry relations are outside GPU graph kernel");
            }
            const auto basePat = lowerObservablePatternToIr(term.pattern, model);
            const std::uint32_t baseWeight =
                def.isSpecies ? 1u : observableAutomorphismWeight(basePat, model);
            appendPatternTerms(basePat, def.isSpecies != 0, baseWeight);
        }
        def.termCount = static_cast<std::uint32_t>(plan.obsTerms.size()) - def.termOffset;
        plan.observables.push_back(def);
        plan.observableNames.push_back(obs.name);
    }

    // Deduplicated match-list registry.
    using MatchListKey = std::tuple<
        std::int32_t, std::int32_t, std::uint16_t, std::uint16_t,
        std::vector<CanonicalConstraintKey>, std::vector<CanonicalConstraintKey>>;
    std::map<MatchListKey, std::uint32_t> matchListIndex;
    auto internMatchList = [&](
        std::int32_t anchorType,
        std::int32_t partnerType,
        std::uint16_t bondSite0,
        std::uint16_t bondSite1,
        const std::vector<CanonicalConstraintKey>& c0,
        const std::vector<CanonicalConstraintKey>& c1) -> std::uint32_t {
        MatchListKey key{anchorType, partnerType, bondSite0, bondSite1, c0, c1};
        const auto it = matchListIndex.find(key);
        if (it != matchListIndex.end()) return it->second;
        const auto [off0, cnt0] = appendConstraints(c0);
        const auto [off1, cnt1] = appendConstraints(c1);
        const auto id = static_cast<std::uint32_t>(plan.matchLists.size());
        detail::GpuMatchListDef ml;
        ml.anchorType = anchorType;
        ml.partnerType = partnerType;
        ml.node0ConstraintOffset = off0;
        ml.node0ConstraintCount = cnt0;
        ml.node1ConstraintOffset = off1;
        ml.node1ConstraintCount = cnt1;
        ml.bondSite0 = bondSite0;
        ml.bondSite1 = bondSite1;
        ml.listOffset = plan.totalMatchListSlots;
        ml.listCapacity = plan.typeCapacities.at(static_cast<std::size_t>(anchorType));
        plan.totalMatchListSlots += ml.listCapacity;
        plan.matchLists.push_back(ml);
        matchListIndex.emplace(std::move(key), id);
        return id;
    };

    // Compile each expanded rule with canonical same-name site expansion.
    for (const auto& rule : model.expanded_rules) {
        if (rule.volume_factor != 1.0 || rule.match_once ||
            rule.move_connected ||
            !rule.pattern.aliases.empty() || !rule.pattern.connected_to.empty()) {
            refuse("rule modifiers/aliases are outside GPU graph kernel slice");
        }
        // Allow SameComplex when the two nodes are already directly bonded in the pattern;
        // allow DifferentComplex between 2 unbound reactant nodes (enforced in kernel).
        for (const auto& mc : rule.pattern.molecularity) {
            if (mc.kind == nfnext::MolecularityKind::SameComplex) {
                bool directlyBonded = false;
                for (const auto& b : rule.pattern.bonds) {
                    if ((b.first == mc.left && b.second == mc.right) ||
                        (b.first == mc.right && b.second == mc.left)) {
                        directlyBonded = true;
                        break;
                    }
                }
                if (!directlyBonded) {
                    refuse(
                        "unbonded SameComplex molecularity constraint is outside GPU graph kernel slice");
                }
            } else if (mc.kind != nfnext::MolecularityKind::DifferentComplex) {
                refuse("unsupported molecularity constraint in GPU graph kernel slice");
            }
        }
        const auto nNodes = rule.pattern.nodes.size();
        const auto nBonds = rule.pattern.bonds.size();
        if (nNodes == 0 || nNodes > 2 || nBonds > 1) {
            refuse("rule reactant pattern exceeds 1-2 node / 0-1 bond GPU graph kernel slice");
        }
        if (nNodes == 1 && nBonds != 0) {
            refuse("self-bonded single-node reactant is outside GPU graph kernel slice");
        }

        // Compile reactant include/exclude filters (exact Gillespie thinning on GPU).
        const auto ruleFilterOffset = static_cast<std::uint32_t>(plan.ruleFilters.size());
        if (!rule.filters.empty()) {
            if (rule.total_rate) {
                refuse("TotalRate combined with include/exclude filters is outside GPU graph kernel slice");
            }
            for (const auto& filter : rule.filters) {
                if (filter.products) {
                    refuse("product include/exclude filters are outside GPU graph kernel slice");
                }
                if (filter.reactant_node_offset >= nNodes) {
                    refuse("reactant filter node offset out of range in GPU graph kernel");
                }
                if (filter.patterns.empty()) {
                    refuse("empty include/exclude filter pattern in GPU graph kernel");
                }
                detail::GpuRuleFilter gf{};
                gf.termOffset = static_cast<std::uint32_t>(plan.obsTerms.size());
                gf.reactantNode = static_cast<std::uint16_t>(filter.reactant_node_offset);
                gf.include = filter.include ? 1u : 0u;
                for (const auto& fPat : filter.patterns) {
                    appendPatternTerms(fPat, false, 1u);
                }
                gf.termCount = static_cast<std::uint32_t>(plan.obsTerms.size()) - gf.termOffset;
                plan.ruleFilters.push_back(gf);
            }
        }
        const auto ruleFilterCount = static_cast<std::uint16_t>(
            plan.ruleFilters.size() - ruleFilterOffset);

        // Compile rate (static elementary or dynamic FunctionVM bytecode).
        bool isDynamic = false;
        float staticRate = 0.0f;
        std::uint32_t vmOffset = 0;
        std::uint32_t vmLen = 0;
        if (rule.rate_law.kind == nfnext::RateLawKind::Elementary) {
            if (!std::isfinite(rule.rate) || rule.rate < 0.0) {
                refuse("rule has invalid elementary rate");
            }
            staticRate = static_cast<float>(rule.rate);
            if (!std::isfinite(staticRate) || (rule.rate > 0.0 && staticRate == 0.0f)) {
                refuse("rule rate is not representable in float32");
            }
        } else if (rule.rate_law.kind == nfnext::RateLawKind::Function) {
            isDynamic = true;
            const auto compiledFn =
                nfnext::FunctionCompiler().compile(rule.rate_law.expression, funcEnv);
            const auto& bc = compiledFn.sharedCode()->code;
            vmOffset = static_cast<std::uint32_t>(plan.vmCode.size());
            using Op = nfnext::function_vm_detail::Op;
            for (const auto& ins : bc) {
                detail::GpuVmInstr g{};
                switch (ins.op) {
                case Op::Constant:
                    g.op = detail::kGpuVmConst;
                    g.value = static_cast<float>(ins.value);
                    break;
                case Op::Symbol: {
                    const auto* obsBind = funcEnv.observableBinding(ins.symbol);
                    if (!obsBind) {
                        refuse("unresolved symbol in GPU dynamic rate: " + ins.symbol);
                    }
                    g.op = detail::kGpuVmObservable;
                    g.index = obsIdToGpuIndex.at(obsBind->id);
                    break;
                }
                case Op::Add: g.op = detail::kGpuVmAdd; break;
                case Op::Subtract: g.op = detail::kGpuVmSub; break;
                case Op::Multiply: g.op = detail::kGpuVmMul; break;
                case Op::Divide: g.op = detail::kGpuVmDiv; break;
                case Op::Power: g.op = detail::kGpuVmPow; break;
                case Op::Negate: g.op = detail::kGpuVmNeg; break;
                case Op::Less: g.op = detail::kGpuVmLess; break;
                case Op::LessEqual: g.op = detail::kGpuVmLessEq; break;
                case Op::Greater: g.op = detail::kGpuVmGreater; break;
                case Op::GreaterEqual: g.op = detail::kGpuVmGreaterEq; break;
                case Op::Equal: g.op = detail::kGpuVmEqual; break;
                case Op::NotEqual: g.op = detail::kGpuVmNotEqual; break;
                case Op::JumpIfZero:
                    g.op = detail::kGpuVmJumpIfZero;
                    g.index = static_cast<std::uint32_t>(ins.jump_target);
                    break;
                case Op::Jump:
                    g.op = detail::kGpuVmJump;
                    g.index = static_cast<std::uint32_t>(ins.jump_target);
                    break;
                case Op::Function: {
                    static constexpr std::uint8_t kFnOps[10] = {
                        detail::kGpuVmExp, detail::kGpuVmLog, detail::kGpuVmSqrt,
                        detail::kGpuVmPow, detail::kGpuVmSin, detail::kGpuVmCos,
                        detail::kGpuVmTan, detail::kGpuVmAbs, detail::kGpuVmMin,
                        detail::kGpuVmMax,
                    };
                    if (ins.function >= 10) refuse("unsupported builtin in GPU VM");
                    g.op = kFnOps[ins.function];
                    break;
                }
                }
                plan.vmCode.push_back(g);
            }
            vmLen = static_cast<std::uint32_t>(plan.vmCode.size()) - vmOffset;
        } else {
            refuse("unsupported rule rate law in GPU graph kernel");
        }

        // Validate actions and map created logical nodes.
        std::map<std::uint32_t, std::uint32_t> createdNodeToSlot;
        std::set<std::uint32_t> skippedFixedCreatedNodes;
        std::uint32_t createdCount = 0;
        for (const auto& action : rule.actions) {
            if (action.kind == nfnext::ActionKind::Create) {
                if (fixedTypes.count(action.molecule_type) != 0) {
                    skippedFixedCreatedNodes.insert(action.target_node);
                } else if (createdNodeToSlot.find(action.target_node) == createdNodeToSlot.end()) {
                    createdNodeToSlot[action.target_node] =
                        static_cast<std::uint32_t>(nNodes) + createdCount++;
                }
            } else if (action.kind != nfnext::ActionKind::SetSiteState &&
                       action.kind != nfnext::ActionKind::Bind &&
                       action.kind != nfnext::ActionKind::Unbind &&
                       action.kind != nfnext::ActionKind::Destroy &&
                       action.kind != nfnext::ActionKind::DestroyComplex) {
                refuse("unsupported graph action kind in GPU graph kernel");
            }
        }
        if (createdCount > 2) {
            refuse("rule creates more than 2 molecules in GPU graph kernel");
        }

        // Expand same-name site permutations on reactant nodes, deduplicating
        // canonically by (node constraints, bond endpoints, action endpoints).
        std::vector<std::vector<std::vector<std::uint16_t>>> rPerms(nNodes);
        for (std::size_t ni = 0; ni < nNodes; ++ni) {
            rPerms[ni] = sitePermutationsForType(
                model.molecule_types.at(rule.pattern.nodes[ni].molecule_type));
        }

        using ActionKey = std::tuple<std::uint8_t, std::uint16_t, std::uint16_t,
                                     std::uint16_t, std::uint16_t, std::int32_t>;
        using RuleVariantKey = std::tuple<
            std::vector<std::vector<CanonicalConstraintKey>>,
            std::vector<std::tuple<std::uint16_t, std::uint16_t, std::uint16_t, std::uint16_t>>,
            std::vector<ActionKey>>;
        std::set<RuleVariantKey> seenVariants;

        const bool isInterchangeable =
            (nNodes == 2 && nBonds == 0 && !rule.pattern.interchangeable.empty());
        if (isInterchangeable && ruleFilterCount > 0u) {
            refuse("interchangeable reactants with include/exclude filters are outside GPU graph kernel slice");
        }
        if (rule.total_rate && nNodes == 2 && nBonds == 0 && !isInterchangeable &&
            rule.pattern.nodes[0].molecule_type == rule.pattern.nodes[1].molecule_type) {
            refuse("TotalRate on non-interchangeable same-type unbound reactants is outside GPU graph kernel slice");
        }

        const std::size_t rulesBeforeExpand = plan.rules.size();
        std::vector<std::size_t> idx(nNodes, 0);
        for (;;) {
            std::vector<std::vector<CanonicalConstraintKey>> nodeC(nNodes);
            for (std::size_t ni = 0; ni < nNodes; ++ni) {
                nodeC[ni] = canonicalizeNodeConstraints(
                    rule.pattern.nodes[ni], rPerms[ni][idx[ni]]);
            }
            std::vector<std::tuple<std::uint16_t, std::uint16_t, std::uint16_t, std::uint16_t>> bKeys;
            std::uint16_t bondSite0 = 0, bondSite1 = 0;
            if (nBonds == 1) {
                const auto& b = rule.pattern.bonds.front();
                const auto s0 = rPerms[b.first][idx[b.first]][b.first_site];
                const auto s1 = rPerms[b.second][idx[b.second]][b.second_site];
                if (b.first == 0 && b.second == 1) {
                    bondSite0 = s0;
                    bondSite1 = s1;
                } else {
                    bondSite0 = s1;
                    bondSite1 = s0;
                }
                bKeys.emplace_back(0, bondSite0, 1, bondSite1);
            }

            std::vector<detail::GpuRuleAction> gpuActs;
            std::vector<ActionKey> actKeys;
            for (const auto& action : rule.actions) {
                if (skippedFixedCreatedNodes.count(action.target_node) != 0) continue;
                auto mapNode = [&](std::uint32_t logical) -> std::uint16_t {
                    if (logical < nNodes) return static_cast<std::uint16_t>(logical);
                    return static_cast<std::uint16_t>(createdNodeToSlot.at(logical));
                };
                auto mapSite = [&](std::uint32_t logical, std::uint16_t site) -> std::uint16_t {
                    if (logical < nNodes) return rPerms[logical][idx[logical]][site];
                    return site;
                };
                detail::GpuRuleAction ga{};
                if (action.kind == nfnext::ActionKind::SetSiteState) {
                    ga.kind = detail::kGpuActionSetState;
                    ga.targetNode = mapNode(action.target_node);
                    ga.site = mapSite(action.target_node, action.site);
                    ga.value = action.value;
                } else if (action.kind == nfnext::ActionKind::Bind) {
                    ga.kind = detail::kGpuActionBind;
                    ga.targetNode = mapNode(action.target_node);
                    ga.site = mapSite(action.target_node, action.site);
                    ga.partnerNode = mapNode(action.partner_node);
                    ga.partnerSite = mapSite(action.partner_node, action.partner_site);
                } else if (action.kind == nfnext::ActionKind::Unbind) {
                    ga.kind = detail::kGpuActionUnbind;
                    ga.targetNode = mapNode(action.target_node);
                    ga.site = mapSite(action.target_node, action.site);
                    ga.partnerNode = mapNode(action.partner_node);
                    ga.partnerSite = mapSite(action.partner_node, action.partner_site);
                } else if (action.kind == nfnext::ActionKind::Create) {
                    ga.kind = detail::kGpuActionCreate;
                    ga.targetNode = mapNode(action.target_node);
                    ga.value = static_cast<std::int32_t>(action.molecule_type);
                } else if (action.kind == nfnext::ActionKind::Destroy) {
                    ga.kind = detail::kGpuActionDestroy;
                    ga.targetNode = mapNode(action.target_node);
                } else if (action.kind == nfnext::ActionKind::DestroyComplex) {
                    ga.kind = detail::kGpuActionDestroyComplex;
                    ga.targetNode = mapNode(action.target_node);
                }
                gpuActs.push_back(ga);
                actKeys.emplace_back(
                    ga.kind, ga.targetNode, ga.site, ga.partnerNode, ga.partnerSite, ga.value);
            }
            std::sort(actKeys.begin(), actKeys.end());
            RuleVariantKey vKey{nodeC, bKeys, actKeys};
            if (seenVariants.insert(vKey).second) {
                detail::GpuGraphRule gr{};
                gr.actionOffset = static_cast<std::uint32_t>(plan.actions.size());
                gr.actionCount = static_cast<std::uint32_t>(gpuActs.size());
                for (const auto& ga : gpuActs) plan.actions.push_back(ga);
                gr.vmOffset = vmOffset;
                gr.vmLen = vmLen;
                gr.rate = staticRate;
                gr.isDynamicRate = isDynamic ? 1 : 0;
                gr.createdCount = createdCount;
                gr.filterOffset = ruleFilterOffset;
                gr.filterCount = ruleFilterCount;
                gr.isTotalRate = rule.total_rate ? 1u : 0u;
                gr.pad0 = 0u;

                if (nNodes == 1) {
                    gr.isTwoComponent = 0;
                    gr.matchList0 = internMatchList(
                        static_cast<std::int32_t>(rule.pattern.nodes[0].molecule_type),
                        -1, 0, 0, nodeC[0], {});
                    gr.matchList1 = 0xFFFFFFFFu;
                } else if (nBonds == 1) {
                    gr.isTwoComponent = 0;
                    gr.matchList0 = internMatchList(
                        static_cast<std::int32_t>(rule.pattern.nodes[0].molecule_type),
                        static_cast<std::int32_t>(rule.pattern.nodes[1].molecule_type),
                        bondSite0, bondSite1, nodeC[0], nodeC[1]);
                    gr.matchList1 = 0xFFFFFFFFu;
                } else {
                    gr.isTwoComponent = 1;
                    gr.isInterchangeable = isInterchangeable ? 1 : 0;
                    gr.matchList0 = internMatchList(
                        static_cast<std::int32_t>(rule.pattern.nodes[0].molecule_type),
                        -1, 0, 0, nodeC[0], {});
                    gr.matchList1 = internMatchList(
                        static_cast<std::int32_t>(rule.pattern.nodes[1].molecule_type),
                        -1, 0, 0, nodeC[1], {});
                }
                plan.rules.push_back(gr);
            }

            std::size_t pos = nNodes;
            while (pos > 0) {
                --pos;
                if (++idx[pos] < rPerms[pos].size()) break;
                idx[pos] = 0;
                if (pos == 0) goto done_rule_perms;
            }
        }
    done_rule_perms:
        if (rule.total_rate && (plan.rules.size() - rulesBeforeExpand) != 1) {
            refuse("TotalRate on multivalent site-expanded rule is outside GPU graph kernel slice");
        }
    }

    if (plan.rules.size() > 256 || plan.matchLists.size() > 256) {
        refuse("expanded GPU graph rule/match-list count exceeds bounded kernel limit");
    }
    return plan;
}

} // namespace

NfnextGpuResult simulateNfnextGpu(const bng::compile::CompiledModel& source,
                                  const NfnextGpuRequest& request) {
    if (request.mode != "unary" && request.mode != "graph") {
        refuse("mode must explicitly select 'unary' or 'graph'");
    }
    if (request.sampleTimes.empty()) refuse("sample_times must not be empty");
    double previous = -1.0;
    for (const double time : request.sampleTimes) {
        if (!std::isfinite(time) || time < 0.0 || time <= previous)
            refuse("sample_times must be finite, nonnegative, and strictly increasing");
        if (request.mode == "unary") {
            const float deviceTime = static_cast<float>(time);
            if (!std::isfinite(deviceTime) || static_cast<double>(deviceTime) != time)
                refuse("sample_times must be exactly representable as finite GPU single precision");
        }
        previous = time;
    }
    if (request.batchSize == 0 || request.batchSize > std::numeric_limits<std::uint32_t>::max())
        refuse("batch_size must fit the positive native GPU trajectory range");
    if (request.maxEvents == 0 || request.maxEvents > std::numeric_limits<std::uint32_t>::max())
        refuse("max_events must fit the positive native GPU event range");
    if (request.maxParticles > std::numeric_limits<std::uint32_t>::max())
        refuse("max_particles exceeds native GPU particle indexing");

    if (request.mode == "graph") {
        const auto plan = compileGraphPlan(source, request.maxParticles);
        const auto expectedValues = checkedProduct(
            checkedProduct(request.batchSize, request.sampleTimes.size()),
            plan.observableNames.size());
        if (expectedValues > std::numeric_limits<std::uint32_t>::max())
            refuse("batch output element count exceeds GPU kernel indexing capacity");
        if (request.backend != "metal" && request.backend != "cuda") {
            refuse("backend must explicitly select 'metal' or 'cuda'");
        }
        const GpuBackendKind targetKind =
            request.backend == "cuda" ? GpuBackendKind::Cuda : GpuBackendKind::Metal;
        const auto inventory = gpuBackendInventory();
        const auto backend = std::find_if(inventory.begin(), inventory.end(), [targetKind](const auto& item) {
            return item.kind == targetKind;
        });
        if (request.backend == "cuda") {
            if (backend == inventory.end() || !backend->compiled)
                refuse("CUDA backend is not compiled into this build");
            if (!backend->available)
                refuse("CUDA backend has no usable device: " + backend->detail);
#ifdef BNG3_HAS_CUDA
            const auto output = detail::simulateNfnextGraphCuda(plan, request);
            NfnextGpuResult result;
            result.sampleTimes = request.sampleTimes;
            result.observableNames = plan.observableNames;
            result.observables = output.observables;
            result.eventCounts = output.eventCounts;
            result.batchSize = request.batchSize;
            result.backend = "cuda";
            result.device = output.device;
            result.wallTimeMs = output.wallTimeMs;
            result.dispatchWaitTimeMs = output.dispatchWaitTimeMs;
            result.setupTimeMs = output.setupTimeMs;
            result.deviceMemoryBytes = output.deviceMemoryBytes;
            if (result.observables.size() != expectedValues ||
                result.eventCounts.size() != request.batchSize) {
                refuse("CUDA graph kernel returned output with an invalid batch shape");
            }
            return result;
#else
            refuse("CUDA backend is not compiled into this build");
#endif
        }
        if (backend == inventory.end() || !backend->compiled)
            refuse("Metal backend is not compiled into this build");
        if (!backend->available)
            refuse("Metal backend has no usable device: " + backend->detail);
#ifdef BNG3_HAS_METAL
        const auto output = detail::simulateNfnextGraphMetal(plan, request);
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
        result.setupTimeMs = output.setupTimeMs;
        result.deviceMemoryBytes = output.deviceMemoryBytes;
        if (result.observables.size() != expectedValues ||
            result.eventCounts.size() != request.batchSize) {
            refuse("Metal graph kernel returned output with an invalid batch shape");
        }
        return result;
#else
        refuse("Metal backend is not compiled into this build");
#endif
    }

    const auto plan = compileUnaryStatePlan(source, request.maxParticles);
    const auto expectedValues = checkedProduct(
        checkedProduct(request.batchSize, request.sampleTimes.size()),
        plan.observableNames.size());
    if (expectedValues > std::numeric_limits<std::uint32_t>::max())
        refuse("batch output element count exceeds GPU kernel indexing capacity");
    if (request.backend != "metal" && request.backend != "cuda") {
        refuse("backend must explicitly select 'metal' or 'cuda'");
    }

    const GpuBackendKind targetKind =
        request.backend == "cuda" ? GpuBackendKind::Cuda : GpuBackendKind::Metal;
    const auto inventory = gpuBackendInventory();
    const auto backend = std::find_if(inventory.begin(), inventory.end(), [targetKind](const auto& item) {
        return item.kind == targetKind;
    });
    if (request.backend == "cuda") {
        if (backend == inventory.end() || !backend->compiled)
            refuse("CUDA backend is not compiled into this build");
        if (!backend->available)
            refuse("CUDA backend has no usable device: " + backend->detail);
#ifdef BNG3_HAS_CUDA
        const auto output = detail::simulateNfnextUnaryStateCuda(plan, request);
        NfnextGpuResult result;
        result.sampleTimes = request.sampleTimes;
        result.observableNames = plan.observableNames;
        result.observables = output.observables;
        result.eventCounts = output.eventCounts;
        result.batchSize = request.batchSize;
        result.backend = "cuda";
        result.device = output.device;
        result.wallTimeMs = output.wallTimeMs;
        result.dispatchWaitTimeMs = output.dispatchWaitTimeMs;
        result.setupTimeMs = output.setupTimeMs;
        result.deviceMemoryBytes = output.deviceMemoryBytes;
        if (result.observables.size() != expectedValues ||
            result.eventCounts.size() != request.batchSize) {
            refuse("CUDA kernel returned output with an invalid batch shape");
        }
        return result;
#else
        refuse("CUDA backend is not compiled into this build");
#endif
    }

    if (backend == inventory.end() || !backend->compiled)
        refuse("Metal backend is not compiled into this build");
    if (!backend->available)
        refuse("Metal backend has no usable device: " + backend->detail);

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
    result.setupTimeMs = output.setupTimeMs;
    result.deviceMemoryBytes = output.deviceMemoryBytes;
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
