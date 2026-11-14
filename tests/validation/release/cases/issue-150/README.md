# Issue #150: Particle-Population Hybrid Execution

## Overview

This case adds bounded tests toward release qualification for **Issue #150 (C05)**:
"Complete or disposition hybrid particle-population execution."

BNG3 provides hybrid generation, NFcore execution and separate NFnext primitives:
1. **Hybrid Model Generator**: `generate_hybrid_model` parses population maps, specializes reaction rules into particle/population forms, handles reaction-center multiplicities and symmetry ratios, and writes hybrid BNGL models (`cpp/engine/HybridModelGenerator.cpp`).
2. **Action Dispatch & Execution Options**: Supports all canonical arguments (`actions`, `execute`, `overwrite`, `prefix`, `suffix`, `verbose`) and routes hybrid execution through population-aware simulation engines (`cpp/actions/ActionDispatch.cpp`).
3. **Hybrid State & Discrete Combinatorics**: Employs exact combinatorial falling-factorial propensities, 64-bit atomic population updates with underflow rollback, and particleization / departicleization threshold migrations (`cpp/nfnext/include/nfnext/hybrid_state.hpp`).
4. **Fail-Closed Boundaries**: Distinguishes representation from execution; unhandled constructs (e.g. compartment-scoped hybrid transformations) are refused fail-closed rather than silently approximated.

## Mathematical Oracles & Analytical Laws

The formula-only tests in this package check oracle arithmetic; they do not run
product trajectories and must not be counted as execution evidence. The separate
`tests/validation/test_hybrid_execution.py` suite does compare generated NFcore
HPP trajectories with pinned native NFsim and independent laws. Preserve that
bounded evidence, including the compartment comparison's stated oracle limits.
NFnext still refuses population-map execution, and dynamic threshold changes
are explicitly outside the aggregate receipt. Full #150 acceptance remains open.

Independent analytical continuous-time Markov chain (CTMC) laws:

### 1. Unimolecular Conversion & Mass Conservation
For a single-molecule conversion $B \to A \to A_{\text{pop}}$ with $N_0$ initial particles:
$$\mathbb{E}[B(t)] = N_0 e^{-k_{\text{make}} t}, \quad \mathbb{E}[A(t)] = N_0 (1 - e^{-k_{\text{make}} t})$$
$$\forall t \ge 0: \quad A_{\text{total}}(t) + B_{\text{total}}(t) = N_0$$

### 2. Whole Dimer Population Conversion & Multiplicity
For dimer degradation $A(x!1).A(x!1) \to 2 A(x)$ mapped to population species $D_{\text{pop}}$:
$$\mathbb{E}[\text{Dimer}(t)] = N_{\text{dimer}} e^{-k_{\text{off}} t}$$
$$\forall t \ge 0: \quad A_{\text{units}}(t) = 2 \cdot N_{\text{dimer}}$$

### 3. Reversible Particle-Population Conversion Cycle
For reversible interconversions $A_{\text{pop}} \underset{k_r}{\overset{k_f}{\rightleftharpoons}} B$ starting from $N_0$ particles of $A$:
$$\mathbb{P}(B(t)) = \frac{k_f}{k_f + k_r} \left(1 - e^{-(k_f + k_r)t}\right)$$
$$B(t) \sim \text{Binomial}\left(N_0, \mathbb{P}(B(t))\right)$$
$$\forall t \ge 0: \quad A_{\text{total}}(t) + B_{\text{total}}(t) = N_0$$

## Acceptance Checks

- `release-hybrid`: BNG2 hybrid output executed by native NFsim matches BNG3 hybrid distributions and observables within $4.0\sigma$ across 200 trajectories per engine.
- `release-hybrid-conservation`: Independent analytic conversion/mass conservation and multiplicity laws hold in mixed particle/population cases.
- `release-capability-coverage-150`: The test in this package validates contract registration only. The separate execution suite covers its declared cases and limitations; neither establishes all remaining #150 work clauses.
