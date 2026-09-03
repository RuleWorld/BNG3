/*
 * NFinput_energy.cpp
 *
 * Integration between the energy rule expansion engine and NFsim's
 * XML input pipeline. Contains:
 *   - parseEnergyPatterns(): reads <ListOfEnergyPatterns> from XML
 *   - createExpandedBindingReactions(): builds BasicRxnClass instances from
 *     expanded energy rules
 *
 * These are called from NFinput.cpp at the appropriate points in
 * the parsing pipeline.
 */

#include "../NFcore/NFcore.hh"
#include "../NFcore/energyPattern.hh"
#include "../NFreactions/reactions/reaction.hh"
#include "NFinput.hh"
#include "TinyXML/tinyxml.h"

#include <map>
#include <string>
#include <vector>
#include <iostream>
#include <cmath>

using namespace std;
using namespace NFcore;


namespace NFinput {

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
    if (!pList) return true;

    if (verbose) cout << "\n\tReading list of Energy Patterns..." << endl;

    double phi = 0.5;
    double RT = 2.478;

    if (parameter.find("phi") != parameter.end())
        phi = parameter.find("phi")->second;
    if (parameter.find("RT") != parameter.end())
        RT = parameter.find("RT")->second;

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
        if (parameter.find(epExpr) != parameter.end()) {
            energyVal = parameter.find(epExpr)->second;
        } else {
            try { energyVal = NFutil::convertToDouble(epExpr); }
            catch (...) {
                cerr << "Error: cannot resolve energy '" << epExpr << "' for pattern " << epId << endl;
                delete ef;
                return false;
            }
        }

        EnergyPatternInfo epInfo;
        epInfo.id = epId;
        epInfo.energyValue = energyVal;

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
                    ci.isBound = (numBonds != "0" && numBonds != "");
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
                }
            }
        }
        ef->addEnergyPattern(epInfo);
    }

    if (verbose)
        cout << "\n\tParsed " << ef->getNumPatterns() << " energy pattern(s) with RT=" << RT << endl;
    s->setEnergyFunction(ef);
    return true;
}

