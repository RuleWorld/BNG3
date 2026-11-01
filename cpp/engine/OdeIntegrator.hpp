#pragma once

#include <functional>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "ast/Model.hpp"
#include "io/TfunReader.hpp"
#include "ast/ModelFunctionEvaluator.hpp"
#include "compile/CompiledRateLaw.hpp"
#include "NetworkGenerator.hpp"

namespace bng::engine {

// The reactant-count offset canonical BioNetGen applies to a repeated
// identical reactant.
//
// A rule with two identical reactants does not have `n^2` ways to react: it
// has `n * (n - 1)`, because the same molecule cannot react with itself.
// Canonical BioNetGen 2.9.3 encodes that in the `discrete` branch of
// `bng2/Network3/src/network.cpp`'s `rxn_rate`, which multiplies a repeated
// reactant by `X - n` instead of `X`.  This helper computes the `n` of that
// expression: the number of identical reactants immediately preceding the
// reactant at `position` in the reaction's reactant list.
//
// Every stochastic path in this engine uses it, so the count convention does
// not depend on which route a caller asked for.  The deterministic (ODE)
// evaluation keeps the continuous convention, exactly as canonical BioNetGen
// does: its `discrete` flag is off for CVODE and on for SSA/PLA/PSA
// (`bng2/Network3/src/run_network.cpp`).
inline std::size_t identicalReactantOffset(
    const std::vector<std::size_t>& reactantIndices, std::size_t position) {
    if (position == 0 || position >= reactantIndices.size()) {
        return 0;
    }
    if (reactantIndices[position] != reactantIndices[position - 1]) {
        return 0;
    }
    return identicalReactantOffset(reactantIndices, position - 1) + 1;
}

struct OdeOptions {
    double tStart = 0.0;
    double tEnd = 1.0;
    std::size_t nSteps = 100;
    double rtol = 1e-8;
    double atol = 1e-12;
    std::string method = "euler";  // "euler", "rk4", "cvode" (cvode not yet implemented)
    double maxStep = 0.0;          // 0 = no limit
    std::string stopCondition;     // muParser expression (empty = none)
    unsigned int seed = 0;         // SSA and ODE event draws (0 = random)
    bool steadyState = false;      // Enable steady-state detection
    double steadyStateTol = 1e-8;  // Tolerance for steady-state (|dydt| < tol)
    std::string stopIf;            // Boolean expression to evaluate at each step
    bool printCDAT = true;         // Whether to write .cdat output file
    bool printFunctions = false;   // Whether to write .fdat output file
    std::vector<double> sampleTimes; // Non-uniform output time points (overrides nSteps)
    std::size_t maxSimSteps = 0;   // Max internal simulation steps (0 = unlimited)
    bool maxSimStepsSpecified = false; // Distinguish an action limit of 0 from no limit
    bool saveProgress = false;     // Write .net checkpoint at each output step
    bool printNet = false;         // Write .net file after simulation with final concentrations
    bool continueSimulation = false; // Continue one committed native trajectory/session
    bool freshFromInitialState = false; // Start fresh from an existing session's original state
    bool printEnd = false;         // Output final state when simulation stops (stop_if or steady_state)
    std::size_t outputStepInterval = 0; // Output every N internal steps (0 = disabled, use n_steps timing)
    std::string netfile;           // Custom .net file to read instead of auto-generating
    bool sparse = false;           // Use sparse Jacobian (for large networks >1000 species)
    bool evaluateExpressions = true; // Evaluate symbolic expressions in .net output
    double checkProductScale = 0.0;  // Warn if product concentrations exceed this (0 = disabled)
    bool binaryOutput = false;     // Write .cdat/.gdat in binary format (4-byte floats, row-major)
    bool enforceNonnegative = false; // Optional CVODE constraint retry for physical populations
    std::size_t batchSize = 0;       // 0 = single trajectory; N>0 = batched SSA (GPU/CPU pool)
    bool batchGpuPreferred = true;   // try GPU first when batchSize > 0; silently fall back to CPU pool
    std::string batchGpuBackend;     // "auto" (default), "cuda", "metal", or "none" (force CPU pool)
    // Internal: a CPU batch worker owns its RNG/state and must not publish or
    // share the network's resumable single-trajectory session.
    bool isolatedTrajectory = false;
};

struct OdeResult {
    std::vector<double> timePoints;                    // length = nSteps + 1
    std::vector<std::vector<double>> concentrations;   // [timeIndex][speciesIndex]
    std::vector<std::vector<double>> observables;      // [timeIndex][groupIndex]
    std::vector<std::vector<double>> functions;        // [timeIndex][zero-arg function]
    std::size_t eventCount = 0;                              // Internal SSA event count
    std::size_t batchSize = 0;                               // 0 = single trajectory
    std::vector<std::vector<double>> batchStdDevs;           // [timeIndex][speciesIndex] std dev (batch mode only)
    std::vector<std::vector<double>> batchObsStdDevs;        // [timeIndex][obsIndex] observable std dev (batch mode only)
};

class OdeIntegrator {
public:
    OdeIntegrator(const ast::Model& model, const GeneratedNetwork& network);

