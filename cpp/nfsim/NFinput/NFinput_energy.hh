/*
 * NFinput_energy.hh
 *
 * Declarations for energy pattern parsing and Arrhenius rule expansion.
 * Called from NFinput.cpp, NFinput_fromAst.cpp, and NFinput_reactions_fromCompiled.cpp.
 */

#ifndef NFINPUT_ENERGY_HH_
#define NFINPUT_ENERGY_HH_

#include "../NFcore/NFcore.hh"
#include "../NFcore/energyPattern.hh"
#include "TinyXML/tinyxml.h"

#include <functional>
#include <map>
#include <string>
#include <vector>

namespace NFinput {

    /*
     * Rule-level site constraint (state or bond occupancy) preserved across
     * Arrhenius rule expansion (ETH-07).
     */
    struct ArrheniusRuleSiteConstraint {
        int reactantIdx = 0;       // 0 or 1
        std::string compName;      // concrete component name on reactant
        std::string stateName;     // non-empty if rule requires exact state
        bool requireEmpty = false; // true if rule requires unbound site
        bool requireBound = false; // true if rule requires !+ bound site
    };

    /*
     * Optional rule-level context forwarded into Arrhenius expansion:
     *   - siteConstraints: extra state/bond constraints on reactants (ETH-07)
     *   - reactantCompartments: reactant compartment matching constraints (ETH-06)
     *   - volumeCompartments: compartment(s) for forward bimolecular 1/V scaling (ETH-06)
     *   - phiExpr / ea0Expr / drivingWorkExpr: live parameter evaluators for RNF set/update (NFC-14)
     */
    struct ArrheniusRuleContext {
        std::vector<ArrheniusRuleSiteConstraint> siteConstraints;
        NFcore::Compartment *reactantCompartments[2] = {nullptr, nullptr};
        std::vector<NFcore::Compartment*> volumeCompartments;
        std::function<double()> phiExpr;
        std::function<double()> ea0Expr;
        std::function<double()> drivingWorkExpr;
    };

    /*
     * Evaluate a parameter-dependent energy/rate expression via mu::Parser.
     */
    double evaluateEnergyExpression(
        const std::string &expression,
        std::map<std::string, double> &parameters);

    /*
     * Parse <ListOfEnergyPatterns> from the model XML.
     * Creates an EnergyFunction on the System if patterns exist.
     * Call this AFTER initParameters() and BEFORE initReactionRules().
     */
    bool parseEnergyPatterns(
        TiXmlElement *pModel,
        NFcore::System *s,
        std::map<std::string, double> &parameter,
        bool verbose);

    /*
     * Create expanded BasicRxnClass / EnergyRxnClass instances for a binding energy rule.
     */
    bool createExpandedBindingReactions(
        const std::string &rxnName,
        double phi_val,
        double Ea0,
        NFcore::MoleculeType *molType1, const std::string &bindSite1,
        NFcore::MoleculeType *molType2, const std::string &bindSite2,
        NFcore::System *s,
        std::map<std::string, double> &parameter,
        std::map<std::string, int> &allowedStates,
        bool blockSameComplexBinding,
        bool verbose,
        int &reaction_count,
        bool includeReverse,
        const std::string& energySite1 = "",
        const std::string& energySite2 = "",
        double drivingWork = 0.0,
        bool includeForward = true,
        const ArrheniusRuleContext& ruleContext = {});

    /*
     * Create expanded BasicRxnClass instances for an energy state-change rule.
     */
    bool createExpandedStateChangeReactions(
        const std::string &rxnName,
        double phi_val,
        double Ea0,
        NFcore::MoleculeType *molType,
        const std::string &component,
        const std::string &stateFrom,
        const std::string &stateTo,
        NFcore::System *s,
        bool blockSameComplexBinding,
        bool verbose,
        int &reaction_count,
        bool includeReverse,
        const std::string& energyComponent = "",
        double drivingWork = 0.0,
        const ArrheniusRuleContext& ruleContext = {});

} // namespace NFinput

#endif /* NFINPUT_ENERGY_HH_ */
