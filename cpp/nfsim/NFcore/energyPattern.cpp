/*
 * energyPattern.cpp
 *
 * Implementation of the Sekar energy rule expansion algorithm.
 *
 * The expansion works by:
 * 1. Identifying energy patterns that overlap with the reaction center
 *    (Corollary 3.3-43: only these contribute to ΔG)
 * 2. Extracting "context conditions" — components whose bond/state
 *    determines whether a pattern matches
 * 3. Enumerating all combinations of context conditions
 * 4. For each combination, computing ΔG and the Arrhenius rate
 * 5. Producing a conventional rule for each combination
 */

#include "energyPattern.hh"
#include <iostream>
#include <sstream>
#include <algorithm>
#include <utility>

using namespace NFcore;
using namespace std;

EnergyFunction::EnergyFunction(double phi, double RT) : phi(phi), RT(RT) {}
EnergyFunction::~EnergyFunction() {}

void EnergyFunction::addEnergyPattern(const EnergyPatternInfo &ep) {
    const int patternIndex = static_cast<int>(patterns.size());
    patterns.push_back(ep);

    // Build compile-time inverted indexes once.  A pattern is stored at most
    // once per reaction-center key, preserving the legacy find* behavior that
    // returned each matching energy factor once even if it mentioned the same
    // center repeatedly.
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

    std::set<StatePatternKey> stateKeys;
    for (const auto &molecule : ep.molecules) {
        for (const auto &component : molecule.components) {
            if (!component.stateConstraint.empty())
                stateKeys.emplace(molecule.typeName, component.name);
        }
    }
    for (const auto &key : stateKeys)
        statePatternIndex[key].push_back(patternIndex);
}