    OdeResult integrate(const OdeOptions& options);
    // Register implicit algebraic residuals by the observable that exposes
    // each algebraic state and an expression that must equal zero.
    void setAlgebraicRules(
        const std::vector<std::pair<std::string, std::string>>& rules);
    void writeOutputFiles(const std::string& prefix, const OdeResult& result, bool printCDAT = true, bool printFunctions = false, bool append = false) const;
    void writeSpeciesStatsFile(const std::string& prefix, const OdeResult& result, bool append = false) const;
    void writeBinaryOutputFiles(const std::string& prefix, const OdeResult& result, bool printCDAT = true) const;
    void writeBatchStdDevsFile(const std::string& prefix, const OdeResult& result) const;
    void derivs(double t, const double* y, double* dydt) const;
    // Return compiled per-reaction coefficients in generated-network order,
    // before ordinary mass-action species factors are applied. This supports
    // independent parity checks of the runtime expression evaluator.
    std::vector<double> evaluateRateCoefficients(double t, const double* y) const;
    // CVODE integrates a scaled state to keep very small SBML amounts and
    // very large converted rate constants numerically well-conditioned.
    void cvodeDerivs(double t, const double* y, double* dydt) const;
    int idaResidual(double time, const double* scaledState,
                    const double* scaledDerivative, double* residual) const;
    double cvodeEventRoot(double time, const double* scaledState) const;
    // The root function of every trigger group, for the solver's root
    // finding.  One root per group: the events that share a trigger are
    // triggered at the same instant, so they cross together.
    void cvodeEventRoots(double time, const double* scaledState, double* roots) const;

    void loadTfun(const std::string& name,
                  const std::string& filePath,
                  const std::string& method = "linear") {
        tfunRegistry_.load(name, filePath, method);
    }
    io::TfunRegistry& getTfunRegistry() { return tfunRegistry_; }

public:
    // Compiled reaction network for fast derivative evaluation and simulator backends
    struct CompiledReaction {
        std::vector<std::size_t> reactantIndices;  // 0-based species indices
        std::vector<std::size_t> productIndices;
        double rateConstant = 0.0;    // evaluated rate (for elementary)
        double statFactor;            // statistical factor
        bool isFunctional = false;    // true if rate depends on time/observables
        bool isTimeDependent = false; // SSA cannot use the direct method for these rates
        std::optional<compile::CompiledRateLaw> compiledRateLaw;  // compile-owned rate evaluation
        std::optional<ast::Expression> functionalRateExpr;  // for runtime evaluation
        // Preserve the source coefficient even when it is folded into
        // rateConstant. Delayed completion may evaluate this expression at a
        // historical parameter snapshot after a continuation intervention.
        std::optional<ast::Expression> sourceRateExpr;
        bool isTotalRate = false;     // no statistical/unit conversion factor
        bool isAbsoluteFlux = false;  // source law already includes reactant dependence
        double delay = 0.0;           // constant reaction delay (0 = ordinary reaction)
        bool nonConsuming = false;    // defer net stoichiometry until completion
    };

