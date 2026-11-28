/*
 * energyPattern.cpp
 *
 * Implementation of the Sekar energy rule expansion algorithm.
 *
 * The expansion works by:
 * 1. Identifying energy patterns that overlap with the reaction center
 *    (Corollary 3.3-43: only these contribute to ΔG)
 * 2. Enumerating distinct center embeddings of each relevant pattern and
 *    extracting their context conditions (bond, state, unbound, partner-state)
 * 3. Enumerating all mutually consistent combinations of context conditions
 * 4. Evaluating ΔG via conjunction (AND) of all conditions per embedding
 * 5. Producing conventional rules with exact Arrhenius rates and constraints
 */

#include "energyPattern.hh"
#include "NFcore.hh"
#include <iostream>
#include <sstream>
#include <algorithm>
#include <utility>
#include <map>
#include <set>

using namespace NFcore;
using namespace std;

namespace {

struct ConditionKey {
    int reactantIdx = 0;
    int kind = 0; // 0=Bond, 1=State, 2=Unbound
    std::string molType;
    std::string compName;
    std::string stateValue;
    std::string partnerType;
    std::string partnerComp;
    std::vector<std::pair<std::string, std::string>> partnerStates;

    bool operator<(const ConditionKey &o) const {
        return std::tie(reactantIdx, kind, molType, compName, stateValue,
                        partnerType, partnerComp, partnerStates) <
               std::tie(o.reactantIdx, o.kind, o.molType, o.compName, o.stateValue,
                        o.partnerType, o.partnerComp, o.partnerStates);
    }
    bool operator==(const ConditionKey &o) const {
        return std::tie(reactantIdx, kind, molType, compName, stateValue,
                        partnerType, partnerComp, partnerStates) ==
               std::tie(o.reactantIdx, o.kind, o.molType, o.compName, o.stateValue,
                        o.partnerType, o.partnerComp, o.partnerStates);
    }
};

ConditionKey makeConditionKey(const ContextCondition &cc) {
    ConditionKey key;
    key.reactantIdx = cc.reactantIdx;
    key.kind = static_cast<int>(cc.kind);
    key.molType = cc.molType;
    key.compName = cc.compName;
    key.stateValue = cc.stateValue;
    key.partnerType = cc.partnerType;
    key.partnerComp = cc.partnerComp;
    key.partnerStates = cc.partnerStates;
    std::sort(key.partnerStates.begin(), key.partnerStates.end());
    return key;
}

struct CenterEmbedding {
    int patternIndex = -1;
    double sign = 1.0; // +1.0 formed/gained, -1.0 broken/lost
    std::vector<ContextCondition> rawConditions;
    std::uint64_t requiredMask = 0;
};

// Extract all context conditions on a single molecule `mi` in `ep`, skipping
// component index `centerCompIdx` (which is the reaction center on `mi`),
// and optionally skipping a specific bond to `otherCenterMolIdx`.
void extractMoleculeContextConditions(
    const EnergyPatternInfo &ep,
    int mi,
    int reactantIdx,
    int centerCompIdx,
    int otherCenterMolIdx,
    std::vector<ContextCondition> &out) {
    const EpMolecule &mol = ep.molecules[static_cast<std::size_t>(mi)];
    for (int ci = 0; ci < static_cast<int>(mol.components.size()); ++ci) {
        if (ci == centerCompIdx) continue;
        const auto &comp = mol.components[static_cast<std::size_t>(ci)];

        if (!comp.stateConstraint.empty()) {
            ContextCondition sc;
            sc.kind = ContextCondition::Kind::State;
            sc.molType = mol.typeName;
            sc.reactantIdx = reactantIdx;
            sc.compName = comp.name;
            sc.stateValue = comp.stateConstraint;
            out.push_back(std::move(sc));
        }

        if (comp.isBound) {
            ContextCondition bc;
            bc.kind = ContextCondition::Kind::Bond;
            bc.molType = mol.typeName;
            bc.reactantIdx = reactantIdx;
            bc.compName = comp.name;

            if (!comp.isWildcardBound) {
                int partnerMolIdx = -1;
                int partnerCompIdx = -1;
                for (const auto &bond : ep.bonds) {
                    if (bond.mol1 == mi && bond.comp1 == ci) {
                        partnerMolIdx = bond.mol2;
                        partnerCompIdx = bond.comp2;
                        break;
                    }
                    if (bond.mol2 == mi && bond.comp2 == ci) {
                        partnerMolIdx = bond.mol1;
                        partnerCompIdx = bond.comp1;
                        break;
                    }
                }
                if (partnerMolIdx >= 0 && partnerMolIdx != otherCenterMolIdx &&
                    static_cast<std::size_t>(partnerMolIdx) < ep.molecules.size()) {
                    const auto &partnerMol = ep.molecules[static_cast<std::size_t>(partnerMolIdx)];
                    bc.partnerType = partnerMol.typeName;
                    if (partnerCompIdx >= 0 &&
                        static_cast<std::size_t>(partnerCompIdx) < partnerMol.components.size()) {
                        bc.partnerComp = partnerMol.components[static_cast<std::size_t>(partnerCompIdx)].name;
                    }
                    for (const auto &pComp : partnerMol.components) {
                        if (!pComp.stateConstraint.empty()) {
                            bc.partnerStates.emplace_back(pComp.name, pComp.stateConstraint);
                        }
                    }
                    std::sort(bc.partnerStates.begin(), bc.partnerStates.end());
                } else if (partnerMolIdx == otherCenterMolIdx) {
                    // Bond connects the two reaction-center molecules directly; skip here.
                    continue;
                }
            }
            out.push_back(std::move(bc));
        } else if (comp.isUnbound) {
            ContextCondition uc;
            uc.kind = ContextCondition::Kind::Unbound;
            uc.molType = mol.typeName;
            uc.reactantIdx = reactantIdx;
            uc.compName = comp.name;
            out.push_back(std::move(uc));
        }
    }
}

// Check if `sub` partnerStates is a subset of `sup` partnerStates.
bool isPartnerStateSubset(
    const std::vector<std::pair<std::string, std::string>> &sub,
    const std::vector<std::pair<std::string, std::string>> &sup) {
    for (const auto &kv : sub) {
        if (std::find(sup.begin(), sup.end(), kv) == sup.end()) return false;
    }
    return true;
}

// Return true if bitmask `combo` assigns mutually contradictory values to
// `conditions` (e.g., two different required states on the same component,
// two different specific bond partners on the same site, bound + unbound, etc.).
bool isComboContradictory(std::uint64_t combo, const std::vector<ContextCondition> &conditions) {
    const int n = static_cast<int>(conditions.size());
    for (int i = 0; i < n; ++i) {
        const bool metI = ((combo >> i) & std::uint64_t{1}) != 0;
        const auto &ci = conditions[static_cast<std::size_t>(i)];
        for (int j = i + 1; j < n; ++j) {
            const auto &cj = conditions[static_cast<std::size_t>(j)];
            if (ci.reactantIdx != cj.reactantIdx || ci.compName != cj.compName) continue;
            const bool metJ = ((combo >> j) & std::uint64_t{1}) != 0;

            // Both are State conditions on the same component
            if (ci.kind == ContextCondition::Kind::State &&
                cj.kind == ContextCondition::Kind::State) {
                if (metI && metJ && ci.stateValue != cj.stateValue) return true;
                if (metI != metJ && ci.stateValue == cj.stateValue) return true;
            }

            // Bond vs Unbound on the same site
            if (ci.kind == ContextCondition::Kind::Bond &&
                cj.kind == ContextCondition::Kind::Unbound) {
                if (metI && metJ) return true; // must be bound AND must be unbound
                if (!metI && ci.partnerType.empty() && !metJ) return true; // wildcard empty AND not unbound
            }
            if (ci.kind == ContextCondition::Kind::Unbound &&
                cj.kind == ContextCondition::Kind::Bond) {
                if (metI && metJ) return true;
                if (!metJ && cj.partnerType.empty() && !metI) return true;
            }

            // Both are Bond conditions on the same site
            if (ci.kind == ContextCondition::Kind::Bond &&
                cj.kind == ContextCondition::Kind::Bond) {
                const bool wildI = ci.partnerType.empty();
                const bool wildJ = cj.partnerType.empty();
                // Wildcard false => site must be empty => incompatible with any active bond
                if (wildI && !metI && metJ) return true;
                if (wildJ && !metJ && metI) return true;

                // Two active specific bonds on the same site must agree on partner & states
                if (!wildI && !wildJ && metI && metJ) {
                    if (ci.partnerType != cj.partnerType || ci.partnerComp != cj.partnerComp)
                        return true;
                    for (const auto &psI : ci.partnerStates) {
                        for (const auto &psJ : cj.partnerStates) {
                            if (psI.first == psJ.first && psI.second != psJ.second)
                                return true;
                        }
                    }
                }

                // Active stronger specific bond implies weaker bond on same partner cannot be false
                if (!wildI && !wildJ && ci.partnerType == cj.partnerType &&
                    ci.partnerComp == cj.partnerComp) {
                    if (metI && !metJ && isPartnerStateSubset(cj.partnerStates, ci.partnerStates))
                        return true;
                    if (metJ && !metI && isPartnerStateSubset(ci.partnerStates, cj.partnerStates))
                        return true;
                }
            }
        }
    }
    return false;
}

std::vector<ExpandedRuleInfo::ContextConstraint> buildConstraintsForCombo(
    std::uint64_t combo,
    const std::vector<ContextCondition> &conditions) {
    std::vector<ExpandedRuleInfo::ContextConstraint> constraints;
    constraints.reserve(conditions.size());
    for (std::size_t ci = 0; ci < conditions.size(); ++ci) {
        const bool conditionMet = ((combo >> ci) & std::uint64_t{1}) != 0;
        const auto &cond = conditions[ci];
        ExpandedRuleInfo::ContextConstraint cc;
        cc.reactantIdx = cond.reactantIdx;
        cc.compName = cond.compName;
        cc.mustBeBound = conditionMet;
        cc.kind = cond.kind;
        cc.stateValue = cond.stateValue;
        cc.partnerType = cond.partnerType;
        cc.partnerComp = cond.partnerComp;
        cc.partnerStates = cond.partnerStates;
        constraints.push_back(std::move(cc));
    }
    return constraints;
}

} // namespace

