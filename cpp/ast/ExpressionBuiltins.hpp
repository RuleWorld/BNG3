/// ExpressionBuiltins.hpp
///
/// One table of BNGL built-in function names for the whole platform.
///
/// WO-3 (expression unification) is the long-running task of making
/// `bng::ast::Expression` the single runtime evaluator and retiring NFsim's
/// ExprTk path. That is a large change gated on the expression parity suite.
/// This header is the narrow, safe slice of it: the *name and arity metadata*
/// that three places previously duplicated, each with its own drift.
///
/// The three consumers were:
///
///   1. `cpp/ast/Expression.cpp` — the shared evaluator (ODE RHS, SSA
///      propensity, network generation, observables, functions).
///   2. `cpp/nfsim/NFinput/NFinput_fromAst.cpp` — `isSupportedGlobalBuiltin`,
///      the gate deciding whether the direct AST->NFsim path can handle a
///      function call or must fall back to the XML bridge.
///   3. `cpp/nfsim/NFfunction/nfsim_funcparser.h` — the ExprTk shim, which
///      registers adapters for the names ExprTk lacks.
///
/// Because those lists were independent, they disagreed. The disagreements
/// were not theoretical:
///
///   - `sign` and `log` were accepted by the NFsim gate but had no
///     implementation in the shared evaluator, so they worked under NFsim and
///     fell through to the user-function resolver under ODE/SSA.
///   - `avg` is a BNG2 built-in, is implemented in the shared evaluator, and
///     is native to ExprTk, yet the gate rejected it and forced an
///     unnecessary XML fallback.
///   - The gate lower-cased names while the ExprTk shim is compiled with
///     `exprtk_disable_caseinsensitivity`, so `SIN(x)` passed the gate and
///     then failed later inside `GlobalFunction::prepareForSimulation()`.
///
/// Every entry below records which backends can evaluate the name, so a
/// contract test can assert the engines agree instead of discovering a
/// mismatch from a model that silently changed meaning.
///
/// ORACLE
/// ------
/// `oracle` records whether the name exists in the BNG2 reference
/// implementation, `legacy/perl/Perl2/Expression.pm` (the `%functions` table
/// at line 56). That file is the compatibility oracle for BNGL expression
/// semantics; it is not a BNG3 design document. Names marked
/// `Bng3Extension` are supported by BNG3 but absent from BNG2, and are
/// therefore a deliberate superset rather than a parity claim.
///
/// Deliberately ABSENT from this table:
///
///   - `log`. BNG2 has no bare `log`; it exposes `ln`, `log10`, and `log2`
///     only. ExprTk's `log` is the natural logarithm, so accepting `log`
///     meant a model written expecting base 10 silently got base e. It is now
///     rejected with a diagnostic naming the three explicit spellings.
///   - `Sat`, `MM`, `Hill`, `Arrhenius`, `FunctionProduct`, `TFUN`/`tfun`.
///     These are rate-law and table-function constructs, not ordinary scalar
///     built-ins. They have dedicated lowering paths and must not be admitted
///     by a generic function gate.
///   - `time`/`t`, `_pi`, `_e`. Resolved before builtin dispatch: `time` from
///     the evaluation context, the constants from the symbol table.

#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <string>
#include <string_view>

