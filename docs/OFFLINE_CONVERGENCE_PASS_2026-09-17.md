# BNG3 offline convergence pass — 2026-09-17

Static audit and low-risk convergence fixes performed in a restricted
container: no network, no `cmake`, no `ninja`, no Catch2/ANTLR4/SUNDIALS/ExprTk
build tree, and **no Git checkout** (the working tree was a source snapshot
with no `.git`, so `git status`, `git log`, `git diff`, and `git diff --check`
were unavailable; plain file diffs were used instead).

Two tools that the plan assumed absent turned out to be available and were
used for real verification: **`perl` 5.x**, which allowed the BNG2 expression
oracle to be *executed* rather than read, and **`g++ 13.3`**, which allowed
dependency-light translation units and new headers to be compiled and in some
cases run.

Scope exclusions were respected: no work on NFsim energy functionality
(EnergyPattern, PR #475, barrier patterns, `driven_by`, thermodynamic
semantics) and none on Atomizer/SBML.

---

## 1. Executive summary

### What was already implemented despite an unchecked checklist

The tree is substantially more complete than the checklist implies. Of roughly
120 unchecked items, the large majority are **validation, oracle, provenance,
or maintainer-decision** items that cannot be closed offline by construction —
not missing implementation. Specifically already in place and working:

- The direct AST→NFsim path is the **default** in both `bind_nfsim.cpp` and
  `ActionDispatch.cpp`, and is **fail-closed**: XML fallback requires an
  explicit `BNG_NFSIM_ALLOW_XML_FALLBACK=1` opt-in, and
  `BNG_NFSIM_REQUIRE_DIRECT` hard-fails. `construction_path` is already
  reported to Python. The checklist's framing of XML as the default path is
  stale.
- WO-4 (guarding the standalone `NFsim` CLI behind `BUILD_NFSIM_CLI`) is
  already applied, though `cpp/CMakeLists.unify.snippet.cmake` still describes
  it as pending.
- The per-section compiled builders (`*FromCompiled`) already consume only the
  `bng::compile` contract, so the parser/AST → backend seam the checklist asks
  for exists.
- `cpp/compile/Capabilities.cpp` already gates unsupported models before
  construction begins, with diagnostics.

### What was actually missing

Four genuine defects and one genuine architectural duplication:

1. **`rint` was numerically wrong in both expression engines, in different
   directions.** This is the most consequential finding. BNG2 defines
   `rint(x)` as `floor(x + 0.5)` (round-half-up) at
   `legacy/perl/Perl2/Expression.pm:74`. The shared evaluator used
   `std::rint` (round-half-to-even) and NFsim's ExprTk shim used `std::round`
   (round-half-away-from-zero). Verified by executing the Perl oracle:

   | x | oracle | old shared (`std::rint`) | old NFsim (`std::round`) |
   |---|---|---|---|
   | -2.5 | -2 | -2 | **-3** |
   | -1.5 | -1 | **-2** | **-2** |
   | -0.5 |  0 | **-0** | **-1** |
   |  0.5 |  1 | **0** | 1 |
   |  1.5 |  2 | 2 | 2 |
   |  2.5 |  3 | **2** | 3 |
   |  3.5 |  4 | 4 | 4 |

   The shared evaluator was wrong at 4 of 7 half-integers, NFsim at 3 of 7,
   and they disagreed with each other at 2. No corpus model uses `rint`, which
   is why the 71/71 validation gate stayed green.

2. **Backend asymmetry in the builtin function sets.** Three independent lists
   (shared evaluator dispatch, the direct-NFsim gate, the ExprTk shim) had
   drifted. `sign` and `log` were accepted by the NFsim gate with no
   implementation in the shared evaluator; `avg` was implemented and
   ExprTk-native but rejected by the gate, forcing an unnecessary XML
   fallback; and the gate matched case-insensitively while the shim is built
   with `exprtk_disable_caseinsensitivity`, so `SIN(x)` passed the gate and
   then failed late inside `GlobalFunction::prepareForSimulation()`.

