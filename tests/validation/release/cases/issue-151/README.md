# Issue #151: Verified NFsim Physical-Unit Count-Rate Bridge

## Overview

This case establishes the independent release qualification for **Issue #151 (C06)**:
"Implement the verified NFsim physical-unit count-rate bridge."

In BioNetGen (BNGL), models with physical units require converting concentration-based macroscopic rates ($M \cdot s^{-1}$, $s^{-1}$, $M^{-1} s^{-1}$, etc.) to stochastic count rates (reactions per second per item combination) when simulating via particle-based network-free simulation (NFsim).

## Mathematical Foundations

### Rate Conversion Formulas

For an elementary reaction of molecularity $m$ in compartment volume $V$ [L] with Avogadro number $N_A$ [molecules/mol]:

1. **Zero-order synthesis** ($0 \to A$):
   $$k_{\text{count}} = k_{\text{phys}} \cdot N_A \cdot V \quad [\text{items} \cdot s^{-1}]$$
   Events follow a homogeneous Poisson process with intensity $\lambda = k_{\text{count}}$.
   At time $t$, the accumulated molecule count $N_A(t)$ follows:
   $$N_A(t) \sim \text{Poisson}(\lambda t)$$

2. **Unimolecular decay** ($A \to B$):
   $$k_{\text{count}} = k_{\text{phys}} \quad [s^{-1}]$$
   Unimolecular reactions are intrinsic first-order hazards, invariant to compartment volume $V$ and Avogadro number $N_A$.
   For $N_0$ initial molecules, survival probability $p(t) = e^{-k_{\text{count}} t}$.
   At time $t$, remaining molecules follow:
   $$N_A(t) \sim \text{Binomial}(N_0, p(t))$$

3. **Unimolecular inter-compartment transport** ($@\text{cell}:A() \to @\text{ec}:A()$):
   $$k_{\text{count}} = k_t \quad [s^{-1}]$$
   Cross-compartment transport requires validated positive 3D static compartment volumes for both source and destination.
   Particle conservation holds pathwise:
   $$N_{\text{cell}}(t) + N_{\text{ec}}(t) = N_0$$
   Source compartment molecules follow:
   $$N_{\text{cell}}(t) \sim \text{Binomial}(N_0, e^{-k_t t})$$

4. **Heterobimolecular combination** ($A + B \to C$):
   $$k_{\text{count}} = \frac{k_{\text{phys}}}{N_A \cdot V} \quad [\text{item}^{-1} s^{-1}]$$
   The state transition follows a pure-birth continuous-time Markov chain (CTMC).
   State transition probabilities $P(t) = \exp(Q t)$ are computed analytically via matrix exponential.

5. **Homodimer binding** ($A + A \to A_2$):
   $$k_{\text{count}} = 0.5 \cdot \frac{k_{\text{phys}}}{N_A \cdot V} \quad [\text{item}^{-1} s^{-1}]$$
   Statistical symmetry factor $1/2$ accounts for identical reactant pairs: $\binom{N_A}{2} = \frac{1}{2} N_A (N_A - 1)$.

### Statistical Error Control (DKW Inequality)

For empirical distribution function $F_n(x)$ over $n$ trajectories and true CDF $F(x)$:
$$P\left(\sup_x |F_n(x) - F(x)| > \epsilon\right) \le 2 \exp(-2 n \epsilon^2)$$
With $n = 200$ trajectories and significance level $\alpha = 0.005$:
$$\epsilon = \sqrt{\frac{\ln(2 / \alpha)}{2 n}} = \sqrt{\frac{\ln(400)}{400}} \approx 0.12239$$

## Acceptance Checks

- `release-nf-units`: Unit-annotated BNG3 models simulated with direct NFsim match independent analytical count laws across:
  - Zero-order physical synthesis
  - Unimolecular physical decay
  - Unimolecular physical transport across compartments
  - Bimolecular physical combination
- `release-unit-scaling`: Hand-derived Avogadro, volume, and molecularity scaling formulas verify exact rate conversion and reject perturbed variations:
  - Missing volume scaling ($V^0$)
  - Double volume scaling ($V^2$)
  - Inverted volume scaling ($1/V$)
  - Missing Avogadro factor ($N_A$)
  - Dimension mismatches between reaction molecularity and rate units (e.g. $[s^{-1}]$ for zero- or second-order).
- `release-obligation-151`: Verifies completeness of contract and obligations, refusal of missing or non-positive compartment volume context, and single application of the conversion bridge.
