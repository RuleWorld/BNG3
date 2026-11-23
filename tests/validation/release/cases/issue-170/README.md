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
network-reconstruction compatibility only; no analysis or theorem result is claimed by this import
check. Set `BNG3_CRN_ARTIFACT_DIR` to retain the CRN JSON, importer payload, consumer output, and
installed package identity receipt.

## Historical analyzer limitation (superseded at the measured revisions)

An earlier note in this file recorded that `lake exe analyze` failed to compile because
`NetworkData.analyze` was noncomputable at the downstream revision originally used for this case.
A later local downstream pilot built and ran the real analyzer successfully on both pilot networks
(`reversible_pair` and `irreversible_chain`, each `rc=0`) at these measured revisions:

- BNG3 producer `main`: `676d69cbd46105fd803bc21cd0c46eea950751e8`
- installed wheel: `bionetgen-3.0.0a1-cp314-cp314-macosx_27_0_arm64.whl`
- crnt-lean `master`: `7386777488a41efd92e6abc2bccf889fb611660e`
- Lean `4.34.0`, toolchain `leanprover/lean4:v4.34.0`

For both networks the analyzer fields (deficiency, stoichiometric rank, linkage classes,
complex/reaction counts and the certified flags) agreed with exact rational computations done
independently of BNG3's exported matrix, and corrupted-adapter controls were rejected. This is
local pilot evidence at the pinned revisions above only. It does not close #170, and the CI case
described here still checks import and network reconstruction rather than analyzer output.
