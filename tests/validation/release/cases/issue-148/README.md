# Issue #148 Release Case Package

**Closure audit (2026-11-14): incomplete acceptance.** The production route now includes modifier/filter and compartment support; scaffold/genome examples were added. Energy, units and unlowered populations still refuse; added scaffold/genome examples do not replace full pinned-native corpus comparisons and shared population/lattice/protocol semantics. Contract membership is not execution coverage. See docs/CURRENT_PROGRESS.md for the assessed revision and retained evidence.

**Issue Title**: C03: Qualify a complete model-to-NFnext execution boundary
**Tracking Issue**: #148

---

## 1. Overview and Architecture

This package checks a bounded model execution subset of **NFnext** directly from the production `CompiledModel` representation (`cpp/nfnext/src/from_bng.cpp:executeFromBioNetGen`).

This is not complete `nfnext.full` acceptance. Required families remain refused
(see item 7 below), and elementary/pure-death comparisons and bounded graph
examples do not replace the required scaffold/genome/full network-free corpus.
The contract-registration test checks metadata, not row-level execution.
Keep #148 open until its full live contract passes on main with consumed evidence.

The production NFnext execution loop carries:
1. **Model Initialization**: Bounded static integer seed populations, stateful components, and complex multi-molecule seed species are loaded into `GenericGraphState`.
2. **Observables Registration**: `Molecules` and `Species` observables are tracked and evaluated over the particle graph.
3. **Rate Evaluation**: Elementary parameter rates, dynamic observable-dependent rate functions, and `TotalRate` modifiers are compiled and evaluated.
4. **Embedding Enumeration & Filters**: `GenericMatcher` discovers pattern embeddings in the graph state, handling interchangeable symmetric reactant combinations ($\binom{N}{2}$ for duplicate pairs), `MatchOnce` symmetry suppression, and `include_reactants`/`exclude_reactants` filters.
5. **Discrete-Event Simulation**: Continuous-time Markov chain progression via exact SSA waiting-time sampling and propensity-weighted discrete rule choice using `CounterRng`.
6. **Graph Transformations**: In-place particle graph updates (state changes, bond creation, unbinding, synthesis, degradation, whole-complex deletion, compartment transport, and `MoveConnected`).
7. **Corpus Coverage**: Elementary CTMC ensembles, bimolecular binding/unbinding, symmetric homodimer combinations, pre-formed complex seed species, multi-state signaling cascades, linear polymer elongation, multi-site scaffold recruitment, and gene expression/autoregulatory genome circuits.
8. **Strict Fail-Closed Boundaries**: Unsupported constructs (un-lowered population maps requiring `generate_hybrid_model`, energy patterns, physical units, wildcard seed bonds) raise an explicit `RuntimeError` fail-closed rather than approximating semantics.

---

## 2. Independent Oracles

- **Pure-Death CTMC Analytical Law**: Unconverted particle counts follow $\text{Binomial}(N_0, \exp(-k \cdot t))$. Ensembles of 64 runs must match the analytical mean within $4.0 \cdot \text{SE}$ and discriminate against mutated rate laws by $> 4.0 \cdot \text{SE}$.
- **Pinned Native NFsim**: Direct XML conversion and execution using the locked native NFsim binary (`9b00d42f`), compared via two-sample Kolmogorov-Smirnov test and two-sample Hoeffding mean bounds.
- **Algebraic Mass Conservation**: Invariant checks confirm exact molecule conservation ($\sum A = A_0$) across binding and unbinding transformations.

---

## 3. Production Entry Points and Routes

- **C++**: `nfnext::executeFromBioNetGen(const bng::compile::CompiledModel& model, const BngExecutionRequest& request)`
- **Architectural Executable**: `tests/architecture_contracts/bng3_nfnext_execution_boundary`
- **Python API**: `bionetgen.load(...).simulate(method="nfnext", ...)` / `_bionetgen_cpp.simulate_nfnext`

Trajectories executed through `method="nfnext"` remain strictly on the NFnext engine from initial state through final observable collection.
