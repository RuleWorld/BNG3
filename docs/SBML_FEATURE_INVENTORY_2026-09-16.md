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
| Function definitions and MathML | Lowered for supported subset | Arithmetic, piecewise, common functions, time, and SBML numeric constants are translated; infinity/NaN/factorial/gcd/lcm and selected rational forms carry explicit approximation or support warnings. |
| Events | Parsed and annotated | Event structure is retained in the intermediate model and review block; event execution is not part of the current continuous-time simulation path. |
| Notes, RDF/CVTerms/MIRIAM, SBO, `metaid` | Preserved in intermediate model and reported | The BNGL comment block is non-kinetic provenance/classification, not an executable metadata channel. |
| SBML Multi v1 Release 2 | Lowered for validated representable structures | Species types, binding sites, component indexes, bonds, species patterns, compartment references, numeric values, intra-species reactions, and product component maps are handled where one BNGL representation is valid; invalid or multi-layer cases fail closed. |
| C++ SBML writer table functions | Lowered | Finite inline BNGL `tfun` arrays become Core MathML piecewise expressions with step/linear interpolation and endpoint clamping. File-backed or malformed tables remain unsupported. |

## Package inventory

| Package family | Current classification |
| --- | --- |
| `multi` | Parsed and lowered for the representable subset above; independent NFsim parity is still pending. |
| `layout`, `render`, `groups`, `req` | Detected and reported as non-mathematical package metadata; not imported into kinetic state. |
| `comp`, `fbc`, `qual`, `spatial`, `arrays`, `distrib`, `dyn` | Detected with explicit dropped/unsupported diagnostics. The current path does not silently flatten composition, flux-balance, logical, spatial, array, uncertainty, or dynamic-agent semantics. |

## Corpus evidence

The current pinned SBML Test Suite report selected 1,923 cases: 752 passed, 1,171 were explicitly unsupported, 0 failed, and 0 timed out. Its warning inventory includes stoichiometry, units, events, MathML, assignment rules, algebraic rules, fast reactions, conversion factors, and `comp`/`distrib`/`fbc` package diagnostics.

The current pinned curated BioModels flat report selected all 1,096 inventory records. It classified 580 as passed, 468 SBML records as unsupported, 32 as failed at the configured numerical comparison stage, and 3 as timed out. The two-mode report additionally exposes atomized-only parser failures and timeouts. These results are current surface evidence, not a release-readiness claim.

The remaining convergence work is to expand the explicitly unsupported semantic families, triage the curated numerical failures/timeouts, and provide an independently built `NFSIM_BIN` for the NFsim oracle.
