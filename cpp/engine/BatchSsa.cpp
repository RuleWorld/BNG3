#include "compile/CompiledModel.hpp"
#include "engine/BatchSsa.hpp"
#include "engine/DelayedSemanticsGuard.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <future>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>

namespace bng::engine {

namespace {

// Centered online moments and pairwise merging avoid subtracting two large,
// nearly equal raw moments when the ensemble has a small spread.
struct RunningMoments {
    std::size_t count = 0;
    double mean = 0.0;
    double centeredSumSquares = 0.0;

    void add(double value) {
        ++count;
        const double delta = value - mean;
        mean += delta / static_cast<double>(count);
        centeredSumSquares += delta * (value - mean);
    }

    void merge(const RunningMoments& other) {
        if (other.count == 0) return;
        if (count == 0) {
            *this = other;
            return;
        }
        const std::size_t combinedCount = count + other.count;
        const double delta = other.mean - mean;
        const double otherWeight = static_cast<double>(other.count) / combinedCount;
        centeredSumSquares += other.centeredSumSquares
            + delta * delta * static_cast<double>(count) * otherWeight;
        mean += delta * otherWeight;
        count = combinedCount;
    }

    double average() const {
        return count > 0 ? mean : std::numeric_limits<double>::quiet_NaN();
    }

    double standardDeviation() const {
        return count > 0
            ? std::sqrt(std::max(0.0, centeredSumSquares / count))
            : 0.0;
    }
};

int32_t checkedPopulation(double population) {
    if (!std::isfinite(population)
        || population < std::numeric_limits<int32_t>::min()
        || population > std::numeric_limits<int32_t>::max()) {
        throw std::runtime_error("Batch SSA: population is outside int32 range");
    }
    return static_cast<int32_t>(population);
}

int32_t recordFinalSpeciesPopulation(double value, bool allowContinuousEventRange) {
    const double rounded = std::round(value);
    if (!allowContinuousEventRange) {
        return checkedPopulation(rounded);
    }
    if (!std::isfinite(rounded)) {
        throw std::runtime_error("Batch SSA: non-finite final state value");
    }
    constexpr double kMin = static_cast<double>(std::numeric_limits<int32_t>::min());
    constexpr double kMax = static_cast<double>(std::numeric_limits<int32_t>::max());
    return static_cast<int32_t>(std::clamp(rounded, kMin, kMax));
}

} // namespace

namespace detail {

std::vector<float> batchOutputTimes(const BatchSsaOptions& options) {
    const std::size_t numPoints = static_cast<std::size_t>(options.nSteps) + 1;
    std::vector<float> times(numPoints);
    const double step = (options.nSteps > 0)
        ? (options.tEnd - options.tStart) / options.nSteps
        : 0.0;
    for (std::size_t i = 0; i < numPoints; ++i) {
        times[i] = static_cast<float>(options.tStart + static_cast<double>(i) * step);
    }
    return times;
}

// Populate the double-precision mean/std fields in BatchSsaMetrics from the
// float observableMeans/StdDevs already computed, so OdeIntegrator can consume
// them directly without a redundant conversion loop at the call site.
void fillDoubleFields(BatchSsaMetrics& m) {
    const std::size_t T = m.timePoints.size();
    const std::size_t G = m.observableMeans.empty() ? 0 : m.observableMeans[0].size();

    m.timePointsDouble.resize(T);
    for (std::size_t t = 0; t < T; ++t)
        m.timePointsDouble[t] = static_cast<double>(m.timePoints[t]);

    m.meanObservables.resize(T, std::vector<double>(G));
    m.stdObservables.resize(T, std::vector<double>(G));
    for (std::size_t t = 0; t < T; ++t)
        for (std::size_t g = 0; g < G; ++g) {
            m.meanObservables[t][g] = static_cast<double>(m.observableMeans[t][g]);
            m.stdObservables[t][g]  = static_cast<double>(m.observableStdDevs[t][g]);
        }

    // meanSpecies/stdSpecies: backends that record a full species time grid
    // (including the GPU batch kernels) already populated these fields; never
    // replace that grid with a single final-state row. Only derive a one-point
    // grid for backends that expose finalSpecies alone.
    if (m.meanSpecies.empty() && !m.finalSpecies.empty() && m.batchSize > 0) {
        const std::size_t S = m.finalSpecies.size() / m.batchSize;
        // We only have final-state species — build a single time-point vector.
        m.meanSpecies.assign(1, std::vector<double>(S, 0.0));
        m.stdSpecies.assign(1, std::vector<double>(S, 0.0));
        std::vector<RunningMoments> moments(S);
        for (std::size_t b = 0; b < m.batchSize; ++b)
            for (std::size_t s = 0; s < S; ++s) {
                moments[s].add(static_cast<double>(m.finalSpecies[b * S + s]));
            }
        for (std::size_t s = 0; s < S; ++s) {
            m.meanSpecies[0][s] = moments[s].average();
            m.stdSpecies[0][s] = moments[s].standardDeviation();
        }
    }
}

} // namespace detail



// ============================================================================
// Network Flattening & Validation (Fail-closed on unsupported rate laws)
// ============================================================================

namespace {

constexpr uint32_t kMaxBatchVmStack = 32u;

float checkedFloat32Constant(double value, const std::string& context) {
    if (!std::isfinite(value)) {
        throw std::runtime_error("Batch SSA: non-finite constant in " + context + "; failing closed.");
    }
    if (std::abs(value) > static_cast<double>(std::numeric_limits<float>::max())) {
        throw std::runtime_error("Batch SSA: constant out of float32 range in " + context + "; failing closed.");
    }
    const float f = static_cast<float>(value);
    if (value != 0.0 && f == 0.0f) {
        throw std::runtime_error("Batch SSA: constant underflows float32 in " + context + "; failing closed.");
    }
    return f;
}

bool parseSubstrateLocal(const std::string& name, uint32_t& speciesIdx, float& offset) {
    constexpr const char* kPrefix = "__substrate_";
    constexpr std::size_t kPrefixLen = 12;
    if (name.compare(0, kPrefixLen, kPrefix) != 0) return false;
    const std::string rest = name.substr(kPrefixLen);
    if (rest.empty()) return false;
    const std::size_t offPos = rest.find("_off");
    const std::string idxStr = (offPos == std::string::npos) ? rest : rest.substr(0, offPos);
    if (idxStr.empty()) return false;
    for (char c : idxStr) {
        if (c < '0' || c > '9') return false;
    }
    try {
        const unsigned long parsedIdx = std::stoul(idxStr);
        if (parsedIdx > std::numeric_limits<uint32_t>::max()) return false;
        speciesIdx = static_cast<uint32_t>(parsedIdx);
    } catch (...) {
        return false;
    }
    if (offPos == std::string::npos) {
        offset = 0.0f;
        return true;
    }
    const std::string offStr = rest.substr(offPos + 4);
    if (offStr.empty()) return false;
    for (char c : offStr) {
        if (c < '0' || c > '9') return false;
    }
    try {
        const unsigned long parsedOff = std::stoul(offStr);
        offset = static_cast<float>(parsedOff);
    } catch (...) {
        return false;
    }
    return true;
}

struct BatchVmCompiler {
    const compile::CompiledModel& compiledModel;
    const std::unordered_map<std::string, uint32_t>& obsNameToIndex;
    const std::vector<std::size_t>& reactantIndices;
    uint32_t numSpecies = 0;
    std::size_t reactionIndex = 0;
    std::vector<BatchVmInstr>& out;
    uint32_t baseOffset = 0;
    int32_t curStack = 0;
    int32_t maxStack = 0;
    std::unordered_set<std::size_t> activeFunctions;

