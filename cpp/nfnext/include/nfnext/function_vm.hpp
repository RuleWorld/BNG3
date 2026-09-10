#pragma once

#include "nfnext/types.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace nfnext {

class FunctionCompileError : public std::runtime_error {
public:
    explicit FunctionCompileError(const std::string& message) : std::runtime_error(message) {}
};
class FunctionEvaluationError : public std::runtime_error {
public:
    explicit FunctionEvaluationError(const std::string& message) : std::runtime_error(message) {}
};
class InvalidPropensity : public std::runtime_error {
public:
    explicit InvalidPropensity(const std::string& message) : std::runtime_error(message) {}
};

enum class NonFinitePolicy : std::uint8_t { Reject = 0, Allow = 1 };

struct FunctionCompilerOptions {
    NonFinitePolicy nonfinite_policy{NonFinitePolicy::Reject};
};

class FunctionEnvironment {
public:
    struct Binding {
        double value{0.0};
        std::uint32_t id{0};
    };

    static FunctionEnvironment parameter(const std::string& name, double value,
                                         ParameterId id = 0) {
        FunctionEnvironment environment;
        environment.addParameter(name, value, id);
        return environment;
    }

    void addParameter(const std::string& name, double value, ParameterId id) {
        parameters_[name] = Binding{value, id};
    }
    void addObservable(const std::string& name, double value, ObservableId id) {
        observables_[name] = Binding{value, id};
    }
    void set(const std::string& name, double value) {
        auto parameter = parameters_.find(name);
        if (parameter != parameters_.end()) { parameter->second.value = value; return; }
        auto observable = observables_.find(name);
        if (observable != observables_.end()) { observable->second.value = value; return; }
        throw FunctionEvaluationError("unknown function symbol: " + name);
    }

    bool has(const std::string& name) const noexcept {
        return parameters_.find(name) != parameters_.end() ||
               observables_.find(name) != observables_.end();
    }
    double value(const std::string& name) const {
        const auto parameter = parameters_.find(name);
        if (parameter != parameters_.end()) return parameter->second.value;
        const auto observable = observables_.find(name);
        if (observable != observables_.end()) return observable->second.value;
        throw FunctionEvaluationError("unknown function symbol: " + name);
    }
    const Binding* parameterBinding(const std::string& name) const noexcept {
        const auto it = parameters_.find(name);
        return it == parameters_.end() ? nullptr : &it->second;
    }
    const Binding* observableBinding(const std::string& name) const noexcept {
        const auto it = observables_.find(name);
        return it == observables_.end() ? nullptr : &it->second;
    }

private:
    std::unordered_map<std::string, Binding> parameters_;
    std::unordered_map<std::string, Binding> observables_;
};

namespace function_vm_detail {

enum class Op : std::uint8_t {
    Constant, Symbol, Add, Subtract, Multiply, Divide, Power, Negate, Function
};

struct Instruction {
    Op op{Op::Constant};
    double value{0.0};
    std::uint8_t function{0};
    std::uint8_t argc{0};
    std::string symbol;
};

struct Bytecode {
    std::vector<Instruction> code;
    std::size_t max_stack{0};
};

inline bool builtin(const std::string& name, std::uint8_t& id) {
    static const char* names[] = {"exp", "log", "sqrt", "pow", "sin", "cos", "tan", "abs", "min", "max"};
    for (std::uint8_t i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
        if (name == names[i]) { id = i; return true; }
    }
    return false;
}

class Parser {
public:
    Parser(const std::string& source, const FunctionEnvironment& environment,
           Bytecode& bytecode, std::vector<ParameterId>& parameter_dependencies,
           std::vector<ObservableId>& observable_dependencies)
        : source_(source), environment_(environment), bytecode_(bytecode),
          parameter_dependencies_(parameter_dependencies),
          observable_dependencies_(observable_dependencies) {}

    void parse() {
        expression();
        skipSpace();
        if (position_ != source_.size()) fail("unexpected trailing input");
        bytecode_.max_stack = std::max(bytecode_.max_stack, stack_depth_);
    }

private:
    void skipSpace() {
        while (position_ < source_.size() && std::isspace(static_cast<unsigned char>(source_[position_]))) ++position_;
    }
    bool consume(char value) {
        skipSpace();
        if (position_ < source_.size() && source_[position_] == value) { ++position_; return true; }
        return false;
    }
    void require(char value) {
        if (!consume(value)) fail(std::string("expected '") + value + "'");
    }
    [[noreturn]] void fail(const std::string& message) const {
        throw FunctionCompileError(message + " at offset " + std::to_string(position_));
    }

