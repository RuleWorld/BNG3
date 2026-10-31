# Issue 161: authored SBML Multi checks

This directory holds reduced export-parity inputs for the unresolved species/type pooling question. They cover the two-molecule trivalent-ligand and bivalent-receptor motif and a state-bearing binding case. The check runs the authored `writeSBMLMulti()` action in C++ BNG3 and pinned BNG2, reports strict structural XML differences, validates each output with libSBML, then checks bounded source-network parity and candidate reimport.

Run from the repository root after the CI lane provides a fresh `bng_cpp` and the pinned `BNG2.pl`:

```sh
python tests/validation/release/cases/issue-161/run_case.py \
  --bng-cpp "$BNG_CPP" \
  --bng2 "$BNG2_PL"
```

`BNG2_PL` must come from the accepted pin in `provenance/upstreams.lock.yml` (`RuleWorld/bionetgen@9601746f8884ed19ab2acea49fe87fc4660ace46`). The command writes no report unless `--report` is supplied. The CI workflow invokes this script explicitly; files in `release/cases/` are not discovered automatically.

The runner rejects the result for acceptance if the product checkout is dirty or the BNG2 checkout does not match the locked, clean upstream revision. Its report records both revisions and dirty flags, executable hashes, and source fixture hashes.

The pinned BNG2 command accepts both BNGL inputs, but its authored SBML Multi outputs are not valid SBML Multi references. On the recorded run, libSBML found 14 severity errors in the binding fixture and 5 in the state-bearing fixture; diagnostics include component IDs referenced by outward binding sites and component maps that do not resolve to the required Multi objects. The BNG3 outputs pass libSBML with zero severity errors. Raw strict structural comparisons remain different and their failure counts are retained; an invalid BNG2 XML document is never treated as a pass.

For these two reduced hashed fixtures, a separate source-authored contract checks candidate XML against manually derived BNGL semantics: molecule site inventories, exact species patterns, bond endpoints/site ordinals, state values and ownership, reaction component maps and participants, named or literal rates, seed amounts, and the unit-volume compartment. The contract does not use BNG2 XML or candidate parser output to define expected values. If BNG2 XML is invalid and the candidate passes libSBML, the complete source contract, and its negative controls, the fixture may pass on the source contract while the strict comparison is labeled `reference-invalid`. A valid BNG2 document must still pass strict comparison. The raw strict diff remains available in the report. This fallback is limited to source-hash-pinned fixtures and is not a general Multi qualification or Issue 161 closure.

The broad parity lane applies the same contract to the full authored `tests/validation/Validate/test_write_sbml_multi.bngl` fixture. That full contract checks all authored species patterns and site statuses, the three receptor-ligand bond graphs, all six rule directions and component maps, rate laws and parameters, quantities, and volume. It does not generate the unbounded polymer network. The sidecar JSON retains every strict BNG2/BNG3 structural difference and contract/control result alongside both XML documents.

The runner also compares bounded networks generated directly from source BNGL by pinned BNG2 and BNG3, then compares the BNG3 network reconstructed from candidate XML with the pinned BNG2 source network. These checks cover species graphs, bonds/states, rates, and initial quantities at the explicitly bounded fixture depth. They do not establish unbounded polymer execution or complete SBML Multi support. Six XML mutation controls exercise whether the structural comparator detects changes to bonds, states, component-map targets, initial quantities, compartment volumes, and rates. When `--report` is supplied, both authored XML files and the source, one-rule, and reimport `.net` files are preserved beside the JSON report so the invalid reference and independent network evidence can be reviewed together.

## Independent Core execution oracle (additional, not full qualification)

`stateful_binding.bngl` and `stateful_binding_core.xml` are separately authored, SHA-256-locked sources. They describe five chemical species and six reaction directions: two reversible associations (one for each internal state), free-site state conversion, and bound-complex state conversion on a site that also carries a bond. The Core source independently spells out every reaction and volume-adjusted extent law; it is **not** obtained from the candidate Multi export or BNG3 network generation.

`test_stateful_binding.py` exports SBML Multi from the BNGL source, validates the document with libSBML, reimports with both modern-atomizer settings, simulates native BNG3 ODEs, and compares all five species trajectories and two conservation laws against libRoadRunner executing the independent Core source. It checks both the pinned 0.5-volume fixture and an explicit, identical source transformation to volume 2.0. In CI this is a distinct step of the existing `issue-161` job, with a separate JUnit result.

`test_multi_math_representation.py` separately authors Multi kinetics using a `PossibleSpeciesFeatureValue.numericValue` parameter and a kinetic-law `MultiMath.representationType="numericValue"` species-reference token; `MultiMath.representationType="sum"` on both a state-specific species and an unseeded wildcard species matching two states; two occurrences of the same species-feature type, only one of which changes state; and an equivalent `SubListOfSpeciesFeatures.relation="and"` conjunction. Separately specified SBML Core laws provide the kinetic oracles, with explicit structural checks for repeated sites and wildcard observables. Each document must validate with libSBML, and reimport with either atomization setting must reproduce the corresponding Core trajectory in libRoadRunner. CI executes these ten comparisons as a second independent-oracle step with its own JUnit result.

This establishes a bounded, executable **state-bearing binding and compartment-rate** slice. It does not qualify the remaining SBML Multi capability-matrix rows or replace the exact-main release gates (`release-sbml-multi`, `release-atomizer-structure`, and `release-capability-coverage-161`).

The supplied October 30 patch series modified three stateful-oracle files that were absent at the PR base. Their source models and test were reconstructed from the supplied equations and hunks; their SHA-256 constants identify these reconstructed bytes, rather than claiming recovery of the missing originals. The zero-order Core builder omits empty reactant/product lists as required by SBML. The added oracle checks retain their original numerical tolerances.
