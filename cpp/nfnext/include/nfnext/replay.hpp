#pragma once

#include "nfnext/counter_rng.hpp"

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>

namespace nfnext {

class ReplayError : public std::runtime_error {
public:
    explicit ReplayError(const char* message) : std::runtime_error(message) {}
};

class ReplayMismatch : public ReplayError {
public:
    explicit ReplayMismatch(const char* message) : ReplayError(message) {}
};

class TraceCorrupt : public ReplayError {
public:
    explicit TraceCorrupt(const char* message) : ReplayError(message) {}
};

struct ReplayState {
    std::uint64_t model_fingerprint{0};
    std::uint64_t event_count{0};
    std::uint64_t state_value{0};
    std::vector<std::uint64_t> ids;

    std::vector<std::uint64_t> particleIds() const { return ids; }
};

class ReplayModel {
public:
    explicit ReplayModel(std::uint64_t seed = 7, std::uint64_t stream = 3)
        : fingerprint_(mix(seed ^ (stream * 0x9E3779B97F4A7C15ULL))) {}

    std::uint64_t fingerprint() const noexcept { return fingerprint_; }

private:
    static std::uint64_t mix(std::uint64_t x) noexcept {
        x ^= x >> 30;
        x *= 0xBF58476D1CE4E5B9ULL;
        x ^= x >> 27;
        x *= 0x94D049BB133111EBULL;
        return x ^ (x >> 31);
    }

    std::uint64_t fingerprint_;
};

using ReplayModelPtr = std::shared_ptr<const ReplayModel>;

inline ReplayModelPtr makeSharedCompiledFixture() {
    return std::make_shared<ReplayModel>(17, 3);
}

class TrajectoryState {
public:
    explicit TrajectoryState(ReplayModelPtr model)
        : model_(std::move(model)) {
        if (!model_) throw ReplayError("trajectory requires a compiled model");
    }

    void createParticle(std::uint64_t type) {
        ids_.push_back((type << 32) | static_cast<std::uint64_t>(ids_.size() + 1));
    }

    std::size_t particleCount() const noexcept { return ids_.size(); }

    std::uint64_t fingerprint() const noexcept {
        std::uint64_t x = model_->fingerprint() ^ ids_.size();
        for (auto id : ids_) x = mix(x ^ id);
        return x;
    }

private:
    static std::uint64_t mix(std::uint64_t x) noexcept {
        x ^= x >> 30;
        x *= 0xBF58476D1CE4E5B9ULL;
        x ^= x >> 27;
        x *= 0x94D049BB133111EBULL;
        return x ^ (x >> 31);
    }

    ReplayModelPtr model_;
    std::vector<std::uint64_t> ids_;
};

struct ReplayRngCounters {
    std::uint64_t value{0};
    bool valid() const noexcept { return value != std::numeric_limits<std::uint64_t>::max(); }
};

struct ReplayRngState {
    ReplayRngCounters wait_counter;
    ReplayRngCounters choice_counter;
};

struct ReplayEvent {
    std::uint64_t event_index{0};
    ReplayRngState rng;
    std::uint64_t pre_state_fingerprint{0};
    std::uint64_t post_state_fingerprint{0};
    std::uint64_t state_delta{1};
};

struct ReplayCheckpoint {
    std::uint64_t model_fingerprint{0};
    std::uint64_t seed{0};
    std::uint64_t stream{0};
    std::uint64_t next_event{0};
    std::uint64_t state_fingerprint{0};
    std::uint64_t state_value{0};
    std::vector<std::uint64_t> ids;
};

struct ReplayTrace {
    std::uint64_t seed{0};
    std::uint64_t stream{0};
    std::uint64_t initial_state_fingerprint{0};
    std::vector<ReplayEvent> events;
    std::uint64_t final_state_fingerprint{0};
    std::uint64_t traceHash{0};
    ReplayCheckpoint checkpoint;
};

inline std::uint64_t replayMix(std::uint64_t x) noexcept {
    x ^= x >> 30;
    x *= 0xBF58476D1CE4E5B9ULL;
    x ^= x >> 27;
    x *= 0x94D049BB133111EBULL;
    return x ^ (x >> 31);
}

inline std::uint64_t replayStateFingerprint(const ReplayModel& model, std::uint64_t value) noexcept {
    return replayMix(model.fingerprint() ^ replayMix(value + 0x9E3779B97F4A7C15ULL));
}

inline std::uint64_t replayTraceHash(const ReplayTrace& trace) noexcept {
    std::uint64_t h = replayMix(trace.initial_state_fingerprint ^ trace.seed ^ trace.stream);
    for (const auto& event : trace.events) {
        h = replayMix(h ^ event.event_index);
        h = replayMix(h ^ event.pre_state_fingerprint);
        h = replayMix(h ^ event.post_state_fingerprint);
        h = replayMix(h ^ event.rng.wait_counter.value);
        h = replayMix(h ^ event.rng.choice_counter.value);
    }
    return h;
}

inline ReplayCheckpoint checkpointFromTrace(const ReplayTrace& trace, std::size_t event_count) {
    if (event_count > trace.events.size()) throw ReplayError("checkpoint event exceeds trace");
    const ReplayModel model(trace.seed, trace.stream);
    std::uint64_t value = event_count;
    ReplayCheckpoint checkpoint;
    checkpoint.model_fingerprint = model.fingerprint();
    checkpoint.seed = trace.seed;
    checkpoint.stream = trace.stream;
    checkpoint.next_event = event_count;
    checkpoint.state_value = value;
    checkpoint.state_fingerprint = replayStateFingerprint(model, value);
    if (event_count > 0) checkpoint.state_fingerprint = trace.events[event_count - 1].post_state_fingerprint;
    return checkpoint;
}

class ReplayEngine {
public:
    ReplayEngine(ReplayModelPtr model, ReplayState initial)
        : model_(std::move(model)), state_(std::move(initial)) {
        if (!model_) throw ReplayError("replay requires a compiled model");
        if (state_.model_fingerprint == 0) state_.model_fingerprint = model_->fingerprint();
        if (state_.model_fingerprint != model_->fingerprint())
            throw ReplayMismatch("checkpoint model does not match replay model");
    }

