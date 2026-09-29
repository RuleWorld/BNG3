# Tier-P divergence: seed site states were bound by discovery order

- Date: 2026-09-29
- Models: `AN`, `ANx`, `ANx_noActivity` (`build/validation/direct_path_sweep.json` → `diverged_models`)
- Defect: `cpp/nfsim/NFinput/NFinput_fromCompiled.cpp`, seed-species stage (line 875 before the fix)
- Regression test: `tests/validation/test_parity_nfsim.py::test_nf_seed_site_state_is_resolved_by_name`
- Status: **fixed in source, not yet rebuilt.** The prebuilt `build/cpp/bng_cpp` in this
  working tree still contains the defect, so the failing test output quoted below is
  pre-fix by construction.

## Reproduction (measured, not inherited)

`ANx` (`models/ANx.bngl`), `t_end=0.1`, `n_steps=10`, seed 7, both legs in one process.
Final observable values (`R0..R8` declared as `Molecules Rk RD(m~k)`; the seed is
`RD(...,m~2) 370` clusters, so the whole 6660-dimer pool starts in state 2):

| observable | direct | in-memory-XML |
| --- | --- | --- |
| `R0` (`RD(m~0)`) | **6656** | 0 |
| `R1` (`RD(m~1)`) | 4 | 9 |
| `R2` (`RD(m~2)`) | **0** | **6648** |
| `R3` | 0 | 3 |
| `R4`–`R8` | 0 | 0 |
| `RDtot` (`RD()`) | 6660 | 6660 |
| `RD_R`, `RD_B` | 437, 418 | 429, 426 |

Two facts fall out, and they matter separately:

1. The direct leg reports the **seed pool** under `R0`. It is not that `R0` is bound to
   the wrong observable template — `R0 RD(m~0)` is correctly bound to state `'0'` — it is
   that **every seed molecule was created in state 0** instead of state 2. `RD_R` and
   `RD_B` diverge too, and they are pure stoichiometry, because `MethLevel` reads that
   same wrong state when it sets the catalytic rates. The dynamics diverge because the
   *initial conditions* are wrong, not because an observable was mislabelled.
2. The columns are not a permutation. `R1`/`R3` and `RD_R`/`RD_B` differ in the last
   digits, which a pure relabelling cannot produce.

> **Correction to `docs/TIER_P_DIRECT_PATH_SWEEP.md:67-73`.** That note says the direct
> leg "returns the unmethylated count (6660) under `R0`" and that the columns are
> "permuted among the names". Both are wrong for the reason above: 6660 is the state-2
> seed pool, not the unmethylated count (the unmethylated count is 0 in both legs), and
> the series are not permuted. The conclusion it drew — the direct path is behaviourally
> wrong and the XML path is right — stands; the evidence given for it does not.

## The line

`cpp/nfsim/NFinput/NFinput_fromCompiled.cpp:873-875`, in the seed-species stage
(`addSpeciesFromCompiledWithOverrides`, called as builder stage 8 at
`NFinput_fromAst.cpp:5988-5990`):

```cpp
concrete->setComponentState(
    runtimeName,
    static_cast<int>(site.stateConstraintResolved.exact->index));
```

`PatternStateConstraint::exact` is a `StateId`, and its `index` is defined in
`cpp/compile/PatternDescriptor.cpp:467-469` as an offset into **the atomizer's
declaration/discovery order** of `component.allowedStates`:

```cpp
site.stateConstraintResolved.exact = StateId{
    componentId, static_cast<std::size_t>(
                     std::distance(component->allowedStates.begin(), state))};
```

NFsim's state value is a *different* offset: an index into the molecule type's own
`possibleCompStates`. For a component whose states are all integers, both
`addMoleculeTypesFromCompiled` (`NFinput_fromCompiled.cpp:590-593`) and the XML loader
(`NFinput.cpp:585-591`) **renumber** that table to `0..max` in ascending numeric order.
The two index spaces coincide only when the model happens to declare its integer states
in ascending order — and nothing requires that. A component mentioned only from patterns
has no declared order at all; `ANx` names `m~2` in its `species` block before any
observable mentions `m~0`, so its allowed states are

```
['2', '0', '1', '3', '4', '5', '6', '7', '8', '?', 'PLUS', 'MINUS']
```

and `'2'` — the seed state — is discovery index **0**. Every one of the 6660 seed
receptors was therefore created in NFsim state 0.

The observable path was never wrong. `lowerPatternToNFsimPermutations`
(`cpp/nfsim/NFcore2/nfsim_pattern_lowering.cpp:468-484`) resolves the state **by name**
through `MoleculeType::getStateValueFromName`, so `R0` really did count state `'0'` — it
just counted a population that had been built in the wrong state.