EnergyFunction::EnergyFunction(double phi, double RT) : phi(phi), RT(RT) {}
EnergyFunction::~EnergyFunction() {}

void EnergyFunction::addEnergyPattern(const EnergyPatternInfo &ep) {
    const int patternIndex = static_cast<int>(patterns.size());
    patterns.push_back(ep);

    // Build compile-time inverted indexes once.
    std::set<BindingPatternKey> bindingKeys;
    for (const auto &bond : ep.bonds) {
        if (bond.mol1 < 0 || bond.mol2 < 0 || bond.comp1 < 0 || bond.comp2 < 0 ||
            static_cast<std::size_t>(bond.mol1) >= ep.molecules.size() ||
            static_cast<std::size_t>(bond.mol2) >= ep.molecules.size()) {
            continue;
        }
        const auto &molecule1 = ep.molecules[static_cast<std::size_t>(bond.mol1)];
        const auto &molecule2 = ep.molecules[static_cast<std::size_t>(bond.mol2)];
        if (static_cast<std::size_t>(bond.comp1) >= molecule1.components.size() ||
            static_cast<std::size_t>(bond.comp2) >= molecule2.components.size()) {
            continue;
        }

        std::pair<std::string, std::string> endpoint1 {
            molecule1.typeName, molecule1.components[static_cast<std::size_t>(bond.comp1)].name};
        std::pair<std::string, std::string> endpoint2 {
            molecule2.typeName, molecule2.components[static_cast<std::size_t>(bond.comp2)].name};
        if (endpoint2 < endpoint1) std::swap(endpoint1, endpoint2);
        bindingKeys.emplace(
            endpoint1.first, endpoint1.second, endpoint2.first, endpoint2.second);
    }
    for (const auto &key : bindingKeys)
        bindingPatternIndex[key].push_back(patternIndex);

    // Index wildcard-bound (!+) and explicitly unbound (A(b)) sites for binding rules.
    std::set<StatePatternKey> siteBondKeys;
    std::set<StatePatternKey> stateKeys;
    for (const auto &molecule : ep.molecules) {
        for (const auto &component : molecule.components) {
            if (component.isWildcardBound || component.isUnbound) {
                siteBondKeys.emplace(molecule.typeName, component.name);
            }
            if (!component.stateConstraint.empty()) {
                stateKeys.emplace(molecule.typeName, component.name);
            }
        }
    }
    for (const auto &key : siteBondKeys)
        siteBondPatternIndex[key].push_back(patternIndex);
    for (const auto &key : stateKeys)
        statePatternIndex[key].push_back(patternIndex);
}