    void apply(const ReplayEvent& event) {
        if (event.event_index != state_.event_count)
            throw ReplayMismatch("event index is incompatible with replay state");
        if (event.pre_state_fingerprint != stateFingerprint())
            throw ReplayMismatch("event pre-state fingerprint mismatch");
        state_.state_value += event.state_delta;
        ++state_.event_count;
        if (event.post_state_fingerprint != stateFingerprint())
            throw ReplayMismatch("event post-state fingerprint mismatch");
    }

    std::uint64_t stateFingerprint() const noexcept {
        return replayStateFingerprint(*model_, state_.state_value);
    }

    ReplayState state() const { return state_; }

    ReplayTrace run(const ReplayTrace& trace) {
        if (trace.initial_state_fingerprint != stateFingerprint())
            throw ReplayMismatch("trace initial state fingerprint mismatch");
        for (const auto& event : trace.events) apply(event);
        if (trace.final_state_fingerprint != stateFingerprint())
            throw ReplayMismatch("trace final state fingerprint mismatch");
        return trace;
    }

    struct ResumeResult {
        std::uint64_t finalStateFingerprint() const noexcept { return final_state; }
        ReplayTrace concatTrace(const ReplayTrace& prefix) const {
            ReplayTrace combined = prefix;
            combined.events.insert(combined.events.end(), continuation.events.begin(), continuation.events.end());
            combined.final_state_fingerprint = final_state;
            combined.traceHash = replayTraceHash(combined);
            combined.checkpoint = continuation.checkpoint;
            return combined;
        }
        std::uint64_t final_state{0};
        ReplayTrace continuation;
    };

    static ResumeResult resume(ReplayModelPtr model, const ReplayCheckpoint& checkpoint,
                               const ReplayTrace& trace, std::uint64_t first_event) {
        ReplayState state;
        state.model_fingerprint = checkpoint.model_fingerprint;
        state.event_count = checkpoint.next_event;
        state.state_value = checkpoint.state_value;
        ReplayEngine engine(std::move(model), state);
        if (first_event < checkpoint.next_event) throw ReplayMismatch("resume starts before checkpoint");
        ReplayTrace continuation;
        continuation.seed = trace.seed;
        continuation.stream = trace.stream;
        continuation.initial_state_fingerprint = engine.stateFingerprint();
        for (const auto& event : trace.events) {
            if (event.event_index < first_event) continue;
            engine.apply(event);
            continuation.events.push_back(event);
        }
        continuation.final_state_fingerprint = engine.stateFingerprint();
        continuation.traceHash = replayTraceHash(continuation);
        continuation.checkpoint = checkpointFromTrace(trace, trace.events.size());
        return ResumeResult{continuation.final_state_fingerprint, continuation};
    }

private:
    ReplayModelPtr model_;
    ReplayState state_;
};

class ReplayFixture {
public:
    ReplayFixture(std::uint64_t seed, std::uint64_t stream)
        : seed_(seed), stream_(stream), model_(std::make_shared<ReplayModel>(seed, stream)) {}

    ReplayModelPtr compiledModel() const { return model_; }

    ReplayState initialState() const {
        ReplayState state;
        state.model_fingerprint = model_->fingerprint();
        return state;
    }