3. **Two BNG2 observable counting modes did not exist at all.**
   `MoleculesObservables` and `SpeciesObservables` appeared **nowhere** in
   BNG3 — zero occurrences across `cpp/`, `python/`, `tests/`, and `models/`.
   A model requesting `CountUnique` received `CountAll` values with no
   warning. `SpeciesLabel` (`Auto`/`HNauty`/`Quasi`) was likewise stored and
   read by nobody.

   Both modes are now implemented in `cpp/engine/ObservableProjection.cpp`.
   Reading the oracle closely was essential here, because the two options
   share a spelling but are **not the same operation**:

   | observable kind | `CountAll` | `CountUnique` |
   |---|---|---|
   | `Molecules` | `total += match_count` | `total += match_count / Aut(pattern)` |
   | `Species` | `+1` per matching pattern | `+1`, then stop scanning patterns |

   BNG2's symmetry correction is commented out on the `Species` branch, where
   the flag instead short-circuits the term loop (`last if ($mode)`), so a
   species counts once however many of the observable's patterns it matches.
   An initial reading that applied automorphism division to both keys would
   have produced plausible-looking but wrong `Species` values; the corrected
   semantics are pinned by `tests/cpp/test_observable_counting.cpp`.

   The `Molecules` division is asserted exact rather than truncated. `Aut(P)`
   acts freely on embeddings by precomposition, so the embedding set
   partitions into orbits of size exactly `|Aut(P)|` and the quotient is
   always an integer; a remainder indicates a matcher defect, not a modelling
   situation, so it throws. The claim was checked numerically over 32
   pattern/target combinations (symmetric edge, path, triangle, and star
   patterns into complete graphs and cycles) with zero non-divisible cases.

4. **The direct-NFsim fallback reason was discarded at the boundary.** The
   nine per-section builders write precise messages to stderr, but
   `buildSystemFromAst` returned a bare `nullptr`, so both call sites threw
   "NFsim direct AST initialization unavailable" with no cause. An operator
   could not distinguish an unported construct from a model error.

5. **Duplicate Nauty build.** `cpp/nauty/*.c` and `cpp/nfsim/nauty24/*.c` were
   both compiled and linked into every binary. After normalizing the
   documented `set`→`nset` rename they are identical, except that only the
   NFsim copy guarded `HAVE_SYSTYPES_H` under MSVC — so `cpp/nauty` carried a
   latent MSVC portability bug. `cpp/CMakeLists.unify.snippet.cmake` specified
   this exact edit as WO-1b and it had never been applied.

### Also found, deliberately not changed

- **`cpp/core/HNauty.hpp` has zero callers.** A ~650-line hand-port of
  `HNauty.pm` is unreachable from any translation unit. Deleting it is
  premature: the checklist has an open maintainer decision about the
  "largest-versus-canonical-form" question at `HNauty.hpp:640`, and that
  decision should be made before the reference implementation is discarded.
  Recorded in the retirement table below.
- **The dead `if` adapter in `nfsim_funcparser.h` was deleted** (see changed
  files). It registered `add_function("if", ...)` with `cond > 0.5` truthiness,
  contradicting both ExprTk's built-in `if` keyword and BNG2's
  `if($_[0])` nonzero truthiness. ExprTk's grammar claims the name before
  symbol-table lookup, so the adapter was unreachable — but leaving wrong
  semantics in an unreachable adapter is a trap for the next ExprTk bump.

### What remains

Everything requiring a build, an independent oracle, or a maintainer
signature. Sections 5 and 6 below enumerate this precisely.

---

## 2. Gap table

Statuses: `DONE`, `DONE_BUT_UNVALIDATED`, `PARTIAL`, `MISSING`,
`BLOCKED_BY_ENVIRONMENT`, `MAINTAINER_DECISION`, `OUT_OF_SCOPE`.

