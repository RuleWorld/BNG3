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
    if (event.priority) {
        // The priority orders the assignments of events that are executed
        // simultaneously.  A single event has nothing to order, so the value
        // is accepted and does not change the execution.
        for (const auto& name : event.priority->getDependencies()) {
            if (name == "time") fail("event priority must be static");
            for (const auto& observable : model.getObservables()) {
                if (observable.getName() == name) fail("event priority must be static");
            }
            try {
                if (model.getParameters().isTimeDependent(name)) fail("event priority must be static");
            } catch (const std::exception&) { fail("event priority requires static parameters"); }
        }
    }
    if (!event.persistent) {
        // A non-persistent trigger re-arms itself as soon as the assignment
        // leaves the trigger true, which needs an event queue rather than a
        // single continuous root crossing.
        fail("non-persistent triggers are unsupported");
    }
    const auto& trigger = event.trigger;
    // A trigger is a strict inequality or a conjunction of them.  A
    // conjunction holds only where every conjunct holds, so its root function
    // is the smallest of the conjunct root functions.
    std::function<void(const Expression&)> checkTrigger = [&](const Expression& expression) {
        if (expression.kind() != ExpressionKind::Binary) {
            fail("trigger must be a continuous scalar inequality");
        }
        if (expression.name() == "&&") {
            for (const auto& child : expression.args()) checkTrigger(child);
            return;
        }
        if (expression.name() != ">" && expression.name() != ">=" &&
            expression.name() != "<" && expression.name() != "<=") {
            fail("trigger must be a continuous scalar inequality");
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
    // Every conjunct of the trigger has to compare a time or species
    // observable against a static threshold or another observable.
    std::function<void(const Expression&)> checkSides = [&](const Expression& expression) {
        if (expression.kind() == ExpressionKind::Binary && expression.name() == "&&") {
            for (const auto& child : expression.args()) checkSides(child);
            return;
        }
        const bool leftDynamic = dynamicIdentifier(expression.args()[0]);
        const bool rightDynamic = dynamicIdentifier(expression.args()[1]);
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
    // Every conjunct of the trigger is a continuous polynomial expression.
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