    void expression() { addSub(); }
    void addSub() {
        multiply();
        for (;;) {
            if (consume('+')) { multiply(); emitBinary(function_vm_detail::Op::Add); }
            else if (consume('-')) { multiply(); emitBinary(function_vm_detail::Op::Subtract); }
            else return;
        }
    }
    void multiply() {
        unary();
        for (;;) {
            if (consume('*')) { unary(); emitBinary(function_vm_detail::Op::Multiply); }
            else if (consume('/')) { unary(); emitBinary(function_vm_detail::Op::Divide); }
            else return;
        }
    }
    void unary() {
        if (consume('+')) { unary(); return; }
        if (consume('-')) { unary(); emitUnary(function_vm_detail::Op::Negate); return; }
        power();
    }
    void power() {
        primary();
        if (consume('^')) { unary(); emitBinary(function_vm_detail::Op::Power); }
    }
    void primary() {
        skipSpace();
        if (consume('(')) {
            expression();
            require(')');
            return;
        }
        if (position_ >= source_.size()) fail("expected expression");
        const char first = source_[position_];
        if (std::isdigit(static_cast<unsigned char>(first)) || first == '.') {
            const char* begin = source_.c_str() + position_;
            char* end = nullptr;
            const double value = std::strtod(begin, &end);
            if (end == begin) fail("invalid number");
            position_ += static_cast<std::size_t>(end - begin);
            bytecode_.code.push_back({Op::Constant, value});
            pushStack();
            return;
        }
        if (!std::isalpha(static_cast<unsigned char>(first)) && first != '_')
            fail("expected number, symbol, or parenthesized expression");
        const auto begin = position_++;
        while (position_ < source_.size() &&
               (std::isalnum(static_cast<unsigned char>(source_[position_])) || source_[position_] == '_')) ++position_;
        const std::string name = source_.substr(begin, position_ - begin);
        if (consume('(')) {
            std::uint8_t function_id = 0;
            if (!builtin(name, function_id)) fail("unknown function: " + name);
            std::uint8_t argc = 0;
            skipSpace();
            if (!consume(')')) {
                for (;;) {
                    expression();
                    if (argc == std::numeric_limits<std::uint8_t>::max()) fail("too many function arguments");
                    ++argc;
                    if (consume(')')) break;
                    require(',');
                }
            }
            const bool valid_arity = (function_id <= 2 && argc == 1) ||
                                     (function_id == 3 && argc == 2) ||
                                     (function_id >= 4 && function_id <= 7 && argc == 1) ||
                                     (function_id >= 8 && argc == 2);
            if (!valid_arity) fail("wrong number of function arguments: " + name);
            bytecode_.code.push_back({Op::Function, 0.0, function_id, argc});
            stack_depth_ -= argc;
            pushStack();
            return;
        }
        if (!environment_.has(name)) throw FunctionCompileError("unknown function symbol: " + name);
        bytecode_.code.push_back({Op::Symbol, 0.0, 0, 0, name});
        const auto* parameter = environment_.parameterBinding(name);
        if (parameter != nullptr) {
            if (std::find(parameter_dependencies_.begin(), parameter_dependencies_.end(), parameter->id) == parameter_dependencies_.end())
                parameter_dependencies_.push_back(parameter->id);
        } else {
            const auto* observable = environment_.observableBinding(name);
            if (observable != nullptr && std::find(observable_dependencies_.begin(), observable_dependencies_.end(), observable->id) == observable_dependencies_.end())
                observable_dependencies_.push_back(observable->id);
        }
        pushStack();
    }
    void pushStack() {
        ++stack_depth_;
        bytecode_.max_stack = std::max(bytecode_.max_stack, stack_depth_);
    }
    void emitUnary(Op op) { bytecode_.code.push_back({op}); }
    void emitBinary(Op op) { if (stack_depth_ < 2) fail("operator stack underflow"); --stack_depth_; bytecode_.code.push_back({op}); }

    const std::string& source_;
    const FunctionEnvironment& environment_;
    Bytecode& bytecode_;
    std::vector<ParameterId>& parameter_dependencies_;
    std::vector<ObservableId>& observable_dependencies_;
    std::size_t position_{0};
    std::size_t stack_depth_{0};
};

inline double evaluateBuiltin(std::uint8_t id, const double* args) {
    switch (id) {
        case 0: return std::exp(args[0]);
        case 1: return std::log(args[0]);
        case 2: return std::sqrt(args[0]);
        case 3: return std::pow(args[0], args[1]);
        case 4: return std::sin(args[0]);
        case 5: return std::cos(args[0]);
        case 6: return std::tan(args[0]);
        case 7: return std::abs(args[0]);
        case 8: return std::min(args[0], args[1]);
        case 9: return std::max(args[0], args[1]);
        default: throw FunctionEvaluationError("unknown compiled function");
    }
}

} // namespace function_vm_detail

