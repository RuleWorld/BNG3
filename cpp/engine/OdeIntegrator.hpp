#pragma once

#include <functional>
#include <string>
#include <unordered_map>
#include <vector>

#include "ast/Model.hpp"
#include "io/TfunReader.hpp"
#include "ast/ModelFunctionEvaluator.hpp"
#include "NetworkGenerator.hpp"

namespace bng::engine {

struct OdeOptions {
    double tStart = 0.0;
    double tEnd = 1.0;
    std::size_t nSteps = 100;
    double rtol = 1e-8;
    double atol = 1e-12;
    std::string method = "euler";  // "euler", "rk4", "cvode" (cvode not yet implemented)
    double maxStep = 0.0;          // 0 = no limit
    std::string stopCondition;     // muParser expression (empty = none)
    unsigned int seed = 0;         // for SSA (0 = random)
    bool steadyState = false;      // Enable steady-state detection
    double steadyStateTol = 1e-8;  // Tolerance for steady-state (|dydt| < tol)
    std::string stopIf;            // Boolean expression to evaluate at each step
    bool printCDAT = true;         // Whether to write .cdat output file
    bool printFunctions = false;   // Whether to write .fdat output file
    std::vector<double> sampleTimes; // Non-uniform output time points (overrides nSteps)
    std::size_t maxSimSteps = 0;   // Max internal simulation steps (0 = unlimited)
    bool saveProgress = false;     // Write .net checkpoint at each output step
    bool printNet = false;         // Write .net file after simulation with final concentrations
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
    void writeOutputFiles(const std::string& prefix, const OdeResult& result, bool printCDAT = true, bool printFunctions = false, bool append = false) const;
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
        std::optional<ast::Expression> functionalRateExpr;  // for runtime evaluation
        bool isTotalRate = false;     // true if rate is total (not multiplied by reactant conc)
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
    };

    std::vector<CompiledReaction> compiledRxns_;
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
    io::TfunRegistry tfunRegistry_;                            // Time-function tables for TFUN expressions
    std::vector<double> cvodeStateScale_;
    mutable std::vector<double> cvodePhysicalState_;
    mutable std::vector<double> cvodePhysicalDerivatives_;
    std::vector<std::size_t> resultFunctionIndices_;                // zero-argument, user-visible, declaration order

    // One native event: the trigger that fires it, the delay between the
    // trigger and the execution, the priority that orders it against the
    // other events executed at the same instant, and the assignments it
    // performs.
    struct NativeEvent {
        std::string id;
        ast::Expression trigger;
        bool initialValue = true;
        bool persistent = true;
        bool useValuesFromTriggerTime = true;
        double delay = 0.0;
        double priority = 0.0;
        std::vector<ast::EventAssignment> assignments;
        // The species each assignment writes, in the order of `assignments`.
        std::vector<std::size_t> targets;
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
    // Execute the queued events whose execution instant has arrived.  Returns
    // true when the state changed.
    bool applyDueEvents(double time, std::vector<double>& state);
    double eventSideDerivative(const ast::Expression& expression, double time,
                               const std::vector<double>& derivatives) const;
    double eventRootDerivative(const ast::Expression& trigger, double time,
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
    void assignEventValues(const NativeEvent& event, std::vector<double>& state,
                            const std::vector<double>& values) const;
    // True when the trigger expression holds at the given instant.
    bool triggerHolds(const ast::Expression& trigger, double time,
                      const double* state) const;
    // Queue every event of a trigger group that has just been triggered.
    void queueTriggeredGroup(std::size_t groupIndex, double time,
                             const std::vector<double>& state);
    // Re-test every trigger after an execution (SBML L3V2 Core Sec. 4.12.8)
    // and queue the events whose trigger became true.  `heldBefore` holds the
    // trigger values from before the execution, so a rising edge is told
    // from a trigger that was already true.
    void retestTriggers(double time, std::vector<double>& state,
                        const std::vector<bool>& heldBefore);
    std::vector<NativeEvent> nativeEvents_;
    std::vector<NativeEventGroup> nativeEventGroups_;
    std::vector<PendingEvent> pendingEvents_;
    // The root function value of every group at the last instant the events
    // were processed.  A group whose value changed its sign since then
    // crossed its trigger in the meantime.
    std::vector<double> lastRootValues_;
    // The instant at which each event's trigger last rose.
    std::vector<double> triggerRoseAt_;
    void validateEventRootSurface();
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
    void evaluateFunctionalRateCoefficients(double t,
                                            const double* y,
                                            double* rates,
                                            std::vector<double>& groupValues,
                                            bool failOnError = false) const;
    void updateGroups(const double* y, std::vector<double>& groupValues) const;
    void updateFunctions(const std::vector<double>& groupValues,
                         double time,
                         std::vector<double>& functionValues) const;
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
    OdeResult integrateCvode(const OdeOptions& opts);
    OdeResult integrateSSA(const OdeOptions& opts);
    OdeResult integrateBatchSSA(const OdeOptions& opts);

    double computePropensity(const CompiledReaction& rxn,
                             const std::vector<double>& y,
                             double rateCoefficient) const;
    double computePropensity(const CompiledReaction& rxn,
                             const double* y,
                             double rateCoefficient) const;
};

} // namespace bng::engine
