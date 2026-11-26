#include "RxnList.hpp"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <utility>

namespace bng::ast {

namespace {

bool keepOriginRuleInSignature(const Rxn& reaction) {
    if (reaction.getRateLaw().find("|local:") != std::string::npos) {
        return true;
    }
    if (const auto& rateExpr = reaction.getRateExpression();
        rateExpr.has_value() && rateExpr->kind() == ExpressionKind::Function) {
        std::string lower = rateExpr->name();
        std::transform(lower.begin(), lower.end(), lower.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (lower == "arrhenius" || lower == "functionproduct") {
            return true;
        }
    }
    return false;
}

std::string reactionSignature(const Rxn& reaction) {
    std::ostringstream out;
    // Sort reactants for deduplication (order in Rxn is preserved for output)
    auto sortedReactants = reaction.getReactants();
    std::sort(sortedReactants.begin(), sortedReactants.end());
    for (std::size_t i = 0; i < sortedReactants.size(); ++i) {
        if (i != 0) {
            out << ",";
        }
        out << sortedReactants[i];
    }
    out << "->";
    // Sort products for deduplication (same as reactants)
    auto sortedProducts = reaction.getProducts();
    std::sort(sortedProducts.begin(), sortedProducts.end());
    for (std::size_t i = 0; i < sortedProducts.size(); ++i) {
        if (i != 0) {
            out << ",";
        }
        out << sortedProducts[i];
    }
    out << "@" << reaction.getRateLaw();
    out << "@totalRate=" << reaction.isTotalRate();
    out << "@absoluteFlux=" << reaction.isAbsoluteFlux();
    if (reaction.getDelayExpression()) {
        out << "@delay=" << reaction.getDelayExpression()->toString()
            << (reaction.isNonConsuming() ? ":nonconsuming" : ":consuming");
    }
    // Fold byte-identical reactions across rules when their rate laws are
    // structurally equivalent (matching BNG2 RxnList::add / RateLaw::equivalent,
    // RuleWorld/bionetgen 3513bca766). Conservatively preserve rule boundaries
    // for per-rule local contexts, Arrhenius, and FunctionProduct rates.
    if (keepOriginRuleInSignature(reaction) && !reaction.getOriginRuleName().empty()) {
        out << "#" << reaction.getOriginRuleName();
    }
    return out.str();
}

} // namespace

bool RxnList::add(Rxn reaction) {
    // BNG2 (Perl2/RxnList.pm::add) drops null reactions whose reactant and
    // product multisets are identical (e.g. a wildcard-state rule matching
    // a species already in the target state, as in Hawse_full). Skip before
    // dedup so generated and loaded networks match Perl on both paths.
    // Zero-effect rules (0 -> 0, from SBML import of empty reactions) are
    // exempt: BNG3 deliberately preserves them as rate-carrying no-ops.
    auto sortedReactants = reaction.getReactants();
    auto sortedProducts = reaction.getProducts();
    std::sort(sortedReactants.begin(), sortedReactants.end());
    std::sort(sortedProducts.begin(), sortedProducts.end());
    if (!sortedReactants.empty() && sortedReactants == sortedProducts) return false;
    const auto signature = reactionSignature(reaction);
    const auto existing = indexBySignature_.find(signature);
    if (existing != indexBySignature_.end()) {
        if (std::getenv("BNG_DEBUG_FACTORS")) {
            std::cerr << "[FACTOR] Merging dup: sig=" << signature
                      << " existing_factor=" << reactions_[existing->second].getFactor()
                      << " + incoming=" << reaction.getFactor()
                      << " rule=" << reaction.getOriginRuleName() << "\n";
        }
        reactions_[existing->second].addFactor(reaction.getFactor());
        reactions_[existing->second].addOriginRuleName(reaction.getOriginRuleName());
        return false;
    }
    indexBySignature_[signature] = reactions_.size();
    reactions_.push_back(std::move(reaction));
    return true;
}

bool RxnList::containsLabel(const std::string& label) const {
    for (const auto& reaction : reactions_) {
        if (reaction.getLabel() == label) {
            return true;
        }
    }
    return false;
}

std::size_t RxnList::size() const {
    return reactions_.size();
}

const std::vector<Rxn>& RxnList::all() const {
    return reactions_;
}

} // namespace bng::ast