/*
 * Create expanded BasicRxnClass instances from an energy binding rule.
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
    bool includeReverse)
{
    EnergyFunction *ef = s->getEnergyFunction();
    if (!ef) return false;

    string mt1Name = molType1->getName();
    string mt2Name = molType2->getName();

    /* A factorized context can be evaluated from the selected reaction
     * mapping. Keep the legacy materialized expansion for contexts that span
     * both reactants or whose energy pattern needs multiple conditions
     * simultaneously; those cases need a more general representation. */
    EnergyBindingContext compactContext;
    bool useCompact = ef->getBindingContext(
        mt1Name, bindSite1, mt2Name, bindSite2, compactContext);
    if (mt1Name == mt2Name) useCompact = false;
    if (useCompact) {
        int contextReactant = -1;
        for (const auto &condition : compactContext.conditions) {
            if (contextReactant < 0) contextReactant = condition.reactantIdx;
            if (condition.reactantIdx != contextReactant) {
                useCompact = false;
                break;
            }
        }

        /* A compact term may be gated by a conjunction of occupancy
         * predicates on the selected weighted molecule. */
        for (const auto &term : compactContext.conditionalTerms) {
            if (term.conditionMask == 0) {
                useCompact = false;
                break;
            }
        }

        /* Restrict the initial compact path to contexts on reactant 0 so
         * both directions use the same direct molecule mapping without
         * changing any other Arrhenius behavior. */
        if (contextReactant != 0) useCompact = false;
    }

    if (useCompact) {
        for (int direction = 0; direction < 2; direction++) {
            const bool isForward = (direction == 0);
            if (!includeReverse && !isForward) continue;
            TemplateMolecule *t1 = new TemplateMolecule(molType1);
            TemplateMolecule *t2 = new TemplateMolecule(molType2);

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
            else ts->addUnbindingTransform(t1, bindSite1, t2, bindSite2);
            ts->setComplexBookkeeping(blockSameComplexBinding);
            ts->finalize();

            /* Pull out the activation-only term as DOR's base rate. The
             * EnergyRxnClass supplies the context factor for each mapping. */
            double activationRate = std::exp(-Ea0 / ef->getRT());
            string directionName = rxnName + (isForward ? "_fwd" : "_rev");
            EnergyRxnClass *r = new EnergyRxnClass(
                directionName, activationRate, "", ts, 0, compactContext,
                phi_val, ef->getRT(), isForward, s);

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

    // Run the legacy expansion algorithm for non-factorized contexts.
    vector<ExpandedRuleInfo> expanded = ef->expandBindingRule(
        rxnName, Ea0, phi_val, mt1Name, bindSite1, mt2Name, bindSite2);

    for (const auto &rule : expanded) {
        if (!includeReverse && !rule.isForward) continue;
        TemplateMolecule *t1, *t2;

        if (rule.isForward) {
            t1 = new TemplateMolecule(molType1);
            t1->addEmptyComponent(bindSite1);
            t2 = new TemplateMolecule(molType2);
            t2->addEmptyComponent(bindSite2);
        } else {
            t1 = new TemplateMolecule(molType1);
            t2 = new TemplateMolecule(molType2);
            TemplateMolecule::bind(t1, bindSite1, "", t2, bindSite2, "");
        }

        for (const auto &cc : rule.constraints) {
            TemplateMolecule *target = (cc.reactantIdx == 0) ? t1 : t2;
            if (cc.mustBeBound) target->addBoundComponent(cc.compName);
            else target->addEmptyComponent(cc.compName);
        }

        vector<TemplateMolecule *> templates;
        templates.push_back(t1);
        if (rule.isForward) templates.push_back(t2);

        TransformationSet *ts = new TransformationSet(templates);
        if (rule.isForward) ts->addBindingTransform(t1, bindSite1, t2, bindSite2);
        else ts->addUnbindingTransform(t1, bindSite1, t2, bindSite2);

        // Wire complex bookkeeping for blockSameComplexBinding flag
        ts->setComplexBookkeeping(blockSameComplexBinding);

        ts->finalize();

        // Rate is already correctly calculated inside expandBindingRule using phi
        double rate = rule.rate;
        BasicRxnClass *r = new BasicRxnClass(rule.name, rate, "", ts, s);
        
        // Register with system!
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
    bool includeReverse)
{
    EnergyFunction *ef = s->getEnergyFunction();
    if (!ef || !molType || stateFrom.empty() || stateTo.empty()) return false;

    vector<ExpandedRuleInfo> expanded = ef->expandStateChangeRule(
        rxnName, Ea0, phi_val, molType->getName(), component, stateFrom, stateTo);

    for (const auto &rule : expanded) {
        if (!includeReverse && !rule.isForward) continue;
        const string &fromState = rule.isForward ? stateFrom : stateTo;
        const string &toState = rule.isForward ? stateTo : stateFrom;
        if (molType->isEquivalentComponent(component)) return false;

        TemplateMolecule *t = new TemplateMolecule(molType);
        TransformationSet *ts = nullptr;
        try {
            t->addComponentConstraint(component, fromState);
            for (const auto &constraint : rule.constraints) {
                if (constraint.reactantIdx != 0 ||
                    molType->isEquivalentComponent(constraint.compName)) {
                    delete t;
                    return false;
                }
                if (constraint.mustBeBound) t->addBoundComponent(constraint.compName);
                else t->addEmptyComponent(constraint.compName);
            }

            vector<TemplateMolecule *> templates {t};
            ts = new TransformationSet(templates);
            if (!ts->addStateChangeTransform(t, component, toState)) {
                delete ts;
                delete t;
                return false;
            }
            ts->setComplexBookkeeping(blockSameComplexBinding);
            ts->finalize();
        } catch (const std::exception &) {
            delete ts;
            delete t;
            return false;
        }

        if (!std::isfinite(rule.rate) || rule.rate < 0.0) {
            delete ts;
            delete t;
            return false;
        }
        auto *reaction = new BasicRxnClass(rule.name, rule.rate, "", ts, s);
        s->addReaction(reaction);
        ++reaction_count;

        if (verbose) {
            cout << "\t  Created " << (rule.isForward ? "forward" : "reverse")
                 << " state-change rule: " << rule.name << "  rate=" << rule.rate << endl;
        }
    }
    return !expanded.empty();
}

} // namespace NFinput