## Which route is right

**The XML route, and it is not close.** `ANx`'s own declarations make it unambiguous:
`Molecules R0 RD(m~0)` is the unmethylated pool, and the seed is `RD(...,m~2)`, so the
seed pool belongs under `R2` and `R0` must start at 0. The XML leg reports exactly that
(`R2` = 6648, `R0` = 0). The direct leg's answer is only explicable as "everything is
in state 0".

The XML loader is also right by construction rather than by luck: it resolves every
state — seeds (`NFinput.cpp:1001-1009`), products (`:2049-2060`), observables
(`:3692-3759`) — by name through the `allowedStates` map, and that map is filled from
the very same renumbering loop that builds the molecule type (`:588`). So the XML route
computes name → value, and the value it stores is by construction the value NFsim uses.
The direct path had exactly one site doing otherwise; the rest of it already resolved by
name (`NFinput_reactions_fromCompiled.cpp:390-400`, `NFinput_fromCompiled.cpp:1004-1012`).

## The fix

`NFinput_fromCompiled.cpp:871-916` now resolves the `StateId` back to its **name** and
asks the live `MoleculeType` for the value, mirroring the product path:

```cpp
const auto* stateName = model.stateName(*site.stateConstraintResolved.exact);
const int componentIndex = types[moleculeIndex]->getCompIndexFromName(runtimeName);
concrete->setComponentState(
    runtimeName,
    types[moleculeIndex]->getStateValueFromName(componentIndex, *stateName));
```

### Why this is order-independent

The result is a function of exactly one input: the state **name** written in the seed.
`getStateValueFromName` is a linear search of the molecule type's own
`possibleCompStates`, whose contents and order are fixed by the molecule type already
built for this `System` (stage 3) — the same table the XML route's `allowedStates` map
mirrors. The order in which the atomizer happened to discover the state names is no
longer an input to the result at all. `grep` confirms `:875` was the only place in
`cpp/nfsim` that consumed `stateConstraintResolved.exact->index` positionally; every
other consumer already went through `model.stateName(...)`.

### The order-dependence, measured, pre-fix

Two models identical in BNGL semantics and differing only in **block order** — the seed
block first makes `'2'` the first discovered state, the observables block first makes it
the third. Pre-fix, with the prebuilt binary:

| model | `s` allowed_states (atomizer discovery order) | direct `O2` | XML `O2` |
| --- | --- | --- | --- |
| `species` block first | `['2','0','1','3']` | **0** ❌ | 100 ✅ |
| `observables` block first | `['0','1','2','3']` | 100 ✅ | 100 ✅ |

Same model, same observable, two different answers from the direct path depending on a
detail with no semantic content. The XML leg is invariant. That is the regression test:

```sh
python3 -m pytest -c tests/validation/pytest.ini \
  tests/validation/test_parity_nfsim.py -k seed_site_state
```

`observables_first` passes; `species_first` fails on the direct leg with
`seed pool not under O2: {'O0': 100.0, 'O1': 0.0, 'O2': 0.0, 'O3': 0.0, 'Otot': 100.0}`.
Both cases must pass once the rebuilt extension is in place.

## The three models are now a strict xfail

`test_tierp_direct_path_outcome_is_measured_and_attributed` reports the numbers, writes
`build/validation/direct_path_sweep.json`, and then, instead of failing:

- a divergence **not** in `_KNOWN_SEED_STATE_ORDER_DIVERGENCES` fails hard;
- a listed model that **stops** diverging fails hard with "the marker is hiding a
  passing model, remove the name" — this is the `strict=True` behaviour, enforced
  explicitly so it holds regardless of the `xfail_strict` ini setting;
- only then does it `pytest.xfail`.

The report is written before any of that, so an xfail still leaves the full measurement
on disk. A silently-passing divergence is the failure mode this harness is built to
catch, so the marker is not allowed to outlive the bug.

## Not established here

- **The fix is unverified at runtime.** Rebuilding the extension is out of scope for this
  change, so the post-fix numbers above are predicted from the code, not measured. The
  regression test is the thing that has to go green after the rebuild, and it is
  failing-first by design.
- `AN`, `ANx` and `ANx_noActivity` are the AN family, which shares the ANx seed. They
  are listed because the sweep measured exactly those three; the fix is in shared code
  and is expected to clear all three, which the stale-marker check will insist on.
- The other accepted tier-P models are unaffected by this defect: it needs a
  pattern-only component whose discovery order is not ascending, which is why exactly
  three models tripped it.
