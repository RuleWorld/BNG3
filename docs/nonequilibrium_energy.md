# Nonequilibrium energy: barrier patterns and driving reservoirs

Status: **experimental**, gated off by default.

This describes two extensions to eBNGL that go beyond what canonical NFsim
implements: transition-state (barrier) contributions, and reversible rules
annotated with signed chemical work from a driving reservoir.

## Surface syntax

```
begin barrier patterns
  A(s~U) -> A(s~P) Gbar
end barrier patterns

begin reaction rules
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea) driven_by(muATP)
end reaction rules
```

## Semantics

```
k_f = exp[-(Ea + B + phi       * (dG - W)) / RT]
k_r = exp[-(Ea + B + (phi - 1) * (dG - W)) / RT]
```

- `B` is the summed barrier contribution matched to the rule's reaction center.
- `W` is the signed reservoir work.
- `dG` is the ground-state free energy change from the energy patterns.

Two consequences define the feature and are what the tests pin down:

- `B` cancels in `k_f / k_r`. A barrier changes kinetics without changing local
  detailed balance — it models a catalyst or a kinetic obstruction, not a
  thermodynamic driving force.
- `k_f / k_r = exp[-(dG - W) / RT]`. Reservoir work shifts local detailed
  balance, so a cycle containing a driven edge can carry nonzero affinity and
  the model is no longer equilibrium-compatible.

With `B = W = 0` both expressions reduce to the original eBNGL forms, so
existing models produce byte-identical rates.

## Why a barrier is not an energy pattern

A barrier is keyed by **reaction center**, not by species pattern, and is
symmetric under reversal: both traversals of a transition cross the same
transition state. It is added to the activation energy, never to an
`EnergyDeltaPlan` or any ground-state energy. Folding a barrier into
`ListOfEnergyPatterns` would change the model's detailed balance, which is why
XML serialization keeps `ListOfBarrierPatterns` as a separate section.

Canonical keys, produced by `compile::energy::ReactionCenterKey`:

```
bond:<type>.<site>|<type>.<site>
state:<type>.<comp>~<state>|<type>.<comp>~<state>
```

Both halves are stored in sorted order, which is what makes reversal symmetry
fall out of the key rather than out of caller discipline.

## Architecture

| Layer | Unit |
| --- | --- |
| Surface syntax | `parser/ThermoSourceNormalization.{hpp,cpp}` |
| AST | `ast/BarrierPattern.{hpp,cpp}`, `ReactionRule` driving work |
| Reaction-center keying | `compile/energy/BarrierTable.{hpp,cpp}` |
| AST lowering | `compile/energy/BarrierCompiler.{hpp,cpp}` |
| Shared rate math + gate | `compile/energy/DrivenEnergy.{hpp,cpp}` |
| Cycle/gauge analysis | `compile/energy/ThermodynamicConstraints.{hpp,cpp}` |
| Compiled IR | `CompiledBarrierFactor`, `CompiledRule::drivingWorkValue()` |
| NFsim | `EnergyFunction` barrier table + `drivingWork` expansion parameters |
| Serialization | `XmlWriter::writeBarrierPatterns`, `RateLaw@drivingWork` |
| BNGL round-trip | `BnglWriter::writeBarrierPatterns`, `driven_by()` on rule lines |
| Symbols | `SymbolKind::BarrierPattern` |
| Python IR | `barrier_patterns` section, `driving_work` on rules (`bngir.py`) |

`begin barrier patterns` is rewritten before ANTLR into a reaction rules block
whose entries carry the synthetic label `__bng3_barrier_<N>`, so the generated
parser does not have to be regenerated. A barrier transition is therefore
backed by an ordinary `ReactionRule`, which lets the existing graph-diff
machinery derive the reaction center instead of needing a second transition
detector. A post-parse pass moves those rules into the model's barrier patterns
and renumbers the surviving rules, so the resulting model is indistinguishable
from one written without a barrier block.

