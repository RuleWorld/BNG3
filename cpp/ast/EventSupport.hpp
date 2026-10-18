#pragma once

#include "Model.hpp"
#include <set>
#include <cmath>
#include <stdexcept>

namespace bng::ast {

// The first native slice has no queue: one immediate event, with a continuous
// scalar threshold and simultaneous assignments to species observables.
inline void validateNativeEventSubset(const Model& model) {
    if (!model.getEventFormatVersion()) return;
    const auto fail = [](const std::string& reason) {
        throw std::runtime_error(std::string(kUnsupportedEventExecutionMessage) + ": " + reason);
    };
    if (model.getEvents().size() != 1) fail("exactly one immediate event is supported");
    const auto& event = model.getEvents().front();
    if (event.delay || event.priority) fail("delay and priority are unsupported");
    const auto& trigger = event.trigger;
    if (trigger.kind() != ExpressionKind::Binary || trigger.args().size() != 2 ||
        (trigger.name() != ">" && trigger.name() != ">=" &&
         trigger.name() != "<" && trigger.name() != "<=")) {
        fail("trigger must be a continuous scalar inequality");
    }
    const auto dynamicIdentifier = [&](const Expression& expression) {
        if (expression.kind() != ExpressionKind::Identifier) return false;
        if (expression.name() == "time") return true;
        for (const auto& observable : model.getObservables()) {
            if (observable.getName() == expression.name()) return true;
        }
        return false;
    };
    const bool leftDynamic = dynamicIdentifier(trigger.args()[0]);
    const bool rightDynamic = dynamicIdentifier(trigger.args()[1]);
    if (leftDynamic == rightDynamic) {
        fail("trigger requires one time or species observable against a static threshold");
    }
    const auto& threshold = trigger.args()[leftDynamic ? 1 : 0];
    for (const auto& name : threshold.getDependencies()) {
        if (name == "time") fail("event threshold must be static");
        for (const auto& observable : model.getObservables()) {
            if (observable.getName() == name) fail("event threshold must be static");
        }
        try {
            if (model.getParameters().isTimeDependent(name)) fail("event threshold must be static");
        } catch (const std::exception&) { fail("event threshold requires static parameters"); }
    }
    std::set<std::string> visiting;
    std::function<void(const Expression&)> continuous = [&](const Expression& expression) {
        if (expression.kind() == ExpressionKind::Number) {
            if (!std::isfinite(expression.numberValue())) fail("nonfinite event expression");
            return;
        }
        if (expression.kind() == ExpressionKind::Identifier) {
            const auto& name = expression.name();
            if (name == "time") return;
            for (const auto& observable : model.getObservables()) {
                if (observable.getName() == name) return;
            }
            if (!visiting.insert(name).second) fail("recursive event parameter");
            try { continuous(model.getParameters().get(name).getExpression()); }
            catch (const std::exception&) { fail("unknown or unsupported event identifier " + name); }
            visiting.erase(name);
            return;
        }
        if ((expression.kind() == ExpressionKind::Unary &&
             (expression.name() == "+" || expression.name() == "-")) ||
            (expression.kind() == ExpressionKind::Binary &&
             (expression.name() == "+" || expression.name() == "-" || expression.name() == "*"))) {
            for (const auto& child : expression.args()) continuous(child);
            return;
        }
        fail("only continuous polynomial event expressions are supported");
    };
    continuous(trigger.args()[0]);
    continuous(trigger.args()[1]);
    std::set<std::string> targets;
    for (const auto& assignment : event.assignments) {
        if (!targets.insert(assignment.target).second) fail("duplicate assignment target");
        bool found = false;
        for (const auto& observable : model.getObservables()) {
            found = found || observable.getName() == assignment.target;
        }
        if (!found) fail("assignment target must be a species observable");
        continuous(assignment.value);
    }
    if (targets.empty()) fail("event requires an assignment");
}

} // namespace bng::ast
