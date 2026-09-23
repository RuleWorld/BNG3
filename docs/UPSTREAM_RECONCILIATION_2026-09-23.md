# Upstream source reconciliation — 2026-09-23

This record reconciles the three live RuleWorld source heads observed with
`gh` on 2026-09-23 against the revisions previously recorded in
[`../provenance/upstreams.lock.yml`](../provenance/upstreams.lock.yml). The
per-commit ledgers are the detailed record:

- [BioNetGen](../provenance/reconciliation/bionetgen.yml): 29 commits from
  `e0a5c6d9` through `9601746f`.
- [NFsim](../provenance/reconciliation/nfsim.yml): 4 commits from
  `a6f9fa94` through `9b00d42f`.
- [PyBioNetGen](../provenance/reconciliation/pybionetgen.yml): 2 commits from
  `43b09a53` through `28bf351a`.

The recorded revisions are observed snapshots and proposed reconciliation
cutoffs. They are **not approved import cutoffs**. The baseline remains
`pending-maintainer-approval`; owners, oracle recipes and artifact digests,
compiler image digests, and the Python lock-file digest remain open.

## Ported or already represented behavior

The source changes applicable to the BNG3 runtime were reconciled as follows:

- The retained Perl compatibility engine now handles recoverable rejection of
  products with invalid compartment bonds and accepts an energy-normalization
  variable shared across all energy patterns in an Arrhenius activation-energy
  expression.
- Related BNG2 legacy fixes were ported in `legacy/perl/Perl2/`: expression
  argument/dependency traversal, safe unary dispatch and serialization,
  compartment completeness and adjacency checks, canonical reaction labels,
  Fixed-reactant deprecation warning, scan output without a header, child
  process exit reporting, strict macro-file input handling, and TotalRate and
  generated MATLAB export corrections.
- The hybrid validation XML reference now escapes its `>` relation.
- PyBioNetGen's explicit `packaging` dependency is declared in `pyproject.toml`,
  matching BNG3's existing `packaging.version` import.
- The newer native BioNetGen issue fixes are already represented in BNG3's
  graph canonicalization, reaction-product validation, and CLI action error
  paths. The NFsim issue fixes are also represented in BNG3's native path,
  including absolute start time, time-function dependencies, observable-driven
  propensity refresh, unsupported TotalRate rejection, and separate complex
  bookkeeping and binding-guard flags.
- BNG3 already has its own isolated scan execution and simulation/trajectory
  contracts. Those implementations remain BNG3-native rather than copied from
  the source repositories.

These are source-level dispositions, not a claim of full cross-repository
parity. The ledgers intentionally contain no test-run claims for this pass;
the `tests` lists are empty. Current hosted status and release qualification
must be established separately on the exact pushed BNG3 commit.

## Source-specific changes not transplanted

The remaining commits are explicitly classified in their ledgers. They are
source-repository merge bookkeeping, issue-triage or release notes, Sphinx /
ReadTheDocs tutorial navigation and teaching content, generated BNG2 network
and trajectory references, or citation/recent-model website workflows. BNG3
does not share those site and workflow structures, and BNG2-generated
`.net`/`.cdat`/`.gdat` files are not adopted as independent BNG3 oracle
evidence. This leaves the new upstream JAK-STAT, LAT, TASEP, cooperative-energy,
and transport/local-function teaching materials available for a separate
documentation-port decision; it does not imply that BNG3's runtime lacks those
features.

The source issue-triage commit also includes behavior that BNG3 intentionally
keeps fail-closed where semantics are unsupported. In particular, this update
does not weaken BNG3's unsupported-function handling to match a permissive
legacy stub.

## Validation and approval boundary

This pass checks source revisions, reconciles the listed commit ranges, and
updates the code and provenance records. It does not run test suites or claim
that the complete BNG3 convergence checklist has been re-audited. The
provenance schema validator, frozen corpus manifest validation and
regeneration, Perl syntax checks, and whitespace checks are recorded with the
resulting commits. Maintainers still need to assign ledger owners, accept or
adjust the source cutoffs, and approve the oracle/build recipes before the
source lock can become an approved baseline.
