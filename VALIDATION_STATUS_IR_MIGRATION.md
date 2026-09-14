# IR migration validation status

Validation date: 2026-09-11

## Passed in the packaging environment

| Check | Result |
|---|---|
| `tools/check_architecture_dependencies.py` | PASS — 21 explicit compatibility files |
| `tests/python/test_bngir_structural_helpers.py` | PASS — 8/8 |
| structural BNGIR + architecture pytest | PASS — 9/9 |
| `python -m py_compile python/bionetgen/bngir.py` | PASS |
| `git diff --check` | PASS |
| direct syntax checks for migrated core/compile/engine/io units | PASS |
| NFsim compiled reaction lowering with temporary ExprTk interface stub | PASS |
| BNGsim adapter with temporary ModelBuilder interface stub | PASS |

## Directly syntax-checked C++ areas

Core matching; `SymbolTable`; `CompiledModel`; `CompiledRule`; `ReactionRule`; `LegacyNetworkRuleKernel`; `NetworkRulePlan`; `ObservableProjection`; ContactMap; RegulatoryGraph; both Ruleviz writers; ProcessGraph; ReactionNetworkGraph; RuleInfluenceGraph; MDL; SSC; LaTeX; C++; Python; MATLAB; MEX exporters; resolved-expression MathML; standard SBML; SBML-Multi.

## Not available in this environment

A complete clean CMake build and full CTest matrix were not rerun. The runtime does not contain the complete ANTLR C++ toolchain/runtime needed to rebuild/test the parser after population-map changes, nor the real external BNGsim dependency. The full NFsim/BNG2 stochastic/oracle matrix was not rerun here.

The temporary ExprTk and BNGsim headers were interface-only syntax stubs created under `/tmp`; they are intentionally excluded from this archive.

## High-priority full-environment validation

Regenerate parser artifacts after expressing the population-map rate in grammar; run hybrid population-map models with nonzero rates; run local-function rules scoped to non-root molecule occurrences; test reversible local scopes; rerun direct compiled NFsim versus compatibility/oracle paths; build the BNGsim adapter against the pinned real dependency; exercise SBML/SBML-Multi round trips.