bng::compile::energy::EnergyDeltaPlan EnergyFunction::compileBindingDeltaPlan(
    const string &molType1, const string &bindSite1,
    const string &molType2, const string &bindSite2
) const {
    using bng::compile::energy::ConditionKind;
    using bng::compile::energy::EnergyCondition;
    using bng::compile::energy::EnergyDeltaPlan;
    using bng::compile::energy::EnergyTerm;

    const vector<int> relevant = findRelevantPatternsForBinding(
        molType1, bindSite1, molType2, bindSite2);
    if (relevant.empty()) return EnergyDeltaPlan::constant(0.0);

    vector<int> alwaysPatterns;
    vector<int> conditionalPatterns;

    for (int pi : relevant) {
        const EnergyPatternInfo &ep = patterns[pi];
        bool hasExtraContext = false;
        int weightedMoleculeCount = 0;

        for (const auto &mol : ep.molecules) {
            if (mol.typeName == molType1) ++weightedMoleculeCount;
        }
        for (const auto &mol : ep.molecules) {
            const bool isReactantType =
                mol.typeName == molType1 || mol.typeName == molType2;
            if (!isReactantType) {
                hasExtraContext = true;
                break;
            }
            for (const auto &comp : mol.components) {
                if (mol.typeName == molType1 && comp.name == bindSite1) continue;
                if (mol.typeName == molType2 && comp.name == bindSite2) continue;
                if (comp.isBound || !comp.stateConstraint.empty()) {
                    hasExtraContext = true;
                    break;
                }
            }
            if (hasExtraContext) break;
        }

        if (weightedMoleculeCount != 1)
            return EnergyDeltaPlan::materializedFallback();

        if (hasExtraContext) conditionalPatterns.push_back(pi);
        else alwaysPatterns.push_back(pi);
    }

    double baseEnergy = 0.0;
    for (int pi : alwaysPatterns) baseEnergy += patterns[pi].energyValue;
    if (conditionalPatterns.empty()) return EnergyDeltaPlan::constant(baseEnergy);

    const auto legacyConditions = extractContextConditions(
        conditionalPatterns, molType1, bindSite1, molType2, bindSite2);
    if (legacyConditions.empty() || legacyConditions.size() >= 64)
        return EnergyDeltaPlan::materializedFallback();

    vector<EnergyCondition> conditions;
    conditions.reserve(legacyConditions.size());
    for (const auto &legacy : legacyConditions) {
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
        term.energyValue = patterns[pi].energyValue;
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

    const auto plan = compileBindingDeltaPlan(
        molType1, bindSite1, molType2, bindSite2);
    if (!plan.isFactorized()) return false;

    context.baseEnergy = plan.baseEnergy();
    context.conditions.reserve(plan.conditions().size());
    for (const auto &condition : plan.conditions()) {
        ContextCondition legacy;
        legacy.molType = condition.moleculeType;
        legacy.reactantIdx = condition.reactantIndex;
        legacy.compName = condition.componentName;
        legacy.partnerType = condition.partnerType;
        legacy.partnerComp = condition.partnerComponent;
        for (std::size_t factorIndex : condition.sourceFactorIndices)
            legacy.gatedPatternIndices.push_back(static_cast<int>(factorIndex));
        context.conditions.push_back(std::move(legacy));
    }

    context.conditionalTerms.reserve(plan.terms().size());
    for (const auto &term : plan.terms()) {
        context.conditionalTerms.push_back({term.energyValue, term.conditionMask});
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
        const auto &ep = patterns[patternIndex];
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
        const auto &ep = patterns[pi];
        bool hasExtraContext = false;
        int weightedMoleculeCount = 0;
        for (const auto &mol : ep.molecules) {
            if (mol.typeName == molType) ++weightedMoleculeCount;
            if (mol.typeName != molType) {
                hasExtraContext = true;
                continue;
            }
            for (const auto &component : mol.components) {
                if (component.name == comp) continue;
                if (component.isBound || !component.stateConstraint.empty()) {
                    hasExtraContext = true;
                    break;
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

/*
 * Find energy patterns relevant to a binding rule.
 *
 * A pattern is "relevant" if it contains a bond between molType1.site1
 * and molType2.site2 — i.e., the bond being formed/broken by the rule.
 * Only such patterns have different match counts in reactant vs product,
 * so only they contribute to ΔG (Sekar Corollary 3.3-43).
 */
vector<int> EnergyFunction::findRelevantPatternsForBinding(
    const string &molType1, const string &site1,
    const string &molType2, const string &site2
) const {
    std::pair<std::string, std::string> endpoint1 {molType1, site1};
    std::pair<std::string, std::string> endpoint2 {molType2, site2};
    if (endpoint2 < endpoint1) std::swap(endpoint1, endpoint2);
    const BindingPatternKey key {
        endpoint1.first, endpoint1.second, endpoint2.first, endpoint2.second};
    const auto found = bindingPatternIndex.find(key);
    return found == bindingPatternIndex.end() ? vector<int>{} : found->second;
}

/*
 * Find energy patterns relevant to a state-change rule.
 *
 * A pattern is relevant if it constrains the state of molType.comp,
 * because a state change on that component changes the match count.
 */
vector<int> EnergyFunction::findRelevantPatternsForStateChange(
    const string &molType, const string &comp
) const {
    const auto found = statePatternIndex.find(StatePatternKey {molType, comp});
    return found == statePatternIndex.end() ? vector<int>{} : found->second;
}

/*
 * Extract context conditions from relevant energy patterns.
 *
 * For each relevant pattern, identify components beyond the reaction
 * center that the pattern constrains. These become context conditions
 * that must be resolved during expansion.
 *
 * Example: Pattern S(A!1,B!2).A(s!1).B(s!2) with reaction center A-s bond
 *          → Context condition: S.B must be bound to B.s
 */
vector<ContextCondition> EnergyFunction::extractContextConditions(
    const vector<int> &relevantPatternIndices,
    const string &molType1, const string &site1,
    const string &molType2, const string &site2
) const {
    // Collect unique context conditions across all relevant patterns.
    // Key: (reactantMolType, compName) → condition info
    map<pair<string,string>, ContextCondition> condMap;

    for (int pi : relevantPatternIndices) {
        const EnergyPatternInfo &ep = patterns[pi];

        // For each molecule in the pattern that matches a reactant type,
        // check for components beyond the reaction center
        for (int mi = 0; mi < (int)ep.molecules.size(); mi++) {
            const EpMolecule &mol = ep.molecules[mi];

            int reactantIdx = -1;
            if (mol.typeName == molType1) reactantIdx = 0;
            else if (mol.typeName == molType2) reactantIdx = 1;
            else continue;  // molecule from outside the reactants — skip for now

            for (const auto &comp : mol.components) {
                // Skip the reaction center component
                if (reactantIdx == 0 && comp.name == site1) continue;
                if (reactantIdx == 1 && comp.name == site2) continue;

                // This component is a context condition
                if (comp.isBound) {
                    auto key = make_pair(mol.typeName, comp.name);
                    if (condMap.find(key) == condMap.end()) {
                        ContextCondition cc;
                        cc.molType = mol.typeName;
                        cc.reactantIdx = reactantIdx;
                        cc.compName = comp.name;

                        // Find the bond partner
                        for (const auto &bond : ep.bonds) {
                            if (bond.mol1 == mi && bond.comp1 == (int)(&comp - &mol.components[0])) {
                                cc.partnerType = ep.molecules[bond.mol2].typeName;
                                cc.partnerComp = ep.molecules[bond.mol2].components[bond.comp2].name;
                                break;
                            }
                            if (bond.mol2 == mi && bond.comp2 == (int)(&comp - &mol.components[0])) {
                                cc.partnerType = ep.molecules[bond.mol1].typeName;
                                cc.partnerComp = ep.molecules[bond.mol1].components[bond.comp1].name;
                                break;
                            }
                        }

                        condMap[key] = cc;
                    }
                    condMap[key].gatedPatternIndices.push_back(pi);
                }
            }
        }
    }

    vector<ContextCondition> result;
    for (auto &kv : condMap) {
        // Deduplicate gated pattern indices
        sort(kv.second.gatedPatternIndices.begin(), kv.second.gatedPatternIndices.end());
        kv.second.gatedPatternIndices.erase(
            unique(kv.second.gatedPatternIndices.begin(), kv.second.gatedPatternIndices.end()),
            kv.second.gatedPatternIndices.end());
        result.push_back(kv.second);
    }
    return result;
}

/*
 * Expand a binding energy rule into conventional rules.
 *
 * Algorithm (Sekar §3.4):
 * 1. Find energy patterns containing the reaction center bond
 * 2. Separate into "always-matching" (no extra context) and "conditional"
 * 3. Extract context conditions from conditional patterns
 * 4. Enumerate all 2^n combinations of n boolean context conditions
 * 5. For each combination, compute ΔG and rates
 */
vector<ExpandedRuleInfo> EnergyFunction::expandBindingRule(
    const string &rxnName,
    double Ea0,
    double phi,
    const string &molType1, const string &bindSite1,
    const string &molType2, const string &bindSite2
) const {
    vector<ExpandedRuleInfo> expanded;

    // Step 1: Find relevant patterns
    vector<int> relevant = findRelevantPatternsForBinding(
        molType1, bindSite1, molType2, bindSite2);

    if (relevant.empty()) {
        // No energy patterns overlap with the reaction center.
        // ΔG = 0 for all contexts → single rule with rate = exp(-Ea0/RT)
        cerr << "Warning: Arrhenius rule " << rxnName
             << " has no overlapping energy patterns. ΔG=0." << endl;

        ExpandedRuleInfo fwd;
        fwd.name = rxnName + "_fwd";
        fwd.deltaG = 0.0;
        fwd.rate = computeForwardRate(Ea0, 0.0, phi);
        fwd.isForward = true;
        expanded.push_back(fwd);

        ExpandedRuleInfo rev;
        rev.name = rxnName + "_rev";
        rev.deltaG = 0.0;
        rev.rate = computeReverseRate(Ea0, 0.0, phi);
        rev.isForward = false;
        expanded.push_back(rev);
        return expanded;
    }

    // Step 2: Classify relevant patterns into "always" and "conditional"
    // "Always" patterns: contain ONLY the reaction center molecules+sites,
    //                    no extra context → always match when the bond exists
    // "Conditional" patterns: have additional context beyond the center

    vector<int> alwaysPatterns;    // indices into 'relevant'
    vector<int> conditionalPatterns;

    for (int ri = 0; ri < (int)relevant.size(); ri++) {
        int pi = relevant[ri];
        const EnergyPatternInfo &ep = patterns[pi];

        bool hasExtraContext = false;
        for (const auto &mol : ep.molecules) {
            bool isReactantType = (mol.typeName == molType1 || mol.typeName == molType2);
            if (!isReactantType) {
                // Pattern involves a third molecule type → conditional
                hasExtraContext = true;
                break;
            }
            for (const auto &comp : mol.components) {
                // Skip the reaction center components
                if (mol.typeName == molType1 && comp.name == bindSite1) continue;
                if (mol.typeName == molType2 && comp.name == bindSite2) continue;
                // Any other component with a constraint → extra context
                if (comp.isBound || !comp.stateConstraint.empty()) {
                    hasExtraContext = true;
                    break;
                }
            }
            if (hasExtraContext) break;
        }

        if (hasExtraContext)
            conditionalPatterns.push_back(pi);
        else
            alwaysPatterns.push_back(pi);
    }

    // Base ΔG from always-matching patterns (forward direction: bond forms → +G_e)
    double baseG = 0.0;
    for (int pi : alwaysPatterns) {
        baseG += patterns[pi].energyValue;
    }

    // Step 3: Extract context conditions from conditional patterns
    vector<ContextCondition> conditions = extractContextConditions(
        conditionalPatterns, molType1, bindSite1, molType2, bindSite2);

    if (conditions.empty()) {
        // All relevant patterns are "always" — single forward + reverse rule
        ExpandedRuleInfo fwd;
        fwd.name = rxnName + "_fwd";
        fwd.deltaG = baseG;
        fwd.rate = computeForwardRate(Ea0, baseG, phi);
        fwd.isForward = true;
        expanded.push_back(fwd);

        ExpandedRuleInfo rev;
        rev.name = rxnName + "_rev";
        rev.deltaG = baseG;
        rev.rate = computeReverseRate(Ea0, baseG, phi);
        rev.isForward = false;
        expanded.push_back(rev);

        cout << "  Expanded " << rxnName << " → 1 forward + 1 reverse rule"
             << "  (ΔG=" << baseG << ", k_fwd=" << fwd.rate
             << ", k_rev=" << rev.rate << ")" << endl;
        return expanded;
    }

    // Step 4: Enumerate all 2^n combinations of context conditions
    int nCond = (int)conditions.size();
    int nCombinations = 1 << nCond;  // 2^n

    cout << "  Expanding " << rxnName << " with " << nCond
         << " context condition(s), " << nCombinations
         << " variant(s) per direction:" << endl;

    for (int combo = 0; combo < nCombinations; combo++) {
        // Determine which conditional patterns are active in this combination
        set<int> activePatterns;  // indices into patterns[]
        for (int pi : alwaysPatterns) activePatterns.insert(pi);

        // Build context constraints for this combination
        vector<ExpandedRuleInfo::ContextConstraint> constraints;
        for (int ci = 0; ci < nCond; ci++) {
            bool conditionMet = (combo >> ci) & 1;

            ExpandedRuleInfo::ContextConstraint cc;
            cc.reactantIdx = conditions[ci].reactantIdx;
            cc.compName = conditions[ci].compName;
            cc.mustBeBound = conditionMet;
            constraints.push_back(cc);

            if (conditionMet) {
                for (int pi : conditions[ci].gatedPatternIndices) {
                    activePatterns.insert(pi);
                }
            }
        }

        // Step 5: Compute ΔG for this combination
        double deltaG = 0.0;
        for (int pi : activePatterns) {
            deltaG += patterns[pi].energyValue;
        }

        // Create forward rule
        {
            ExpandedRuleInfo rule;
            stringstream ss;
            ss << rxnName << "_fwd_v" << combo;
            rule.name = ss.str();
            rule.deltaG = deltaG;
            rule.rate = computeForwardRate(Ea0, deltaG, phi);
            rule.isForward = true;
            rule.constraints = constraints;
            expanded.push_back(rule);
        }

        // Create reverse rule
        {
            ExpandedRuleInfo rule;
            stringstream ss;
            ss << rxnName << "_rev_v" << combo;
            rule.name = ss.str();
            rule.deltaG = deltaG;
            rule.rate = computeReverseRate(Ea0, deltaG, phi);
            rule.isForward = false;
            // Reverse rule has same context constraints
            rule.constraints = constraints;
            expanded.push_back(rule);
        }

        cout << "    v" << combo << ": ΔG=" << deltaG
             << "  k_fwd=" << computeForwardRate(Ea0, deltaG, phi)
             << "  k_rev=" << computeReverseRate(Ea0, deltaG, phi)
             << "  context=[";
        for (int ci = 0; ci < nCond; ci++) {
            if (ci > 0) cout << ", ";
            cout << conditions[ci].molType << "." << conditions[ci].compName
                 << "=" << (((combo >> ci) & 1) ? "bound" : "free");
        }
        cout << "]" << endl;
    }

    return expanded;
}

/*
 * Expand a state-change energy rule.
 * Same algorithm but for unimolecular reactions.
 */
vector<ExpandedRuleInfo> EnergyFunction::expandStateChangeRule(
    const string &rxnName,
    double Ea0,
    double phi,
    const string &molType, const string &comp,
    const string &stateFrom, const string &stateTo
) const {
    vector<ExpandedRuleInfo> expanded;

    vector<int> relevant = findRelevantPatternsForStateChange(molType, comp);

    // For state change, a pattern is relevant if it constrains the state
    // of the changing component. We need to determine for each relevant
    // pattern whether it matches the "from" state or "to" state.

    // Patterns matching the "to" state contribute +G_e to ΔG
    // Patterns matching the "from" state contribute -G_e to ΔG
    // (because they match in reactant but not product)

    // Classify relevant patterns into "always" and "conditional"
    vector<int> alwaysPatterns;
    vector<int> conditionalPatterns;

    for (int ri = 0; ri < (int)relevant.size(); ri++) {
        int pi = relevant[ri];
        const EnergyPatternInfo &ep = patterns[pi];

        bool hasExtraContext = false;
        for (const auto &mol : ep.molecules) {
            if (mol.typeName != molType) {
                // Pattern involves another molecule type -> conditional
                hasExtraContext = true;
                break;
            }
            for (const auto &c : mol.components) {
                // Skip the reaction center component (the one changing state)
                if (c.name == comp) continue;
                // Any other component with a constraint -> extra context
                if (c.isBound || !c.stateConstraint.empty()) {
                    hasExtraContext = true;
                    break;
                }
            }
            if (hasExtraContext) break;
        }

        if (hasExtraContext)
            conditionalPatterns.push_back(pi);
        else
            alwaysPatterns.push_back(pi);
    }

    // Base ΔG from always-matching patterns
    double baseG = 0.0;
    for (int pi : alwaysPatterns) {
        const EnergyPatternInfo &ep = patterns[pi];
        for (const auto &mol : ep.molecules) {
            if (mol.typeName == molType) {
                for (const auto &c : mol.components) {
                    if (c.name == comp) {
                        if (c.stateConstraint == stateTo) {
                            baseG += ep.energyValue;
                        } else if (c.stateConstraint == stateFrom) {
                            baseG -= ep.energyValue;
                        }
                    }
                }
            }
        }
    }

    // Extract context conditions
    // Unimolecular: only molType is involved, use extractContextConditions passing it as molType1
    vector<ContextCondition> conditions = extractContextConditions(
        conditionalPatterns, molType, comp, "", "");

    if (conditions.empty()) {
        ExpandedRuleInfo fwd;
        fwd.name = rxnName + "_fwd";
        fwd.deltaG = baseG;
        fwd.rate = computeForwardRate(Ea0, baseG, phi);
        fwd.isForward = true;
        expanded.push_back(fwd);

        ExpandedRuleInfo rev;
        rev.name = rxnName + "_rev";
        rev.deltaG = baseG;
        rev.rate = computeReverseRate(Ea0, baseG, phi);
        rev.isForward = false;
        expanded.push_back(rev);

        cout << "  Expanded state-change " << rxnName << " → 1 forward + 1 reverse rule"
             << "  (ΔG=" << baseG << ", k_fwd=" << fwd.rate
             << ", k_rev=" << rev.rate << ")" << endl;
        return expanded;
    }

    // Enumerate all 2^n combinations of context conditions
    int nCond = (int)conditions.size();
    int nCombinations = 1 << nCond;  // 2^n

    cout << "  Expanding state-change " << rxnName << " with " << nCond
         << " context condition(s), " << nCombinations
         << " variant(s) per direction:" << endl;

    for (int combo = 0; combo < nCombinations; combo++) {
        set<int> activePatterns;
        for (int pi : alwaysPatterns) activePatterns.insert(pi);

        vector<ExpandedRuleInfo::ContextConstraint> constraints;
        for (int ci = 0; ci < nCond; ci++) {
            bool conditionMet = (combo >> ci) & 1;

            ExpandedRuleInfo::ContextConstraint cc;
            cc.reactantIdx = conditions[ci].reactantIdx;
            cc.compName = conditions[ci].compName;
            cc.mustBeBound = conditionMet;
            constraints.push_back(cc);

            if (conditionMet) {
                for (int pi : conditions[ci].gatedPatternIndices) {
                    activePatterns.insert(pi);
                }
            }
        }

        double deltaG = 0.0;
        for (int pi : activePatterns) {
            const EnergyPatternInfo &ep = patterns[pi];
            for (const auto &mol : ep.molecules) {
                if (mol.typeName == molType) {
                    for (const auto &c : mol.components) {
                        if (c.name == comp) {
                            if (c.stateConstraint == stateTo) {
                                deltaG += ep.energyValue;
                            } else if (c.stateConstraint == stateFrom) {
                                deltaG -= ep.energyValue;
                            }
                        }
                    }
                }
            }
        }

        // Create forward rule
        {
            ExpandedRuleInfo rule;
            stringstream ss;
            ss << rxnName << "_fwd_v" << combo;
            rule.name = ss.str();
            rule.deltaG = deltaG;
            rule.rate = computeForwardRate(Ea0, deltaG, phi);
            rule.isForward = true;
            rule.constraints = constraints;
            expanded.push_back(rule);
        }

        // Create reverse rule
        {
            ExpandedRuleInfo rule;
            stringstream ss;
            ss << rxnName << "_rev_v" << combo;
            rule.name = ss.str();
            rule.deltaG = deltaG;
            rule.rate = computeReverseRate(Ea0, deltaG, phi);
            rule.isForward = false;
            rule.constraints = constraints;
            expanded.push_back(rule);
        }

        cout << "    v" << combo << ": ΔG=" << deltaG
             << "  k_fwd=" << computeForwardRate(Ea0, deltaG, phi)
             << "  k_rev=" << computeReverseRate(Ea0, deltaG, phi)
             << "  context=[";
        for (int ci = 0; ci < nCond; ci++) {
            if (ci > 0) cout << ", ";
            cout << conditions[ci].molType << "." << conditions[ci].compName
                 << "=" << (((combo >> ci) & 1) ? "bound" : "free");
        }
        cout << "]" << endl;
    }

    return expanded;
}
