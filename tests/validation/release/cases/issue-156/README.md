# Issue 156: BNGIR Lossless Versioning and Exact Semantic Equality

This directory defines the release case contract and qualification checks for [Issue #156](https://github.com/RuleWorld/BNG3/issues/156).

## Goal and Decisions

Issue #156 qualifies BNGIR v0.2 lossless schema defaults and exact process semantic equality:
- `release-bngir-schema`: BNGIR v0.2 covers all BNGL constructs (units, observable kinds, delayed rules, modifiers) and migrates cleanly from v0.1 without loss.
- `release-semantic-equality`: Exact semantic equality passes all certified EQ-* families (renaming, rule splitting, observable patterns, functions, delays) and strictly rejects numerical approximations, raising `EqualityUndecided` when no terminating decision procedure exists.
- `release-capability-coverage-156`: Verifies exact-revision release contracts, inventory rows (`bngir.v02`, `bngir.equality`), and live acceptance obligations.

## Running the Acceptance Suite

```sh
PYTHONPATH=python:build/cpp python3 -m pytest -q \
  tests/validation/release/cases/issue-156/test_bngir_release.py
```
