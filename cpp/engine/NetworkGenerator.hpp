#pragma once

#include <filesystem>
#include <memory>
#include <mutex>
#include <string>
#include <utility>

#include "ast/RxnList.hpp"
#include "ast/SpeciesList.hpp"
#include "compile/Document.hpp"
#include "engine/SimulationSession.hpp"

namespace bng::ast { class Model; }
namespace bng::compile { class BNGcoreLoweringContext; }

namespace bng::engine {

struct GeneratedNetwork {
    ast::SpeciesList species;
    ast::RxnList reactions;

    // A network carries one continuation trajectory shared by its integrators.
    // Keep the lock shared when a GeneratedNetwork is copied so session
    // snapshots and replacements cannot race across copies of the same
    // network. The lock protects storage access; it does not define semantics
    // for concurrent continuation runs on one trajectory.
    SimulationSession snapshotSimulationSession() const {
        std::lock_guard<std::mutex> lock(*simulationSessionMutex_);
        return simulationSession;
    }

    void replaceSimulationSession(SimulationSession session) const {
        std::lock_guard<std::mutex> lock(*simulationSessionMutex_);
        simulationSession = std::move(session);
    }

    void resetSimulationSession() const {
        std::lock_guard<std::mutex> lock(*simulationSessionMutex_);
        simulationSession.reset();
    }

    // Reaction rates loaded from a .net file already include compartment-unit
    // conversion. Keep source-generated networks distinguishable so readers
    // and writers do not apply that conversion a second time.
    bool ratesIncludeUnitConversion = false;

    // Species and reaction graphs retain pointers to the BNGcore node/state
    // types created during compiled lowering. Keep that storage alive for the
    // lifetime of the generated network rather than the generator call.
    std::shared_ptr<compile::BNGcoreLoweringContext> loweringContext;

private:
    mutable SimulationSession simulationSession;
    std::shared_ptr<std::mutex> simulationSessionMutex_ =
        std::make_shared<std::mutex>();
};

class NetworkGenerator {
public:
    // Compatibility constructor for parser-facing callers. The model is
    // compiled immediately; generation itself consumes compile::Document.
    explicit NetworkGenerator(ast::Model& model);
    explicit NetworkGenerator(const compile::Document& document);

    GeneratedNetwork generate(const std::filesystem::path& sourcePath);
    GeneratedNetwork generateNative(std::size_t maxIter = 32);

    // Normalize one compiled seed into the count basis consumed by native
    // networks.  Action dispatch uses the same conversion for resets so a
    // unit-aware model cannot restore raw concentration/amount literals.
    static double normalizeSeedAmount(const compile::CompiledModel& model,
                                      const compile::CompiledSeed& seed);

    const compile::Document& document() const noexcept { return document_; }

private:
    ast::Model* sourceModel_ = nullptr; // source-preserving NetWriter bridge only
    compile::Document document_;
};

} // namespace bng::engine
