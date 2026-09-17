/// ExpressionEval.hpp
///
/// WO-3 — the one expression / rate-law evaluator for the whole platform.
///
/// STATUS: this is now the single route. There used to be two engines —
/// `bng::ast::Expression` for the ODE RHS, SSA/PLA/PSA propensities, network
/// generation, observables, and user functions, and an ExprTk path for NFsim's
/// global/local/composite functions and functional rate laws. The Perl
/// `Expression.pm` remains an oracle only.
///
/// As of 2026-09-17 NFsim evaluates through this facade:
/// `cpp/nfsim/NFfunction/nfsim_funcparser.h` retains the `mu::Parser`
/// interface NFsim is written against but parses with
/// `bng::parser::parseExpression` and evaluates with `bng::eval::evaluate`.
/// ExprTk and `NFSIM_USE_EXPRTK` are removed from the build (WO-3b), so there
/// is no second implementation of BNGL math left to drift.
///
/// The facade is intentionally thin: it owns no math. It binds the existing
/// Expression evaluator to a variable context and exposes two call shapes —
/// global (time + observables + parameters) and complex-scoped (the additional
/// per-complex observable values NFsim local functions need).
///
/// Gate: `test_parity_expressions` (function-driven RHS to 1e-9 against the
/// Perl oracle) and the NFsim parity tests. Neither has been run since the
/// evaluator merge; both are required before the merge can be called
/// validated.

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
// How NFsim uses this (implemented; kept as a description of the wiring):
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
// makes the equivalence to the global path obvious, and is what let ExprTk go.

inline double evalLocalFunction(const bng::ast::Expression& fn,
                                double time,
                                const std::function<double(const std::string&)>& localLookup) {
    return evaluate(fn, Context{time, localLookup});
}

} // namespace bng::eval
