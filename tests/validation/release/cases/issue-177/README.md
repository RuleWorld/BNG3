# Issue 177: Independent qualification of barrier and reservoir energy extensions

This directory contains the independent qualification suite for **Issue #177** (Capability rows `energy.barriers` and `energy.reservoirs`), covering:
- `release-barrier-energy`: analytic transition rates and detailed-balance identities pass for barrier fixtures.
- `release-reservoir-energy`: independent cycle affinity/current and stationary distribution checks pass under driven protocols.
- `release-capability-coverage-177`: complete independent evaluation of all assigned inventory rows (`energy.barriers` and `energy.reservoirs`).

## Background and Semantics

The BNG3 nonequilibrium energy extensions generalize Arrhenius rate laws in energy-extended BNGL (eBNGL) to include:
1. **Barrier patterns** (transition-state energy contributions $B$).
2. **Driving reservoirs** (signed chemical work $W$ on reversible transitions).

### Rate Laws

For an Arrhenius rule $A \rightleftharpoons B$ with activation barrier $E_a$, transition-state barrier $B$, ground-state free energy change $\Delta G = G_B - G_A$, signed driving reservoir work $W$, transition coefficient $\phi \in [0, 1]$, and thermal scale $RT$:

$$k_f = \exp\left[-\frac{E_a + B + \phi \cdot (\Delta G - W)}{RT}\right]$$
$$k_r = \exp\left[-\frac{E_a + B + (\phi - 1) \cdot (\Delta G - W)}{RT}\right]$$

### Key Thermodynamic and Kinetic Theorems

1. **Barrier cancellation in rate ratios (Detailed Balance Preservation)**:
   $$\frac{k_f}{k_r} = \exp\left[-\frac{\Delta G - W}{RT}\right]$$
   When $W = 0$, $k_f / k_r = \exp(-\Delta G / RT)$. The barrier $B$ enters identically into both forward and reverse activation energies and **cancels exactly** in the equilibrium constant. A barrier alters the transition timescale (catalysis when $B < 0$, kinetic obstruction when $B > 0$) without altering the thermodynamic equilibrium distribution.

2. **Cycle Affinity under Driving Reservoir Work**:
   For any closed cycle of reversible transitions $1 \to 2 \to \dots \to n \to 1$ with state energies $G_i$ (where $\sum_{\text{cycle}} \Delta G = 0$):
   $$\mathcal{A}_{\text{cycle}} = RT \sum_{e \in \text{cycle}} \ln \frac{k_e^+}{k_e^-} = \sum_{e \in \text{cycle}} W_e$$
   - When $\sum W_e = 0$, $\mathcal{A}_{\text{cycle}} = 0$, satisfying Kolmogorov's criterion for detailed balance and microscopic reversibility.
   - When $\sum W_e \neq 0$, detailed balance is broken, generating a non-zero cycle affinity $\mathcal{A}_{\text{cycle}} = \sum W_e$ and driving the system into a **Nonequilibrium Steady State (NESS)** with non-zero steady-state cycle current $J_{\text{cycle}} > 0$.

3. **Matrix Tree Theorem / King-Altman NESS Stationary Distribution and Flux**:
   For a 3-state cycle $1 \rightleftharpoons 2 \rightleftharpoons 3 \rightleftharpoons 1$, the exact stationary probabilities $p^* = (p_1^*, p_2^*, p_3^*)^T$ satisfy:
   $$p_1^* = \frac{k_{21} k_{31} + k_{23} k_{31} + k_{32} k_{21}}{\Sigma}$$
   $$p_2^* = \frac{k_{12} k_{32} + k_{13} k_{32} + k_{31} k_{12}}{\Sigma}$$
   $$p_3^* = \frac{k_{13} k_{23} + k_{12} k_{23} + k_{21} k_{13}}{\Sigma}$$
   where $\Sigma$ is the sum of spanning-tree weights rooted at each state.
   The net steady-state cycle flux is:
   $$J_{\text{cycle}} = \frac{k_{12} k_{23} k_{31} - k_{21} k_{32} k_{13}}{\Sigma} = \frac{k_{21} k_{32} k_{13} \left(\exp(\mathcal{A}_{\text{cycle}}/RT) - 1\right)}{\Sigma}$$

## Fail-Closed Policies and Gating

- **Feature Gate**: Gated by `BNG_NFSIM_GENERAL_ENERGY`. When unset or `"0"`, both network generation (`NetWriter`) and direct NFsim (`simulate_nf`) reject barrier patterns and reservoir work with explicit diagnostics.
- **Export Guard**: Exporters that cannot represent energy-derived rate laws (`io::requireNoEnergySemantics()`, e.g., SBML, MATLAB, LaTeX, MCell) fail closed with `RuntimeError` rather than emitting silent approximations.
- **Input Validation**: Non-finite barriers (NaN/Inf), barriers without energy patterns, compound multi-site transformations, and non-Arrhenius `driven_by` annotations are rejected during AST normalization and compilation.