| Area | Status | Evidence | Remaining work |
|---|---|---|---|
| graph canonicalization | `DONE_BUT_UNVALIDATED` | One compiled tree; `nfsim_core` links `nauty`; 10/10 structural contract passes locally | Build + independent NFsim identity/trajectory evidence that one low-level dependency does not alter complex identity |
| expression representation | `PARTIAL` | `bng::ast::Expression` vs ExprTk still split; `bng::eval` facade has zero consumers | Route NFsim functions through the shared evaluator (gated on parity suite); then remove `NFSIM_USE_EXPRTK` per WO-3b |
| expression builtin metadata | `DONE_BUT_UNVALIDATED` | `cpp/ast/ExpressionBuiltins.hpp` is the single table; consumed by both engines; invariant compiled and run locally | Cross-backend numerical parity under CI |
| `rint` semantics | `DONE_BUT_UNVALIDATED` | Fixed in both engines; oracle values produced by executing `Expression.pm:74` | Confirm under CTest; no corpus fixture exercises it, so consider adding one |
| direct NFsim (non-energy) | `PARTIAL` | Direct path is default and fail-closed; nine builders present; precise per-stage reasons now surfaced | Close remaining per-construct fallbacks; each needs a fixture and oracle result |
| direct NFsim fallback reporting | `DONE_BUT_UNVALIDATED` | Named stage table; `direct_unavailable_reason` on `Result` | Assert the reason string in the parity harness |
| parser/AST | `PARTIAL` | Grammar and AST substantial; `setOption` was the one parsed-but-dropped construct found | Systematic per-construct backend-drop sweep beyond options |
| network generation | `BLOCKED_BY_ENVIRONMENT` | Not statically auditable without running fixtures | Full Tier-P NET parity vs BNG2 |
| simulators (ODE/SSA/PLA/PSA) | `BLOCKED_BY_ENVIRONMENT` | — | Requires SUNDIALS build |
| Python API | `PARTIAL` | `Result` extended and `py_compile` clean | Legacy `modelapi` retirement (see table below) |
| CLI/actions | `PARTIAL` | `setOption` now validated at a single seam | Audit remaining actions for silent no-ops |
| model options | `DONE_BUT_UNVALIDATED` | `cpp/ast/ModelOptions.hpp`; registry compiled and run locally | — |
| observable counting modes | `DONE_BUT_UNVALIDATED` | `cpp/engine/ObservableProjection.cpp` implements both `CountAll` and `CountUnique` for Molecules and Species; `-fsyntax-only` clean; divisibility argument verified numerically | BNG2 differential run |
| XML/NET/BNGL round-trip | `BLOCKED_BY_ENVIRONMENT` | — | Requires build |
| validation framework | `BLOCKED_BY_ENVIRONMENT` | Exclusion ledger reported empty; not re-verifiable offline | Re-run strict corpus |
| provenance | `MAINTAINER_DECISION` | `upstreams.lock.yml` statuses are `observed`/`pending`; no SHA verifiable without network | Maintainer selects cutoffs; no guessed hashes added |
| legacy code | `MAINTAINER_DECISION` | `HNauty.hpp` unreachable; Perl retained as oracle | See retirement table |
| release engineering | `BLOCKED_BY_ENVIRONMENT` | — | Wheel matrix on merge head |
| NFsim energy | `OUT_OF_SCOPE` | — | — |
| Atomizer / SBML | `OUT_OF_SCOPE` | — | — |

### Remaining-gap checklist

```markdown
## Graph/canonicalization
- [x] Every bundled Nauty tree identified (cpp/nauty, cpp/nfsim/nauty24)
- [x] Compiled consumers identified from CMake
- [x] Trees compared; identical modulo the documented set->nset rename
- [x] One compiled tree; nfsim_core links the shared target
- [x] Structural regression test added and passing
- [ ] Runtime proof that one dependency preserves NFsim complex identity
- [ ] HNauty largest-vs-canonical-form decision (MAINTAINER_DECISION)
- [ ] cpp/core/HNauty.hpp reachability resolved (delete or wire up)

## Expression/functions
- [x] All expression parsers/evaluators inventoried (3 builtin lists, 2 engines)
- [x] Builtin name/arity/semantics metadata unified in one table
- [x] rint reconciled with the executed BNG2 oracle in both engines
- [x] sign implemented in the shared evaluator
- [x] log rejected everywhere with an ln/log10/log2 diagnostic
- [x] avg admitted by the NFsim gate (removed a false fallback)
- [x] Builtin gate made case-sensitive to match the shim
- [x] Dead `if` adapter with wrong truthiness deleted
- [ ] NFsim functions routed through bng::eval (the WO-3 evaluator swap)
- [ ] bng::eval facade given real consumers, or removed as dead code
- [ ] NFSIM_USE_EXPRTK build path removed (WO-3b; blocked on the above)
- [ ] String round-trips into NFsim eliminated

## Direct NFsim
- [x] Every direct-path fallback reason enumerated
- [x] Generic fallback reasons replaced with per-stage attribution
- [x] Reason surfaced at both call sites and on the Python Result
- [ ] Per-construct fallbacks closed (local-function scopes, population maps,
      reaction filters, protocol-NF)
- [ ] XML bridge retained until CI proves direct parity (unchanged, correct)

## Parser/AST
- [x] setOption identified as parsed-but-dropped and validated at one seam
- [ ] Remaining constructs swept for backend drop

## Network generation / Simulation
- [ ] BLOCKED_BY_ENVIRONMENT (no build)

## Python/API
- [x] direct_unavailable_reason exposed on Result
- [ ] Legacy modelapi retirement (MAINTAINER_DECISION)

## CLI/actions
- [x] setOption no longer silently ignores semantically active options
- [x] MoleculesObservables/SpeciesObservables CountAll and CountUnique
      implemented (they previously did not exist)
- [ ] Remaining actions audited for silent no-ops
- [ ] SpeciesLabel=Quasi approximate labeling (fail-closed; implementing it
      means a second canonicalization mode, a deliberate design decision)

## Interchange
- [ ] BLOCKED_BY_ENVIRONMENT

## Validation/provenance
- [ ] BLOCKED_BY_ENVIRONMENT / MAINTAINER_DECISION; no fake approvals added

## Legacy cleanup
- [ ] See retirement table; nothing deleted that is still reachable
```

