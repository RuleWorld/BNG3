# BNG3 SBML feature inventory

Date: 2026-09-16

This is a support classification for the current modern Atomizer and C++ SBML writer path. `Preserved` means retained in the intermediate model; it does not imply executable BNGL or numerical equivalence. `Lowered` means emitted through an explicit BNGL/Core MathML representation. `Explicitly unsupported` means the validator records the limitation and fails closed for affected semantic checks.

| SBML surface | Current classification | Boundary |
| --- | --- | --- |
| Model identity, level/version, units, conversion factor, constraints count | Preserved | Source identity and counts are retained; unsupported constraint semantics are not invented. |
| Compartments and hierarchy | Preserved / lowered | Core dimensions, size, units, constant, outside, and Multi type markers are parsed; unsupported hierarchy packages are not flattened. |
| Species and species references | Preserved / lowered | Initial amount/concentration, units, boundary/constant flags, charge, species type, conversion factor, stoichiometry, and annotations are represented. Nonnegative fixed integer stoichiometry is required for executable BNGL. |
| Parameters and local parameters | Preserved / lowered | Local scope is retained; references that escape reaction scope are explicitly unsupported. |
| Reactions and kinetic laws | Lowered | Reversible, modifiers, compartments, conversion factors, standard expressions, and supported MathML are emitted to the current Core writer. |
| Rules and initial assignments | Preserved / lowered | Assignment and rate rules are represented; algebraic rules are reported as dropped because BNGL has no equivalent DAE constraint. |
| Function definitions and MathML | Lowered for supported subset | Arithmetic, piecewise, common functions, time, SBML numeric constants, canonical inverse-trigonometric operators, exact e-notation, and integer-domain factorial are translated; infinity/NaN/gcd/lcm and selected unsupported forms carry explicit approximation or support warnings. |
| Events | Lowered for fixed-time constant subset; annotated otherwise | Constant-valued time triggers and assignments become explicit BNGL action phases; state-dependent, delayed-dynamic, and non-constant events remain fail-closed. |
| Notes, RDF/CVTerms/MIRIAM, SBO, `metaid` | Preserved in intermediate model; opaque payload preserved by modern SBML export path | Ordinary executable BNGL remains a non-kinetic classification path; payload equality is checked after SBML reimport. |
| COMBINE/OMEX manifest selection | Preserved as archive provenance | Manifest member, selected SBML member, candidates, normalized content entries, and selection warnings are exposed; SED-ML is not executed. |
| SBML Multi v1 Release 2 | Lowered for validated representable structures | Species types, binding sites, component indexes, bonds, species patterns, compartment references, numeric values, intra-species reactions, and product component maps are handled where one BNGL representation is valid; invalid or multi-layer cases fail closed. |
| C++ SBML writer table functions | Lowered | Finite inline BNGL `tfun` arrays become Core MathML piecewise expressions with step/linear interpolation and endpoint clamping. File-backed or malformed tables remain unsupported. |

## Package inventory

| Package family | Current classification |
| --- | --- |
| `multi` | Parsed and lowered for the representable subset above; independent NFsim parity is still pending. |
| `layout`, `render`, `groups`, `req` | Detected and reported as non-mathematical package metadata; not imported into kinetic state. |
| `comp`, `fbc`, `qual`, `spatial`, `arrays`, `distrib`, `dyn` | Detected with explicit dropped/unsupported diagnostics. The current path does not silently flatten composition, flux-balance, logical, spatial, array, uncertainty, or dynamic-agent semantics. |

## Corpus evidence

Post-change SBML Test Suite status is recorded in `/private/tmp/bng3-sbml-suite-post-factorial.json`: 1,923 selected cases yielded 687 passed, 1,235 explicitly unsupported, 1 failed, and 0 timed out. The unsupported cases have 1/2/3/4 causes with cardinalities 705/445/79/6; the largest pairwise overlaps are algebraic-rules+constraints (117), events+no-state (74), `comp`+no-state (64), events+`distrib` (61), and constraints+stoichiometry (40). The post-change cause projection for `{events, MathML, local scope, species assignment, constraints}` touches 836 unsupported records, with 455 target-only and 381 retaining an outside cause. The older detailed cause paragraph below is retained for historical comparison; the post-change JSON is authoritative.

The current pinned SBML Test Suite report selected 1,923 cases: 687 passed, 1,235 were explicitly unsupported, 1 failed, and 0 timed out. Of the 688 cases that reached export/reimport, 597 carried source metadata and all 597 payloads matched exactly; 91 had no source metadata. The gate treats semantic `approximated` warnings as unsupported while allowing informational unit-scale notes. Its warning inventory includes stoichiometry, units, events, MathML, assignment rules, algebraic rules, fast reactions, conversion factors, and `comp`/`distrib`/`fbc` package diagnostics.

The current pinned curated BioModels flat report selected all 1,096 inventory records. It classified 591 as passed, 459 SBML records as unsupported, 31 as failed at the configured numerical comparison stage, and 2 as timed out; all 604 source-bearing flat runs that reached export/reimport had exact metadata-payload matches. The earlier two-mode report predates the semantic-gate and event corrections; the post-gate isolated two-mode refresh did not reach a terminal report and remains an open evidence item. These results are current surface evidence, not a release-readiness claim.

The final machine-readable reports are `/private/tmp/bng3-sbml-suite-post-factorial.json` and `/private/tmp/bng3-curated-biomodels-flat-final-audited.json`. Each unsupported record retains `unsupported_reason` and normalized `unsupported_causes`; the report also contains exact record references for cause intersections. Cause totals are non-exclusive. In the suite, the unsupported records have 1/2/3/4 causes with cardinalities 705/445/79/6. The five largest pairwise overlaps are algebraic-rules+constraints (117), events+no-state (74), `comp`+no-state (64), events+`distrib` (61), and constraints+stoichiometry (40). The suite's 217 stoichiometry records split into 188 dynamic/`stoichiometryMath`, 23 constant noninteger, and 6 constant negative; the curated SBML-only report's 55 split into 52 constant noninteger, 2 dynamic/`stoichiometryMath`, and 1 integer above the BNGL expansion limit.

These are explicit current boundaries, not claims that every affected family is fundamentally impossible for BNG3. The likely implementation roadmap is: compiler/preprocessing work for MathML, local scope, participant edge cases, much of species assignment and fixed stoichiometry; runtime scheduling/assertion work for events and constraints; flattening for `comp`; backend-specific work for dynamic/continuous stoichiometry, `distrib`, and DAE-like algebraic rules; and a distinct optimization backend for `fbc`. The exact record IDs and reasons remain authoritative in the JSON reports.

For the proposed first compiler/runtime batch `{events, MathML, local scope, species assignment, constraints}`, the cause-set projection touches 836 of 1,235 suite unsupported records and leaves 455 target-only records; 381 still carry an outside cause. The curated SBML projection touches 399 of 461 unsupported records and leaves 378 target-only; 62 still carry an outside cause. This is an upper-bound prioritization measure, not a predicted pass count.

The remaining convergence work is to expand the explicitly unsupported semantic families, triage the curated numerical failures/timeouts, and provide an independently built `NFSIM_BIN` for the NFsim oracle.

The 2026-09-16 factorial/e-notation patch is included in the post-change suite aggregate: 14 cases moved to pass, 15 left the explicitly unsupported bucket, and one factorial-containing discontinuous rate-rule case is now recorded as a genuine failure. The curated report remains pre-change flat-only evidence; no post-change two-mode curated result is claimed.