    struct CompiledGroup {
        std::string name;
        std::vector<std::pair<std::size_t, double>> entries;  // (speciesIndex, weight)
    };

    const std::vector<CompiledReaction>& getCompiledReactions() const { return compiledRxns_; }
    const std::vector<CompiledGroup>& getCompiledGroups() const { return compiledGroups_; }
    const std::vector<bool>& getFixedSpecies() const { return fixedSpecies_; }
    bool hasFunctionalRates() const { return hasFunctionalRates_; }

private:
    const ast::Model& model_;
    const GeneratedNetwork& network_;
    ast::ModelFunctionEvaluator functionEvaluator_;

    struct CompiledConstantReaction {
        std::size_t reactantOffset = 0;
        std::size_t productOffset = 0;
        std::size_t reactantCount = 0;
        std::size_t productCount = 0;
        double rateConstant = 0.0;
        bool isTotalRate = false;
        bool isAbsoluteFlux = false;
    };

    std::vector<CompiledReaction> compiledRxns_;
    std::vector<std::size_t> delayedRxnIndices_;
    std::vector<double> historyDelays_;
    bool hasPositiveExpressionDelay_ = false;
    // True when some delay() duration depends on time or state.
    bool hasDynamicExpressionDelay_ = false;
    // Whether the integration records trajectory history at every step.
    bool recordsHistory() const {
        return !historyDelays_.empty() || hasDynamicExpressionDelay_;
    }
    std::vector<CompiledGroup> compiledGroups_;
    std::vector<bool> fixedSpecies_;    // true for $ (constant) species
    std::size_t nSpecies_ = 0;
    bool hasFunctionalRates_ = false;

    // Performance optimizations.
    //
    // groupValues_ and functionalRateCoefficients_ are scratch for derivs(),
    // the single-threaded ODE/CVODE path.  They are deliberately NOT used by
    // the SSA path: the batched CPU pool shares one integrator across its
    // worker threads, so any mutable member the SSA path writes would be a
    // data race between those workers.  evaluateFunctionalRateCoefficients()
    // therefore takes the observable scratch as an explicit argument, and the
    // SSA path passes its own per-thread buffer.
    mutable std::vector<double> groupValues_;                  // Pre-allocated for derivs()
    mutable std::vector<double> functionalRateCoefficients_;  // Pre-allocated for derivs()
    std::unordered_map<std::string, std::size_t> observableIndex_; // O(1) observable lookup
    std::vector<std::size_t> constantRxnIndices_;              // Fallback indices for small networks
    std::vector<CompiledConstantReaction> constantReactions_;  // Compact constant-rate reaction data
    std::vector<std::size_t> constantReactantIndices_;         // Flattened reactant species indices
    std::vector<std::size_t> constantProductIndices_;          // Flattened product species indices
    bool useCompactConstantReactions_ = false;
    std::vector<std::size_t> functionalRxnIndices_;            // Indices of functional-rate reactions
    SimulationSession* activeSimulationSession_ = nullptr;
    io::TfunRegistry tfunRegistry_;                            // Time-function tables for TFUN expressions
    std::vector<double> cvodeStateScale_;
    mutable std::vector<double> cvodePhysicalState_;
    mutable std::vector<double> cvodePhysicalDerivatives_;
    std::vector<std::size_t> algebraicSpeciesIndices_;
    std::vector<ast::Expression> algebraicResiduals_;
    std::vector<std::size_t> resultFunctionIndices_;                // zero-argument, user-visible, declaration order

