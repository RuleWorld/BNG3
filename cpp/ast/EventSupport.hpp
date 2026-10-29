#pragma once

#include "Model.hpp"
#include "ModelFunctionEvaluator.hpp"
#include <set>
#include <cmath>
#include <stdexcept>

namespace bng::ast {

// The native event runtime executes the events of a model: each event has a
// continuous scalar trigger, an optional constant delay, a priority that
// orders the events executed at the same instant, and assignments to species
// observables.
inline void validateNativeEventSubset(const Model& model) {
    if (!model.getEventFormatVersion()) return;
    const auto fail = [](const std::string& reason) {
        throw std::runtime_error(std::string(kUnsupportedEventExecutionMessage) + ": " + reason);
    };
    if (model.getEvents().empty()) fail("at least one event is required");
    const ModelFunctionEvaluator functionEvaluator(model);
    for (const auto& event : model.getEvents()) {
    const auto trigger = functionEvaluator.expandFunctions(event.trigger);
    // A trigger is a continuous inequality or a conjunction of comparisons.
    // Equality is supported only as a discrete gate within a conjunction.
    const bool hasConjunction = trigger.kind() == ExpressionKind::Binary &&
                                trigger.name() == "&&";
    std::function<void(const Expression&)> checkTrigger = [&](const Expression& expression) {
        if (expression.kind() != ExpressionKind::Binary) {
            fail("trigger must be a continuous scalar inequality");
        }
        if (expression.name() == "&&") {
            for (const auto& child : expression.args()) checkTrigger(child);
            return;
        }
        if (expression.name() != "==" && expression.name() != ">" &&
            expression.name() != ">=" &&
            expression.name() != "<" && expression.name() != "<=") {
            fail("trigger must be a continuous scalar inequality");
        }
        if (expression.name() == "==" && !hasConjunction) {
            fail("standalone equality trigger is outside the native event subset");
        }
        if (expression.args().size() != 2) {
            fail("trigger must compare two quantities");
        }
    };
    checkTrigger(trigger);
    const auto dynamicIdentifier = [&](const Expression& expression) {
        if (expression.kind() != ExpressionKind::Identifier) return false;
        if (expression.name() == "time") return true;
        for (const auto& observable : model.getObservables()) {
            if (observable.getName() == expression.name()) return true;
        }
        return false;
    };
    const auto dynamicDelayedExpression = [&](const Expression& expression) {
        if (expression.kind() != ExpressionKind::Function ||
            expression.name() != "delay" || expression.args().size() != 2) {
            return false;
        }
        for (const auto& dependency : expression.args()[0].getDependencies()) {
            if (dependency == "time") return true;
            for (const auto& observable : model.getObservables()) {
                if (observable.getName() == dependency) return true;
            }
        }
        return false;
    };
    std::function<bool(const Expression&)> dynamicSide = [&](const Expression& expression) {
        if (dynamicIdentifier(expression) || dynamicDelayedExpression(expression)) {
            return true;
        }
        for (const auto& child : expression.args()) {
            if (dynamicSide(child)) return true;
        }
        return false;
    };
    // Every conjunct of the trigger has to compare a time or species
    // observable against a static threshold or another observable.
    std::function<void(const Expression&)> checkSides = [&](const Expression& expression) {
        if (expression.kind() == ExpressionKind::Binary && expression.name() == "&&") {
            for (const auto& child : expression.args()) checkSides(child);
            return;
        }
        const bool leftDynamic = dynamicSide(expression.args()[0]);
        const bool rightDynamic = dynamicSide(expression.args()[1]);
        if (!leftDynamic && !rightDynamic) {
            fail("trigger requires one time or species observable against a static threshold");
        }
        // A side that is not itself a bare time or species observable has to be
        // a static threshold: a mixed expression such as ``time - 1`` would make
        // the crossing surface time-dependent in a way the runtime cannot
        // classify.  Two bare observables are allowed: a difference of two
        // species is a continuous state surface like any other.
        for (std::size_t side = 0; side < 2; ++side) {
            if (side == 0 ? leftDynamic : rightDynamic) continue;
            for (const auto& name : expression.args()[side].getDependencies()) {
                if (name == "time") fail("event threshold must be static");
                for (const auto& observable : model.getObservables()) {
                    if (observable.getName() == name) fail("event threshold must be static");
                }
                try {
                    if (model.getParameters().isTimeDependent(name)) fail("event threshold must be static");
                } catch (const std::exception&) { fail("event threshold requires static parameters"); }
            }
        }
    };
    checkSides(trigger);
    std::set<std::string> visiting;
    bool allowDistributionAssignment = false;
    std::function<void(const Expression&)> continuous = [&](const Expression& expression) {
        if (expression.kind() == ExpressionKind::Function &&
            (expression.name() == "abs" || expression.name() == "floor") &&
            expression.args().size() == 1) {
            continuous(expression.args().front());
            return;
        }
        if (expression.kind() == ExpressionKind::Number) {
            if (!std::isfinite(expression.numberValue())) fail("nonfinite event expression");
            return;
        }
        if (expression.kind() == ExpressionKind::Identifier) {
            const auto& name = expression.name();
            if (name == "time" || name == "t") return;
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
             (expression.name() == "+" || expression.name() == "-" ||
              expression.name() == "*" || expression.name() == "/" ||
              expression.name() == "^" || expression.name() == "**"))) {
            if (expression.kind() == ExpressionKind::Binary &&
                expression.name() == "/") {
                const auto& denominator = expression.args()[1];
                if (dynamicSide(denominator) ||
                    model.getParameters().expressionIsTimeDependent(denominator)) {
                    fail("event division requires a static nonzero denominator");
                }
                const double value = denominator.evaluate([&](const std::string& name) {
                    return model.getParameters().evaluate(name);
                });
                if (!std::isfinite(value) || value == 0.0) {
                    fail("event division requires a static nonzero denominator");
                }
            }
            for (const auto& child : expression.args()) continuous(child);
            return;
        }
        if (dynamicDelayedExpression(expression)) {
            for (const auto& name : expression.args()[1].getDependencies()) {
                if (name == "time") fail("delay expression duration must be static");
                for (const auto& observable : model.getObservables()) {
                    if (observable.getName() == name) {
                        fail("delay expression duration must be static");
                    }
                }
                try {
                    if (model.getParameters().isTimeDependent(name)) {
                        fail("delay expression duration must be static");
                    }
                } catch (const std::exception&) {
                    fail("delay expression duration requires static parameters");
                }
            }
            continuous(expression.args()[0]);
            continuous(expression.args()[1]);
            return;
        }
        // Assignment values are sampled at an event instant; unlike trigger
        // surfaces they may select a discontinuous branch at that instant.
        if (allowDistributionAssignment &&
            expression.kind() == ExpressionKind::Function &&
            expression.name() == "if" && expression.args().size() == 3) {
            std::function<void(const Expression&)> condition = [&](const Expression& test) {
                if (test.kind() == ExpressionKind::Binary &&
                    (test.name() == "&&" || test.name() == "||")) {
                    for (const auto& child : test.args()) condition(child);
                    return;
                }
                if (test.kind() == ExpressionKind::Unary && test.name() == "!") {
                    condition(test.args().front());
                    return;
                }
                if (test.kind() != ExpressionKind::Binary || test.args().size() != 2 ||
                    (test.name() != ">" && test.name() != ">=" &&
                     test.name() != "<" && test.name() != "<=" &&
                     test.name() != "==" && test.name() != "!=")) {
                    fail("conditional event assignment requires an arithmetic comparison");
                }
                for (const auto& child : test.args()) continuous(child);
            };
            condition(expression.args()[0]);
            continuous(expression.args()[1]);
            continuous(expression.args()[2]);
            return;
        }
        if (allowDistributionAssignment &&
            expression.kind() == ExpressionKind::Function &&
            expression.name().rfind("distrib_", 0) == 0) {
            for (const auto& argument : expression.args()) continuous(argument);
            return;
        }
        if (allowDistributionAssignment &&
            expression.kind() == ExpressionKind::Function &&
            expression.name() == "sqrt" && expression.args().size() == 1) {
            continuous(expression.args().front());
            return;
        }
        fail("only continuous arithmetic event expressions are supported");
    };
    if (event.priority) {
        const auto& priority = *event.priority;
        bool dynamic = false;
        std::function<void(const Expression&)> inspectPriority = [&](const Expression& expression) {
            if (expression.kind() == ExpressionKind::ObservableRef) dynamic = true;
            if (expression.kind() == ExpressionKind::Identifier) {
                if (expression.name() == "time" || expression.name() == "t") {
                    dynamic = true;
                }
                for (const auto& observable : model.getObservables()) {
                    if (observable.getName() == expression.name()) dynamic = true;
                }
            }
            for (const auto& child : expression.args()) inspectPriority(child);
        };
        inspectPriority(priority);
        if (dynamic) {
            // This bounded subclass uses the same continuous polynomial
            // arithmetic already supported for event triggers and assignment
            // values. Priority expressions may depend on time, species
            // observables, and static parameters only.
            continuous(priority);
            for (const auto& name : priority.getDependencies()) {
                if (name == "time" || name == "t") continue;
                bool observableReference = false;
                for (const auto& observable : model.getObservables()) {
                    observableReference = observableReference ||
                                          observable.getName() == name;
                }
                if (observableReference) continue;
                try {
                    if (model.getParameters().isTimeDependent(name)) {
                        fail("dynamic event priority requires static parameters");
                    }
                } catch (const std::exception&) {
                    fail("dynamic event priority requires static parameters");
                }
            }
        } else {
            for (const auto& name : priority.getDependencies()) {
                try {
                    if (model.getParameters().isTimeDependent(name)) {
                        fail("event priority must use static parameters or dynamic state");
                    }
                } catch (const std::exception&) {
                    fail("event priority requires static parameters");
                }
            }
        }
    }
    // Every conjunct of the trigger is a continuous arithmetic expression.
    std::function<void(const Expression&)> continuousTrigger = [&](const Expression& expression) {
        if (expression.kind() == ExpressionKind::Binary && expression.name() == "&&") {
            for (const auto& child : expression.args()) continuousTrigger(child);
            return;
        }
        continuous(expression.args()[0]);
        continuous(expression.args()[1]);
    };
    continuousTrigger(trigger);
    if (event.delay) {
        // A delay is a scheduling offset, so it has to be a static constant.
        for (const auto& name : event.delay->getDependencies()) {
            if (name == "time") fail("event delay must be static");
            for (const auto& observable : model.getObservables()) {
                if (observable.getName() == name) fail("event delay must be static");
            }
            try {
                if (model.getParameters().isTimeDependent(name)) fail("event delay must be static");
            } catch (const std::exception&) { fail("event delay requires static parameters"); }
        }
        continuous(*event.delay);
    }
    const auto isStaticNonfinite = [&](const Expression& expression) {
        std::function<bool(const Expression&)> referencesDynamicValue =
            [&](const Expression& current) {
                if (current.kind() == ExpressionKind::ObservableRef) return true;
                if (current.kind() == ExpressionKind::Identifier) {
                    if (current.name() == "time" || current.name() == "t") return true;
                    for (const auto& observable : model.getObservables()) {
                        if (observable.getName() == current.name()) return true;
                    }
                }
                return std::any_of(
                    current.args().begin(), current.args().end(),
                    [&](const auto& child) { return referencesDynamicValue(child); });
            };
        if (referencesDynamicValue(expression)) return false;
        try {
            const double value = expression.evaluate([&](const std::string& name) {
                return model.getParameters().evaluate(name);
            });
            return !std::isfinite(value);
        } catch (...) {
            return false;
        }
    };
    std::set<std::string> targets;
    for (const auto& assignment : event.assignments) {
        if (!targets.insert(assignment.target).second) fail("duplicate assignment target");
        bool found = false;
        for (const auto& observable : model.getObservables()) {
            found = found || observable.getName() == assignment.target;
        }
        if (!found) fail("assignment target must be a species observable");
        allowDistributionAssignment = true;
        const auto value = functionEvaluator.expandFunctions(assignment.value);
        if (!isStaticNonfinite(value)) continuous(value);
        allowDistributionAssignment = false;
    }
    if (targets.empty()) fail("event requires an assignment");
    }
}

} // namespace bng::ast
