// nfsim_funcparser.h — mu::Parser interface backed by the SHARED BNG3 evaluator
//
// WO-3: one expression engine for the whole platform.
//
// HISTORY
// -------
// BNG3 used to evaluate math two different ways. `bng::ast::Expression` served
// the ODE RHS, the SSA/PLA/PSA propensities, network generation, observables,
// and user functions. NFsim did its own thing: this header was an ExprTk-backed
// drop-in for muParser, so every NFsim global function, local function,
// composite function, and functional rate law was parsed from a *string* by
// ExprTk and evaluated by ExprTk.
//
// Two engines for the same language is a correctness problem, not just
// duplication. They agreed often enough that the places they disagreed went
// unnoticed:
//
//   - `rint` was `std::rint` (round-half-to-even) on the shared side and
//     `std::round` (round-half-away-from-zero) here, and BNG2 defines it as
//     `floor(x + 0.5)` (round-half-up). All three differed.
//   - `sign` and `log` were accepted by NFsim but unimplemented in the shared
//     evaluator, so they worked network-free and broke under ODE.
//   - The direct-path builtin gate matched case-insensitively while ExprTk was
//     compiled case-sensitively.
//
// Those were fixed by reconciling the lists. This file removes the cause: NFsim
// now parses with the same parser and evaluates with the same tree walker as
// everything else, so the classes of divergence above cannot recur.
//
// WHAT THIS IS NOW
// ----------------
// The `mu::Parser` *interface* is retained deliberately. NFsim holds
// `mu::Parser*` in `GlobalFunction`, `LocalFunction`, `CompositeFunction`, and
// `Observable::addReferenceToMyself`, and threads it through reaction rate
// evaluation. Reworking all of that is a separate, riskier change with no
// semantic benefit. The surface used by NFsim is small and stable:
//
//     exception_type / GetMsg()
//     DefineVar(name, double*)      bind a live pointer
//     DefineConst(name, value)      store/refresh a value
//     SetExpr(string)               parse
//     Eval()                        evaluate
//     GetExpr()                     original text
//
// (`GetVar()` appears only in commented-out code in function.cpp.)
//
// WHAT GOT DELETED, AND WHY IT WAS SAFE
// -------------------------------------
//   - The ExprTk dependency, and `NFSIM_USE_EXPRTK`. This completes WO-3b.
//   - `remap_name` / `remap_expression` / `trackUnderscoreName`. These existed
//     solely because ExprTk rejects identifiers beginning with `_`, so BNG's
//     `_PI`, `_e`, `_Na` and the injected `__TFUN_VAL__` had to be rewritten to
//     `u_PI` and friends on the way in and the expression text rescanned. The
//     BNGL lexer accepts them directly -- `STRING: (LETTER | '_') (LETTER |
//     DIGIT | '_')*` in BNGLexer.g4 -- so the entire remapping layer is
//     unnecessary. Deleting it also removes a latent bug: the rescan rewrote
//     any `_`-leading token anywhere in the string, including inside contexts
//     it had no business touching.
//   - `normalize_legacy_logical_operators`, which rewrote `&&` to ` and ` and
//     `||` to ` or ` for ExprTk. `bng::ast::Expression` implements `&&`, `||`,
//     `^^`, `!`, `~`, `%`, `**`, and the full comparison set natively, and the
//     BNGL grammar tokenizes them, so no rewriting is needed.
//   - `LnFunction`, `RintFunction`, `SignFunction`: adapters for names ExprTk
//     lacked. The shared evaluator implements `ln`, `rint`, and `sign` itself.
//   - `IfFunction`: was already unreachable (ExprTk's `if` is a grammar
//     keyword) and had the wrong truthiness (`cond > 0.5` rather than
//     `cond != 0`).
//
// BEHAVIORAL NOTES FOR REVIEW
// ---------------------------
//   - Symbol lookup now happens at *evaluation* time against a live map
//     instead of being bound into a compiled ExprTk object. `DefineVar` and
//     `DefineConst` after `SetExpr` therefore no longer force a recompile,
//     which is what `__TFUN_VAL__` injection depended on and what
//     `Observable::addReferenceToMyself` exercises on every observable update.
//   - This is a tree walk rather than ExprTk's compiled form, so per-evaluation
//     cost is expected to rise. Convergence before performance, per AGENTS.md;
//     if functional-rate models regress, the fix is to memoize in
//     `bng::ast::Expression`, which benefits every backend, not to reintroduce
//     a second engine.
//   - Unknown symbols throw `exception_type`, matching muParser/ExprTk, so
//     NFsim's existing catch sites are unchanged.

