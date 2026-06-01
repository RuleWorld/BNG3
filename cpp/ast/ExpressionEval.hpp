/// ExpressionEval.hpp
///
/// WO-3 — One expression / rate-law evaluator for the whole platform.
///
/// Today there are three: bng::ast::Expression (engine ODE RHS + SSA propensity),
/// NFsim's exprtk path (NFfunction/, network-free local + global functions), and
/// the Perl Expression.pm (oracle only). This facade makes bng::ast::Expression
/// the single runtime evaluator and gives NFsim a typed entry that does not link
/// exprtk.
///
/// The facade is intentionally thin: it owns no new math. It binds the existing
/// Expression evaluator to a variable context and exposes two call shapes —
/// global (time + observables + parameters) and complex-scoped (the additional
/// per-complex observable values NFsim local functions need).
///
/// Gate: test_parity_expressions (function-driven RHS to 1e-9 vs the Perl oracle)
/// and the NFsim parity tests. exprtk is removed from the build (WO-3b) only
/// after NFsim functions evaluate through here and those gates are green.

#pragma once

#include <functional>
#include <string>
#include <unordered_map>

namespace bng::ast { class Expression; }

namespace bng::eval {

/// Variable bindings available to an expression at evaluation time.
/// `lookup` resolves any symbol (parameter, observable, or — in complex scope —
/// a local observable) to a double. The engine and NFsim each provide a lookup
/// closure backed by their own state; the *math* is identical because both go
/// through the same Expression tree walk.
struct Context {
    double time = 0.0;
    std::function<double(const std::string&)> lookup;  // symbol -> value
};

/// Evaluate a parsed Expression in a context. Single implementation; delegates
/// to bng::ast::Expression's evaluator with `ctx.lookup` as the symbol resolver.
double evaluate(const bng::ast::Expression& expr, const Context& ctx);

/// Convenience: evaluate against a flat symbol table (parameters/observables
/// already reduced to numbers). Used by the ODE RHS and SSA propensity, where
/// the full observable vector is known up front.
double evaluate(const bng::ast::Expression& expr,
                double time,
                const std::unordered_map<std::string, double>& symbols);

// --------------------------------------------------------------------------- //
// NFsim shim (WO-3 integration point)
// --------------------------------------------------------------------------- //
// NFsim's NFfunction layer currently compiles function strings with exprtk and
// evaluates them per reaction firing. Replace that with calls to evaluate():
//
//   1. At System build time, parse each function body once into a
//      bng::ast::Expression (functions arrive from ast::Model in WO-2, so the
//      parsed tree can be carried directly — no string round-trip).
//   2. At evaluation time, build a Context whose `lookup` returns the current
//      value of each referenced observable (global) or local observable
//      (complex-scoped), then call bng::eval::evaluate(expr, ctx).
//
// The signature NFsim should call for a complex-scoped local function:
//
//   double evalLocalFunction(const bng::ast::Expression& fn,
//                            double time,
//                            const std::function<double(const std::string&)>& localLookup);
//
// which is just evaluate(fn, Context{time, localLookup}). Keeping it one line
// makes the equivalence to the global path obvious and is what lets exprtk go.

inline double evalLocalFunction(const bng::ast::Expression& fn,
                                double time,
                                const std::function<double(const std::string&)>& localLookup) {
    return evaluate(fn, Context{time, localLookup});
}

} // namespace bng::eval
