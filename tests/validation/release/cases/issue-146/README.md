# Issue #146: Independent Direct-NFsim and XML-Path Qualification

## Overview

This case establishes the independent release qualification for **Issue #146 (C01)**:
"Expand independent direct-NFsim and XML-path qualification."

BNG3 provides two distinct construction paths to initialize network-free particle simulations with NFsim:
1. **Direct AST Path**: Direct in-memory translation from BNG3's internal AST / CompiledModel representation directly into NFcore `System`, `ReactionClass`, `MoleculeType`, and `Observable` instances (`cpp/nfsim/NFinput/NFinput_fromAst.cpp`).
2. **In-Memory XML Compatibility Path**: Canonical XML emission followed by DOM-based NFsim system initialization (`cpp/nfsim/NFinput/NFinput.cpp`).

Under fixed seeds and identical model semantics, both construction routes must achieve bit-for-bit exact pathwise reproducibility (`rtol = 0.0, atol = 0.0`).

## Qualified Capabilities

### 1. BNGL Observable Semantics
- `bngl.molecules-observables`: Count total matches of a pattern across all complexes.
- `bngl.species-observables`: Count distinct chemical species (complexes) containing a pattern.
- `bngl.species-count-equality`: Filter complexes with exact molecule count (e.g. `Species S_eq A()==1`).
- `bngl.species-count-greater-than`: Filter complexes with molecule count exceeding a threshold (e.g. `Species S_gt A()>1`).
- `bngl.multiple-pattern-terms`: Observables matching multiple patterns simultaneously.
- `bngl.observable-coefficients`: Weighted arithmetic combination of species in observable definitions.
- `bngl.local-molecule-scope`: Molecule-scoped local functions.
- `bngl.local-species-scope`: Complex- and species-scoped local functions.

### 2. NFsim Execution Options (42 options)
- System and execution modes: `-xml`, `-sim`, `-o`, `-oSteps`, `-oTimes`, `-eq`, `-seed`.
- Performance and limits: `-utl`, `-gml`, `-maxcputime`, `-profile`.
- Algorithmic controls: `-notf`, `-nocslf`, `-cb`, `-bscb`, `-connect`, `-walk`, `-test`.
- Logging and output formatting: `-v`, `-b`, `-csv`, `-dump`, `-ogf`, `-printconnected`, `-printmoltypes`, `-printrxncounts`, `-rxnlog`, `-logbuffer`, `-trackconnected`, `-trackrxnnum`.
- CLI info and help: `-h`, `-help`, `-version`, `-logo`, `-rnf`, `-rtag`, `-agentcell`, `-rm`, `-rulemonkey`, `-ss`, `-oec`, `-i`.

### 3. Statistical Verification (DKW Inequality)
Stochastic trajectory ensembles are validated against analytical stochastic laws (e.g. Poisson arrival for synthesis, Binomial distribution for unimolecular decay):
$$P\left(\sup_x |F_n(x) - F(x)| > \epsilon\right) \le 2 \exp(-2 n \epsilon^2)$$
With $n = 200$ trajectories and $\alpha = 0.005$, $\epsilon \approx 0.12239$.

## Acceptance Checks

- `release-nfcore`: Direct and XML construction routes match bit-for-bit on canonical models (`simple_system`, `tlbr`, `motor`, `localfunc`). Observable semantics and CLI flags execute cleanly.
- `release-nfcore-statistics`: Prescribed seed/sample/error-control manifest passes distributional comparisons against analytical continuous-time Markov chain laws without tolerance relaxation.
- `release-capability-coverage-146`: Complete verification of all 50 assigned capability rows.
