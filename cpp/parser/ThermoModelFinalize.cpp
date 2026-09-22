#include "ThermoModelFinalize.hpp"

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <utility>
#include <vector>

#include "ThermoSourceNormalization.hpp"
#include "ast/BarrierPattern.hpp"
#include "ast/Model.hpp"
#include "ast/ReactionRule.hpp"

namespace bng::parser {

namespace {

// The visitor stores a rule label as the raw label_def text, which includes
// the trailing colon. Strip it before matching the synthetic prefix so both
// spellings resolve.
std::string normalizedLabel(const ast::ReactionRule& rule) {
    auto label = rule.getLabel();
    if (!label.empty() && label.back() == ':') label.pop_back();
    return label;
}

// `__bng3_barrier_` is a reserved namespace. Any label in it is treated as
// synthetic, including a malformed one with a missing or non-numeric index:
// that then fails closed in the index check below rather than quietly
// surviving as an ordinary rule with a reserved name.
bool isBarrierLabel(const std::string& label) {
    const std::string prefix = kBarrierRuleLabelPrefix;
    return label.size() >= prefix.size() &&
           label.compare(0, prefix.size(), prefix) == 0;
}

} // namespace

bool finalizeThermodynamicMetadata(
    ast::Model& model,
    const std::map<std::size_t, std::string>& barrierLabels,
    const std::map<std::size_t, std::string>& drivingWork,
    const ExpressionParser& parseExpression) {
    auto& rules = model.getReactionRules();

    const bool sawBarrierRule = std::any_of(
        rules.begin(), rules.end(), [](const ast::ReactionRule& rule) {
            return isBarrierLabel(normalizedLabel(rule));
        });

    // An ordinary model must come out byte-identical: no renumbering, no
    // reordering, no rule list reassignment.
    if (!sawBarrierRule && drivingWork.empty() && barrierLabels.empty()) {
        return false;
    }

    struct PendingBarrier {
        std::size_t index = 0;
        ast::ReactionRule rule;
    };

    std::vector<ast::ReactionRule> ordinary;
    std::vector<PendingBarrier> barriers;
    ordinary.reserve(rules.size());
    for (auto& rule : rules) {
        const auto label = normalizedLabel(rule);
        if (!isBarrierLabel(label)) {
            ordinary.push_back(std::move(rule));
            continue;
        }

        const std::string prefix = kBarrierRuleLabelPrefix;
        const auto digits = label.substr(prefix.size());
        // Covers both an absent index ("__bng3_barrier_") and a non-numeric
        // one ("__bng3_barrier_x").
        if (digits.empty() ||
            !std::all_of(digits.begin(), digits.end(), [](unsigned char value) {
                return std::isdigit(value) != 0;
            })) {
            throw std::runtime_error(
                "malformed synthetic barrier-pattern label '" + label + "'");
        }
        std::size_t barrierIndex = 0;
        try {
            barrierIndex = static_cast<std::size_t>(std::stoull(digits));
        } catch (const std::exception&) {
            throw std::runtime_error(
                "synthetic barrier-pattern index out of range in '" + label + "'");
        }

        // A barrier needs exactly one transition-state energy. Zero would make
        // it a silent no-op; two would mean a rate pair, which is meaningless
        // for a symmetric transition state.
        if (rule.getRates().size() != 1) {
            throw std::runtime_error(
                "barrier pattern " + std::to_string(barrierIndex) +
                " requires exactly one transition-state energy expression");
        }
        barriers.push_back(PendingBarrier{barrierIndex, std::move(rule)});
    }

    // Attach reservoir work by position among ordinary rules. An out-of-range
    // index means the normalizer and the visitor disagreed about rule order,
    // which must surface rather than drop the annotation.
    for (const auto& [index, expressionText] : drivingWork) {
        if (index >= ordinary.size()) {
            throw std::runtime_error(
                "driven_by annotation refers to reaction rule index " +
                std::to_string(index) + " but the model has " +
                std::to_string(ordinary.size()) + " ordinary reaction rule(s)");
        }
        if (!parseExpression) {
            throw std::runtime_error(
                "no expression parser available for a driven_by() annotation");
        }
        try {
            ordinary[index].setDrivingWorkExpression(parseExpression(expressionText));
        } catch (const std::exception& error) {
            throw std::runtime_error("cannot parse driven_by() work expression '" +
                                     expressionText + "': " + error.what());
        }
    }

    for (std::size_t index = 0; index < ordinary.size(); ++index) {
        ordinary[index].setRuleName("R" + std::to_string(index + 1));
    }
    rules = std::move(ordinary);

    std::sort(barriers.begin(), barriers.end(),
              [](const PendingBarrier& left, const PendingBarrier& right) {
                  return left.index < right.index;
              });
    for (std::size_t position = 0; position < barriers.size(); ++position) {
        if (position != 0 &&
            barriers[position].index == barriers[position - 1].index) {
            throw std::runtime_error("duplicate synthetic barrier-pattern index " +
                                     std::to_string(barriers[position].index));
        }
        auto& pending = barriers[position];
        const auto label = barrierLabels.find(pending.index);
        pending.rule.setRuleName("B" + std::to_string(position + 1));
        model.addBarrierPattern(ast::BarrierPattern(
            label == barrierLabels.end() ? std::string() : label->second,
            std::move(pending.rule)));
    }

    // A label annotation with no matching barrier rule means metadata was lost
    // between normalization and parsing.
    for (const auto& [index, label] : barrierLabels) {
        const bool matched = std::any_of(
            barriers.begin(), barriers.end(),
            [index = index](const PendingBarrier& pending) {
                return pending.index == index;
            });
        if (!matched) {
            throw std::runtime_error("barrier-pattern label '" + label +
                                     "' refers to missing barrier index " +
                                     std::to_string(index));
        }
    }

    return true;
}

} // namespace bng::parser
