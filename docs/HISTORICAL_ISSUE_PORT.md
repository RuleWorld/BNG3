# BNG3 port of selected BioNetGen issue work

This page records the BNG3 implementation and compatibility decisions for the
issues selected from [RuleWorld/bionetgen PR #334](https://github.com/RuleWorld/bionetgen/pull/334).
BNG3's current source and runtime behavior are authoritative for changes in
this repository. An issue report is a reproduction lead, not proof that its
proposed semantics match the supported model language.

## Implemented or locked by regression tests

| Issue | BNG3 result |
| --- | --- |
| [#265](https://github.com/RuleWorld/bionetgen/issues/265) | PSA reaction selection now uses a Fenwick tree, selecting in O(log R) and updating only reactions whose propensities changed. A competing-channel regression checks the selection distribution. The two upstream reaction-order fixtures run as PSA models in about 0.061–0.064 s after warm-up on this checkout. |
| [#214](https://github.com/RuleWorld/bionetgen/issues/214) | The upstream 481 KB model is retained as a parser stress fixture. Its three invalid `nan` compartment sizes are normalized in memory to `1.0`; BNG3 parses the model and confirms the 16-product `R_ENTCS` rule, including nine `Hpl` and six `AMP` products. The regression completes in about 0.26 s locally. |
| [#165](https://github.com/RuleWorld/bionetgen/issues/165) | The linked Dropbox model is unavailable. A synthetic sixfold-symmetric receptor/PI complex now exercises canonicalization. This does not claim to reproduce the missing full model. |
| [#29](https://github.com/RuleWorld/bionetgen/issues/29) | With `continue=>1`, omitted `t_start`, and explicit `t_end`, BNG3 now treats `t_end` as a duration and advances the end time from the prior run. Explicit sample times remain absolute. The action regression verifies 0–100 followed by 100–110, including an intervening `setConcentration`. |
| [#277](https://github.com/RuleWorld/bionetgen/issues/277) | SBML output now lowers `Sat`, `MM`, and `Hill` macros to MathML instead of emitting an unresolved macro identifier. The regression covers each macro and checks the reactant factors. The report's request to remove the catalyst factor conflicts with BNG2 `RateLaw.pm::toMathMLString()` and BNG3 `OdeIntegrator.cpp`, both of which include additional reactants for `Sat`/`Hill`; `MM` uses both substrate and enzyme. This change preserves those runtime semantics. A catalyst-free macro definition needs a separate compatibility decision. |
| [#122](https://github.com/RuleWorld/bionetgen/issues/122) | Atomizer dependency ordering is covered for an initial assignment that references a parameter defined by an assignment rule, regardless of source declaration order. |
| [#208](https://github.com/RuleWorld/bionetgen/issues/208) | The default absolute ODE tolerance is now `1e-12` across C++, Python, scan, sensitivity, and CLI entry points; explicit caller values remain unchanged. The upstream `IntegratorAccuracy` fixture compares all three observables at 1,001 times against a `1e-13` reference and stays within 0.1% relative error. |
| [#232](https://github.com/RuleWorld/bionetgen/issues/232) | The issue's exact compartment chain is covered. BNG3 generates both seeded directions; it does not reproduce the BNG2 2.6.0 one-direction output. |
| [#246](https://github.com/RuleWorld/bionetgen/issues/246) | A parentless `EC`/`mem` model remains nonadjacent and generates no cross-compartment bond reaction. BNG3 does not invent a parent relationship. |
| [#160](https://github.com/RuleWorld/bionetgen/issues/160) | An SSA action regression checks `output_step_interval=>2` output cadence and final-state reporting at a five-event stop. |
| [#175](https://github.com/RuleWorld/bionetgen/issues/175) | The validation suite already exercises `parameter_scan` across ODE, parallel, NF, and protocol paths. This branch adds issue-specific upstream fixtures and focused tests for continuation, integrator accuracy, output cadence, symmetry, and PSA stress. |
| [#54](https://github.com/RuleWorld/bionetgen/issues/54) | BNG3 accepts `**`, `~=`, `!`, and `~` in expressions; a parser/evaluator regression locks those spellings. |
| [#86](https://github.com/RuleWorld/bionetgen/issues/86), [#105](https://github.com/RuleWorld/bionetgen/issues/105), [#111](https://github.com/RuleWorld/bionetgen/issues/111) | A NET reader regression verifies integer species references and a compound reaction-rate expression survive parsing as authored. The existing `readNetwork` action test covers loading and rewriting a `.net` file; no broader multi-file `simulate(netfile=...)` contract is claimed. |
| [#124](https://github.com/RuleWorld/bionetgen/issues/124) | A parser/network regression places rules and seed species before molecule types and parameters, then checks forward parameter evaluation and network generation. |
| [#216](https://github.com/RuleWorld/bionetgen/issues/216) | Inline parameter comments now survive BNGL parsing and NET writing. `NetReader` also exposes parameter comments in its parse result. |

## Existing support and remaining parity contracts

| Issue | Current boundary |
| --- | --- |
| [#335](https://github.com/RuleWorld/bionetgen/issues/335), [#135](https://github.com/RuleWorld/bionetgen/issues/135) | Units are implemented in BNG3, as confirmed by the user. This branch does not duplicate the units subsystem; the existing Core, Multi, reader, and dimensional-analysis tests remain the contract. Direct NFsim's unit-bearing-model limitation remains documented in `docs/BNG3_UNITS.md`. |
| [#144](https://github.com/RuleWorld/bionetgen/issues/144) | BNG3 writes SBML Level 3 Version 2 with Core and Multi support. The pinned SBML Test Suite import/round-trip gate covers 1,923 cases: 687 pass, 1,235 are explicitly unsupported, and 1 fails; 597 source-metadata payloads round-trip exactly. Curated BioModels round-trip reports also exist. These are bounded import/round-trip checks, not full simulation or schema conformance; remaining unsupported semantics and curated failures/timeouts stay visible in `docs/SBML_CONVERGENCE_STATUS_2026-09-16.md`. |
| [#94](https://github.com/RuleWorld/bionetgen/issues/94) | BNG3 keeps dedicated typed `Sat`/`MM`/`Hill` lowering rather than rewriting these laws to general functions. SBML emission is covered above; broader backend parity remains separate. |
| [#128](https://github.com/RuleWorld/bionetgen/issues/128) | The modern Atomizer already lowers SBML `true`, `false`, and `xor`; its parser/writer path also handles factorial. Those conversions remain scoped to Atomizer output and do not promise that every imported expression can run on every simulator backend. |
| [#98](https://github.com/RuleWorld/bionetgen/issues/98) | NET numeric indices remain part of the interchange format and are preserved; their removal requires a versioned format migration. |
| [#131](https://github.com/RuleWorld/bionetgen/issues/131) | BNG3's public model input is BNGL into the canonical AST; BNG-XML is an export format used by the NFsim compatibility bridge. The legacy Python XML parser serves Atomizer utilities, not a general BNG-XML-to-AST API. Adding that importer needs a format/version and supported-element contract, so this branch makes no broader import claim. |
| [#132](https://github.com/RuleWorld/bionetgen/issues/132), [#162](https://github.com/RuleWorld/bionetgen/issues/162) | Finite-network generation now fingerprints reactant and product local-observable counts by scope name. `NetWriter` lowers nested `FunctionProduct` expressions, including the issue #132 dissociation example's `if`/function nesting, to per-reaction rates consumed by ODE and NET output. Direct NFsim `FunctionProduct` remains reactant-scoped; product-side local evaluation is not claimed there. The finite-network evaluator rejects unsupported or time-dependent forms explicitly. |
| [#58](https://github.com/RuleWorld/bionetgen/issues/58) | Zero-order synthesis works, but default-state products and tagged copy-constructor semantics from the issue remain unsupported. They need explicit language/API compatibility rules before extension. |
| [#59](https://github.com/RuleWorld/bionetgen/issues/59) | `DeleteMolecules` is supported. Making it the default or adding `DeleteComplex` changes established degradation behavior, so this branch leaves the compatibility decision open. |

## Held as explicit scope or compatibility decisions

| Issue | Decision |
| --- | --- |
| [#119](https://github.com/RuleWorld/bionetgen/issues/119) | Dynamic compartment volume changes require solver coupling and concentration-versus-amount semantics. Not added as a local patch. |
| [#116](https://github.com/RuleWorld/bionetgen/issues/116) | The spatial/Flow `*` wildcard has no sufficiently defined matching contract. |
| [#260](https://github.com/RuleWorld/bionetgen/issues/260) | The report proposes a narrower rule for wildcard bonds and multiple bonds. Broader validation behavior needs a compatibility contract and migration fixtures. |
| [#26](https://github.com/RuleWorld/bionetgen/issues/26) | Live fixed-species mutation needs an explicit simulator API and cache-update contract. |
| [#88](https://github.com/RuleWorld/bionetgen/issues/88) | Non-finite rates need one language-wide parsing and runtime policy before implementation. |
| [#93](https://github.com/RuleWorld/bionetgen/issues/93), [#99](https://github.com/RuleWorld/bionetgen/issues/99) | Syntax deprecations require a usage inventory, warning period, and replacement guidance. Canonical output and legacy parsing remain separate concerns. |
| [#170](https://github.com/RuleWorld/bionetgen/issues/170) | Models2 curation needs named missing examples and an owner; no model set is inferred from the issue alone. |
