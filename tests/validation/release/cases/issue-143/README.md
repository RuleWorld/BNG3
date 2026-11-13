# Issue 143 Acceptance Suite

## Contract
- **Issue**: [#143](https://github.com/RuleWorld/BNG3/issues/143) B06: Complete the shared rate-law and local-function semantic contract
- **Acceptance checks**: `release-rates`, `release-rate-invalidation`, `release-capability-coverage-143`
- **Oracles**:
  - Closed-form analytical laws (pure-death hazard integral, Michaelis-Menten hyperbolic kinetics, Hill cooperative kinetics, Saturation kinetics, Arrhenius temperature dependence, mathematical builtins, IEEE-754 operators)
  - Pinned BNG2 (`RuleWorld/bionetgen@9601746f8884ed19ab2acea49fe87fc4660ace46`)
  - Native NFsim binary where applicable

## Semantic Guarantees
1. **Rate Law Families**:
   - `bngl.mass-action` & `bngl.ele`: Standard mass-action rate laws $k \cdot \prod [S_i]$ evaluated with exact stoichiometry.
   - `bngl.function` & `bngl.functionproduct`: Global and scoped functions evaluate dynamic expressions without caching stale values.
   - `bngl.mm`: Michaelis-Menten kinetics $v = \frac{V_{max} [S]}{K_m + [S]}$, and 4-argument free substrate form with quadratic root solver.
   - `bngl.sat`: Saturation kinetics $v = \frac{k_0 [S]}{K + [S]}$.
   - `bngl.hill`: Cooperative Hill kinetics $v = \frac{V_{max} [S]^n}{K_h^n + [S]^n}$.
   - `bngl.arrhenius`: Temperature/energy-dependent rates $k = A \exp(-E_a / (k_B T))$.
   - `bngl.reverse-rates`: Bidirectional rules split into forward and reverse reactions with correct independent rate expressions.
   - `bngl.statistical-rate-factors`: Proper symmetry and multiplicity factors on reaction rules with identical reactants.
   - `bngl.delay`: Reactions with fixed time delay preserving reactant initiation and completion semantics.

2. **Builtins and Operators**:
   - Constants `_pi` and `_e`, simulation `time`.
   - Transcendental, hyperbolic, and rounding functions: `exp`, `ln`, `log10`, `log2`, `abs`, `rint`, `sqrt`, `cos`, `sin`, `tan`, `asin`, `acos`, `atan`, `sinh`, `cosh`, `tanh`, `asinh`, `acosh`, `atanh`, `if`, `min`, `max`, `sum`, `avg`, `mratio`.
   - Table functions (`tfun`, `TFUN`): linear interpolation and flat clamping from inline and file-backed table sources.
   - Mathematical and boolean operators: `+`, `-`, `*`, `/`, `^`, `**`, `>`, `<`, `>=`, `<=`, `==`, `!=`, `~=`, `&&`, `||`, `!`, `~`.

3. **Dynamic Invalidation**:
   - Invalidation of cached rate values when parameters are modified dynamically via `setParameter`.
   - Continuous updating of rate laws depending on simulation time (`Time`).
   - Dynamic updating of rate laws depending on observables (`Molecules` / `Species`).
   - Strict rejection of stale-rate mutations by analytical comparators.
