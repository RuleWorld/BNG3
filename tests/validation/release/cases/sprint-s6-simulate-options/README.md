# S6: `action.simulate` option cases

This case family reads its option contract from pinned BNG2
`RuleWorld/bionetgen@9601746f8884ed19ab2acea49fe87fc4660ace46` and executes the
BNG3 `bng_cpp` action consumer. The authored `A -> B` source has the independent
law `A(t)=10e^(-0.4t)`, `B(t)=10-A(t)`. ODE outputs use a fixed absolute error
bound of `1e-6`; schedule checks use `1e-12`. The SSA slice verifies method
selection, output times, integer populations and conserved `A+B=10` only. It
does not claim stochastic distribution or pathwise equivalence.

Run all eight row selectors in strict-oracle mode:

```sh
BNG3_CI_STRICT_ORACLES=1 \
BNG2_PERL=/path/to/locked/bionetgen/bng2/BNG2.pl \
BNGPATH=/path/to/locked/bionetgen/bng2 \
python -m pytest -c tests/validation/pytest.ini \
  tests/validation/release/cases/sprint-s6-simulate-options/test_simulate_options.py \
  --bng-cpp /path/to/bng_cpp -q
```

Each row has a separate selector named
`test_simulate_option_contract[action.simulate.<option>]`. Select one row by
appending its parameter ID after the test name. Each execution records its
source and product revisions, executable and output digests, scenario source
digests, trajectory values, and current verdict as JSON under
`S6_RECEIPT_DIR` (defaults to the S6 outbox). A missing oracle fails strict
collection; it cannot yield a passing or cached result.

Current case scope is one conversion model, default/explicit/invalid/interaction
inputs for each selected option, and the ODE/SSA method pair. It does not cover
other methods, stiff or large systems, dynamic parameter changes, delays,
non-unit compartments, Python API equivalence, or installed-package behavior.
The matrix rows remain `missing` until their full declared contract passes on
`main`. A source acceptance check and successful case collection do not by
themselves make a row supported.
