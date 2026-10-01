#pragma once

#include <functional>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "ast/Model.hpp"
#include "io/TfunReader.hpp"
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
    // CVODE integrates a scaled state to keep very small SBML amounts and
    // very large converted rate constants numerically well-conditioned.
    void cvodeDerivs(double t, const double* y, double* dydt) const;

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
        double rateConstant;          // evaluated rate (for elementary)
        double statFactor;            // statistical factor
        bool isFunctional = false;    // true if rate depends on time/observables
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

    // Performance optimizations
    mutable std::vector<double> groupValues_;                  // Pre-allocated for derivs()
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
    // Per-model function index. `Model::getFunctions()` has a single const-ref
    // accessor (Model.hpp:93) and its only mutators — Model::addFunction
    // (Model.cpp:33) and Model::merge (Model.cpp:244) — run at parse/include
    // time, so the function list cannot change while this integrator is alive.
    // These hold INDEXES into that immutable vector, never computed values, and
    // are built in compile() alongside observableIndex_. A model that gains or
    // loses a function gets a new OdeIntegrator, whose constructor reruns
    // compile(); that constructor is the invalidation point.
    std::unordered_map<std::string, std::size_t> functionIndex_;    // name -> model_.getFunctions() index
    std::unordered_set<std::size_t> zeroArgumentFunctionSet_;       // indexes of zero-argument functions
    std::vector<std::size_t> resultFunctionIndices_;                // zero-argument, user-visible, declaration order
    mutable std::vector<std::string> functionStack_;                // cycle guard reused across updateFunctions() calls

    void compile();
    void compileGroups();
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

    double computePropensity(const CompiledReaction& rxn, const std::vector<double>& y) const;
};

} // namespace bng::engine