void EnergyFunction::updateEnergiesFromSystem(const System *s) {
    if (s == nullptr) return;
    const auto &params = s->getParameterMap();
    for (auto &ep : patterns) {
        if (ep.energyEvaluator) {
            const double val = ep.energyEvaluator(params);
            if (std::isfinite(val)) {
                ep.energyValue = val;
            }
        }
    }
}

double EnergyFunction::barrierForBinding(
    const string &molType1, const string &bindSite1,
    const string &molType2, const string &bindSite2
) const {
    if (barrierTable.empty()) return 0.0;
    return barrierTable.lookup(bng::compile::energy::ReactionCenterKey::binding(
        molType1, bindSite1, molType2, bindSite2));
}

double EnergyFunction::barrierForStateChange(
    const string &molType, const string &comp,
    const string &stateFrom, const string &stateTo
) const {
    if (barrierTable.empty()) return 0.0;
    return barrierTable.lookup(bng::compile::energy::ReactionCenterKey::stateChange(
        molType, comp, stateFrom, stateTo));
}

bng::compile::energy::EnergyDeltaPlan EnergyFunction::compileBindingDeltaPlan(
    const string &molType1, const string &bindSite1,
    const string &molType2, const string &bindSite2
) const {
    using bng::compile::energy::ConditionKind;
    using bng::compile::energy::EnergyCondition;
    using bng::compile::energy::EnergyDeltaPlan;
    using bng::compile::energy::EnergyTerm;

    if (molType1 == molType2) return EnergyDeltaPlan::materializedFallback();

    const vector<int> relevant = findRelevantPatternsForBinding(
        molType1, bindSite1, molType2, bindSite2);
    if (relevant.empty()) return EnergyDeltaPlan::constant(0.0);

    vector<int> alwaysPatterns;
    vector<int> conditionalPatterns;

    for (int pi : relevant) {
        const EnergyPatternInfo &ep = patterns[static_cast<std::size_t>(pi)];
        bool hasExtraContext = false;
        int weightedMoleculeCount = 0;

        // Compact EnergyRxnClass only handles explicit-bond patterns without
        // unbound/wildcard/state/partner-state conditions.
        bool hasExplicitCenterBond = false;
        for (const auto &bond : ep.bonds) {
            if (bond.mol1 < 0 || bond.mol2 < 0 ||
                static_cast<std::size_t>(bond.mol1) >= ep.molecules.size() ||
                static_cast<std::size_t>(bond.mol2) >= ep.molecules.size()) continue;
            const auto &m1 = ep.molecules[static_cast<std::size_t>(bond.mol1)];
            const auto &m2 = ep.molecules[static_cast<std::size_t>(bond.mol2)];
            if (static_cast<std::size_t>(bond.comp1) >= m1.components.size() ||
                static_cast<std::size_t>(bond.comp2) >= m2.components.size()) continue;
            const auto &c1 = m1.components[static_cast<std::size_t>(bond.comp1)];
            const auto &c2 = m2.components[static_cast<std::size_t>(bond.comp2)];
            if ((m1.typeName == molType1 && c1.name == bindSite1 &&
                 m2.typeName == molType2 && c2.name == bindSite2) ||
                (m2.typeName == molType1 && c2.name == bindSite1 &&
                 m1.typeName == molType2 && c1.name == bindSite2)) {
                hasExplicitCenterBond = true;
                break;
            }
        }
        if (!hasExplicitCenterBond) {
            return EnergyDeltaPlan::materializedFallback();
        }

        for (const auto &mol : ep.molecules) {
            if (mol.typeName == molType1) ++weightedMoleculeCount;
            const bool isReactantType =
                mol.typeName == molType1 || mol.typeName == molType2;
            if (!isReactantType) {
                hasExtraContext = true;
                // Partner state constraints require materialized template matching.
                for (const auto &comp : mol.components) {
                    if (!comp.stateConstraint.empty())
                        return EnergyDeltaPlan::materializedFallback();
                }
                continue;
            }
            for (const auto &comp : mol.components) {
                if (mol.typeName == molType1 && comp.name == bindSite1) continue;
                if (mol.typeName == molType2 && comp.name == bindSite2) continue;
                if (!comp.stateConstraint.empty() || comp.isUnbound || comp.isWildcardBound) {
                    return EnergyDeltaPlan::materializedFallback();
                }
                if (comp.isBound) {
                    hasExtraContext = true;
                }
            }
        }

        if (weightedMoleculeCount != 1)
            return EnergyDeltaPlan::materializedFallback();

        if (hasExtraContext) conditionalPatterns.push_back(pi);
        else alwaysPatterns.push_back(pi);
    }

    double baseEnergy = 0.0;
    for (int pi : alwaysPatterns) baseEnergy += patterns[static_cast<std::size_t>(pi)].energyValue;
    if (conditionalPatterns.empty()) return EnergyDeltaPlan::constant(baseEnergy);

    const auto legacyConditions = extractContextConditions(
        conditionalPatterns, molType1, bindSite1, molType2, bindSite2);
    if (legacyConditions.empty() || legacyConditions.size() >= 64)
        return EnergyDeltaPlan::materializedFallback();

    // Ensure no two conditions share the same component with different partners
    // (multiple competing partners on one site are handled by materialized fallback).
    std::set<std::pair<int, std::string>> seenSite;
    vector<EnergyCondition> conditions;
    conditions.reserve(legacyConditions.size());
    for (const auto &legacy : legacyConditions) {
        if (legacy.kind != ContextCondition::Kind::Bond || !legacy.partnerStates.empty())
            return EnergyDeltaPlan::materializedFallback();
        if (!seenSite.emplace(legacy.reactantIdx, legacy.compName).second)
            return EnergyDeltaPlan::materializedFallback();

        EnergyCondition condition;
        condition.kind = ConditionKind::Bond;
        condition.reactantIndex = legacy.reactantIdx;
        condition.moleculeType = legacy.molType;
        condition.componentName = legacy.compName;
        condition.expectedBound = true;
        condition.partnerType = legacy.partnerType;
        condition.partnerComponent = legacy.partnerComp;
        for (int factorIndex : legacy.gatedPatternIndices) {
            if (factorIndex >= 0)
                condition.sourceFactorIndices.push_back(
                    static_cast<std::size_t>(factorIndex));
        }
        conditions.push_back(std::move(condition));
    }

    vector<EnergyTerm> terms;
    terms.reserve(conditionalPatterns.size());
    for (int pi : conditionalPatterns) {
        std::uint64_t conditionMask = 0;
        for (std::size_t ci = 0; ci < legacyConditions.size(); ++ci) {
            const auto &gated = legacyConditions[ci].gatedPatternIndices;
            if (find(gated.begin(), gated.end(), pi) != gated.end())
                conditionMask |= (std::uint64_t{1} << ci);
        }
        if (conditionMask == 0)
            return EnergyDeltaPlan::materializedFallback();

        EnergyTerm term;
        term.energyValue = patterns[static_cast<std::size_t>(pi)].energyValue;
        term.conditionMask = conditionMask;
        term.sourceFactorIndex = static_cast<std::size_t>(pi);
        terms.push_back(term);
    }

    auto plan = EnergyDeltaPlan::factorized(
        baseEnergy, std::move(conditions), std::move(terms));
    return plan.has_value() ? std::move(*plan)
                            : EnergyDeltaPlan::materializedFallback();
}

