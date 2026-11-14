# Issue #147: Extend NFnext Lowering for Approved Unsupported Semantic Families

## Overview

This package retains the bounded candidate-family checks introduced in #646.
The later #647 implementation adds NFIR v6 fields and preserves modifiers and
filters through compilation, canonicalization, semantic identity and disk cache.
Direct and multiple-observable arithmetic rates have production execution tests.
The earlier six-family lowering refusal table was superseded by those changes.

Representation is not complete execution. Production NFnext still explicitly
refuses compartments, populations, energy, physical units, MatchOnce, TotalRate,
MoveConnected and filters. Time-dependent/local/DOR families also require their
own exact representation/execution evidence. The maintainer decision requires
representation, execution and independent checks for every required family;
passing candidate-boundary/refusal checks cannot close #147. Retain all test IDs
and independent expectations while implementing the missing semantics separately.

## Acceptance Checks

- `release-nfir-lowering`: every network-free inventory row lowers with complete semantics and validated IDs.
- `release-nfir-roundtrip`: independently authored canonical model facts agree with NFIR and native NFsim input facts.
- `release-obligation-147`: each task above has its named check result, source/oracle identity and main commit recorded. Candidate slice labels and successful refusal controls are bounded diagnostic evidence, not completion of the required semantic families.