`driven_by(W)` is stripped from the rule line and re-emitted through the
existing synthetic `setOption` channel, indexed over ordinary (non-barrier)
rules in source order. Indexing over ordinary rules only is what makes the
annotation independent of where the barrier block was placed.

The post-parse lowering runs in `parseModelSource`
(`cpp/parser/BNGAstVisitor.cpp`), which is the single parse pipeline every
entry point uses: `parseModel`, `parseModelFromFile` (the CLI and the
`include`/`include_files` actions), and the Python `parse_file` /
`parse_string` bindings. Before that consolidation the bindings drove
`BNGAstVisitor` themselves and skipped the post-parse pass, so a model using
either construct parsed cleanly through `python/bionetgen` and lost it.

### Two RT conventions

The NFsim path divides by an explicit `RT`, and both directions take the
**forward** `dG` and the **forward** `W`; the direction enters only through
`phi` versus `phi - 1`.

The network path (`NetWriter`) folds RT into the parameters and builds the
reverse direction as its own reaction, whose `dG` is already negated because its
reactants and products are swapped. `W` must therefore be negated explicitly
there. `B` is direction-independent in both paths and is never negated.

This asymmetry is the most likely source of a silent sign error and deserves a
differential test against an independent oracle before the gate is relaxed.

## What is gated and why

`BNG_NFSIM_GENERAL_ENERGY` must be set for any backend to accept these
constructs. Unset (or `0`) means `Feature::BarrierPatterns` and
`Feature::DrivenReservoirs` report `Unsupported` for both the network compiler
and NFsim.

The gate exists because **no independent oracle exists for these semantics**.
Canonical NFsim and BNG2 do not implement barrier patterns or reservoir work, so
the usual differential-parity evidence cannot be produced yet. Until it can, the
features stay opt-in.

## Fail-closed behavior

The following are rejected rather than approximated:

- a barrier transition that is not exactly one state change or bond change
  (compound rewrites, molecule creation/deletion, no-op transitions);
- a barrier state transition without explicit source and target states;
- a barrier or reservoir-work expression that is not statically evaluable (a
  time- or observable-dependent value would change the cycle affinity during a
  trajectory);
- `driven_by()` on a rule whose rate law is not Arrhenius (there is no `dG` to
  shift);
- barrier patterns declared without energy patterns (there is no Arrhenius
  expansion for the barrier to modify);
- a non-finite barrier or work value;
- more than one `driven_by()` on a rule, or a malformed annotation;
- a malformed or non-canonical `reactionCenter` key in serialized XML.

## Compact path versus materialized expansion

Reservoir work **disables** the compact `EnergyRxnClass` evaluator: the work
factor is `exp(phi*W/RT)` forward and `exp((phi-1)*W/RT)` reverse, so folding it
into the DOR base rate is direction-dependent and not yet independently
validated. Driven rules therefore take the materialized Sekar expansion, which
computes the full `k_f`/`k_r` inside `expandBindingRule` and is correct by
construction.

A barrier does **not** disable the compact path. It is direction-independent
and context-independent, so `exp(-(Ea0 + B)/RT)` is exactly the compact base
rate with the barrier applied, and it never interacts with the context `dG` the
compact evaluator supplies. The equality
`base * context == drivenArrheniusRate(...)` is asserted directly, and with
`B = 0` the folded base rate is bit-identical to the previous expression, so
barrier-only models keep the optimization.

## Round-trip and export behavior

- **BNGL** (`BnglWriter`): emits `begin energy patterns`, then
  `begin barrier patterns`, then rules with `driven_by(...)` appended after the
  rate law — exactly where the normalizer strips it from. The text contract
  between writer and normalizer is asserted by a round-trip test. Energy
  patterns were previously not emitted at all; that is fixed here because a
  barrier block is only legal in a model that also has energy patterns.