---

## 3. Changed-files table

| File | Change | Reason | Validation |
|---|---|---|---|
| `cpp/nauty/{nauty.h,nauty.c,nautil.c,nausparse.h,nausparse.c}` | Adopted the `nset`-patched variant | One compiled nauty; also fixes the missing MSVC `HAVE_SYSTYPES_H` guard | `diff` clean vs the deleted copy after normalizing the rename; `STATICALLY VERIFIED` |
| `cpp/nfsim/nauty24/` | **Deleted** (5 sources + readme) | Duplicate build of the same upstream library | `STATICALLY VERIFIED` — no remaining references |
| `cpp/nauty/README.md` | New | Records the `nset` provenance, consumers, and why not to re-fork | n/a (doc) |
| `cpp/nfsim/NFcore/complex.cpp` | `#include "../nauty24/nausparse.h"` → `"nausparse.h"` | Resolve through the shared target's interface include | `STATICALLY VERIFIED` |
| `cpp/CMakeLists.txt` | Removed `NFSIM_NAUTY_C` glob + source entry; replaced the private include dir with `$<TARGET_PROPERTY:nauty,...>`; added `nauty` to `nfsim_core` links | WO-1b | `PURE-PYTHON TESTED` (structural contract) |
| `cpp/ast/ExpressionBuiltins.hpp` | New, 27 entries | Single builtin table for both engines | Compiled **and run**: invariants pass |
| `cpp/ast/Expression.cpp` | `rint` → `floor(x+0.5)`; added `sign`; rejected-name diagnostic before the user-function fall-through; includes the table | Oracle parity and backend agreement | `SYNTAX CHECKED` (`g++ -fsyntax-only`, clean); oracle values executed in Perl |
| `cpp/nfsim/NFfunction/nfsim_funcparser.h` | `rint` → `floor(x+0.5)`; deleted `IfFunction`, its member, and its registration | Oracle parity; remove unreachable wrong-semantics code | `IMPLEMENTED BUT NOT BUILD-VERIFIED` (needs ExprTk) |
| `cpp/nfsim/NFinput/NFinput_fromAst.cpp` | Gate delegates to the shared table; added `unsupportedBuiltinDiagnostic`; named nine-stage table with per-stage failure attribution; `<array>`/`<functional>` includes | Remove list drift; precise fallback reasons | Pattern compiled and run in isolation; full TU `REQUIRES FULL CI` (ANTLR) |
| `cpp/nfsim/NFinput/NFinput_fromAst.hh` | Added defaulted `std::string* unavailableReason` to three overloads | Propagate the reason without breaking callers | `STATICALLY VERIFIED` |
| `cpp/bindings/bind_nfsim.cpp` | Captures and reports the reason; adds `direct_unavailable_reason` to the result dict | Auditable fail-closed errors | `REQUIRES FULL CI` (pybind11) |
| `cpp/actions/ActionDispatch.cpp` | Captures and reports the reason | Same | `REQUIRES FULL CI` |
| `cpp/ast/ModelOptions.hpp` | New | `setOption` validation against the BNG2 oracle | Compiled **and run**: registry invariants pass |
| `cpp/engine/ObservableProjection.{hpp,cpp}` | Implemented `CountAll`/`CountUnique` for Molecules and Species; per-term automorphism count cached at construction; exact-division assertion | The two modes did not exist | `SYNTAX CHECKED` (clean); divisibility verified numerically |
| `tests/cpp/test_observable_counting.cpp` | New, 5 test cases | Pins the two modes and their non-equivalence | `REQUIRES FULL CI` (Catch2) |
| `cpp/ast/Model.cpp` | Validate in `setOption`; warn on deprecated only | Single seam covering parser, actions, and hybrid copy | `SYNTAX CHECKED` (clean) |
| `python/bionetgen/result.py` | `direct_unavailable_reason` attribute + docstring | Expose the reason to harnesses | `PURE-PYTHON TESTED` (`py_compile` clean) |
| `tests/cpp/test_expression_evaluator.cpp` | +4 test cases | Regressions for `rint`, `sign`, `log`, and engine agreement | `REQUIRES FULL CI` (Catch2) |
| `tests/cpp/test_model_options.cpp` | New, 4 test cases | Regressions for option validation | `REQUIRES FULL CI` (Catch2) |
| `tests/cpp/CMakeLists.txt` | Registered `test_model_options` | — | `STATICALLY VERIFIED` |
| `tests/python/test_single_nauty_contract.py` | New, 7 tests / 10 cases | Locks the single-nauty invariant | `PURE-PYTHON TESTED` — 10/10 pass locally |
| `docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md` | Updated 3 items with explicit partial/awaiting-validation wording | Stop the checklist being stale in both directions | n/a (doc) |
| `cpp/CMakeLists.unify.snippet.cmake` | Marked WO-1b and WO-4 applied | Snippet described applied work as pending | n/a (doc) |