#pragma once

#include "ast/Expression.hpp"
#include "ast/ExpressionEval.hpp"

#include <functional>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>

// Declared in cpp/parser/BNGAstVisitor.hpp. Re-declared here rather than
// included because that header pulls in the generated ANTLR visitor headers,
// and this file is included broadly across NFsim.
namespace bng::parser {
bng::ast::Expression parseExpression(const std::string& exprText);
}

namespace mu {

class Parser {
public:
    struct exception_type : public std::runtime_error {
        explicit exception_type(const std::string& msg) : std::runtime_error(msg) {}
        std::string GetMsg() const { return what(); }
    };

    Parser() {
        // NFsim/BNG convention. Registered as constants so they resolve
        // through the same symbol path as observables and parameters; the
        // shared evaluator also understands the `_pi()` and `_e()` call forms.
        DefineConst("_PI", 3.14159265358979323846);
        DefineConst("_e", 2.71828182845904523536);
        DefineConst("_Na", 6.02214076e23);

        // Additional constants supported by bngsim.
        DefineConst("_pi", 3.14159265358979323846);
        DefineConst("_NA", 6.02214076e23);
        DefineConst("_kB", 1.380649e-23);
        DefineConst("_R", 8.314462618153241);
        DefineConst("_h", 6.62607015e-34);
        DefineConst("_F", 96485.33212331002);
    }

    ~Parser() = default;

    // Non-copyable: variables_ holds borrowed pointers into caller state.
    Parser(const Parser&) = delete;
    Parser& operator=(const Parser&) = delete;

    /// Bind a name to a caller-owned double. Read at evaluation time, so the
    /// caller may update the pointee freely without reparsing.
    void DefineVar(const std::string& name, double* ptr) {
        if (ptr == nullptr) {
            throw exception_type("DefineVar('" + name + "') was given a null pointer");
        }
        variables_[name] = ptr;
    }

    /// Store or refresh a value. Safe after SetExpr; no reparse occurs.
    void DefineConst(const std::string& name, double value) {
        constants_[name] = value;
    }

    /// Parse the expression with the shared BNGL expression parser.
    void SetExpr(const std::string& expr) {
        originalExpr_ = expr;
        try {
            expression_ = bng::parser::parseExpression(expr);
        } catch (const std::exception& error) {
            expression_.reset();
            throw exception_type("failed to parse expression '" + expr + "': " +
                                 error.what());
        }
    }

    double Eval() {
        if (!expression_.has_value()) {
            throw exception_type("Expression not compiled (call SetExpr first)");
        }
        const auto resolve = [this](const std::string& name) -> double {
            const auto variable = variables_.find(name);
            if (variable != variables_.end()) return *variable->second;
            const auto constant = constants_.find(name);
            if (constant != constants_.end()) return constant->second;
            throw exception_type("unknown symbol '" + name + "' in expression '" +
                                 originalExpr_ + "'");
        };
        try {
            // Through the shared facade, so NFsim and the engine reach the
            // evaluator by the same route rather than each calling
            // Expression::evaluate with its own conventions.
            return bng::eval::evaluate(
                *expression_,
                bng::eval::Context{currentTime(),
                                   std::function<double(const std::string&)>(resolve)});
        } catch (const exception_type&) {
            throw;
        } catch (const std::exception& error) {
            // Domain errors, arity errors, and unsupported-construct errors
            // from the shared evaluator become the exception type NFsim's
            // existing call sites already catch.
            throw exception_type(std::string("error evaluating '") + originalExpr_ +
                                 "': " + error.what());
        }
    }

    /// The expression as the caller supplied it.
    std::string GetExpr() const { return originalExpr_; }

private:
    /// Value supplied to the shared evaluator for `time()` / `t()`.
    ///
    /// NFsim exposes simulation time as an ordinary symbol (the XML loader
    /// records a "Time" varRef; direct construction uses setCounterFromTime),
    /// so read it from the symbol table to keep the symbol spelling and the
    /// call form in agreement. Absent means zero, matching the shared
    /// evaluator's default.
    double currentTime() const {
        const auto variable = variables_.find("time");
        if (variable != variables_.end()) return *variable->second;
        const auto constant = constants_.find("time");
        if (constant != constants_.end()) return constant->second;
        return 0.0;
    }

    std::unordered_map<std::string, double*> variables_;
    std::unordered_map<std::string, double> constants_;
    std::optional<bng::ast::Expression> expression_;
    std::string originalExpr_;
};

} // namespace mu
