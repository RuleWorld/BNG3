# Energy/compiler validation matrix

| ID | Layer | Contract | Gate |
|---|---|---|---|
| E001 | EnergyDeltaPlan | conjunction masks compute literal ΔG | exact, 1e-12 |
| E002 | EnergyDeltaPlan | invalid masks rejected | exact |
| E003 | EnergyDeltaPlan | >63 predicates fail closed | exact |
| E004 | EnergyDeltaPlan | forward/reverse Arrhenius factors satisfy ratio | exact, 1e-12 |
| E005 | EnergyDeltaPlan | lookup table equals direct evaluation | exhaustive |
| E006 | Energy compiler | shared predicates deduplicate | exact |
| E007 | Energy compiler | context on reactant 1 preserved | exact |
| E008 | Energy compiler | mixed-reactant context preserved | exact |
| E009 | Energy compiler | state predicates preserved | exact |
| E010 | Energy compiler | one-hop partner-state preserved | exact |
| E011 | Energy compiler | correlated/ambiguous topology falls back | exact |
| E012 | Energy compiler | same-type reactants do not alias orientation | exact |
| E013 | Compatibility | old EnergyBindingContext only for representable occupancy predicates | exact |
| E014 | Legacy bridge | malformed factor becomes opaque/global fallback | exact |
| D001 | Dependency | state edit invalidates only matching factor/rules | exact |
| D002 | Dependency | bond edit invalidates both endpoint dependencies | exact |
| D003 | Dependency | add/delete molecule conservatively invalidates type-dependent factors | exact |
| D004 | Dependency | unresolved AST refs cause conservative global invalidation | exact |
| D005 | Dependency | AST-native descriptor equals source pattern meaning | exact |
| D006 | Dependency | no normal-path reparsing of BNGL strings | structural |
| C001 | Cache | repeated compile returns same immutable object | exact |
| C002 | Cache | A+B and B+A plans remain orientation-sensitive | exact |
| C003 | Cache | energy-store version bump invalidates plans | exact |
| C004 | Cache | concurrent lookup compiles once | exact/race-free |
| L001 | Lowering | constant ΔG -> constant backend | exact |
| L002 | Lowering | one-reactant predicates -> mapping-local backend | exact |
| L003 | Lowering | two-reactant predicates -> pair-factorized backend | exact |
| L004 | Lowering | unsupported topology -> materialized fallback | exact |
| L005 | Lowering | opt-in flag does not alter unsupported/default behavior | exact |
| R001 | Runtime | staged reversible build commits atomically | exact |
| R002 | Runtime | failed reverse build leaves system unchanged | exact |
| R003 | Runtime | pair aggregation propensity equals literal pair enumeration | exhaustive |
| R004 | Runtime | mapping-local weighted propensity equals literal mapping sum | exhaustive |
| R005 | Runtime | initial propensity generalized == materialized | 1e-12 |
| R006 | Runtime | selected physical event weights equal materialized classes | 1e-12 |
| R007 | Runtime | molecularity/null-event behavior preserved | exact |
| R008 | Runtime | symmetric sites preserve multiplicity | exact |
| R009 | Runtime | same-type reactants remain safe | exact/fallback |
| T001 | Thermodynamics | barrier shift changes kinetics but not equilibrium ratio | 1e-12 |
| T002 | Thermodynamics | driving work changes cycle affinity | 1e-12 |
| T003 | Thermodynamics | tree has zero cycle rank | exact |
| T004 | Thermodynamics | one independent loop has cycle rank 1 | exact |
| T005 | Thermodynamics | gauge dimension equals connected components | exact |
| I001 | Indexed IR | affine index mapping | exact |
| I002 | Indexed IR | boundary indices are correct | exact |
| I003 | Indexed IR | affected-index query is local | exact |
| I004 | Indexed IR | invalid/out-of-domain index rejected | exact |
| S001 | Stochastic | endpoint mean parity | <=5 pooled SE |
| S002 | Stochastic | endpoint variance parity | ratio 0.80–1.25 |
| S003 | Stochastic | categorical/discrete TV distance | <=0.075 |
| S004 | Stochastic | unchanged RNG structure -> byte parity | exact SHA |
| P001 | Performance | disabled feature overhead | <=2% median |
| P002 | Performance | generalized non-energy overhead | <=3% median |
| P003 | Performance | >=6 predicates reduce class count >=16x | required |
| P004 | Performance | >=8 predicates construction speedup >=4x | target gate |
| P005 | Performance | no materialized exponential memory growth | monotonic bound |
| X001 | Robustness | ASan/UBSan on energy corpus | zero findings |
| X002 | Robustness | randomized mask oracle | 10k generated cases |
| X003 | Robustness | randomized pattern compiler oracle | 1k small graphs |
| X004 | Robustness | cache TSAN/concurrency stress | zero races |
