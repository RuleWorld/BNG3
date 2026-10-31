# Issue 170 CRN API & Consumer Acceptance

This acceptance case qualifies the chemical reaction network (CRN) API and its independent consumption contract:
- `release-crn-api`: Hand-derived CRN complexes, reactions, stoichiometric matrix, and structured rate laws.
- `release-crn-consumer`: Independent CRNT consumer loading the public CRN JSON artifact with zero BNG3 internals or private imports.

`test_crn_consumer.py` verifies:
1. Pure standard-library deserialization of `model.write_crn(...)`.
2. Reconstitution of species, complexes, and reaction digraph.
3. Verification of the fundamental algebraic relationship $N = Y \cdot B$, where:
   - $N$ is the species-by-reaction stoichiometric matrix.
   - $Y$ is the species-by-complex stoichiometric matrix.
   - $B$ is the complex-by-reaction incidence matrix.
4. Calculation and verification of the CRNT Deficiency $\delta = m - l - s \ge 0$, where:
   - $m$ is the number of complexes.
   - $l$ is the number of linkage classes (connected components).
   - $s = \text{rank}(N)$ is the dimension of the stoichiometric subspace.
