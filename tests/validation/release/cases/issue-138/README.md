# Issue #138: Migrate Remaining Runtime Consumers to the Resolved Semantic Model

This directory contains the independent release acceptance suite for **Issue #138** (B01: Migrate remaining runtime consumers to the resolved semantic model).

## Acceptance Criteria

- `release-compiled-inputs`: Architecture dependency ratchet (`tools/check_architecture_dependencies.py`) and legacy inventory check (`tools/check_legacy_dependency_inventory.py`) enforce that no unauthorized runtime AST dependencies or execution-time re-parsing leaks into backend and lowered layers.
- `release-compiled-parity`: Every BNGL syntax inventory case compares generated networks and simulation trajectories with BNG2 and native NFsim after complete source AST destruction.
- `release-capability-coverage-138`: Complete independent evaluation of all 30 assigned capability inventory rows and 6 contract obligations against their named independent oracles.

## Covered Capability Inventory Rows

The 30 assigned capability inventory rows for Issue #138:
1. `bngl.model-blocks`: Delimited `begin model ... end model` block structures.
2. `bngl.parameters`: Parameter definitions and expressions.
3. `bngl.molecule-types`: Molecule type declarations with component site specifications.
4. `bngl.species-and-seed-species`: Initial species amounts and complex definitions.
5. `bngl.reaction-rules`: Rule definitions with kinetic rates and modifiers.
6. `bngl.observables`: Molecules and Species observables with weights and patterns.
7. `bngl.functions`: User-defined kinetic rate functions and mathematical expressions.
8. `bngl.compartments`: Spatial hierarchical compartment definitions.
9. `bngl.energy-patterns`: Free-energy pattern definitions for energy-based modeling.
10. `bngl.population-maps`: Structured population-mapping definitions.
11. `bngl.actions`: Standard action block declarations.
12. `bngl.simulation-protocols`: Multi-step action protocols (e.g. simulate followed by parameter updates).
13. `bngl.comments-and-line-continuations`: Comment lines (`#`) and line continuations (`\`).
14. `bngl.source-file-include-readmodel`: Secondary file inclusion (`readFile`, `include_model`).
15. `bngl.indexed-declarations`: Indexed block and element declarations.
16. `bngl.molecule-names`: Valid molecule alphanumeric naming conventions.
17. `bngl.site-names`: Component site naming conventions.
18. `bngl.internal-states`: Component internal state values (`~0`, `~1`, `~u`, `~p`).
19. `bngl.numeric-bonds`: Numeric bond indices (`!1`, `!2`).
20. `bngl.wildcard-bonds`: Wildcard bond notation (`!+`, `!?`).
21. `bngl.unbound-sites`: Explicit unbound site specifications.
22. `bngl.omitted-sites`: Implicit site omission in pattern matching.
23. `bngl.disconnected-patterns`: Multi-reactant disconnected patterns (`+`).
24. `bngl.molecule-and-pattern-labels`: Molecule and pattern labeling (`%label::`).
25. `bngl.compartment-annotations`: Molecule and species compartment prefixes (`@C:`).
26. `bngl.fixed-species`: Constant/clamped species ($ prefix).
27. `bngl.symmetric-identical-sites`: Homologous identical sites within a molecule type.
28. `bngl.integer-state-values`: Numeric integer states.
29. `bngl.empty-compartment-lists`: Empty or default compartment declarations.
30. `bngl.unnamed-rules`: Anonymous reaction rules without explicit rule names.

## Independent Oracles and Analytical Bounds

1. **Architecture Dependency Verification**:
   - `tools/check_architecture_dependencies.py`: Verifies that no forbidden `#include <ast/...>` or `#include <parser/...>` dependencies or re-parsing calls exist outside the explicit allowlist.
   - `tools/check_legacy_dependency_inventory.py`: Ensures exact alignment of legacy callers and migration targets.
2. **Post-AST-Destruction Parity**:
   - Tests instantiate models, compile them into native IR (`compile::Document` / `BioNetGenModel`), explicitly delete and destroy the source AST, and verify that network generation and simulation execution succeed with bit-for-bit parity or exact graph isomorphism (`compare.compare_net`).
3. **Golden BNG2 Benchmark Parity**:
   - Verified across canonical benchmark models (`simple_system`, `deleteMolecules`, `statfactor`, `localfunc`, `Haugh2b`, `Motivating_example_cBNGL`).