No file outside this table was modified. No assertion, guard, tolerance,
exclusion, or skip was weakened. No test was disabled.

---

## 4. Legacy-path retirement analysis

| Legacy component | Replacement | Remaining blocker | Safe to delete? |
|---|---|---|---|
| `cpp/nfsim/nauty24/` | shared `nauty` target | none — all references eliminated | **Yes, done** |
| `detail::IfFunction` (ExprTk shim) | ExprTk built-in `if` | none — unreachable by grammar precedence | **Yes, done** |
| `cpp/core/HNauty.hpp` | `bng::core` canonical labeling via `PatternGraph.cpp` | Zero callers, but the `HNauty.hpp:640` largest-vs-canonical decision is still open and this is the only in-tree reference implementation | **No** — resolve the decision first |
| `cpp/ast/ExpressionEval.{hpp,cpp}` | intended to *become* the shared path | Zero consumers; it is the target of WO-3, not dead weight to remove | **No** — wire up or consciously abandon |
| NFsim ExprTk path (`NFSIM_USE_EXPRTK`) | `bng::eval` facade | WO-3 evaluator swap not started | **No** |
| XML-mediated NFsim path | direct AST construction | Direct parity not proven under CI; it is the behavioral oracle | **No** — correctly retained |
| `python/bionetgen/modelapi/` | modern `bionetgen` API | Needs a zero-default-path-reference proof and contract tests | **No** |
| `legacy/perl/` | BNG3 native | It *is* the semantic oracle; this pass depended on it | **No** — keep indefinitely |
| `cpp/nauty/nauty24/` + `nauty24.tar.gz` | n/a | Not compiled; upstream provenance | **No** — keep as provenance |

---

## 5. Deferred validation commands

Read from `AGENTS.md`, `CMakeLists.txt`, `.github/workflows/`, and `scripts/`.
None invented.

