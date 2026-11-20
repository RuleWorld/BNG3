# Issue 154: Lossless BNGIR Round Trips & Version Migration

This directory defines the release case contract and qualification checks for [Issue #154](https://github.com/RuleWorld/BNG3/issues/154).

## Goal and Decisions

Issue #154 qualifies lossless BNGIR round trips for the complete BNGL construct inventory:
- `release-bngir-roundtrip`: Every construct family (parameters, parameter dependencies, molecule types, compartments, seed species, observables, functions, energy patterns, barrier patterns, population maps, rules, delayed rules, modifiers, actions) preserves source facts and downstream execution.
- `release-bngir-version`: BNGIR v0.2 represents every v0.1 field plus the complete new schema with no data loss across bidirectional migration.
- `release-obligation-154`: Compares implementation/configuration with the recorded contract and executes negative adversarial fixtures to ensure explicit error handling.

## Running the Acceptance Suite

```sh
PYTHONPATH=python:build/cpp python3 -m pytest -q \
  tests/validation/release/cases/issue-154/test_bngir_roundtrip_release.py
```
