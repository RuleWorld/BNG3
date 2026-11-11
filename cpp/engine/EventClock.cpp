#include "OdeIntegrator.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace bng::engine {
namespace {
bool isTime(const ast::Expression& expression) {
    return expression.kind() == ast::ExpressionKind::Identifier &&
           (expression.name() == "time" || expression.name() == "t");
}
}  // namespace

void OdeIntegrator::initializePeriodicEventClocks(const std::vector<double>& state,
                                                  bool continuing, double startTime) {
    periodicEventClocks_.clear();
    periodicClockTriggers_.clear();
    // In an event-only system the state is exactly constant between events.
    // Keep reaction-coupled systems on the standard CVODE root path.
    if (std::any_of(continuousSpecies_.begin(), continuousSpecies_.end(),
                    [](bool continuous) { return continuous; })) return;
    for (std::size_t group = 0; group < nativeEventGroups_.size(); ++group) {
        const auto& trigger = nativeEventGroups_[group].trigger;
        if (std::any_of(nativeEventGroups_[group].events.begin(),
                        nativeEventGroups_[group].events.end(),
                        [&](std::size_t event) {
                            return nativeEvents_[event].delay.has_value();
                        })) continue;
        const auto expanded = functionEvaluator_.expandFunctions(trigger);
        if (expanded.kind() != ast::ExpressionKind::Binary ||
            expanded.name() != ">=" || !isTime(expanded.args()[0])) continue;
        const auto& rhs = expanded.args()[1];
        if (rhs.kind() != ast::ExpressionKind::Binary || rhs.name() != "+" ||
            rhs.args()[1].kind() != ast::ExpressionKind::Number) continue;
        const double period = rhs.args()[1].numberValue();
        if (!std::isfinite(period) || !(period > 0.0)) continue;
        const auto& reset = rhs.args()[0];
        if (reset.kind() != ast::ExpressionKind::Identifier &&
            reset.kind() != ast::ExpressionKind::ObservableRef) continue;
        const auto observable = observableIndex_.find(reset.name());
        if (observable == observableIndex_.end()) continue;
        const auto& entries = compiledGroups_[observable->second].entries;
        if (entries.size() != 1 || entries[0].second != 1.0) continue;
        const auto species = entries[0].first;
        if (continuousSpecies_[species]) continue;

        // This is a proof of a periodic recurrence, not a heuristic based on
        // current values. Reject any other writer, delay, or reset expression.
        bool valid = true;
        bool hasWriter = false;
        for (std::size_t index = 0; index < nativeEvents_.size(); ++index) {
            const auto& event = nativeEvents_[index];
            for (std::size_t assignment = 0; assignment < event.targets.size();
                 ++assignment) {
                const auto& target = event.targets[assignment];
                if (target.kind != NativeEventTarget::Kind::Species ||
                    target.speciesIndex != species) continue;
                hasWriter = true;
                const auto& members = nativeEventGroups_[group].events;
                valid = valid && std::find(members.begin(), members.end(), index) !=
                    members.end() && !event.delay &&
                    isTime(functionEvaluator_.expandFunctions(
                        event.assignments[assignment].value));
            }
        }
        if (!valid || !hasWriter) continue;
        PeriodicEventClock clock;
        clock.group = group;
        clock.species = species;
        clock.period = period;
        clock.origin = state[species];
        if (continuing && activeSimulationSession_) {
            const auto phase = activeSimulationSession_->periodicEventPhases.find(
                trigger.toString());
            if (phase != activeSimulationSession_->periodicEventPhases.end() &&
                std::fma(static_cast<double>(phase->second.ticks), period,
                         phase->second.origin) == state[species]) {
                clock.origin = phase->second.origin;
                clock.ticks = phase->second.ticks;
            } else if (phase != activeSimulationSession_->periodicEventPhases.end()) {
                const double oldNext = std::fma(
                    static_cast<double>(phase->second.ticks + 1), period,
                    phase->second.origin);
                clock.roseAtStart = oldNext > startTime &&
                    std::fma(1.0, period, clock.origin) <= startTime;
            }
        }
        clock.next = std::fma(static_cast<double>(clock.ticks + 1), period,
                              clock.origin);
        if (!std::isfinite(clock.next) ||
            clock.next <= std::fma(static_cast<double>(clock.ticks), period,
                                    clock.origin)) {
            throw std::runtime_error("periodic event interval is below time precision");
        }
        // A threshold already true with initialValue=true has no rising
        // edge. initialValue=false is processed by the normal startup path;
        // its reset will arm a new future crossing.
        clock.armed = clock.next > startTime;
        const auto index = periodicEventClocks_.size();
        periodicClockTriggers_[&trigger] = index;
        for (const auto event : nativeEventGroups_[group].events) {
            periodicClockTriggers_[&nativeEvents_[event].trigger] = index;
        }
        periodicEventClocks_.push_back(clock);
    }
    // Every continuously varying trigger must have a known calendar instant.
    // Discrete triggers have already been removed from nativeEventRoots_.
    if (std::any_of(nativeEventRoots_.begin(), nativeEventRoots_.end(),
                    [&](const auto& root) {
                        return !periodicClockTriggers_.count(root.second);
                    })) {
        periodicEventClocks_.clear();
        periodicClockTriggers_.clear();
    }
    for (const auto& clock : periodicEventClocks_) {
        if (activeSimulationSession_) {
            activeSimulationSession_->periodicEventPhases[
                nativeEventGroups_[clock.group].trigger.toString()] =
                {clock.origin, clock.ticks};
        }
        if (clock.roseAtStart) queueTriggeredGroup(clock.group, startTime, state);
    }
}