```bash
# Build
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
pip install -e .

# Native tests — expect the two new Catch2 targets to appear
ctest --test-dir build --output-on-failure
ctest --test-dir build -R 'test_expression_evaluator|test_model_options' \
      --output-on-failure

# Python suite
PYTHONPATH=python:build/cpp python -m pytest -q tests/python

# The one new test that already passes offline
python -m pytest -q tests/python/test_single_nauty_contract.py

# Validation corpus and contracts
python -m pytest -q tests/validation
python scripts/validate.py
python scripts/validate_actions.py
python scripts/validate_ratelaws.py
python scripts/validate_trajectories.py
python scripts/validate_io_roundtrip.py
python scripts/validate_provenance.py
python scripts/validate_corpus_manifest.py
python scripts/validate_golden_manifest.py
python scripts/check_localfunc_rates.py

# Independent NFsim oracle (requires -DBUILD_NFSIM_CLI=ON)
cmake -B build-oracle -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_NFSIM_CLI=ON
cmake --build build-oracle -j
python scripts/validate_nfsim.py
python scripts/cross_validate.py

# Architecture ratchet
python tools/check_architecture_dependencies.py
```

### Targeted checks for this pass

```bash
# The nauty unification is a link-level change: confirm one definition.
nm -C build/cpp/libnfsim_core.a 2>/dev/null | grep -c ' T nauty$'   # expect 1
nm -C build/cpp/libnauty.a      | grep -c ' T nauty$'               # expect 1

# Confirm the direct path is still selected for models that used it, and that
# any fallback now carries a reason.
BNG_NFSIM_REQUIRE_DIRECT=1 python -m pytest -q tests/python -k nfsim

# rint has no corpus fixture; this is the minimum manual check.
python -c "
import bionetgen" # then evaluate a function using rint() under ode and nf
```

---

## 6. Full-CI validation checklist

Another environment must verify:

- [ ] clean configure (the `nfsim_core` include list now uses a generator
      expression — confirm it expands)
- [ ] complete build on GCC, Clang, **and MSVC** — the MSVC matrix is the
      specific risk for the nauty unification, since the merged header changes
      `HAVE_SYSTYPES_H` behavior under `_MSC_VER`
- [ ] one `nauty` symbol set in the final binaries
- [ ] CTest, including `test_expression_evaluator` and `test_model_options`
- [ ] Python suite (`399 passed, 28 skipped` baseline)
- [ ] strict validation corpus at `71/71`, `0` skips — **the option-validation
      change is the regression risk here**: `setOption` now throws on
      `SpeciesLabel=Quasi` and `*Observables=CountUnique`. No corpus model uses
      either (verified by grep), and `SpeciesLabel=HNauty`,
      `NumberPerQuantityUnit`, `units`, and the unknown key `test` are all
      still accepted, but this needs a real corpus run
- [ ] action contracts `6/6`
- [ ] `test_observable_counting` — the five cases assert concrete integers (2,
      1, 2, 1, 2) and will fail loudly if the matcher's embedding count for a
      symmetric homodimer differs from 2 on any platform
- [ ] a BNG2 differential on a `CountUnique` model, which is the only way to
      confirm the counting modes against the oracle rather than against the
      oracle's source text
- [ ] direct NFsim tests, with `construction_path` still `direct` for every
      fixture that was direct before
- [ ] independent NFsim oracle comparison — required before the nauty
      unification can be called identity-preserving
- [ ] independent BNG2 differential, including an `rint` fixture if one is added
- [ ] sanitizer jobs
- [ ] packaging / wheel matrix

**No claim of parity, convergence, or release readiness is made.** Nothing in
this pass was build-verified. The only results actually executed here are: the
Perl oracle values for `rint`; the compiled-and-run builtin-table and
option-registry invariants; the named-stage failure-attribution pattern;
`g++ -fsyntax-only` on `cpp/ast/Expression.cpp` and `cpp/ast/Model.cpp`;
`py_compile` on `python/bionetgen/result.py`; and 10/10 cases of
`tests/python/test_single_nauty_contract.py`.

---

## 7. Addendum — 2026-09-17, second pass

### 7.1 One expression engine (WO-3 + WO-3b) — done

NFsim no longer has its own expression implementation. `nfsim_funcparser.h`
keeps the `mu::Parser` interface NFsim is written against (it is held by
`GlobalFunction`, `LocalFunction`, `CompositeFunction`, and
`Observable::addReferenceToMyself`, and threaded through rate evaluation), but
the guts are now `bng::parser::parseExpression` for parsing and
`bng::eval::evaluate` for evaluation. ExprTk, `NFSIM_USE_EXPRTK`, every
`exprtk_SOURCE_DIR` include path, and the root `FetchContent_Declare(exprtk)`
block are removed — which also drops a network fetch from a cold configure.

