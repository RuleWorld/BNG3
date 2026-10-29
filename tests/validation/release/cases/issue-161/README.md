# Issue 161: authored SBML Multi checks

This directory holds a reduced export-parity input for the unresolved
species/type pooling question. It uses the two-molecule trivalent-ligand and
bivalent-receptor motif from `tests/validation/Validate/test_write_sbml_multi.bngl`,
with two association configurations that share one composite molecule
composition. The check executes the authored `writeSBMLMulti()` action in C++
BNG3 and pinned BNG2 and compares `listOfSpeciesTypes`, `listOfSpecies`, and
`listOfReactions` with the existing structural XML comparator. It does not
generate a reaction network as a separate prerequisite.

Run from the repository root after the CI lane provides a fresh `bng_cpp` and
the pinned `BNG2.pl`:

```sh
python tests/validation/release/cases/issue-161/run_case.py \
  --bng-cpp "$BNG_CPP" \
  --bng2 "$BNG2_PL"
```

`BNG2_PL` must come from the accepted pin in
`provenance/upstreams.lock.yml` (`RuleWorld/bionetgen@9601746f8884ed19ab2acea49fe87fc4660ace46`).
The command writes no report unless `--report` is supplied. The CI workflow
must invoke this script explicitly; files in `release/cases/` are not
discovered automatically.

The runner rejects the result for acceptance if the product checkout is dirty
or the BNG2 checkout does not match the locked, clean upstream revision. Its
report records the product revision and dirty flag, BNG2 revision and dirty
flag, and SHA-256 digests of both executables and each source fixture.

The runner also exports `state_bearing_binding_refusal.bngl`. The pinned BNG2
oracle accepts this source and writes a Multi document with species-feature
values and a binding reaction. The BNG3 export must therefore succeed and pass
the same BNG2 structural comparison; a refusal is a failed acceptance check,
not an expected result.

Source validity was checked with BNG2 from the accepted pin above. Both inputs
completed the authored `writeSBMLMulti()` action with exit status 0. libSBML
read both resulting XML files with zero errors and zero internal-consistency
errors. The reduced binding case emitted 6 species, 4 reactions, and reused
composite species type `ST3` for both bound configurations. The state-bearing
case emitted 3 species and 2 reactions, including state value `u` on the
binding-site molecule. These are source-validity and oracle-export results;
they do not establish current BNG3 parity or successful BNG3 reimport. The
runner requires a fresh native BNG3 export and structural BNG2 comparison.
After export it also reconstructs BNGL through Atomizer and asks the same
fresh BNG3 executable to generate a network. That last stage is a network
generation smoke check; it does not independently establish preserved
reaction kinetics or full Multi semantics.