class CompiledFunction {
public:
    double evaluate(const FunctionEnvironment& environment) const {
        std::array<double, 256> stack{};
        std::size_t top = 0;
        for (const auto& instruction : code_->code) {
            using Op = function_vm_detail::Op;
            switch (instruction.op) {
                case Op::Constant: stack.at(top++) = instruction.value; break;
                case Op::Symbol: stack.at(top++) = environment.value(instruction.symbol); break;
                case Op::Negate: if (top < 1) throw FunctionEvaluationError("stack underflow"); stack[top - 1] = -stack[top - 1]; break;
                case Op::Add: binary(stack, top, [](double a, double b) { return a + b; }); break;
                case Op::Subtract: binary(stack, top, [](double a, double b) { return a - b; }); break;
                case Op::Multiply: binary(stack, top, [](double a, double b) { return a * b; }); break;
                case Op::Divide:
                    binary(stack, top, [this](double a, double b) {
                        if (b == 0.0 && options_.nonfinite_policy == NonFinitePolicy::Reject)
                            throw FunctionEvaluationError("division by zero");
                        return a / b;
                    });
                    break;
                case Op::Power: binary(stack, top, [](double a, double b) { return std::pow(a, b); }); break;
                case Op::Function: {
                    if (top < instruction.argc) throw FunctionEvaluationError("function stack underflow");
                    const auto first = top - instruction.argc;
                    const auto value = function_vm_detail::evaluateBuiltin(instruction.function, stack.data() + first);
                    top = first;
                    stack[top++] = value;
                    break;
                }
            }
            if (options_.nonfinite_policy == NonFinitePolicy::Reject && top != 0 && !std::isfinite(stack[top - 1]))
                throw FunctionEvaluationError("non-finite function result");
        }
        if (top != 1) throw FunctionEvaluationError("function did not produce one value");
        return stack[0];
    }

    const std::vector<ParameterId>& parameterDependencies() const noexcept { return parameter_dependencies_; }
    const std::vector<ObservableId>& observableDependencies() const noexcept { return observable_dependencies_; }
    const std::vector<std::string>& dependencies() const noexcept { return dependencies_; }
    bool isImmutable() const noexcept { return true; }
    std::shared_ptr<const function_vm_detail::Bytecode> sharedCode() const noexcept { return code_; }

private:
    explicit CompiledFunction(std::shared_ptr<const function_vm_detail::Bytecode> code,
                              FunctionCompilerOptions options,
                              std::vector<ParameterId> parameter_dependencies,
                              std::vector<ObservableId> observable_dependencies)
        : code_(std::move(code)), options_(options),
          parameter_dependencies_(std::move(parameter_dependencies)),
          observable_dependencies_(std::move(observable_dependencies)) {}

    template <class Fn>
    static void binary(std::array<double, 256>& stack, std::size_t& top, Fn&& fn) {
        if (top < 2) throw FunctionEvaluationError("operator stack underflow");
        const auto right = stack[--top];
        stack[top - 1] = fn(stack[top - 1], right);
    }

    std::shared_ptr<const function_vm_detail::Bytecode> code_;
    FunctionCompilerOptions options_;
    std::vector<ParameterId> parameter_dependencies_;
    std::vector<ObservableId> observable_dependencies_;
    std::vector<std::string> dependencies_;
    friend class FunctionCompiler;
};

class FunctionCompiler {
public:
    explicit FunctionCompiler(FunctionCompilerOptions options = {}) : options_(options) {}

    CompiledFunction compile(const std::string& source, const FunctionEnvironment& environment) const {
        auto code = std::make_shared<function_vm_detail::Bytecode>();
        std::vector<ParameterId> parameters;
        std::vector<ObservableId> observables;
        function_vm_detail::Parser parser(source, environment, *code, parameters, observables);
        parser.parse();
        return CompiledFunction(std::move(code), options_, std::move(parameters), std::move(observables));
    }

private:
    FunctionCompilerOptions options_;
};

inline void validatePropensity(double value) {
    if (!std::isfinite(value) || value < 0.0) throw InvalidPropensity("invalid propensity");
}

inline std::size_t allocationCounter() noexcept {
    return 0;
}

} // namespace nfnext