The shim went from 312 lines to 208, and the deletions matter more than the
line count:

- **The underscore remapping layer is gone.** `remap_name` / `remap_expression`
  / `trackUnderscoreName` existed only because ExprTk rejects identifiers
  beginning with `_`, so `_PI`, `_e`, `_Na`, and the injected `__TFUN_VAL__`
  were rewritten to `u_PI` and friends and the expression text rescanned. The
  BNGL lexer accepts them natively (`STRING: (LETTER | '_') (LETTER | DIGIT |
  '_')*`). The rescan was also a latent bug: it rewrote *any* `_`-leading token
  anywhere in the string.
- **`normalize_legacy_logical_operators` is gone.** It rewrote `&&` to ` and `
  for ExprTk. `bng::ast::Expression` implements `&&`, `||`, `^^`, `!`, `~`,
  `%`, `**`, and the full comparison set directly.
- **`LnFunction`, `RintFunction`, `SignFunction` are gone** — adapters for
  names ExprTk lacked, now implemented once in the shared evaluator.

`bng::eval` also stops being dead code: the shim is its first real consumer, so
the facade's item can come off the retirement table.

Verified by compiling the **real** shim header and the **real**
`Expression.cpp`/`ExpressionEval.cpp` together against a stubbed
`parseExpression` (ANTLR is unavailable offline) and running it. Behaviors
confirmed: live `DefineVar` pointers; `DefineConst` refresh *after* `SetExpr`
with no reparse (what `__TFUN_VAL__` injection and `Observable::
addReferenceToMyself` depend on); leading-underscore identifiers without
remapping; oracle `rint(2.5) == 3` and `sign(-3) == -1`; native `&&`; `if()`
using `cond != 0` truthiness; simulation time resolving through both the
`time` symbol and the `t()` call form; and parse/unknown-symbol/eval-before-
SetExpr errors all surfacing as `mu::Parser::exception_type` so NFsim's
existing catch sites are unchanged.

**Expected regression risk: performance.** This is a tree walk where ExprTk
compiled to a faster form, so per-evaluation cost should rise on
function-heavy and functional-rate models (`localfunc`, `motor`, `TQSSA`,
`CaOscillate_Func`, the `test_tfun_*` set). Convergence before performance per
AGENTS.md; if it bites, the fix is memoization inside
`bng::ast::Expression`, which benefits every backend — not a second engine.

### 7.2 Direct NFsim hard cases — root-caused, NOT fixed

I diagnosed this rather than implementing it, and want to be explicit that it
is unfinished.

**The refusal.** `collectLocalFunctionReferences`
(`NFinput_fromAst.cpp:1115` and `:1133`) rejects any local function whose body
calls another model function: *"nested local/composite mapping is not direct
yet"*.

**Why it fails.** NFsim's `LocalFunction` needs a *flat* list of references —
observables and molecule-scoped counters — which it binds to live pointers at
`prepareForSimulation` time. A nested model-function call is not expressible in
that flat list, so the collector gives up rather than producing a
`LocalFunction` whose references do not cover its body.

**Why this is tractable, and the shape of the fix.** The *global* path already
solves the same problem by inlining: `expandModelFunction`
(`NFinput_fromAst.cpp:436`) substitutes a zero-argument model function's body
into the caller, with an `activeFunctions` set for cycle detection, and is used
at three call sites. The local path should reuse that mechanism: on seeing a
zero-argument model-function call whose body contains no scoped/local
reference, recurse into the callee's body to collect *its* references under the
same cycle guard, and inline the callee's text so the emitted expression
contains no unresolved call.

**Why I stopped.** Two things are unresolved and neither is safely decidable
without running NFsim:

1. Reference collection and expression-string construction are separate passes
   here. Inlining must be applied consistently to both or the `LocalFunction`
   gets references that do not match its expression text — which fails at
   `prepareForSimulation` or, worse, evaluates with a stale binding.
2. The genuinely hard subcase is a nested call to a *one-argument local*
   function, i.e. scope composition. That is what NFsim's `CompositeFunction`
   exists for, and mapping onto it is a semantic question (whose complex scope
   wins) rather than a missing translation. Guessing would violate the
   "never reinterpret a model silently" rule this codebase is built on.