bool EnergyFunction::getBindingContext(
    const string &molType1, const string &bindSite1,
    const string &molType2, const string &bindSite2,
    EnergyBindingContext &context
) const {
    context.baseEnergy = 0.0;
    context.conditions.clear();
    context.conditionalTerms.clear();
    context.basePatternIndices.clear();

    const auto plan = compileBindingDeltaPlan(
        molType1, bindSite1, molType2, bindSite2);
    if (!plan.isFactorized()) return false;

    context.baseEnergy = plan.baseEnergy();
    context.conditions.reserve(plan.conditions().size());
    for (const auto &condition : plan.conditions()) {
        ContextCondition legacy;
        legacy.kind = ContextCondition::Kind::Bond;
        legacy.molType = condition.moleculeType;
        legacy.reactantIdx = condition.reactantIndex;
        legacy.compName = condition.componentName;
        legacy.partnerType = condition.partnerType;
        legacy.partnerComp = condition.partnerComponent;
        for (std::size_t factorIndex : condition.sourceFactorIndices)
            legacy.gatedPatternIndices.push_back(static_cast<int>(factorIndex));
        context.conditions.push_back(std::move(legacy));
    }

    // Track which relevant patterns are conditional vs base (always) so
    // EnergyRxnClass can refresh energies live under RNF set/update.
    std::set<int> conditionalSet;
    context.conditionalTerms.reserve(plan.terms().size());
    for (const auto &term : plan.terms()) {
        const int srcIdx = static_cast<int>(term.sourceFactorIndex);
        conditionalSet.insert(srcIdx);
        EnergyPatternTerm et;
        et.energyValue = term.energyValue;
        et.conditionMask = term.conditionMask;
        et.sourcePatternIndex = srcIdx;
        context.conditionalTerms.push_back(et);
    }
    const vector<int> relevant = findRelevantPatternsForBinding(
        molType1, bindSite1, molType2, bindSite2);
    for (int pi : relevant) {
        if (conditionalSet.count(pi) == 0) {
            context.basePatternIndices.push_back(pi);
        }
    }
    return true;
}