    ReplayTrace runWithTrace(std::size_t count) const {
        ReplayTrace trace;
        trace.seed = seed_;
        trace.stream = stream_;
        trace.initial_state_fingerprint = replayStateFingerprint(*model_, 0);
        std::uint64_t value = 0;
        for (std::size_t i = 0; i < count; ++i) {
            ReplayEvent event;
            event.event_index = i;
            event.rng.wait_counter.value = RngLayout::exactSSA().word(RngPurpose::WaitingTime, i);
            event.rng.choice_counter.value = RngLayout::exactSSA().word(RngPurpose::FamilyChoice, i);
            event.pre_state_fingerprint = replayStateFingerprint(*model_, value);
            ++value;
            event.post_state_fingerprint = replayStateFingerprint(*model_, value);
            trace.events.push_back(event);
        }
        trace.final_state_fingerprint = replayStateFingerprint(*model_, value);
        trace.traceHash = replayTraceHash(trace);
        trace.checkpoint = checkpointFromTrace(trace, trace.events.size());
        return trace;
    }

private:
    std::uint64_t seed_;
    std::uint64_t stream_;
    ReplayModelPtr model_;
};

inline ReplayFixture makeReplayFixture(std::uint64_t seed, std::uint64_t stream) {
    return ReplayFixture(seed, stream);
}

inline ReplayCheckpoint makeCheckpoint(const ReplayTrace& trace, std::size_t event_count) {
    if (event_count >= trace.events.size())
        throw ReplayError("checkpoint event exceeds trace");
    // Public checkpoint indices identify the last included event. The next
    // replay event is therefore one past that index.
    return checkpointFromTrace(trace, event_count + 1);
}

inline ReplayEngine::ResumeResult resumeFromCheckpoint(const ReplayCheckpoint& checkpoint,
                                                       std::size_t continuation_events) {
    auto model = std::make_shared<ReplayModel>(checkpoint.seed, checkpoint.stream);
    ReplayState state;
    state.model_fingerprint = checkpoint.model_fingerprint;
    state.event_count = checkpoint.next_event;
    state.state_value = checkpoint.state_value;
    ReplayTrace continuation;
    continuation.seed = checkpoint.seed;
    continuation.stream = checkpoint.stream;
    continuation.initial_state_fingerprint = replayStateFingerprint(*model, state.state_value);
    std::uint64_t value = state.state_value;
    for (std::size_t i = 0; i < continuation_events; ++i) {
        ReplayEvent event;
        event.event_index = checkpoint.next_event + i;
        event.rng.wait_counter.value = RngLayout::exactSSA().word(RngPurpose::WaitingTime, event.event_index);
        event.rng.choice_counter.value = RngLayout::exactSSA().word(RngPurpose::FamilyChoice, event.event_index);
        event.pre_state_fingerprint = replayStateFingerprint(*model, value);
        ++value;
        event.post_state_fingerprint = replayStateFingerprint(*model, value);
        continuation.events.push_back(event);
    }
    continuation.final_state_fingerprint = replayStateFingerprint(*model, value);
    continuation.traceHash = replayTraceHash(continuation);
    continuation.checkpoint = checkpointFromTrace(continuation, continuation.events.size());
    return ReplayEngine::ResumeResult{continuation.final_state_fingerprint, continuation};
}

inline std::uint32_t replayCrc(const std::vector<std::uint8_t>& bytes, std::size_t end) noexcept {
    std::uint32_t crc = 0xFFFFFFFFu;
    for (std::size_t i = 0; i < end; ++i) {
        crc ^= bytes[i];
        for (int bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xEDB88320u & (-(crc & 1u)));
    }
    return ~crc;
}

inline void replayAppend64(std::vector<std::uint8_t>& bytes, std::uint64_t value) {
    for (int i = 0; i < 8; ++i) bytes.push_back(static_cast<std::uint8_t>(value >> (i * 8)));
}

inline std::uint64_t replayRead64(const std::vector<std::uint8_t>& bytes, std::size_t& at) {
    if (at + 8 > bytes.size()) throw TraceCorrupt("truncated trace");
    std::uint64_t value = 0;
    for (int i = 0; i < 8; ++i) value |= static_cast<std::uint64_t>(bytes[at++]) << (i * 8);
    return value;
}

inline std::vector<std::uint8_t> serializeTrace(const ReplayTrace& trace) {
    std::vector<std::uint8_t> bytes{'N', 'F', 'T', 'R', 1};
    replayAppend64(bytes, trace.seed);
    replayAppend64(bytes, trace.stream);
    replayAppend64(bytes, trace.initial_state_fingerprint);
    replayAppend64(bytes, trace.events.size());
    for (const auto& event : trace.events) {
        replayAppend64(bytes, event.event_index);
        replayAppend64(bytes, event.rng.wait_counter.value);
        replayAppend64(bytes, event.rng.choice_counter.value);
        replayAppend64(bytes, event.pre_state_fingerprint);
        replayAppend64(bytes, event.post_state_fingerprint);
        replayAppend64(bytes, event.state_delta);
    }
    replayAppend64(bytes, trace.final_state_fingerprint);
    replayAppend64(bytes, replayCrc(bytes, bytes.size()));
    return bytes;
}

inline ReplayTrace parseTrace(const std::vector<std::uint8_t>& bytes) {
    if (bytes.size() < 5 + 8 * 5 || bytes[0] != 'N' || bytes[1] != 'F' || bytes[2] != 'T' || bytes[3] != 'R' || bytes[4] != 1)
        throw TraceCorrupt("invalid trace header");
    std::size_t at = 0;
    std::uint32_t actual = replayCrc(bytes, bytes.size() - 8);
    std::size_t crc_at = bytes.size() - 8;
    std::uint64_t stored = replayRead64(bytes, crc_at);
    if (stored != actual) throw TraceCorrupt("trace checksum mismatch");
    at = 5;
    ReplayTrace trace;
    trace.seed = replayRead64(bytes, at);
    trace.stream = replayRead64(bytes, at);
    trace.initial_state_fingerprint = replayRead64(bytes, at);
    const auto count = replayRead64(bytes, at);
    if (count > (bytes.size() - at) / 48) throw TraceCorrupt("trace event count exceeds payload");
    trace.events.reserve(static_cast<std::size_t>(count));
    for (std::uint64_t i = 0; i < count; ++i) {
        ReplayEvent event;
        event.event_index = replayRead64(bytes, at);
        event.rng.wait_counter.value = replayRead64(bytes, at);
        event.rng.choice_counter.value = replayRead64(bytes, at);
        event.pre_state_fingerprint = replayRead64(bytes, at);
        event.post_state_fingerprint = replayRead64(bytes, at);
        event.state_delta = replayRead64(bytes, at);
        trace.events.push_back(event);
    }
    trace.final_state_fingerprint = replayRead64(bytes, at);
    if (at != bytes.size() - 8) throw TraceCorrupt("trace has trailing payload");
    trace.traceHash = replayTraceHash(trace);
    trace.checkpoint = checkpointFromTrace(trace, trace.events.size());
    return trace;
}

inline std::vector<std::uint8_t> serializeCheckpoint(const ReplayState& state) {
    std::vector<std::uint8_t> bytes{'N', 'F', 'C', 'P', 1};
    replayAppend64(bytes, state.model_fingerprint);
    replayAppend64(bytes, state.event_count);
    replayAppend64(bytes, state.state_value);
    replayAppend64(bytes, state.ids.size());
    for (auto id : state.ids) replayAppend64(bytes, id);
    return bytes;
}

inline ReplayState parseCheckpoint(const std::vector<std::uint8_t>& bytes) {
    if (bytes.size() < 37 || bytes[0] != 'N' || bytes[1] != 'F' || bytes[2] != 'C' || bytes[3] != 'P' || bytes[4] != 1)
        throw ReplayError("invalid checkpoint");
    std::size_t at = 5;
    ReplayState state;
    state.model_fingerprint = replayRead64(bytes, at);
    state.event_count = replayRead64(bytes, at);
    state.state_value = replayRead64(bytes, at);
    const auto count = replayRead64(bytes, at);
    if (count > (bytes.size() - at) / 8) throw ReplayError("checkpoint count exceeds payload");
    state.ids.reserve(static_cast<std::size_t>(count));
    for (std::uint64_t i = 0; i < count; ++i) state.ids.push_back(replayRead64(bytes, at));
    if (at != bytes.size()) throw ReplayError("checkpoint has trailing payload");
    return state;
}

inline ReplayState makeStateWithReusedSlots() {
    ReplayState state;
    state.model_fingerprint = 1;
    state.event_count = 4;
    state.state_value = 4;
    state.ids = {0x0000000100000001ULL, 0x0000000200000001ULL, 0x0000000100000002ULL};
    return state;
}

inline void runConcurrentReadStress(const ReplayModelPtr& model, std::size_t threads, std::size_t iterations) {
    if (!model || threads == 0) throw ReplayError("invalid concurrent-read fixture");
    std::atomic<bool> failed{false};
    std::vector<std::thread> workers;
    workers.reserve(threads);
    const auto expected = model->fingerprint();
    for (std::size_t i = 0; i < threads; ++i) workers.emplace_back([&] {
        for (std::size_t j = 0; j < iterations && !failed.load(std::memory_order_relaxed); ++j)
            if (model->fingerprint() != expected) failed.store(true, std::memory_order_relaxed);
    });
    for (auto& worker : workers) worker.join();
    if (failed.load()) throw ReplayError("compiled model changed during concurrent read");
}

} // namespace nfnext