Doing (1) alone would close the common real-world case — a local function
calling a plain global helper — and is the right next commit. It needs a
build and the `localfunc` / `isingspin_localfcn` fixtures to verify, so I have
left the fail-closed refusal in place with its precise diagnostic rather than
shipping an unverified translation.

### 7.3 Dead code and unimplemented options — marked, not deleted

- `cpp/core/HNauty.hpp` now carries an `UNUSED — REFERENCE IMPLEMENTATION
  ONLY` banner recording that `hnauty(...)` has zero callers, that no
  translation unit includes it, that it is retained as the only in-tree port of
  `HNauty.pm` for the open largest-versus-canonical-form decision, and that it
  is therefore outside CI coverage except via `tests/cpp/test_hnauty.cpp`.
- `SpeciesLabel=Quasi` is now **accepted, recorded, and warned about** as
  `UNUSED` rather than rejected. The asymmetry with `CountUnique` is
  deliberate: falling back to the *exact* canonicalization path cannot degrade
  species identity, whereas silently downgrading `CountUnique` to `CountAll`
  would have changed observable values. The warning exists because a user who
  chose `Quasi` for tractability on a large model should know they are paying
  the exact path's cost.

### 7.4 Legacy Python API — cannot be deleted yet

Marked, with the evidence, in `python/bionetgen/modelapi/__init__.py`.

The premise that nothing depends on it does not hold. `modelapi` is on the
**default import path**:

```
python/bionetgen/__init__.py:93    from bionetgen.modelapi.model import bngmodel
python/bionetgen/__init__.py:105   from bionetgen.modelapi.sympy_odes import ...
python/bionetgen/core/tools/cli.py:44        import bionetgen.modelapi.model as mdl
python/bionetgen/core/tools/visualize.py:143 bionetgen.modelapi.bngmodel(...)
python/bionetgen/atomizer/utils/consoleCommands.py
```

plus six test modules (`test_bng_parsing`, `test_sympy_odes`,
`test_get_rule_mod`, `test_bngfile_compat`, `test_bionetgen`, `test_runner`).
Deleting the package would break `import bionetgen` outright, and the
checklist's own precondition — a search proving zero default-path references —
is not met. Retirement order is recorded in the module docstring:
reimplement `bngmodel`/`sympy_odes` on the native backend, migrate `cli.py`
and `visualize.py`, rewrite the six test modules, re-run the search, then
delete.

### 7.5 Revised retirement table

| Legacy component | Replacement | Remaining blocker | Safe to delete? |
|---|---|---|---|
| ExprTk + `NFSIM_USE_EXPRTK` | shared evaluator via `mu::Parser` shim | none | **Yes, done** |
| ExprTk underscore remapping / operator normalization | BNGL lexer + `Expression` operators | none | **Yes, done** |
| `bng::eval` facade (was dead) | — | none; it now has a consumer | **No — in use** |
| `cpp/core/HNauty.hpp` | `core/PatternGraph.cpp` | largest-vs-canonical decision | **No — marked UNUSED** |
| XML-mediated NFsim path | direct AST construction | nested local/composite mapping (7.2); direct parity unproven | **No** |
| `python/bionetgen/modelapi/` | native backend | on the default import path (7.4) | **No** |
| `legacy/perl/` | — | it *is* the oracle | **No — keep** |

### 7.6 Additional CI requirements from this pass

- [ ] **Configure with no network.** The ExprTk fetch is gone; confirm a cold
      configure no longer reaches for it and that no target still references
      `exprtk_SOURCE_DIR`.
- [ ] **The expression parity gate** (`test_parity_expressions`, functional RHS
      to 1e-9 against the Perl oracle) — this is now the gate for the merged
      evaluator and has not been run against it.
- [ ] **NFsim function-bearing fixtures**: `localfunc`, `isingspin_localfcn`,
      `isingspin_energy`, `motor`, `TQSSA`, `CaOscillate_Func`, `tlbr`, and the
      `test_tfun_*` set — every one exercises a code path whose evaluator just
      changed.
- [ ] **TFUN specifically**, because `__TFUN_VAL__` injection relied on
      ExprTk's post-`SetExpr` recompile and now relies on live map lookup.
- [ ] **Benchmarks**, to quantify the expected tree-walk slowdown before
      deciding whether memoization is needed.
- [ ] Observable counting: a BNG2 differential on a `CountUnique` model.