bng::compile::energy::EnergyDeltaPlan EnergyFunction::compileStateChangeDeltaPlan(
    const string &molType, const string &comp,
    const string &stateFrom, const string &stateTo
) const {
    using bng::compile::energy::ConditionKind;
    using bng::compile::energy::EnergyCondition;
    using bng::compile::energy::EnergyDeltaPlan;
    using bng::compile::energy::EnergyTerm;

    const vector<int> relevant = findRelevantPatternsForStateChange(molType, comp);
    if (relevant.empty()) return EnergyDeltaPlan::constant(0.0);

    vector<int> alwaysPatterns;
    vector<int> conditionalPatterns;
    auto signedCenterEnergy = [&](int patternIndex, double &contribution) -> bool {
        const auto &ep = patterns[static_cast<std::size_t>(patternIndex)];
        int centerCount = 0;
        contribution = 0.0;
        for (const auto &mol : ep.molecules) {
            if (mol.typeName != molType) continue;
            for (const auto &component : mol.components) {
                if (component.name != comp || component.stateConstraint.empty()) continue;
                ++centerCount;
                if (component.stateConstraint == stateTo)
                    contribution += ep.energyValue;
                else if (component.stateConstraint == stateFrom)
                    contribution -= ep.energyValue;
            }
        }
        return centerCount == 1;
    };

    for (int pi : relevant) {
        const auto &ep = patterns[static_cast<std::size_t>(pi)];
        bool hasExtraContext = false;
        int weightedMoleculeCount = 0;
        for (const auto &mol : ep.molecules) {
            if (mol.typeName == molType) ++weightedMoleculeCount;
            if (mol.typeName != molType) {
                hasExtraContext = true;
                for (const auto &c : mol.components) {
                    if (!c.stateConstraint.empty())
                        return EnergyDeltaPlan::materializedFallback();
                }
                continue;
            }
            for (const auto &component : mol.components) {
                if (component.name == comp) continue;
                if (!component.stateConstraint.empty() || component.isUnbound || component.isWildcardBound) {
                    return EnergyDeltaPlan::materializedFallback();
                }
                if (component.isBound) {
                    hasExtraContext = true;
                }
            }
        }
        if (weightedMoleculeCount != 1)
            return EnergyDeltaPlan::materializedFallback();

        double ignored = 0.0;
        if (!signedCenterEnergy(pi, ignored))
            return EnergyDeltaPlan::materializedFallback();

        if (hasExtraContext) conditionalPatterns.push_back(pi);
        else alwaysPatterns.push_back(pi);
    }

    double baseEnergy = 0.0;
    for (int pi : alwaysPatterns) {
        double contribution = 0.0;
        if (!signedCenterEnergy(pi, contribution))
            return EnergyDeltaPlan::materializedFallback();
        baseEnergy += contribution;
    }
    if (conditionalPatterns.empty()) return EnergyDeltaPlan::constant(baseEnergy);

    const auto legacyConditions = extractContextConditions(
        conditionalPatterns, molType, comp, "", "");
    if (legacyConditions.empty() || legacyConditions.size() >= 64)
        return EnergyDeltaPlan::materializedFallback();

    vector<EnergyCondition> conditions;
    conditions.reserve(legacyConditions.size());
    for (const auto &legacy : legacyConditions) {
        if (legacy.kind != ContextCondition::Kind::Bond || !legacy.partnerStates.empty())
            return EnergyDeltaPlan::materializedFallback();
        EnergyCondition condition;
        condition.kind = ConditionKind::Bond;
        condition.reactantIndex = legacy.reactantIdx;
        condition.moleculeType = legacy.molType;
        condition.componentName = legacy.compName;
        condition.expectedBound = true;
        condition.partnerType = legacy.partnerType;
        condition.partnerComponent = legacy.partnerComp;
        for (int factorIndex : legacy.gatedPatternIndices) {
            if (factorIndex >= 0)
                condition.sourceFactorIndices.push_back(
                    static_cast<std::size_t>(factorIndex));
        }
        conditions.push_back(std::move(condition));
    }

    vector<EnergyTerm> terms;
    for (int pi : conditionalPatterns) {
        double contribution = 0.0;
        if (!signedCenterEnergy(pi, contribution))
            return EnergyDeltaPlan::materializedFallback();
        if (contribution == 0.0) continue;

        std::uint64_t conditionMask = 0;
        for (std::size_t ci = 0; ci < legacyConditions.size(); ++ci) {
            const auto &gated = legacyConditions[ci].gatedPatternIndices;
            if (find(gated.begin(), gated.end(), pi) != gated.end())
                conditionMask |= (std::uint64_t{1} << ci);
        }
        if (conditionMask == 0)
            return EnergyDeltaPlan::materializedFallback();

        EnergyTerm term;
        term.energyValue = contribution;
        term.conditionMask = conditionMask;
        term.sourceFactorIndex = static_cast<std::size_t>(pi);
        terms.push_back(term);
    }

    if (terms.empty()) return EnergyDeltaPlan::constant(baseEnergy);
    auto plan = EnergyDeltaPlan::factorized(
        baseEnergy, std::move(conditions), std::move(terms));
    return plan.has_value() ? std::move(*plan)
                            : EnergyDeltaPlan::materializedFallback();
}

vector<int> EnergyFunction::findRelevantPatternsForBinding(
    const string &molType1, const string &site1,
    const string &molType2, const string &site2
) const {
    vector<int> result;
    std::set<int> seen;
    auto append = [&](const vector<int> &indices) {
        for (int idx : indices) {
            if (seen.insert(idx).second) result.push_back(idx);
        }
    };

    std::pair<std::string, std::string> endpoint1 {molType1, site1};
    std::pair<std::string, std::string> endpoint2 {molType2, site2};
    if (endpoint2 < endpoint1) std::swap(endpoint1, endpoint2);
    const BindingPatternKey key {
        endpoint1.first, endpoint1.second, endpoint2.first, endpoint2.second};
    const auto found = bindingPatternIndex.find(key);
    if (found != bindingPatternIndex.end()) append(found->second);

    const auto foundSite1 = siteBondPatternIndex.find(StatePatternKey {molType1, site1});
    if (foundSite1 != siteBondPatternIndex.end()) append(foundSite1->second);

    const auto foundSite2 = siteBondPatternIndex.find(StatePatternKey {molType2, site2});
    if (foundSite2 != siteBondPatternIndex.end()) append(foundSite2->second);

    return result;
}

vector<int> EnergyFunction::findRelevantPatternsForStateChange(
    const string &molType, const string &comp
) const {
    const auto found = statePatternIndex.find(StatePatternKey {molType, comp});
    return found == statePatternIndex.end() ? vector<int>{} : found->second;
}

/*
 * Extract context conditions from relevant energy patterns, including both
 * bond constraints (with partner type/component/states), state constraints,
 * and explicit unbound-site constraints.
 */
vector<ContextCondition> EnergyFunction::extractContextConditions(
    const vector<int> &relevantPatternIndices,
    const string &molType1, const string &site1,
    const string &molType2, const string &site2
) const {
    map<ConditionKey, ContextCondition> condMap;

    for (int pi : relevantPatternIndices) {
        const EnergyPatternInfo &ep = patterns[static_cast<std::size_t>(pi)];
        for (int mi = 0; mi < static_cast<int>(ep.molecules.size()); ++mi) {
            const EpMolecule &mol = ep.molecules[static_cast<std::size_t>(mi)];

            int reactantIdx = -1;
            int centerCompIdx = -1;
            if (mol.typeName == molType1) {
                reactantIdx = 0;
                for (int ci = 0; ci < static_cast<int>(mol.components.size()); ++ci) {
                    if (mol.components[static_cast<std::size_t>(ci)].name == site1) {
                        centerCompIdx = ci;
                        break;
                    }
                }
            } else if (!molType2.empty() && mol.typeName == molType2) {
                reactantIdx = 1;
                for (int ci = 0; ci < static_cast<int>(mol.components.size()); ++ci) {
                    if (mol.components[static_cast<std::size_t>(ci)].name == site2) {
                        centerCompIdx = ci;
                        break;
                    }
                }
            } else {
                continue;
            }

            std::vector<ContextCondition> localConds;
            extractMoleculeContextConditions(ep, mi, reactantIdx, centerCompIdx, -1, localConds);
            for (auto &cc : localConds) {
                const ConditionKey key = makeConditionKey(cc);
                auto it = condMap.find(key);
                if (it == condMap.end()) {
                    cc.gatedPatternIndices.push_back(pi);
                    condMap.emplace(key, std::move(cc));
                } else {
                    it->second.gatedPatternIndices.push_back(pi);
                }
            }
        }
    }

    vector<ContextCondition> result;
    result.reserve(condMap.size());
    for (auto &kv : condMap) {
        auto &gated = kv.second.gatedPatternIndices;
        sort(gated.begin(), gated.end());
        gated.erase(unique(gated.begin(), gated.end()), gated.end());
        result.push_back(std::move(kv.second));
    }
    return result;
}

