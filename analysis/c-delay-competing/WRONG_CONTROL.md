# Wrong-implementation control — delayed NonConsuming equality counterexample

The new `test_delayed_semantic_equal_counterexamples` assertion discriminates a
false-equality implementation from the tested product.

## Observed control (pre-fix checkout, stale editable finder)

The local shell has an editable finder pointing at the primary checkout
`32309fb5`, whose `python/bionetgen/bngir.py` sha256 is
`b0748e176530332974b08b354f7c872425667b66fe24895df8d176058284ff07`.

Command (from this worktree, without `-S`, so the stale finder wins):

```
PYTHONPATH="...:/opt/anaconda3/lib/python3.14/site-packages" \
  python3 analysis/c-delay-competing/wrong_control.py
```

Output:

```
bionetgen from /Users/akutuva/Documents/BioNetGen/BNG3/python/bionetgen/__init__.py
tau2 {'undecided': 200}
consuming {'equal': 200}
```

That implementation falsely certifies equality (200/200) when the
`NonConsuming` flag is removed, i.e. when the completion law changes from a
constant-rate Poisson stream to a state-dependent consuming stream. The new
assertion fails there (`assert True is False`). This is why the local
`record_delay_release.py` run without an isolated install fails; with the clean
installed package from this worktree it passes.

## Tested product

Exact worktree revision `5f17ce1b`, `python/bionetgen/bngir.py` sha256
`cb0c9569956d87bbfddf370ed517a702b898424e909d9c9af0f4cb233fec89b4`,
installed in `/private/tmp/bng3-c-venv`: both variants return
`EqualityUndecided` (200/200), so the counterexample test passes. No product
change was made by this slice; the control only demonstrates that the added
check has discriminating power.