namespace bng::ast::builtins {

/// Presence in the BNG2 Perl reference implementation.
enum class Oracle {
    Bng2Builtin,    ///< in legacy/perl/Perl2/Expression.pm %functions
    Bng3Extension,  ///< supported by BNG3, absent from BNG2
};

/// How NFsim can evaluate the name.
enum class NfsimBackend {
    ExprTkNative,  ///< ExprTk provides it directly
    ExprTkShim,    ///< provided by an adapter in nfsim_funcparser.h
    Unavailable,   ///< NFsim cannot evaluate it; direct path must fail closed
};

/// Negative arity means variadic (at least one argument).
inline constexpr int kVariadic = -1;

struct Builtin {
    std::string_view name;
    int              arity;
    Oracle           oracle;
    NfsimBackend     nfsim;
    /// True when cpp/ast/Expression.cpp evaluates this name. Every entry is
    /// currently implemented there; the field exists so that a future addition
    /// on the NFsim side cannot be recorded as shared without the shared
    /// evaluator actually growing an implementation.
    bool             sharedEvaluator;
};

/// The table. Keep alphabetical; keep it the only list.
inline constexpr std::array<Builtin, 27> kBuiltins{{
    {"abs",   1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"acos",  1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"acosh", 1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"asin",  1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"asinh", 1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"atan",  1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"atanh", 1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"avg",   kVariadic, Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    // floor/ceil are commented out in the BNG2 table ("not supported by
    // muParser"), so they are a BNG3 extension rather than parity.
    {"ceil",  1,         Oracle::Bng3Extension, NfsimBackend::ExprTkNative, true},
    {"cos",   1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"cosh",  1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"exp",   1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"floor", 1,         Oracle::Bng3Extension, NfsimBackend::ExprTkNative, true},
    // ExprTk parses `if` as a built-in keyword; both it and BNG2 use `!= 0`
    // truthiness, which is what the shared evaluator implements.
    {"if",    3,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"ln",    1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkShim,   true},
    {"log10", 1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"log2",  1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"max",   kVariadic, Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"min",   kVariadic, Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    // round-half-up, floor(x + 0.5); see Expression.cpp and the shim.
    {"rint",  1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkShim,   true},
    {"sign",  1,         Oracle::Bng3Extension, NfsimBackend::ExprTkShim,   true},
    {"sin",   1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"sinh",  1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"sqrt",  1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"sum",   kVariadic, Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"tan",   1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
    {"tanh",  1,         Oracle::Bng2Builtin,   NfsimBackend::ExprTkNative, true},
}};

/// Case-SENSITIVE lookup. The ExprTk shim is compiled with
/// `exprtk_disable_caseinsensitivity`, and the BNG2 table is lower-case, so a
/// case-insensitive match here would admit spellings no backend can evaluate.
inline const Builtin* find(std::string_view name) {
    const auto it = std::find_if(kBuiltins.begin(), kBuiltins.end(),
                                [&](const Builtin& b) { return b.name == name; });
    return it == kBuiltins.end() ? nullptr : &*it;
}

inline bool isBuiltin(std::string_view name) { return find(name) != nullptr; }

/// True when NFsim can evaluate `name`, i.e. the direct AST path may keep it
/// instead of falling back to the XML bridge.
inline bool isNfsimEvaluable(std::string_view name) {
    const Builtin* builtin = find(name);
    return builtin != nullptr && builtin->nfsim != NfsimBackend::Unavailable;
}

/// True when the shared `bng::ast::Expression` evaluator implements `name`.
inline bool isSharedEvaluable(std::string_view name) {
    const Builtin* builtin = find(name);
    return builtin != nullptr && builtin->sharedEvaluator;
}

/// `true` when `count` arguments is acceptable for `name`.
inline bool acceptsArgumentCount(std::string_view name, std::size_t count) {
    const Builtin* builtin = find(name);
    if (builtin == nullptr) return false;
    if (builtin->arity == kVariadic) return count >= 1;
    return static_cast<int>(count) == builtin->arity;
}

/// Diagnostic for a name this table rejects. Returns a hint for the known
/// removals so the user is not left guessing, and an empty string otherwise
/// (callers supply their own generic message).
inline std::string rejectionHint(std::string_view name) {
    if (name == "log") {
        return "BNGL has no 'log'; use 'ln' (natural), 'log10', or 'log2'";
    }
    if (name == "mratio") {
        return "'mratio' has no NFsim implementation; it is available to the "
               "ODE/SSA backends only";
    }
    if (name == "Sat" || name == "MM" || name == "Hill" ||
        name == "Arrhenius" || name == "FunctionProduct") {
        return "rate-law constructs are lowered separately and cannot appear "
               "as a general function call here";
    }
    if (name == "TFUN" || name == "tfun") {
        return "table functions are lowered separately via the TFUN adapter";
    }
    return {};
}

} // namespace bng::ast::builtins
