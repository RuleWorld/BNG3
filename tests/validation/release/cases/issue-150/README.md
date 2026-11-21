# Issue #150 hybrid execution acceptance

The live execution suite is `tests/validation/test_hybrid_execution.py`.
The contract lists the required runtime case and oracle identities.
The release recorder consumes the suite results and the SHA-256 digests of
the retained model inputs and trajectories.

| Work clause | Production entry point | Executed cases and independent oracles |
| --- | --- | --- |
| Whole-complex conversion, count updates, and reverse conversion at the source rates | `generate_hybrid_model`, embedded NFcore, and NFnext through `BioNetGenModel.simulate` | Single-particle conversion, whole-dimer dissociation and reversible cycles against BNG2-generated HPP run by pinned native NFsim. Exact molecule conservation and binomial laws check multiplicity and conversion rates. |
| Mapped rates, observables, conservation, compartments, protocol, and initialization | Public `simulate(method="nfcore")` and `simulate(method="nfnext")`, and BNGL `simulate_protocol` dispatch to NFcore | Pre-run rate assignment, absolute clock initialization, and joined stages against pinned native NFsim and exact piecewise binomial laws. Compartment-local graph and count preservation, observable continuity, and reverse conversion use an independent location-specific law. The BNGL action case checks BNG2's final-state carry semantics and exact boundary and mass identities. |
| Actual hybrid trajectories and laws, population thresholds, and conversion cycles | Generated HPP on both backends and direct NFnext population maps | Reversible CTMC, observable cutoff and absolute-rate conversion against pinned native NFsim and exact marginal laws. The action option fixtures use pinned BNG2 for defaults, outputs and errors. |

Pinned BNG2 does not transform compartment models. The compartment
single-stage cases use analytic laws and a native NFsim consumer for the
exportable case. The compartment stage case uses independent analytic laws.

The phase change in the native two-state stage case uses an exact sampled
boundary. The two observed counts fully determine that case's Markov state.
A second native process starts from those counts and a distinct seed. This
avoids the pinned native RNF driver's clock overshoot between sequential
`sim` commands.

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
- `release-capability-coverage-150` requires every assigned row to have affirmative execution evidence with its named independent oracle. The consuming report records the tested source revision.
