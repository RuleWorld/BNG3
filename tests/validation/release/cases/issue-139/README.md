# Issue #139: Separate Network-Rule Execution from Reconstructed AST Rules

This directory contains the independent release acceptance suite for **Issue #139** (B02: Separate network-rule execution from reconstructed AST rules).

## Acceptance Checks

- `release-network-rule-plan`: Parser-independent rule execution and independent BNG2 network equality across every assigned rule row.
- `release-network-rule-mutations`: Injected incorrect multiplicity, deletion, and filter mutations strictly fail the independent comparator.
- `release-capability-coverage-139`: Complete independent evaluation of all 19 assigned capability inventory rows and 11 contract obligations against their named independent oracles.

## Covered Capability Inventory Rows

The 19 assigned capability inventory rows for Issue #139:
1. `bngl.matchonce`: Rule-level `MatchOnce` modifier suppresses duplicate symmetric embeddings.
2. `bngl.irreversible-rules`: Standard unidirectional (`->`) reaction rules.
3. `bngl.reversible-rules`: Bidirectional (`<->`) reaction rules lowering to forward and reverse reaction channels.
4. `bngl.null-reactants-and-products`: Zero-order synthesis (`0 -> A()`) and degradation (`A() -> 0`) rules.
5. `bngl.binding`: Intermolecular bond formation (`A(b) + B(a) -> A(b!1).B(a!1)`).
6. `bngl.unbinding`: Bond cleavage rules (`A(b!1).B(a!1) -> A(b) + B(a)`).
7. `bngl.state-changes`: Component state modification (`A(s~0) -> A(s~1)`).
8. `bngl.molecule-creation`: Synthesis creating multi-component species.
9. `bngl.molecule-deletion`: Unimolecular degradation removing species graphs.
10. `bngl.deletemolecules`: `DeleteMolecules` keyword deletes matched molecules and cleaves connected bonds cleanly.
11. `bngl.moveconnected`: `MoveConnected` keyword transports connected cargo molecules across compartments.
12. `bngl.totalrate`: `TotalRate` rate-law scaling modifier on finite-network reaction generation.
13. `bngl.include-reactants`: Reactant filter pattern restricting rule application to matching species.
14. `bngl.exclude-reactants`: Reactant filter pattern excluding matching species from reacting.
15. `bngl.include-products`: Product filter pattern ensuring only matching produced species are retained.
16. `bngl.exclude-products`: Product filter pattern discarding produced species matching the pattern.
17. `bngl.compartment-transport`: Compartment relocation rules (`@C1:A() -> @C2:A()`).
18. `bngl.reaction-center-symmetry`: Homodimerization and symmetric binding factor evaluation (0.5 statistical factor).
19. `bngl.connected-context-preservation`: State modifications and reactions preserving bystander molecules in complexes.

## Executed Contract Slices

1. `network-rule-execution-graph`: Compile-owned species graph transformations (binding, unbinding, state changes, creation, deletion, DeleteMolecules, MoveConnected).
2. `network-rule-execution-rate`: Exact rate-law evaluation, homodimer symmetry factors, and TotalRate handling.
3. `network-rule-execution-filter`: Include and exclude reactant and product filtering.
4. `network-rule-execution-local-scope`: Local observable scopes and local functions.
5. `network-rule-execution-reversible`: Reversible rule expansion into distinct forward and reverse reaction channels.

## Independent Oracles and Negative Controls

1. **Analytical Network Topology & Multiplicities**:
   - Explicit graph isomorphism: species vertices, component states, and edge bonds.
   - Exact reaction stoichiometry and statistical factor calculation (e.g. $0.5$ for homodimerization $A + A \rightarrow A.A$, $1.0$ for MatchOnce).
2. **Pinned BNG2 Network Parity**:
   - Generated `.net` structures match pinned BNG2 bit-for-bit or via structural multiset isomorphism (`compare.compare_net`).
3. **Negative Controls & Mutation Testing**:
   - Injected multiplicity mutants (e.g. factor doubled or halved) are strictly rejected (`diff.ok == False`).
   - Injected deletion mutants (orphan fragments or missing bystander molecules) are strictly rejected.
   - Injected filter mutants (permitting excluded reactants or discarding required products) are strictly rejected.