    // One native event: the trigger that fires it, the delay between the
    // trigger and the execution, the priority that orders it against the
    // other events executed at the same instant, and the assignments it
    // performs.
    struct NativeEventTarget {
        enum class Kind { Species, Parameter } kind = Kind::Species;
        std::size_t speciesIndex = 0;
        std::string parameterName;
    };
    struct NativeEvent {
        std::string id;
        ast::Expression trigger;
        bool initialValue = true;
        bool persistent = true;
        bool useValuesFromTriggerTime = true;
        std::optional<ast::Expression> delay;
        double priority = 0.0;
        std::optional<ast::Expression> dynamicPriority;
        std::vector<ast::EventAssignment> assignments;
        // The state target each assignment writes, in assignment order.
        std::vector<NativeEventTarget> targets;
    };
    // The events that share one trigger are triggered at the same instant,
    // so they share one root function.
    struct NativeEventGroup {
        ast::Expression trigger;
        std::vector<std::size_t> events;
    };
    // A trigger edge that is waiting for its delay to elapse.
    struct PendingEvent {
        std::size_t event = 0;
        double executionTime = 0.0;
        std::vector<double> values;
    };

    void validateEventTargets();
    double eventValue(const ast::Expression& expression, double time, const double* state) const;
    double eventAssignmentValue(const ast::Expression& expression, double time,
                                const double* state) const;
    // Execute the queued events whose execution instant has arrived.  Returns
    // true when the state changed.
    bool applyDueEvents(double time, std::vector<double>& state);
    double eventSideDerivative(const ast::Expression& expression, double time,
                               const double* state,
                               const std::vector<double>& derivatives) const;
    double eventRootDerivative(const ast::Expression& trigger, double time,
                               const double* state,
                               const std::vector<double>& derivatives) const;
    // The trigger's signed root function: positive exactly where the trigger
    // holds.  A conjunction is the conjunction of its conjuncts, so its root
    // function is the smallest of the conjunct root functions.
    double eventRootValue(const ast::Expression& trigger, double time,
                          const double* state) const;
    // The conjuncts of a trigger; a single inequality is one conjunct.
    static std::vector<const ast::Expression*> triggerConjuncts(
        const ast::Expression& trigger);
    // True when every conjunct of the trigger is a strict inequality.
    static bool isStrictTrigger(const ast::Expression& trigger);
    // The difference that decides the sign of the trigger at a given time and
    // the rate of change of that difference.
    struct TriggerSurface {
        double difference = 0.0;
        double derivative = 0.0;
    };
    TriggerSurface triggerSurface(const ast::Expression& trigger, double time,
                                  const double* state,
                                  const std::vector<double>& derivatives) const;
    std::vector<double> eventValues(const NativeEvent& event, double time,
                                    const double* state) const;
    double eventDelay(const NativeEvent& event, double time,
                      const double* state) const;
    void assignEventValues(const NativeEvent& event, std::vector<double>& state,
                            const std::vector<double>& values);
    // True when the trigger expression holds at the given instant.
    bool triggerHolds(const ast::Expression& trigger, double time,
                      const double* state) const;
    // Queue every event of a trigger group that has just been triggered.
    void queueTriggeredGroup(std::size_t groupIndex, double time,
                             const std::vector<double>& state);
    // Re-test every trigger after an execution (SBML L3V2 Core Sec. 4.12.7,
    // "Detailed semantics of events") and queue the events whose trigger
    // became true.  `heldBefore` holds the trigger values from before the
    // execution, so a rising edge is told from a trigger that was already
    // true.
    void retestTriggers(double time, std::vector<double>& state,
                        const std::vector<bool>& heldBefore);
    std::vector<NativeEvent> nativeEvents_;
    std::unordered_set<std::string> eventAssignedParameterNames_;
    std::unordered_set<std::string> eventDependentParameterNames_;
    std::vector<NativeEventGroup> nativeEventGroups_;
    // CVODE needs a monotonic root function for each conjunct. A minimum of
    // several surfaces can enter and leave a narrow conjunction between two
    // accepted solver states without changing sign.
    std::vector<std::pair<std::size_t, const ast::Expression*>> nativeEventRoots_;
    // Conjuncts whose dynamic dependencies are all species that no reaction
    // changes: they are piecewise constant, change only when an event
    // assigns, and are evaluated exactly instead of as root functions.
    std::unordered_set<const ast::Expression*> discreteEventConjuncts_;
    // Species whose amount some reaction changes (nonzero net stoichiometry).
    std::vector<bool> continuousSpecies_;
    void markContinuousSpecies();
    bool isDiscreteConjunct(const ast::Expression& conjunct) const;
    void pruneDiscreteEventRoots();
    std::vector<PendingEvent> pendingEvents_;
    // The root function value of every group at the last instant the events
    // were processed.  A group whose value changed its sign since then
    // crossed its trigger in the meantime.
    std::vector<double> lastRootValues_;
    // The instant at which each event's trigger last rose.
    std::vector<double> triggerRoseAt_;
    void validateEventRootSurface();
    double evaluateParameterWithEventState(
        const std::string& name, double time,
        const std::unordered_map<std::string, double>& eventValues) const;
    void compile();
    void compileGroups();
    // Evaluate the runtime rate coefficients of every functional-rate reaction
    // into `rates` (which must have one entry per compiled reaction).
    //
    // `groupValues` is the observable scratch the rate expressions are
    // resolved against.  It is supplied by the caller so that the SSA path can
    // use a per-thread buffer: the batched CPU pool shares a single
    // OdeIntegrator across its worker threads, and a shared scratch would make
    // a state-dependent rate law read another trajectory's observable values.
    //
    // `discreteReactantCounts` selects the reactant-count convention for the
    // substrate references a special rate law carries.  The stochastic paths
    // pass true: a repeated identical reactant contributes `population -
    // offset`, the distinct-reactant-pair count canonical BioNetGen uses.  The
    // deterministic path passes false: the same reference contributes the
    // plain population, the concentration-like count canonical BioNetGen's
    // continuous branch uses.
    void evaluateFunctionalRateCoefficients(double t,
                                            const double* y,
                                            double* rates,
                                            std::vector<double>& groupValues,
                                            bool failOnError = false,
                                            bool discreteReactantCounts = false) const;
    void updateGroups(const double* y, std::vector<double>& groupValues) const;
    void correctAlgebraicState(std::vector<double>& state, double time,
                               double tolerance) const;
    void updateFunctions(const std::vector<double>& groupValues,
                         double time,
                         std::vector<double>& functionValues) const;
    std::vector<double> historyStateAt(double time) const;
    std::unordered_map<std::string, double> historyParametersAt(double time) const;
    double evaluateExpressionWithHistory(
        const ast::Expression& expression, double time,
        const double* state,
        bool discreteReactantCounts = false) const;
    void recordHistoryPoint(double time, const std::vector<double>& state);
    void recordHistoryJump(double time, const std::vector<double>& state);
    double reactionFlux(const CompiledReaction& reaction,
                        double rateCoefficient, const double* state) const;
    std::vector<double> outputTimes(const OdeOptions& options) const;
    std::optional<ast::Expression> parseStopIf(const OdeOptions& options) const;
    bool stopConditionMet(const ast::Expression& condition,
                          double time,
                          const std::vector<double>& state) const;
    bool steadyStateReached(const OdeOptions& options,
                            double time,
                            const std::vector<double>& state) const;

    OdeResult integrateEuler(const OdeOptions& opts);
    OdeResult integrateRK4(const OdeOptions& opts);
    OdeResult integrateCvode(const OdeOptions& opts, bool useAdamsFallback = false);
    OdeResult integrateIda(const OdeOptions& opts);
    OdeResult integrateSSA(const OdeOptions& opts);
    OdeResult integrateBatchSSA(const OdeOptions& opts);
    OdeResult integrateCore(const OdeOptions& options);

    double computePropensity(const CompiledReaction& rxn,
                             const std::vector<double>& y,
                             double rateCoefficient) const;
    double computePropensity(const CompiledReaction& rxn,
                             const double* y,
                             double rateCoefficient) const;
};

} // namespace bng::engine