void OdeIntegrator::advancePeriodicEventClocks(std::size_t eventIndex, double time) {
    for (auto& clock : periodicEventClocks_) {
        const auto& group = nativeEventGroups_[clock.group];
        if (std::find(group.events.begin(), group.events.end(), eventIndex) ==
            group.events.end()) continue;
        const auto& event = nativeEvents_[eventIndex];
        if (std::none_of(event.targets.begin(), event.targets.end(),
                [&](const NativeEventTarget& target) {
                    return target.kind == NativeEventTarget::Kind::Species &&
                           target.speciesIndex == clock.species;
                })) continue;
        const double previous = std::fma(static_cast<double>(clock.ticks),
                                          clock.period, clock.origin);
        // A second persistent event at this instant writes the same reset;
        // it must not advance the phase a second time.
        if (time == previous) continue;
        if (time == clock.next) {
            ++clock.ticks;
        } else {
            // An initialValue=false trigger may execute at the start after
            // its first threshold has already passed. Its reset anchors anew.
            clock.origin = time;
            clock.ticks = 0;
        }
        // t_n = origin + n*h, evaluated with one final rounding. Repeatedly
        // adding rounded root times would accumulate both localization and
        // summation error and eventually lose endpoint events.
        clock.next = std::fma(static_cast<double>(clock.ticks + 1),
                              clock.period, clock.origin);
        if (!(clock.next > time) || clock.ticks >= (std::uint64_t{1} << 53)) {
            throw std::runtime_error("periodic event interval is below time precision");
        }
        clock.armed = true;
        if (activeSimulationSession_) {
            activeSimulationSession_->periodicEventPhases[group.trigger.toString()] =
                {clock.origin, clock.ticks};
        }
    }
}

void OdeIntegrator::queueDuePeriodicEventClocks(double time,
                                               const std::vector<double>& state) {
    for (const auto& clock : periodicEventClocks_) {
        // No proximity tolerance: even the next representable future instant
        // must remain in the future.
        if (clock.armed && clock.next <= time &&
            triggerRoseAt_[nativeEventGroups_[clock.group].events.front()] <
                clock.next) {
            queueTriggeredGroup(clock.group, time, state);
        }
    }
}
}  // namespace bng::engine
