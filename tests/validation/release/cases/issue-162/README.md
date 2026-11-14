# Issue 162: Curated BioModels Source Qualification

This directory defines the release case contract and qualification checks for [Issue #162](https://github.com/RuleWorld/BNG3/issues/162).

## Goal and Decisions

Issue #162 qualifies the curated BioModels corpus across both flat and atomized modes:
- `release-biomodels`: Revision-locked curated BioModels inventory produces per-model flat and atomized source comparisons against independent simulation oracles.
- `release-biomodels-triage`: Fail-closed triage categorizes records cleanly into passed, unsupported, failed, timeout, and not-comparable, ensuring source solver errors have independent documented diagnoses.
- `release-obligation-162`: Verifies exact-revision release contracts, inventory rows, and obligations against `provenance/capability-matrix.yml` and `provenance/issue-obligations.json`.

## Running the Acceptance Suite

```sh
PYTHONPATH=python:build/cpp python3 -m pytest -q \
  tests/validation/release/cases/issue-162/test_biomodels_release.py
```
