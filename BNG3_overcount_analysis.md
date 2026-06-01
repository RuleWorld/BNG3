# Over-count root cause — analysis and experiment

`blbr` emits +26 reactions vs Perl BNG2; `Motivating_example_cBNGL` +2. This is
the gate WO-1 must clear. This note is the evidence, a decision tree that pins
the cause to one of two files, and the exact experiment to run once the engine
builds. It is reasoning from the source, not a verified fix — the fix needs the
oracle.

## What "over-count" means mechanically

`RxnList::add` (cpp/ast/RxnList.cpp) deduplicates by a signature:

```
sorted(reactant species strings) "->" sorted(product species strings) "@" rateLaw ["#" originRuleName]
```

Reactants/products are species **indices** into the SpeciesList, stringified.
Two reactions merge (one row, summed statistical factor) iff their signatures
are equal. **Too many reactions = failed merges**: reactions that should share a
signature don't. There are exactly two ways a signature can differ when it
shouldn't:

1. **Species identity** — the same physical species received two different
   canonical labels, so it became two SpeciesList entries with different
   indices, so reactions referencing it get different reactant/product fields.
   Origin: `SpeciesGraph::canonicalLabel()` (cpp/ast/SpeciesGraph.cpp) →
   `HNauty` (cpp/core/HNauty.hpp).

2. **Rule-name disambiguator** — the `#originRuleName` suffix differs for
   reactions that Perl considers the same rule. Perl "never merges reactions
   from different rules"; if BNG3 attaches an over-specific origin name (a rule
   instance index, or a per-symmetry-variant suffix) the suffix splits a merge.
   Origin: `reactionSignature` in cpp/ast/RxnList.cpp + wherever
   `originRuleName` is assigned during rule application.

Both manifest identically as a reaction-count surplus; they are distinguished by
inspecting the surplus reactions (below).

## Why symmetry-heavy models

`blbr` = bivalent ligand, bivalent receptor: large symmetric aggregates.
`cBNGL` = compartmental, with symmetric placements. Canonical labeling of a
graph with non-trivial automorphisms is exactly where a labeler can return
inconsistent results for isomorphic inputs. The surplus being concentrated in
these two models points first at **cause 1** (canonicalization of symmetric
species), with **cause 2** as the alternative the experiment rules in or out.

## Direct evidence in the code

`cpp/core/HNauty.hpp` is a hand-port of the Perl HNauty.pm canonical-labeling
algorithm, and it carries an unresolved comment about the core comparison
direction (around the terminal-node update, ~line 620–640):

> "The algorithm picks the LARGEST canonical form? No, typically nauty picks the
> lexicographically smallest. … Let's just faithfully replicate."

A canonical labeler that is unsure whether it selects the min or max
representative, and whose automorphism bookkeeping was ported by hand, is a
credible source of inconsistent labels for automorphic graphs. The earlier
`reactionCenterSignature` fix (`canonicalNodeId` → `reinterpret_cast<…>`) was an
adjacent correctness fix in the same labeling machinery; this is the remaining
piece.

A second thing to confirm: that `SpeciesLabel = HNauty` is actually in force for
these models. If any species takes a non-HNauty labeling fallback, isomorphic
species can diverge for that reason alone.

## The experiment (run once bng_cpp builds)

The harness already isolates the surplus. `compare.compare_net` keys reactions
by species *string*, and `NetDiff.summary()` prints "reactions only in test" —
those are the un-merged surplus, named.

```bash
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build
python scripts/regen_golden.py --models blbr Motivating_example_cBNGL   # Perl oracle .net
pytest tests/validation/test_parity_net.py -k blbr -rA                  # prints the 26 surplus reactions
```

Then decide:

1. **Read the surplus reactions' species strings.**
   - If two surplus reactions are identical in reactant+product species strings
     and differ only by rate/rule annotation → **cause 2** (RxnList /
     originRuleName). Fix in cpp/ast/RxnList.cpp + origin-name assignment.
   - If surplus reactions reference species strings that look like the same
     molecular graph written two ways → **cause 1** (HNauty). Continue.

2. **Confirm the canonicalization collision directly.** Instrument
   `SpeciesGraph::canonicalLabel()` to log `(adjacency fingerprint, label)` for
   every species generated for `blbr`. Group by a graph-isomorphism check
   (independent of the label). Any group whose members got >1 distinct label is
   a canonicalization failure, and those species are exactly the ones in the
   surplus reactions.

3. **Localize within HNauty.** Re-derive the terminal-node comparison against
   Perl HNauty.pm `lex_ordered` semantics: which representative (min or max) is
   canonical, and that the automorphism generators produced during refinement
   are applied to collapse equivalent labelings. Fix; re-run; the surplus must
   go to zero and `blbr` + `cBNGL` come off `KNOWN_OVERCOUNT`.

## Correction to the v1 spec

The v1 spec folded "make NFsim use the engine canonicalizer" into WO-1. That was
an overgeneralization. The over-count is entirely in **network generation**
(`SpeciesGraph::canonicalLabel` / HNauty); NFsim is network-free and plays no
part. NFsim's nauty usage is a different algorithm layer (complex symmetry during
simulation) and need not share the engine's species-canonicalization logic. What
the two share is only the **raw nauty C library**, which is duplicated as a build
artifact (two compiles of upstream nauty) — a hygiene issue, not a correctness
one. So WO-1 splits cleanly:

- **WO-1a (correctness):** fix `SpeciesGraph::canonicalLabel` / HNauty so
  isomorphic species get one label. Gated by net parity. *Algorithmic — do it
  against the oracle, per the experiment above.*
- **WO-1b (hygiene):** link one nauty C library for both engine and NFsim. See
  cpp/CMakeLists.unify.snippet.cmake. Mechanical, low-risk.

Treating them separately also satisfies the two-round rule: if a "fix" to 1a
doesn't move the count, the surplus inspection in step 1 tells you whether you're
even in the right file (cause 1 vs cause 2) before a second attempt.
