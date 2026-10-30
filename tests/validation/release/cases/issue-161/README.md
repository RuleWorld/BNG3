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

The pinned BNG2 command accepts both BNGL inputs, but its authored SBML Multi outputs are not valid SBML Multi references. On the recorded run, libSBML found 14 severity errors in the binding fixture and 5 in the state-bearing fixture; diagnostics include component IDs referenced by outward binding sites and component maps that do not resolve to the required Multi objects. The BNG3 outputs pass libSBML with zero severity errors. Strict structural XML comparisons remain failures and are retained as diagnostics; invalid BNG2 XML is not treated as an acceptance oracle.

For these two hashed fixtures, a separate source-authored contract checks the candidate XML against manually derived BNGL semantics: molecule site inventories, exact species patterns, bond endpoints/site ordinals, state values and ownership, reaction component maps and participants, named or literal rates, seed amounts, and the unit-volume compartment. The contract does not use BNG2 XML or candidate parser output to define expected values. If BNG2 XML is invalid and the candidate passes libSBML, the complete source contract, and its negative controls, the fixture may pass on the source contract while the strict comparison is labeled `reference-invalid`. A valid BNG2 document must still pass strict comparison. The raw strict diff remains available in the report. This fallback is limited to these two source-hash-pinned fixtures and is not a general Multi qualification or Issue 161 closure.

The runner also compares bounded networks generated directly from source BNGL by pinned BNG2 and BNG3, then compares the BNG3 network reconstructed from candidate XML with the pinned BNG2 source network. These checks cover species graphs, bonds/states, rates, and initial quantities at the explicitly bounded fixture depth. They do not establish unbounded polymer execution or complete SBML Multi support. Six XML mutation controls exercise whether the structural comparator detects changes to bonds, states, component-map targets, initial quantities, compartment volumes, and rates. When `--report` is supplied, both authored XML files and the source, one-rule, and reimport `.net` files are preserved beside the JSON report so the invalid reference and independent network evidence can be reviewed together.
