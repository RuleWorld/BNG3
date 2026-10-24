#pragma once

#include <cstddef>
#include <cstdint>
#include <random>
#include <string>
#include <unordered_map>
#include <vector>

namespace bng::engine {

// Runtime state that belongs to one simulation trajectory.  It is carried by
// the generated network so separately constructed integrators used by a
// continuing protocol phase see the same DDE history, in-flight reactions,
// and stochastic stream.  Batch trajectories each receive their own session.
struct SimulationSession {
    struct HistoryPoint {
        double time = 0.0;
        std::vector<double> state;
        std::vector<double> derivative;
        std::unordered_map<std::string, double> parameters;
    };

    struct PendingCompletion {
        double time = 0.0;
        std::size_t reaction = 0;
        std::uint64_t order = 0;
    };

    struct PendingNativeEvent {
        std::size_t event = 0;
        double executionTime = 0.0;
        std::vector<double> values;
    };

    bool initialized = false;
    double startTime = 0.0;
    double currentTime = 0.0;
    std::vector<double> initialState;
    std::vector<double> state;
    std::vector<HistoryPoint> history;
    std::vector<double> reactionDelays;
    std::vector<double> discontinuities;
    std::vector<PendingCompletion> pendingCompletions;
    std::vector<PendingNativeEvent> pendingNativeEvents;
    std::vector<double> eventTriggerRoseAt;
    std::mt19937_64 rng;
    bool rngInitialized = false;
    bool ssaHazardInitialized = false;
    double ssaRemainingHazard = 0.0;
    std::uint64_t nextCompletionOrder = 0;

    void reset() {
        initialized = false;
        startTime = 0.0;
        currentTime = 0.0;
        initialState.clear();
        state.clear();
        history.clear();
        reactionDelays.clear();
        discontinuities.clear();
        pendingCompletions.clear();
        pendingNativeEvents.clear();
        eventTriggerRoseAt.clear();
        rngInitialized = false;
        ssaHazardInitialized = false;
        ssaRemainingHazard = 0.0;
        nextCompletionOrder = 0;
    }
};

}  // namespace bng::engine