    void pushInstr(BatchVmInstr ins, int32_t stackDelta) {
        curStack += stackDelta;
        if (curStack < 0 || curStack > static_cast<int32_t>(kMaxBatchVmStack)) {
            throw std::runtime_error(
                "Batch SSA: functional rate VM stack overflow in reaction " +
                std::to_string(reactionIndex) + "; failing closed.");
        }
        if (curStack > maxStack) maxStack = curStack;
        out.push_back(ins);
    }

    uint32_t emitOp(uint8_t op, int32_t stackDelta, uint32_t index = 0, float value = 0.0f) {
        const uint32_t pc = static_cast<uint32_t>(out.size()) - baseOffset;
        BatchVmInstr ins{};
        ins.op = op;
        ins.index = index;
        ins.value = value;
        pushInstr(ins, stackDelta);
        return pc;
    }

    void emitConst(double value) {
        const float f = checkedFloat32Constant(
            value, "functional rate of reaction " + std::to_string(reactionIndex));
        emitOp(kBatchVmConst, +1, 0u, f);
    }

    void compileExpr(const compile::ResolvedExpression& expr) {
        using K = compile::ResolvedExpressionKind;
        switch (expr.kind) {
        case K::Number:
            emitConst(expr.numberValue);
            return;

        case K::ParameterRef: {
            const compile::CompiledParameter* param = nullptr;
            if (expr.symbol && expr.symbol->kind == compile::SymbolKind::Parameter &&
                expr.symbol->index < compiledModel.parameters().size()) {
                param = &compiledModel.parameters()[expr.symbol->index];
            } else {
                for (const auto& candidate : compiledModel.parameters()) {
                    if (candidate.name == expr.operation || candidate.name == expr.source) {
                        param = &candidate;
                        break;
                    }
                }
            }
            if (!param || param->timeDependent || !param->constantValue.has_value()) {
                throw std::runtime_error(
                    "Batch SSA: unsupported or time-dependent parameter '" + expr.operation +
                    "' in functional rate of reaction " + std::to_string(reactionIndex) +
                    "; failing closed.");
            }
            emitConst(*param->constantValue);
            return;
        }

        case K::ObservableRef: {
            if (!expr.arguments.empty()) {
                throw std::runtime_error(
                    "Batch SSA: local observable reference '" + expr.operation +
                    "' is unsupported in reaction " + std::to_string(reactionIndex) +
                    "; failing closed.");
            }
            auto it = obsNameToIndex.find(expr.operation);
            if (it == obsNameToIndex.end() && expr.symbol &&
                expr.symbol->kind == compile::SymbolKind::Observable &&
                expr.symbol->index < compiledModel.observables().size()) {
                it = obsNameToIndex.find(compiledModel.observables()[expr.symbol->index].name);
            }
            if (it == obsNameToIndex.end()) {
                throw std::runtime_error(
                    "Batch SSA: unresolved observable '" + expr.operation +
                    "' in functional rate of reaction " + std::to_string(reactionIndex) +
                    "; failing closed.");
            }
            emitOp(kBatchVmObservable, +1, it->second, 0.0f);
            return;
        }

        case K::LocalRef: {
            uint32_t sIdx = 0;
            float offset = 0.0f;
            if (parseSubstrateLocal(expr.localName, sIdx, offset) && sIdx < numSpecies) {
                emitOp(kBatchVmSpeciesCount, +1, sIdx, offset);
                return;
            }
            throw std::runtime_error(
                "Batch SSA: unsupported local reference '" + expr.localName +
                "' in functional rate of reaction " + std::to_string(reactionIndex) +
                "; failing closed.");
        }

        case K::ReactantCountRef: {
            if (expr.reactantIndex >= reactantIndices.size()) {
                throw std::runtime_error(
                    "Batch SSA: reactant count reference out of range in reaction " +
                    std::to_string(reactionIndex) + "; failing closed.");
            }
            const std::size_t sIdx = reactantIndices[expr.reactantIndex];
            if (sIdx >= numSpecies) {
                throw std::runtime_error("Batch SSA: reactant species index out of range");
            }
            const std::size_t priorCount = static_cast<std::size_t>(std::count(
                reactantIndices.begin(),
                reactantIndices.begin() + static_cast<std::ptrdiff_t>(expr.reactantIndex),
                sIdx));
            emitOp(kBatchVmSpeciesCount, +1, static_cast<uint32_t>(sIdx),
                   static_cast<float>(priorCount));
            return;
        }

        case K::Unary: {
            if (expr.arguments.size() != 1 || !expr.unaryOp.has_value()) {
                throw std::runtime_error("Batch SSA: malformed unary expression; failing closed.");
            }
            compileExpr(expr.arguments[0]);
            switch (*expr.unaryOp) {
            case compile::UnaryOp::Plus:
                return;
            case compile::UnaryOp::Negate:
                emitOp(kBatchVmNeg, 0);
                return;
            case compile::UnaryOp::LogicalNot:
                emitConst(0.0);
                emitOp(kBatchVmEqual, -1);
                return;
            case compile::UnaryOp::Unknown:
                break;
            }
            throw std::runtime_error("Batch SSA: unsupported unary operator; failing closed.");
        }

        case K::Binary: {
            if (expr.arguments.size() != 2 || !expr.binaryOp.has_value()) {
                throw std::runtime_error("Batch SSA: malformed binary expression; failing closed.");
            }
            if (*expr.binaryOp == compile::BinaryOp::LogicalAnd) {
                compileExpr(expr.arguments[0]);
                const uint32_t jzPc = emitOp(kBatchVmJumpIfZero, -1, 0u);
                const int32_t stackBefore = curStack;
                compileExpr(expr.arguments[1]);
                emitConst(0.0);
                emitOp(kBatchVmNotEqual, -1);
                const uint32_t jmpPc = emitOp(kBatchVmJump, 0, 0u);
                out[baseOffset + jzPc].index = static_cast<uint32_t>(out.size()) - baseOffset;
                curStack = stackBefore;
                emitConst(0.0);
                out[baseOffset + jmpPc].index = static_cast<uint32_t>(out.size()) - baseOffset;
                return;
            }
            if (*expr.binaryOp == compile::BinaryOp::LogicalOr) {
                compileExpr(expr.arguments[0]);
                const uint32_t jzPc = emitOp(kBatchVmJumpIfZero, -1, 0u);
                const int32_t stackBefore = curStack;
                emitConst(1.0);
                const uint32_t jmpPc = emitOp(kBatchVmJump, 0, 0u);
                out[baseOffset + jzPc].index = static_cast<uint32_t>(out.size()) - baseOffset;
                curStack = stackBefore;
                compileExpr(expr.arguments[1]);
                emitConst(0.0);
                emitOp(kBatchVmNotEqual, -1);
                out[baseOffset + jmpPc].index = static_cast<uint32_t>(out.size()) - baseOffset;
                return;
            }
            compileExpr(expr.arguments[0]);
            compileExpr(expr.arguments[1]);
            switch (*expr.binaryOp) {
            case compile::BinaryOp::Add:          emitOp(kBatchVmAdd, -1); return;
            case compile::BinaryOp::Subtract:     emitOp(kBatchVmSub, -1); return;
            case compile::BinaryOp::Multiply:     emitOp(kBatchVmMul, -1); return;
            case compile::BinaryOp::Divide:       emitOp(kBatchVmDiv, -1); return;
            case compile::BinaryOp::Power:        emitOp(kBatchVmPow, -1); return;
            case compile::BinaryOp::Less:         emitOp(kBatchVmLess, -1); return;
            case compile::BinaryOp::LessEqual:    emitOp(kBatchVmLessEq, -1); return;
            case compile::BinaryOp::Greater:      emitOp(kBatchVmGreater, -1); return;
            case compile::BinaryOp::GreaterEqual: emitOp(kBatchVmGreaterEq, -1); return;
            case compile::BinaryOp::Equal:        emitOp(kBatchVmEqual, -1); return;
            case compile::BinaryOp::NotEqual:     emitOp(kBatchVmNotEqual, -1); return;
            case compile::BinaryOp::LogicalAnd:
            case compile::BinaryOp::LogicalOr:
            case compile::BinaryOp::Modulo:
            case compile::BinaryOp::LogicalXor:
            case compile::BinaryOp::Unknown:
                break;
            }
            throw std::runtime_error("Batch SSA: unsupported binary operator; failing closed.");
        }

        case K::BuiltinCall: {
            if (!expr.builtin.has_value()) {
                throw std::runtime_error("Batch SSA: unknown builtin call; failing closed.");
            }
            using B = compile::BuiltinFunction;
            switch (*expr.builtin) {
            case B::Pi:
                emitConst(3.14159265358979323846);
                return;
            case B::E:
                emitConst(2.71828182845904523536);
                return;
            case B::Exp:
                if (expr.arguments.size() != 1) throw std::runtime_error("Batch SSA: exp() expects 1 argument");
                compileExpr(expr.arguments[0]);
                emitOp(kBatchVmExp, 0);
                return;
            case B::Ln:
                if (expr.arguments.size() != 1) throw std::runtime_error("Batch SSA: ln() expects 1 argument");
                compileExpr(expr.arguments[0]);
                emitOp(kBatchVmLog, 0);
                return;
            case B::Log10:
                if (expr.arguments.size() != 1) throw std::runtime_error("Batch SSA: log10() expects 1 argument");
                compileExpr(expr.arguments[0]);
                emitOp(kBatchVmLog, 0);
                emitConst(std::log(10.0));
                emitOp(kBatchVmDiv, -1);
                return;
            case B::Log2:
                if (expr.arguments.size() != 1) throw std::runtime_error("Batch SSA: log2() expects 1 argument");
                compileExpr(expr.arguments[0]);
                emitOp(kBatchVmLog, 0);
                emitConst(std::log(2.0));
                emitOp(kBatchVmDiv, -1);
                return;
            case B::Sqrt:
                if (expr.arguments.size() != 1) throw std::runtime_error("Batch SSA: sqrt() expects 1 argument");
                compileExpr(expr.arguments[0]);
                emitOp(kBatchVmSqrt, 0);
                return;
            case B::Sin:
                if (expr.arguments.size() != 1) throw std::runtime_error("Batch SSA: sin() expects 1 argument");
                compileExpr(expr.arguments[0]);
                emitOp(kBatchVmSin, 0);
                return;
            case B::Cos:
                if (expr.arguments.size() != 1) throw std::runtime_error("Batch SSA: cos() expects 1 argument");
                compileExpr(expr.arguments[0]);
                emitOp(kBatchVmCos, 0);
                return;
            case B::Tan:
                if (expr.arguments.size() != 1) throw std::runtime_error("Batch SSA: tan() expects 1 argument");
                compileExpr(expr.arguments[0]);
                emitOp(kBatchVmTan, 0);
                return;
            case B::Abs:
                if (expr.arguments.size() != 1) throw std::runtime_error("Batch SSA: abs() expects 1 argument");
                compileExpr(expr.arguments[0]);
                emitOp(kBatchVmAbs, 0);
                return;
            case B::Min:
                if (expr.arguments.size() < 2) throw std::runtime_error("Batch SSA: min() expects >=2 arguments");
                compileExpr(expr.arguments[0]);
                for (std::size_t i = 1; i < expr.arguments.size(); ++i) {
                    compileExpr(expr.arguments[i]);
                    emitOp(kBatchVmMin, -1);
                }
                return;
            case B::Max:
                if (expr.arguments.size() < 2) throw std::runtime_error("Batch SSA: max() expects >=2 arguments");
                compileExpr(expr.arguments[0]);
                for (std::size_t i = 1; i < expr.arguments.size(); ++i) {
                    compileExpr(expr.arguments[i]);
                    emitOp(kBatchVmMax, -1);
                }
                return;
            case B::Sum:
                if (expr.arguments.empty()) throw std::runtime_error("Batch SSA: sum() expects >=1 argument");
                compileExpr(expr.arguments[0]);
                for (std::size_t i = 1; i < expr.arguments.size(); ++i) {
                    compileExpr(expr.arguments[i]);
                    emitOp(kBatchVmAdd, -1);
                }
                return;
            case B::Avg:
                if (expr.arguments.empty()) throw std::runtime_error("Batch SSA: avg() expects >=1 argument");
                compileExpr(expr.arguments[0]);
                for (std::size_t i = 1; i < expr.arguments.size(); ++i) {
                    compileExpr(expr.arguments[i]);
                    emitOp(kBatchVmAdd, -1);
                }
                emitConst(static_cast<double>(expr.arguments.size()));
                emitOp(kBatchVmDiv, -1);
                return;
            case B::If: {
                if (expr.arguments.size() != 3) throw std::runtime_error("Batch SSA: if() expects 3 arguments");
                compileExpr(expr.arguments[0]);
                const uint32_t jzPc = emitOp(kBatchVmJumpIfZero, -1, 0u);
                const int32_t stackBeforeBranch = curStack;
                compileExpr(expr.arguments[1]);
                const uint32_t jmpPc = emitOp(kBatchVmJump, 0, 0u);
                const uint32_t elsePc = static_cast<uint32_t>(out.size()) - baseOffset;
                out[baseOffset + jzPc].index = elsePc;
                curStack = stackBeforeBranch;
                compileExpr(expr.arguments[2]);
                const uint32_t endPc = static_cast<uint32_t>(out.size()) - baseOffset;
                out[baseOffset + jmpPc].index = endPc;
                return;
            }
            case B::Saturation: {
                // Sat(k0, K, S): (K + S != 0) ? (k0 * S / (K + S)) : 0
                if (expr.arguments.size() == 2) {
                    compileExpr(expr.arguments[0]);
                    return;
                }
                if (expr.arguments.size() >= 3) {
                    compileExpr(expr.arguments[1]);
                    compileExpr(expr.arguments[2]);
                    emitOp(kBatchVmAdd, -1);
                    emitConst(0.0);
                    emitOp(kBatchVmNotEqual, -1);
                    const uint32_t jzPc = emitOp(kBatchVmJumpIfZero, -1, 0u);
                    const int32_t stackBefore = curStack;
                    compileExpr(expr.arguments[0]);
                    compileExpr(expr.arguments[2]);
                    emitOp(kBatchVmMul, -1);
                    compileExpr(expr.arguments[1]);
                    compileExpr(expr.arguments[2]);
                    emitOp(kBatchVmAdd, -1);
                    emitOp(kBatchVmDiv, -1);
                    const uint32_t jmpPc = emitOp(kBatchVmJump, 0, 0u);
                    out[baseOffset + jzPc].index = static_cast<uint32_t>(out.size()) - baseOffset;
                    curStack = stackBefore;
                    emitConst(0.0);
                    out[baseOffset + jmpPc].index = static_cast<uint32_t>(out.size()) - baseOffset;
                    return;
                }
                throw std::runtime_error("Batch SSA: Sat() requires 2 or 3 arguments; failing closed.");
            }
            case B::Hill: {
                // Hill(Vmax, Kh, n, S): den = Kh^n + S^n; (den != 0) ? Vmax * S^n / den : 0
                if (expr.arguments.size() >= 4) {
                    compileExpr(expr.arguments[1]);
                    compileExpr(expr.arguments[2]);
                    emitOp(kBatchVmPow, -1);
                    compileExpr(expr.arguments[3]);
                    compileExpr(expr.arguments[2]);
                    emitOp(kBatchVmPow, -1);
                    emitOp(kBatchVmAdd, -1);
                    emitConst(0.0);
                    emitOp(kBatchVmNotEqual, -1);
                    const uint32_t jzPc = emitOp(kBatchVmJumpIfZero, -1, 0u);
                    const int32_t stackBefore = curStack;
                    compileExpr(expr.arguments[0]);
                    compileExpr(expr.arguments[3]);
                    compileExpr(expr.arguments[2]);
                    emitOp(kBatchVmPow, -1);
                    emitOp(kBatchVmMul, -1);
                    compileExpr(expr.arguments[1]);
                    compileExpr(expr.arguments[2]);
                    emitOp(kBatchVmPow, -1);
                    compileExpr(expr.arguments[3]);
                    compileExpr(expr.arguments[2]);
                    emitOp(kBatchVmPow, -1);
                    emitOp(kBatchVmAdd, -1);
                    emitOp(kBatchVmDiv, -1);
                    const uint32_t jmpPc = emitOp(kBatchVmJump, 0, 0u);
                    out[baseOffset + jzPc].index = static_cast<uint32_t>(out.size()) - baseOffset;
                    curStack = stackBefore;
                    emitConst(0.0);
                    out[baseOffset + jmpPc].index = static_cast<uint32_t>(out.size()) - baseOffset;
                    return;
                }
                throw std::runtime_error("Batch SSA: Hill() requires 4 arguments; failing closed.");
            }
            case B::MichaelisMenten: {
                if (expr.arguments.size() == 3) {
                    // MM(Vmax, Km, S) == Sat(Vmax, Km, S)
                    compileExpr(expr.arguments[1]);
                    compileExpr(expr.arguments[2]);
                    emitOp(kBatchVmAdd, -1);
                    emitConst(0.0);
                    emitOp(kBatchVmNotEqual, -1);
                    const uint32_t jzPc = emitOp(kBatchVmJumpIfZero, -1, 0u);
                    const int32_t stackBefore = curStack;
                    compileExpr(expr.arguments[0]);
                    compileExpr(expr.arguments[2]);
                    emitOp(kBatchVmMul, -1);
                    compileExpr(expr.arguments[1]);
                    compileExpr(expr.arguments[2]);
                    emitOp(kBatchVmAdd, -1);
                    emitOp(kBatchVmDiv, -1);
                    const uint32_t jmpPc = emitOp(kBatchVmJump, 0, 0u);
                    out[baseOffset + jzPc].index = static_cast<uint32_t>(out.size()) - baseOffset;
                    curStack = stackBefore;
                    emitConst(0.0);
                    out[baseOffset + jmpPc].index = static_cast<uint32_t>(out.size()) - baseOffset;
                    return;
                }
                if (expr.arguments.size() == 4) {
                    // Self-consistent MM(kcat, Km, St, Et):
                    // b = St - Km - Et
                    // q = sqrt(b*b + 4*St*Km)
                    // S = (b >= 0) ? 0.5*(b + q) : 2*St*Km / (q - b)
                    // rate = (Km + S != 0) ? kcat * Et * S / (Km + S) : 0
                    auto emitB = [&]() {
                        compileExpr(expr.arguments[2]);
                        compileExpr(expr.arguments[1]);
                        emitOp(kBatchVmSub, -1);
                        compileExpr(expr.arguments[3]);
                        emitOp(kBatchVmSub, -1);
                    };
                    auto emitQ = [&]() {
                        emitB();
                        emitConst(2.0);
                        emitOp(kBatchVmPow, -1);
                        emitConst(4.0);
                        compileExpr(expr.arguments[2]);
                        emitOp(kBatchVmMul, -1);
                        compileExpr(expr.arguments[1]);
                        emitOp(kBatchVmMul, -1);
                        emitOp(kBatchVmAdd, -1);
                        emitOp(kBatchVmSqrt, 0);
                    };
                    auto emitS = [&]() {
                        emitB();
                        emitConst(0.0);
                        emitOp(kBatchVmGreaterEq, -1);
                        const uint32_t jzB = emitOp(kBatchVmJumpIfZero, -1, 0u);
                        const int32_t stackB = curStack;
                        emitConst(0.5);
                        emitB();
                        emitQ();
                        emitOp(kBatchVmAdd, -1);
                        emitOp(kBatchVmMul, -1);
                        const uint32_t jmpB = emitOp(kBatchVmJump, 0, 0u);
                        out[baseOffset + jzB].index = static_cast<uint32_t>(out.size()) - baseOffset;
                        curStack = stackB;
                        emitConst(2.0);
                        compileExpr(expr.arguments[2]);
                        emitOp(kBatchVmMul, -1);
                        compileExpr(expr.arguments[1]);
                        emitOp(kBatchVmMul, -1);
                        emitQ();
                        emitB();
                        emitOp(kBatchVmSub, -1);
                        emitOp(kBatchVmDiv, -1);
                        out[baseOffset + jmpB].index = static_cast<uint32_t>(out.size()) - baseOffset;
                    };
                    compileExpr(expr.arguments[1]);
                    emitS();
                    emitOp(kBatchVmAdd, -1);
                    emitConst(0.0);
                    emitOp(kBatchVmNotEqual, -1);
                    const uint32_t jzDen = emitOp(kBatchVmJumpIfZero, -1, 0u);
                    const int32_t stackDen = curStack;
                    compileExpr(expr.arguments[0]);
                    compileExpr(expr.arguments[3]);
                    emitOp(kBatchVmMul, -1);
                    emitS();
                    emitOp(kBatchVmMul, -1);
                    compileExpr(expr.arguments[1]);
                    emitS();
                    emitOp(kBatchVmAdd, -1);
                    emitOp(kBatchVmDiv, -1);
                    const uint32_t jmpDen = emitOp(kBatchVmJump, 0, 0u);
                    out[baseOffset + jzDen].index = static_cast<uint32_t>(out.size()) - baseOffset;
                    curStack = stackDen;
                    emitConst(0.0);
                    out[baseOffset + jmpDen].index = static_cast<uint32_t>(out.size()) - baseOffset;
                    return;
                }
                throw std::runtime_error("Batch SSA: MM() requires 3 or 4 arguments; failing closed.");
            }
            case B::FunctionProduct:
                if (expr.arguments.empty()) {
                    emitConst(1.0);
                    return;
                }
                compileExpr(expr.arguments[0]);
                for (std::size_t i = 1; i < expr.arguments.size(); ++i) {
                    compileExpr(expr.arguments[i]);
                    emitOp(kBatchVmMul, -1);
                }
                return;
            default:
                throw std::runtime_error(
                    "Batch SSA: unsupported builtin '" + expr.operation +
                    "' in functional rate of reaction " + std::to_string(reactionIndex) +
                    "; failing closed.");
            }
        }

        case K::FunctionRef: {
            const compile::CompiledFunction* fn = nullptr;
            std::size_t fnIdx = std::numeric_limits<std::size_t>::max();
            if (expr.symbol && expr.symbol->kind == compile::SymbolKind::Function &&
                expr.symbol->index < compiledModel.functions().size()) {
                fnIdx = expr.symbol->index;
                fn = &compiledModel.functions()[fnIdx];
            } else {
                for (std::size_t i = 0; i < compiledModel.functions().size(); ++i) {
                    if (compiledModel.functions()[i].name == expr.operation) {
                        fnIdx = i;
                        fn = &compiledModel.functions()[i];
                        break;
                    }
                }
            }
            if (!fn || !expr.arguments.empty() || !fn->arguments.empty()) {
                throw std::runtime_error(
                    "Batch SSA: unsupported function call '" + expr.source +
                    "' in reaction " + std::to_string(reactionIndex) + "; failing closed.");
            }
            if (!activeFunctions.insert(fnIdx).second) {
                throw std::runtime_error(
                    "Batch SSA: recursive function '" + fn->name +
                    "' in reaction " + std::to_string(reactionIndex) + "; failing closed.");
            }
            const auto body = compiledModel.expandFunctions(fn->expression);
            compileExpr(body);
            activeFunctions.erase(fnIdx);
            return;
        }

        case K::TimeRef:
        case K::TableFunction:
        case K::Unresolved:
            throw std::runtime_error(
                "Batch SSA: unsupported rate expression node ('" + expr.source +
                "') in reaction " + std::to_string(reactionIndex) + "; failing closed.");
        }
    }
};

} // namespace

FlattenedReactionNetwork FlattenedReactionNetwork::fromModelAndNetwork(
    const ast::Model& model,
    const GeneratedNetwork& network
) {
    compile::requireNoNativeEvents(model, "batch SSA/JAX flattening");
    requireNoDelayedSemantics(model, network, "batch SSA/JAX flattening");
    FlattenedReactionNetwork flat;
    OdeIntegrator integrator(model, network);

    const auto& compiledRxns = integrator.getCompiledReactions();
    const auto& compiledGroups = integrator.getCompiledGroups();
    if (std::any_of(compiledRxns.begin(), compiledRxns.end(),
                    [](const auto& rxn) { return rxn.isRateRuleChannel; })) {
        throw std::runtime_error(
            "Batch SSA/JAX flattening does not support continuous SBML rateRule channels");
    }

    flat.numSpecies = static_cast<uint32_t>(network.species.size());
    flat.numReactions = static_cast<uint32_t>(compiledRxns.size());
    flat.numObservables = static_cast<uint32_t>(compiledGroups.size());

    // Initial species populations (exact integers)
    flat.initialSpecies.resize(flat.numSpecies);
    for (std::size_t i = 0; i < flat.numSpecies; ++i) {
        double amt = network.species.get(i).getAmount();
        flat.initialSpecies[i] = checkedPopulation(std::max(0.0, std::round(amt)));
    }

    // A constant species carries the model's "this amount does not change"
    // marker (BNGL's ``$`` seed species; SBML's ``boundaryCondition``).  The
    // deterministic reading honours it, the partitioned simulators honour it
    // and the direct method honours it, so the flattened state-change lists
    // have to omit it as well: a reaction may name a constant species, but it
    // may not change it.  The reactant list is untouched for mass-action
    // reactions so a constant species still contributes its amount to the
    // propensity; for absolute-flux reactions, constant reactants are never
    // consumed so they do not gate stoichiometric availability.
    std::vector<bool> constantSpecies(flat.numSpecies, false);
    for (std::size_t i = 0; i < flat.numSpecies; ++i) {
        constantSpecies[i] = network.species.get(i).isConstant();
    }

    // Observables (built first so functional-rate bytecode can bind observable indices)
    flat.obsOffsets.reserve(flat.numObservables + 1);
    flat.obsOffsets.push_back(0);
    std::unordered_map<std::string, uint32_t> obsNameToIndex;
    obsNameToIndex.reserve(flat.numObservables);
    for (std::size_t g = 0; g < compiledGroups.size(); ++g) {
        const auto& group = compiledGroups[g];
        flat.observableNames.push_back(group.name);
        obsNameToIndex.emplace(group.name, static_cast<uint32_t>(g));
        for (const auto& entry : group.entries) {
            flat.obsSpecies.push_back(static_cast<uint32_t>(entry.first));
            flat.obsWeights.push_back(static_cast<float>(entry.second));
        }
        flat.obsOffsets.push_back(static_cast<uint32_t>(flat.obsSpecies.size()));
    }

    std::optional<compile::CompiledModel> compiledModelOpt;
    if (integrator.hasFunctionalRates()) {
        compiledModelOpt.emplace(model);
    }

    // Reaction arrays
    flat.rateConstants.resize(flat.numReactions, 0.0f);
    flat.reactionFlags.resize(flat.numReactions, 0u);
    flat.rxnVmOffsets.resize(flat.numReactions, 0u);
    flat.rxnVmLens.resize(flat.numReactions, 0u);
    flat.reactantOffsets.reserve(flat.numReactions + 1);
    flat.reactChangeOffsets.reserve(flat.numReactions + 1);
    flat.prodChangeOffsets.reserve(flat.numReactions + 1);

    flat.reactantOffsets.push_back(0);
    flat.reactChangeOffsets.push_back(0);
    flat.prodChangeOffsets.push_back(0);

    for (std::size_t r = 0; r < flat.numReactions; ++r) {
        const auto& rxn = compiledRxns[r];
        uint8_t flags = 0u;
        if (rxn.isAbsoluteFlux) {
            flags |= kBatchRxnFlagAbsoluteFlux;
        }

        if (rxn.isFunctional) {
            if (rxn.isTimeDependent) {
                throw std::runtime_error(
                    "Batch SSA: unsupported rate law (reaction " + std::to_string(r) +
                    " has time-dependent functional rate); failing closed.");
            }
            if (!rxn.compiledRateLaw.has_value()) {
                throw std::runtime_error(
                    "Batch SSA: unsupported rate law (reaction " + std::to_string(r) +
                    " lacks compiled functional rate expression); failing closed.");
            }
            if (rxn.compiledRateLaw->dependsOnTime() ||
                rxn.compiledRateLaw->dependsOnDelay() ||
                rxn.compiledRateLaw->dependencies().tableFunction) {
                throw std::runtime_error(
                    "Batch SSA: unsupported rate law (reaction " + std::to_string(r) +
                    " depends on time, delay, or table function); failing closed.");
            }
            if (!compiledModelOpt.has_value()) {
                compiledModelOpt.emplace(model);
            }
            const auto expanded =
                compiledModelOpt->expandFunctions(rxn.compiledRateLaw->resolvedExpression());
            const uint32_t vmOffset = static_cast<uint32_t>(flat.vmCode.size());
            BatchVmCompiler compiler{
                *compiledModelOpt, obsNameToIndex, rxn.reactantIndices,
                flat.numSpecies, r, flat.vmCode, vmOffset, 0, 0};
            compiler.compileExpr(expanded);
            if (compiler.curStack != 1) {
                throw std::runtime_error(
                    "Batch SSA: compiled functional rate VM left invalid stack depth in reaction " +
                    std::to_string(r) + "; failing closed.");
            }
            const uint32_t vmLen = static_cast<uint32_t>(flat.vmCode.size()) - vmOffset;
            flat.rxnVmOffsets[r] = vmOffset;
            flat.rxnVmLens[r] = vmLen;
            flat.rateConstants[r] = 0.0f;
            flags |= kBatchRxnFlagFunctional;
            flat.hasFunctional = true;
        } else {
            // Fail-closed rule: invalid rate constants (negative, NaN, inf)
            if (rxn.rateConstant < 0.0 || std::isnan(rxn.rateConstant) || std::isinf(rxn.rateConstant)) {
                throw std::runtime_error(
                    "Batch SSA: unsupported rate law (reaction " + std::to_string(r) +
                    " has non-positive or non-finite rate constant: " + std::to_string(rxn.rateConstant) +
                    "); failing closed.");
            }

            if (rxn.rateConstant > std::numeric_limits<float>::max()) {
                throw std::runtime_error(
                    "Batch SSA: rate constant for reaction " + std::to_string(r)
                    + " is outside float32 range");
            }
            const float storedRate = static_cast<float>(rxn.rateConstant);
            if (rxn.rateConstant > 0.0 && storedRate == 0.0f) {
                throw std::runtime_error(
                    "Batch SSA: rate constant for reaction " + std::to_string(r)
                    + " is outside float32 range");
            }
            flat.rateConstants[r] = storedRate;
        }
        flat.reactionFlags[r] = flags;

        // Reactants (with offset for identical reactants: A + A -> offset 0 for 1st, 1 for 2nd).
        // For absolute-flux reactions, only non-constant reactants gate stoichiometric
        // availability, matching OdeIntegrator::computePropensity().
        for (std::size_t i = 0; i < rxn.reactantIndices.size(); ++i) {
            const std::size_t sIdx = rxn.reactantIndices[i];
            if (sIdx >= flat.numSpecies) {
                throw std::runtime_error("Batch SSA: reactant index out of range");
            }
            const float currentOffset = static_cast<float>(std::count(
                rxn.reactantIndices.begin(),
                rxn.reactantIndices.begin() + static_cast<std::ptrdiff_t>(i),
                sIdx));
            if (!rxn.isAbsoluteFlux || !constantSpecies[sIdx]) {
                flat.reactantSpecies.push_back(static_cast<uint32_t>(sIdx));
                flat.reactantStoichOffsets.push_back(currentOffset);
            }
            if (!constantSpecies[sIdx]) {
                flat.reactChangeSpecies.push_back(static_cast<uint32_t>(sIdx));
            }
        }
        flat.reactantOffsets.push_back(static_cast<uint32_t>(flat.reactantSpecies.size()));
        flat.reactChangeOffsets.push_back(static_cast<uint32_t>(flat.reactChangeSpecies.size()));

        // Products
        for (std::size_t pIdx : rxn.productIndices) {
            if (pIdx >= flat.numSpecies) {
                throw std::runtime_error("Batch SSA: product index out of range");
            }
            if (!constantSpecies[pIdx]) {
                flat.prodChangeSpecies.push_back(static_cast<uint32_t>(pIdx));
            }
        }
        flat.prodChangeOffsets.push_back(static_cast<uint32_t>(flat.prodChangeSpecies.size()));
    }

    return flat;
}

// ============================================================================
// CPU Batch SSA Simulator (Single Worker & Multi-core)
// ============================================================================

CpuBatchSsaSimulator::CpuBatchSsaSimulator(const ast::Model& model, const GeneratedNetwork& network)
    : model_(model), network_(network) {
    // Native bng3_events are supported on CPU batch SSA: each worker owns an
    // isolated OdeIntegrator with its own seeded SimulationSession. GPU/JAX
    // flattening remains fail-closed via FlattenedReactionNetwork.
    requireNoExpressionDelaySemantics(model_, network_, "batch SSA");
}

BatchSsaMetrics CpuBatchSsaSimulator::simulateSingleWorker(const BatchSsaOptions& options) {
    auto tStartTotal = std::chrono::high_resolution_clock::now();

    auto tStartPrep = std::chrono::high_resolution_clock::now();
    OdeIntegrator integrator(model_, network_);
    const auto& compiledGroups = integrator.getCompiledGroups();
    std::size_t numObs = compiledGroups.size();
    std::size_t numPoints = options.nSteps + 1;
    std::size_t numSpecies = network_.species.size();

    auto tEndPrep = std::chrono::high_resolution_clock::now();
    double prepMs = std::chrono::duration<double, std::milli>(tEndPrep - tStartPrep).count();

    BatchSsaMetrics metrics;
    metrics.batchSize = options.batchSize;
    metrics.modelPrepTimeMs = prepMs;
    metrics.observableNames.reserve(numObs);
    for (const auto& g : compiledGroups) {
        metrics.observableNames.push_back(g.name);
    }
    metrics.trajectoryEventCounts.resize(options.batchSize, 0);
    metrics.finalSpecies.resize(options.batchSize * numSpecies, 0);
    metrics.finalObservables.resize(options.batchSize * numObs, 0.0f);

    std::vector<std::vector<RunningMoments>> moments(
        numPoints, std::vector<RunningMoments>(numObs));

    auto tStartSim = std::chrono::high_resolution_clock::now();

    OdeOptions odeOpts;
    odeOpts.tStart = options.tStart;
    odeOpts.tEnd = options.tEnd;
    odeOpts.nSteps = options.nSteps;
    odeOpts.method = "ssa";
    odeOpts.maxSimSteps = options.maxSimSteps;
    odeOpts.isolatedTrajectory = true;

    uint64_t totalEvents = 0;

    for (std::size_t b = 0; b < options.batchSize; ++b) {
        // Decorrelated per-trajectory seed, shared with integrateBatchSSA's CPU
        // pool and the GPU backends. `baseSeed + b` aliased: batch runs whose
        // base seeds differ by delta shared batchSize - delta trajectories.
        odeOpts.seed = batchTrajectoryEngineSeed(options.baseSeed, b);
        OdeResult res = integrator.integrate(odeOpts);

        if (b == 0) {
            metrics.timePoints.resize(res.timePoints.size());
            for (std::size_t i = 0; i < res.timePoints.size(); ++i) {
                metrics.timePoints[i] = static_cast<float>(res.timePoints[i]);
            }
        }

        totalEvents += res.eventCount;
        metrics.trajectoryEventCounts[b] = static_cast<uint32_t>(res.eventCount);

        // Record final species
        const bool hasNativeEvents = model_.getEventFormatVersion().has_value();
        if (!res.concentrations.empty()) {
            const auto& finalConc = res.concentrations.back();
            for (std::size_t s = 0; s < numSpecies && s < finalConc.size(); ++s) {
                metrics.finalSpecies[b * numSpecies + s] =
                    recordFinalSpeciesPopulation(finalConc[s], hasNativeEvents);
            }
        }

        // Record observables
        for (std::size_t step = 0; step < numPoints && step < res.observables.size(); ++step) {
            for (std::size_t g = 0; g < numObs && g < res.observables[step].size(); ++g) {
                double val = res.observables[step][g];
                moments[step][g].add(val);
                if (step == numPoints - 1) {
                    metrics.finalObservables[b * numObs + g] = static_cast<float>(val);
                }
            }
        }
    }

    auto tEndSim = std::chrono::high_resolution_clock::now();
    double simMs = std::chrono::duration<double, std::milli>(tEndSim - tStartSim).count();
    auto tEndTotal = std::chrono::high_resolution_clock::now();
    double totalMs = std::chrono::duration<double, std::milli>(tEndTotal - tStartTotal).count();

    metrics.simulationTimeMs = simMs;
    metrics.totalWallTimeMs = totalMs;
    metrics.totalEvents = totalEvents;

    metrics.trajectoriesPerSecSim = (options.batchSize / (simMs / 1000.0));
    metrics.trajectoriesPerSecTotal = (options.batchSize / (totalMs / 1000.0));
    metrics.eventsPerSecSim = (totalEvents / (simMs / 1000.0));
    metrics.eventsPerSecTotal = (totalEvents / (totalMs / 1000.0));
    metrics.memoryUsageBytes = sizeof(OdeIntegrator) + options.batchSize * (numSpecies * sizeof(int32_t) + numObs * sizeof(float));

    // Compute means and standard deviations
    metrics.observableMeans.resize(numPoints, std::vector<float>(numObs, 0.0f));
    metrics.observableStdDevs.resize(numPoints, std::vector<float>(numObs, 0.0f));
    for (std::size_t step = 0; step < numPoints; ++step) {
        for (std::size_t g = 0; g < numObs; ++g) {
            metrics.observableMeans[step][g] = static_cast<float>(moments[step][g].average());
            metrics.observableStdDevs[step][g] = static_cast<float>(moments[step][g].standardDeviation());
        }
    }
    detail::fillDoubleFields(metrics);
    return metrics;
}

BatchSsaMetrics CpuBatchSsaSimulator::simulateMultiCore(const BatchSsaOptions& options, unsigned int numThreads) {
    auto tStartTotal = std::chrono::high_resolution_clock::now();

    auto tStartPrep = std::chrono::high_resolution_clock::now();
    if (numThreads == 0) {
        numThreads = std::thread::hardware_concurrency();
    }
    if (numThreads == 0) numThreads = 1;

    // One compiled model for the whole pool. Constructing an OdeIntegrator
    // recompiles every reaction and observable from the AST, so the previous
    // one-per-worker layout paid numThreads+1 model compiles per batch (15+1
    // here) and held numThreads copies of the compiled network alive at once.
    //
    // Sharing is safe because the SSA path is re-entrant on this class:
    // integrate() dispatches to integrateSSA(), which reads only the compiled
    // reaction/group tables and writes exclusively to its own locals and the
    // OdeResult it returns. Every helper it reaches (outputTimes, parseStopIf,
    // updateGroups, stopConditionMet, computePropensity) is const and takes
    // its output through an out-parameter.
    //
    // The mutable members of OdeIntegrator are NOT safe to share, and the SSA
    // path reaches none of them: groupValues_ and functionalRateCoefficients_
    // are scratch for derivs(), which only the single-threaded ODE/CVODE path
    // calls, and cvodePhysicalState_/cvodePhysicalDerivatives_ belong to
    // cvodeDerivs(). A state-dependent rate law used to break this rule:
    // evaluateFunctionalRateCoefficients() filled groupValues_ from the
    // current state, so two workers sharing the integrator could resolve a
    // rate expression against another trajectory's observable values. The
    // observable scratch is now an explicit argument, and the SSA path passes
    // its own per-thread buffer (SsaScratch::groupValues), so a fixed seed
    // reproduces the same ensemble on every worker count.
    OdeIntegrator integrator(model_, network_);
    const auto& compiledGroups = integrator.getCompiledGroups();
    std::size_t numObs = compiledGroups.size();
    std::size_t numPoints = options.nSteps + 1;
    std::size_t numSpecies = network_.species.size();

    auto tEndPrep = std::chrono::high_resolution_clock::now();
    double prepMs = std::chrono::duration<double, std::milli>(tEndPrep - tStartPrep).count();

    BatchSsaMetrics metrics;
    metrics.batchSize = options.batchSize;
    metrics.modelPrepTimeMs = prepMs;
    metrics.observableNames.reserve(numObs);
    for (const auto& g : compiledGroups) {
        metrics.observableNames.push_back(g.name);
    }
    metrics.trajectoryEventCounts.resize(options.batchSize, 0);
    metrics.finalSpecies.resize(options.batchSize * numSpecies, 0);
    metrics.finalObservables.resize(options.batchSize * numObs, 0.0f);

    struct WorkerResult {
        uint64_t workerEvents = 0;
        std::vector<std::vector<RunningMoments>> moments;
        std::vector<float> timePoints;
    };

    auto tStartSim = std::chrono::high_resolution_clock::now();

    std::size_t batchSize = options.batchSize;
    std::size_t chunkSize = (batchSize + numThreads - 1) / numThreads;

    std::vector<std::future<WorkerResult>> futures;
    futures.reserve(numThreads);

    for (unsigned int t = 0; t < numThreads; ++t) {
        std::size_t startIdx = t * chunkSize;
        std::size_t endIdx = std::min(startIdx + chunkSize, batchSize);
        if (startIdx >= endIdx) continue;

        futures.push_back(std::async(std::launch::async, [this, &options, startIdx, endIdx, numPoints, numObs, numSpecies, &metrics]() {
            WorkerResult wRes;
            wRes.moments.resize(numPoints, std::vector<RunningMoments>(numObs));
            OdeIntegrator integrator(model_, network_);

            OdeOptions odeOpts;
            odeOpts.tStart = options.tStart;
            odeOpts.tEnd = options.tEnd;
            odeOpts.nSteps = options.nSteps;
            odeOpts.method = "ssa";
            odeOpts.maxSimSteps = options.maxSimSteps;
            odeOpts.isolatedTrajectory = true;

            for (std::size_t b = startIdx; b < endIdx; ++b) {
                // Same derivation as the single-worker loop above.
                odeOpts.seed = batchTrajectoryEngineSeed(options.baseSeed, b);
                OdeResult res = integrator.integrate(odeOpts);

                if (wRes.timePoints.empty() && !res.timePoints.empty()) {
                    wRes.timePoints.resize(res.timePoints.size());
                    for (std::size_t i = 0; i < res.timePoints.size(); ++i) {
                        wRes.timePoints[i] = static_cast<float>(res.timePoints[i]);
                    }
                }

                wRes.workerEvents += res.eventCount;
                metrics.trajectoryEventCounts[b] = static_cast<uint32_t>(res.eventCount);

                const bool hasNativeEvents = model_.getEventFormatVersion().has_value();
                if (!res.concentrations.empty()) {
                    const auto& finalConc = res.concentrations.back();
                    for (std::size_t s = 0; s < numSpecies && s < finalConc.size(); ++s) {
                        metrics.finalSpecies[b * numSpecies + s] =
                            recordFinalSpeciesPopulation(finalConc[s], hasNativeEvents);
                    }
                }

                for (std::size_t step = 0; step < numPoints && step < res.observables.size(); ++step) {
                    for (std::size_t g = 0; g < numObs && g < res.observables[step].size(); ++g) {
                        double val = res.observables[step][g];
                        wRes.moments[step][g].add(val);
                        if (step == numPoints - 1) {
                            metrics.finalObservables[b * numObs + g] = static_cast<float>(val);
                        }
                    }
                }
            }
            return wRes;
        }));
    }

    uint64_t totalEvents = 0;
    std::vector<std::vector<RunningMoments>> moments(
        numPoints, std::vector<RunningMoments>(numObs));

    for (auto& f : futures) {
        WorkerResult wRes = f.get();
        totalEvents += wRes.workerEvents;
        if (metrics.timePoints.empty() && !wRes.timePoints.empty()) {
            metrics.timePoints = std::move(wRes.timePoints);
        }
        for (std::size_t step = 0; step < numPoints; ++step) {
            for (std::size_t g = 0; g < numObs; ++g) {
                moments[step][g].merge(wRes.moments[step][g]);
            }
        }
    }

    auto tEndSim = std::chrono::high_resolution_clock::now();
    double simMs = std::chrono::duration<double, std::milli>(tEndSim - tStartSim).count();
    auto tEndTotal = std::chrono::high_resolution_clock::now();
    double totalMs = std::chrono::duration<double, std::milli>(tEndTotal - tStartTotal).count();

    metrics.simulationTimeMs = simMs;
    metrics.totalWallTimeMs = totalMs;
    metrics.totalEvents = totalEvents;

    metrics.trajectoriesPerSecSim = (options.batchSize / (simMs / 1000.0));
    metrics.trajectoriesPerSecTotal = (options.batchSize / (totalMs / 1000.0));
    metrics.eventsPerSecSim = (totalEvents / (simMs / 1000.0));
    metrics.eventsPerSecTotal = (totalEvents / (totalMs / 1000.0));
    // One compiled model backs the whole pool, not one per worker.
    metrics.memoryUsageBytes = sizeof(OdeIntegrator) +
                              options.batchSize * (numSpecies * sizeof(int32_t) + numObs * sizeof(float));

    metrics.observableMeans.resize(numPoints, std::vector<float>(numObs, 0.0f));
    metrics.observableStdDevs.resize(numPoints, std::vector<float>(numObs, 0.0f));
    for (std::size_t step = 0; step < numPoints; ++step) {
        for (std::size_t g = 0; g < numObs; ++g) {
            metrics.observableMeans[step][g] = static_cast<float>(moments[step][g].average());
            metrics.observableStdDevs[step][g] = static_cast<float>(moments[step][g].standardDeviation());
        }
    }
    detail::fillDoubleFields(metrics);
    return metrics;
}

} // namespace bng::engine