/*
 * Expand a binding energy rule into conventional rules using exact per-embedding
 * condition extraction and logical AND conjunction.
 */
vector<ExpandedRuleInfo> EnergyFunction::expandBindingRule(
    const string &rxnName,
    double Ea0,
    double phi,
    const string &molType1, const string &bindSite1,
    const string &molType2, const string &bindSite2,
    double drivingWork
) const {
    vector<ExpandedRuleInfo> expanded;

    const double barrier = barrierForBinding(molType1, bindSite1, molType2, bindSite2);
    if (barrier != 0.0 || drivingWork != 0.0) {
        cout << "  " << rxnName << ": transition-state barrier B=" << barrier
             << ", reservoir work W=" << drivingWork
             << " (k_fwd/k_rev = exp(-(dG-W)/RT))" << endl;
    }

    vector<int> relevant = findRelevantPatternsForBinding(
        molType1, bindSite1, molType2, bindSite2);

    if (relevant.empty()) {
        cerr << "Warning: Arrhenius rule " << rxnName
             << " has no overlapping energy patterns. ΔG=0." << endl;

        ExpandedRuleInfo fwd;
        fwd.name = rxnName + "_fwd";
        fwd.deltaG = 0.0;
        fwd.rate = computeForwardRate(Ea0, 0.0, phi, barrier, drivingWork);
        fwd.isForward = true;
        expanded.push_back(fwd);

        ExpandedRuleInfo rev;
        rev.name = rxnName + "_rev";
        rev.deltaG = 0.0;
        rev.rate = computeReverseRate(Ea0, 0.0, phi, barrier, drivingWork);
        rev.isForward = false;
        expanded.push_back(rev);
        return expanded;
    }

    // Build all distinct reaction-center embeddings for every relevant energy pattern.
    vector<CenterEmbedding> alwaysEmbeddings;
    vector<CenterEmbedding> conditionalEmbeddings;

    for (int pi : relevant) {
        const EnergyPatternInfo &ep = patterns[static_cast<std::size_t>(pi)];
        std::set<std::vector<ConditionKey>> seenBondEmbedKeys;
        bool matchedExplicitBond = false;

        // 1. Explicit bond embeddings matching (molType1.bindSite1 - molType2.bindSite2)
        for (const auto &bond : ep.bonds) {
            if (bond.mol1 < 0 || bond.mol2 < 0 ||
                static_cast<std::size_t>(bond.mol1) >= ep.molecules.size() ||
                static_cast<std::size_t>(bond.mol2) >= ep.molecules.size()) continue;
            const auto &m1 = ep.molecules[static_cast<std::size_t>(bond.mol1)];
            const auto &m2 = ep.molecules[static_cast<std::size_t>(bond.mol2)];
            if (static_cast<std::size_t>(bond.comp1) >= m1.components.size() ||
                static_cast<std::size_t>(bond.comp2) >= m2.components.size()) continue;
            const auto &c1 = m1.components[static_cast<std::size_t>(bond.comp1)];
            const auto &c2 = m2.components[static_cast<std::size_t>(bond.comp2)];

            auto tryOrientation = [&](int r0Mol, int r0Comp, int r1Mol, int r1Comp) {
                matchedExplicitBond = true;
                CenterEmbedding emb;
                emb.patternIndex = pi;
                emb.sign = +1.0;
                extractMoleculeContextConditions(ep, r0Mol, 0, r0Comp, r1Mol, emb.rawConditions);
                extractMoleculeContextConditions(ep, r1Mol, 1, r1Comp, r0Mol, emb.rawConditions);

                std::vector<ConditionKey> sig;
                for (const auto &c : emb.rawConditions) sig.push_back(makeConditionKey(c));
                std::sort(sig.begin(), sig.end());
                sig.erase(std::unique(sig.begin(), sig.end()), sig.end());
                if (!seenBondEmbedKeys.insert(sig).second) return;

                if (emb.rawConditions.empty()) alwaysEmbeddings.push_back(std::move(emb));
                else conditionalEmbeddings.push_back(std::move(emb));
            };

            if (m1.typeName == molType1 && c1.name == bindSite1 &&
                m2.typeName == molType2 && c2.name == bindSite2) {
                tryOrientation(bond.mol1, bond.comp1, bond.mol2, bond.comp2);
            }
            if (m2.typeName == molType1 && c2.name == bindSite1 &&
                m1.typeName == molType2 && c1.name == bindSite2) {
                tryOrientation(bond.mol2, bond.comp2, bond.mol1, bond.comp1);
            }
        }

        // 2. Wildcard-bond (!+) and explicitly unbound (A(b)) single-site embeddings
        if (!matchedExplicitBond) {
            auto trySiteReactant = [&](int reactantIdx, const string &mtName, const string &siteName) {
                std::set<std::vector<ConditionKey>> seenSiteEmbedKeys;
                for (int mi = 0; mi < static_cast<int>(ep.molecules.size()); ++mi) {
                    const auto &mol = ep.molecules[static_cast<std::size_t>(mi)];
                    if (mol.typeName != mtName) continue;
                    for (int ci = 0; ci < static_cast<int>(mol.components.size()); ++ci) {
                        const auto &comp = mol.components[static_cast<std::size_t>(ci)];
                        if (comp.name != siteName) continue;
                        if (!comp.isWildcardBound && !comp.isUnbound) continue;

                        CenterEmbedding emb;
                        emb.patternIndex = pi;
                        // Binding creates a bond: !+ is GAINED (+1), unbound is LOST (-1).
                        emb.sign = comp.isWildcardBound ? +1.0 : -1.0;
                        extractMoleculeContextConditions(ep, mi, reactantIdx, ci, -1, emb.rawConditions);

                        std::vector<ConditionKey> sig;
                        for (const auto &c : emb.rawConditions) sig.push_back(makeConditionKey(c));
                        std::sort(sig.begin(), sig.end());
                        sig.erase(std::unique(sig.begin(), sig.end()), sig.end());
                        if (!seenSiteEmbedKeys.insert(sig).second) continue;

                        if (emb.rawConditions.empty()) alwaysEmbeddings.push_back(std::move(emb));
                        else conditionalEmbeddings.push_back(std::move(emb));
                    }
                }
            };
            trySiteReactant(0, molType1, bindSite1);
            trySiteReactant(1, molType2, bindSite2);
        }
    }

    double baseG = 0.0;
    std::vector<std::pair<int, double>> baseContribs;
    for (const auto &emb : alwaysEmbeddings) {
        baseG += emb.sign * patterns[static_cast<std::size_t>(emb.patternIndex)].energyValue;
        baseContribs.emplace_back(emb.patternIndex, emb.sign);
    }

    // Collect deduplicated unique context conditions across all conditional embeddings
    map<ConditionKey, int> condIndexByKey;
    vector<ContextCondition> conditions;
    for (auto &emb : conditionalEmbeddings) {
        emb.requiredMask = 0;
        for (const auto &cc : emb.rawConditions) {
            const ConditionKey key = makeConditionKey(cc);
            auto it = condIndexByKey.find(key);
            int idx = -1;
            if (it == condIndexByKey.end()) {
                idx = static_cast<int>(conditions.size());
                condIndexByKey.emplace(key, idx);
                ContextCondition stored = cc;
                stored.gatedPatternIndices.push_back(emb.patternIndex);
                conditions.push_back(std::move(stored));
            } else {
                idx = it->second;
                conditions[static_cast<std::size_t>(idx)].gatedPatternIndices.push_back(emb.patternIndex);
            }
            if (idx < 64) emb.requiredMask |= (std::uint64_t{1} << idx);
        }
    }

    if (conditions.empty()) {
        ExpandedRuleInfo fwd;
        fwd.name = rxnName + "_fwd";
        fwd.deltaG = baseG;
        fwd.rate = computeForwardRate(Ea0, baseG, phi, barrier, drivingWork);
        fwd.isForward = true;
        fwd.activePatternContributions = baseContribs;
        expanded.push_back(fwd);

        ExpandedRuleInfo rev;
        rev.name = rxnName + "_rev";
        rev.deltaG = baseG;
        rev.rate = computeReverseRate(Ea0, baseG, phi, barrier, drivingWork);
        rev.isForward = false;
        rev.activePatternContributions = baseContribs;
        expanded.push_back(rev);

        cout << "  Expanded " << rxnName << " → 1 forward + 1 reverse rule"
             << "  (ΔG=" << baseG << ", k_fwd=" << fwd.rate
             << ", k_rev=" << rev.rate << ")" << endl;
        return expanded;
    }

    const int nCond = static_cast<int>(conditions.size());
    const std::uint64_t nCombinations = std::uint64_t{1} << nCond;

    cout << "  Expanding " << rxnName << " with " << nCond
         << " context condition(s), up to " << nCombinations
         << " variant(s) per direction:" << endl;

    for (std::uint64_t combo = 0; combo < nCombinations; ++combo) {
        if (isComboContradictory(combo, conditions)) continue;

        double deltaG = baseG;
        std::vector<std::pair<int, double>> activeContribs = baseContribs;
        for (const auto &emb : conditionalEmbeddings) {
            // Logical AND: ALL required conditions of this embedding must hold.
            if ((combo & emb.requiredMask) == emb.requiredMask) {
                deltaG += emb.sign * patterns[static_cast<std::size_t>(emb.patternIndex)].energyValue;
                activeContribs.emplace_back(emb.patternIndex, emb.sign);
            }
        }

        const auto constraints = buildConstraintsForCombo(combo, conditions);

        {
            ExpandedRuleInfo rule;
            stringstream ss;
            ss << rxnName << "_fwd_v" << combo;
            rule.name = ss.str();
            rule.deltaG = deltaG;
            rule.rate = computeForwardRate(Ea0, deltaG, phi, barrier, drivingWork);
            rule.isForward = true;
            rule.constraints = constraints;
            rule.activePatternContributions = activeContribs;
            expanded.push_back(std::move(rule));
        }

        {
            ExpandedRuleInfo rule;
            stringstream ss;
            ss << rxnName << "_rev_v" << combo;
            rule.name = ss.str();
            rule.deltaG = deltaG;
            rule.rate = computeReverseRate(Ea0, deltaG, phi, barrier, drivingWork);
            rule.isForward = false;
            rule.constraints = constraints;
            rule.activePatternContributions = activeContribs;
            expanded.push_back(std::move(rule));
        }
    }

    return expanded;
}

