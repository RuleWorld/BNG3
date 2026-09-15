# Convergence continuation — 2026-09-14

## Baseline

This continuation targets public `RuleWorld/BNG3` `main` commit
`452f13ff4aeb7a4bba6c5ac4c72a0e0d52101978`.

PR #10's final head was `ed4c59e028b2799a7b8025a8b37dccdc1dec0888`.
The public repository comparison shows that the only source-file change between
that head and the baseline above is PR #11's `python/bionetgen/scan.py`
DataFrame optimization. No continuation change in this note reverts that work.

The GitHub integration available to this execution environment could read the
current repository and exact commits but returned HTTP 403 when asked to create
a continuation branch. The implementation is therefore packaged as a
commit-ready overlay/patch against the exact public baseline rather than being
represented as a pushed SHA.

## Checklist work implemented

### Direct NFsim evidence is now fail-closed

The migration shadow test used to force XML for its first run, then remove only
`BNG_NFSIM_FORCE_XML` before the nominal direct run. Because
`BNG_NFSIM_ALLOW_XML_FALLBACK=1` remained set, a broken direct constructor could
silently fall back to XML and make the comparison XML-vs-XML.

The continuation:

- preserves NFsim `construction_path` metadata in `SimResult` and the parity
  harness trajectory;
- clears XML fallback permission before the direct leg;
- requires the XML leg to report `in-memory-xml` and the direct leg to report
  `direct`;
- anchors the repository `python/` directory for spawned source-tree ensemble
  workers;
- treats a Python import without the compiled backend as unavailable instead of
  a runnable API;
- makes required BNG2 NET/ODE/expression references fail closed in strict CI;
- extends hosted independent NFsim parity to the existing exact fixed-seed
  `motor` and `tlbr` endpoint contracts, in addition to the 200-seed
  `simple_system` ensemble; the ensemble runner itself now requires every BNG3
  member to report `construction_path=direct`.

This strengthens checklist §5.2/§5.3 evidence without changing simulation
semantics or retiring the XML comparator.

### First typed Lean / production NFIR bridge

The formal worked example and a new production-boundary C++ contract use the
same rule:

```text
A(x~u) + B(y) -> A(x~p!1).B(y!1) k
```

`formal/lean/BNG/Examples.lean` now checks the proof-friendly typed NFnext
lowering for two distinct reactants, the state update, and the new bond. The C++
contract independently crosses:

```text
BNGL parser -> bng::compile::CompiledModel -> nfnext::lowerFromBioNetGen
```

and checks the corresponding `DifferentComplex`, state predicate,
`SetSiteState`, and `Bind` representation.

This is deliberately a small checklist §4/NFnext correspondence slice. It does
not establish complete NFnext backend equivalence.

### Population maps remain governed, not guessed

Population maps are intentionally fail-closed for direct NFsim in the current
capability contract and are routed to the hybrid population backend. This
continuation does not invent direct-NFsim population semantics merely to make a
checklist row look fuller. Such support should be added only with an explicit
semantic contract and independent oracle fixture.

## Reproduced local evidence

- Focused result/NFsim-harness subset: `19 passed, 6 skipped, 6 deselected`.
  The skips require a compiled API/native NFsim not present in this source-only
  environment.
- NET/ODE/expression harness subset: `19 passed, 120 skipped`; skips are
  backend/oracle availability conditions here.
- `formal/lean/scripts/validate_all.sh`:
  - static validation: 36 Lean files passed;
  - NFnext header contract: passed;
  - NFnext runtime contract: 18/18 passed;
  - Lean kernel check: skipped because `lake` is not installed in this runtime.
- A clean CMake configure was attempted, but dependency acquisition failed while
  fetching ANTLR because the execution container has no outbound GitHub DNS.
  Therefore the new C++ bridge must still pass the normal hosted C++ matrix
  before it counts as exact-head completion evidence.

## Next checklist slices

1. Expand Tier-NF from the current four-model core toward the locked supported
   NFsim corpus, adding fixed-seed and distributional evidence rather than
   tolerating skips.
2. Add further typed Lean/C++ lowering bridges for deletion, reversible rules,
   local/dynamic rate expressions once NFIR carries those semantics, and
   fail-closed unsupported constructs.
3. Expand Tier-P BNG2 network parity over the approved corpus and eliminate
   environment skips only when a real independent oracle is available.
4. Keep NFnext contracts as reference/future contracts until execution-level
   backend equivalence exists; do not promote architecture tests into a release
   claim.
5. Run the pinned Lean 4.33.1 kernel job, full C++/ASan matrix, Python suite,
   oracle parity, package smoke, and provenance gates on the eventual pushed
   continuation SHA.
