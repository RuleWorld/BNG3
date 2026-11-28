/*
 * NFinput_energy.cpp
 *
 * Integration between the energy rule expansion engine and NFsim's
 * input pipelines (XML, AST, Compiled).
 */

#include "../NFcore/NFcore.hh"
#include "../NFcore/energyPattern.hh"
#include "../NFfunction/NFfunction.hh"
#include "../NFreactions/reactions/reaction.hh"
#include "NFinput.hh"
#include "NFinput_energy.hh"
#include "TinyXML/tinyxml.h"

#include <map>
#include <set>
#include <string>
#include <vector>
#include <iostream>
#include <cmath>

#include "compile/energy/BarrierTable.hpp"
#include "compile/energy/DrivenEnergy.hpp"

using namespace std;
using namespace NFcore;


namespace NFinput {

double evaluateEnergyExpression(const string &expression,
                                map<string, double> &parameters)
{
    mu::Parser parser;
    for (auto &parameter : parameters)
        parser.DefineVar(parameter.first, &parameter.second);
    double value;
    try {
        parser.SetExpr(expression);
        value = parser.Eval();
    } catch (const mu::Parser::exception_type &error) {
        throw std::runtime_error(error.GetMsg());
    }
    if (!std::isfinite(value))
        throw std::runtime_error("energy expression is not finite");
    return value;
}

namespace {

// Check whether an expanded variant's constraints are compatible with all
// rule-level site constraints (ETH-07). Returns false if contradictory.
bool variantCompatibleWithRuleContext(
    const ExpandedRuleInfo &rule,
    const ArrheniusRuleContext &ruleContext,
    const std::function<std::string(int, const std::string&)> &mapCompName)
{
    for (const auto &rc : ruleContext.siteConstraints) {
        for (const auto &cc : rule.constraints) {
            if (cc.reactantIdx != rc.reactantIdx) continue;
            const std::string mappedComp = mapCompName(cc.reactantIdx, cc.compName);
            if (mappedComp != rc.compName) continue;

            if (!rc.stateName.empty() && cc.kind == ContextCondition::Kind::State) {
                if (cc.mustBeBound && cc.stateValue != rc.stateName) return false;
                if (!cc.mustBeBound && cc.stateValue == rc.stateName) return false;
            }
            if (rc.requireEmpty) {
                if (cc.kind == ContextCondition::Kind::Bond && cc.mustBeBound) return false;
                if (cc.kind == ContextCondition::Kind::Unbound && !cc.mustBeBound) return false;
            }
            if (rc.requireBound) {
                if (cc.kind == ContextCondition::Kind::Bond && !cc.mustBeBound && cc.partnerType.empty())
                    return false;
                if (cc.kind == ContextCondition::Kind::Unbound && cc.mustBeBound)
                    return false;
            }
        }
    }
    return true;
}

// Apply energy-pattern context constraints AND rule-level site constraints to
// reactant template(s) t0 (and optional t1 for binding).
// Throws or returns false on invalid component/partner lookup.
bool applyConstraintsToTemplates(
    const ExpandedRuleInfo &rule,
    const ArrheniusRuleContext &ruleContext,
    TemplateMolecule *t0,
    TemplateMolecule *t1,
    System *s,
    const std::function<std::string(int, const std::string&)> &mapCompName,
    std::vector<TemplateMolecule*> &ownedPartners)
{
    auto targetFor = [&](int rIdx) -> TemplateMolecule* {
        return (rIdx == 0) ? t0 : t1;
    };

    std::set<std::pair<int, std::string>> appliedEmpty;
    std::set<std::pair<int, std::string>> appliedBound;
    std::set<std::pair<int, std::string>> appliedExactState;
    std::map<std::pair<int, std::string>, TemplateMolecule*> boundPartners;
    std::map<std::pair<int, std::string>, std::set<std::pair<std::string, std::string>>> boundPartnerAppliedStates;

    for (const auto &cc : rule.constraints) {
        TemplateMolecule *target = targetFor(cc.reactantIdx);
        if (target == nullptr) return false;
        const std::string compName = mapCompName(cc.reactantIdx, cc.compName);
        if (target->getMoleculeType()->isEquivalentComponent(compName)) return false;
        const auto siteKey = std::make_pair(cc.reactantIdx, compName);

        if (cc.kind == ContextCondition::Kind::State) {
            if (cc.mustBeBound) {
                if (appliedExactState.insert(siteKey).second) {
                    target->addComponentConstraint(compName, cc.stateValue);
                }
            } else {
                target->addComponentExclusion(compName, cc.stateValue);
            }
        } else if (cc.kind == ContextCondition::Kind::Unbound) {
            if (cc.mustBeBound) {
                if (appliedEmpty.insert(siteKey).second) {
                    target->addEmptyComponent(compName);
                }
            } else {
                if (boundPartners.count(siteKey) == 0 && appliedBound.insert(siteKey).second) {
                    target->addBoundComponent(compName);
                }
            }
        } else {
            // Kind::Bond
            if (cc.mustBeBound) {
                if (cc.partnerType.empty()) {
                    if (boundPartners.count(siteKey) == 0 && appliedBound.insert(siteKey).second) {
                        target->addBoundComponent(compName);
                    }
                } else {
                    MoleculeType *partnerMT = s->getMoleculeTypeByName(cc.partnerType);
                    if (partnerMT == nullptr) return false;
                    TemplateMolecule *partnerTM = nullptr;
                    auto pIt = boundPartners.find(siteKey);
                    if (pIt == boundPartners.end()) {
                        partnerTM = new TemplateMolecule(partnerMT);
                        ownedPartners.push_back(partnerTM);
                        boundPartners.emplace(siteKey, partnerTM);
                        TemplateMolecule::bind(target, compName, "", partnerTM, cc.partnerComp, "");
                    } else {
                        partnerTM = pIt->second;
                    }
                    auto &pStates = boundPartnerAppliedStates[siteKey];
                    for (const auto &ps : cc.partnerStates) {
                        if (pStates.insert(ps).second) {
                            partnerTM->addComponentConstraint(ps.first, ps.second);
                        }
                    }
                }
            } else {
                if (cc.partnerType.empty()) {
                    if (appliedEmpty.insert(siteKey).second) {
                        target->addEmptyComponent(compName);
                    }
                } else {
                    MoleculeType *partnerMT = s->getMoleculeTypeByName(cc.partnerType);
                    if (partnerMT == nullptr) return false;
                    target->addBondExclusion(compName, partnerMT, cc.partnerComp, cc.partnerStates);
                }
            }
        }
    }

    // Apply rule-level site constraints (ETH-07), avoiding duplicates with already-applied constraints
    for (const auto &rc : ruleContext.siteConstraints) {
        TemplateMolecule *target = targetFor(rc.reactantIdx);
        if (target == nullptr) return false;
        if (target->getMoleculeType()->isEquivalentComponent(rc.compName)) return false;
        const auto siteKey = std::make_pair(rc.reactantIdx, rc.compName);

        if (!rc.stateName.empty() && appliedExactState.insert(siteKey).second) {
            target->addComponentConstraint(rc.compName, rc.stateName);
        }
        if (rc.requireEmpty && appliedEmpty.insert(siteKey).second) {
            target->addEmptyComponent(rc.compName);
        }
        if (rc.requireBound && boundPartners.count(siteKey) == 0 &&
            appliedBound.insert(siteKey).second) {
            target->addBoundComponent(rc.compName);
        }
    }

    return true;
}

void attachLiveArrheniusRateExpression(
    BasicRxnClass *reaction,
    System *s,
    bool isForward,
    double staticPhi,
    double staticEa0,
    double staticBarrier,
    double staticWork,
    double rt,
    const std::vector<std::pair<int, double>> &contribs,
    const ArrheniusRuleContext &ruleContext)
{
    if (!ruleContext.phiExpr && !ruleContext.ea0Expr &&
        !ruleContext.drivingWorkExpr && contribs.empty()) {
        return;
    }
    auto phiFn = ruleContext.phiExpr;
    auto ea0Fn = ruleContext.ea0Expr;
    auto workFn = ruleContext.drivingWorkExpr;
    reaction->setBaseRateExpression(
        [s, isForward, staticPhi, staticEa0, staticBarrier, staticWork, rt,
         contribs, phiFn, ea0Fn, workFn]() -> double {
            const double curPhi = phiFn ? phiFn() : staticPhi;
            const double curEa0 = ea0Fn ? ea0Fn() : staticEa0;
            const double curWork = workFn ? workFn() : staticWork;
            double curDeltaG = 0.0;
            EnergyFunction *curEf = s->getEnergyFunction();
            if (curEf != nullptr) {
                for (const auto &entry : contribs) {
                    if (entry.first >= 0 && entry.first < curEf->getNumPatterns()) {
                        curDeltaG += entry.second * curEf->getPattern(entry.first).energyValue;
                    }
                }
            }
            return bng::compile::energy::drivenArrheniusRate(
                curEa0, staticBarrier, curDeltaG, curWork, curPhi, rt, isForward);
        });
}

} // namespace

/*
 * Parse <ListOfEnergyPatterns> from the XML model element.
 */
bool parseEnergyPatterns(
    TiXmlElement *pModel,
    System *s,
    map<string, double> &parameter,
    bool verbose)
{
    TiXmlElement *pList = pModel->FirstChildElement("ListOfEnergyPatterns");
    if (!pList) {
        if (pModel->FirstChildElement("ListOfBarrierPatterns")) {
            cerr << "Error: barrier patterns require energy patterns and an "
                    "Arrhenius rate law." << endl;
            return false;
        }
        return true;
    }

    if (verbose) cout << "\n\tReading list of Energy Patterns..." << endl;

    double phi = 0.5;
    const double RT = 1.0;

    if (parameter.find("phi") != parameter.end())
        phi = parameter.find("phi")->second;
    EnergyFunction *ef = new EnergyFunction(phi, RT);

    TiXmlElement *pEP;
    for (pEP = pList->FirstChildElement("EnergyPattern"); pEP != 0; pEP = pEP->NextSiblingElement("EnergyPattern"))
    {
        if (!pEP->Attribute("id") || !pEP->Attribute("expression")) {
            cerr << "Error: EnergyPattern missing 'id' or 'expression'." << endl;
            delete ef;
            return false;
        }

        string epId = pEP->Attribute("id");
        string epExpr = pEP->Attribute("expression");

        double energyVal = 0.0;
        try { energyVal = evaluateEnergyExpression(epExpr, parameter); }
        catch (const std::exception &error) {
            cerr << "Error: cannot evaluate energy expression '" << epExpr
                 << "' for pattern " << epId << ": " << error.what() << endl;
            delete ef;
            return false;
        }

        EnergyPatternInfo epInfo;
        epInfo.id = epId;
        epInfo.energyValue = energyVal;
        epInfo.energyEvaluator = [epExpr](const std::map<std::string, double> &params) -> double {
            std::map<std::string, double> mutableParams = params;
            return evaluateEnergyExpression(epExpr, mutableParams);
        };

        TiXmlElement *pPattern = pEP->FirstChildElement("Pattern");
        TiXmlElement *pListOfMols = pPattern ? pPattern->FirstChildElement("ListOfMolecules") : pEP->FirstChildElement("ListOfMolecules");
        if (!pListOfMols) {
            cerr << "Error: EnergyPattern " << epId << " has no ListOfMolecules." << endl;
            delete ef;
            return false;
        }

        map<string, pair<int,int>> compIdMap;
        TiXmlElement *pMol;
        for (pMol = pListOfMols->FirstChildElement("Molecule"); pMol != 0; pMol = pMol->NextSiblingElement("Molecule"))
        {
            EpMolecule mol;
            mol.xmlId = pMol->Attribute("id") ? pMol->Attribute("id") : "";
            mol.typeName = pMol->Attribute("name") ? pMol->Attribute("name") : "";
            int molIdx = (int)epInfo.molecules.size();

            TiXmlElement *pListOfComps = pMol->FirstChildElement("ListOfComponents");
            if (pListOfComps) {
                TiXmlElement *pComp;
                for (pComp = pListOfComps->FirstChildElement("Component"); pComp != 0; pComp = pComp->NextSiblingElement("Component"))
                {
                    EpMolecule::CompInfo ci;
                    ci.name = pComp->Attribute("name") ? pComp->Attribute("name") : "";
                    string compId = pComp->Attribute("id") ? pComp->Attribute("id") : "";
                    string numBonds = pComp->Attribute("numberOfBonds") ? pComp->Attribute("numberOfBonds") : "0";
                    ci.isWildcardBound = (numBonds == "+");
                    ci.isUnbound = (numBonds == "0");
                    ci.isBound = (numBonds != "0" && numBonds != "" && numBonds != "?");
                    ci.bondPartnerId = "";

                    if (pComp->Attribute("state")) ci.stateConstraint = pComp->Attribute("state");

                    int compIdx = (int)mol.components.size();
                    compIdMap[compId] = make_pair(molIdx, compIdx);
                    mol.components.push_back(ci);
                }
            }
            epInfo.molecules.push_back(mol);
        }

        TiXmlElement *pListOfBonds = pPattern ? pPattern->FirstChildElement("ListOfBonds") : pEP->FirstChildElement("ListOfBonds");
        if (pListOfBonds) {
            TiXmlElement *pBond;
            for (pBond = pListOfBonds->FirstChildElement("Bond"); pBond != 0; pBond = pBond->NextSiblingElement("Bond"))
            {
                string site1 = pBond->Attribute("site1") ? pBond->Attribute("site1") : "";
                string site2 = pBond->Attribute("site2") ? pBond->Attribute("site2") : "";
                if (compIdMap.count(site1) && compIdMap.count(site2)) {
                    EnergyPatternInfo::Bond bond;
                    bond.mol1 = compIdMap[site1].first; bond.comp1 = compIdMap[site1].second;
                    bond.mol2 = compIdMap[site2].first; bond.comp2 = compIdMap[site2].second;
                    epInfo.bonds.push_back(bond);
                    epInfo.molecules[bond.mol1].components[bond.comp1].bondPartnerId = epInfo.molecules[bond.mol2].xmlId;
                    epInfo.molecules[bond.mol2].components[bond.comp2].bondPartnerId = epInfo.molecules[bond.mol1].xmlId;
                    epInfo.molecules[bond.mol1].components[bond.comp1].isBound = true;
                    epInfo.molecules[bond.mol2].components[bond.comp2].isBound = true;
                    epInfo.molecules[bond.mol1].components[bond.comp1].isWildcardBound = false;
                    epInfo.molecules[bond.mol2].components[bond.comp2].isWildcardBound = false;
                    epInfo.molecules[bond.mol1].components[bond.comp1].isUnbound = false;
                    epInfo.molecules[bond.mol2].components[bond.comp2].isUnbound = false;
                }
            }
        }
        ef->addEnergyPattern(epInfo);
    }

    TiXmlElement *pBarrierList = pModel->FirstChildElement("ListOfBarrierPatterns");
    if (pBarrierList) {
        if (!bng::compile::energy::generalEnergyEnabled()) {
            cerr << "Error: model declares barrier patterns but "
                 << bng::compile::energy::generalEnergyGateName()
                 << " is not set." << endl;
            delete ef;
            return false;
        }
        bng::compile::energy::BarrierTable barrierTable;
        TiXmlElement *pBP;
        int barrierIndex = 0;
        for (pBP = pBarrierList->FirstChildElement("BarrierPattern"); pBP != 0;
             pBP = pBP->NextSiblingElement("BarrierPattern")) {
            ++barrierIndex;
            const string label = pBP->Attribute("id")
                                     ? pBP->Attribute("id")
                                     : "barrier_" + NFutil::toString(barrierIndex);
            if (!pBP->Attribute("expression") || !pBP->Attribute("reactionCenter")) {
                cerr << "Error: BarrierPattern " << label
                     << " missing 'expression' or 'reactionCenter'." << endl;
                delete ef;
                return false;
            }

            const string expressionText = pBP->Attribute("expression");
            double barrierValue = 0.0;
            try { barrierValue = evaluateEnergyExpression(expressionText, parameter); }
            catch (const std::exception &error) {
                cerr << "Error: cannot resolve barrier energy '" << expressionText
                     << "' for BarrierPattern " << label << ": " << error.what() << endl;
                delete ef;
                return false;
            }

            bng::compile::energy::ReactionCenterKey key;
            if (!bng::compile::energy::ReactionCenterKey::parse(
                    pBP->Attribute("reactionCenter"), key)) {
                cerr << "Error: BarrierPattern " << label
                     << " has an unreadable reactionCenter '"
                     << pBP->Attribute("reactionCenter") << "'" << endl;
                delete ef;
                return false;
            }

            string diagnostic;
            if (!barrierTable.add(key, barrierValue, label, diagnostic)) {
                cerr << "Error: " << diagnostic << endl;
                delete ef;
                return false;
            }
            if (verbose)
                cout << "\n\tBarrier pattern " << label << " = " << barrierValue
                     << " on " << key.toString() << endl;
        }
        ef->setBarrierTable(std::move(barrierTable));
    }

    if (verbose)
        cout << "\n\tParsed " << ef->getNumPatterns() << " energy pattern(s) with RT=" << RT
             << ", " << (ef->hasBarriers() ? "with" : "no") << " barrier patterns" << endl;
    s->setEnergyFunction(ef);
    return true;
}

/*
 * Create expanded BasicRxnClass / EnergyRxnClass instances from an energy binding rule.
 */
bool createExpandedBindingReactions(
    const string &rxnName,
    double phi_val,
    double Ea0,
    MoleculeType *molType1, const string &bindSite1,
    MoleculeType *molType2, const string &bindSite2,
    System *s,
    map<string, double> &parameter,
    map<string, int> &allowedStates,
    bool blockSameComplexBinding,
    bool verbose,
    int &reaction_count,
    bool includeReverse,
    const string& energySite1,
    const string& energySite2,
    double drivingWork,
    bool includeForward,
    const ArrheniusRuleContext& ruleContext)
{
    EnergyFunction *ef = s->getEnergyFunction();
    if (!ef) return false;

    string mt1Name = molType1->getName();
    string mt2Name = molType2->getName();
    const string energyBindSite1 = energySite1.empty() ? bindSite1 : energySite1;
    const string energyBindSite2 = energySite2.empty() ? bindSite2 : energySite2;
    const double barrier = ef->barrierForBinding(mt1Name, bindSite1, mt2Name, bindSite2);

    EnergyBindingContext compactContext;
    bool useCompact = ef->getBindingContext(
        mt1Name, energyBindSite1, mt2Name, energyBindSite2, compactContext);
    if (mt1Name == mt2Name) useCompact = false;
    if (!ruleContext.siteConstraints.empty()) useCompact = false;
    if (energyBindSite1 != bindSite1 || energyBindSite2 != bindSite2) useCompact = false;

    if (drivingWork != 0.0) {
        if (verbose && useCompact) {
            cout << "\t  " << rxnName
                 << ": compact energy path disabled (driven rule); "
                 << "using materialized expansion" << endl;
        }
        useCompact = false;
    }
    if (useCompact) {
        int contextReactant = -1;
        for (const auto &condition : compactContext.conditions) {
            if (contextReactant < 0) contextReactant = condition.reactantIdx;
            if (condition.reactantIdx != contextReactant) {
                useCompact = false;
                break;
            }
        }
        for (const auto &term : compactContext.conditionalTerms) {
            if (term.conditionMask == 0) {
                useCompact = false;
                break;
            }
        }
        if (contextReactant != 0) useCompact = false;
    }

    if (useCompact) {
        const double activationRate = std::exp(-(Ea0 + barrier) / ef->getRT());
        if (!std::isfinite(activationRate) || activationRate < 0.0) {
            cerr << "Error: Arrhenius activation rate for " << rxnName
                 << " is not finite and non-negative." << endl;
            return false;
        }
        for (int direction = 0; direction < 2; direction++) {
            const bool isForward = (direction == 0);
            if ((isForward && !includeForward) || (!isForward && !includeReverse)) continue;
            TemplateMolecule *t1 = new TemplateMolecule(molType1);
            TemplateMolecule *t2 = new TemplateMolecule(molType2);
            if (ruleContext.reactantCompartments[0] != nullptr) {
                t1->setCompartment(ruleContext.reactantCompartments[0]);
            }
            if (ruleContext.reactantCompartments[1] != nullptr) {
                t2->setCompartment(ruleContext.reactantCompartments[1]);
            }

            if (isForward) {
                t1->addEmptyComponent(bindSite1);
                t2->addEmptyComponent(bindSite2);
            } else {
                TemplateMolecule::bind(t1, bindSite1, "", t2, bindSite2, "");
            }

            vector<TemplateMolecule *> templates;
            templates.push_back(t1);
            if (isForward) templates.push_back(t2);

            TransformationSet *ts = new TransformationSet(templates);
            if (isForward) ts->addBindingTransform(t1, bindSite1, t2, bindSite2);
            else ts->addUnbindingTransform(t1, bindSite1, t2, bindSite2, true);
            ts->setComplexBookkeeping(blockSameComplexBinding);
            ts->finalize();

            string directionName = rxnName + (isForward ? "_fwd" : "_rev");
            EnergyRxnClass *r = new EnergyRxnClass(
                directionName, activationRate, "", ts, 0, compactContext,
                phi_val, ef->getRT(), isForward, s);
            r->setLiveEnergyExpressions(ruleContext.phiExpr, ruleContext.ea0Expr, barrier);
            if (isForward && !ruleContext.volumeCompartments.empty()) {
                r->setReactantVolumeCompartments(ruleContext.volumeCompartments);
            }

            s->addReaction(r);
            reaction_count++;

            if (verbose) {
                cout << "\t  Created compact "
                     << (isForward ? "forward" : "reverse")
                     << " rule: " << directionName
                     << " (mapping-local Arrhenius context)" << endl;
            }
        }
        return true;
    }

    auto mapCompName = [&](int rIdx, const std::string &cName) -> std::string {
        if (rIdx == 0 && !energySite1.empty() && energyBindSite1 != bindSite1 && cName == bindSite1)
            return energyBindSite1;
        if (rIdx == 1 && !energySite2.empty() && energyBindSite2 != bindSite2 && cName == bindSite2)
            return energyBindSite2;
        return cName;
    };

    vector<ExpandedRuleInfo> expanded = ef->expandBindingRule(
        rxnName, Ea0, phi_val, mt1Name, energyBindSite1, mt2Name, energyBindSite2,
        drivingWork);

    for (const auto &rule : expanded) {
        if ((rule.isForward && !includeForward) || (!rule.isForward && !includeReverse)) continue;
        if (!variantCompatibleWithRuleContext(rule, ruleContext, mapCompName)) continue;
        if (!std::isfinite(rule.rate) || rule.rate < 0.0) {
            cerr << "Error: Arrhenius rate for " << rule.name << " is not finite and non-negative." << endl;
            return false;
        }
        TemplateMolecule *t1 = new TemplateMolecule(molType1);
        TemplateMolecule *t2 = new TemplateMolecule(molType2);
        std::vector<TemplateMolecule*> ownedPartners;
        TransformationSet *ts = nullptr;
        try {
            if (ruleContext.reactantCompartments[0] != nullptr) {
                t1->setCompartment(ruleContext.reactantCompartments[0]);
            }
            if (ruleContext.reactantCompartments[1] != nullptr) {
                t2->setCompartment(ruleContext.reactantCompartments[1]);
            }

            if (rule.isForward) {
                t1->addEmptyComponent(bindSite1);
                t2->addEmptyComponent(bindSite2);
            } else {
                TemplateMolecule::bind(t1, bindSite1, "", t2, bindSite2, "");
            }

            if (!applyConstraintsToTemplates(rule, ruleContext, t1, t2, s, mapCompName, ownedPartners)) {
                for (auto *p : ownedPartners) delete p;
                delete t1;
                delete t2;
                return false;
            }

            vector<TemplateMolecule *> templates;
            templates.push_back(t1);
            if (rule.isForward) templates.push_back(t2);

            ts = new TransformationSet(templates);
            if (rule.isForward) ts->addBindingTransform(t1, bindSite1, t2, bindSite2);
            else ts->addUnbindingTransform(t1, bindSite1, t2, bindSite2, true);
            ts->setComplexBookkeeping(blockSameComplexBinding);
            ts->finalize();
        } catch (const std::exception &) {
            delete ts;
            for (auto *p : ownedPartners) delete p;
            delete t1;
            delete t2;
            return false;
        }

        double rate = rule.rate;
        BasicRxnClass *r = new BasicRxnClass(rule.name, rate, "", ts, s);
        attachLiveArrheniusRateExpression(
            r, s, rule.isForward, phi_val, Ea0, barrier, drivingWork, ef->getRT(),
            rule.activePatternContributions, ruleContext);
        if (rule.isForward && !ruleContext.volumeCompartments.empty()) {
            r->setReactantVolumeCompartments(ruleContext.volumeCompartments);
        }

        s->addReaction(r);
        reaction_count++;

        if (verbose) {
            cout << "\t  Created " << (rule.isForward ? "forward" : "reverse")
                 << " rule: " << rule.name << "  rate=" << rate << endl;
        }
    }
    return true;
}

/*
 * Create expanded BasicRxnClass instances from an energy state-change rule.
 */
bool createExpandedStateChangeReactions(
    const string &rxnName,
    double phi_val,
    double Ea0,
    MoleculeType *molType,
    const string &component,
    const string &stateFrom,
    const string &stateTo,
    System *s,
    bool blockSameComplexBinding,
    bool verbose,
    int &reaction_count,
    bool includeReverse,
    const string& energyComponent,
    double drivingWork,
    const ArrheniusRuleContext& ruleContext)
{
    EnergyFunction *ef = s->getEnergyFunction();
    if (!ef || !molType || stateFrom.empty() || stateTo.empty()) return false;

    const string energyStateComponent =
        energyComponent.empty() ? component : energyComponent;
    const double barrier = ef->barrierForStateChange(
        molType->getName(), energyStateComponent, stateFrom, stateTo);

    auto mapCompName = [&](int rIdx, const std::string &cName) -> std::string {
        if (rIdx == 0 && !energyComponent.empty() && energyStateComponent != component && cName == component)
            return energyStateComponent;
        return cName;
    };

    vector<ExpandedRuleInfo> expanded = ef->expandStateChangeRule(
        rxnName, Ea0, phi_val, molType->getName(), energyStateComponent,
        stateFrom, stateTo, drivingWork);

    bool createdAny = false;
    for (const auto &rule : expanded) {
        if (!includeReverse && !rule.isForward) continue;
        if (!variantCompatibleWithRuleContext(rule, ruleContext, mapCompName)) continue;
        const string &fromState = rule.isForward ? stateFrom : stateTo;
        const string &toState = rule.isForward ? stateTo : stateFrom;
        if (molType->isEquivalentComponent(component)) return false;

        TemplateMolecule *t = new TemplateMolecule(molType);
        std::vector<TemplateMolecule*> ownedPartners;
        TransformationSet *ts = nullptr;
        try {
            if (ruleContext.reactantCompartments[0] != nullptr) {
                t->setCompartment(ruleContext.reactantCompartments[0]);
            }
            t->addComponentConstraint(component, fromState);
            if (!applyConstraintsToTemplates(rule, ruleContext, t, nullptr, s, mapCompName, ownedPartners)) {
                for (auto *p : ownedPartners) delete p;
                delete t;
                return false;
            }

            vector<TemplateMolecule *> templates {t};
            ts = new TransformationSet(templates);
            if (!ts->addStateChangeTransform(t, component, toState)) {
                delete ts;
                for (auto *p : ownedPartners) delete p;
                delete t;
                return false;
            }
            ts->setComplexBookkeeping(blockSameComplexBinding);
            ts->finalize();
        } catch (const std::exception &) {
            delete ts;
            for (auto *p : ownedPartners) delete p;
            delete t;
            return false;
        }

        if (!std::isfinite(rule.rate) || rule.rate < 0.0) {
            delete ts;
            for (auto *p : ownedPartners) delete p;
            delete t;
            return false;
        }
        auto *reaction = new BasicRxnClass(rule.name, rule.rate, "", ts, s);
        attachLiveArrheniusRateExpression(
            reaction, s, rule.isForward, phi_val, Ea0, barrier, drivingWork, ef->getRT(),
            rule.activePatternContributions, ruleContext);
        s->addReaction(reaction);
        ++reaction_count;
        createdAny = true;

        if (verbose) {
            cout << "\t  Created " << (rule.isForward ? "forward" : "reverse")
                 << " state-change rule: " << rule.name << "  rate=" << rule.rate << endl;
        }
    }
    return createdAny || !expanded.empty();
}

} // namespace NFinput