/*
 * Expand a state-change energy rule using exact per-embedding condition
 * extraction (handling partner states, homotypic Ising neighbor spins,
 * multi-state couplings, and logical AND conjunction).
 */
vector<ExpandedRuleInfo> EnergyFunction::expandStateChangeRule(
    const string &rxnName,
    double Ea0,
    double phi,
    const string &molType, const string &comp,
    const string &stateFrom, const string &stateTo,
    double drivingWork
) const {
    vector<ExpandedRuleInfo> expanded;

    const double barrier = barrierForStateChange(molType, comp, stateFrom, stateTo);
    if (barrier != 0.0 || drivingWork != 0.0) {
        cout << "  " << rxnName << ": transition-state barrier B=" << barrier
             << ", reservoir work W=" << drivingWork
             << " (k_fwd/k_rev = exp(-(dG-W)/RT))" << endl;
    }

    vector<int> relevant = findRelevantPatternsForStateChange(molType, comp);

    vector<CenterEmbedding> alwaysEmbeddings;
    vector<CenterEmbedding> conditionalEmbeddings;

    for (int pi : relevant) {
        const EnergyPatternInfo &ep = patterns[static_cast<std::size_t>(pi)];
        // Deduplicate automorphism-equivalent embeddings within the same pattern
        // (e.g. symmetric S(b!1,spin~U).S(b!1,spin~U) has |Aut|=2, while
        // directed S(r!1,spin~U).S(l!1,spin~U) yields two distinct embeddings:
        // right-neighbor U and left-neighbor U).
        std::set<std::pair<int, std::vector<ConditionKey>>> seenEmbedKeys;

        for (int mi = 0; mi < static_cast<int>(ep.molecules.size()); ++mi) {
            const auto &mol = ep.molecules[static_cast<std::size_t>(mi)];
            if (mol.typeName != molType) continue;
            for (int ci = 0; ci < static_cast<int>(mol.components.size()); ++ci) {
                const auto &c = mol.components[static_cast<std::size_t>(ci)];
                if (c.name != comp || c.stateConstraint.empty()) continue;

                double sign = 0.0;
                if (c.stateConstraint == stateTo) sign = +1.0;
                else if (c.stateConstraint == stateFrom) sign = -1.0;
                else continue;

                CenterEmbedding emb;
                emb.patternIndex = pi;
                emb.sign = sign;
                extractMoleculeContextConditions(ep, mi, 0, ci, -1, emb.rawConditions);

                std::vector<ConditionKey> sig;
                for (const auto &cond : emb.rawConditions) sig.push_back(makeConditionKey(cond));
                std::sort(sig.begin(), sig.end());
                sig.erase(std::unique(sig.begin(), sig.end()), sig.end());
                const int signTag = (sign > 0.0) ? 1 : -1;
                if (!seenEmbedKeys.emplace(signTag, sig).second) continue;

                if (emb.rawConditions.empty()) alwaysEmbeddings.push_back(std::move(emb));
                else conditionalEmbeddings.push_back(std::move(emb));
            }
        }
    }

    double baseG = 0.0;
    std::vector<std::pair<int, double>> baseContribs;
    for (const auto &emb : alwaysEmbeddings) {
        baseG += emb.sign * patterns[static_cast<std::size_t>(emb.patternIndex)].energyValue;
        baseContribs.emplace_back(emb.patternIndex, emb.sign);
    }

    map<ConditionKey, int> condIndexByKey;
    vector<ContextCondition> conditions;
    for (auto &emb : conditionalEmbeddings) {
        emb.requiredMask = 0;
        for (const auto &cc : emb.rawConditions) {
            const ConditionKey key = makeConditionKey(cc);
            auto it = condIndexByKey.find(key);
            int idx = -1;
            if (it == condIndexByKey.end()) {
                idx = static_cast<int>(conditions.size());
                condIndexByKey.emplace(key, idx);
                ContextCondition stored = cc;
                stored.gatedPatternIndices.push_back(emb.patternIndex);
                conditions.push_back(std::move(stored));
            } else {
                idx = it->second;
                conditions[static_cast<std::size_t>(idx)].gatedPatternIndices.push_back(emb.patternIndex);
            }
            if (idx < 64) emb.requiredMask |= (std::uint64_t{1} << idx);
        }
    }

    if (conditions.empty()) {
        ExpandedRuleInfo fwd;
        fwd.name = rxnName + "_fwd";
        fwd.deltaG = baseG;
        fwd.rate = computeForwardRate(Ea0, baseG, phi, barrier, drivingWork);
        fwd.isForward = true;
        fwd.activePatternContributions = baseContribs;
        expanded.push_back(fwd);

        ExpandedRuleInfo rev;
        rev.name = rxnName + "_rev";
        rev.deltaG = baseG;
        rev.rate = computeReverseRate(Ea0, baseG, phi, barrier, drivingWork);
        rev.isForward = false;
        rev.activePatternContributions = baseContribs;
        expanded.push_back(rev);

        cout << "  Expanded state-change " << rxnName << " → 1 forward + 1 reverse rule"
             << "  (ΔG=" << baseG << ", k_fwd=" << fwd.rate
             << ", k_rev=" << rev.rate << ")" << endl;
        return expanded;
    }

    const int nCond = static_cast<int>(conditions.size());
    const std::uint64_t nCombinations = std::uint64_t{1} << nCond;

    cout << "  Expanding state-change " << rxnName << " with " << nCond
         << " context condition(s), up to " << nCombinations
         << " variant(s) per direction:" << endl;

    for (std::uint64_t combo = 0; combo < nCombinations; ++combo) {
        if (isComboContradictory(combo, conditions)) continue;

        double deltaG = baseG;
        std::vector<std::pair<int, double>> activeContribs = baseContribs;
        for (const auto &emb : conditionalEmbeddings) {
            if ((combo & emb.requiredMask) == emb.requiredMask) {
                deltaG += emb.sign * patterns[static_cast<std::size_t>(emb.patternIndex)].energyValue;
                activeContribs.emplace_back(emb.patternIndex, emb.sign);
            }
        }

        const auto constraints = buildConstraintsForCombo(combo, conditions);

        {
            ExpandedRuleInfo rule;
            stringstream ss;
            ss << rxnName << "_fwd_v" << combo;
            rule.name = ss.str();
            rule.deltaG = deltaG;
            rule.rate = computeForwardRate(Ea0, deltaG, phi, barrier, drivingWork);
            rule.isForward = true;
            rule.constraints = constraints;
            rule.activePatternContributions = activeContribs;
            expanded.push_back(std::move(rule));
        }

        {
            ExpandedRuleInfo rule;
            stringstream ss;
            ss << rxnName << "_rev_v" << combo;
            rule.name = ss.str();
            rule.deltaG = deltaG;
            rule.rate = computeReverseRate(Ea0, deltaG, phi, barrier, drivingWork);
            rule.isForward = false;
            rule.constraints = constraints;
            rule.activePatternContributions = activeContribs;
            expanded.push_back(std::move(rule));
        }
    }

    return expanded;
}