- **XML** (`XmlWriter`): `<ListOfBarrierPatterns>` with a canonical
  `reactionCenter` attribute produced by the same `compileBarrierCenter()` the
  native backends use, plus `drivingWork` on the Arrhenius `RateLaw`. Work is
  propagated to a synthesized reverse rule even though the currently-legal
  bidirectional Arrhenius form does not reach that branch.
- **Python IR** (`bngir.py`): a `barrier_patterns` section and `driving_work`
  on each rule, with `barrier_patterns` and `driven_reservoirs` feature flags,
  in both the v0.1 and v0.2 emitters.
- **BNGsim adapter**: rejects barrier patterns and driven rules explicitly. A
  driven rule can reach it without energy patterns, and dropping the work would
  turn a nonequilibrium model into an equilibrium one with no diagnostic.
- **Other kinetics exporters** (SBML, SBML-multi, MATLAB, LaTeX, MCell MDL,
  SSC, C++, Python, MEX): refuse the model via
  `io::requireNoEnergySemantics()`. See below.

## Why the other exporters fail closed

A generated reaction network stores `Arrhenius(phi, Ea)` as the rate law text of
every energy-derived reaction. Only `NetWriter` resolves those into numeric
per-reaction rate parameters; no other exporter does. An exporter that copies
the rate law therefore emits either a literal `Arrhenius(...)` call the target
language has never heard of, or output that silently omits the energy
contribution. Neither reproduces the source kinetics.

`cpp/io/EnergyExportGuard.{hpp,cpp}` refuses such a model, naming the format and
the offending construct. It rejects on any of:

- barrier patterns,
- `driven_by()` reservoir work (reported with the rule name),
- energy patterns,
- an Arrhenius rate law on any rule.

The Arrhenius check is deliberately independent of the energy-pattern check: a
rule can carry an Arrhenius rate law in a model whose energy patterns were
dropped or were never present, and that rule is still inexpressible. Detection
is case-insensitive and covers the reverse rate slot, matching what
`NetWriter::parseArrhenius` accepts.

Constructs are reported most-specific-first, so a model with both barrier and
energy patterns names the barrier patterns — the thing the user actually wrote.

**Structural and visualization writers are deliberately not guarded**: contact
maps, regulatory/influence/process graphs and rule visualization legitimately
ignore rate laws, so omitting an energy annotation does not misrepresent what
they claim to show. `.net`, BNGL and XML output are also unguarded, because
those formats do carry the energy semantics.

No model in `models/` or `tests/energy/fixtures/` uses both energy semantics and
one of the guarded exporters, so this change admits no previously-passing
export.

## Validation state

All components listed in the architecture table above — including
`cpp/parser/BNGAstVisitor.cpp`, `cpp/compile/energy/BarrierCompiler.cpp`,
`cpp/io/NetWriter.cpp`, `cpp/io/EnergyExportGuard.cpp`,
`cpp/nfsim/NFinput/NFinput.cpp`,
`cpp/nfsim/NFinput/NFinput_reactions_fromCompiled.cpp`, and the Python
bindings / `bngir.py` — are built, linked into `bng_cpp` and the Python
extension, and tested in the default CMake/CTest and CI builds (BNG3 uses its
shared expression engine rather than ExprTk).

### Wired C++ contract and unit tests (`tests/energy/`)

`CMakeLists.txt` includes `tests/energy/` by default, registering
`test_energy_compiler_contracts` (`energy::` CTest prefix),
`test_energy_compiler_original` (`energy-original::` prefix), and
`energy_validation_harness` (`tests/energy/tests/python`), in addition to the
compiler-only `tests/energy/standalone/run_checks.sh` checks. The promoted
default C++ test sources (`tests/energy/cmake/energy_tests.cmake`) execute
against the real ANTLR parser, AST, compiled model, and writers:

- real BNGL parsing of `begin barrier patterns` and `driven_by()`, barrier
  removal from the ordinary rule list, rule renumbering, and label preservation
  (`tests/energy/tests/cpp/future_barrier_driving_syntax.cpp`);
- surface-syntax normalization, comment/identifier-boundary safety, nested-paren
  work expressions, continuation-line numbering, and `BnglWriter` round-trip
  (`tests/energy/tests/cpp/test_thermo_source_normalization.cpp`);
- post-parse lowering in `ThermoModelFinalize`, cross-convention equivalence
  between `networkArrheniusRate` and `drivenArrheniusRate`, reverse-direction
  work negation, and all fail-closed paths
  (`tests/energy/tests/cpp/test_thermo_model_finalize.cpp`);
- `BarrierTable` reversal symmetry, canonical reaction-center key round-trip
  and malformed-key rejection, `BarrierCompiler` reaction-center extraction,
  compact-path barrier folding, and `drivenArrheniusRate`
  (`tests/energy/tests/cpp/test_barrier_and_driven_energy.cpp`);
- cycle rank, gauge degrees of freedom, cycle affinity, state-potential
  reconstruction, insertion-order determinism, and equilibrium compatibility
  (`tests/energy/tests/cpp/future_thermodynamic_constraints.cpp`);
- fail-closed kinetics export guards in `io::requireNoEnergySemantics()`
  (`tests/energy/tests/cpp/test_energy_export_guard.cpp`).

### Independent release qualification (`tests/validation/release/cases/issue-177/`)

Issue [#177](https://github.com/RuleWorld/BNG3/issues/177) qualified both
inventory rows (`energy.barriers` and `energy.reservoirs`; merged in PR #651,
commit `1a20420e`, and executed in `.github/workflows/ci.yml` under
*Validate independent issue-177 barrier and reservoir energy laws*, passing in
hosted CI run `45812432339` at `90832910`):

- **`release-barrier-energy`** (`tests/validation/release/cases/issue-177/test_barrier_energy.py`):
  verifies analytic forward/reverse Arrhenius rates in generated `.net` output,
  exact barrier cancellation in `k_f / k_r`, detailed-balance cycle identities,
  catalytic (`B < 0`) vs. obstructive (`B > 0`) kinetics, reversal symmetry,
  direct NFsim execution with barriers, gate-disabled fail-closed refusal,
  invalid declaration rejection, and negative mutation controls.
- **`release-reservoir-energy`** (`tests/validation/release/cases/issue-177/test_reservoir_energy.py`):
  verifies shifted detailed balance under driving work, cycle affinity
  `sum(W_e)`, end-to-end nonequilibrium steady-state (NESS) distributions and
  nonzero steady-state cycle current against independent Matrix Tree /
  King-Altman analytic laws, driven protocol monotonicity, direct NFsim
  execution, fail-closed gate/export guards, malformed annotation rejection,
  and negative mutation controls.
- **`release-capability-coverage-177`**: verifies full coverage of the
  assigned `energy.barriers` and `energy.reservoirs` capability rows.

### Opt-in boundary and remaining scope

`BNG_NFSIM_GENERAL_ENERGY=1` remains **opt-in (gated off by default)**. No
external simulator (neither canonical BNG2 nor canonical NFsim) implements
barrier patterns or driving reservoirs, so cross-simulator differential parity
against an independent external engine cannot be produced; current
qualification relies on independently derived analytic thermodynamic/kinetic
laws and internal cross-path checks. In addition, the optional
`BNG_ENABLE_FUTURE_ENERGY_CONTRACTS` CMake target in
`tests/energy/cmake/energy_tests.cmake` (which holds legacy handoff contracts
such as `future_direct_xml_energy_parity.cpp` and
`future_energy_serialization_roundtrip.cpp`) remains off by default.

To run the C++ energy contract suite locally in a configured build:

```bash
cmake -B build -G Ninja && cmake --build build && ctest --test-dir build -R "^energy" --output-on-failure
```
