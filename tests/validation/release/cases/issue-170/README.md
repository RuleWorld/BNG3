# Issue 170 CRN API & Consumer Acceptance

This acceptance case qualifies the chemical reaction network (CRN) API and its consumption contract:
- `release-crn-api`: Hand-derived CRN complexes, reactions, stoichiometric matrix, and structured rate laws.
- `release-crn-consumer`: the separate `crnt-lean` repository's `NetworkData` JSON decoder and `toNetwork` importer load an adapter derived from the installed package's public CRN JSON artifact.

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

`test_crn_installed_lean_consumer.py` is the downstream integration case. It requires an installed
BNG3 package and `BNG3_SOURCE_REVISION`, `BNG3_CRNT_LEAN_ROOT`, and
`BNG3_CRNT_LEAN_REVISION`; it runs the probe in
`CrntLeanImportProbe.lean` with the real `crnt-lean` checkout as its working directory. The probe
deserializes `NetworkData` and reconstructs its Lean `Network`. This check establishes import and
network-reconstruction compatibility only. The separate `lake exe analyze` executable currently
fails to compile at the recorded downstream revision because `NetworkData.analyze` is noncomputable;
no analysis or theorem result is claimed by this import check. Set `BNG3_CRN_ARTIFACT_DIR` to retain
the CRN JSON, importer payload, consumer output, and installed package identity receipt.
